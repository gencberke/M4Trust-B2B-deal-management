"""Faz 4C — funding-plan compiler girdi sözleşmeleri (Moka §9, v2 §2.3).

Bu modül yalnızca veri sözleşmeleridir: DB/HTTP/FastAPI bağımlılığı yoktur.
`services/payments/funding_plan.py::compile_funding_plan` bu tipleri saf
girdi olarak kullanır. `ReleaseMode`/`RequestedReleaseMode`/
`FundingScheduleSpec` donmuştur (program haritası §5, "04 Faz 4C başında").
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator


class ReleaseMode(str, Enum):
    """`compile_funding_plan`'in ÜRETEBİLECEĞİ (çıktı) release mode kümesi."""

    ALL_OR_NOTHING = "all_or_nothing"
    FIXED_TRANCHES = "fixed_tranches"


class RequestedReleaseMode(str, Enum):
    """Spec üzerinden İSTENEBİLECEK release mode kümesi (reddedilenler dahil).

    `PROPORTIONAL_TO_VERIFIED_QUANTITY` Moka profilinde her zaman reddedilir —
    LLM/manager release mode belirleyemez (bkz. `compile_funding_plan`,
    `PROVIDER_CAPABILITY_CONFLICT` / `MOKA_REQUIRES_FIXED_FUNDING_UNITS`).
    """

    ALL_OR_NOTHING = "all_or_nothing"
    FIXED_TRANCHES = "fixed_tranches"
    PROPORTIONAL_TO_VERIFIED_QUANTITY = "proportional_to_verified_quantity"


class MilestoneReleaseOverride(BaseModel):
    """Belirli bir `rule_index` için varsayılan `all_or_nothing`'i geçersiz kılan istek."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_index: int
    release_mode: RequestedReleaseMode
    tranche_count: int | None = None

    @field_validator("rule_index")
    @classmethod
    def _validate_rule_index(cls, value: int) -> int:
        if value < 0:
            raise ValueError("rule_index negatif olamaz.")
        return value

    @field_validator("tranche_count")
    @classmethod
    def _validate_tranche_count(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("tranche_count en az 1 olmalı.")
        return value


class FundingScheduleSpec(BaseModel):
    """Milestone başına release-mode override listesi.

    Belirtilmeyen (override edilmemiş) her milestone varsayılan olarak
    `all_or_nothing` alır (program haritası §5.14 "Default spec her milestone
    için `all_or_nothing` üretir").
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    overrides: tuple[MilestoneReleaseOverride, ...] = ()


class PaymentResolutionApprovalPublic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    participant_role: str
    user_id: str
    acting_entity_id: str
    created_at: str


class PaymentResolutionPublic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    transaction_id: str
    funding_unit_id: str
    review_case_id: str
    operation_type: str
    status: str
    idempotency_key: str
    requested_by_user_id: str
    requested_by_entity_id: str
    executed_by_user_id: str | None
    created_at: str
    updated_at: str
    approvals: list[PaymentResolutionApprovalPublic]


class PaymentResolutionListPublic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    transaction_id: str
    resolutions: list[PaymentResolutionPublic]
