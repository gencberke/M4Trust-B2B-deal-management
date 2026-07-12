"""Plan 09 tracking-policy history and canonical package binding."""

from __future__ import annotations

from backend.app.db import connect, init_db
from backend.app.schemas.extraction import ExtractionJSON
from backend.app.schemas.tracking import TrackingMode
from backend.app.services.tracking_policy import (
    create_draft_policy,
    lock_manager_policy,
    update_manager_policy,
)


def _extraction() -> ExtractionJSON:
    return ExtractionJSON.model_validate(
        {
            "contract_id": "plan09-policy",
            "parties": {
                "buyer": {"name": "Buyer", "tax_id": None},
                "seller": {"name": "Seller", "tax_id": None},
            },
            "commercial_terms": {
                "currency": "TRY",
                "total_amount": 100,
                "goods": [{"name": "Service", "quantity": 1, "unit": "job"}],
                "delivery_deadline": None,
            },
            "payment_rules": [
                {
                    "milestone": "Approval",
                    "trigger": "approval",
                    "percentage": 100,
                    "required_evidence": ["contract"],
                    "source_quote": "safe",
                    "confidence": 1,
                }
            ],
            "risk_flags": [],
            "needs_manual_review": False,
        }
    )


def test_policy_mutations_append_immutable_versions() -> None:
    conn = connect()
    try:
        init_db(conn)
        conn.execute(
            "INSERT INTO transactions "
            "(id,state,buyer_token,seller_token,manager_token,markdown,masked_markdown,created_at) "
            "VALUES ('tx-p09','awaiting_approval','b','s','m','','','2026-07-12T00:00:00Z')"
        )
        create_draft_policy(conn, "tx-p09")
        update_manager_policy(
            conn,
            "tx-p09",
            _extraction(),
            physical_delivery_confirmed=False,
            tracking_mode=TrackingMode.off,
            configured_by_user_id=None,
        )
        lock_manager_policy(conn, "tx-p09", _extraction())

        rows = conn.execute(
            "SELECT version,status,snapshot_hash FROM tracking_policy_versions "
            "WHERE transaction_id='tx-p09' ORDER BY version"
        ).fetchall()
        assert [row["version"] for row in rows] == [1, 2, 3]
        assert [row["status"] for row in rows] == ["draft", "draft", "locked"]
        assert len({row["snapshot_hash"] for row in rows}) == 3
        try:
            conn.execute(
                "UPDATE tracking_policy_versions SET status='draft' "
                "WHERE transaction_id='tx-p09' AND version=3"
            )
        except Exception as exc:  # sqlite trigger is the contract
            assert "immutable" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("history row unexpectedly mutable")
    finally:
        conn.close()
