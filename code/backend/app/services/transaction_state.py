"""Legacy transaction-state canonical projeksiyon kontratı (v2 §2.8).

Saf, DB-bağımsız: router, repository, `sqlite3` veya payment provider import
ETMEZ. `lifecycle_version=account_v2` geçiş motoru burada YOKTUR — yeni
`account_v2` transaction'lar kendi state machine'ini kullanır (Plan 03+); bu
modül yalnız `legacy_v1` satırlarının bugünkü state'ini v2'nin canonical
görünümüne çevirir. Migration `007` (`lifecycle_version` kolonu) Plan 03'e
aittir; bu modül hiçbir tabloya/kolona dokunmaz.

Kontrat (v2 §2.8 tablosu, birebir):

| Legacy state | Canonical görünüm |
|---|---|
| uploaded | processing |
| extracting | processing |
| awaiting_review | preparation / blocked_review |
| awaiting_approval | preparation / ready_for_ratification |
| rejected | rejected |
| active | active |
| evidence_pending | active / blocked_evidence |
| decided + fully released | settled |
| decided + partially released | active / partially_settled |

İki dallanan satırda ("/" işaretli) hangi taraf seçileceği tek bir legacy
status'ten çıkarılamaz; bu yüzden `LegacyProjectionInput`, yalnızca ilgili
status için anlamlı olan bir discriminator alanı taşır. Eksik/gereksiz
discriminator `LegacyProjectionError` ile fail-closed reddedilir.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LifecycleVersion(str, Enum):
    LEGACY_V1 = "legacy_v1"
    ACCOUNT_V2 = "account_v2"


class LegacyStatus(str, Enum):
    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    AWAITING_REVIEW = "awaiting_review"
    AWAITING_APPROVAL = "awaiting_approval"
    REJECTED = "rejected"
    ACTIVE = "active"
    EVIDENCE_PENDING = "evidence_pending"
    DECIDED = "decided"


class ReleaseCompleteness(str, Enum):
    """Yalnız `DECIDED` durumunda anlamlıdır."""

    FULLY_RELEASED = "fully_released"
    PARTIALLY_RELEASED = "partially_released"


class CanonicalState(str, Enum):
    PROCESSING = "processing"
    PREPARATION = "preparation"
    BLOCKED_REVIEW = "blocked_review"
    READY_FOR_RATIFICATION = "ready_for_ratification"
    REJECTED = "rejected"
    ACTIVE = "active"
    BLOCKED_EVIDENCE = "blocked_evidence"
    SETTLED = "settled"
    PARTIALLY_SETTLED = "partially_settled"


class LegacyProjectionError(ValueError):
    """Bilinmeyen `lifecycle_version` veya eksik/tutarsız discriminator için."""


@dataclass(frozen=True, slots=True)
class LegacyProjectionInput:
    """`legacy_v1` bir satırın canonical projeksiyonu için minimum sinyal.

    Yalnız ilgili `legacy_status` için gereken discriminator dolu olmalıdır;
    ilgisiz alanlar `None` kalabilir (doldurulmuşsa yok sayılır).
    """

    legacy_status: LegacyStatus
    review_blocking: bool | None = None
    ratification_ready: bool | None = None
    evidence_blocking: bool | None = None
    release_completeness: ReleaseCompleteness | None = None
    more_releases_expected: bool | None = None


def validate_lifecycle_version(value: str) -> LifecycleVersion:
    """`lifecycle_version` alanının izinli iki değerden biri olduğunu doğrular."""
    try:
        return LifecycleVersion(value)
    except ValueError as exc:
        raise LegacyProjectionError(f"Bilinmeyen lifecycle_version: {value!r}") from exc


_STATIC_PROJECTIONS: dict[LegacyStatus, CanonicalState] = {
    LegacyStatus.UPLOADED: CanonicalState.PROCESSING,
    LegacyStatus.EXTRACTING: CanonicalState.PROCESSING,
    LegacyStatus.REJECTED: CanonicalState.REJECTED,
    LegacyStatus.ACTIVE: CanonicalState.ACTIVE,
}


def project_legacy_state(projection_input: LegacyProjectionInput) -> CanonicalState:
    """`legacy_v1` satırını v2 §2.8 canonical görünümüne çevirir (saf fonksiyon)."""
    status = projection_input.legacy_status

    static = _STATIC_PROJECTIONS.get(status)
    if static is not None:
        return static

    if status is LegacyStatus.AWAITING_REVIEW:
        if projection_input.review_blocking is None:
            raise LegacyProjectionError("awaiting_review için review_blocking zorunlu.")
        return (
            CanonicalState.BLOCKED_REVIEW
            if projection_input.review_blocking
            else CanonicalState.PREPARATION
        )

    if status is LegacyStatus.AWAITING_APPROVAL:
        if projection_input.ratification_ready is None:
            raise LegacyProjectionError("awaiting_approval için ratification_ready zorunlu.")
        return (
            CanonicalState.READY_FOR_RATIFICATION
            if projection_input.ratification_ready
            else CanonicalState.PREPARATION
        )

    if status is LegacyStatus.EVIDENCE_PENDING:
        if projection_input.evidence_blocking is None:
            raise LegacyProjectionError("evidence_pending için evidence_blocking zorunlu.")
        return (
            CanonicalState.BLOCKED_EVIDENCE
            if projection_input.evidence_blocking
            else CanonicalState.ACTIVE
        )

    if status is LegacyStatus.DECIDED:
        if projection_input.release_completeness is None:
            raise LegacyProjectionError("decided için release_completeness zorunlu.")
        if projection_input.release_completeness is ReleaseCompleteness.FULLY_RELEASED:
            return CanonicalState.SETTLED
        if projection_input.more_releases_expected is None:
            raise LegacyProjectionError(
                "decided + partially_released için more_releases_expected zorunlu."
            )
        return (
            CanonicalState.ACTIVE
            if projection_input.more_releases_expected
            else CanonicalState.PARTIALLY_SETTLED
        )

    raise LegacyProjectionError(f"Desteklenmeyen legacy_status: {status!r}")
