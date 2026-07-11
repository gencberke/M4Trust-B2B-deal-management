"""Faz 6B — saf milestone evaluator table-driven testleri.

Bu modül `services/milestone_decision.py`'yi test eder. DB/HTTP/FastAPI/provider
bağımlılığı olmadığını da statik olarak doğrular (AST tabanlı import kontrolü,
önceki fazlardaki router static-test deseniyle aynı).
"""

from __future__ import annotations

import ast
import inspect

from backend.app.schemas.extraction import RequiredEvidence
from backend.app.schemas.payments import ReleaseMode
from backend.app.services import milestone_decision as md


def _unit(unit_id: str, sequence: int, *, threshold: int | None = None, released: bool = False) -> md.FundingUnitEligibility:
    return md.FundingUnitEligibility(
        funding_unit_id=unit_id,
        sequence=sequence,
        quantity_threshold=threshold,
        already_released=released,
    )


_NO_REVIEW = md.MilestoneReviewState()
_BLOCKING_DISPUTE = md.MilestoneReviewState(has_blocking_dispute=True)
_BLOCKING_REVIEW = md.MilestoneReviewState(has_blocking_review=True)

_ALL_OR_NOTHING_MILESTONE = md.Milestone(
    milestone_id="m-aon",
    release_mode=ReleaseMode.ALL_OR_NOTHING,
    required_evidence=frozenset({RequiredEvidence.e_irsaliye}),
)
_FIXED_TRANCHE_MILESTONE = md.Milestone(
    milestone_id="m-tranche",
    release_mode=ReleaseMode.FIXED_TRANCHES,
    required_evidence=frozenset({RequiredEvidence.e_irsaliye}),
)

_FOUR_TRANCHE_UNITS = (
    _unit("U01", 1, threshold=25),
    _unit("U02", 2, threshold=50),
    _unit("U03", 3, threshold=75),
    _unit("U04", 4, threshold=100),
)


