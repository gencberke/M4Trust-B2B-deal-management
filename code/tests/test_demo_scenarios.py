"""Plan 14 / P1 — `services/demo_scenarios.py` gerçek-servis senaryo motoru.

Her hedef state YALNIZ gerçek servislerle beklenen account_v2 state'ine ulaşır;
settled yolunda release-guard artefaktları (approved unit'ler + release
instruction'ları) oluşur; senaryo üretimi idempotenttir (aynı tx_id re-run
duplicate üretmez).
"""

from __future__ import annotations

import pytest

from backend.app.config import Settings
from backend.app.db import connect, init_db
from backend.app.repositories import funding_units as funding_units_repo
from backend.app.services import demo_scenarios
from backend.app.services.demo_scenarios import DemoEntityRef, DemoParties
from reviews_fixtures import create_real_user


def _create_entity(conn, entity_id: str, user_id: str) -> None:
    conn.execute(
        "INSERT INTO legal_entities (id, entity_type, legal_name, tax_identifier_type, "
        "tax_identifier_ciphertext, tax_identifier_lookup_hmac, tax_identifier_last4, "
        "verification_status, created_by_user_id, created_at, updated_at) "
        "VALUES (?, 'company', ?, 'vkn', 'cipher', ?, '1234', 'self_declared', ?, 'now', 'now')",
        (entity_id, entity_id, entity_id, user_id),
    )


def _add_membership(conn, membership_id: str, user_id: str, entity_id: str) -> None:
    conn.execute(
        "INSERT INTO memberships (id, user_id, legal_entity_id, role, status, created_at) "
        "VALUES (?, ?, ?, 'owner', 'active', 'now')",
        (membership_id, user_id, entity_id),
    )


def _setup(tmp_path):
    """Gerçek users/entities/memberships + izole DB; DemoParties döner."""
    settings = Settings.from_env()  # conftest isolated_db env'ini kullanır
    conn = connect(settings)
    init_db(conn)
    create_real_user(conn, email_normalized="demo-buyer@example.com", user_id="u-buyer")
    create_real_user(conn, email_normalized="demo-seller@example.com", user_id="u-seller")
    _create_entity(conn, "entity-buyer", "u-buyer")
    _create_entity(conn, "entity-seller", "u-seller")
    _add_membership(conn, "m-buyer", "u-buyer", "entity-buyer")
    _add_membership(conn, "m-seller", "u-seller", "entity-seller")
    conn.commit()

    parties = DemoParties(
        buyer=DemoEntityRef(
            user_id="u-buyer", entity_id="entity-buyer",
            email="demo-buyer@example.com", display_name="ABC A.Ş.", tax_id="1111111111",
        ),
        seller=DemoEntityRef(
            user_id="u-seller", entity_id="entity-seller",
            email="demo-seller@example.com", display_name="XYZ Ltd.", tax_id="2222222222",
        ),
    )
    return conn, settings, parties


def _state(conn, tx_id: str) -> str:
    return conn.execute("SELECT state FROM transactions WHERE id = ?", (tx_id,)).fetchone()[0]


def test_awaiting_review_scenario(tmp_path) -> None:
    conn, settings, parties = _setup(tmp_path)
    result = demo_scenarios.create_scenario(
        conn, settings, scenario="awaiting_review", parties=parties,
        transaction_id="tx-review", title="Demo review",
    )
    assert result["state"] == "awaiting_review"
    # Blocking pre_ratification validator case açılmış olmalı.
    assert conn.execute(
        "SELECT COUNT(*) FROM review_cases WHERE transaction_id = ? AND status = 'open'",
        ("tx-review",),
    ).fetchone()[0] >= 1
    conn.close()


def test_awaiting_ratification_scenario(tmp_path) -> None:
    conn, settings, parties = _setup(tmp_path)
    result = demo_scenarios.create_scenario(
        conn, settings, scenario="awaiting_ratification", parties=parties,
        transaction_id="tx-ar", title="Demo awaiting ratification",
    )
    assert result["state"] == "awaiting_ratification"
    # Policy kilitli, package open, henüz ratify yok.
    assert conn.execute(
        "SELECT status FROM tracking_policies WHERE transaction_id = ?", ("tx-ar",)
    ).fetchone()[0] == "locked"
    conn.close()


