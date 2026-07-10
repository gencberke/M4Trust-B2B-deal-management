"""Policy-aware, saf ödeme karar semantiği testleri."""

from __future__ import annotations

import copy

import pytest

from backend.app.config import Settings
from backend.app.schemas.extraction import ExtractionJSON, RequiredEvidence
from backend.app.services.decision import DeliveryEvidence, decide
from backend.app.services.effective_requirements import EffectiveEvidenceRequirements


def _payload(*, quantity: float = 10.0) -> dict:
    return {
        "contract_id": "sozlesme-decision-001",
        "parties": {
            "buyer": {"name": "Alici A.S.", "tax_id": "1234567890"},
            "seller": {"name": "Satici Ltd.", "tax_id": "9876543210"},
        },
        "commercial_terms": {
            "currency": "TRY",
            "total_amount": 10000.0,
            "goods": [{"name": "Cimento", "quantity": quantity, "unit": "ton"}],
            "delivery_deadline": "2026-01-01",
        },
        "payment_rules": [],
        "risk_flags": [],
        "needs_manual_review": False,
    }


def _extraction(*, quantity: float = 10.0) -> ExtractionJSON:
    return ExtractionJSON.model_validate(copy.deepcopy(_payload(quantity=quantity)))


def _requirements(
    *,
    contractual: set[RequiredEvidence] | None = None,
    operational: set[RequiredEvidence] | None = None,
    advisory: set[RequiredEvidence] | None = None,
) -> EffectiveEvidenceRequirements:
    contractual = contractual or {RequiredEvidence.contract}
    operational = operational or set()
    advisory = advisory or set()
    return EffectiveEvidenceRequirements(
        contractual_required_evidence=frozenset(contractual),
        operational_required_evidence=frozenset(operational),
        advisory_evidence=frozenset(advisory),
        effective_required_evidence=frozenset(contractual | operational),
    )


def _decide(
    extraction: ExtractionJSON,
    requirements: EffectiveEvidenceRequirements,
    evidence: DeliveryEvidence,
):
    return decide(
        extraction,
        requirements,
        evidence,
        video_confidence_threshold=0.80,
        divergence_threshold=0.10,
    )


def _finding_codes(result) -> set[str]:
    return {finding.code for finding in result.findings}


def test_approval_only_captures_before_quantity_validation() -> None:
    result = _decide(
        _extraction(quantity=0.0),
        _requirements(),
        DeliveryEvidence(e_irsaliye=None, video=None),
    )

    assert result.action == "capture"
    assert result.capture_ratio == 1.0
    assert result.manual_review_required is False


@pytest.mark.parametrize(
    ("delivered_quantity", "action", "ratio"),
    [(10.0, "capture", 1.0), (6.0, "partial_capture", 0.6)],
)
def test_document_only_uses_e_irsaliye_for_full_and_partial_capture(
    delivered_quantity: float,
    action: str,
    ratio: float,
) -> None:
    result = _decide(
        _extraction(),
        _requirements(operational={RequiredEvidence.e_irsaliye}),
        DeliveryEvidence(e_irsaliye={"delivered_quantity": delivered_quantity}, video=None),
    )

    assert result.action == action
    assert result.capture_ratio == ratio


def test_missing_effective_e_irsaliye_holds() -> None:
    result = _decide(
        _extraction(),
        _requirements(operational={RequiredEvidence.e_irsaliye}),
        DeliveryEvidence(e_irsaliye=None, video=None),
    )

    assert result.action == "hold"
    assert "MISSING_REQUIRED_EVIDENCE" in _finding_codes(result)


def test_missing_advisory_video_is_informational_and_nonblocking() -> None:
    result = _decide(
        _extraction(),
        _requirements(
            operational={RequiredEvidence.e_irsaliye},
            advisory={RequiredEvidence.video},
        ),
        DeliveryEvidence(e_irsaliye={"delivered_quantity": 10.0}, video=None),
    )

    assert result.action == "capture"
    assert "VIDEO_NOT_PROVIDED" in _finding_codes(result)


