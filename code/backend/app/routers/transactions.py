"""Transactions router — upload + liste/detay/party-view (§4.1, Faz 3B/4A).

Router yalnız HTTP input doğrulama, account/legacy create seçimi,
storage/document row hazırlığı ve arka plan pipeline dispatch'i yapar (§10);
convert->analyze->ContextBuilder->extract->restore->validate->persist
zinciri `services/transaction_pipeline.py::run_pipeline()`'a taşındı (Plan 04
/ Faz 4A). Ham `markdown` yalnızca `transactions.markdown` kolonunda saklanır;
hiçbir API cevabına veya event payload'ına girmez (§6.7/pci.req.10).
"""

from __future__ import annotations

import hashlib
import json
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from sqlite3 import Connection, Row
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, ValidationError

from backend.app.api.errors import ApiError
from backend.app.config import Settings
from backend.app.db import get_db
from backend.app.eventbus import emit
from backend.app.repositories import documents as documents_repo
from backend.app.repositories import rule_sets as rule_sets_repo
from backend.app.repositories.entities import get_active_membership
from backend.app.repositories.transactions import (
    list_transaction_events,
    list_transaction_payments,
    list_transaction_rows,
    load_transaction,
)
from backend.app.routers.invitations import get_notification_provider
from backend.app.schemas.extraction import ExtractionJSON
from backend.app.schemas.tracking import (
    PolicyConflict,
    PolicyConflictCode,
    TrackingMode,
    TrackingPolicyStatus,
)
from backend.app.services import invitations as invitations_service
from backend.app.services import participants as participants_service
from backend.app.services import transaction_pipeline
from backend.app.services import transaction_state
from backend.app.services.auth import verify_csrf
from backend.app.services.access_control import (
    ActorContext,
    get_current_actor,
    require_authenticated_user,
)
from backend.app.services.document_storage import make_document_storage_provider
from backend.app.services.extraction_projection import redacted_extraction_projection
from backend.app.services.tracking_policy import (
    contractual_required_evidence,
    create_draft_policy,
    load_tracking_policy,
    lock_manager_policy,
    tracking_summary,
    update_manager_policy,
)

router = APIRouter(prefix="/api/transactions", tags=["transactions"])

_ROLE_COUNTERPART = {"buyer": "seller", "seller": "buyer"}

# dönüştürülecek (document_parser) türler + test/demo kolaylığı için passthrough.
_CONVERTIBLE_SUFFIXES = {".pdf", ".docx", ".png", ".jpg", ".jpeg"}
_PASSTHROUGH_SUFFIXES = {".md", ".txt"}
_ALLOWED_SUFFIXES = _CONVERTIBLE_SUFFIXES | _PASSTHROUGH_SUFFIXES

