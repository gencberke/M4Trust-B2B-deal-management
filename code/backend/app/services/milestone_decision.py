"""Faz 6B — saf milestone evaluator (Program 06, v2 §8.8-8.9, Moka §19).

Bu modül DB, HTTP, FastAPI, event veya provider çağrısı YAPMAZ. `MilestoneEvidenceSet`,
`MilestoneDecision`, `ReleaseCandidate`, `evaluate_milestone` ve
`select_units_for_legacy_ratio` imzaları donmuştur (program haritası §5, "06 Faz 6B
başında"). Girdi tipleri saf projeksiyonlardır: caller (Faz 6C entegrasyonu, Berke)
persisted milestone/funding-unit/evidence/review/dispute satırlarını buraya typed
olarak taşır -- bu modül hiçbir satırı kendisi okumaz veya sorgulamaz.

`ReleaseCandidate` yalnız eligible funding-unit ID'lerini taşır: `capture_ratio` ve
provider identifier'ı integration boundary'de YOKTUR (Moka §19.3). `decision.py`
DEĞİŞMEZ; `select_units_for_legacy_ratio` yalnız geçiş testleri için `decide()`
çıktısındaki oranı unit seçimine çevirir, account production yolunun source of
truth'u değildir (o `evaluate_milestone`'dur).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from backend.app.schemas.extraction import RequiredEvidence
from backend.app.schemas.payments import ReleaseMode

EvidenceKind = Literal["contract", "e_irsaliye", "video", "e_invoice", "other"]
MilestoneStatus = Literal["eligible", "hold"]
FindingSeverity = Literal["info", "warning", "review"]


@dataclass(frozen=True, slots=True)
class MilestoneFinding:
    """UI/evidence katmanının güvenle gösterebileceği yapılandırılmış bulgu.

    `decision.py::DecisionFinding` ile aynı (code, severity, message) şeklini
    taşır -- ayrı bir modül olarak tanımlanır çünkü `decision.py` değiştirilmez
    ve bu modül ona bağımlı olmamalıdır.
    """

    code: str
    severity: FindingSeverity
    message: str


@dataclass(frozen=True, slots=True)
class Milestone:
    """Evaluator'ın milestone girdisi -- persisted `milestones` satırının saf
    projeksiyonu (id, release_mode, required_evidence dışında hiçbir alan
    evaluator kararını etkilemez)."""

    milestone_id: str
    release_mode: ReleaseMode
    required_evidence: frozenset[RequiredEvidence] = frozenset()


@dataclass(frozen=True, slots=True)
class FundingUnitEligibility:
    """Persisted `funding_units` satırının evaluator'a özgü saf projeksiyonu.

    `quantity_threshold`: yalnız `fixed_tranches` unit'leri için kümülatif
    doğrulanmış miktar eşiği (persisted eligibility payload'ından caller
    tarafından okunur; evaluator oranı yeniden hesaplamaz). `all_or_nothing`
    unit'lerinde `None` kalır.
    `already_released`: unit daha önce approve/release edilmişse `True` --
    evaluator bu bilgiyi tekrar candidate üretmemek için kullanır.
    """

    funding_unit_id: str
    sequence: int
    quantity_threshold: int | None = None
    already_released: bool = False


@dataclass(frozen=True, slots=True)
class VideoAdvisorySummary:
    """`decision.py`'nin video sinyal okumasıyla aynı semantiği taşıyan, saf
    özet: video hiçbir zaman miktar veya oran üretmez, yalnız hold/review
    önerir."""

    provided: bool = False
    high_confidence: bool = False
    count_divergence_detected: bool = False
    damage_matched: bool = False


@dataclass(frozen=True, slots=True)
class MilestoneEvidenceSet:
    """Bir milestone değerlendirmesi için toplanmış, önceden filtrelenmiş kanıt
    girdisi.

    `verified_evidence_types`: yalnız `verification_status == verified` olan
    kanıt türleri (rejected/review_required caller tarafından zaten dışlanmış
    olmalıdır -- bu modül evidence store'u tekrar sorgulamaz).
    `cumulative_verified_quantity`: yalnız verified `e_irsaliye` kanıtından
    türetilen kümülatif teslim miktarı (video asla bu alana katkı yapmaz).
    `funding_units`: bu milestone'a ait funding unit'lerin eligibility
    projeksiyonu (sequence sırası zorunlu değildir, evaluator kendisi sıralar).
    """

    verified_evidence_types: frozenset[EvidenceKind] = frozenset()
    cumulative_verified_quantity: int | None = None
    video_advisory: VideoAdvisorySummary = field(default_factory=VideoAdvisorySummary)
    funding_units: tuple[FundingUnitEligibility, ...] = ()


@dataclass(frozen=True, slots=True)
class MilestoneReviewState:
    """`ReviewService.has_blocking_case` (transaction-wide) ve
    `disputes.has_open_dispute(conn, transaction_id, milestone_id=...)`
    (milestone-scoped çağrının repository'de zaten transaction-wide OR
    milestone-scoped dispute'u birleştirdiği) çağrılarının caller tarafından
    önceden çözülmüş sonucu. Bu modül dispute/review store'unu sorgulamaz."""

    has_blocking_review: bool = False
    has_blocking_dispute: bool = False


@dataclass(frozen=True, slots=True)
class ReleaseCandidate:
    """Eligible funding-unit ID'lerinin deterministik (sequence sıralı) listesi.

    `capture_ratio` ve provider identifier'ı KASITLI olarak burada yoktur --
    release miktarını değil, hangi bölünemez unit'in serbest bırakılabilir
    olduğunu taşır (Moka §19.3, "bir funding unit = bir pool payment")."""

    funding_unit_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MilestoneDecision:
    """Saf ve deterministik evaluator çıktısı."""

    status: MilestoneStatus
    release_candidate: ReleaseCandidate
    findings: tuple[MilestoneFinding, ...] = ()
    manual_review_required: bool = False


def _finding(code: str, severity: FindingSeverity, message: str) -> MilestoneFinding:
    return MilestoneFinding(code=code, severity=severity, message=message)


def _hold(
    findings: list[MilestoneFinding], *, manual_review_required: bool = False
) -> MilestoneDecision:
    return MilestoneDecision(
        status="hold",
        release_candidate=ReleaseCandidate(()),
        findings=tuple(findings),
        manual_review_required=manual_review_required,
    )


def _eligible(
    unit_ids: tuple[str, ...], findings: list[MilestoneFinding]
) -> MilestoneDecision:
    return MilestoneDecision(
        status="eligible",
        release_candidate=ReleaseCandidate(unit_ids),
        findings=tuple(findings),
    )


def _pending_units_by_sequence(
    funding_units: tuple[FundingUnitEligibility, ...],
) -> list[FundingUnitEligibility]:
    return sorted(
        (unit for unit in funding_units if not unit.already_released),
        key=lambda unit: unit.sequence,
    )


def _evaluate_video_advisory(
    video_advisory: VideoAdvisorySummary,
) -> tuple[list[MilestoneFinding], bool]:
    """Video sinyalini değerlendirir; hiçbir dalda miktar/oran üretmez ve asla
    otomatik dispute açmaz -- yalnız hold + manuel inceleme önerir."""

    if not video_advisory.provided:
        return [], False
    if not video_advisory.high_confidence:
        return [
            _finding(
                "VIDEO_LOW_CONFIDENCE",
                "warning",
                "Video analizi güven eşiğinin altında; sayım ve hasar sinyalleri dikkate alınmadı.",
            )
        ], False

    findings: list[MilestoneFinding] = []
    manual_review_required = False
    if video_advisory.count_divergence_detected:
        findings.append(
            _finding(
                "VIDEO_COUNT_DIVERGENCE",
                "review",
                "Yüksek güvenli video sayımı doğrulanmış teslim miktarından anlamlı biçimde ayrışıyor.",
            )
        )
        manual_review_required = True
    if video_advisory.damage_matched:
        findings.append(
            _finding(
                "VIDEO_DAMAGE_MATCHED",
                "review",
                "Yüksek güvenli video hasar sinyali teslim edilen kalemle eşleşti.",
            )
        )
        manual_review_required = True
    if not findings:
        findings.append(
            _finding(
                "VIDEO_COUNT_ALIGNED",
                "info",
                "Yüksek güvenli video sayımı doğrulanmış teslim miktarıyla uyumlu.",
            )
        )
    return findings, manual_review_required


def evaluate_milestone(
    milestone: Milestone,
    evidence_set: MilestoneEvidenceSet,
    review_state: MilestoneReviewState,
) -> MilestoneDecision:
    """Bir milestone için hangi funding unit'lerin release'e eligible olduğunu
    saf ve deterministik biçimde belirler. Aynı girdi her zaman aynı çıktıyı
    üretir (idempotent); DB/HTTP/provider çağrısı yapmaz."""

    findings: list[MilestoneFinding] = []

    if review_state.has_blocking_dispute:
        findings.append(
            _finding(
                "BLOCKING_DISPUTE_OPEN",
                "review",
                "Bu milestone kapsamında (veya transaction genelinde) açık bir dispute var; release bloklanır.",
            )
        )
        return _hold(findings)
    if review_state.has_blocking_review:
        findings.append(
            _finding(
                "BLOCKING_REVIEW_OPEN",
                "review",
                "Açık bir blocking review case var; release bloklanır.",
            )
        )
        return _hold(findings)

    video_findings, video_manual_review = _evaluate_video_advisory(evidence_set.video_advisory)
    findings.extend(video_findings)
    if video_manual_review:
        return _hold(findings, manual_review_required=True)

    effective_required = frozenset(milestone.required_evidence) - {RequiredEvidence.contract}
    missing = effective_required - evidence_set.verified_evidence_types
    if missing:
        names = ", ".join(sorted(str(kind.value if hasattr(kind, "value") else kind) for kind in missing))
        findings.append(
            _finding(
                "MISSING_REQUIRED_EVIDENCE",
                "warning",
                f"Gerekli kanıt henüz doğrulanmadı: {names}.",
            )
        )
        return _hold(findings)

    pending_units = _pending_units_by_sequence(evidence_set.funding_units)
    if not pending_units:
        findings.append(
            _finding(
                "ALL_UNITS_ALREADY_RELEASED",
                "info",
                "Bu milestone'un tüm funding unit'leri zaten release edilmiş.",
            )
        )
        return _hold(findings)

    if milestone.release_mode is ReleaseMode.ALL_OR_NOTHING:
        eligible_ids = tuple(unit.funding_unit_id for unit in pending_units)
        findings.append(
            _finding(
                "MILESTONE_ELIGIBLE",
                "info",
                "Tüm gerekli kanıt doğrulandı; milestone unit'i eligible.",
            )
        )
        return _eligible(eligible_ids, findings)

    # fixed_tranches
    cumulative = evidence_set.cumulative_verified_quantity
    if cumulative is None:
        findings.append(
            _finding(
                "MISSING_CUMULATIVE_QUANTITY",
                "warning",
                "Kümülatif doğrulanmış teslim miktarı yok; tranche eşiği değerlendirilemiyor.",
            )
        )
        return _hold(findings)

    eligible_ids = tuple(
        unit.funding_unit_id
        for unit in pending_units
        if unit.quantity_threshold is not None and cumulative >= unit.quantity_threshold
    )
    if not eligible_ids:
        findings.append(
            _finding(
                "THRESHOLD_NOT_REACHED",
                "info",
                f"Kümülatif doğrulanmış miktar ({cumulative}) hiçbir tranche eşiğini geçmiyor.",
            )
        )
        return _hold(findings)

    findings.append(
        _finding(
            "MILESTONE_ELIGIBLE",
            "info",
            f"Kümülatif doğrulanmış miktar ({cumulative}) {len(eligible_ids)} tranche eşiğini geçti.",
        )
    )
    return _eligible(eligible_ids, findings)


def select_units_for_legacy_ratio(
    funding_units: tuple[FundingUnitEligibility, ...],
    capture_ratio: float,
) -> ReleaseCandidate:
    """`decision.py::decide()`'ın legacy `capture_ratio` çıktısını funding-unit
    seçimine çeviren saf yardımcı -- YALNIZ geçiş testleri içindir.

    Ratio'yu provider'a göndermez, unit bölmez, funding unit amount'unu
    değiştirmez; ratio'yu (largest-remainder ile aynı Decimal/ROUND_HALF_UP
    disiplini kullanarak) deterministik biçimde bir unit SAYISINA çevirir ve
    sequence sırasına göre ilk o kadar pending unit'i seçer. `decision.py`
    değiştirilmez ve bu yardımcı account production yolunun source of
    truth'u DEĞİLDİR -- gerçek account yolu `evaluate_milestone` kullanır.
    """

    if isinstance(capture_ratio, bool) or not isinstance(capture_ratio, (int, float)):
        raise TypeError("capture_ratio sayısal olmalıdır.")
    if not 0.0 <= capture_ratio <= 1.0:
        raise ValueError("capture_ratio 0.0 ile 1.0 arasında olmalıdır.")

    pending_units = _pending_units_by_sequence(funding_units)
    if not pending_units or capture_ratio <= 0.0:
        return ReleaseCandidate(())

    unit_count = (Decimal(str(capture_ratio)) * len(pending_units)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    selected = pending_units[: int(unit_count)]
    return ReleaseCandidate(tuple(unit.funding_unit_id for unit in selected))
