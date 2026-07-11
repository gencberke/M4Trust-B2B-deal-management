"""Ratification package + ratification değer tipleri (Plan 04 / Wave B / Faz 4D-4E)."""

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


class RatificationPackagePublicView(BaseModel):
    """`GET .../ratification-packages/current` cevabı.

    Her iki tarafın da aynı canonical projeksiyonu ve aynı `package_hash`'i
    görmesi gerekir (v2 §2.15) — ham doküman/extraction/token/secret taşımaz,
    `canonical_payload_json` zaten yalnız hash/derive edilmiş özet verisi
    içerir (bkz. `services/ratification_package.py::_build_inputs`).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    transaction_id: str
    version: int
    status: RatificationPackageStatus
    package_hash: str
    canonical_payload: dict
    created_at: str
    opened_at: str | None = None
    completed_at: str | None = None


class Ratification(BaseModel):
    """`ratifications` satırının servis-katmanı görünümü (Faz 4E)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    package_id: str
    transaction_id: str
    participant_id: str
    user_id: str
    legal_entity_id: str
    participant_role: str
    auth_method: str
    approved_at: str
    client_ip_hash: str | None = None
    user_agent_summary: str | None = None


class RatificationOutcome(BaseModel):
    """`create_ratification` çıktısı: kayıt + package tamamlanma durumu."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ratification: Ratification
    package_status: RatificationPackageStatus
    funding_triggered: bool