_VALIDATOR_STATUS_TO_STATE = {
    "PASS": "awaiting_approval",
    "NEEDS_REVIEW": "awaiting_review",
    "REJECT": "rejected",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_party(row: Row, token: str) -> str | None:
    """Token -> taraf çözümü. Eşleşme yoksa `None` (çağıran 403 döner)."""
    if not token:
        return None
    if row["buyer_token"] and token == row["buyer_token"]:
        return "buyer"
    if row["seller_token"] and token == row["seller_token"]:
        return "seller"
    return None


def resolve_manager(row: Row, token: str) -> bool:
    """Sadece transaction'ın manager capability token'ını kabul eder."""
    if not token or "manager_token" not in row.keys():
        return False
    return bool(row["manager_token"]) and token == row["manager_token"]


def _load_extraction(conn: Connection, transaction_id: str) -> dict | None:
    """Persist edilmiş (RESTORE edilmiş) son extraction JSON'ını yükler (§11 merkezi seam)."""
    current = rule_sets_repo.get_current(conn, transaction_id)
    if current is None or current.extraction is None:
        return None
    return current.extraction.model_dump(mode="json")


def _load_validator(conn: Connection, transaction_id: str) -> dict | None:
    current = rule_sets_repo.get_current(conn, transaction_id)
    if current is None:
        return None
    return {"status": current.validator_status, "findings": current.validator_report}


def _validated_extraction(extraction: dict | None) -> ExtractionJSON | None:
    """İç extraction dict'ini yalnız policy kuralları için doğrular."""
    if extraction is None:
        return None
    try:
        return ExtractionJSON.model_validate(extraction)
    except ValidationError:
        return None


def _not_configurable_conflict(row: Row, validator: dict | None) -> PolicyConflict | None:
    """Policy'nin değiştirilebildiği tek güvenli akış penceresini sınırlar."""
    conflicts: list[str] = []
    if row["state"] != "awaiting_approval":
        conflicts.append("STATE_NOT_AWAITING_APPROVAL")
    if validator is None or validator.get("status") != "PASS":
        conflicts.append("VALIDATOR_NOT_PASS")
    if not conflicts:
        return None
    return PolicyConflict(
        code=PolicyConflictCode.POLICY_NOT_CONFIGURABLE,
        message="Takip politikası yalnız doğrulama başarılıyken ve taraf onayı beklenirken yapılandırılabilir.",
        conflicts=conflicts,
    )


def _raise_policy_conflict(conflict: PolicyConflict) -> None:
    raise HTTPException(status_code=409, detail=conflict.model_dump(mode="json"))


class TrackingPolicyUpdateRequest(BaseModel):
    """Manager policy update contract'ı — beklenmeyen alan kabul edilmez."""

    model_config = ConfigDict(extra="forbid")

    manager_token: str
    physical_delivery_confirmed: bool
    tracking_mode: TrackingMode


class TrackingPolicyLockRequest(BaseModel):
    """Manager policy lock contract'ı — capability yalnız body'den gelir."""

    model_config = ConfigDict(extra="forbid")

    manager_token: str


# --- POST / GET endpoint'leri -----------------------------------------------


def _validate_suffix(filename: str | None) -> tuple[str, bool]:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Desteklenmeyen dosya türü: '{suffix or '(uzantısız)'}'. "
                f"İzin verilenler: {sorted(_ALLOWED_SUFFIXES)}"
            ),
        )
    return suffix, suffix in _PASSTHROUGH_SUFFIXES


async def _write_temp_file(file: UploadFile, suffix: str) -> tuple[bytes, Path]:
    contents = await file.read()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(contents)
    finally:
        tmp.close()
    return contents, Path(tmp.name)


async def _create_legacy_transaction(
    background_tasks: BackgroundTasks, file: UploadFile, conn: Connection
) -> dict:
    """Anonim capability-link akışı — değişmedi (lifecycle_version='legacy_v1')."""
    settings = Settings.from_env()
    suffix, is_passthrough = _validate_suffix(file.filename)
    _contents, temp_path = await _write_temp_file(file, suffix)

    transaction_id = uuid4().hex
    buyer_token = secrets.token_urlsafe(32)
    seller_token = secrets.token_urlsafe(32)
    manager_token = secrets.token_urlsafe(32)

    conn.execute(
        "INSERT INTO transactions "
        "(id, state, buyer_token, seller_token, manager_token, markdown, masked_markdown, "
        "created_at, lifecycle_version) "
        "VALUES (?, 'uploaded', ?, ?, ?, NULL, NULL, ?, 'legacy_v1')",
        (transaction_id, buyer_token, seller_token, manager_token, _utc_now_iso()),
    )
    create_draft_policy(conn, transaction_id)
    # Background task kendi connection'ını açar; satırı başlamadan görünür kıl.
    conn.commit()

    background_tasks.add_task(
        transaction_pipeline.run_pipeline,
        transaction_id,
        is_passthrough,
        settings,
        transaction_pipeline.LegacyPipelineInput(file_path=temp_path),
    )

    return {
        "id": transaction_id,
        "buyer_link": f"/t/{transaction_id}/party?token={buyer_token}",
        "seller_link": f"/t/{transaction_id}/party?token={seller_token}",
        "manager_link": f"/t/{transaction_id}/manager?token={manager_token}",
    }


