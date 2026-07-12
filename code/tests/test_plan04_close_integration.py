"""Plan 04 kapanış entegrasyonu — gerçek app ratification/funding gate'i.

Plan 06A cutover'ından sonra çift ratification artık funding_pending'de durmaz;
funding unit'ler ağsız fake gateway ile gerçekten pool'lanır ve transaction
`active`'e geçer (funding exactly-once).
"""

from __future__ import annotations

from reviews_fixtures import create_real_session, create_real_user
from test_ratifications import _setup_open_package, make_db


def test_real_app_ratification_gate_keeps_same_hash_and_funds_units(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "plan04-close.db"
    monkeypatch.setenv("DB_PATH", str(db_path))

    conn = make_db(db_path)
    tx_id = "tx-plan04-close"
    package_id = _setup_open_package(conn, tx_id)
    buyer_user_id = create_real_user(
        conn, email_normalized="close-buyer@example.com", user_id="u-buyer"
    )
    seller_user_id = create_real_user(
        conn, email_normalized="close-seller@example.com", user_id="u-seller"
    )
    for entity_id, legal_name, user_id, membership_id in (
        ("entity-buyer", "Buyer Entity", buyer_user_id, "membership-close-buyer"),
        ("entity-seller", "Seller Entity", seller_user_id, "membership-close-seller"),
    ):
        conn.execute(
            "INSERT INTO legal_entities (id, entity_type, legal_name, tax_identifier_type, "
            "tax_identifier_ciphertext, tax_identifier_lookup_hmac, tax_identifier_last4, "
            "verification_status, created_by_user_id, created_at, updated_at) "
            "VALUES (?, 'company', ?, 'vkn', 'cipher', ?, '0000', 'self_declared', ?, 'now', 'now')",
            (entity_id, legal_name, f"hmac-{entity_id}", user_id),
        )
        conn.execute(
            "INSERT INTO memberships (id, user_id, legal_entity_id, role, status, created_at) "
            "VALUES (?, ?, ?, 'owner', 'active', 'now')",
            (membership_id, user_id, entity_id),
        )
    buyer_session = create_real_session(conn, user_id=buyer_user_id)
    seller_session = create_real_session(conn, user_id=seller_user_id)
    conn.commit()
    conn.close()

    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    with TestClient(create_app()) as client:
        client.cookies.set("m4t_session", buyer_session.raw_token)
        buyer_view = client.get(
            f"/api/transactions/{tx_id}/ratification-packages/current",
            headers={"X-Acting-Entity-ID": "entity-buyer"},
        )
        assert buyer_view.status_code == 200, buyer_view.text
        package_hash = buyer_view.json()["package_hash"]
        buyer_ratification = client.post(
            f"/api/ratification-packages/{package_id}/ratifications",
            headers={
                "X-CSRF-Token": buyer_session.raw_csrf_token,
                "X-Acting-Entity-ID": "entity-buyer",
            },
        )
        assert buyer_ratification.status_code == 200, buyer_ratification.text

        client.cookies.clear()
        client.cookies.set("m4t_session", seller_session.raw_token)
        seller_view = client.get(
            f"/api/transactions/{tx_id}/ratification-packages/current",
            headers={"X-Acting-Entity-ID": "entity-seller"},
        )
        assert seller_view.status_code == 200, seller_view.text
        assert seller_view.json()["package_hash"] == package_hash
        seller_ratification = client.post(
            f"/api/ratification-packages/{package_id}/ratifications",
            headers={
                "X-CSRF-Token": seller_session.raw_csrf_token,
                "X-Acting-Entity-ID": "entity-seller",
            },
        )
        assert seller_ratification.status_code == 200, seller_ratification.text
        assert seller_ratification.json()["funding_triggered"] is True

    conn = make_db(db_path)
    try:
        assert conn.execute(
            "SELECT state FROM transactions WHERE id = ?", (tx_id,)
        ).fetchone()[0] == "active"
        # funding_required ve funding_units_pool_created event'leri exactly-once.
        assert conn.execute(
            "SELECT COUNT(*) FROM events WHERE transaction_id = ? AND event_type = 'funding_required'",
            (tx_id,),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM events WHERE transaction_id = ? "
            "AND event_type = 'funding_units_pool_created'",
            (tx_id,),
        ).fetchone()[0] == 1
        # Account yolu legacy mock_payments'a dokunmaz; gerçek funding funding_units
        # + provider_payments üzerinden yürür ve tüm unit'ler pool_created olur.
        assert conn.execute(
            "SELECT COUNT(*) FROM mock_payments WHERE transaction_id = ?", (tx_id,)
        ).fetchone()[0] == 0
        unit_statuses = [
            row[0]
            for row in conn.execute(
                "SELECT status FROM funding_units WHERE transaction_id = ?", (tx_id,)
            )
        ]
        assert unit_statuses and all(status == "pool_created" for status in unit_statuses)
        assert conn.execute(
            "SELECT COUNT(*) FROM provider_payments WHERE funding_unit_id IN "
            "(SELECT id FROM funding_units WHERE transaction_id = ?)",
            (tx_id,),
        ).fetchone()[0] == len(unit_statuses)
    finally:
        conn.close()
