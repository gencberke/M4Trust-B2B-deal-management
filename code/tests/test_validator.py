"""`services/validator.py` testleri — deterministik kural kapısının her kontrolü.

Saf fonksiyon test edilir: I/O yok, doğrudan `ExtractionJSON` inşa edilir.
"""

from __future__ import annotations

import copy

import pytest

from backend.app.schemas.extraction import ExtractionJSON
from backend.app.services.validator import validate


def _valid_payload() -> dict:
    """Tüm kontrollerden temiz geçen taban extraction sözlüğü."""
    return {
        "contract_id": "sozlesme-001",
        "parties": {
            "buyer": {"name": "Alici A.S.", "tax_id": "1234567890"},
            "seller": {"name": "Satici Ltd.", "tax_id": "9876543210"},
        },
        "commercial_terms": {
            "currency": "TRY",
            "total_amount": 15000.50,
            "goods": [{"name": "Cimento", "quantity": 100, "unit": "ton"}],
            "delivery_deadline": "2026-01-01",
        },
        "payment_rules": [
            {
                "milestone": "Peşinat",
                "trigger": "approval",
                "percentage": 50.0,
                "required_evidence": ["contract"],
                "source_quote": "Sözleşme onayında %50 ödenir.",
                "confidence": 0.9,
            },
            {
                "milestone": "Teslimat",
                "trigger": "e_invoice",
                "percentage": 50.0,
                "required_evidence": ["e_irsaliye"],
                "source_quote": "Teslimatta kalan %50 ödenir.",
                "confidence": 0.85,
            },
        ],
        "risk_flags": [],
        "needs_manual_review": False,
    }


def _extraction(**overrides) -> ExtractionJSON:
    """Taban payload üzerinde derin kopya + override ile `ExtractionJSON` üretir."""
    payload = copy.deepcopy(_valid_payload())
    payload.update(overrides)
    return ExtractionJSON.model_validate(payload)


def _codes(report) -> set[str]:
    return {finding.code for finding in report.findings}


# --- Temiz senaryo -----------------------------------------------------------


def test_valid_payload_passes_with_no_findings():
    report = validate(_extraction())
    assert report.status == "PASS"
    assert report.findings == []


# --- PERCENTAGE_SUM ----------------------------------------------------------


def test_percentage_sum_exactly_100_does_not_trigger_reject():
    report = validate(_extraction())
    assert "PERCENTAGE_SUM" not in _codes(report)


@pytest.mark.parametrize("total_second_percentage", [49.99, 50.01])
def test_percentage_sum_outside_tolerance_rejects(total_second_percentage):
    payload = _valid_payload()
    payload["payment_rules"][1]["percentage"] = total_second_percentage
    report = validate(ExtractionJSON.model_validate(payload))
    assert report.status == "REJECT"
    assert "PERCENTAGE_SUM" in _codes(report)


@pytest.mark.parametrize("total_second_percentage", [49.995, 50.005])
def test_percentage_sum_inside_tolerance_not_rejected_for_sum(total_second_percentage):
    payload = _valid_payload()
    payload["payment_rules"][1]["percentage"] = total_second_percentage
    report = validate(ExtractionJSON.model_validate(payload))
    assert "PERCENTAGE_SUM" not in _codes(report)


# --- NO_RULES ------------------------------------------------------------


def test_empty_payment_rules_rejects():
    payload = _valid_payload()
    payload["payment_rules"] = []
    report = validate(ExtractionJSON.model_validate(payload))
    assert report.status == "REJECT"
    assert "NO_RULES" in _codes(report)


# --- CARD_DATA_LEAK ------------------------------------------------------


def test_card_placeholder_in_source_quote_rejects():
    payload = _valid_payload()
    payload["payment_rules"][0]["source_quote"] = "Kart no: [[CARD_PAN_1]] ile ödendi."
    report = validate(ExtractionJSON.model_validate(payload))
    assert report.status == "REJECT"
    assert "CARD_DATA_LEAK" in _codes(report)


def test_card_placeholder_in_tax_id_still_rejects():
    """Kart token'ı tax_id alanında bile bulunmamalı — muafiyet yalnızca PII taraması içindir."""
    payload = _valid_payload()
    payload["parties"]["seller"]["tax_id"] = "[[CARD_PAN_1]]"
    report = validate(ExtractionJSON.model_validate(payload))
    assert report.status == "REJECT"
    assert "CARD_DATA_LEAK" in _codes(report)


# --- UNMASKED_PII ----------------------------------------------------------


def test_unmasked_iban_in_source_quote_needs_review():
    payload = _valid_payload()
    payload["payment_rules"][0]["source_quote"] = (
        "Ödeme TR33 0006 1005 1978 6457 8413 26 hesabına yapılır."
    )
    report = validate(ExtractionJSON.model_validate(payload))
    assert report.status == "NEEDS_REVIEW"
    assert "UNMASKED_PII" in _codes(report)


