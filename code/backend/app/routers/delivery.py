"""Delivery router — teslimat kanıtı event'leri + paylaşımlı decision denemesi (§4.1, §6.1, §6.5, Faz 4B).

İki endpoint (e-irsaliye simülasyonu, video upload) yalnızca işlem fonlanmışken
(`active`/`evidence_pending`) kabul edilir. Her kanıt event'inden hemen sonra
`_attempt_decision()` çağrılır: `decide()` saf fonksiyonuna girdi hazırlar,
`hold` dışındaki her aksiyonda §6.1 release guard'ı (iki taraf da onaylamış +
uygun state) sağlanmadan `PaymentProvider.approve_pool_payment` ASLA çağrılmaz.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from sqlite3 import Connection

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict

from backend.app.config import Settings
from backend.app.db import connect
from backend.app.eventbus import emit
from backend.app.routers.transactions import load_transaction
from backend.app.schemas.extraction import ExtractionJSON
from backend.app.services.decision import DeliveryEvidence, decide
from backend.app.services.payment_provider import make_payment_provider
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


def _load_extraction(conn: Connection, transaction_id: str) -> dict | None:
    """Persist edilmiş (RESTORE edilmiş) son extraction JSON'ını yükler.

    `routers/transactions.py::_load_extraction` ile aynı sorgu — `approvals.py`
    da kendi kopyasını tutar (mevcut proje deseni); paylaşılan bir private
    fonksiyonun router'lar arası import edilmesi yerine küçük tekrar tercih
    edilmiştir.
    """
    row = conn.execute(
        "SELECT extraction_json FROM extracted_rules WHERE transaction_id = ? "
        "ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (transaction_id,),
    ).fetchone()
    if row is None or row["extraction_json"] is None:
        return None
    return json.loads(row["extraction_json"])


def _approved_parties(conn: Connection, transaction_id: str) -> set[str]:
    return {
        r["party"]
        for r in conn.execute(
            "SELECT DISTINCT party FROM approvals WHERE transaction_id = ?",
            (transaction_id,),
        ).fetchall()
    }


def _latest_event_payload(conn: Connection, transaction_id: str, event_type: str) -> dict | None:
    row = conn.execute(
        "SELECT payload FROM events WHERE transaction_id = ? AND event_type = ? "
        "ORDER BY id DESC LIMIT 1",
        (transaction_id, event_type),
    ).fetchone()
    if row is None or row["payload"] is None:
        return None
    return json.loads(row["payload"])


def _current_state(conn: Connection, transaction_id: str) -> str:
    row = conn.execute(
        "SELECT state FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()
    return row["state"]


def _attempt_decision(conn: Connection, transaction_id: str, settings: Settings) -> dict | None:
    """Toplanmış kanıtlarla `decide()`'ı çağırır, karara göre ödeme aksiyonunu tetikler.

    Dönen sözlük her zaman `{"action", "capture_ratio", "rationale"}` taşır
    (guard başarısız olursa ek `"note"` alanı eklenir); hiç extraction yoksa
    (henüz karar verilecek bir şey yoksa) `None` döner. Commit ÇAĞIRMAZ —
    çağıran (endpoint) sorumludur (mevcut router deseniyle tutarlı).
    """
    extraction_dict = _load_extraction(conn, transaction_id)
    if extraction_dict is None:
        return None
    extraction = ExtractionJSON.model_validate(extraction_dict)

    e_irsaliye = _latest_event_payload(conn, transaction_id, "e_irsaliye_received")
    video = _latest_event_payload(conn, transaction_id, "delivery_video_analyzed")
    result = decide(extraction, DeliveryEvidence(e_irsaliye=e_irsaliye, video=video))

    decision_payload = {
        "action": result.action,
        "capture_ratio": result.capture_ratio,
        "rationale": result.rationale,
    }

    if result.action == "hold":
        # Durum `evidence_pending`de kalır; ek event üretilmez (§5 state machine).
        return decision_payload

    if result.action in {"capture", "partial_capture"}:
        # §6.1 release guard: yalnızca iki taraf da onaylamışsa VE state uygunsa
        # (buyer_approved ∧ seller_approved ∧ state ∈ {active, evidence_pending}).
        approved = _approved_parties(conn, transaction_id)
        state = _current_state(conn, transaction_id)
        guard_ok = {"buyer", "seller"} <= approved and state in _FUNDED_STATES
        if not guard_ok:
            return {
                **decision_payload,
                "note": (
                    "Ödeme aksiyonu uygulanmadı: her iki taraf onaylamamış "
                    "veya işlem uygun durumda değil (§6.1 release guard)."
                ),
            }

        emit(conn, transaction_id, "payment_decision_created", decision_payload, "decision")
        provider = make_payment_provider(settings, conn)
        provider.approve_pool_payment(
            other_trx_code=transaction_id, capture_ratio=result.capture_ratio
        )
        payment_status = "released" if result.capture_ratio >= 1.0 else "partially_released"
        emit(
            conn,
            transaction_id,
            "mock_payment_executed",
            {"status": payment_status, "capture_ratio": result.capture_ratio},
            "payment_provider",
        )
        conn.execute("UPDATE transactions SET state = 'decided' WHERE id = ?", (transaction_id,))
        return decision_payload

    # result.action == "dispute" — capture çağrısı ASLA yapılmaz (§6.1).
    emit(conn, transaction_id, "payment_decision_created", decision_payload, "decision")
    emit(conn, transaction_id, "dispute_opened", {"rationale": result.rationale}, "decision")
    conn.execute("UPDATE transactions SET state = 'decided' WHERE id = ?", (transaction_id,))
    return decision_payload


def _mark_evidence_pending_if_active(conn: Connection, transaction_id: str, state: str) -> None:
    if state == "active":
        conn.execute(
            "UPDATE transactions SET state = 'evidence_pending' WHERE id = ?", (transaction_id,)
        )


@router.post("/{transaction_id}/events/e-irsaliye")
def receive_e_irsaliye(transaction_id: str, body: EIrsaliyeEvent) -> dict:
    """E-irsaliye simülasyon event'i — kanıt kaydeder, ardından decision dener."""
    settings = Settings.from_env()
    conn = connect(settings)
    try:
        row = load_transaction(conn, transaction_id)
        if row is None:
            raise HTTPException(status_code=404, detail="İşlem bulunamadı.")
        if row["state"] not in _FUNDED_STATES:
            raise HTTPException(status_code=409, detail=_NOT_FUNDED_DETAIL)

        emit(conn, transaction_id, "e_irsaliye_received", body.model_dump(), "e_irsaliye")
        _mark_evidence_pending_if_active(conn, transaction_id, row["state"])

        decision = _attempt_decision(conn, transaction_id, settings)
        state = _current_state(conn, transaction_id)
        conn.commit()

        return {"state": state, "decision": decision}
    finally:
        conn.close()


@router.post("/{transaction_id}/delivery-video")
async def upload_delivery_video(transaction_id: str, file: UploadFile = File(...)) -> dict:
    """Teslimat videosu upload'ı — fake analiz senkron/hafif olduğundan inline koşulur.

    Böylece cevap doğrudan güncel kararı yansıtır (BackgroundTask kullanılmaz,
    aksi halde cevap dönerken karar henüz üretilmemiş olurdu).
    """
    settings = Settings.from_env()
    conn = connect(settings)
    try:
        row = load_transaction(conn, transaction_id)
        if row is None:
            raise HTTPException(status_code=404, detail="İşlem bulunamadı.")
        if row["state"] not in _FUNDED_STATES:
            raise HTTPException(status_code=409, detail=_NOT_FUNDED_DETAIL)

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
        _mark_evidence_pending_if_active(conn, transaction_id, row["state"])

        decision = _attempt_decision(conn, transaction_id, settings)
        state = _current_state(conn, transaction_id)
        conn.commit()

        return {"state": state, "analysis": analysis, "decision": decision}
    finally:
        conn.close()
