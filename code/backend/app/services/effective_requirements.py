"""Sözleşmesel ve operasyonel teslimat kanıtlarını saf biçimde çözer."""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.schemas.extraction import ExtractionJSON, RequiredEvidence
from backend.app.schemas.tracking import TrackingMode, TrackingPolicySnapshot


@dataclass(frozen=True)
class EffectiveEvidenceRequirements:
    """Karar motorunun okuyacağı değişmez kanıt kümeleri.

    Sözleşme kaynaklı evidence, yönetici policy'siyle çıkarılamaz. Operasyonel
    takip e-irsaliyeyi birincil kanıt olarak ekler; video ise yalnız advisory
    kümesinde tutulur ve efektif ödeme kanıtı olmaz.
    """

    contractual_required_evidence: frozenset[RequiredEvidence]
    operational_required_evidence: frozenset[RequiredEvidence]
    advisory_evidence: frozenset[RequiredEvidence]
    effective_required_evidence: frozenset[RequiredEvidence]


def _contractual_evidence(extraction: ExtractionJSON) -> frozenset[RequiredEvidence]:
    return frozenset(
        evidence
        for rule in extraction.payment_rules
        for evidence in rule.required_evidence
    )


def resolve_effective_requirements(
    extraction: ExtractionJSON,
    policy: TrackingPolicySnapshot,
) -> EffectiveEvidenceRequirements:
    """Kilitli/geçerli policy'den saf efektif kanıt gereksinimi üretir.

    Policy doğrulaması bu fonksiyonun sorumluluğu değildir; çağıran taraf
    yalnız kilitli ve geçerli policy vermelidir.
    """

    contractual = _contractual_evidence(extraction)
    operational: frozenset[RequiredEvidence] = frozenset()
    advisory: frozenset[RequiredEvidence] = frozenset()

    if policy.tracking_mode is TrackingMode.document_only:
        operational = frozenset({RequiredEvidence.e_irsaliye})
    elif policy.tracking_mode is TrackingMode.document_and_video:
        operational = frozenset({RequiredEvidence.e_irsaliye})
        advisory = frozenset({RequiredEvidence.video})

    return EffectiveEvidenceRequirements(
        contractual_required_evidence=contractual,
        operational_required_evidence=operational,
        advisory_evidence=advisory,
        effective_required_evidence=contractual | operational,
    )
