"""`services/decision.py` testleri — decision engine'in her karar dalı.

Saf fonksiyon test edilir: I/O yok, doğrudan `ExtractionJSON` ve
`DeliveryEvidence` inşa edilir (fake fixture'lara bağımlılık yok).
"""

from __future__ import annotations

import copy

from backend.app.schemas.extraction import ExtractionJSON
from backend.app.services.decision import DeliveryEvidence, decide


def _payload(*, quantity: float = 10.0, required_evidence: list[str] | None = None) -> dict:
    """Tek kural, tek kalemli taban extraction sözlüğü."""
    if required_evidence is None:
        required_evidence = ["contract", "e_irsaliye"]
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
        "payment_rules": [
            {
                "milestone": "Teslimat",
                "trigger": "e_invoice",
                "percentage": 100.0,
                "required_evidence": required_evidence,
                "source_quote": "Teslimatta tüm tutar ödenir.",
                "confidence": 0.9,
            }
        ],
        "risk_flags": [],
        "needs_manual_review": False,
    }


def _extraction(*, quantity: float = 10.0, required_evidence: list[str] | None = None) -> ExtractionJSON:
    payload = copy.deepcopy(_payload(quantity=quantity, required_evidence=required_evidence))
    return ExtractionJSON.model_validate(payload)


# --- HOLD: eksik kanıt ---------------------------------------------------


def test_hold_when_required_video_missing():
    extraction = _extraction(required_evidence=["contract", "video"])
    evidence = DeliveryEvidence(e_irsaliye=None, video=None)
    result = decide(extraction, evidence)
    assert result.action == "hold"
    assert result.capture_ratio == 0.0
    assert "video" in result.rationale


def test_hold_when_required_e_irsaliye_missing():
    extraction = _extraction(required_evidence=["contract", "e_irsaliye"])
    evidence = DeliveryEvidence(e_irsaliye=None, video={"counts": 10, "damage_signals": [], "confidence": 0.9})
    result = decide(extraction, evidence)
    assert result.action == "hold"
    assert "e_irsaliye" in result.rationale


# --- CAPTURE: tam teslimat -------------------------------------------------


def test_capture_on_full_delivery_no_conflict():
    extraction = _extraction(quantity=10.0, required_evidence=["contract", "e_irsaliye"])
    evidence = DeliveryEvidence(e_irsaliye={"delivered_quantity": 10.0}, video=None)
    result = decide(extraction, evidence)
    assert result.action == "capture"
    assert result.capture_ratio == 1.0


# --- PARTIAL_CAPTURE: eksik teslimat ---------------------------------------


def test_partial_capture_ratio_computed_correctly():
    extraction = _extraction(quantity=10.0, required_evidence=["contract", "e_irsaliye"])
    evidence = DeliveryEvidence(e_irsaliye={"delivered_quantity": 6.0}, video=None)
    result = decide(extraction, evidence)
    assert result.action == "partial_capture"
    assert result.capture_ratio == 0.6


def test_over_delivery_clamped_to_capture_not_partial():
    """Teslim edilen sözleşme miktarını aşarsa oran 1.0'a kısılır -> capture, partial değil."""
    extraction = _extraction(quantity=10.0, required_evidence=["contract", "e_irsaliye"])
    evidence = DeliveryEvidence(e_irsaliye={"delivered_quantity": 15.0}, video=None)
    result = decide(extraction, evidence)
    assert result.action == "capture"
    assert result.capture_ratio == 1.0


# --- DISPUTE: çelişki --------------------------------------------------


def test_dispute_when_quantities_diverge_over_threshold():
    extraction = _extraction(quantity=10.0, required_evidence=["contract", "e_irsaliye", "video"])
    evidence = DeliveryEvidence(
        e_irsaliye={"delivered_quantity": 10.0},
        video={"counts": 5, "damage_signals": [], "confidence": 0.9},  # %50 ayrışma
    )
    result = decide(extraction, evidence)
    assert result.action == "dispute"
    assert result.capture_ratio == 0.0


def test_dispute_when_damage_signals_present_even_if_quantities_agree():
    extraction = _extraction(quantity=10.0, required_evidence=["contract", "e_irsaliye", "video"])
    evidence = DeliveryEvidence(
        e_irsaliye={"delivered_quantity": 10.0},
        video={"counts": 10, "damage_signals": ["hasar_tespiti"], "confidence": 0.9},
    )
    result = decide(extraction, evidence)
    assert result.action == "dispute"
    assert result.capture_ratio == 0.0


def test_small_divergence_within_threshold_does_not_dispute():
    """Ayrışma eşiğin (yüzde 10) altındaysa çelişki tetiklenmez."""
    extraction = _extraction(quantity=10.0, required_evidence=["contract", "e_irsaliye", "video"])
    evidence = DeliveryEvidence(
        e_irsaliye={"delivered_quantity": 10.0},
        video={"counts": 9.5, "damage_signals": [], "confidence": 0.9},  # %5 ayrışma
    )
    result = decide(extraction, evidence)
    assert result.action == "capture"


# --- Sıfır sözleşme miktarı -------------------------------------------------


def test_zero_contract_quantity_holds_without_division_error():
    extraction = _extraction(quantity=0.0, required_evidence=["contract", "e_irsaliye"])
    evidence = DeliveryEvidence(e_irsaliye={"delivered_quantity": 0.0}, video=None)
    result = decide(extraction, evidence)
    assert result.action == "hold"
    assert result.capture_ratio == 0.0


# --- Sıralama: çelişki, kısmi teslimattan önce kontrol edilir ---------------


def test_conflict_wins_over_under_delivery_when_both_apply():
    """Hem eksik teslimat hem çelişki varsa -> dispute kazanır (sıra: 2 > 3)."""
    extraction = _extraction(quantity=10.0, required_evidence=["contract", "e_irsaliye", "video"])
    evidence = DeliveryEvidence(
        e_irsaliye={"delivered_quantity": 6.0},  # eksik teslimat (6/10)
        video={"counts": 6, "damage_signals": ["hasar_tespiti"], "confidence": 0.9},  # + hasar sinyali
    )
    result = decide(extraction, evidence)
    assert result.action == "dispute"
    assert result.capture_ratio == 0.0
