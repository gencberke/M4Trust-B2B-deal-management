"""Plan 04 kapanış entegrasyonu — gerçek app ratification/funding gate'i."""

from __future__ import annotations

from reviews_fixtures import create_real_session, create_real_user
from test_ratifications import _setup_open_package, make_db


def test_real_app_ratification_gate_keeps_same_hash_and_stops_at_funding_pending(
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
    buyer_session = create_real_session(conn, user_id=buyer_user_id)
    seller_session = create_real_session(conn, user_id=seller_user_id)
    conn.commit()
    conn.close()

    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    with TestClient(create_app()) as client:
        client.cookies.set("m4t_session", buyer_session.raw_token)
        buyer_view = client.get(
            f"/api/transactions/{tx_id}/ratification-packages/current"
        )
        assert buyer_view.status_code == 200, buyer_view.text
        package_hash = buyer_view.json()["package_hash"]
        buyer_ratification = client.post(
            f"/api/ratification-packages/{package_id}/ratifications",
            headers={"X-CSRF-Token": buyer_session.raw_csrf_token},
        )
        assert buyer_ratification.status_code == 200, buyer_ratification.text

        client.cookies.clear()
        client.cookies.set("m4t_session", seller_session.raw_token)
        seller_view = client.get(
            f"/api/transactions/{tx_id}/ratification-packages/current"
        )
        assert seller_view.status_code == 200, seller_view.text
        assert seller_view.json()["package_hash"] == package_hash
        seller_ratification = client.post(
            f"/api/ratification-packages/{package_id}/ratifications",
            headers={"X-CSRF-Token": seller_session.raw_csrf_token},
        )
        assert seller_ratification.status_code == 200, seller_ratification.text
        assert seller_ratification.json()["funding_triggered"] is True

    conn = make_db(db_path)
    try:
        assert conn.execute(
            "SELECT state FROM transactions WHERE id = ?", (tx_id,)
        ).fetchone()[0] == "funding_pending"
        assert conn.execute(
            "SELECT COUNT(*) FROM events WHERE transaction_id = ? AND event_type = 'funding_required'",
            (tx_id,),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM mock_payments WHERE transaction_id = ?", (tx_id,)
        ).fetchone()[0] == 0
    finally:
        conn.close()