async def _create_account_transaction(
    background_tasks: BackgroundTasks,
    file: UploadFile,
    acting_entity_id: str | None,
    own_role: str | None,
    counterparty_email: str | None,
    actor: ActorContext,
    conn: Connection,
) -> dict:
    """Authenticated hesap akışı (Faz 3C) — capability token ÜRETMEZ.

    `attach_creator` + karşı taraf placeholder'ı her zaman kurulur; davet
    yalnız `counterparty_email` verildiyse gönderilir (§14, `03_identity_...md`).
    """
    require_authenticated_user(actor)  # frozen kontrat: user_id yoksa 401

    if acting_entity_id is None or own_role is None:
        raise ApiError(
            status_code=422,
            code="ACCOUNT_CREATE_FIELDS_REQUIRED",
            message="acting_entity_id ve own_role birlikte verilmelidir.",
        )
    if own_role not in _ROLE_COUNTERPART:
        raise ApiError(
            status_code=422,
            code="INVALID_OWN_ROLE",
            message="own_role yalnızca 'buyer' veya 'seller' olabilir.",
        )
    if get_active_membership(conn, user_id=actor.user_id, legal_entity_id=acting_entity_id) is None:
        raise ApiError(
            status_code=403,
            code="ACTING_ENTITY_NOT_AUTHORIZED",
            message="Bu legal entity adına işlem oluşturma yetkiniz yok.",
        )

    settings = Settings.from_env()
    suffix, is_passthrough = _validate_suffix(file.filename)
    contents = await file.read()
    content_sha256 = hashlib.sha256(contents).hexdigest()

    transaction_id = uuid4().hex
    document_id = uuid4().hex

    # Kalıcı storage'a önce yazılır (§2.11) — temp dosya kalıcı source of
    # truth DEĞİLDİR, bu yüzden request-scope'ta hiç oluşturulmaz.
    storage = make_document_storage_provider(settings)
    stored = storage.store(
        transaction_id=transaction_id,
        document_id=document_id,
        original_filename=file.filename or "document",
        media_type=file.content_type,
        content=contents,
        expected_sha256=content_sha256,
    )

    try:
        conn.execute(
            "INSERT INTO transactions "
            "(id, state, buyer_token, seller_token, manager_token, markdown, masked_markdown, "
            "created_at, created_by_user_id, owner_entity_id, lifecycle_version, content_sha256) "
            "VALUES (?, 'uploaded', NULL, NULL, NULL, NULL, NULL, ?, ?, ?, 'account_v2', ?)",
            (transaction_id, _utc_now_iso(), actor.user_id, acting_entity_id, content_sha256),
        )
        create_draft_policy(conn, transaction_id)
        documents_repo.insert_document(
            conn,
            document_id=document_id,
            transaction_id=transaction_id,
            version=1,
            original_filename=file.filename or "document",
            media_type=file.content_type,
            storage_ref=stored.storage_ref,
            content_sha256=stored.content_sha256,
            uploaded_by_user_id=actor.user_id,
            now=_utc_now_iso(),
        )

        participants_service.attach_creator(conn, transaction_id, actor, own_role, acting_entity_id)
        counterparty_role = _ROLE_COUNTERPART[own_role]
        participants_service.create_counterparty_placeholder(
            conn, transaction_id, counterparty_role, None
        )

        invitation_view: dict | None = None
        if counterparty_email:
            created_invitation = invitations_service.create_invitation(
                conn,
                transaction_id,
                counterparty_role,
                counterparty_email.strip().lower(),
                actor,
                get_notification_provider(),
                invite_link_builder=lambda raw_token: f"/api/invitations/{raw_token}/accept",
            )
            invitation_view = {
                "invitation_id": created_invitation.invitation_id,
                "participant_role": counterparty_role,
                "expires_at": created_invitation.expires_at,
                "invite_link": f"/api/invitations/{created_invitation.raw_token}/accept",
                "notification_delivered": created_invitation.notification_delivered,
            }

        conn.commit()
    except BaseException:
        # Storage başarılı, DB mutation başarısız oldu — best-effort compensation (§4).
        try:
            storage.delete(stored.storage_ref)
        except Exception:  # noqa: BLE001 — compensation en iyi çaba, ana hatayı gölgelemez
            pass
        raise

    background_tasks.add_task(
        transaction_pipeline.run_pipeline,
        transaction_id,
        is_passthrough,
        settings,
        transaction_pipeline.AccountPipelineInput(
            document_id=document_id, storage_ref=stored.storage_ref, suffix=suffix
        ),
    )

    return {
        "id": transaction_id,
        "lifecycle_version": "account_v2",
        "own_role": own_role,
        "acting_entity_id": acting_entity_id,
        "invitation": invitation_view,
    }


