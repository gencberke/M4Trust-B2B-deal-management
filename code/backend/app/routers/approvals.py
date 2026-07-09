"""Approvals router — çift taraf onayı + havuz ödemesi tetikleme (§4.1/§6.1, Faz 3B).

İki taraf da onayladığında (`buyer_approved ∧ seller_approved`) ve state hâlâ
`awaiting_review`/`awaiting_approval` ise `PaymentProvider.create_pool_payment`
çağrılır ve state `active`'e geçer. Release/approve çağrısı bu router'da YOK —
o, Faz 4'ün decision engine'i tarafından tetiklenir (§6.1: release'i yalnızca
deterministik akış yapar).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from sqlite3 import Connection

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.config import Settings
from backend.app.db import connect
from backend.app.eventbus import emit
from backend.app.routers.transactions import load_transaction, resolve_party
from backend.app.services.payment_provider import make_payment_provider

router = APIRouter(prefix="/api/transactions", tags=["approvals"])

# İki onay tamamlandığında havuz ödemesi bu state'lerden tetiklenir — `active`
# (zaten tetiklenmiş) ve `rejected` (akış durmuş) hariç.
_APPROVABLE_STATES = {"awaiting_review", "awaiting_approval"}


class ApprovalRequest(BaseModel):
    token: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _approved_parties(conn: Connection, transaction_id: str) -> set[str]:
    return {
        r["party"]
        for r in conn.execute(
            "SELECT DISTINCT party FROM approvals WHERE transaction_id = ?",
            (transaction_id,),
        ).fetchall()
    }


def _load_extraction_for_payment(conn: Connection, transaction_id: str) -> dict | None:
    row = conn.execute(
        "SELECT extraction_json FROM extracted_rules WHERE transaction_id = ? "
        "ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (transaction_id,),
    ).fetchone()
    if row is None or row["extraction_json"] is None:
        return None
    return json.loads(row["extraction_json"])


@router.post("/{transaction_id}/approvals")
def create_approval(transaction_id: str, body: ApprovalRequest) -> dict:
    settings = Settings.from_env()
    conn = connect(settings)
    try:
        row = load_transaction(conn, transaction_id)
        if row is None:
            raise HTTPException(status_code=404, detail="İşlem bulunamadı.")

        party = resolve_party(row, body.token)
        if party is None:
            raise HTTPException(status_code=403, detail="Geçersiz token.")

        if row["state"] == "rejected":
            raise HTTPException(
                status_code=409, detail="İşlem reddedildi; onay akışı durduruldu."
            )

        already_approved = party in _approved_parties(conn, transaction_id)
        if not already_approved:
            conn.execute(
                "INSERT INTO approvals (transaction_id, party, created_at) VALUES (?, ?, ?)",
                (transaction_id, party, _utc_now_iso()),
            )
            emit(conn, transaction_id, f"{party}_approved", {"party": party}, party)

        approved = _approved_parties(conn, transaction_id)
        state = row["state"]

        if {"buyer", "seller"} <= approved and state in _APPROVABLE_STATES:
            extraction = _load_extraction_for_payment(conn, transaction_id)
            if extraction is not None:
                commercial = extraction.get("commercial_terms") or {}
                amount = commercial.get("total_amount")
                currency = commercial.get("currency")
                provider = make_payment_provider(settings, conn)
                provider.create_pool_payment(
                    amount=amount, currency=currency, other_trx_code=transaction_id
                )
                conn.execute(
                    "UPDATE transactions SET state = 'active' WHERE id = ?", (transaction_id,)
                )
                state = "active"

        conn.commit()

        return {
            "state": state,
            "approvals": {"buyer": "buyer" in approved, "seller": "seller" in approved},
        }
    finally:
        conn.close()