@pytest.mark.parametrize(
    "video",
    [
        {"unit_count": 5, "damage_signals": [], "confidence": 0.9},
        {
            "unit_count": 10,
            "damage_signals": [
                {"type": "hasar_tespiti", "confidence": 0.9, "matched_box": True}
            ],
            "confidence": 0.9,
        },
    ],
)
def test_high_confidence_advisory_anomaly_holds_without_dispute(video: dict) -> None:
    result = _decide(
        _extraction(),
        _requirements(
            operational={RequiredEvidence.e_irsaliye},
            advisory={RequiredEvidence.video},
        ),
        DeliveryEvidence(e_irsaliye={"delivered_quantity": 10.0}, video=video),
    )

    assert result.action == "hold"
    assert result.action != "dispute"
    assert result.capture_ratio == 0.0
    assert result.manual_review_required is True
    assert any(finding.severity == "review" for finding in result.findings)


def test_low_confidence_advisory_video_warns_without_blocking_capture() -> None:
    result = _decide(
        _extraction(),
        _requirements(
            operational={RequiredEvidence.e_irsaliye},
            advisory={RequiredEvidence.video},
        ),
        DeliveryEvidence(
            e_irsaliye={"delivered_quantity": 10.0},
            video={
                "unit_count": 1,
                "damage_signals": [
                    {"type": "hasar_tespiti", "confidence": 0.95, "matched_box": True}
                ],
                "confidence": 0.79,
            },
        ),
    )

    assert result.action == "capture"
    assert result.manual_review_required is False
    assert "VIDEO_LOW_CONFIDENCE" in _finding_codes(result)


def test_video_alone_cannot_produce_a_quantity_based_payment_decision() -> None:
    result = _decide(
        _extraction(),
        _requirements(contractual={RequiredEvidence.contract, RequiredEvidence.video}),
        DeliveryEvidence(
            e_irsaliye=None,
            video={"unit_count": 10, "damage_signals": [], "confidence": 0.9},
        ),
    )

    assert result.action == "hold"
    assert "PRIMARY_EVIDENCE_MISSING" in _finding_codes(result)


def test_missing_contractual_video_holds() -> None:
    result = _decide(
        _extraction(),
        _requirements(contractual={RequiredEvidence.contract, RequiredEvidence.video}),
        DeliveryEvidence(e_irsaliye=None, video=None),
    )

    assert result.action == "hold"
    assert "MISSING_REQUIRED_EVIDENCE" in _finding_codes(result)


def test_contractual_video_anomaly_is_evaluated_even_without_advisory_role() -> None:
    """Zorunlu videonun yalnızca varlığını saymak, hasarı görmezden gelmek olurdu.

    Policy katmanı bu kombinasyonu artık reddediyor; yine de saf karar motoru
    kendi başına güvenli olmalı (upstream doğrulamaya bel bağlamamalı).
    """
    result = _decide(
        _extraction(),
        _requirements(
            contractual={RequiredEvidence.contract, RequiredEvidence.video},
            operational={RequiredEvidence.e_irsaliye},
        ),
        DeliveryEvidence(
            e_irsaliye={"delivered_quantity": 10.0},
            video={
                "unit_count": 3,
                "damage_signals": [
                    {"type": "hasar_tespiti", "confidence": 0.95, "matched_box": True}
                ],
                "confidence": 0.95,
            },
        ),
    )

    assert result.action == "hold"
    assert result.capture_ratio == 0.0
    assert result.manual_review_required is True
    assert "VIDEO_COUNT_DIVERGENCE" in _finding_codes(result)


def test_video_advisory_confidence_threshold_has_safe_default_and_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings.from_env().video_advisory_confidence_threshold == 0.80

    monkeypatch.setenv("VIDEO_ADVISORY_CONFIDENCE_THRESHOLD", "0.91")
    assert Settings.from_env().video_advisory_confidence_threshold == 0.91
