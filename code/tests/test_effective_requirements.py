"""Saf effective-evidence resolver sözleşmesi."""

from __future__ import annotations

import pytest

from backend.app.schemas.extraction import ExtractionJSON, RequiredEvidence
from backend.app.schemas.tracking import TrackingMode, TrackingPolicySnapshot, TrackingPolicyStatus

try:
    from backend.app.services.effective_requirements import (
        EffectiveEvidenceRequirements,
        resolve_effective_requirements,
    )
except ImportError:  # RED aşamasında modül henüz yoktur.
    EffectiveEvidenceRequirements = None
    resolve_effective_requirements = None


def _extraction() -> ExtractionJSON:
    return ExtractionJSON.model_validate(
        {
            "contract_id": "effective-requirements-001",
            "parties": {
                "buyer": {"name": "Alıcı A.Ş."},
                "seller": {"name": "Satıcı Ltd."},
            },
            "commercial_terms": {
                "currency": "TRY",
                "total_amount": 1000.0,
                "goods": [{"name": "Koli", "quantity": 10.0, "unit": "adet"}],
                "delivery_deadline": None,
            },
            "payment_rules": [
                {
                    "milestone": "Teslimat",
                    "trigger": "delivery_video",
                    "percentage": 100.0,
                    "required_evidence": ["contract", "video"],
                    "source_quote": "Video teslimat kaydıdır.",
                    "confidence": 0.9,
                }
            ],
            "risk_flags": [],
        }
    )


def _policy(mode: TrackingMode) -> TrackingPolicySnapshot:
    return TrackingPolicySnapshot(
        transaction_id="effective-requirements-001",
        manager_physical_delivery_confirmed=mode is not TrackingMode.off,
        tracking_mode=mode,
        status=TrackingPolicyStatus.locked,
    )


@pytest.mark.parametrize(
    ("mode", "operational", "advisory", "effective"),
    [
        (TrackingMode.off, set(), set(), {RequiredEvidence.contract, RequiredEvidence.video}),
        (
            TrackingMode.document_only,
            {RequiredEvidence.e_irsaliye},
            set(),
            {RequiredEvidence.contract, RequiredEvidence.e_irsaliye, RequiredEvidence.video},
        ),
        (
            TrackingMode.document_and_video,
            {RequiredEvidence.e_irsaliye},
            {RequiredEvidence.video},
            {RequiredEvidence.contract, RequiredEvidence.e_irsaliye, RequiredEvidence.video},
        ),
    ],
)
def test_resolver_preserves_contractual_requirements_and_adds_only_policy_evidence(
    mode: TrackingMode,
    operational: set[RequiredEvidence],
    advisory: set[RequiredEvidence],
    effective: set[RequiredEvidence],
) -> None:
    assert EffectiveEvidenceRequirements is not None
    assert resolve_effective_requirements is not None

    requirements = resolve_effective_requirements(_extraction(), _policy(mode))

    assert requirements.contractual_required_evidence == frozenset(
        {RequiredEvidence.contract, RequiredEvidence.video}
    )
    assert requirements.operational_required_evidence == frozenset(operational)
    assert requirements.advisory_evidence == frozenset(advisory)
    assert requirements.effective_required_evidence == frozenset(effective)
