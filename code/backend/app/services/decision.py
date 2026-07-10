"""Saf, policy-aware teslimat kanıtı karar motoru.

Bu modül yalnızca extraction, çözülmüş evidence gereksinimleri ve kanıt
payload'larını okur. DB, ağ, router veya Settings bağımlılığı yoktur.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from backend.app.schemas.extraction import ExtractionJSON, RequiredEvidence
from backend.app.services.effective_requirements import EffectiveEvidenceRequirements

_DEFAULT_DIVERGENCE_THRESHOLD = 0.10


@dataclass(frozen=True)
class DeliveryEvidence:
    """Bir işlem için toplanmış teslimat kanıtları."""

    e_irsaliye: dict | None
    video: dict | None


@dataclass(frozen=True)
class DecisionFinding:
    """UI/evidence katmanının güvenle gösterebileceği yapılandırılmış bulgu."""

    code: str
    severity: Literal["info", "warning", "review"]
    message: str


@dataclass(frozen=True)
class DecisionResult:
    """Saf karar çıktısı; ``dispute`` eski tüketiciler için literal'de korunur."""

    action: Literal["capture", "partial_capture", "hold", "dispute"]
    capture_ratio: float
    rationale: str
    findings: tuple[DecisionFinding, ...] = ()
    manual_review_required: bool = False


def _finding(code: str, severity: Literal["info", "warning", "review"], message: str) -> DecisionFinding:
    return DecisionFinding(code=code, severity=severity, message=message)


def _result(
    action: Literal["capture", "partial_capture", "hold", "dispute"],
    capture_ratio: float,
    rationale: str,
    findings: list[DecisionFinding],
    *,
    manual_review_required: bool = False,
) -> DecisionResult:
    return DecisionResult(
        action=action,
        capture_ratio=capture_ratio,
        rationale=rationale,
        findings=tuple(findings),
        manual_review_required=manual_review_required,
    )


def _missing_effective_evidence(
    requirements: EffectiveEvidenceRequirements,
    evidence: DeliveryEvidence,
) -> list[RequiredEvidence]:
    missing: list[RequiredEvidence] = []
    required = requirements.effective_required_evidence
    if RequiredEvidence.e_irsaliye in required and evidence.e_irsaliye is None:
        missing.append(RequiredEvidence.e_irsaliye)
    if RequiredEvidence.video in required and evidence.video is None:
        missing.append(RequiredEvidence.video)
    return missing


def _as_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _damage_types(damage_signals: list[object]) -> str:
    types = [
        str(signal.get("type", "bilinmeyen")) if isinstance(signal, dict) else str(signal)
        for signal in damage_signals
    ]
    return ", ".join(sorted(set(types)))


def _advisory_video_findings(
    *,
    requirements: EffectiveEvidenceRequirements,
    evidence: DeliveryEvidence,
    e_irsaliye_quantity: float,
    contract_quantity: float,
    video_confidence_threshold: float,
    divergence_threshold: float,
) -> tuple[list[DecisionFinding], str | None]:
    """İkincil video sinyalini değerlendirir; ödeme oranı üretmez.

    Dönüşteki ikinci değer varsa karar, video kaynaklı manual-review hold'dur.
    """

    if RequiredEvidence.video not in requirements.advisory_evidence:
        return [], None
    if evidence.video is None:
        return [
            _finding(
                "VIDEO_NOT_PROVIDED",
                "info",
                "İkincil video kanıtı sağlanmadı; e-irsaliye ile karar verildi.",
            )
        ], None

    confidence = _as_float(evidence.video.get("confidence"))
    if confidence is None or confidence < video_confidence_threshold:
        return [
            _finding(
                "VIDEO_LOW_CONFIDENCE",
                "warning",
                "Video analizi güven eşiğinin altında; sayım ve hasar sinyalleri dikkate alınmadı.",
            )
        ], None

    findings: list[DecisionFinding] = []
    video_quantity = _as_float(evidence.video.get("unit_count"))
    if video_quantity is None:
        findings.append(
            _finding(
                "VIDEO_COUNT_UNAVAILABLE",
                "warning",
                "Video analizinde karşılaştırılabilir birim sayısı yok; yalnız e-irsaliye kullanıldı.",
            )
        )
    else:
        divergence_ratio = abs(e_irsaliye_quantity - video_quantity) / contract_quantity
        if divergence_ratio > divergence_threshold:
            findings.append(
                _finding(
                    "VIDEO_COUNT_DIVERGENCE",
                    "review",
                    "E-irsaliye ve yüksek güvenli video sayımı anlamlı biçimde ayrışıyor.",
                )
            )
            return findings, (
                f"E-irsaliye ({e_irsaliye_quantity}) ve video sayımı ({video_quantity}) "
                f"sözleşme miktarının %{divergence_threshold * 100:.0f}'undan fazla ayrışıyor; "
                "manuel inceleme gerekli."
            )
        findings.append(
            _finding(
                "VIDEO_COUNT_ALIGNED",
                "info",
                "Yüksek güvenli video sayımı e-irsaliye ile uyumlu.",
            )
        )

    raw_signals = evidence.video.get("damage_signals") or []
    damage_signals = raw_signals if isinstance(raw_signals, list) else []
    matched_high_confidence = [
        signal
        for signal in damage_signals
        if isinstance(signal, dict)
        and signal.get("matched_box") is True
        and (_as_float(signal.get("confidence")) or 0.0) >= video_confidence_threshold
    ]
    if matched_high_confidence:
        findings.append(
            _finding(
                "VIDEO_DAMAGE_MATCHED",
                "review",
                "Yüksek güvenli video hasar sinyali teslim edilen koliyle eşleşti.",
            )
        )
        return findings, (
            f"Video kanıtında teslim edilen koliyle eşleşen hasar sinyali tespit edildi: "
            f"{_damage_types(matched_high_confidence)}. Manuel inceleme gerekli."
        )
    if damage_signals:
        findings.append(
            _finding(
                "VIDEO_DAMAGE_UNCONFIRMED",
                "warning",
                "Video hasar sinyali teslim edilen koliyle yüksek güvenle eşleşmedi; uyarı kaydedildi.",
            )
        )
    return findings, None