def test_active_scenario_two_pooled_units(tmp_path) -> None:
    conn, settings, parties = _setup(tmp_path)
    result = demo_scenarios.create_scenario(
        conn, settings, scenario="active", parties=parties,
        transaction_id="tx-active", title="Demo active",
    )
    assert result["state"] == "active"
    units = funding_units_repo.list_for_transaction(conn, "tx-active")
    assert len(units) == 2
    assert all(u["status"] == "pool_created" for u in units)
    conn.close()


def test_active_partial_scenario_one_unit_released(tmp_path) -> None:
    conn, settings, parties = _setup(tmp_path)
    demo_scenarios.create_scenario(
        conn, settings, scenario="active_partial", parties=parties,
        transaction_id="tx-partial", title="Demo partial",
    )
    assert _state(conn, "tx-partial") == "active"
    statuses = sorted(u["status"] for u in funding_units_repo.list_for_transaction(conn, "tx-partial"))
    assert statuses == ["approved", "pool_created"]
    conn.close()


def test_settled_scenario_release_guard_artifacts(tmp_path) -> None:
    conn, settings, parties = _setup(tmp_path)
    result = demo_scenarios.create_scenario(
        conn, settings, scenario="settled", parties=parties,
        transaction_id="tx-settled", title="Demo settled",
    )
    assert result["state"] == "settled"
    units = funding_units_repo.list_for_transaction(conn, "tx-settled")
    assert len(units) == 2
    assert all(u["status"] == "approved" for u in units)
    # Release-guard artefaktları: her unit için idempotent approve instruction'ı.
    assert conn.execute(
        "SELECT COUNT(*) FROM release_instructions WHERE operation_type = 'approve_pool_payment'"
    ).fetchone()[0] == 2
    assert conn.execute(
        "SELECT COUNT(*) FROM provider_operations WHERE operation_type = 'approve_pool_payment'"
    ).fetchone()[0] == 2
    conn.close()


def test_disputed_scenario_open_dispute_blocks(tmp_path) -> None:
    conn, settings, parties = _setup(tmp_path)
    demo_scenarios.create_scenario(
        conn, settings, scenario="disputed", parties=parties,
        transaction_id="tx-disputed", title="Demo disputed",
    )
    assert _state(conn, "tx-disputed") == "active"
    assert conn.execute(
        "SELECT COUNT(*) FROM disputes WHERE transaction_id = ? AND status = 'open'",
        ("tx-disputed",),
    ).fetchone()[0] == 1
    conn.close()


def test_scenario_creation_is_idempotent(tmp_path) -> None:
    conn, settings, parties = _setup(tmp_path)
    first = demo_scenarios.create_scenario(
        conn, settings, scenario="settled", parties=parties,
        transaction_id="tx-idem", title="Demo idempotent",
    )
    units_first = funding_units_repo.list_for_transaction(conn, "tx-idem")
    approve_ops_first = conn.execute(
        "SELECT COUNT(*) FROM provider_operations WHERE operation_type = 'approve_pool_payment'"
    ).fetchone()[0]

    second = demo_scenarios.create_scenario(
        conn, settings, scenario="settled", parties=parties,
        transaction_id="tx-idem", title="Demo idempotent",
    )
    units_second = funding_units_repo.list_for_transaction(conn, "tx-idem")

    assert first["state"] == second["state"] == "settled"
    assert len(units_first) == len(units_second) == 2  # duplicate unit üretilmedi
    approve_ops_second = conn.execute(
        "SELECT COUNT(*) FROM provider_operations WHERE operation_type = 'approve_pool_payment'"
    ).fetchone()[0]
    assert approve_ops_second == approve_ops_first  # tekrar approve edilmedi
    conn.close()


def test_advance_rejects_unknown_target(tmp_path) -> None:
    conn, settings, parties = _setup(tmp_path)
    demo_scenarios.create_uploaded(
        conn, settings, transaction_id="tx-x", parties=parties,
        profile="delivery", title="Demo x",
    )
    with pytest.raises(demo_scenarios.DemoScenarioError):
        demo_scenarios.advance(
            conn, settings, transaction_id="tx-x", target_state="nonsense", parties=parties,
        )
    conn.close()
