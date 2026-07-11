"""Ratification package değer tipleri (Plan 04 / Wave B / Faz 4D)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class RatificationPackageStatus(str, Enum):
    draft = "draft"
    open = "open"
    complete = "complete"
    superseded = "superseded"
    cancelled = "cancelled"


class RatificationPackage(BaseModel):
    """`ratification_packages` satırının immutable input görünümü."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    transaction_id: str
    version: int
    document_id: str
    rule_set_version_id: str
    tracking_policy_version_id: str | None = None
    canonical_payload_json: str
    document_hash: str
    rule_set_hash: str
    participant_snapshot_hash: str
    tracking_policy_hash: str
    package_hash: str
    status: RatificationPackageStatus
    created_at: str
    opened_at: str | None = None
    completed_at: str | None = None
