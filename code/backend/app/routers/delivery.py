"""Delivery router — teslimat kanıtı event'leri (§4.1, §6.1).

İki endpoint (e-irsaliye simülasyonu, video upload) yalnızca işlem fonlanmışken
(`active`/`evidence_pending`) VE ilgili kanıt kanalı bu işlem için etkinken
kabul edilir. Kanal, sözleşmesel zorunluluktan (extraction) veya yöneticinin
kilitlediği takip politikasından gelir; ikisi de yoksa endpoint 409 döner.

Ödeme/karar orkestrasyonunun sahibi bu router DEĞİLDİR: kanıt event'i yazıldıktan
sonra `services/settlement.py::evaluate_settlement` çağrılır — release guard,
provider çağrısı ve state geçişi orada tek yerde tutulur (§6.1). Bu yüzden
opsiyonel video anomalisi buradan `dispute_opened` üretmez; karar `hold` +
manuel inceleme olur.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from sqlite3 import Connection

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict

from backend.app.config import Settings
from backend.app.db import get_db
from backend.app.eventbus import emit
from backend.app.repositories.transactions import load_transaction
from backend.app.routers.transactions import resolve_manager, resolve_party
from backend.app.schemas.extraction import ExtractionJSON, RequiredEvidence
from backend.app.services.settlement import evaluate_settlement
from backend.app.services.tracking_policy import (
    contractual_required_evidence,
    e_irsaliye_tracking_enabled,
    load_tracking_policy,
    video_tracking_enabled,
)
from backend.app.services.video import make_video_analyzer

router = APIRouter(prefix="/api/transactions", tags=["delivery"])

# Havuz ödemesi tutulmadan (create_pool_payment öncesi) kanıt event'i kabul
# edilmez; `evidence_pending` ise zaten en az bir kanıt işlenmiş demektir.
_FUNDED_STATES = {"active", "evidence_pending"}
_NOT_FUNDED_DETAIL = "İşlem henüz aktif değil / havuz ödemesi yok."


class EIrsaliyeEvent(BaseModel):
    """E-irsaliye simülasyon payload'ı — bilinmeyen ek alanlar sessizce yok sayılır."""

    model_config = ConfigDict(extra="ignore")

    delivered_quantity: float


def _conflict(code: str, message: str, conflicts: list[str]) -> HTTPException:
    """Manager policy uçlarıyla aynı `{code, message, conflicts}` 409 gövdesi."""
    return HTTPException(
        status_code=409, detail={"code": code, "message": message, "conflicts": conflicts}
    )


def _load_extraction(conn: Connection, transaction_id: str) -> ExtractionJSON | None:
    """Persist edilmiş (restore edilmiş) son extraction'ı doğrulanmış olarak yükler."""
    row = conn.execute(
        "SELECT extraction_json FROM extracted_rules WHERE transaction_id = ? "
        "ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (transaction_id,),
    ).fetchone()
    if row is None or row["extraction_json"] is None:
        return None
    try:
        return ExtractionJSON.model_validate(json.loads(row["extraction_json"]))
    except (TypeError, ValueError):
        return None


def _contractual_requirements(conn: Connection, transaction_id: str) -> set[RequiredEvidence]:
    extraction = _load_extraction(conn, transaction_id)
    return set() if extraction is None else contractual_required_evidence(extraction)


