"""Faz 4C — `services/payments/funding_plan.py` saf compiler testleri.

Kapsam: `plans/ready/04_rule_versioning_ratification_manual_review.md` §4C ve
faz talimatının "Zorunlu testler" listesi. Router/DB/provider bağlantısı YOKTUR.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.schemas.extraction import PaymentRule, RequiredEvidence, Trigger
from backend.app.schemas.payments import (
    FundingScheduleSpec,
    MilestoneReleaseOverride,
    ReleaseMode,
    RequestedReleaseMode,
)
from backend.app.services.payments.domain import MOKA_STANDARD_PROFILE, ProviderCapabilities
from backend.app.services.payments.funding_plan import (
    FundingPlanValidationError,
    ProviderCapabilityConflictError,
    compile_funding_plan,
    to_minor,
)

NO_OVERRIDES = FundingScheduleSpec()


def rule(milestone: str, percentage: float, **kwargs) -> PaymentRule:
    defaults = dict(
        trigger=Trigger.approval,
        required_evidence=[RequiredEvidence.contract],
        source_quote="...",
        confidence=0.9,
    )
    defaults.update(kwargs)
    return PaymentRule(milestone=milestone, percentage=percentage, **defaults)


# --- to_minor -----------------------------------------------------------------


def test_to_minor_half_kurus_rounds_half_up() -> None:
    assert to_minor(100.005, "TRY") == 10001
    assert to_minor(100.004, "TRY") == 10000
    assert to_minor(100.0, "TRY") == 10000


def test_to_minor_rejects_empty_currency() -> None:
    with pytest.raises(FundingPlanValidationError):
        to_minor(10.0, "")


# --- compile_funding_plan: exact distribution ----------------------------------


def test_four_milestones_20_30_40_10_totals_exact() -> None:
    rules = [
        rule("avans", 20),
        rule("teslimat-1", 30),
        rule("teslimat-2", 40),
        rule("kabul", 10),
    ]
    plan = compile_funding_plan(rules, 1_000_00, "TRY", NO_OVERRIDES, MOKA_STANDARD_PROFILE)
    assert [m.amount_minor for m in plan.milestones] == [200_00, 300_00, 400_00, 100_00]
    assert sum(m.amount_minor for m in plan.milestones) == 1_000_00


def test_thirds_rounding_sums_exact_and_deterministic() -> None:
    rules = [rule("a", 33.33), rule("b", 33.33), rule("c", 33.34)]
    plan = compile_funding_plan(rules, 100_000, "TRY", NO_OVERRIDES, MOKA_STANDARD_PROFILE)
    amounts = [m.amount_minor for m in plan.milestones]
    assert sum(amounts) == 100_000
    # basis points: 3333/3333/3334 -> largest-remainder tie-break lowest index first
    assert amounts == [33_330, 33_330, 33_340]


def test_same_input_produces_same_output() -> None:
    rules = [rule("a", 60), rule("b", 40)]
    plan1 = compile_funding_plan(rules, 777_00, "TRY", NO_OVERRIDES, MOKA_STANDARD_PROFILE)
    plan2 = compile_funding_plan(rules, 777_00, "TRY", NO_OVERRIDES, MOKA_STANDARD_PROFILE)
    assert plan1 == plan2


def test_output_dict_and_sequence_ordering_is_deterministic() -> None:
    rules = [rule("a", 60), rule("b", 40)]
    plan = compile_funding_plan(rules, 100_00, "TRY", NO_OVERRIDES, MOKA_STANDARD_PROFILE)
    assert [m.rule_index for m in plan.milestones] == [0, 1]
    sequences = [unit.sequence for m in plan.milestones for unit in m.funding_units]
    assert sequences == sorted(sequences) == list(range(1, len(sequences) + 1))
    payload = dict(plan.milestones[0].funding_units[0].eligibility_payload)
    assert json.dumps(payload) == json.dumps(payload)  # kararlı anahtar sırası


# --- fixed_tranches --------------------------------------------------------------


def test_100_units_splits_into_4_equal_tranches() -> None:
    rules = [rule("teslimat", 100)]
    spec = FundingScheduleSpec(
        overrides=(
            MilestoneReleaseOverride(
                rule_index=0, release_mode=RequestedReleaseMode.FIXED_TRANCHES, tranche_count=4
            ),
        )
    )
    plan = compile_funding_plan(rules, 400_00, "TRY", spec, MOKA_STANDARD_PROFILE)
    milestone = plan.milestones[0]
    assert milestone.release_mode is ReleaseMode.FIXED_TRANCHES
    assert [u.amount_minor for u in milestone.funding_units] == [100_00] * 4
    assert sum(u.amount_minor for u in milestone.funding_units) == 400_00


def test_undividable_tranche_amount_distributes_remainder() -> None:
    rules = [rule("teslimat", 100)]
    spec = FundingScheduleSpec(
        overrides=(
            MilestoneReleaseOverride(
                rule_index=0, release_mode=RequestedReleaseMode.FIXED_TRANCHES, tranche_count=3
            ),
        )
    )
    plan = compile_funding_plan(rules, 100, "TRY", spec, MOKA_STANDARD_PROFILE)
    amounts = [u.amount_minor for u in plan.milestones[0].funding_units]
    assert amounts == [34, 33, 33]
    assert sum(amounts) == 100


def test_all_or_nothing_produces_single_unit() -> None:
    rules = [rule("teslimat", 100)]
    plan = compile_funding_plan(rules, 500_00, "TRY", NO_OVERRIDES, MOKA_STANDARD_PROFILE)
    assert len(plan.milestones[0].funding_units) == 1
    assert plan.milestones[0].funding_units[0].amount_minor == 500_00


# --- rejection paths ---------------------------------------------------------------


@pytest.mark.parametrize("total", [0, -1])
def test_negative_or_zero_total_rejected(total: int) -> None:
    with pytest.raises(FundingPlanValidationError):
        compile_funding_plan([rule("a", 100)], total, "TRY", NO_OVERRIDES, MOKA_STANDARD_PROFILE)


def test_percentage_sum_not_100_rejected() -> None:
    rules = [rule("a", 50), rule("b", 40)]
    with pytest.raises(FundingPlanValidationError):
        compile_funding_plan(rules, 100_00, "TRY", NO_OVERRIDES, MOKA_STANDARD_PROFILE)


def test_invalid_rule_index_override_rejected() -> None:
    rules = [rule("a", 100)]
    spec = FundingScheduleSpec(
        overrides=(
            MilestoneReleaseOverride(rule_index=5, release_mode=RequestedReleaseMode.ALL_OR_NOTHING),
        )
    )
    with pytest.raises(FundingPlanValidationError):
        compile_funding_plan(rules, 100_00, "TRY", spec, MOKA_STANDARD_PROFILE)


def test_duplicate_rule_index_override_rejected() -> None:
    rules = [rule("a", 50), rule("b", 50)]
    spec = FundingScheduleSpec(
        overrides=(
            MilestoneReleaseOverride(rule_index=0, release_mode=RequestedReleaseMode.ALL_OR_NOTHING),
            MilestoneReleaseOverride(rule_index=0, release_mode=RequestedReleaseMode.ALL_OR_NOTHING),
        )
    )
    with pytest.raises(FundingPlanValidationError):
        compile_funding_plan(rules, 100_00, "TRY", spec, MOKA_STANDARD_PROFILE)


def test_unsupported_release_mode_rejected_at_construction() -> None:
    with pytest.raises(ValidationError):
        MilestoneReleaseOverride(rule_index=0, release_mode="not_a_real_mode")


def test_moka_proportional_release_mode_is_provider_capability_conflict() -> None:
    rules = [rule("a", 100)]
    spec = FundingScheduleSpec(
        overrides=(
            MilestoneReleaseOverride(
                rule_index=0,
                release_mode=RequestedReleaseMode.PROPORTIONAL_TO_VERIFIED_QUANTITY,
            ),
        )
    )
    with pytest.raises(ProviderCapabilityConflictError) as exc_info:
        compile_funding_plan(rules, 100_00, "TRY", spec, MOKA_STANDARD_PROFILE)
    assert exc_info.value.code == "PROVIDER_CAPABILITY_CONFLICT"
    assert exc_info.value.reason == "MOKA_REQUIRES_FIXED_FUNDING_UNITS"


def test_fixed_tranches_rejected_when_capability_missing() -> None:
    rules = [rule("a", 100)]
    spec = FundingScheduleSpec(
        overrides=(
            MilestoneReleaseOverride(
                rule_index=0, release_mode=RequestedReleaseMode.FIXED_TRANCHES, tranche_count=2
            ),
        )
    )
    no_tranches = ProviderCapabilities(
        supports_pool_payment=True,
        supports_partial_pool_approval=False,
        supports_multiple_approvals_per_payment=False,
        supports_approval_undo=True,
        supports_fixed_tranches=False,
        supports_marketplace_subdealers=False,
    )
    with pytest.raises(ProviderCapabilityConflictError) as exc_info:
        compile_funding_plan(rules, 100_00, "TRY", spec, no_tranches)
    assert exc_info.value.code == "PROVIDER_CAPABILITY_CONFLICT"


# --- isolation: no DB/FastAPI/provider import ----------------------------------


def test_funding_plan_module_imports_no_db_http_or_provider() -> None:
    module_path = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "app"
        / "services"
        / "payments"
        / "funding_plan.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    forbidden_prefixes = (
        "fastapi",
        "sqlite3",
        "httpx",
        "requests",
        "backend.app.db",
        "backend.app.eventbus",
        "backend.app.services.payments.moka",
        "backend.app.services.payments.ports",
    )
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for name in imported:
        assert not any(name == p or name.startswith(p + ".") for p in forbidden_prefixes), name
