"""Manual review domain şemaları (Plan 04 / Wave A / Faz 4B, v2 §5.14-5.15).

`ExtractionJSON`den bağımsızdır. `title`/`description`/`reason_code` her zaman
deterministik ve PII'siz üretilir (bkz. `services/review.py`,
`services/reconciliation.py`) — bu yüzden bu modeller GET list ucunda
doğrudan döndürülebilir (ayrı bir "redacted" varyant gerekmez); serbest metin
taşıyan tek alan `ReviewActionRequest.comment`dır ve o da yalnız yetkili
POST ucundan, uzunluk sınırlı ve tarama'dan geçmiş olarak girer.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ReviewPhase(str, Enum):
    pre_ratification = "pre_ratification"
    settlement = "settlement"
    payment = "payment"


class ReviewSourceType(str, Enum):
    validator = "validator"
    party_mismatch = "party_mismatch"
    evidence = "evidence"
    video = "video"
    payment = "payment"
    system = "system"


class ReviewSeverity(str, Enum):
    warning = "warning"
    blocking = "blocking"


class ReviewStatus(str, Enum):
    open = "open"
    evidence_requested = "evidence_requested"
    resolved = "resolved"
    escalated = "escalated"
    cancelled = "cancelled"


# Bir case'in "hâlâ açık/canlı" kabul edildiği durumlar — migration'daki
# partial unique index'in WHERE koşuluyla birebir aynı liste.
ACTIVE_REVIEW_STATUSES = frozenset(
    {ReviewStatus.open, ReviewStatus.evidence_requested, ReviewStatus.escalated}
)


class ReviewActionType(str, Enum):
    comment = "comment"
    request_evidence = "request_evidence"
    resolve_continue = "resolve_continue"
    resolve_reject = "resolve_reject"
    escalate = "escalate"
    escalate_dispute = "escalate_dispute"
    cancel = "cancel"


class ReviewCase(BaseModel):
    """`review_cases` satırının servis-katmanı görünümü."""

    model_config = ConfigDict(extra="forbid")

    id: str
    transaction_id: str
    phase: ReviewPhase
    source_type: ReviewSourceType
    source_id: str | None = None
    reason_code: str
    title: str
    description: str
    severity: ReviewSeverity
    status: ReviewStatus
    assigned_to_user_id: str | None = None
    opened_by_actor_type: str
    opened_by_user_id: str | None = None
    resolved_by_user_id: str | None = None
    resolution_code: str | None = None
    resolution_note: str | None = None
    created_at: str
    resolved_at: str | None = None


class ReviewAction(BaseModel):
    """`review_actions` satırının servis-katmanı görünümü (append-only log)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    review_case_id: str
    actor_user_id: str
    acting_entity_id: str | None = None
    action: ReviewActionType
    payload: dict[str, Any] | None = None
    created_at: str


class ReviewCaseWithActions(BaseModel):
    """`GET .../reviews` tek bir case + eylem geçmişini birlikte döner."""

    model_config = ConfigDict(extra="forbid")

    case: ReviewCase
    actions: list[ReviewAction] = Field(default_factory=list)


class ReviewActionRequest(BaseModel):
    """`POST /api/reviews/{review_case_id}/actions` gövdesi.

    Nested/arbitrary obje kabul edilmez (`extra="forbid"` + düz alanlar).
    `comment`, yalnız bu yetkili uçtan gelen, uzunluk sınırlı serbest
    metindir — audit'e KOPYALANMAZ (yalnız `review_actions.payload_json`'da,
    public-olmayan projeksiyonda kalır).
    """

    model_config = ConfigDict(extra="forbid")

    action: ReviewActionType
    comment: str | None = Field(default=None, max_length=2000)
    resolution_code: str | None = Field(default=None, max_length=64)
