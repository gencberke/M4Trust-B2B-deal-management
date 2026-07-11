"""Plan 06A early branch: migration, schedule materialization, fake funding."""

from __future__ import annotations

import json
from importlib import import_module

from backend.app.db import connect, init_db
from backend.app.repositories import funding_units as funding_units_repo
from backend.app.services.access_control import ActorContext
from backend.app.services.payments import funding_coordinator
from backend.app.services.ratification_package import canonical_package_json, compute_package_hash


def _apply_6a(conn) -> None:
    for name in (
        "015_milestones",
        "016_funding_units_provider_payments",
        "017_release_instructions",
    ):
        table_name = {
            "015_milestones": "milestones",
            "016_funding_units_provider_payments": "funding_units",
            "017_release_instructions": "release_instructions",
        }[name]
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
            (table_name,),
        ).fetchone()
        if exists is None:
            import_module(f"backend.app.db.migrations.{name}").apply(conn)


def _seed_complete_package(conn) -> tuple[str, str]:
    tx_id = "tx-6a-demo"
    package_id = "package-6a-demo"
    conn.execute(
        "INSERT INTO transactions (id, state, buyer_token, seller_token, manager_token, "
        "markdown, masked_markdown, created_at, lifecycle_version, owner_entity_id) "
        "VALUES (?, 'funding_pending', NULL, NULL, NULL, NULL, NULL, 'now', 'account_v2', 'entity')",
        (tx_id,),
    )
    conn.execute(
        "INSERT INTO contract_documents (id, transaction_id, version, original_filename, "
        "storage_ref, content_sha256, status, created_at) VALUES ('doc-6a', ?, 1, 'x.md', "
        "'tx-6a/doc', 'doc-hash', 'active', 'now')",
        (tx_id,),
    )
    conn.execute(
        "INSERT INTO rule_set_versions (id, transaction_id, version, rules_json, rules_hash, "
        "status, validator_status, created_by_actor_type, created_at) VALUES "
        "('rule-6a', ?, 1, '{}', 'rule-hash', 'ratifiable', 'PASS', 'system', 'now')",
        (tx_id,),
    )
    payload = {
        "provider_profile": "moka_standard_v1",
        "rule_set": {"id": "rule-6a"},
        "funding_schedule": {
            "total_amount_minor": 1000,
            "milestones": [
                {
                    "rule_index": 0,
                    "title": "Teslimat",
                    "trigger_type": "delivery",
                    "basis_points": 10000,
                    "amount_minor": 1000,
                    "currency": "TRY",
                    "required_evidence": ["e_irsaliye"],
                    "release_mode": "fixed_tranches",
                    "funding_units": [
                        {
                            "sequence": 1,
                            "amount_minor": 600,
                            "eligibility_type": "verified_quantity",
                            "eligibility_payload": {"quantity_threshold": 6},
                        },
                        {
                            "sequence": 2,
                            "amount_minor": 400,
                            "eligibility_type": "verified_quantity",
                            "eligibility_payload": {"quantity_threshold": 10},
                        },
                    ],
                }
            ],
        },
    }
    canonical = canonical_package_json(payload)
    conn.execute(
        """INSERT INTO ratification_packages (
            id, transaction_id, version, document_id, rule_set_version_id,
            tracking_policy_version_id, canonical_payload_json, document_hash,
            rule_set_hash, participant_snapshot_hash, tracking_policy_hash,
            package_hash, status, created_at, opened_at, completed_at
        ) VALUES (?, ?, 1, 'doc-6a', 'rule-6a', NULL, ?, 'doc-hash', 'rule-hash',
                  'participant-hash', 'policy-hash', ?, 'complete', 'now', 'now', 'now')""",
        (package_id, tx_id, canonical, compute_package_hash(canonical)),
    )
    conn.commit()
    return tx_id, package_id


def _system_actor() -> ActorContext:
    return ActorContext(actor_type="anonymous", auth_method="none")


def test_6a_materializes_schedule_and_funds_each_unit_once(monkeypatch) -> None:
    conn = connect()
    init_db(conn)
    _apply_6a(conn)
    tx_id, package_id = _seed_complete_package(conn)

    result = funding_coordinator.ensure_pool_funded(
        conn, tx_id, package_id, _system_actor()
    )
    assert result.status == "active"
    units = funding_units_repo.list_for_transaction(conn, tx_id)
    assert [unit["other_trx_code"] for unit in units] == [
        "M4T-tx6ademo-P1-U01",
        "M4T-tx6ademo-P1-U02",
    ]
    assert [unit["status"] for unit in units] == ["pool_created", "pool_created"]
    assert conn.execute("SELECT COUNT(*) FROM milestones").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM provider_payments").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM provider_operations").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM fake_provider_payments").fetchone()[0] == 2
    assert conn.execute("SELECT state FROM transactions WHERE id = ?", (tx_id,)).fetchone()[0] == "active"

    second = funding_coordinator.ensure_pool_funded(
        conn, tx_id, package_id, _system_actor()
    )
    assert second.status == "active"
    assert second.event_emitted is False
    assert conn.execute("SELECT COUNT(*) FROM provider_payments").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM provider_operations").fetchone()[0] == 2
    conn.close()