def decide(
    extraction: ExtractionJSON,
    requirements: EffectiveEvidenceRequirements,
    evidence: DeliveryEvidence,
    *,
    video_confidence_threshold: float,
    divergence_threshold: float = _DEFAULT_DIVERGENCE_THRESHOLD,
) -> DecisionResult:
    """Kilitli policy'nin efektif kanıtlarına göre deterministik ödeme kararı üretir.

    Video hiçbir zaman capture miktarını belirlemez. ``dispute`` literal'i geriye
    uyumluluk için korunur, fakat bu mantık video sinyalinde yalnız ``hold`` döndürür.
    """

    external_effective = requirements.effective_required_evidence - {RequiredEvidence.contract}
    if not external_effective:
        return _result(
            "capture",
            1.0,
            "Sözleşme yalnız taraf onaylarını gerektiriyor; ödeme %100 serbest bırakılabilir.",
            [],
        )

    missing = _missing_effective_evidence(requirements, evidence)
    if missing:
        names = ", ".join(sorted(kind.value for kind in missing))
        return _result(
            "hold",
            0.0,
            f"Gerekli kanıt eksik: {names}. Ödeme kararı için bekleniyor.",
            [
                _finding(
                    "MISSING_REQUIRED_EVIDENCE",
                    "warning",
                    f"Efektif kanıt gereksinimi henüz karşılanmadı: {names}.",
                )
            ],
        )

    if evidence.e_irsaliye is None:
        return _result(
            "hold",
            0.0,
            "Video tek başına teslimat miktarını doğrulayamaz; e-irsaliye bekleniyor.",
            [
                _finding(
                    "PRIMARY_EVIDENCE_MISSING",
                    "warning",
                    "Ödeme oranı için birincil e-irsaliye miktarı gerekir.",
                )
            ],
        )

    contract_quantity = sum(goods.quantity for goods in extraction.commercial_terms.goods)
    if contract_quantity <= 0:
        return _result(
            "hold",
            0.0,
            "Sözleşme miktarı geçersiz veya sıfır; manuel inceleme gerekli.",
            [
                _finding(
                    "INVALID_CONTRACT_QUANTITY",
                    "review",
                    "Birincil miktar hesabı için sözleşme miktarı pozitif olmalıdır.",
                )
            ],
            manual_review_required=True,
        )

    delivered_quantity = _as_float(evidence.e_irsaliye.get("delivered_quantity"))
    if delivered_quantity is None or delivered_quantity <= 0:
        return _result(
            "hold",
            0.0,
            "E-irsaliye teslim miktarı sıfır veya geçersiz; ödeme beklemede.",
            [
                _finding(
                    "DELIVERED_QUANTITY_NON_POSITIVE",
                    "warning",
                    "Teslim edilen miktar pozitif olmalıdır; sıfır oranlı kısmi ödeme yapılmadı.",
                )
            ],
        )

    advisory_findings, manual_review_rationale = _advisory_video_findings(
        requirements=requirements,
        evidence=evidence,
        e_irsaliye_quantity=delivered_quantity,
        contract_quantity=contract_quantity,
        video_confidence_threshold=video_confidence_threshold,
        divergence_threshold=divergence_threshold,
    )
    if manual_review_rationale is not None:
        return _result(
            "hold",
            0.0,
            manual_review_rationale,
            advisory_findings,
            manual_review_required=True,
        )

    if delivered_quantity < contract_quantity:
        ratio = delivered_quantity / contract_quantity
        return _result(
            "partial_capture",
            ratio,
            (
                f"Kısmi teslimat: {delivered_quantity}/{contract_quantity} birim teslim edildi "
                f"(oran: %{ratio * 100:.1f})."
            ),
            advisory_findings,
        )

    return _result(
        "capture",
        1.0,
        "E-irsaliye teslimat miktarını tam karşılıyor.",
        advisory_findings,
    )
