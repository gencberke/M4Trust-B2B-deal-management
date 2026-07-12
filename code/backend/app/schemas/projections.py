"""PII-safe read projections used by the authenticated frontend slices."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ReleaseInstructionProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    status: str


class FundingUnitProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    transaction_id: str
    milestone_id: str
    sequence: int
    title: str
    amount_minor: int
    currency: str
    eligibility_type: str
    eligibility_payload: dict[str, str | int | bool | None] = Field(default_factory=dict)
    status: str
    release_instruction_id: str | None = None
    release_instruction_status: str | None = None


class MilestoneProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    transaction_id: str
    rule_set_version_id: str
    rule_index: int
    title: str
    trigger_type: str
    percentage_basis_points: int
    amount_minor: int
    currency: str
    required_evidence: list[str]
    release_mode: str
    status: str
    released_amount_minor: int
    created_at: str
    updated_at: str
    funding_units: list[FundingUnitProjection]


class MilestoneFundingProjection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    transaction_id: str
    package_id: str | None
    milestones: list[MilestoneProjection]
