"""`services/rule_versions.py` (RuleVersionService, frozen v2 §8.2) testleri."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.config import Settings
from backend.app.db import connect, init_db
from backend.app.repositories import rule_sets as rule_sets_repo
from backend.app.services import rule_versions
from backend.app.services.access_control import ActorContext

_PAYLOAD = {
    "contract_id": "c1",
    "parties": {"buyer": {"name": "B", "tax_id": None}, "seller": {"name": "S", "tax_id": None}},
    "commercial_terms": {
        "currency": "TRY",
        "total_amount": 100.0,
        "goods": [],
        "delivery_deadline": None,
    },
    "payment_rules": [
        {
            "milestone": "m1",
            "trigger": "approval",
            "percentage": 100.0,
            "required_evidence": ["contract"],
            "source_quote": "q",
            "confidence": 0.9,
        }
    ],
    "risk_flags": [],
    "needs_manual_review": False,
}


@pytest.fixture()
def conn(tmp_path: Path):
    connection = connect(Settings(db_path=tmp_path / "rv.db"))
    init_db(connection)
    connection.execute(
        "INSERT INTO transactions (id, state, buyer_token, seller_token, manager_token, "
        "markdown, masked_markdown, created_at, lifecycle_version) "
        "VALUES ('t1', 'uploaded', NULL, NULL, NULL, NULL, NULL, 'now', 'account_v2')"
    )
    connection.execute(
        "INSERT INTO contract_documents (id, transaction_id, version, original_filename, "
        "storage_ref, content_sha256, status, created_at) "
        "VALUES ('d1', 't1', 1, 'a.pdf', 't1/d1', 'h', 'active', 'now')"
    )
    connection.execute(
        "INSERT INTO extraction_runs (id, transaction_id, document_id, provider, model, "
        "prompt_version, schema_version, status, created_at) "
        "VALUES ('er1', 't1', 'd1', 'fake', 'fake', 'v1', 'v1', 'ok', 'now')"
    )
    connection.commit()
    yield connection
    connection.close()


def test_canonical_json_is_key_order_independent() -> None:
    a = rule_versions.canonical_rules_json({"b": 1, "a": 2})
    b = rule_versions.canonical_rules_json({"a": 2, "b": 1})
    assert a == b
    assert rule_versions.compute_rules_hash(a) == rule_versions.compute_rules_hash(b)


def test_single_field_change_produces_different_hash() -> None:
    a = rule_versions.canonical_rules_json({"a": 1})
    b = rule_versions.canonical_rules_json({"a": 2})
    assert rule_versions.compute_rules_hash(a) != rule_versions.compute_rules_hash(b)


def test_create_initial_validates_against_extraction_json(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValidationError):
        rule_versions.create_initial_from_extraction(
            conn, transaction_id="t1", extraction_run_id="er1", rules_payload={"not": "valid"}
        )


def test_create_initial_is_version_one_and_draft(conn: sqlite3.Connection) -> None:
    v1 = rule_versions.create_initial_from_extraction(
        conn, transaction_id="t1", extraction_run_id="er1", rules_payload=_PAYLOAD
    )
    assert v1.version == 1
    assert v1.status == "draft"
    assert v1.parent_version_id is None
    assert v1.source_extraction_run_id == "er1"
    assert v1.created_by_actor_type == "system"
    assert v1.extraction.contract_id == "c1"


def test_validate_version_pass_becomes_ratifiable(conn: sqlite3.Connection) -> None:
    v1 = rule_versions.create_initial_from_extraction(
        conn, transaction_id="t1", extraction_run_id="er1", rules_payload=_PAYLOAD
    )
    validated = rule_versions.validate_version(conn, version_id=v1.id, confidence_threshold=0.7)
    assert validated.validator_status == "PASS"
    assert validated.status == "ratifiable"


def test_validate_version_needs_review_becomes_validated(conn: sqlite3.Connection) -> None:
    low_confidence = json.loads(json.dumps(_PAYLOAD))
    low_confidence["payment_rules"][0]["confidence"] = 0.1
    v1 = rule_versions.create_initial_from_extraction(
        conn, transaction_id="t1", extraction_run_id="er1", rules_payload=low_confidence
    )
    validated = rule_versions.validate_version(conn, version_id=v1.id, confidence_threshold=0.7)
    assert validated.validator_status == "NEEDS_REVIEW"
    assert validated.status == "validated"


def test_create_revision_produces_new_version_without_mutating_parent(
    conn: sqlite3.Connection,
) -> None:
    v1 = rule_versions.create_initial_from_extraction(
        conn, transaction_id="t1", extraction_run_id="er1", rules_payload=_PAYLOAD
    )
    revised_payload = json.loads(json.dumps(_PAYLOAD))
    revised_payload["contract_id"] = "c1-revised"
    actor = ActorContext(actor_type="user", user_id="u1", auth_method="session")

    rev = rule_versions.create_revision(
        conn,
        transaction_id="t1",
        parent_version_id=v1.id,
        rules_payload=revised_payload,
        actor_context=actor,
    )

    assert rev.version == 2
    assert rev.parent_version_id == v1.id
    assert rev.created_by_actor_type == "user"
    assert rev.created_by_user_id == "u1"
    assert rev.extraction.contract_id == "c1-revised"

    # eski satır DEĞİŞMEDİ
    parent_row = rule_sets_repo.get_by_id(conn, v1.id)
    assert json.loads(parent_row["rules_json"])["contract_id"] == "c1"
    assert parent_row["rules_hash"] == v1.rules_hash


def test_get_current_returns_latest_non_superseded(conn: sqlite3.Connection) -> None:
    v1 = rule_versions.create_initial_from_extraction(
        conn, transaction_id="t1", extraction_run_id="er1", rules_payload=_PAYLOAD
    )
    assert rule_versions.get_current(conn, "t1").version == 1

    revised_payload = json.loads(json.dumps(_PAYLOAD))
    actor = ActorContext(actor_type="user", user_id="u1", auth_method="session")
    rev = rule_versions.create_revision(
        conn, transaction_id="t1", parent_version_id=v1.id, rules_payload=revised_payload, actor_context=actor
    )
    assert rule_versions.get_current(conn, "t1").version == rev.version


def test_superseded_version_is_not_returned_as_current(conn: sqlite3.Connection) -> None:
    v1 = rule_versions.create_initial_from_extraction(
        conn, transaction_id="t1", extraction_run_id="er1", rules_payload=_PAYLOAD
    )
    rule_versions.supersede(conn, version_id=v1.id, reason_code="test")
    assert rule_versions.get_current(conn, "t1") is None


def test_get_current_returns_none_when_no_versions_exist(conn: sqlite3.Connection) -> None:
    assert rule_versions.get_current(conn, "t1") is None


def test_concurrent_version_insert_is_fail_closed_by_unique_constraint(
    conn: sqlite3.Connection,
) -> None:
    rule_versions.create_initial_from_extraction(
        conn, transaction_id="t1", extraction_run_id="er1", rules_payload=_PAYLOAD
    )
    with pytest.raises(sqlite3.IntegrityError):
        rule_sets_repo.insert_rule_set_version(
            conn,
            version_id="dup",
            transaction_id="t1",
            version=1,
            parent_version_id=None,
            source_extraction_run_id=None,
            rules_json="{}",
            rules_hash="h",
            status="draft",
            created_by_user_id=None,
            created_by_actor_type="system",
            now="now",
        )


def test_service_functions_do_not_commit_or_connect(conn: sqlite3.Connection) -> None:
    """Servis kendi commit'ini atmazsa, commit edilmemiş veri rollback ile kaybolur."""
    rule_versions.create_initial_from_extraction(
        conn, transaction_id="t1", extraction_run_id="er1", rules_payload=_PAYLOAD
    )
    conn.rollback()
    assert rule_sets_repo.get_latest_non_superseded(conn, "t1") is None
