"""Decision engine — teslimat kanıtlarından ödeme aksiyonu üretir (§3.4, §6.5).

Saf fonksiyon: I/O yok (DB/network/dosya erişimi yasak). Girdi olarak yalnızca
extraction JSON'ı ve teslimat kanıtlarını alır, çıktı olarak deterministik bir
karar döndürür. LLM bu modülün hiçbir yerinde çağrılmaz.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from backend.app.schemas.extraction import ExtractionJSON, RequiredEvidence

# E-irsaliye ↔ video sayım ayrışması için eşik: sözleşme miktarının %10'u.
_CONFLICT_THRESHOLD = 0.10


@dataclass(frozen=True)
class DeliveryEvidence:
    """Bir işlem için toplanmış teslimat kanıtları."""

    e_irsaliye: dict | None  # simülasyon payload'ı, ör. {"delivered_quantity": float, ...}
    # VideoAnalyzer çıktısı (§3.4): {"counts": {sınıf: adet}, "unit_count": int,
    # "damage_signals": [{"type", "confidence", "matched_box"}], "confidence": float}.
    # Karar yalnızca `unit_count`u okur — sınıf→birim ayrımı adapter'da yapılır.
    video: dict | None


@dataclass(frozen=True)
class DecisionResult:
    """decide()'ın ürettiği karar."""

    action: Literal["capture", "partial_capture", "hold", "dispute"]
    capture_ratio: float  # 0.0-1.0; capture=1.0, hold/dispute=0.0
    rationale: str  # Türkçe gerekçe (UI/evidence için)


def _required_evidence_union(extraction: ExtractionJSON) -> set[RequiredEvidence]:
    union: set[RequiredEvidence] = set()
    for rule in extraction.payment_rules:
        union.update(rule.required_evidence)
    return union


def _damage_types(damage_signals: list) -> str:
    """Hasar sinyallerini insan-okur gerekçe metnine indirger (dict veya düz string)."""
    types = [
        s.get("type", "bilinmeyen") if isinstance(s, dict) else str(s) for s in damage_signals
    ]
    return ", ".join(sorted(set(types)))


def _missing_evidence(required: set[RequiredEvidence], evidence: DeliveryEvidence) -> list[RequiredEvidence]:
    missing: list[RequiredEvidence] = []
    for kind in required:
        if kind == RequiredEvidence.contract:
            continue  # sözleşmenin kendisi her zaman mevcut kabul edilir
        if kind == RequiredEvidence.e_irsaliye and evidence.e_irsaliye is None:
            missing.append(kind)
        if kind == RequiredEvidence.video and evidence.video is None:
            missing.append(kind)
    return missing


def decide(extraction: ExtractionJSON, evidence: DeliveryEvidence) -> DecisionResult:
    """Sözleşme kurallarına ve toplanan kanıtlara göre ödeme aksiyonuna karar verir.

    Karar sırası pinlidir (ilk eşleşen kazanır):
    1. Gerekli kanıt eksikse -> hold.
    2. E-irsaliye/video çelişkisi (sayım >%10 ayrışıyor veya hasar sinyali var) -> dispute.
    3. Teslim edilen miktar sözleşme miktarından azsa -> partial_capture.
    4. Aksi halde -> capture.
    """
    contract_qty = sum(g.quantity for g in extraction.commercial_terms.goods)

    if contract_qty == 0:
        return DecisionResult(
            action="hold",
            capture_ratio=0.0,
            rationale="Sözleşme miktarı sıfır — karar hesaplanamıyor, manuel inceleme gerekli.",
        )

    required = _required_evidence_union(extraction)
    missing = _missing_evidence(required, evidence)
    if missing:
        names = ", ".join(sorted(kind.value for kind in missing))
        return DecisionResult(
            action="hold",
            capture_ratio=0.0,
            rationale=f"Gerekli kanıt eksik: {names}. Ödeme kararı için bekleniyor.",
        )

    if evidence.e_irsaliye is not None and evidence.video is not None:
        e_irsaliye_qty = float(evidence.e_irsaliye.get("delivered_quantity", 0.0))
        video_unit_count = float(evidence.video.get("unit_count", 0.0))
        damage_signals = evidence.video.get("damage_signals") or []
        divergence_ratio = abs(e_irsaliye_qty - video_unit_count) / contract_qty

        if divergence_ratio > _CONFLICT_THRESHOLD:
            return DecisionResult(
                action="dispute",
                capture_ratio=0.0,
                rationale=(
                    f"E-irsaliye ({e_irsaliye_qty}) ve video sayımı ({video_unit_count}) "
                    f"sözleşme miktarının %{_CONFLICT_THRESHOLD * 100:.0f}'undan fazla ayrışıyor — "
                    "çelişki, insan incelemesi gerekli."
                ),
            )
        if damage_signals:
            return DecisionResult(
                action="dispute",
                capture_ratio=0.0,
                rationale=f"Video kanıtında hasar sinyali tespit edildi: {_damage_types(damage_signals)}.",
            )

    if evidence.e_irsaliye is not None:
        delivered = float(evidence.e_irsaliye.get("delivered_quantity", 0.0))
    else:
        delivered = float(evidence.video.get("unit_count", 0.0)) if evidence.video is not None else 0.0

    if delivered < contract_qty:
        ratio = max(0.0, min(1.0, delivered / contract_qty))
        return DecisionResult(
            action="partial_capture",
            capture_ratio=ratio,
            rationale=(
                f"Kısmi teslimat: {delivered}/{contract_qty} birim teslim edildi "
                f"(oran: %{ratio * 100:.1f})."
            ),
        )

    return DecisionResult(
        action="capture",
        capture_ratio=1.0,
        rationale="Teslimat sözleşme miktarını tam karşılıyor, çelişki veya hasar sinyali yok.",
    )
