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

import json
import secrets
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from sqlite3 import Connection, Row
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
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

from backend.app.config import Settings  # noqa: E402
from backend.app.db import connect  # noqa: E402
from backend.app.eventbus import emit  # noqa: E402
from backend.app.schemas.extraction import ExtractionJSON  # noqa: E402
from backend.app.schemas.tracking import (  # noqa: E402
    PolicyConflict,
    PolicyConflictCode,
    TrackingMode,
    TrackingPolicyStatus,
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


def load_transaction(conn: Connection, transaction_id: str) -> Row | None:
    """`transactions` tablosundan tek bir satır çeker (`approvals.py` da kullanır)."""
    return conn.execute(
        "SELECT * FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()


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


@router.post("")
async def create_transaction(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
) -> dict:
    """Sözleşme dosyasını kaydeder, işlem satırını açar, pipeline'ı arka plana atar."""
    settings = Settings.from_env()

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Desteklenmeyen dosya türü: '{suffix or '(uzantısız)'}'. "
                f"İzin verilenler: {sorted(_ALLOWED_SUFFIXES)}"
            ),
        )
    is_passthrough = suffix in _PASSTHROUGH_SUFFIXES

    contents = await file.read()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(contents)
    finally:
        tmp.close()
    temp_path = Path(tmp.name)

    transaction_id = uuid4().hex
    buyer_token = secrets.token_urlsafe(32)
    seller_token = secrets.token_urlsafe(32)
    manager_token = secrets.token_urlsafe(32)

    conn = connect(settings)
    try:
        conn.execute(
            "INSERT INTO transactions "
            "(id, state, buyer_token, seller_token, manager_token, markdown, masked_markdown, created_at) "
            "VALUES (?, 'uploaded', ?, ?, ?, NULL, NULL, ?)",
            (transaction_id, buyer_token, seller_token, manager_token, _utc_now_iso()),
        )
        create_draft_policy(conn, transaction_id)
        conn.commit()
    finally:
        conn.close()

    background_tasks.add_task(run_pipeline, transaction_id, temp_path, is_passthrough, settings)

    return {
        "id": transaction_id,
        "buyer_link": f"/t/{transaction_id}/party?token={buyer_token}",
        "seller_link": f"/t/{transaction_id}/party?token={seller_token}",
        "manager_link": f"/t/{transaction_id}/manager?token={manager_token}",
    }


@router.get("")
def list_transactions() -> list[dict]:
    """Kısa liste — ham içerik yok, taraf adları (varsa) persist edilmiş extraction'dan."""
    settings = Settings.from_env()
    conn = connect(settings)
    try:
        rows = conn.execute(
            "SELECT id, state, created_at FROM transactions ORDER BY created_at"
        ).fetchall()
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
    finally:
        conn.close()


@router.get("/{transaction_id}")
def get_transaction(transaction_id: str) -> dict:
    """Detay — extraction, validator raporu, event zaman çizelgesi, ödeme durumu."""
    settings = Settings.from_env()
    conn = connect(settings)
    try:
        row = load_transaction(conn, transaction_id)
        if row is None:
            raise HTTPException(status_code=404, detail="İşlem bulunamadı.")

        events = [
            {
                "id": ev["id"],
                "event_type": ev["event_type"],
                "payload": json.loads(ev["payload"]) if ev["payload"] else None,
                "source": ev["source"],
                "created_at": ev["created_at"],
            }
            for ev in conn.execute(
                "SELECT id, event_type, payload, source, created_at FROM events "
                "WHERE transaction_id = ? ORDER BY id",
                (transaction_id,),
            ).fetchall()
        ]

        payments = [
            {
                "other_trx_code": p["other_trx_code"],
                "virtual_pos_order_id": p["virtual_pos_order_id"],
                "status": p["status"],
                "amount": p["amount"],
                "created_at": p["created_at"],
            }
            for p in conn.execute(
                "SELECT other_trx_code, virtual_pos_order_id, status, amount, created_at "
                "FROM mock_payments WHERE transaction_id = ?",
                (transaction_id,),
            ).fetchall()
        ]

        return {
            "id": row["id"],
            "state": row["state"],
            "created_at": row["created_at"],
            # Token istemeyen genel detay: `source_quote` DÖNMEZ (maskeleme NER
            # olmadığı için alıntıdaki isim/adres/ticari ifade temizlenmiyor).
            "extraction": redacted_extraction_projection(_load_extraction(conn, transaction_id)),
            "validator": _load_validator(conn, transaction_id),
            "events": events,
            "payment": payments or None,
        }
    finally:
        conn.close()


@router.get("/{transaction_id}/party-view")
def get_party_view(transaction_id: str, token: str) -> dict:
    """Token -> taraf çözümlü özet görünüm; yanlış/eksik token -> 403."""
    settings = Settings.from_env()
    conn = connect(settings)
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
        conn.close()


@router.get("/{transaction_id}/manager-view")
def get_manager_view(transaction_id: str, token: str) -> dict:
    """Manager capability ile policy hazırlık görünümü; token sızdırmaz."""
    settings = Settings.from_env()
    conn = connect(settings)
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
        conn.close()


@router.put("/{transaction_id}/tracking-policy")
def update_tracking_policy(transaction_id: str, body: TrackingPolicyUpdateRequest) -> dict:
    """Manager'ın taslak takip seçimini değiştirir; aynı seçim idempotenttir."""
    settings = Settings.from_env()
    conn = connect(settings)
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
        conn.close()


@router.post("/{transaction_id}/tracking-policy/lock")
def lock_tracking_policy(transaction_id: str, body: TrackingPolicyLockRequest) -> dict:
    """Manager'ın hazır policy'yi onaylardan önce değişmez hale getirmesi."""
    settings = Settings.from_env()
    conn = connect(settings)
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
        conn.close()


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
    design decision #2); bu yüzden `db.connect(settings)` ile bağımsız bir
    bağlantı açılır, `finally`'de commit/close edilir. Hat asla sessizce
    çökmez: beklenmeyen bir istisna `awaiting_review` + hata event'ine düşer,
    `extracting`'te asla takılı kalınmaz.
    """
    conn = connect(settings)
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
