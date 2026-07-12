"""Approvals router — çift taraf onayı + havuz ödemesi tetikleme (§4.1/§6.1, Faz 3B).

İki taraf da onayladığında (`buyer_approved ∧ seller_approved`) ve state hâlâ
`awaiting_approval` ise `PaymentProvider.create_pool_payment`
çağrılır ve state `active`'e geçer. Release/approve çağrısı bu router'da YOK —
o, Faz 4'ün decision engine'i tarafından tetiklenir (§6.1: release'i yalnızca
deterministik akış yapar).
"""

from __future__ import annotations

from datetime import datetime, timezone
from sqlite3 import Connection

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.app.config import Settings
from backend.app.db import get_db
from backend.app.eventbus import emit
from backend.app.repositories import rule_sets as rule_sets_repo
from backend.app.repositories.transactions import load_transaction
from backend.app.routers.transactions import resolve_party
from backend.app.services.payment_provider import make_payment_provider
from backend.app.services.settlement import evaluate_settlement
from backend.app.services.tracking_policy import load_tracking_policy

router = APIRouter(prefix="/api/transactions", tags=["approvals"])

# İki onay tamamlandığında havuz ödemesi bu state'lerden tetiklenir — `active`
# (zaten tetiklenmiş) ve `rejected` (akış durmuş) hariç.
_APPROVABLE_STATES = {"awaiting_approval"}


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
    current = rule_sets_repo.get_current(conn, transaction_id)
    if current is None or current.extraction is None:
        return None
    return current.extraction.model_dump(mode="json")


def _policy_not_locked_detail() -> dict:
    """Onay öncesi kilit gereksiniminin sabit, güvenli 409 gövdesi."""
    return {
        "code": "POLICY_NOT_LOCKED",
        "message": "Taraf onayından önce takip politikası kilitlenmelidir.",
        "conflicts": ["TRACKING_POLICY_NOT_LOCKED"],
    }


@router.post("/{transaction_id}/approvals")
def create_approval(
    transaction_id: str, body: ApprovalRequest, conn: Connection = Depends(get_db)
) -> dict:
    settings = Settings.from_env()
    try:
        row = load_transaction(conn, transaction_id)
        if row is None:
            raise HTTPException(status_code=404, detail="İşlem bulunamadı.")

        if row["lifecycle_version"] == "account_v2":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ACCOUNT_RATIFICATION_REQUIRED",
                    "message": "Account işlemler eski capability-token onayı yerine "
                    "ratification package akışını kullanmalıdır.",
                    "conflicts": ["ACCOUNT_RATIFICATION_REQUIRED"],
                },
            )

        # Legacy capability surface'in tamamı aynı kill-switch'e tabidir.
        # Token çözümlemeden önce kontrol edilir; flag kapalıyken geçerli ve
        # geçersiz token arasında oracle oluşmaz.
        if not settings.legacy_capability_access_enabled:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "LEGACY_CAPABILITY_ACCESS_DISABLED",
                    "message": "Legacy capability erişimi kapalı.",
                },
            )

        party = resolve_party(row, body.token)
        if party is None:
            raise HTTPException(status_code=403, detail="Geçersiz token.")

        if row["state"] == "rejected":
            raise HTTPException(
                status_code=409, detail="İşlem reddedildi; onay akışı durduruldu."
            )

        policy = load_tracking_policy(conn, transaction_id)
        if policy is None or policy.status.value != "locked":
            raise HTTPException(status_code=409, detail=_policy_not_locked_detail())

        already_approved = party in _approved_parties(conn, transaction_id)
        if (
            already_approved
            and row["state"] in {"active", "evidence_pending", "decided"}
        ):
            approved = _approved_parties(conn, transaction_id)
            return {
                "state": row["state"],
                "approvals": {"buyer": "buyer" in approved, "seller": "seller" in approved},
            }

        if row["state"] not in _APPROVABLE_STATES:
            raise HTTPException(
                status_code=409,
                detail="İşlem taraf onayına açık durumda değil.",
            )

        if not already_approved:
            conn.execute(
                "INSERT INTO approvals (transaction_id, party, created_at) VALUES (?, ?, ?)",
                (transaction_id, party, _utc_now_iso()),
            )
            emit(conn, transaction_id, f"{party}_approved", {"party": party}, party)

        approved = _approved_parties(conn, transaction_id)
        state = row["state"]

        if {"buyer", "seller"} <= approved and state in _APPROVABLE_STATES:
            if settings.payment_provider != "mock":
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "LEGACY_PAYMENT_PROVIDER_UNSUPPORTED",
                        "message": "Legacy approval yolu yalnız mock provider destekler.",
                    },
                )
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
                settlement = evaluate_settlement(conn, transaction_id, settings)
                if settlement is not None:
                    state_row = load_transaction(conn, transaction_id)
                    if state_row is not None:
                        state = state_row["state"]

        conn.commit()

        return {
            "state": state,
            "approvals": {"buyer": "buyer" in approved, "seller": "seller" in approved},
        }
    finally:
        pass
