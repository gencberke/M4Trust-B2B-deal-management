import pytest
from pydantic import ValidationError

from backend.app.schemas.extraction import ExtractionJSON


def _valid_payload():
    return {
        "contract_id": "sozlesme-001",
        "parties": {
            "buyer": {"name": "Alici A.S.", "tax_id": "1234567890"},
            "seller": {"name": "Satici Ltd.", "tax_id": None},
        },
        "commercial_terms": {
            "currency": "TRY",
            "total_amount": 15000.50,
            "goods": [{"name": "Cimento", "quantity": 100, "unit": "ton"}],
            "delivery_deadline": "2026-01-01",
        },
        "payment_rules": [
            {
                "milestone": "Onay üzerine avans",
                "trigger": "approval",
                "percentage": 30,
                "required_evidence": ["contract"],
                "source_quote": "Taraflar mutabakati ile...",
                "confidence": 0.9,
            }
        ],
        "risk_flags": ["gecikme_riski"],
        "needs_manual_review": False,
    }


def test_valid_full_payload_parses():
    parsed = ExtractionJSON.model_validate(_valid_payload())

    assert parsed.contract_id == "sozlesme-001"
    assert parsed.parties.buyer.name == "Alici A.S."
    assert parsed.commercial_terms.currency.value == "TRY"
    assert parsed.payment_rules[0].trigger.value == "approval"
    assert parsed.needs_manual_review is False


def test_delivery_deadline_null_is_valid():
    payload = _valid_payload()
    payload["commercial_terms"]["delivery_deadline"] = None

    parsed = ExtractionJSON.model_validate(payload)

    assert parsed.commercial_terms.delivery_deadline is None


def test_percentage_out_of_range_raises():
    payload = _valid_payload()
    payload["payment_rules"][0]["percentage"] = 150

    with pytest.raises(ValidationError):
        ExtractionJSON.model_validate(payload)


def test_confidence_out_of_range_raises():
    payload = _valid_payload()
    payload["payment_rules"][0]["confidence"] = 1.5

    with pytest.raises(ValidationError):
        ExtractionJSON.model_validate(payload)


def test_invalid_currency_raises():
    payload = _valid_payload()
    payload["commercial_terms"]["currency"] = "GBP"

    with pytest.raises(ValidationError):
        ExtractionJSON.model_validate(payload)


def test_invalid_trigger_raises():
    payload = _valid_payload()
    payload["payment_rules"][0]["trigger"] = "foo"

    with pytest.raises(ValidationError):
        ExtractionJSON.model_validate(payload)


def test_invalid_delivery_deadline_format_raises():
    payload = _valid_payload()
    payload["commercial_terms"]["delivery_deadline"] = "2026/01/01"

    with pytest.raises(ValidationError):
        ExtractionJSON.model_validate(payload)


def test_unknown_extra_field_raises():
    payload = _valid_payload()
    payload["foo"] = 1

    with pytest.raises(ValidationError):
        ExtractionJSON.model_validate(payload)


# --- §4.2 donmuş ikili sözleşme: yapısal snapshot ---------------------------

# Bu sabitler ARCHITECTURE.md §4.2'deki şemanın birebir karşılığıdır. Tracking
# policy işi (opsiyonel fiziksel teslimat ve video takibi) bu şemaya alan
# EKLEMEZ: platformun operasyonel takip tercihi `schemas/tracking.py`de yaşar.
# Bu test kırılıyorsa şema değişmiştir ve ekip mutabakatı gerekir.
_FROZEN_FIELDS = {
    "ExtractionJSON": [
        "contract_id",
        "parties",
        "commercial_terms",
        "payment_rules",
        "risk_flags",
        "needs_manual_review",
    ],
    "Party": ["name", "tax_id"],
    "Goods": ["name", "quantity", "unit"],
    "CommercialTerms": ["currency", "total_amount", "goods", "delivery_deadline"],
    "PaymentRule": [
        "milestone",
        "trigger",
        "percentage",
        "required_evidence",
        "source_quote",
        "confidence",
    ],
}


def test_extraction_schema_field_names_are_frozen():
    from backend.app.schemas import extraction as extraction_module

    for model_name, expected_fields in _FROZEN_FIELDS.items():
        model = getattr(extraction_module, model_name)
        assert list(model.model_fields) == expected_fields, model_name


def test_extraction_schema_enum_members_are_frozen():
    from backend.app.schemas.extraction import Currency, RequiredEvidence, Trigger

    assert [c.value for c in Currency] == ["TRY", "USD", "EUR", "OTHER"]
    assert [t.value for t in Trigger] == [
        "approval",
        "e_invoice",
        "delivery_video",
        "manual_review",
    ]
    assert [e.value for e in RequiredEvidence] == ["contract", "e_irsaliye", "video"]
