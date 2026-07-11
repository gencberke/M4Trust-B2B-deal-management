"""Authorized evidence ingestion uçları (Plan 05 / Faz 5A).

```
POST /api/transactions/{transaction_id}/evidence/e-irsaliye
POST /api/transactions/{transaction_id}/evidence/video
```

`main.py`'ye kayıt Berke'nindir. Yalnız donmuş `get_current_actor`/
`require_authenticated_user`/`require_csrf_protection` kullanılır;
`services/access_control.py`'ye dokunulmaz. Dar `require_evidence_submitter`
kontrolü burada yaşar (manager veya seller-linked assignment; buyer
approver/viewer reddedilir). Router provider ödeme modülü import etmez,
kendi `conn.commit()` çağırmaz (transaction ownership `get_db`
dependency'sindedir) ve settlement'a bağlanmaz — bu Berke'nin entegrasyon işi.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from sqlite3 import Connection
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from backend.app.api.errors import ApiError
from backend.app.config import Settings
from backend.app.db import get_db
from backend.app.repositories import participants as participants_repo
from backend.app.repositories import rule_sets as rule_sets_repo
from backend.app.repositories.transactions import load_transaction
from backend.app.services import evidence_records as evidence_records_service
from backend.app.services.access_control import ActorContext, require_authenticated_user
from backend.app.services.auth import require_csrf_protection
from backend.app.services.document_storage import make_document_storage_provider
from backend.app.services.tracking_policy import (
    contractual_required_evidence,
    e_irsaliye_tracking_enabled,
    load_tracking_policy,
    video_tracking_enabled,
)
from backend.app.services.video import make_video_analyzer

router = APIRouter(prefix="/api/transactions", tags=["evidence-submit"])

# Mevcut bir video/foto upload sınırı repo'da tanımlı değildi (grep ile
# doğrulandı) -- konservatif local sabit; kalıcı config alanı Berke'nin
# entegrasyon TODO'su (PR açıklamasında işaretlendi), `config.py`'ye
# dokunulmadı.
_MAX_VIDEO_BYTES = 25 * 1024 * 1024

_ANALYZER_VERSION = "video_analyzer_v1"


class EIrsaliyeSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_reference: str = Field(min_length=1, max_length=128)
    delivered_quantity: float = Field(ge=0)


class EvidenceRecordPublicView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    transaction_id: str
    milestone_id: str | None
    evidence_type: str
    source: str
    submitted_by_user_id: str
    submitted_by_entity_id: str
    external_reference: str | None
    storage_ref: str | None
    file_sha256: str | None
    payload: dict
    verification_status: str
    analyzer_provider: str | None
    analyzer_version: str | None
    created_at: str
    verified_at: str | None


def _to_public_view(record) -> EvidenceRecordPublicView:
    return EvidenceRecordPublicView(
        id=record.id,
        transaction_id=record.transaction_id,
        milestone_id=record.milestone_id,
        evidence_type=record.evidence_type,
        source=record.source,
        submitted_by_user_id=record.submitted_by_user_id,
        submitted_by_entity_id=record.submitted_by_entity_id,
        external_reference=record.external_reference,
        storage_ref=record.storage_ref,
        file_sha256=record.file_sha256,
        payload=record.payload,
        verification_status=record.verification_status,
        analyzer_provider=record.analyzer_provider,
        analyzer_version=record.analyzer_version,
        created_at=record.created_at,
        verified_at=record.verified_at,
    )


def require_evidence_submitter(conn: Connection, transaction_id: str, actor: ActorContext) -> None:
    """Dar yetki kapısı: yalnız aktif MANAGER assignment veya seller
    participant'ını temsil eden assignment kanıt sunabilir.

    `actor.acting_entity_id`, kabul edilen assignment'ın `legal_entity_id`'i
    ile eşleşmelidir. Kullanıcının TÜM aktif assignment'ları değerlendirilir
    (yalnız ilk bulunan rastgele satıra güvenilmez) -- buyer approver/viewer
    hiçbir eşleşen assignment bulamayacağı için reddedilir.
    """
    transaction = load_transaction(conn, transaction_id)
    if transaction is None:
        raise ApiError(status_code=404, code="TRANSACTION_NOT_FOUND", message="İşlem bulunamadı.")
    if transaction["lifecycle_version"] != "account_v2":
        raise ApiError(
            status_code=409,
            code="LEGACY_EVIDENCE_SUBMISSION_FORBIDDEN",
            message="Evidence ingestion yalnız account_v2 işlemler için kullanılabilir.",
        )
    if transaction["state"] != "active":
        raise ApiError(
            status_code=409,
            code="EVIDENCE_SUBMISSION_STATE_INVALID",
            message="Teslimat kanıtı yalnız fonlanmış ve aktif işlemlerde sunulabilir.",
        )

    assignments = conn.execute(
        "SELECT * FROM transaction_assignments WHERE transaction_id = ? AND user_id = ? "
        "AND status = 'active'",
        (transaction_id, actor.user_id),
    ).fetchall()

    seller = participants_repo.get_participant(conn, transaction_id, "seller")
    seller_participant_id = seller["id"] if seller is not None else None

    for assignment in assignments:
        if assignment["legal_entity_id"] != actor.acting_entity_id:
            continue
        if assignment["role"] == "manager":
            return
        if seller_participant_id is not None and assignment["participant_id"] == seller_participant_id:
            return

    raise ApiError(
        status_code=403,
        code="EVIDENCE_SUBMITTER_FORBIDDEN",
        message="Yalnız aktif manager veya seller assignment'ı kanıt sunabilir.",
    )


def _require_channel_enabled(conn: Connection, transaction_id: str, *, channel: str) -> None:
    """Sözleşmesel gereksinim veya kilitli takip politikasından kanalın etkin
    olduğunu doğrular -- zayıflatma yok, yalnız okuma."""
    current = rule_sets_repo.get_current(conn, transaction_id)
    extraction = current.extraction if current is not None else None
    requirements = contractual_required_evidence(extraction) if extraction is not None else set()
    policy = load_tracking_policy(conn, transaction_id)

    enabled = (
        e_irsaliye_tracking_enabled(policy, requirements)
        if channel == "e_irsaliye"
        else video_tracking_enabled(policy, requirements)
    )
    if not enabled:
        raise ApiError(
            status_code=409,
            code="TRACKING_NOT_ENABLED",
            message=f"Bu işlemde {channel} takibi etkin değil.",
        )


@router.post("/{transaction_id}/evidence/e-irsaliye")
def submit_e_irsaliye_evidence(
    transaction_id: str,
    body: EIrsaliyeSubmitRequest,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
    conn: Connection = Depends(get_db),
) -> EvidenceRecordPublicView:
    require_evidence_submitter(conn, transaction_id, actor)
    _require_channel_enabled(conn, transaction_id, channel="e_irsaliye")

    try:
        record = evidence_records_service.submit_evidence(
            conn,
            transaction_id=transaction_id,
            milestone_id=None,
            evidence_type="e_irsaliye",
            source="external_api",
            actor_context=actor,
            payload={"delivered_quantity": body.delivered_quantity},
            verification_status="verified",
            external_reference=body.external_reference,
        )
    except evidence_records_service.EvidenceIdempotencyConflictError as exc:
        raise ApiError(status_code=409, code=exc.code, message=str(exc)) from exc

    return _to_public_view(record)


def _safe_video_projection(analysis: dict) -> dict:
    """Analyzer çıktısından yalnız bilinen güvenli skaler alanları taşır --
    başka bir analyzer implementasyonu beklenmeyen bir anahtar eklerse dahi
    payload'a sızmaz (allowlist, geçirmeli değil)."""
    counts = analysis.get("counts")
    damage_signals = analysis.get("damage_signals")
    return {
        "counts": (
            {str(k): int(v) for k, v in counts.items()} if isinstance(counts, dict) else {}
        ),
        "unit_count": int(analysis.get("unit_count") or 0),
        "damage_signals": [
            {
                "type": str(signal.get("type", "")),
                "confidence": float(signal.get("confidence", 0.0)),
                "matched_box": bool(signal.get("matched_box", False)),
            }
            for signal in (damage_signals or [])
            if isinstance(signal, dict)
        ],
        "confidence": float(analysis.get("confidence") or 0.0),
    }