@router.post("")
async def create_transaction(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(...),
    acting_entity_id: str | None = Form(None),
    own_role: str | None = Form(None),
    counterparty_email: str | None = Form(None),
    actor: ActorContext = Depends(get_current_actor),
    conn: Connection = Depends(get_db),
) -> dict:
    """Sözleşme dosyasını kaydeder, işlem satırını açar, pipeline'ı arka plana atar.

    İki mod aynı uçta yaşar (additive-first, v2 §2.2): `acting_entity_id`/
    `own_role` verilmişse authenticated **account_v2** akışı (capability token
    yok); verilmemişse mevcut anonim **legacy_v1** akışı DEĞİŞMEDEN çalışır.
    Legacy anonim create'in reddedilmesi (Wave 3 hard cutover,
    `LEGACY_CAPABILITY_ACCESS_ENABLED=false`) bu fazın kapsamında DEĞİLDİR.
    """
    if acting_entity_id is not None or own_role is not None:
        # Aynı endpoint'teki anonim legacy_v1 upload korunur; yalnız session
        # kullanan account_v2 mutation CSRF + Origin doğrulamasından geçer.
        verify_csrf(conn, request=request)
        return await _create_account_transaction(
            background_tasks, file, acting_entity_id, own_role, counterparty_email, actor, conn
        )
    return await _create_legacy_transaction(background_tasks, file, conn)


@router.get("")
def list_transactions(
    actor: ActorContext = Depends(get_current_actor), conn: Connection = Depends(get_db)
) -> list[dict]:
    """Kısa liste — ham içerik yok, taraf adları (varsa) persist edilmiş extraction'dan.

    Authenticated user yalnız aktif assignment'ı olduğu (creator/invitee)
    işlemleri görür. Anonim/legacy_capability istekler yalnız
    `DEMO_PUBLIC_DASHBOARD=true` iken (legacy demo listesi) tüm işlemleri görür.
    """
    settings = Settings.from_env()
    if actor.user_id is not None:
        assigned_ids = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT transaction_id FROM transaction_assignments "
                "WHERE user_id = ? AND status = 'active'",
                (actor.user_id,),
            )
        }
        rows = [row for row in list_transaction_rows(conn) if row["id"] in assigned_ids]
    elif settings.demo_public_dashboard:
        rows = list_transaction_rows(conn)
    else:
        raise HTTPException(status_code=403, detail="Liste erişimi kapalı.")
    result: list[dict] = []
    for row in rows:
        extraction = _load_extraction(conn, row["id"])
        buyer_name = None
        seller_name = None
        if extraction is not None:
            parties = extraction.get("parties") or {}
            buyer_name = (parties.get("buyer") or {}).get("name")
            seller_name = (parties.get("seller") or {}).get("name")
        result.append(
            {
                "id": row["id"],
                "state": row["state"],
                "created_at": row["created_at"],
                "buyer_name": buyer_name,
                "seller_name": seller_name,
            }
        )
    return result


def _latest_event_payload(conn: Connection, transaction_id: str, event_type: str) -> dict | None:
    row = conn.execute(
        "SELECT payload FROM events WHERE transaction_id = ? AND event_type = ? "
        "ORDER BY id DESC LIMIT 1",
        (transaction_id, event_type),
    ).fetchone()
    if row is None or row["payload"] is None:
        return None
    try:
        return json.loads(row["payload"])
    except (TypeError, ValueError):
        return None


