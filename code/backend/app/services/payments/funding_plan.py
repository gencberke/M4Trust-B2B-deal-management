"""Faz 4C — saf funding-plan compiler (Moka §9, v2 §2.3).

Bu modül DB, HTTP, FastAPI, event veya provider çağrısı YAPMAZ. `MilestoneDraft`,
`FundingUnitDraft` ve `compile_funding_plan` imzası donmuştur (program haritası
§5, "04 Faz 4C başında"). Tutar dönüşümünün tek kapısı `to_minor()`'dır; para
hesabı asla doğrudan `float` üzerinde yapılmaz (`Decimal(str(value))`).

Milestone/tranche dağıtımı deterministic largest-remainder (Hamilton) yöntemiyle
yapılır: `floor` ile taban pay verilir, kalan birimler en büyük kalana (eşitlikte
en küçük index'e) sırayla dağıtılır — böylece toplam her zaman girdi tutarına
tam eşit olur ve aynı girdi her zaman aynı çıktıyı üretir.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType
from typing import Mapping, Sequence

from backend.app.schemas.extraction import PaymentRule
from backend.app.schemas.payments import (
    FundingScheduleSpec,
    MilestoneReleaseOverride,
    ReleaseMode,
    RequestedReleaseMode,
)
from backend.app.services.payments.domain import ProviderCapabilities

_BASIS_POINTS_TOTAL = 10_000
_TWO_PLACES = Decimal("0.01")


class FundingPlanError(Exception):
    """Funding-plan compiler'ının tüm domain hatalarının kökü."""


class FundingPlanValidationError(FundingPlanError):
    """Girdi doğrulama hatası (tutar, yüzde toplamı, index, tranche sayısı)."""


class ProviderCapabilityConflictError(FundingPlanError):
    """Provider'ın desteklemediği bir funding-schedule isteği (fail closed)."""

    def __init__(self, *, code: str, reason: str) -> None:
        self.code = code
        self.reason = reason
        super().__init__(f"{code}: {reason}")


def to_minor(total_amount: float, currency: str) -> int:
    """Ondalık tutarı minor unit'e (kuruş/cent) çevirir — tek dönüşüm kapısı.

    Yarım minor-unit `ROUND_HALF_UP` ile yukarı yuvarlanır.
    """
    if not isinstance(currency, str) or not currency.strip():
        raise FundingPlanValidationError("currency boş olamaz.")
    quantized = Decimal(str(total_amount)).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)
    return int(quantized * 100)


@dataclass(frozen=True)
class FundingUnitDraft:
    """Bir funding-plan içindeki bölünemez para hareketi birimi."""

    sequence: int
    amount_minor: int
    eligibility_type: str
    eligibility_payload: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "eligibility_payload", MappingProxyType(dict(self.eligibility_payload)))


@dataclass(frozen=True)
class MilestoneDraft:
    """Bir `PaymentRule`'dan derlenen, para birimi cinsinden somutlaştırılmış milestone."""

    rule_index: int
    title: str
    trigger_type: str
    basis_points: int
    amount_minor: int
    currency: str
    required_evidence: tuple[str, ...]
    release_mode: ReleaseMode
    funding_units: tuple[FundingUnitDraft, ...]


@dataclass(frozen=True)
class FundingPlanDraft:
    """`compile_funding_plan` çıktısı: tüm milestone'lar + toplam doğrulaması."""

    milestones: tuple[MilestoneDraft, ...]
    total_amount_minor: int
    currency: str


