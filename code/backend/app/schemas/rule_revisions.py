"""Dedicated request schema for account rule revisions.

The frozen :class:`ExtractionJSON` contract remains unchanged.  A revision
request may omit a payment rule's ``source_quote`` because the revision
service reconstructs it from the current parent version before validating the
complete payload against ``ExtractionJSON``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from backend.app.schemas.extraction import (
    CommercialTerms,
    Parties,
    RequiredEvidence,
    Trigger,
)


class RevisionPaymentRule(BaseModel):
    """Payment rule input whose quote is optional for safe redacted edits."""

    model_config = ConfigDict(extra="forbid")

    milestone: str
    trigger: Trigger
    percentage: float
    required_evidence: list[RequiredEvidence]
    source_quote: str | None = None
    confidence: float


class ExtractionRevisionRequest(BaseModel):
    """Full extraction-shaped revision request, with optional source quotes."""

    model_config = ConfigDict(extra="forbid")

    contract_id: str
    parties: Parties
    commercial_terms: CommercialTerms
    payment_rules: list[RevisionPaymentRule]
    risk_flags: list[str]
    needs_manual_review: bool = False
