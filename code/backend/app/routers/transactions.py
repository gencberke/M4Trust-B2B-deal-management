"""Transactions router — upload pipeline + liste/detay/party-view (§4.1, Faz 3B).

Upload endpoint'i hemen döner; asıl iş arka planda `run_pipeline()` içinde
CLI'daki (`scripts/extract_contract.py::run_extraction`) ile AYNI sırayla
mevcut servisleri çağırarak yürür: convert -> `privacy.analyze()` ->
`ContextBuilder.build()` -> blocking kontrolü -> extract -> restore ->
`validate()`. CLI'ın kendisi değiştirilmez; yalnızca aynı servisler burada
bağımsız bir arka plan görevinden çağrılır (§6.7: dış LLM'e yalnızca
maskelenmiş metin gider).

Ham `markdown` yalnızca `transactions.markdown` kolonunda saklanır; hiçbir API
cevabına veya event payload'ına girmez (§6.7/pci.req.10, Pinned design
decisions #1).
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from sqlite3 import Connection, Row
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, ValidationError

# Import köprüsü: `document_parser` `code/scripts/` altında yaşar (bkz.
# `scripts/extract_contract.py` aynı desen). Bu router `code/` kökünden
# çalışan `backend` paketinin bir parçası olduğundan `scripts/` ayrıca
# `sys.path`'e eklenmeli. `scripts/extract_contract.py` DEĞİŞMEZ.
_CODE_ROOT = Path(__file__).resolve().parents[3]
_SCRIPTS_ROOT = _CODE_ROOT / "scripts"
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from document_parser import (  # noqa: E402
    DocumentConverter,
    EmptyDocumentError,
    ExtractionError,
    UnsupportedFileTypeError,
)

from backend.app.api.errors import ApiError  # noqa: E402
from backend.app.config import Settings  # noqa: E402
from backend.app.db import get_db, open_background_connection  # noqa: E402
from backend.app.eventbus import emit  # noqa: E402
from backend.app.repositories.entities import get_active_membership  # noqa: E402
from backend.app.repositories.transactions import (  # noqa: E402
    list_transaction_events,
    list_transaction_payments,
    list_transaction_rows,
    load_transaction,
)
from backend.app.routers.invitations import get_notification_provider  # noqa: E402
from backend.app.schemas.extraction import ExtractionJSON  # noqa: E402
from backend.app.schemas.tracking import (  # noqa: E402
    PolicyConflict,
    PolicyConflictCode,
    TrackingMode,
    TrackingPolicyStatus,
)
from backend.app.services import invitations as invitations_service  # noqa: E402
from backend.app.services import participants as participants_service  # noqa: E402
from backend.app.services import transaction_state  # noqa: E402
from backend.app.services.access_control import (  # noqa: E402
    ActorContext,
    get_current_actor,
    require_authenticated_user,
)
from backend.app.services.context_builder import ContextBuilder  # noqa: E402
from backend.app.services.extraction_projection import redacted_extraction_projection  # noqa: E402
from backend.app.services.extraction import make_extraction_service  # noqa: E402
from backend.app.services.privacy import analyze, restore  # noqa: E402
from backend.app.services.rag import Retriever  # noqa: E402
from backend.app.services.tracking_policy import (  # noqa: E402
    contractual_required_evidence,
    create_draft_policy,
    load_tracking_policy,
    lock_manager_policy,
    recommend_physical_delivery,
    tracking_summary,
    update_manager_policy,
    update_system_recommendation,
)
from backend.app.services.validator import validate  # noqa: E402

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
    """Persist edilmiş (RESTORE edilmiş) son extraction JSON'ını yükler."""
    row = conn.execute(
        "SELECT extraction_json FROM extracted_rules WHERE transaction_id = ? "
        "ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (transaction_id,),
    ).fetchone()
    if row is None or row["extraction_json"] is None:
        return None
    return json.loads(row["extraction_json"])


