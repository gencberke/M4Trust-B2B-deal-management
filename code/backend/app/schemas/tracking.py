"""Tracking policy'nin extraction sözleşmesinden ayrı domain şemaları.

Bu modeller platformun operasyonel takip tercihini temsil eder; sözleşme
yorumunu taşıyan ``ExtractionJSON``a alan eklemez.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class PhysicalDeliveryRecommendation(str, Enum):
    """Sistemin bağlayıcı olmayan fiziksel teslimat önerisi."""

    yes = "yes"
    no = "no"
    uncertain = "uncertain"


class TrackingMode(str, Enum):
    """Yöneticinin seçebileceği operasyonel takip modu."""

    off = "off"
    document_only = "document_only"
    document_and_video = "document_and_video"


class VideoRole(str, Enum):
    """Platform videosu bu plan boyunca yalnızca ikincil bir sinyaldir."""

    advisory = "advisory"


class TrackingPolicyStatus(str, Enum):
    """Takip policy'sinin taraf onaylarından bağımsız yaşam döngüsü."""

    draft = "draft"
    locked = "locked"


class PolicyConflictCode(str, Enum):
    """Manager policy uçlarının döndürdüğü kararlı, güvenli çatışma kodları."""

    POLICY_NOT_CONFIGURABLE = "POLICY_NOT_CONFIGURABLE"
    POLICY_LOCKED = "POLICY_LOCKED"
    POLICY_INVALID = "POLICY_INVALID"
    POLICY_CONTRACT_CONFLICT = "POLICY_CONTRACT_CONFLICT"


class RecommendationReasonCode(str, Enum):
    """Sözleşme metni sızdırmayan deterministik öneri gerekçeleri."""

    PHYSICAL_GOODS = "PHYSICAL_GOODS"
    PHYSICAL_UNIT = "PHYSICAL_UNIT"
    CONTRACTUAL_E_IRSALIYE = "CONTRACTUAL_E_IRSALIYE"
    DELIVERY_TERMS = "DELIVERY_TERMS"
    SERVICE_ONLY = "SERVICE_ONLY"
    CONFLICTING_SIGNALS = "CONFLICTING_SIGNALS"
    INSUFFICIENT_SIGNAL = "INSUFFICIENT_SIGNAL"


class PhysicalDeliveryRecommendationResult(BaseModel):
    """Saf recommendation helper'ının güvenli çıktısı."""

    model_config = ConfigDict(extra="forbid")

    recommendation: PhysicalDeliveryRecommendation
    reason_codes: list[RecommendationReasonCode] = Field(default_factory=list)


class TrackingPolicySnapshot(BaseModel):
    """Bir transaction için persist edilen tek tracking policy görünümü."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: str
    recommendation: PhysicalDeliveryRecommendation | None = None
    recommendation_reason_codes: list[RecommendationReasonCode] = Field(default_factory=list)
    manager_physical_delivery_confirmed: bool | None = None
    tracking_mode: TrackingMode = TrackingMode.off
    video_role: VideoRole = VideoRole.advisory
    status: TrackingPolicyStatus = TrackingPolicyStatus.draft
    configured_at: str | None = None
    locked_at: str | None = None


class PolicyConflict(BaseModel):
    """409 cevabının PII ve sözleşme metni taşımayan sabit gövdesi."""

    model_config = ConfigDict(extra="forbid")

    code: PolicyConflictCode
    message: str
    conflicts: list[str] = Field(default_factory=list)