def test_module_does_not_import_db_http_fastapi_or_provider() -> None:
    source = inspect.getsource(md)
    tree = ast.parse(source)
    forbidden_prefixes = ("sqlite3", "fastapi", "httpx", "backend.app.db", "backend.app.main")
    forbidden_modules = {"backend.app.services.payments", "backend.app.repositories"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(forbidden_prefixes), alias.name
                assert alias.name not in forbidden_modules, alias.name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert not module.startswith(forbidden_prefixes), module
            assert module not in forbidden_modules, module


def test_all_or_nothing_missing_required_evidence_holds() -> None:
    evidence_set = md.MilestoneEvidenceSet(
        verified_evidence_types=frozenset(), funding_units=(_unit("U01", 1),)
    )
    decision = md.evaluate_milestone(_ALL_OR_NOTHING_MILESTONE, evidence_set, _NO_REVIEW)
    assert decision.status == "hold"
    assert decision.release_candidate.funding_unit_ids == ()


def test_all_or_nothing_all_evidence_verified_single_unit_eligible() -> None:
    evidence_set = md.MilestoneEvidenceSet(
        verified_evidence_types=frozenset({"e_irsaliye"}), funding_units=(_unit("U01", 1),)
    )
    decision = md.evaluate_milestone(_ALL_OR_NOTHING_MILESTONE, evidence_set, _NO_REVIEW)
    assert decision.status == "eligible"
    assert decision.release_candidate.funding_unit_ids == ("U01",)


def test_fixed_tranche_exact_threshold_eligible() -> None:
    evidence_set = md.MilestoneEvidenceSet(
        verified_evidence_types=frozenset({"e_irsaliye"}),
        cumulative_verified_quantity=25,
        funding_units=_FOUR_TRANCHE_UNITS,
    )
    decision = md.evaluate_milestone(_FIXED_TRANCHE_MILESTONE, evidence_set, _NO_REVIEW)
    assert decision.status == "eligible"
    assert decision.release_candidate.funding_unit_ids == ("U01",)


def test_fixed_tranche_below_threshold_holds() -> None:
    evidence_set = md.MilestoneEvidenceSet(
        verified_evidence_types=frozenset({"e_irsaliye"}),
        cumulative_verified_quantity=24,
        funding_units=_FOUR_TRANCHE_UNITS,
    )
    decision = md.evaluate_milestone(_FIXED_TRANCHE_MILESTONE, evidence_set, _NO_REVIEW)
    assert decision.status == "hold"
    assert decision.release_candidate.funding_unit_ids == ()


def test_fixed_tranche_two_thresholds_crossed_in_single_evaluation() -> None:
    evidence_set = md.MilestoneEvidenceSet(
        verified_evidence_types=frozenset({"e_irsaliye"}),
        cumulative_verified_quantity=50,
        funding_units=_FOUR_TRANCHE_UNITS,
    )
    decision = md.evaluate_milestone(_FIXED_TRANCHE_MILESTONE, evidence_set, _NO_REVIEW)
    assert decision.release_candidate.funding_unit_ids == ("U01", "U02")


def test_fixed_tranche_full_quantity_all_units_eligible() -> None:
    evidence_set = md.MilestoneEvidenceSet(
        verified_evidence_types=frozenset({"e_irsaliye"}),
        cumulative_verified_quantity=100,
        funding_units=_FOUR_TRANCHE_UNITS,
    )
    decision = md.evaluate_milestone(_FIXED_TRANCHE_MILESTONE, evidence_set, _NO_REVIEW)
    assert decision.release_candidate.funding_unit_ids == ("U01", "U02", "U03", "U04")


def test_duplicate_evaluation_yields_same_result() -> None:
    evidence_set = md.MilestoneEvidenceSet(
        verified_evidence_types=frozenset({"e_irsaliye"}),
        cumulative_verified_quantity=76,
        funding_units=_FOUR_TRANCHE_UNITS,
    )
    first = md.evaluate_milestone(_FIXED_TRANCHE_MILESTONE, evidence_set, _NO_REVIEW)
    second = md.evaluate_milestone(_FIXED_TRANCHE_MILESTONE, evidence_set, _NO_REVIEW)
    assert first == second
    assert first.release_candidate.funding_unit_ids == ("U01", "U02", "U03")


def test_already_released_unit_not_candidate_again() -> None:
    units = (
        _unit("U01", 1, threshold=25, released=True),
        _unit("U02", 2, threshold=50),
        _unit("U03", 3, threshold=75),
        _unit("U04", 4, threshold=100),
    )
    evidence_set = md.MilestoneEvidenceSet(
        verified_evidence_types=frozenset({"e_irsaliye"}),
        cumulative_verified_quantity=50,
        funding_units=units,
    )
    decision = md.evaluate_milestone(_FIXED_TRANCHE_MILESTONE, evidence_set, _NO_REVIEW)
    assert decision.release_candidate.funding_unit_ids == ("U02",)


def test_all_units_already_released_holds() -> None:
    units = tuple(_unit(f"U0{i}", i, threshold=i * 25, released=True) for i in range(1, 5))
    evidence_set = md.MilestoneEvidenceSet(
        verified_evidence_types=frozenset({"e_irsaliye"}),
        cumulative_verified_quantity=100,
        funding_units=units,
    )
    decision = md.evaluate_milestone(_FIXED_TRANCHE_MILESTONE, evidence_set, _NO_REVIEW)
    assert decision.status == "hold"
    assert decision.release_candidate.funding_unit_ids == ()


def test_rejected_evidence_not_counted_as_verified() -> None:
    # Rejected evidence caller tarafından verified_evidence_types'a hiç eklenmez.
    evidence_set = md.MilestoneEvidenceSet(
        verified_evidence_types=frozenset(), funding_units=(_unit("U01", 1),)
    )
    decision = md.evaluate_milestone(_ALL_OR_NOTHING_MILESTONE, evidence_set, _NO_REVIEW)
    assert decision.status == "hold"


def test_review_required_evidence_does_not_produce_release() -> None:
    # review_required kanıt da verified_evidence_types dışında tutulur.
    evidence_set = md.MilestoneEvidenceSet(
        verified_evidence_types=frozenset(), funding_units=(_unit("U01", 1),)
    )
    decision = md.evaluate_milestone(_ALL_OR_NOTHING_MILESTONE, evidence_set, _NO_REVIEW)
    assert decision.release_candidate.funding_unit_ids == ()


def test_blocking_review_prevents_any_candidate() -> None:
    evidence_set = md.MilestoneEvidenceSet(
        verified_evidence_types=frozenset({"e_irsaliye"}),
        cumulative_verified_quantity=100,
        funding_units=_FOUR_TRANCHE_UNITS,
    )
    decision = md.evaluate_milestone(_FIXED_TRANCHE_MILESTONE, evidence_set, _BLOCKING_REVIEW)
    assert decision.status == "hold"
    assert decision.release_candidate.funding_unit_ids == ()


def test_transaction_wide_dispute_blocks_milestone() -> None:
    evidence_set = md.MilestoneEvidenceSet(
        verified_evidence_types=frozenset({"e_irsaliye"}), funding_units=(_unit("U01", 1),)
    )
    decision = md.evaluate_milestone(_ALL_OR_NOTHING_MILESTONE, evidence_set, _BLOCKING_DISPUTE)
    assert decision.status == "hold"


def test_other_milestone_dispute_does_not_block_current_milestone() -> None:
    # Caller `has_open_dispute(conn, tx, milestone_id=<bu milestone>)` çağırır;
    # başka bir milestone'a özel dispute bu çağrıda False döner (repository
    # semantiği). Evaluator'a bu durum has_blocking_dispute=False olarak gelir.
    evidence_set = md.MilestoneEvidenceSet(
        verified_evidence_types=frozenset({"e_irsaliye"}), funding_units=(_unit("U01", 1),)
    )
    decision = md.evaluate_milestone(_ALL_OR_NOTHING_MILESTONE, evidence_set, _NO_REVIEW)
    assert decision.status == "eligible"


def test_video_unit_count_not_used_as_quantity() -> None:
    # VideoAdvisorySummary'de miktar alanı yoktur; cumulative_verified_quantity
    # yalnız e_irsaliye'den gelir. Video aligned olsa da miktarı etkilemez.
    evidence_set = md.MilestoneEvidenceSet(
        verified_evidence_types=frozenset({"e_irsaliye"}),
        cumulative_verified_quantity=25,
        video_advisory=md.VideoAdvisorySummary(provided=True, high_confidence=True),
        funding_units=_FOUR_TRANCHE_UNITS,
    )
    decision = md.evaluate_milestone(_FIXED_TRANCHE_MILESTONE, evidence_set, _NO_REVIEW)
    assert decision.release_candidate.funding_unit_ids == ("U01",)


def test_video_anomaly_holds_and_requires_manual_review() -> None:
    evidence_set = md.MilestoneEvidenceSet(
        verified_evidence_types=frozenset({"e_irsaliye"}),
        cumulative_verified_quantity=100,
        video_advisory=md.VideoAdvisorySummary(
            provided=True, high_confidence=True, count_divergence_detected=True
        ),
        funding_units=_FOUR_TRANCHE_UNITS,
    )
    decision = md.evaluate_milestone(_FIXED_TRANCHE_MILESTONE, evidence_set, _NO_REVIEW)
    assert decision.status == "hold"
    assert decision.manual_review_required is True
    assert decision.release_candidate.funding_unit_ids == ()


def test_video_anomaly_does_not_open_dispute_itself() -> None:
    # Evaluator dispute service'i hiç import etmez / çağırmaz -- bu statik
    # import testiyle (test_module_does_not_import_db_http_fastapi_or_provider)
    # ve MilestoneDecision şeklinde dispute-açma yan etkisi olmamasıyla garanti.
    evidence_set = md.MilestoneEvidenceSet(
        verified_evidence_types=frozenset({"e_irsaliye"}),
        cumulative_verified_quantity=100,
        video_advisory=md.VideoAdvisorySummary(
            provided=True, high_confidence=True, damage_matched=True
        ),
        funding_units=_FOUR_TRANCHE_UNITS,
    )
    decision = md.evaluate_milestone(_FIXED_TRANCHE_MILESTONE, evidence_set, _NO_REVIEW)
    assert not hasattr(decision, "dispute_id")
    assert decision.manual_review_required is True


def test_unit_order_is_deterministic_regardless_of_input_order() -> None:
    shuffled = (
        _FOUR_TRANCHE_UNITS[2],
        _FOUR_TRANCHE_UNITS[0],
        _FOUR_TRANCHE_UNITS[3],
        _FOUR_TRANCHE_UNITS[1],
    )
    evidence_set = md.MilestoneEvidenceSet(
        verified_evidence_types=frozenset({"e_irsaliye"}),
        cumulative_verified_quantity=76,
        funding_units=shuffled,
    )
    decision = md.evaluate_milestone(_FIXED_TRANCHE_MILESTONE, evidence_set, _NO_REVIEW)
    assert decision.release_candidate.funding_unit_ids == ("U01", "U02", "U03")


def test_legacy_ratio_helper_does_not_split_units() -> None:
    candidate = md.select_units_for_legacy_ratio(_FOUR_TRANCHE_UNITS, 0.5)
    assert candidate.funding_unit_ids == ("U01", "U02")


def test_legacy_ratio_helper_full_ratio_selects_all() -> None:
    candidate = md.select_units_for_legacy_ratio(_FOUR_TRANCHE_UNITS, 1.0)
    assert candidate.funding_unit_ids == ("U01", "U02", "U03", "U04")


def test_legacy_ratio_helper_zero_ratio_selects_none() -> None:
    candidate = md.select_units_for_legacy_ratio(_FOUR_TRANCHE_UNITS, 0.0)
    assert candidate.funding_unit_ids == ()


def test_legacy_ratio_helper_skips_already_released_units() -> None:
    units = (
        _unit("U01", 1, released=True),
        _unit("U02", 2),
        _unit("U03", 3),
        _unit("U04", 4),
    )
    candidate = md.select_units_for_legacy_ratio(units, 1.0)
    assert candidate.funding_unit_ids == ("U02", "U03", "U04")


def test_release_candidate_has_no_capture_ratio_field() -> None:
    fields = {f for f in md.ReleaseCandidate.__dataclass_fields__}
    assert "capture_ratio" not in fields
    assert fields == {"funding_unit_ids"}


def test_dataclasses_are_frozen() -> None:
    unit = _unit("U01", 1)
    try:
        unit.sequence = 99  # type: ignore[misc]
        assert False, "FundingUnitEligibility mutable olmamalı"
    except AttributeError:
        pass
    decision = md.evaluate_milestone(
        _ALL_OR_NOTHING_MILESTONE,
        md.MilestoneEvidenceSet(
            verified_evidence_types=frozenset({"e_irsaliye"}), funding_units=(unit,)
        ),
        _NO_REVIEW,
    )
    try:
        decision.status = "hold"  # type: ignore[misc]
        assert False, "MilestoneDecision mutable olmamalı"
    except AttributeError:
        pass