def _compute_canonical_state(conn: Connection, row: Row) -> str | None:
    """v2 §2.8 canonical projeksiyonu — yalnız `legacy_v1` satırlar için.

    `account_v2` transaction'lar kendi state machine'ini kullanır (Plan 03+
    kapsamı dışı, henüz tanımlı değil); bu durumda `None` döner.
    """
    if row["lifecycle_version"] != "legacy_v1":
        return None

    try:
        legacy_status = transaction_state.LegacyStatus(row["state"])
    except ValueError:
        return None  # ara/bilinmeyen state (örn. 'extracting' sırasında yarış) -> canonical yok

    transaction_id = row["id"]
    kwargs: dict = {}

    if legacy_status is transaction_state.LegacyStatus.AWAITING_REVIEW:
        # Program 1 sınırı (§2.16): NEEDS_REVIEW bu fazda hâlâ recoverable değil.
        kwargs["review_blocking"] = True
    elif legacy_status is transaction_state.LegacyStatus.AWAITING_APPROVAL:
        policy = load_tracking_policy(conn, transaction_id)
        kwargs["ratification_ready"] = (
            policy is not None and policy.status is TrackingPolicyStatus.locked
        )
    elif legacy_status is transaction_state.LegacyStatus.EVIDENCE_PENDING:
        decision_payload = _latest_event_payload(conn, transaction_id, "payment_decision_created")
        kwargs["evidence_blocking"] = bool(
            decision_payload and decision_payload.get("manual_review_required")
        )
    elif legacy_status is transaction_state.LegacyStatus.DECIDED:
        payment_row = conn.execute(
            "SELECT status FROM mock_payments WHERE transaction_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (transaction_id,),
        ).fetchone()
        payment_status = payment_row["status"] if payment_row is not None else None
        kwargs["release_completeness"] = (
            transaction_state.ReleaseCompleteness.FULLY_RELEASED
            if payment_status == "released"
            else transaction_state.ReleaseCompleteness.PARTIALLY_RELEASED
        )
        # Milestone/multi-release (Program 4+) bu fazda yok — tekil karar finaldir.
        kwargs["more_releases_expected"] = False

    try:
        return transaction_state.project_legacy_state(
            transaction_state.LegacyProjectionInput(legacy_status=legacy_status, **kwargs)
        ).value
    except transaction_state.LegacyProjectionError:
        return None


@router.get("/{transaction_id}")
def get_transaction(
    transaction_id: str,
    actor: ActorContext = Depends(get_current_actor),
    conn: Connection = Depends(get_db),
) -> dict:
    """Detay — extraction, validator raporu, event zaman çizelgesi, ödeme durumu.

    `account_v2` satırlar authenticated + assignment'lı erişim gerektirir;
    `legacy_v1` satırlarda erişim davranışı DEĞİŞMEDEN açık kalır.
    """
    row = load_transaction(conn, transaction_id)
    if row is None:
        raise HTTPException(status_code=404, detail="İşlem bulunamadı.")

    if row["lifecycle_version"] == "account_v2":
        if actor.user_id is None:
            raise HTTPException(status_code=401, detail="Kimlik doğrulama gerekli.")
        if not participants_service.has_transaction_access(conn, transaction_id, actor.user_id):
            raise HTTPException(status_code=403, detail="Bu işlemde erişiminiz yok.")

    events = [
        {
            "id": ev["id"],
            "event_type": ev["event_type"],
            "payload": json.loads(ev["payload"]) if ev["payload"] else None,
            "source": ev["source"],
            "created_at": ev["created_at"],
        }
        for ev in list_transaction_events(conn, transaction_id)
    ]

    payments = [
        {
            "other_trx_code": p["other_trx_code"],
            "virtual_pos_order_id": p["virtual_pos_order_id"],
            "status": p["status"],
            "amount": p["amount"],
            "created_at": p["created_at"],
        }
        for p in list_transaction_payments(conn, transaction_id)
    ]

    return {
        "id": row["id"],
        "state": row["state"],
        "created_at": row["created_at"],
        "lifecycle_version": row["lifecycle_version"],
        "canonical_state": _compute_canonical_state(conn, row),
        # Token istemeyen genel detay: `source_quote` DÖNMEZ.
        "extraction": redacted_extraction_projection(_load_extraction(conn, transaction_id)),
        "validator": _load_validator(conn, transaction_id),
        "events": events,
        "payment": payments or None,
    }


