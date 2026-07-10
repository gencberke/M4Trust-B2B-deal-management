"""Deterministik validator — saf fonksiyon, I/O yok (§6.2/§6.5).

LLM'in ürettiği `ExtractionJSON` çıktısını denetler; ödeme kararı vermez,
yalnızca REJECT/NEEDS_REVIEW/PASS kapısını üretir. Tüm kontroller aşağıdaki
tabloda pinlenmiştir (bkz. plans/ready/backend_iskeleti_ve_islem_akisi.md
"Validator" bölümü). `services/privacy.py`'nin `mask()`/`analyze()`
tespitleri, maskelenmemiş PII ve kart-verisi sızıntısı taramasında yeniden
kullanılır; bu modül `privacy.py`'yi DEĞİŞTİRMEZ.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from backend.app.schemas.extraction import ExtractionJSON
from backend.app.services import privacy

_PERCENTAGE_TOLERANCE = 0.01
_CARD_PLACEHOLDER_MARKER = "[[CARD_"

# `risk_flags` içinde geçen ve tek başına güvenlik uyarısı sayılan işaretler
# (devralınan kontrol — plan §"risk_flags içinde CHD_CONTEXT/PAN_DETECTED/
# security flag").
_SECURITY_RISK_MARKERS = ("CHD_CONTEXT", "PAN_DETECTED", "SECURITY")

_SEVERITY_PRIORITY: dict[str, int] = {"reject": 2, "review": 1}
_STATUS_BY_SEVERITY: dict[str, Literal["REJECT", "NEEDS_REVIEW"]] = {
    "reject": "REJECT",
    "review": "NEEDS_REVIEW",
}


@dataclass(frozen=True)
class ValidatorFinding:
    """Tek bir kontrolün ürettiği bulgu — kod + severity + Türkçe gerekçe."""

    code: str
    severity: Literal["reject", "review"]
    message: str


@dataclass(frozen=True)
class ValidatorReport:
    """`validate()` çıktısı — tek bir status'e indirgenmiş bulgu listesi."""

    status: Literal["PASS", "NEEDS_REVIEW", "REJECT"]
    findings: list[ValidatorFinding]


def _collect_scannable_texts(extraction: ExtractionJSON, *, exclude_tax_id: bool) -> list[str]:
    """Extraction'ın tüm string alanlarını dump edip metin listesine çevirir.

    `exclude_tax_id=True` ise `parties.buyer.tax_id` / `parties.seller.tax_id`
    dışlanır (meşru şema alanı, PII taramasından muaf). Kart-placeholder
    taraması için `exclude_tax_id=False` kullanılır — kart token'ı hiçbir
    alanda (tax_id dahil) bulunmamalıdır.
    """
    dumped = extraction.model_dump(mode="json")

    if exclude_tax_id:
        parties = dumped.get("parties")
        if isinstance(parties, dict):
            for role in ("buyer", "seller"):
                party = parties.get(role)
                if isinstance(party, dict):
                    party.pop("tax_id", None)

    texts: list[str] = []

    def _walk(value: object) -> None:
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                _walk(item)
        elif isinstance(value, list):
            for item in value:
                _walk(item)

    _walk(dumped)
    return texts


def _check_percentage_sum(extraction: ExtractionJSON) -> ValidatorFinding | None:
    # `round(..., 2)`: kayan nokta toplama hatasının (ör. 50.0+49.99 ->
    # 99.99000000000001) tolerans sınırını yanlışlıkla kaydırmasını önler.
    total = round(sum(rule.percentage for rule in extraction.payment_rules), 2)
    # `>=`: tolerans sınırının kendisi (ör. tam ±0.01 sapma) reddi tetikler;
    # yalnızca kesinlikle 0.01'in altındaki sapmalar tolere edilir.
    if abs(total - 100.0) >= _PERCENTAGE_TOLERANCE:
        return ValidatorFinding(
            code="PERCENTAGE_SUM",
            severity="reject",
            message=(
                f"Ödeme kurallarının yüzde toplamı {total:.2f}% — 100%'e eşit olmalı "
                f"(tolerans ±{_PERCENTAGE_TOLERANCE})."
            ),
        )
    return None


def _check_no_rules(extraction: ExtractionJSON) -> ValidatorFinding | None:
    if not extraction.payment_rules:
        return ValidatorFinding(
            code="NO_RULES",
            severity="reject",
            message="Sözleşmeden hiçbir ödeme kuralı çıkarılamadı.",
        )
    return None


def _check_card_data_leak(extraction: ExtractionJSON) -> ValidatorFinding | None:
    texts = _collect_scannable_texts(extraction, exclude_tax_id=False)
    for text in texts:
        if _CARD_PLACEHOLDER_MARKER in text:
            return ValidatorFinding(
                code="CARD_DATA_LEAK",
                severity="reject",
                message=(
                    "Extraction çıktısında kart verisi placeholder'ı "
                    f"('{_CARD_PLACEHOLDER_MARKER}') tespit edildi — kart verisi asla "
                    "restore edilmemeli ve akışa sızmamalı."
                ),
            )
    return None


