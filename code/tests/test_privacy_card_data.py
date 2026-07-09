"""`privacy.analyze()` kart-verisi güvenlik katmanı testleri — §6.7 + PCI.

Kaçak riski yüksek: PAN restore edilmemeli, SAD (CVV/track/PIN) blocking
üretmeli, ve mevcut PII (IBAN/TCKN/VKN) davranışı bozulmamalı. False-positive
negatif örnekleri zorunludur (bağlamsız 3-4 hane blocking'i tetiklememeli).
"""

from backend.app.services.privacy import PrivacyReport, analyze, restore

# Luhn-geçerli test kart numaraları (gerçek kart değil).
VALID_PAN = "4111111111111111"          # Visa test PAN, Luhn OK
VALID_PAN_GROUPED = "4111 1111 1111 1111"
INVALID_PAN = "4111111111111112"        # son hane bozuk → Luhn FAIL
IBAN = "TR330006100519786457841326"
TCKN = "12345678950"
VKN = "1234567890"


def test_valid_pan_is_masked_and_detected():
    report = analyze(f"Kart no: {VALID_PAN}")
    assert isinstance(report, PrivacyReport)
    assert "PAN" in report.detected_types
    assert VALID_PAN not in report.masked_text
    assert "[[CARD_PAN_1]]" in report.masked_text


def test_grouped_pan_is_masked():
    report = analyze(f"Kart: {VALID_PAN_GROUPED}")
    assert "PAN" in report.detected_types
    assert VALID_PAN_GROUPED not in report.masked_text


def test_pan_never_in_mapping_and_not_restored():
    report = analyze(f"Kart no: {VALID_PAN}")
    # Kart token'ı restore edilebilir mapping'e girmez.
    assert all("CARD_PAN" not in tok for tok in report.mapping)
    restored = restore(report.masked_text, report.mapping)
    assert VALID_PAN not in restored          # DO_NOT_RESTORE garantisi
    assert "[[CARD_PAN_1]]" in restored        # token yerinde kalır


def test_non_luhn_16_digits_not_flagged_as_pan():
    report = analyze(f"Referans: {INVALID_PAN}")
    assert "PAN" not in report.detected_types
    # Luhn'dan geçmeyen sayı PAN token'ına dönmez (ham kalır veya başka PII değil).
    assert "[[CARD_PAN" not in report.masked_text


def test_pan_alone_is_not_blocking():
    report = analyze(f"Kart no: {VALID_PAN}")
    assert report.blocking_findings == []      # PAN SAD değil → blocking yok
    assert "PAN_DETECTED" in report.risk_flags


def test_cvv_keyword_triggers_blocking_and_masks_value():
    report = analyze("Kart doğrulama CVV: 123")
    assert "CVV" in report.detected_types
    assert report.blocking_findings                # dolu → canlı LLM atlanır
    assert "123" not in report.masked_text
    assert "CVV" in report.masked_text             # anahtar kelime korunur


def test_cvv_reverse_order_detected():
    report = analyze("Güvenlik: 456 cvc")
    assert "CVV" in report.detected_types


def test_bare_three_digit_number_is_not_cvv():
    # Anahtar kelime yok → false positive olmamalı (demo akışı durmasın).
    report = analyze("Miktar: 100 adet, kalite sınıfı 250.")
    assert "CVV" not in report.detected_types
    assert report.blocking_findings == []


def test_pin_keyword_triggers_blocking():
    report = analyze("İşlem PIN: 4821 ile onaylanır.")
    assert "PIN" in report.detected_types
    assert any("PIN" in f for f in report.blocking_findings)
    assert "4821" not in report.masked_text


def test_bare_four_digit_number_is_not_pin():
    report = analyze("Sipariş kodu 4821 numaralı üründür.")
    assert "PIN" not in report.detected_types
    assert report.blocking_findings == []


def test_track_data_triggers_blocking():
    track = "%B4111111111111111^DOE/JOHN^25051010000000000000?"
    report = analyze(f"Manyetik şerit: {track}")
    assert "TRACK_DATA" in report.detected_types
    assert report.blocking_findings
    assert track not in report.masked_text


def test_iban_still_masked_and_round_trips_through_analyze():
    # Regresyon: PAN aday deseni IBAN'ın gruplu hanelerini bozmamalı.
    report = analyze(f"IBAN: {IBAN}. Ödeme buradan yapılır.")
    assert IBAN not in report.masked_text
    assert "[[PII_IBAN_1]]" in report.masked_text
    assert "PAN" not in report.detected_types      # IBAN PAN sanılmaz
    restored = restore(report.masked_text, report.mapping)
    assert IBAN in restored


def test_existing_pii_tckn_vkn_masked_via_analyze():
    report = analyze(f"TCKN: {TCKN}, VKN: {VKN}")
    assert TCKN not in report.masked_text
    assert VKN not in report.masked_text
    assert report.mapping  # standart PII mapping mevcut


def test_expiry_with_pan_adds_chd_context_flag():
    report = analyze(f"Kart {VALID_PAN}, son kullanma 08/27")
    assert "CHD_CONTEXT" in report.risk_flags


def test_expiry_without_pan_no_chd_context():
    report = analyze("Teslim tarihi 08/27 olarak planlandı.")
    assert "CHD_CONTEXT" not in report.risk_flags
    assert "PAN" not in report.detected_types


def test_clean_text_has_no_findings():
    report = analyze("Endüstriyel pompa 10 adet, teslimat 2026-09-01.")
    assert report.detected_types == set()
    assert report.blocking_findings == []
    assert report.risk_flags == []