def _current_state(conn: Connection, transaction_id: str) -> str:
    row = conn.execute(
        "SELECT state FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()
    return row["state"]


def _guard_evidence_channel(conn: Connection, transaction_id: str, *, channel: str) -> None:
    """404 / kanal kapalı / karar verilmiş / fonlanmamış kontrollerini sırayla uygular.

    Sıra bilinçlidir. Önce "bu işlem bu kanıtı hiç takip ediyor mu?" sorulur:
    takip edilmeyen bir kanal, işlemin hangi durumda olduğundan bağımsız olarak
    kapalıdır. Takip edilen bir kanalda ise karar verilmiş işleme geç gelen kanıt,
    herhangi bir video analizi yapılmadan reddedilir.
    """
    row = load_transaction(conn, transaction_id)
    if row is None:
        raise HTTPException(status_code=404, detail="İşlem bulunamadı.")

    policy = load_tracking_policy(conn, transaction_id)
    requirements = _contractual_requirements(conn, transaction_id)

    if channel == "e_irsaliye":
        if not e_irsaliye_tracking_enabled(policy, requirements):
            raise _conflict(
                "TRACKING_NOT_ENABLED",
                "Bu işlemde e-irsaliye takibi etkin değil.",
                ["E_IRSALIYE_TRACKING_DISABLED"],
            )
    elif not video_tracking_enabled(policy, requirements):
        raise _conflict(
            "TRACKING_NOT_ENABLED",
            "Bu işlemde video takibi etkin değil.",
            ["VIDEO_TRACKING_DISABLED"],
        )

    if row["state"] == "decided":
        raise _conflict(
            "TRANSACTION_DECIDED",
            "İşlem karara bağlandı; yeni teslimat kanıtı kabul edilmiyor.",
            ["TRANSACTION_ALREADY_DECIDED"],
        )

    if row["state"] not in _FUNDED_STATES:
        raise HTTPException(status_code=409, detail=_NOT_FUNDED_DETAIL)


def _authorize_delivery_submission(
    conn: Connection, transaction_id: str, token: str | None
) -> None:
    """Teslimat kanıtını yalnız satıcı veya yönetici capability'siyle kabul eder."""
    row = load_transaction(conn, transaction_id)
    if row is None:
        raise HTTPException(status_code=404, detail="İşlem bulunamadı.")

    party = resolve_party(row, token or "")
    if party != "seller" and not resolve_manager(row, token or ""):
        raise HTTPException(status_code=403, detail="Teslimat kanıtı gönderme yetkiniz yok.")


@router.post("/{transaction_id}/events/e-irsaliye")
def receive_e_irsaliye(
    transaction_id: str,
    body: EIrsaliyeEvent,
    token: str | None = None,
    conn: Connection = Depends(get_db),
) -> dict:
    """E-irsaliye simülasyon event'i — birincil nicel kanıt; ardından settlement."""
    settings = Settings.from_env()
    try:
        _authorize_delivery_submission(conn, transaction_id, token)
        _guard_evidence_channel(conn, transaction_id, channel="e_irsaliye")

        emit(conn, transaction_id, "e_irsaliye_received", body.model_dump(), "e_irsaliye")
        decision = evaluate_settlement(conn, transaction_id, settings)
        state = _current_state(conn, transaction_id)
        conn.commit()

        return {"state": state, "decision": decision}
    finally:
        pass


@router.post("/{transaction_id}/delivery-video")
async def upload_delivery_video(
    transaction_id: str,
    file: UploadFile = File(...),
    token: str | None = None,
    conn: Connection = Depends(get_db),
) -> dict:
    """Teslimat videosu upload'ı — analiz ikincil (advisory) sinyaldir, miktar üretmez.

    Fake analiz senkron/hafif olduğundan inline koşulur; böylece cevap doğrudan
    güncel kararı yansıtır.
    """
    settings = Settings.from_env()
    try:
        _authorize_delivery_submission(conn, transaction_id, token)
        _guard_evidence_channel(conn, transaction_id, channel="video")

        contents = await file.read()
        original_name = file.filename or "delivery_video"
        # `FakeVideoAnalyzer` dosya adındaki ipucuna (ör. "hasarli") bakar; bu
        # yüzden yalnızca uzantı değil TÜM orijinal ad `suffix` olarak korunur.
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=f"_{original_name}")
        try:
            tmp.write(contents)
        finally:
            tmp.close()
        temp_path = Path(tmp.name)

        try:
            analysis = make_video_analyzer(settings).analyze(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)

        emit(conn, transaction_id, "delivery_video_analyzed", analysis, "video")
        decision = evaluate_settlement(conn, transaction_id, settings)
        state = _current_state(conn, transaction_id)
        conn.commit()

        return {"state": state, "analysis": analysis, "decision": decision}
    finally:
        pass