def _load_validator(conn: Connection, transaction_id: str) -> dict | None:
    row = conn.execute(
        "SELECT validator_status, validator_report FROM extracted_rules WHERE transaction_id = ? "
        "ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (transaction_id,),
    ).fetchone()
    if row is None:
        return None
    findings = row["validator_report"]
    if findings:
        try:
            findings = json.loads(findings)
        except (json.JSONDecodeError, TypeError):
            pass  # düz metin gerekçe (pipeline hata/needs_review yolu) — olduğu gibi bırak
    return {"status": row["validator_status"], "findings": findings}


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

    background_tasks.add_task(run_pipeline, transaction_id, temp_path, is_passthrough, settings)

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
    contents, temp_path = await _write_temp_file(file, suffix)
    content_sha256 = hashlib.sha256(contents).hexdigest()

    transaction_id = uuid4().hex
    conn.execute(
        "INSERT INTO transactions "
        "(id, state, buyer_token, seller_token, manager_token, markdown, masked_markdown, "
        "created_at, created_by_user_id, owner_entity_id, lifecycle_version, content_sha256) "
        "VALUES (?, 'uploaded', NULL, NULL, NULL, NULL, NULL, ?, ?, ?, 'account_v2', ?)",
        (transaction_id, _utc_now_iso(), actor.user_id, acting_entity_id, content_sha256),
    )
    create_draft_policy(conn, transaction_id)

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

    background_tasks.add_task(run_pipeline, transaction_id, temp_path, is_passthrough, settings)

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


# --- arka plan pipeline ------------------------------------------------------


def _merge_risk_flags(payload: dict, risk_flags: list[str], *, needs_review: bool) -> dict:
    """`privacy_report.risk_flags`'i extraction JSON'a birleştirir (şema değişmez).

    `scripts/extract_contract.py::_merge_risk_flags` ile aynı küçük mantık —
    plan gereği import edilmez, burada bağımsız olarak yeniden uygulanır.
    """
    existing = list(payload.get("risk_flags") or [])
    for flag in risk_flags:
        if flag not in existing:
            existing.append(flag)
    payload["risk_flags"] = existing
    if needs_review:
        payload["needs_manual_review"] = True
    return payload


def _persist_extraction(conn: Connection, transaction_id: str, extraction: ExtractionJSON, settings: Settings) -> None:
    """Geçerli bir extraction üretildiğinde: validator çalıştır, kaydet, state geçir, event'le."""
    validator_report = validate(
        extraction, confidence_threshold=settings.validator_confidence_threshold
    )
    findings_payload = [
        {"code": f.code, "severity": f.severity, "message": f.message}
        for f in validator_report.findings
    ]

    conn.execute(
        "INSERT INTO extracted_rules "
        "(transaction_id, extraction_json, validator_status, validator_report, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            transaction_id,
            json.dumps(extraction.model_dump(mode="json"), ensure_ascii=False),
            validator_report.status,
            json.dumps(findings_payload, ensure_ascii=False),
            _utc_now_iso(),
        ),
    )
    new_state = _VALIDATOR_STATUS_TO_STATE[validator_report.status]
    conn.execute("UPDATE transactions SET state = ? WHERE id = ?", (new_state, transaction_id))

    emit(
        conn,
        transaction_id,
        "contract_extracted",
        {
            "parties": {
                "buyer_name": extraction.parties.buyer.name,
                "seller_name": extraction.parties.seller.name,
            },
            "currency": extraction.commercial_terms.currency.value,
            "total_amount": extraction.commercial_terms.total_amount,
            "num_rules": len(extraction.payment_rules),
        },
        "pipeline",
    )
    emit(
        conn,
        transaction_id,
        "rules_validated",
        {"status": validator_report.status, "findings": findings_payload},
        "validator",
    )
    if validator_report.status == "PASS":
        recommendation = recommend_physical_delivery(extraction)
        policy = update_system_recommendation(conn, transaction_id, recommendation)
        if policy is not None:
            emit(
                conn,
                transaction_id,
                "tracking_policy_recommended",
                {
                    "recommendation": recommendation.recommendation.value,
                    "reason_codes": [reason.value for reason in recommendation.reason_codes],
                },
                "tracking_policy",
            )


