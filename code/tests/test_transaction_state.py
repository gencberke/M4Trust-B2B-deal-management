"""`backend.app.services.transaction_state` — v2 §2.8 legacy projeksiyon kontrat testleri.

Saf fonksiyon testleri: DB/router/repository importu yok, yalnız
`LegacyProjectionInput` -> `CanonicalState` eşlemesi tablo-tabanlı doğrulanır.
"""

from __future__ import annotations

import pytest

from backend.app.services.transaction_state import (
    CanonicalState,
    LegacyProjectionError,
    LegacyProjectionInput,
    LegacyStatus,
    LifecycleVersion,
    ReleaseCompleteness,
    project_legacy_state,
    validate_lifecycle_version,
)

# --- v2 §2.8 tablosunun birebir karşılığı -----------------------------------

_UNAMBIGUOUS_CASES = [
    (LegacyProjectionInput(legacy_status=LegacyStatus.UPLOADED), CanonicalState.PROCESSING),
    (LegacyProjectionInput(legacy_status=LegacyStatus.EXTRACTING), CanonicalState.PROCESSING),
    (LegacyProjectionInput(legacy_status=LegacyStatus.REJECTED), CanonicalState.REJECTED),
    (LegacyProjectionInput(legacy_status=LegacyStatus.ACTIVE), CanonicalState.ACTIVE),
]


@pytest.mark.parametrize("projection_input,expected", _UNAMBIGUOUS_CASES)
def test_unambiguous_legacy_status_projections(
    projection_input: LegacyProjectionInput, expected: CanonicalState
) -> None:
    assert project_legacy_state(projection_input) is expected


def test_awaiting_review_blocking_maps_to_blocked_review() -> None:
    result = project_legacy_state(
        LegacyProjectionInput(legacy_status=LegacyStatus.AWAITING_REVIEW, review_blocking=True)
    )
    assert result is CanonicalState.BLOCKED_REVIEW


def test_awaiting_review_non_blocking_maps_to_preparation() -> None:
    result = project_legacy_state(
        LegacyProjectionInput(legacy_status=LegacyStatus.AWAITING_REVIEW, review_blocking=False)
    )
    assert result is CanonicalState.PREPARATION


def test_awaiting_review_missing_discriminator_raises() -> None:
    with pytest.raises(LegacyProjectionError):
        project_legacy_state(LegacyProjectionInput(legacy_status=LegacyStatus.AWAITING_REVIEW))


def test_awaiting_approval_ready_maps_to_ready_for_ratification() -> None:
    result = project_legacy_state(
        LegacyProjectionInput(
            legacy_status=LegacyStatus.AWAITING_APPROVAL, ratification_ready=True
        )
    )
    assert result is CanonicalState.READY_FOR_RATIFICATION


def test_awaiting_approval_not_ready_maps_to_preparation() -> None:
    result = project_legacy_state(
        LegacyProjectionInput(
            legacy_status=LegacyStatus.AWAITING_APPROVAL, ratification_ready=False
        )
    )
    assert result is CanonicalState.PREPARATION


def test_awaiting_approval_missing_discriminator_raises() -> None:
    with pytest.raises(LegacyProjectionError):
        project_legacy_state(LegacyProjectionInput(legacy_status=LegacyStatus.AWAITING_APPROVAL))


def test_evidence_pending_blocking_maps_to_blocked_evidence() -> None:
    result = project_legacy_state(
        LegacyProjectionInput(legacy_status=LegacyStatus.EVIDENCE_PENDING, evidence_blocking=True)
    )
    assert result is CanonicalState.BLOCKED_EVIDENCE


def test_evidence_pending_non_blocking_maps_to_active() -> None:
    result = project_legacy_state(
        LegacyProjectionInput(
            legacy_status=LegacyStatus.EVIDENCE_PENDING, evidence_blocking=False
        )
    )
    assert result is CanonicalState.ACTIVE


def test_evidence_pending_missing_discriminator_raises() -> None:
    with pytest.raises(LegacyProjectionError):
        project_legacy_state(LegacyProjectionInput(legacy_status=LegacyStatus.EVIDENCE_PENDING))


def test_decided_fully_released_maps_to_settled() -> None:
    result = project_legacy_state(
        LegacyProjectionInput(
            legacy_status=LegacyStatus.DECIDED,
            release_completeness=ReleaseCompleteness.FULLY_RELEASED,
        )
    )
    assert result is CanonicalState.SETTLED


def test_decided_partially_released_with_more_expected_maps_to_active() -> None:
    result = project_legacy_state(
        LegacyProjectionInput(
            legacy_status=LegacyStatus.DECIDED,
            release_completeness=ReleaseCompleteness.PARTIALLY_RELEASED,
            more_releases_expected=True,
        )
    )
    assert result is CanonicalState.ACTIVE


def test_decided_partially_released_with_no_more_expected_maps_to_partially_settled() -> None:
    result = project_legacy_state(
        LegacyProjectionInput(
            legacy_status=LegacyStatus.DECIDED,
            release_completeness=ReleaseCompleteness.PARTIALLY_RELEASED,
            more_releases_expected=False,
        )
    )
    assert result is CanonicalState.PARTIALLY_SETTLED


def test_decided_missing_release_completeness_raises() -> None:
    with pytest.raises(LegacyProjectionError):
        project_legacy_state(LegacyProjectionInput(legacy_status=LegacyStatus.DECIDED))


def test_decided_partially_released_missing_more_releases_expected_raises() -> None:
    with pytest.raises(LegacyProjectionError):
        project_legacy_state(
            LegacyProjectionInput(
                legacy_status=LegacyStatus.DECIDED,
                release_completeness=ReleaseCompleteness.PARTIALLY_RELEASED,
            )
        )


# --- lifecycle_version doğrulaması ------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [("legacy_v1", LifecycleVersion.LEGACY_V1), ("account_v2", LifecycleVersion.ACCOUNT_V2)],
)
def test_validate_lifecycle_version_accepts_known_values(value: str, expected) -> None:
    assert validate_lifecycle_version(value) is expected


def test_validate_lifecycle_version_rejects_unknown_value() -> None:
    with pytest.raises(LegacyProjectionError):
        validate_lifecycle_version("v3_future")


def test_module_has_no_forbidden_imports() -> None:
    """DB-bağımsızlık kontratı: router/repository/sqlite3/payment provider yok."""
    import backend.app.services.transaction_state as module

    source = module.__file__
    with open(source, encoding="utf-8") as fh:
        content = fh.read()

    for forbidden in ("import sqlite3", "routers", "repositories", "payment_provider", "services.payments"):
        assert forbidden not in content, f"Yasak referans bulundu: {forbidden!r}"
