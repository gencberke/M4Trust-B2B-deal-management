"""Evidence bundle üretici — event zincirinden zaman damgalı JSON demeti (§6.4/§6.7, Faz 4B).

Ham `markdown`, maskeleme haritası ve ham PII/kart verisi bu bundle'a ASLA
girmez (pci.req.10 kontrol haritasıyla tutarlı) — `transactions` tablosundan
yalnızca `id`/`state`/`created_at` alınır, extraction/event/payload'lar zaten
`privacy.restore()`den sonra kaydedilmiş (maskeleme haritası persist edilmez)
uygulama-seviyesi veridir.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from sqlite3 import Connection

from backend.app.repositories import rule_sets as rule_sets_repo
from backend.app.services.extraction_projection import redacted_extraction_projection
from backend.app.services.tracking_policy import load_tracking_policy


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_bundle(conn: Connection, transaction_id: str) -> dict:
    """İşlem özeti + extraction + validator raporu + onaylar + event zinciri +
    ödeme kayıtları + karar gerekçesinden zaman damgalı bir JSON demeti kurar.
    """
    tx_row = conn.execute(
        "SELECT id, state, created_at FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()
    transaction_summary = (
        {"id": tx_row["id"], "state": tx_row["state"], "created_at": tx_row["created_at"]}
        if tx_row is not None
        else None
    )

    current_rules = rule_sets_repo.get_current(conn, transaction_id)
    extraction = None
    validator_report = None
    if current_rules is not None:
        if current_rules.extraction is not None:
            # Bundle yalnızca capability token'ıyla indirilebilir (routers/evidence.py)
            # ve kanıt paketinin amacı kuralın sözleşmedeki dayanağını göstermektir.
            extraction = redacted_extraction_projection(
                current_rules.extraction.model_dump(mode="json"), include_source_quote=True
            )
        validator_report = {
            "status": current_rules.validator_status,
            "findings": current_rules.validator_report,
        }

    approvals = [
        {"party": r["party"], "created_at": r["created_at"]}
        for r in conn.execute(
            "SELECT party, created_at FROM approvals WHERE transaction_id = ? ORDER BY created_at",
            (transaction_id,),
        ).fetchall()
    ]

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

    decision = None
    for ev in reversed(events):  # zincirdeki EN SON karar gerekçesi
        if ev["event_type"] == "payment_decision_created":
            decision = ev["payload"]
            break

    tracking_policy = load_tracking_policy(conn, transaction_id)

    return {
        "transaction": transaction_summary,
        "extraction": extraction,
        "validator_report": validator_report,
        "tracking_policy": tracking_policy.model_dump(mode="json") if tracking_policy else None,
        "approvals": approvals,
        "events": events,
        "payments": payments,
        "decision": decision,
        "generated_at": _utc_now_iso(),
    }
