"""`services/reconciliation.py` — table-driven `compare_party_snapshots` testleri +
`open_party_mismatch_cases` DB orkestrasyon testleri."""

from __future__ import annotations

from importlib import import_module

import pytest

from backend.app.schemas.participants import PartyProfileSnapshot
from backend.app.services.access_control import ActorContext
from backend.app.services.reconciliation import (
    PARTY_PROFILE_MISSING,
    compare_party_snapshots,
    open_party_mismatch_cases,
)
from backend.app.services.review import has_blocking_case, list_cases
from participants_fixtures import create_test_transaction, make_participants_db

_review_migration = import_module("backend.app.db.migrations.010_review_cases")


@pytest.fixture()
def conn():
    connection = make_participants_db()
    _review_migration.apply(connection)
    try:
        yield connection
    finally:
        connection.close()


def actor() -> ActorContext:
    return ActorContext(actor_type="user", user_id="reviewer-1", request_id="req-1")


def snap(**kwargs) -> PartyProfileSnapshot:
    defaults = {"name": "ACME Sanayi A.Ş."}
    defaults.update(kwargs)
    return PartyProfileSnapshot(**defaults)


# --- compare_party_snapshots: table-driven ----------------------------------------


def test_equivalent_normalized_name_no_mismatch() -> None:
    result = compare_party_snapshots(
        role="buyer",
        extracted=snap(name="ACME Sanayi A.Ş."),
        declared=None,
        confirmed=snap(name="acme sanayi a.ş"),
    )
    assert result.mismatches == ()


def test_name_mismatch_detected() -> None:
    result = compare_party_snapshots(
        role="buyer", extracted=snap(name="ACME A.Ş."), declared=None, confirmed=snap(name="Globex Ltd.")
    )
    codes = [m.reason_code for m in result.mismatches]
    assert "PARTY_NAME_MISMATCH" in codes


def test_tax_id_formatting_equivalence_no_mismatch() -> None:
    result = compare_party_snapshots(
        role="buyer",
        extracted=snap(tax_id="1234567890"),
        declared=None,
        confirmed=snap(tax_id="123-456-7890"),
    )
    assert result.mismatches == ()


def test_tax_id_mismatch_detected() -> None:
    result = compare_party_snapshots(
        role="buyer", extracted=snap(tax_id="1111111111"), declared=None, confirmed=snap(tax_id="2222222222")
    )
    codes = [m.reason_code for m in result.mismatches]
    assert "PARTY_TAX_ID_MISMATCH" in codes


def test_email_case_equivalence_no_mismatch() -> None:
    result = compare_party_snapshots(
        role="buyer",
        extracted=snap(contact_email="Info@Acme.com"),
        declared=None,
        confirmed=snap(contact_email="info@acme.com"),
    )
    assert result.mismatches == ()


def test_email_mismatch_detected() -> None:
    result = compare_party_snapshots(
        role="buyer",
        extracted=snap(contact_email="info@acme.com"),
        declared=None,
        confirmed=snap(contact_email="other@acme.com"),
    )
    codes = [m.reason_code for m in result.mismatches]
    assert "PARTY_CONTACT_EMAIL_MISMATCH" in codes


def test_phone_formatting_equivalence_no_mismatch() -> None:
    result = compare_party_snapshots(
        role="buyer",
        extracted=snap(contact_phone="0555 123 45 67"),
        declared=None,
        confirmed=snap(contact_phone="05551234567"),
    )
    assert result.mismatches == ()


def test_phone_mismatch_detected() -> None:
    result = compare_party_snapshots(
        role="buyer", extracted=snap(contact_phone="05551234567"), declared=None, confirmed=snap(contact_phone="05559999999")
    )
    codes = [m.reason_code for m in result.mismatches]
    assert "PARTY_CONTACT_PHONE_MISMATCH" in codes


def test_address_normalization_equivalence_no_mismatch() -> None:
    result = compare_party_snapshots(
        role="buyer",
        extracted=snap(address="Atatürk Cad. No:5, Kadıköy"),
        declared=None,
        confirmed=snap(address="atatürk cad no 5 kadıköy"),
    )
    assert result.mismatches == ()


def test_address_mismatch_detected() -> None:
    result = compare_party_snapshots(
        role="buyer", extracted=snap(address="Istanbul, Kadıköy"), declared=None, confirmed=snap(address="Ankara, Çankaya")
    )
    codes = [m.reason_code for m in result.mismatches]
    assert "PARTY_ADDRESS_MISMATCH" in codes


def test_confirmed_profile_missing_is_blocking() -> None:
    result = compare_party_snapshots(role="seller", extracted=snap(), declared=None, confirmed=None)
    assert result.missing_profile is True
    assert result.has_findings is True


def test_nullable_field_is_skipped_not_flagged_as_mismatch() -> None:
    """Yalnız iki tarafta da non-null olan alanlar karşılaştırılır."""
    result = compare_party_snapshots(
        role="buyer",
        extracted=snap(tax_id=None),
        declared=None,
        confirmed=snap(tax_id="1234567890"),
    )
    assert result.mismatches == ()


def test_extracted_none_entirely_skips_all_field_comparisons() -> None:
    result = compare_party_snapshots(role="buyer", extracted=None, declared=None, confirmed=snap())
    assert result.mismatches == ()
    assert result.missing_profile is False


def test_result_only_exposes_field_name_and_reason_code_not_raw_values() -> None:
    result = compare_party_snapshots(
        role="buyer", extracted=snap(name="Secret Real Name A.Ş."), declared=None, confirmed=snap(name="Totally Different Ltd.")
    )
    mismatch = result.mismatches[0]
    assert mismatch.field == "name"
    assert mismatch.reason_code == "PARTY_NAME_MISMATCH"
    assert not hasattr(mismatch, "extracted_value")
    assert not hasattr(mismatch, "confirmed_value")


