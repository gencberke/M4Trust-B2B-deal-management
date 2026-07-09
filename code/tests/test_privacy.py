"""`privacy.mask`/`restore` için davranışsal testler — §6.7 dış-çağrı sınırı.

Kaçak riski yüksek olduğundan her PII tipi için ayrı ayrı ve birlikte
(round-trip) doğrulanır.
"""

from backend.app.services.privacy import MaskResult, mask, restore

TCKN = "12345678950"
VKN = "1234567890"
IBAN = "TR330006100519786457841326"
PHONE = "+90 532 111 22 33"
EMAIL = "a@b.com"

SAMPLE_TEXT = (
    f"Alıcı TCKN: {TCKN}, satıcı VKN: {VKN}. "
    f"IBAN: {IBAN}. Telefon: {PHONE}. E-posta: {EMAIL}. "
    "Miktar: 100 adet."
)


def test_mask_removes_all_pii_originals() -> None:
    result = mask(SAMPLE_TEXT)
    assert isinstance(result, MaskResult)
    for original in (TCKN, VKN, IBAN, PHONE, EMAIL):
        assert original not in result.masked_text


def test_mask_uses_pii_token_format_per_type() -> None:
    result = mask(SAMPLE_TEXT)
    assert "[[PII_TCKN_1]]" in result.masked_text
    assert "[[PII_VKN_1]]" in result.masked_text
    assert "[[PII_IBAN_1]]" in result.masked_text
    assert "[[PII_PHONE_1]]" in result.masked_text
    assert "[[PII_EMAIL_1]]" in result.masked_text
    assert result.mapping["[[PII_TCKN_1]]"] == TCKN
    assert result.mapping["[[PII_VKN_1]]"] == VKN
    assert result.mapping["[[PII_IBAN_1]]"] == IBAN
    assert result.mapping["[[PII_PHONE_1]]"] == PHONE
    assert result.mapping["[[PII_EMAIL_1]]"] == EMAIL


def test_non_pii_quantity_is_not_masked() -> None:
    result = mask(SAMPLE_TEXT)
    assert "100" in result.masked_text


def test_round_trip_restore_equals_original() -> None:
    result = mask(SAMPLE_TEXT)
    restored = restore(result.masked_text, result.mapping)
    assert restored == SAMPLE_TEXT


def test_restore_on_nested_dict_and_list() -> None:
    result = mask(SAMPLE_TEXT)
    payload = {
        "tax_id": "[[PII_VKN_1]]",
        "nested": ["[[PII_IBAN_1]]"],
    }
    restored = restore(payload, result.mapping)
    assert restored == {"tax_id": VKN, "nested": [IBAN]}


def test_restore_passes_through_non_str_dict_list_values() -> None:
    result = mask(SAMPLE_TEXT)
    payload = {
        "amount": 100.5,
        "active": True,
        "note": None,
        "id": "[[PII_TCKN_1]]",
    }
    restored = restore(payload, result.mapping)
    assert restored == {
        "amount": 100.5,
        "active": True,
        "note": None,
        "id": TCKN,
    }


def test_idempotent_same_value_yields_same_token_both_occurrences() -> None:
    text = f"Birinci: {TCKN}. İkinci tekrar: {TCKN}."
    result = mask(text)
    assert result.masked_text.count("[[PII_TCKN_1]]") == 2
    assert "[[PII_TCKN_2]]" not in result.masked_text
    assert len(result.mapping) == 1


def test_different_values_of_same_type_get_distinct_tokens() -> None:
    other_iban = "TR640001000123456789012345"
    text = f"{IBAN} ve {other_iban}"
    result = mask(text)
    assert "[[PII_IBAN_1]]" in result.masked_text
    assert "[[PII_IBAN_2]]" in result.masked_text
    assert result.mapping["[[PII_IBAN_1]]"] == IBAN
    assert result.mapping["[[PII_IBAN_2]]"] == other_iban


def test_mask_result_mapping_is_placeholder_to_original() -> None:
    result = mask(f"e-posta: {EMAIL}")
    for token, original in result.mapping.items():
        assert token.startswith("[[PII_") and token.endswith("]]")
        assert original in (EMAIL,)


def test_grouped_iban_is_masked_and_round_trips() -> None:
    grouped_iban = "TR33 0006 1005 1978 6457 8413 26"
    text = f"IBAN: {grouped_iban}."
    result = mask(text)
    assert grouped_iban not in result.masked_text
    restored = restore(result.masked_text, result.mapping)
    assert restored == text