def _percentage_to_basis_points(percentage: float) -> int:
    quantized = (Decimal(str(percentage)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(quantized)


def _largest_remainder_distribution(
    *, total: int, weights: Sequence[int], tie_break: Sequence[int]
) -> list[int]:
    """`total`'i `weights` oranında tam sayı birimlere böler (Hamilton yöntemi).

    Eşit kalan durumunda düşük `tie_break` değeri önce +1 alır. Çıktı toplamı
    her zaman `total`'e tam eşittir.
    """
    weight_sum = sum(weights)
    if weight_sum <= 0:
        raise FundingPlanValidationError("Ağırlık toplamı sıfırdan büyük olmalı.")
    raw = [total * w for w in weights]
    base = [r // weight_sum for r in raw]
    remainder = [r % weight_sum for r in raw]
    leftover = total - sum(base)
    order = sorted(range(len(weights)), key=lambda i: (-remainder[i], tie_break[i]))
    result = list(base)
    for i in order[:leftover]:
        result[i] += 1
    return result


def _validate_overrides(
    spec: FundingScheduleSpec, *, rule_count: int
) -> dict[int, MilestoneReleaseOverride]:
    by_index: dict[int, MilestoneReleaseOverride] = {}
    for override in spec.overrides:
        if override.rule_index >= rule_count:
            raise FundingPlanValidationError(
                f"Geçersiz rule_index: {override.rule_index} (rule_set uzunluğu {rule_count})."
            )
        if override.rule_index in by_index:
            raise FundingPlanValidationError(
                f"Duplicate rule_index override: {override.rule_index}."
            )
        by_index[override.rule_index] = override
    return by_index


def _resolve_release_mode(
    rule_index: int,
    overrides_by_index: Mapping[int, MilestoneReleaseOverride],
    capabilities: ProviderCapabilities,
) -> tuple[ReleaseMode, int | None]:
    override = overrides_by_index.get(rule_index)
    if override is None:
        return ReleaseMode.ALL_OR_NOTHING, None

    requested = override.release_mode
    if requested is RequestedReleaseMode.PROPORTIONAL_TO_VERIFIED_QUANTITY:
        # LLM/manager release mode belirleyemez — Moka profilinde daima reddedilir.
        raise ProviderCapabilityConflictError(
            code="PROVIDER_CAPABILITY_CONFLICT",
            reason="MOKA_REQUIRES_FIXED_FUNDING_UNITS",
        )
    if requested is RequestedReleaseMode.ALL_OR_NOTHING:
        return ReleaseMode.ALL_OR_NOTHING, None
    if requested is RequestedReleaseMode.FIXED_TRANCHES:
        if not capabilities.supports_fixed_tranches:
            raise ProviderCapabilityConflictError(
                code="PROVIDER_CAPABILITY_CONFLICT",
                reason="PROVIDER_FIXED_TRANCHES_UNSUPPORTED",
            )
        if override.tranche_count is None:
            raise FundingPlanValidationError(
                f"fixed_tranches için tranche_count gerekli (rule_index={rule_index})."
            )
        return ReleaseMode.FIXED_TRANCHES, override.tranche_count

    raise FundingPlanValidationError(f"Desteklenmeyen release_mode: {requested!r}")


def _build_funding_units(
    *,
    rule_index: int,
    milestone_title: str,
    amount_minor: int,
    release_mode: ReleaseMode,
    tranche_count: int | None,
    start_sequence: int,
) -> tuple[FundingUnitDraft, ...]:
    if release_mode is ReleaseMode.ALL_OR_NOTHING:
        return (
            FundingUnitDraft(
                sequence=start_sequence,
                amount_minor=amount_minor,
                eligibility_type="milestone_completion",
                eligibility_payload={
                    "rule_index": rule_index,
                    "milestone_title": milestone_title,
                },
            ),
        )

    assert tranche_count is not None  # _resolve_release_mode garanti eder
    if tranche_count > amount_minor:
        raise FundingPlanValidationError(
            f"rule_index={rule_index}: tranche_count ({tranche_count}) milestone "
            f"amount_minor'dan ({amount_minor}) büyük olamaz — sıfır tutarlı tranche "
            "üretilemez (provider domain komutu amount_minor<=0'ı zaten reddeder)."
        )
    tranche_amounts = _largest_remainder_distribution(
        total=amount_minor,
        weights=[1] * tranche_count,
        tie_break=list(range(tranche_count)),
    )
    units = []
    for offset, tranche_amount in enumerate(tranche_amounts):
        tranche_index = offset + 1
        units.append(
            FundingUnitDraft(
                sequence=start_sequence + offset,
                amount_minor=tranche_amount,
                eligibility_type="milestone_tranche",
                eligibility_payload={
                    "rule_index": rule_index,
                    "milestone_title": milestone_title,
                    "tranche_index": tranche_index,
                    "tranche_count": tranche_count,
                },
            )
        )
    return tuple(units)


def compile_funding_plan(
    rule_set: Sequence[PaymentRule],
    total_amount_minor: int,
    currency: str,
    spec: FundingScheduleSpec,
    capabilities: ProviderCapabilities,
) -> FundingPlanDraft:
    """`rule_set`'i (payment_rules) somut, minor-unit cinsinden bir funding planına derler.

    Saf fonksiyon: DB/HTTP/FastAPI/event/provider çağrısı yapmaz. Aynı girdi
    için her zaman aynı çıktıyı üretir (deterministic largest-remainder).
    """
    if isinstance(total_amount_minor, bool) or not isinstance(total_amount_minor, int):
        raise FundingPlanValidationError("total_amount_minor tam sayı olmalıdır.")
    if total_amount_minor <= 0:
        raise FundingPlanValidationError("total_amount_minor sıfırdan büyük olmalıdır.")
    if not isinstance(currency, str) or not currency.strip():
        raise FundingPlanValidationError("currency boş olamaz.")
    if not rule_set:
        raise FundingPlanValidationError("rule_set boş olamaz.")

    overrides_by_index = _validate_overrides(spec, rule_count=len(rule_set))

    basis_points = [_percentage_to_basis_points(rule.percentage) for rule in rule_set]
    for rule_index, bp in enumerate(basis_points):
        if bp <= 0:
            raise FundingPlanValidationError(
                f"rule_index={rule_index}: percentage sıfır (veya negatif) olamaz — "
                "sıfır tutarlı milestone/funding unit üretilemez."
            )
    basis_points_total = sum(basis_points)
    if basis_points_total != _BASIS_POINTS_TOTAL:
        raise FundingPlanValidationError(
            "Rule percentage toplamı %100 (10000 basis point) değil: "
            f"{basis_points_total} bp."
        )

    milestone_amounts = _largest_remainder_distribution(
        total=total_amount_minor,
        weights=basis_points,
        tie_break=list(range(len(rule_set))),
    )
    for rule_index, amount in enumerate(milestone_amounts):
        if amount <= 0:
            raise FundingPlanValidationError(
                f"rule_index={rule_index}: largest-remainder dağıtımı sıfır tutarlı "
                "milestone üretti (total_amount_minor bu rule sayısı/oranı için çok "
                "küçük) — provider domain komutu amount_minor<=0'ı zaten reddeder."
            )

    milestones: list[MilestoneDraft] = []
    sequence = 1
    for rule_index, rule in enumerate(rule_set):
        release_mode, tranche_count = _resolve_release_mode(
            rule_index, overrides_by_index, capabilities
        )
        amount_minor = milestone_amounts[rule_index]
        funding_units = _build_funding_units(
            rule_index=rule_index,
            milestone_title=rule.milestone,
            amount_minor=amount_minor,
            release_mode=release_mode,
            tranche_count=tranche_count,
            start_sequence=sequence,
        )
        sequence += len(funding_units)

        milestones.append(
            MilestoneDraft(
                rule_index=rule_index,
                title=rule.milestone,
                trigger_type=rule.trigger.value,
                basis_points=basis_points[rule_index],
                amount_minor=amount_minor,
                currency=currency,
                required_evidence=tuple(evidence.value for evidence in rule.required_evidence),
                release_mode=release_mode,
                funding_units=funding_units,
            )
        )

    return FundingPlanDraft(
        milestones=tuple(milestones),
        total_amount_minor=total_amount_minor,
        currency=currency,
    )