def _persist_no_extraction(conn: Connection, transaction_id: str, reason: str) -> None:
    """Geçerli extraction üretilemediğinde (blocking-skip / extraction hatası / restore-invalid)."""
    conn.execute(
        "INSERT INTO extracted_rules "
        "(transaction_id, extraction_json, validator_status, validator_report, created_at) "
        "VALUES (?, NULL, 'NEEDS_REVIEW', ?, ?)",
        (transaction_id, reason, _utc_now_iso()),
    )
    conn.execute(
        "UPDATE transactions SET state = 'awaiting_review' WHERE id = ?", (transaction_id,)
    )
    emit(
        conn,
        transaction_id,
        "rules_validated",
        {
            "status": "NEEDS_REVIEW",
            "findings": [{"code": "EXTRACTION_UNAVAILABLE", "severity": "review", "message": reason}],
        },
        "pipeline",
    )


def _execute_pipeline(
    conn: Connection, transaction_id: str, file_path: Path, is_passthrough: bool, settings: Settings
) -> None:
    """convert -> analyze -> ContextBuilder -> blocking-check -> extract -> restore -> validate."""
    if is_passthrough:
        markdown = file_path.read_text(encoding="utf-8")
    else:
        markdown = DocumentConverter().convert(file_path)

    report = analyze(markdown)  # §6.7: mask + kart-verisi sınıflandırma (canlı çağrıdan ÖNCE)
    conn.execute(
        "UPDATE transactions SET markdown = ?, masked_markdown = ? WHERE id = ?",
        (markdown, report.masked_text, transaction_id),
    )

    builder = ContextBuilder(settings, Retriever(settings))
    context = builder.build(report.masked_text, privacy_report=report)

    extraction: ExtractionJSON | None = None
    reason: str | None = None

    # §6.7 / PCI: SAD (CVV/track/PIN) tespitinde canlı (openai) provider çağrılmaz.
    if report.blocking_findings and settings.llm_provider == "openai":
        reason = (
            "Hassas ödeme doğrulama verisi tespit edildi; dış LLM çağrısı atlandı: "
            + "; ".join(report.blocking_findings)
        )
    else:
        result = make_extraction_service(settings).extract(report.masked_text, context)
        if result.status != "ok" or result.data is None:
            reason = result.reason or "Extraction başarısız oldu."
        else:
            restored = restore(result.data.model_dump(), report.mapping)
            restored = _merge_risk_flags(
                restored, report.risk_flags, needs_review=bool(report.blocking_findings)
            )
            try:
                extraction = ExtractionJSON.model_validate(restored)
            except ValidationError as exc:
                reason = f"restore sonrası doğrulama başarısız: {exc}"

    if extraction is not None:
        _persist_extraction(conn, transaction_id, extraction, settings)
    else:
        _persist_no_extraction(conn, transaction_id, reason or "Bilinmeyen sebep")


def run_pipeline(transaction_id: str, file_path: Path, is_passthrough: bool, settings: Settings) -> None:
    """`BackgroundTasks` tarafından çağrılan pipeline task'ı — kendi DB bağlantısını açar.

    İstek anındaki `get_db` bağlantısı task koşana kadar kapanmış olur (Pinned
    design decision #2); bu yüzden `open_background_connection(settings)` ile bağımsız bir
    bağlantı açılır, `finally`'de commit/close edilir. Hat asla sessizce
    çökmez: beklenmeyen bir istisna `awaiting_review` + hata event'ine düşer,
    `extracting`'te asla takılı kalınmaz.
    """
    conn = open_background_connection(settings)
    try:
        conn.execute(
            "UPDATE transactions SET state = 'extracting' WHERE id = ?", (transaction_id,)
        )
        conn.commit()

        try:
            _execute_pipeline(conn, transaction_id, file_path, is_passthrough, settings)
        except Exception as exc:  # noqa: BLE001 — hat asla sessizce çökmez (Notes for Implementer)
            conn.execute(
                "UPDATE transactions SET state = 'awaiting_review' WHERE id = ?", (transaction_id,)
            )
            emit(
                conn,
                transaction_id,
                "rules_validated",
                {
                    "status": "NEEDS_REVIEW",
                    "findings": [
                        {"code": "PIPELINE_ERROR", "severity": "review", "message": str(exc)}
                    ],
                },
                "pipeline",
            )

        conn.commit()
    finally:
        conn.close()
        file_path.unlink(missing_ok=True)