def _video_verification_status(payload: dict, confidence_threshold: float) -> str:
    if payload["damage_signals"] and payload["confidence"] >= confidence_threshold:
        return "review_required"
    return "verified"


@router.post("/{transaction_id}/evidence/video")
async def submit_video_evidence(
    transaction_id: str,
    actor: Annotated[ActorContext, Depends(require_authenticated_user)],
    _csrf: Annotated[None, Depends(require_csrf_protection)],
    file: Annotated[UploadFile, File()],
    conn: Connection = Depends(get_db),
) -> EvidenceRecordPublicView:
    require_evidence_submitter(conn, transaction_id, actor)
    _require_channel_enabled(conn, transaction_id, channel="video")

    content = await file.read()
    if len(content) > _MAX_VIDEO_BYTES:
        raise ApiError(
            status_code=413, code="EVIDENCE_FILE_TOO_LARGE", message="Dosya boyutu sınırı aşıldı."
        )
    file_sha256 = hashlib.sha256(content).hexdigest()

    settings = Settings.from_env()
    existing = evidence_records_service.get_by_file_sha256(
        conn, transaction_id=transaction_id, file_sha256=file_sha256
    )
    if existing is not None:
        return _to_public_view(existing)

    storage = make_document_storage_provider(settings)
    stored = storage.store(
        transaction_id=transaction_id,
        # Aynı content hash aynı immutable storage key'ini kullanır. Exact
        # replay bu noktaya gelmeden döner; yarışta provider da idempotenttir.
        document_id=file_sha256,
        original_filename=file.filename or "delivery_evidence",
        media_type=file.content_type,
        content=content,
        expected_sha256=file_sha256,
    )

    original_name = file.filename or "delivery_evidence"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{original_name}")
    try:
        tmp.write(content)
        tmp.close()
        temp_path = Path(tmp.name)
        try:
            analysis = make_video_analyzer(settings).analyze(temp_path)
        except Exception as exc:  # noqa: BLE001 -- analyzer exception metni kalıcı alana yazılmaz
            storage.delete(stored.storage_ref)
            raise ApiError(
                status_code=422, code="EVIDENCE_ANALYSIS_FAILED", message="Video analiz edilemedi."
            ) from exc
    finally:
        Path(tmp.name).unlink(missing_ok=True)

    safe_payload = _safe_video_projection(analysis)
    verification_status = _video_verification_status(
        safe_payload, settings.video_advisory_confidence_threshold
    )

    try:
        record = evidence_records_service.submit_evidence(
            conn,
            transaction_id=transaction_id,
            milestone_id=None,
            evidence_type="video",
            source="analyzer",
            actor_context=actor,
            payload=safe_payload,
            verification_status=verification_status,
            storage_ref=stored.storage_ref,
            file_sha256=file_sha256,
            analyzer_provider=settings.video_provider,
            analyzer_version=_ANALYZER_VERSION,
        )
    except evidence_records_service.EvidenceIdempotencyConflictError as exc:
        existing = evidence_records_service.get_by_file_sha256(
            conn, transaction_id=transaction_id, file_sha256=file_sha256
        )
        if existing is None or existing.storage_ref != stored.storage_ref:
            storage.delete(stored.storage_ref)
        raise ApiError(status_code=409, code=exc.code, message=str(exc)) from exc
    except Exception:
        existing = evidence_records_service.get_by_file_sha256(
            conn, transaction_id=transaction_id, file_sha256=file_sha256
        )
        if existing is None or existing.storage_ref != stored.storage_ref:
            storage.delete(stored.storage_ref)
        raise

    return _to_public_view(record)