def test_declared_snapshot_does_not_affect_comparison() -> None:
    """Confirm sonrası declared==confirmed olduğundan declared parametresi
    karşılaştırmaya girmez; farklı bir declared verilse bile sonuç değişmez."""
    result_with_declared = compare_party_snapshots(
        role="buyer", extracted=snap(name="ACME"), declared=snap(name="Completely Different"), confirmed=snap(name="acme")
    )
    result_without_declared = compare_party_snapshots(
        role="buyer", extracted=snap(name="ACME"), declared=None, confirmed=snap(name="acme")
    )
    assert result_with_declared.mismatches == result_without_declared.mismatches


# --- open_party_mismatch_cases: DB orchestration ----------------------------------


def test_open_party_mismatch_cases_missing_profile(conn) -> None:
    tx_id = create_test_transaction(conn)
    result = compare_party_snapshots(role="buyer", extracted=snap(), declared=None, confirmed=None)
    cases = open_party_mismatch_cases(
        conn, transaction_id=tx_id, participant_id="p1", rule_version_id="rv1",
        result=result, actor_context=actor(),
    )
    assert len(cases) == 1
    assert cases[0].reason_code == PARTY_PROFILE_MISSING
    assert cases[0].severity.value == "blocking"


def test_open_party_mismatch_cases_no_findings_opens_nothing(conn) -> None:
    tx_id = create_test_transaction(conn)
    result = compare_party_snapshots(role="buyer", extracted=snap(), declared=None, confirmed=snap())
    cases = open_party_mismatch_cases(
        conn, transaction_id=tx_id, participant_id="p1", rule_version_id="rv1",
        result=result, actor_context=actor(),
    )
    assert cases == ()
    assert has_blocking_case(conn, tx_id) is False


def test_open_party_mismatch_cases_description_has_no_raw_values(conn) -> None:
    tx_id = create_test_transaction(conn)
    result = compare_party_snapshots(
        role="buyer", extracted=snap(name="Very Secret Company Name"), declared=None, confirmed=snap(name="Different Name Ltd")
    )
    cases = open_party_mismatch_cases(
        conn, transaction_id=tx_id, participant_id="p1", rule_version_id="rv1",
        result=result, actor_context=actor(),
    )
    assert "Very Secret Company Name" not in cases[0].description
    assert "Different Name Ltd" not in cases[0].description
    audit_rows = conn.execute("SELECT metadata_json FROM audit_events").fetchall()
    for row in audit_rows:
        assert "Very Secret Company Name" not in row["metadata_json"]
        assert "Different Name Ltd" not in row["metadata_json"]


def test_repeated_same_mismatch_keeps_single_active_case(conn) -> None:
    tx_id = create_test_transaction(conn)
    result = compare_party_snapshots(
        role="buyer", extracted=snap(name="A"), declared=None, confirmed=snap(name="B")
    )
    first = open_party_mismatch_cases(
        conn, transaction_id=tx_id, participant_id="p1", rule_version_id="rv1",
        result=result, actor_context=actor(),
    )
    second = open_party_mismatch_cases(
        conn, transaction_id=tx_id, participant_id="p1", rule_version_id="rv2",
        result=result, actor_context=actor(),
    )
    assert first[0].id == second[0].id
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM review_cases WHERE transaction_id = ?", (tx_id,)
    ).fetchone()["n"]
    assert count == 1


def test_no_mismatch_does_not_silently_resolve_old_case(conn) -> None:
    """Önce mismatch bulunup case açılır; sonraki çağrıda mismatch YOK ise eski
    case sessizce resolve edilmez, açık kalır."""
    tx_id = create_test_transaction(conn)
    mismatching = compare_party_snapshots(
        role="buyer", extracted=snap(name="A"), declared=None, confirmed=snap(name="B")
    )
    opened = open_party_mismatch_cases(
        conn, transaction_id=tx_id, participant_id="p1", rule_version_id="rv1",
        result=mismatching, actor_context=actor(),
    )
    assert opened[0].status.value == "open"

    clean = compare_party_snapshots(
        role="buyer", extracted=snap(name="A"), declared=None, confirmed=snap(name="A")
    )
    open_party_mismatch_cases(
        conn, transaction_id=tx_id, participant_id="p1", rule_version_id="rv2",
        result=clean, actor_context=actor(),
    )

    reloaded = [c for c in list_cases(conn, tx_id) if c.id == opened[0].id][0]
    assert reloaded.status.value == "open"


def test_reconciliation_does_not_write_participant_snapshots(conn) -> None:
    """Reconciliation `transaction_participants`'a hiçbir yazma yapmaz."""
    tx_id = create_test_transaction(conn)
    conn.execute(
        "INSERT INTO transaction_participants (id, transaction_id, role, status, "
        "declared_snapshot_json, created_at, updated_at) VALUES ('p1', ?, 'buyer', 'ready', "
        "'{\"name\": \"Original\"}', datetime('now'), datetime('now'))",
        (tx_id,),
    )
    result = compare_party_snapshots(
        role="buyer", extracted=snap(name="A"), declared=None, confirmed=snap(name="B")
    )
    open_party_mismatch_cases(
        conn, transaction_id=tx_id, participant_id="p1", rule_version_id="rv1",
        result=result, actor_context=actor(),
    )
    row = conn.execute(
        "SELECT declared_snapshot_json FROM transaction_participants WHERE id = 'p1'"
    ).fetchone()
    assert row["declared_snapshot_json"] == '{"name": "Original"}'