def _require_legacy_capability_enabled(settings: Settings) -> None:
    """`LEGACY_CAPABILITY_ACCESS_ENABLED=false` (Wave 3 hazırlığı) -> 403.

    Bu fazda varsayılan `true`; davranış değişmez (v2 §2.2).
    """
    if not settings.legacy_capability_access_enabled:
        raise HTTPException(status_code=403, detail="Legacy capability erişimi kapalı.")


@router.get("/{transaction_id}/party-view")
def get_party_view(transaction_id: str, token: str, conn: Connection = Depends(get_db)) -> dict:
    """Token -> taraf çözümlü özet görünüm; yanlış/eksik token -> 403."""
    _require_legacy_capability_enabled(Settings.from_env())
    try:
        row = load_transaction(conn, transaction_id)
        if row is None:
            raise HTTPException(status_code=404, detail="İşlem bulunamadı.")

        party = resolve_party(row, token)
        if party is None:
            raise HTTPException(status_code=403, detail="Geçersiz token.")

        extraction = _load_extraction(conn, transaction_id)
        # Taraf, onaylayacağı kuralın sözleşmedeki dayanağını görmelidir (§6.2).
        public_extraction = redacted_extraction_projection(extraction, include_source_quote=True)
        extraction_summary = None
        if public_extraction is not None:
            commercial = public_extraction["commercial_terms"]
            extraction_summary = {
                "contract_id": public_extraction["contract_id"],
                "parties": public_extraction["parties"],
                "currency": commercial.get("currency"),
                "total_amount": commercial.get("total_amount"),
                "commercial_terms": commercial,
                "payment_rules": public_extraction["payment_rules"],
                "risk_flags": public_extraction["risk_flags"],
                "needs_manual_review": public_extraction["needs_manual_review"],
            }

        parsed_extraction = _validated_extraction(extraction)
        contractual_requirements = (
            contractual_required_evidence(parsed_extraction) if parsed_extraction is not None else set()
        )
        policy = load_tracking_policy(conn, transaction_id)

        validator_report = _load_validator(conn, transaction_id)
        validator_findings = validator_report["findings"] if validator_report else None

        approved_parties = {
            r["party"]
            for r in conn.execute(
                "SELECT DISTINCT party FROM approvals WHERE transaction_id = ?",
                (transaction_id,),
            ).fetchall()
        }

        return {
            "party": party,
            "state": row["state"],
            "extraction_summary": extraction_summary,
            "validator_findings": validator_findings,
            "approvals": {
                "buyer": "buyer" in approved_parties,
                "seller": "seller" in approved_parties,
            },
            "tracking_summary": tracking_summary(policy, contractual_requirements),
        }
    finally:
        pass


@router.get("/{transaction_id}/manager-view")
def get_manager_view(transaction_id: str, token: str, conn: Connection = Depends(get_db)) -> dict:
    """Manager capability ile policy hazırlık görünümü; token sızdırmaz."""
    _require_legacy_capability_enabled(Settings.from_env())
    try:
        row = load_transaction(conn, transaction_id)
        if row is None:
            raise HTTPException(status_code=404, detail="İşlem bulunamadı.")
        if not resolve_manager(row, token):
            raise HTTPException(status_code=403, detail="Geçersiz token.")

        extraction = _load_extraction(conn, transaction_id)
        parsed_extraction = _validated_extraction(extraction)
        validator = _load_validator(conn, transaction_id)
        policy = load_tracking_policy(conn, transaction_id)
        ready_for_policy = (
            _not_configurable_conflict(row, validator) is None
            and policy is not None
            and policy.status is TrackingPolicyStatus.draft
        )
        contractual_requirements = (
            contractual_required_evidence(parsed_extraction) if parsed_extraction is not None else set()
        )

        return {
            "state": row["state"],
            "extraction": redacted_extraction_projection(extraction, include_source_quote=True),
            "validator": validator,
            "tracking_policy": policy.model_dump(mode="json") if policy is not None else None,
            "ready_for_policy": ready_for_policy,
            "contractual_required_evidence": sorted(
                kind.value for kind in contractual_requirements
            ),
        }
    finally:
        pass