def _check_unmasked_pii(extraction: ExtractionJSON) -> ValidatorFinding | None:
    texts = _collect_scannable_texts(extraction, exclude_tax_id=True)
    combined = "\n".join(texts)

    mask_result = privacy.mask(combined)
    privacy_report = privacy.analyze(combined)

    has_standard_pii = bool(mask_result.mapping)
    has_pan = "PAN" in privacy_report.detected_types

    if has_standard_pii or has_pan:
        detected_labels: list[str] = []
        if has_standard_pii:
            detected_labels.extend(sorted({token.split("_")[1] for token in mask_result.mapping}))
        if has_pan:
            detected_labels.append("PAN")
        return ValidatorFinding(
            code="UNMASKED_PII",
            severity="review",
            message=(
                "Extraction çıktısında maskelenmemiş hassas veri tespit edildi: "
                f"{', '.join(detected_labels)}."
            ),
        )
    return None


def _check_low_confidence(
    extraction: ExtractionJSON, *, confidence_threshold: float
) -> ValidatorFinding | None:
    low_confidence_rules = [
        rule.milestone for rule in extraction.payment_rules if rule.confidence < confidence_threshold
    ]
    if low_confidence_rules:
        return ValidatorFinding(
            code="LOW_CONFIDENCE",
            severity="review",
            message=(
                f"Şu kuralların güven skoru eşiğin ({confidence_threshold}) altında: "
                f"{', '.join(low_confidence_rules)}."
            ),
        )
    return None


def _check_empty_source_quote(extraction: ExtractionJSON) -> ValidatorFinding | None:
    empty_quote_rules = [
        rule.milestone for rule in extraction.payment_rules if not rule.source_quote.strip()
    ]
    if empty_quote_rules:
        return ValidatorFinding(
            code="EMPTY_SOURCE_QUOTE",
            severity="review",
            message=(
                "Şu kuralların sözleşme metninden alıntısı (source_quote) boş: "
                f"{', '.join(empty_quote_rules)}."
            ),
        )
    return None


def _check_llm_manual_review(extraction: ExtractionJSON) -> ValidatorFinding | None:
    if extraction.needs_manual_review:
        return ValidatorFinding(
            code="LLM_MANUAL_REVIEW",
            severity="review",
            message="LLM, extraction çıktısını kendisi manuel inceleme gerektirir olarak işaretledi.",
        )
    return None


def _check_non_positive_amount(extraction: ExtractionJSON) -> ValidatorFinding | None:
    if extraction.commercial_terms.total_amount <= 0:
        return ValidatorFinding(
            code="NON_POSITIVE_AMOUNT",
            severity="review",
            message=(
                "Sözleşme toplam tutarı sıfır veya negatif: "
                f"{extraction.commercial_terms.total_amount}."
            ),
        )
    return None


def _check_risk_flags(extraction: ExtractionJSON) -> ValidatorFinding | None:
    flagged = [
        flag
        for flag in extraction.risk_flags
        if any(marker in flag for marker in _SECURITY_RISK_MARKERS)
    ]
    if flagged:
        return ValidatorFinding(
            code="RISK_FLAG",
            severity="review",
            message=f"Güvenlik risk işareti(leri) tespit edildi: {', '.join(flagged)}.",
        )
    return None


def validate(extraction: ExtractionJSON, *, confidence_threshold: float = 0.7) -> ValidatorReport:
    """Extraction çıktısını deterministik kurallarla denetler.

    Saf fonksiyon — DB/network/dosya erişimi yoktur. Tüm kontroller çalıştırılır
    ve bulgular biriktirilir; nihai status REJECT > NEEDS_REVIEW > PASS
    önceliğiyle indirgenir (§6.2 "UI her zaman gerekçeyi gösterir").
    """
    findings: list[ValidatorFinding] = []

    checks = (
        _check_percentage_sum(extraction),
        _check_no_rules(extraction),
        _check_card_data_leak(extraction),
        _check_unmasked_pii(extraction),
        _check_low_confidence(extraction, confidence_threshold=confidence_threshold),
        _check_empty_source_quote(extraction),
        _check_llm_manual_review(extraction),
        _check_non_positive_amount(extraction),
        _check_risk_flags(extraction),
    )
    findings = [finding for finding in checks if finding is not None]

    if not findings:
        return ValidatorReport(status="PASS", findings=[])

    highest_severity = max(findings, key=lambda f: _SEVERITY_PRIORITY[f.severity]).severity
    status = _STATUS_BY_SEVERITY[highest_severity]
    return ValidatorReport(status=status, findings=findings)