def test_legitimate_tax_id_alone_does_not_trigger_unmasked_pii():
    report = validate(_extraction())
    assert "UNMASKED_PII" not in _codes(report)


def test_unmasked_pan_needs_review():
    payload = _valid_payload()
    # Luhn-geçerli örnek kart numarası (test PAN'ı).
    payload["payment_rules"][0]["source_quote"] = "Kart no 4539578763621486 ile denendi."
    report = validate(ExtractionJSON.model_validate(payload))
    assert report.status == "NEEDS_REVIEW"
    assert "UNMASKED_PII" in _codes(report)


# --- LOW_CONFIDENCE --------------------------------------------------------


def test_low_confidence_rule_needs_review():
    payload = _valid_payload()
    payload["payment_rules"][0]["confidence"] = 0.5
    report = validate(ExtractionJSON.model_validate(payload))
    assert report.status == "NEEDS_REVIEW"
    assert "LOW_CONFIDENCE" in _codes(report)


def test_custom_confidence_threshold_respected():
    payload = _valid_payload()
    payload["payment_rules"][0]["confidence"] = 0.75
    # Varsayılan eşik (0.7) ile geçer.
    report_default = validate(ExtractionJSON.model_validate(payload))
    assert "LOW_CONFIDENCE" not in _codes(report_default)
    # Daha yüksek özel eşikle (0.8) düşer.
    report_custom = validate(ExtractionJSON.model_validate(payload), confidence_threshold=0.8)
    assert "LOW_CONFIDENCE" in _codes(report_custom)
    assert report_custom.status == "NEEDS_REVIEW"


# --- EMPTY_SOURCE_QUOTE -----------------------------------------------------


@pytest.mark.parametrize("quote", ["", "   ", "\t\n"])
def test_empty_or_whitespace_source_quote_needs_review(quote):
    payload = _valid_payload()
    payload["payment_rules"][0]["source_quote"] = quote
    report = validate(ExtractionJSON.model_validate(payload))
    assert report.status == "NEEDS_REVIEW"
    assert "EMPTY_SOURCE_QUOTE" in _codes(report)


# --- LLM_MANUAL_REVIEW -------------------------------------------------------


def test_needs_manual_review_flag_needs_review():
    payload = _valid_payload()
    payload["needs_manual_review"] = True
    report = validate(ExtractionJSON.model_validate(payload))
    assert report.status == "NEEDS_REVIEW"
    assert "LLM_MANUAL_REVIEW" in _codes(report)


# --- NON_POSITIVE_AMOUNT -----------------------------------------------------


@pytest.mark.parametrize("amount", [0, -1000.0])
def test_non_positive_total_amount_needs_review(amount):
    payload = _valid_payload()
    payload["commercial_terms"]["total_amount"] = amount
    report = validate(ExtractionJSON.model_validate(payload))
    assert report.status == "NEEDS_REVIEW"
    assert "NON_POSITIVE_AMOUNT" in _codes(report)


# --- RISK_FLAG ---------------------------------------------------------------


def test_pan_detected_risk_flag_needs_review():
    payload = _valid_payload()
    payload["risk_flags"] = ["PAN_DETECTED"]
    report = validate(ExtractionJSON.model_validate(payload))
    assert report.status == "NEEDS_REVIEW"
    assert "RISK_FLAG" in _codes(report)


def test_chd_context_risk_flag_needs_review():
    payload = _valid_payload()
    payload["risk_flags"] = ["CHD_CONTEXT"]
    report = validate(ExtractionJSON.model_validate(payload))
    assert report.status == "NEEDS_REVIEW"
    assert "RISK_FLAG" in _codes(report)


def test_unrelated_risk_flag_does_not_trigger_risk_flag_control():
    payload = _valid_payload()
    payload["risk_flags"] = ["LOW_QUALITY_SCAN"]
    report = validate(ExtractionJSON.model_validate(payload))
    assert "RISK_FLAG" not in _codes(report)


# --- Öncelik: REJECT > NEEDS_REVIEW > PASS -----------------------------------


def test_reject_wins_over_review_when_both_present():
    payload = _valid_payload()
    payload["payment_rules"][1]["percentage"] = 30.0  # toplam 80 -> reject
    payload["payment_rules"][0]["confidence"] = 0.4  # ayrıca review-worthy
    report = validate(ExtractionJSON.model_validate(payload))
    assert report.status == "REJECT"
    codes = _codes(report)
    assert "PERCENTAGE_SUM" in codes
    assert "LOW_CONFIDENCE" in codes
