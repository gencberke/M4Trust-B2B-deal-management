"""Takip policy persistence'ı ve deterministik fiziksel teslimat önerisi.

Buradaki recommendation yalnızca yöneticinin kararına yardımcı olur: tracking
modunu değiştirmez, ödeme veya LLM akışı için karar üretmez.
"""

from __future__ import annotations

import json
import sqlite3
import unicodedata
from datetime import datetime, timezone

from backend.app.schemas.extraction import ExtractionJSON, RequiredEvidence
from backend.app.schemas.tracking import (
    PhysicalDeliveryRecommendation,
    PhysicalDeliveryRecommendationResult,
    PolicyConflict,
    PolicyConflictCode,
    RecommendationReasonCode,
    TrackingMode,
    TrackingPolicySnapshot,
    TrackingPolicyStatus,
)

_PHYSICAL_UNITS = {
    "adet",
    "koli",
    "palet",
    "kg",
    "kilogram",
    "ton",
    "litre",
    "metre",
    "m",
    "m2",
    "m3",
    "parca",
    "set",
    "takim",
}
_PHYSICAL_GOODS_TERMS = {
    "cihaz",
    "ekipman",
    "hammadde",
    "koli",
    "makine",
    "malzeme",
    "mobilya",
    "paket",
    "palet",
    "parca",
    "pompa",
    "urun",
}
_SERVICE_TERMS = {
    "bakim",
    "consulting",
    "danismanlik",
    "development",
    "destek",
    "hizmet",
    "kurulum",
    "license",
    "lisans",
    "software",
    "tasarim",
    "yazilim",
}
_DELIVERY_TERMS = {
    "depo",
    "irsaliye",
    "koli",
    "palet",
    "sevk",
    "sevkiyat",
    "teslim",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalized_words(value: str) -> set[str]:
    """Türkçe karakterleri de kararlı ele alan, içeriği döndürmeyen tokenizer."""
    normalized = unicodedata.normalize("NFKD", value.casefold().replace("ı", "i"))
    ascii_text = "".join(character for character in normalized if not unicodedata.combining(character))
    return set("".join(character if character.isalnum() else " " for character in ascii_text).split())


def _append_reason(
    reasons: list[RecommendationReasonCode], reason: RecommendationReasonCode
) -> None:
    if reason not in reasons:
        reasons.append(reason)


def recommend_physical_delivery(extraction: ExtractionJSON) -> PhysicalDeliveryRecommendationResult:
    """Extraction'dan bağlayıcı olmayan, güvenli reason-code önerisi üretir.

    ``video`` tek başına fiziksel teslimat sinyali değildir. Metinsel sinyaller
    yalnız sınıflandırma için okunur; sonuçta asla kaynak metin taşınmaz.
    """
    positive_reasons: list[RecommendationReasonCode] = []
    service_signal = False

    for goods in extraction.commercial_terms.goods:
        if goods.quantity <= 0:
            continue

        unit_words = _normalized_words(goods.unit)
        goods_words = _normalized_words(goods.name)
        if unit_words & _PHYSICAL_UNITS:
            _append_reason(positive_reasons, RecommendationReasonCode.PHYSICAL_UNIT)
        if goods_words & _PHYSICAL_GOODS_TERMS:
            _append_reason(positive_reasons, RecommendationReasonCode.PHYSICAL_GOODS)
        if (unit_words | goods_words) & _SERVICE_TERMS:
            service_signal = True

    for rule in extraction.payment_rules:
        if RequiredEvidence.e_irsaliye in rule.required_evidence:
            _append_reason(positive_reasons, RecommendationReasonCode.CONTRACTUAL_E_IRSALIYE)

        delivery_words = _normalized_words(f"{rule.milestone} {rule.source_quote}")
        if delivery_words & _DELIVERY_TERMS:
            _append_reason(positive_reasons, RecommendationReasonCode.DELIVERY_TERMS)

    if positive_reasons and service_signal:
        return PhysicalDeliveryRecommendationResult(
            recommendation=PhysicalDeliveryRecommendation.uncertain,
            reason_codes=[
                *positive_reasons,
                RecommendationReasonCode.SERVICE_ONLY,
                RecommendationReasonCode.CONFLICTING_SIGNALS,
            ],
        )
    if positive_reasons:
        return PhysicalDeliveryRecommendationResult(
            recommendation=PhysicalDeliveryRecommendation.yes,
            reason_codes=positive_reasons,
        )
    if service_signal:
        return PhysicalDeliveryRecommendationResult(
            recommendation=PhysicalDeliveryRecommendation.no,
            reason_codes=[RecommendationReasonCode.SERVICE_ONLY],
        )
    return PhysicalDeliveryRecommendationResult(
        recommendation=PhysicalDeliveryRecommendation.uncertain,
        reason_codes=[RecommendationReasonCode.INSUFFICIENT_SIGNAL],
    )


def create_draft_policy(conn: sqlite3.Connection, transaction_id: str) -> TrackingPolicySnapshot:
    """Yeni transaction için idempotent draft/off policy kurar ve döndürür."""
    conn.execute(
        "INSERT OR IGNORE INTO tracking_policies "
        "(transaction_id, recommendation, recommendation_reason_codes, "
        "manager_physical_delivery_confirmed, tracking_mode, video_role, status, "
        "configured_at, locked_at) "
        "VALUES (?, NULL, '[]', NULL, 'off', 'advisory', 'draft', NULL, NULL)",
        (transaction_id,),
    )
    policy = load_tracking_policy(conn, transaction_id)
    if policy is None:  # pragma: no cover - SQLite insert sonrası veri tutarlılık guard'ı
        raise RuntimeError("Tracking policy oluşturulamadı.")
    return policy


def load_tracking_policy(
    conn: sqlite3.Connection, transaction_id: str
) -> TrackingPolicySnapshot | None:
    """Transaction'ın tek güncel policy snapshot'ını yükler."""
    row = conn.execute(
        "SELECT transaction_id, recommendation, recommendation_reason_codes, "
        "manager_physical_delivery_confirmed, tracking_mode, video_role, status, "
        "configured_at, locked_at FROM tracking_policies WHERE transaction_id = ?",
        (transaction_id,),
    ).fetchone()
    if row is None:
        return None

    reason_codes = json.loads(row["recommendation_reason_codes"] or "[]")
    return TrackingPolicySnapshot.model_validate(
        {
            "transaction_id": row["transaction_id"],
            "recommendation": row["recommendation"],
            "recommendation_reason_codes": reason_codes,
            "manager_physical_delivery_confirmed": (
                None
                if row["manager_physical_delivery_confirmed"] is None
                else bool(row["manager_physical_delivery_confirmed"])
            ),
            "tracking_mode": row["tracking_mode"],
            "video_role": row["video_role"],
            "status": row["status"],
            "configured_at": row["configured_at"],
            "locked_at": row["locked_at"],
        }
    )


def update_system_recommendation(
    conn: sqlite3.Connection,
    transaction_id: str,
    result: PhysicalDeliveryRecommendationResult,
) -> TrackingPolicySnapshot | None:
    """PASS extraction'ın önerisini policy'ye yazar; manager seçimini değiştirmez."""
    cursor = conn.execute(
        "UPDATE tracking_policies SET recommendation = ?, recommendation_reason_codes = ? "
        "WHERE transaction_id = ?",
        (
            result.recommendation.value,
            json.dumps([reason.value for reason in result.reason_codes]),
            transaction_id,
        ),
    )
    if cursor.rowcount != 1:
        return None
    return load_tracking_policy(conn, transaction_id)


def contractual_required_evidence(extraction: ExtractionJSON) -> set[RequiredEvidence]:
    """Tüm payment rule'ların sözleşmesel kanıt birleşimini döndürür."""
    required: set[RequiredEvidence] = set()
    for rule in extraction.payment_rules:
        required.update(rule.required_evidence)
    return required


def validate_manager_policy(
    extraction: ExtractionJSON,
    *,
    physical_delivery_confirmed: bool | None,
    tracking_mode: TrackingMode,
) -> PolicyConflict | None:
    """Manager seçiminin sözleşmeyle çelişip çelişmediğini saf biçimde denetler."""
    if physical_delivery_confirmed is None:
        return PolicyConflict(
            code=PolicyConflictCode.POLICY_INVALID,
            message="Takip politikası kilitlenmeden önce fiziksel teslimat tercihi seçilmelidir.",
            conflicts=["PHYSICAL_DELIVERY_CONFIRMATION_REQUIRED"],
        )

    if not physical_delivery_confirmed and tracking_mode is not TrackingMode.off:
        return PolicyConflict(
            code=PolicyConflictCode.POLICY_INVALID,
            message="Fiziksel teslimat yoksa takip modu yalnızca 'off' olabilir.",
            conflicts=["PHYSICAL_DELIVERY_FALSE_REQUIRES_OFF"],
        )

    required = contractual_required_evidence(extraction)
    requires_e_irsaliye = RequiredEvidence.e_irsaliye in required
    requires_video = RequiredEvidence.video in required

    # Sözleşmesel teslimat kanıtı fiziksel teslimatın kapatılmasıyla sessizce
    # devre dışı bırakılamaz. Bu fazda her iki evidence türü birlikte olsa da
    # policy `off` kilitlenemez.
    if not physical_delivery_confirmed and tracking_mode is TrackingMode.off:
        conflicts: list[str] = []
        if requires_e_irsaliye:
            conflicts.append("CONTRACTUAL_E_IRSALIYE_REQUIRES_PHYSICAL_DELIVERY")
        if requires_video:
            conflicts.append("CONTRACTUAL_VIDEO_REQUIRES_PHYSICAL_DELIVERY")
        if conflicts:
            return PolicyConflict(
                code=PolicyConflictCode.POLICY_CONTRACT_CONFLICT,
                message="Sözleşmesel teslimat kanıtı varken fiziksel teslimat kapatılamaz.",
                conflicts=conflicts,
            )

    # Sözleşme videoyu zorunlu kılıyorsa takip kapatılamaz: `off` modunda
    # e-irsaliye kanalı da kapalı olurdu ve video tek başına miktar üretemediği
    # için işlem hiçbir zaman karara bağlanamazdı. Yönetici en az `document_only`
    # seçerek e-irsaliyeyi birincil kanıt yapmalıdır.
    if requires_video and tracking_mode is TrackingMode.off:
        return PolicyConflict(
            code=PolicyConflictCode.POLICY_CONTRACT_CONFLICT,
            message=(
                "Sözleşme video kanıtı gerektiriyor; takip kapatılamaz. "
                "En az 'document_only' seçilmelidir."
            ),
            conflicts=["CONTRACTUAL_VIDEO_REQUIRES_TRACKING"],
        )
    return None


def update_manager_policy(
    conn: sqlite3.Connection,
    transaction_id: str,
    extraction: ExtractionJSON,
    *,
    physical_delivery_confirmed: bool,
    tracking_mode: TrackingMode,
) -> tuple[TrackingPolicySnapshot, bool, PolicyConflict | None]:
    """Taslak policy'yi idempotent biçimde günceller; event üretmez."""
    policy = load_tracking_policy(conn, transaction_id)
    if policy is None:  # pragma: no cover - migration/veri bütünlüğü guard'ı
        raise RuntimeError("Tracking policy bulunamadı.")
    if policy.status is TrackingPolicyStatus.locked:
        return (
            policy,
            False,
            PolicyConflict(
                code=PolicyConflictCode.POLICY_LOCKED,
                message="Kilitli takip politikası değiştirilemez.",
                conflicts=["TRACKING_POLICY_LOCKED"],
            ),
        )

    conflict = validate_manager_policy(
        extraction,
        physical_delivery_confirmed=physical_delivery_confirmed,
        tracking_mode=tracking_mode,
    )
    if conflict is not None:
        return policy, False, conflict

    if (
        policy.manager_physical_delivery_confirmed == physical_delivery_confirmed
        and policy.tracking_mode is tracking_mode
    ):
        return policy, False, None

    conn.execute(
        "UPDATE tracking_policies SET manager_physical_delivery_confirmed = ?, "
        "tracking_mode = ?, configured_at = ? WHERE transaction_id = ?",
        (int(physical_delivery_confirmed), tracking_mode.value, _utc_now_iso(), transaction_id),
    )
    updated = load_tracking_policy(conn, transaction_id)
    if updated is None:  # pragma: no cover - SQLite update sonrası guard
        raise RuntimeError("Tracking policy güncellenemedi.")
    return updated, True, None


def lock_manager_policy(
    conn: sqlite3.Connection,
    transaction_id: str,
    extraction: ExtractionJSON,
) -> tuple[TrackingPolicySnapshot, bool, PolicyConflict | None]:
    """Geçerli taslak policy'yi kilitler; tekrar çağrıda zaman damgasını korur."""
    policy = load_tracking_policy(conn, transaction_id)
    if policy is None:  # pragma: no cover - migration/veri bütünlüğü guard'ı
        raise RuntimeError("Tracking policy bulunamadı.")
    if policy.status is TrackingPolicyStatus.locked:
        return policy, False, None

    conflict = validate_manager_policy(
        extraction,
        physical_delivery_confirmed=policy.manager_physical_delivery_confirmed,
        tracking_mode=policy.tracking_mode,
    )
    if conflict is not None:
        return policy, False, conflict

    conn.execute(
        "UPDATE tracking_policies SET status = 'locked', locked_at = ? WHERE transaction_id = ?",
        (_utc_now_iso(), transaction_id),
    )
    locked = load_tracking_policy(conn, transaction_id)
    if locked is None:  # pragma: no cover - SQLite update sonrası guard
        raise RuntimeError("Tracking policy kilitlenemedi.")
    return locked, True, None


def e_irsaliye_tracking_enabled(
    policy: TrackingPolicySnapshot | None,
    contractual_requirements: set[RequiredEvidence],
) -> bool:
    """Sözleşme e-irsaliye istiyorsa veya yönetici belge takibini açtıysa etkindir."""
    if RequiredEvidence.e_irsaliye in contractual_requirements:
        return True
    if policy is None:
        return False
    return policy.tracking_mode in {TrackingMode.document_only, TrackingMode.document_and_video}


def video_tracking_enabled(
    policy: TrackingPolicySnapshot | None,
    contractual_requirements: set[RequiredEvidence],
) -> bool:
    """Sözleşme videoyu zorunlu kılıyorsa veya yönetici ikincil videoyu açtıysa etkindir."""
    if RequiredEvidence.video in contractual_requirements:
        return True
    if policy is None:
        return False
    return policy.tracking_mode is TrackingMode.document_and_video


def tracking_summary(
    policy: TrackingPolicySnapshot | None,
    contractual_requirements: set[RequiredEvidence],
) -> dict | None:
    """Taraf görünümü için token ve ham alıntı içermeyen takip özeti."""
    if policy is None:
        return None

    return {
        "physical_delivery": policy.manager_physical_delivery_confirmed,
        "tracking_mode": policy.tracking_mode.value,
        "e_irsaliye_tracking_enabled": e_irsaliye_tracking_enabled(
            policy, contractual_requirements
        ),
        "video_tracking_enabled": video_tracking_enabled(policy, contractual_requirements),
        "video_role": policy.video_role.value,
        "status": policy.status.value,
        "contractual_requirements": sorted(kind.value for kind in contractual_requirements),
    }