@router.put("/{transaction_id}/tracking-policy")
def update_tracking_policy(transaction_id: str, body: TrackingPolicyUpdateRequest, conn: Connection = Depends(get_db)) -> dict:
    """Manager'ın taslak takip seçimini değiştirir; aynı seçim idempotenttir."""
    try:
        row = load_transaction(conn, transaction_id)
        if row is None:
            raise HTTPException(status_code=404, detail="İşlem bulunamadı.")
        if not Settings.from_env().legacy_capability_access_enabled:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "LEGACY_CAPABILITY_ACCESS_DISABLED",
                    "message": "Legacy capability erişimi kapalı.",
                },
            )
        if not resolve_manager(row, body.manager_token):
            raise HTTPException(status_code=403, detail="Geçersiz token.")

        validator = _load_validator(conn, transaction_id)
        gate_conflict = _not_configurable_conflict(row, validator)
        if gate_conflict is not None:
            _raise_policy_conflict(gate_conflict)

        extraction = _validated_extraction(_load_extraction(conn, transaction_id))
        if extraction is None:  # validator PASS iken olamaz; veri bütünlüğü için safe 409
            _raise_policy_conflict(
                PolicyConflict(
                    code=PolicyConflictCode.POLICY_NOT_CONFIGURABLE,
                    message="Doğrulanmış sözleşme kuralları bulunamadı.",
                    conflicts=["EXTRACTION_NOT_AVAILABLE"],
                )
            )

        policy, updated, conflict = update_manager_policy(
            conn,
            transaction_id,
            extraction,
            physical_delivery_confirmed=body.physical_delivery_confirmed,
            tracking_mode=body.tracking_mode,
        )
        if conflict is not None:
            _raise_policy_conflict(conflict)

        if updated:
            emit(
                conn,
                transaction_id,
                "tracking_policy_updated",
                {"tracking_policy": policy.model_dump(mode="json")},
                "manager",
            )
        conn.commit()
        return {"updated": updated, "tracking_policy": policy.model_dump(mode="json")}
    finally:
        pass


@router.post("/{transaction_id}/tracking-policy/lock")
def lock_tracking_policy(transaction_id: str, body: TrackingPolicyLockRequest, conn: Connection = Depends(get_db)) -> dict:
    """Manager'ın hazır policy'yi onaylardan önce değişmez hale getirmesi."""
    try:
        row = load_transaction(conn, transaction_id)
        if row is None:
            raise HTTPException(status_code=404, detail="İşlem bulunamadı.")
        if not Settings.from_env().legacy_capability_access_enabled:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "LEGACY_CAPABILITY_ACCESS_DISABLED",
                    "message": "Legacy capability erişimi kapalı.",
                },
            )
        if not resolve_manager(row, body.manager_token):
            raise HTTPException(status_code=403, detail="Geçersiz token.")

        validator = _load_validator(conn, transaction_id)
        gate_conflict = _not_configurable_conflict(row, validator)
        if gate_conflict is not None:
            _raise_policy_conflict(gate_conflict)

        extraction = _validated_extraction(_load_extraction(conn, transaction_id))
        if extraction is None:  # validator PASS iken olamaz; veri bütünlüğü için safe 409
            _raise_policy_conflict(
                PolicyConflict(
                    code=PolicyConflictCode.POLICY_NOT_CONFIGURABLE,
                    message="Doğrulanmış sözleşme kuralları bulunamadı.",
                    conflicts=["EXTRACTION_NOT_AVAILABLE"],
                )
            )

        policy, locked, conflict = lock_manager_policy(conn, transaction_id, extraction)
        if conflict is not None:
            _raise_policy_conflict(conflict)

        if locked:
            emit(
                conn,
                transaction_id,
                "tracking_policy_locked",
                {"tracking_policy": policy.model_dump(mode="json")},
                "manager",
            )
        conn.commit()
        return {"locked": locked, "tracking_policy": policy.model_dump(mode="json")}
    finally:
        pass
