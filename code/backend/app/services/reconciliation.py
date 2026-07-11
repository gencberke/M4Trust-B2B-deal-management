"""Party reconciliation (Plan 04 / Wave A / Faz 4B).

İki katman:

* `compare_party_snapshots` — saf fonksiyon (DB/HTTP yok), extracted vs
  confirmed taraf görünümünü normalize edip diff/reason-code üretir.
* `open_party_mismatch_cases` — DB orkestrasyonu, diff sonucundan
  `services/review.py::open_case` çağırarak blocking case'ler açar.

Kurallar: `extracted`/`declared`/`confirmed` sessizce overwrite edilmez (bu
modül yalnız okur); mismatch açıklaması ham değer taşımaz, yalnız alan adı/
reason code; bir reason code için bir aktif blocking case (dedup, migration
010'daki partial unique index + `review.open_case` idempotency'si); no-mismatch
durumu eski case'i sessizce resolve etmez (bu modül hiçbir zaman `resolve_case`
çağırmaz — çözüm yalnız yetkili reviewer action'ıyla olur).
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass

from backend.app.schemas.participants import PartyProfileSnapshot
from backend.app.schemas.reviews import ReviewCase, ReviewPhase, ReviewSeverity, ReviewSourceType
from backend.app.services import review as review_service
from backend.app.services.access_control import ActorContext

_WHITESPACE_RE = re.compile(r"\s+")
_NAME_PUNCTUATION_RE = re.compile(r"[.,'’\-:]")
_NON_DIGIT_RE = re.compile(r"\D")


def _normalize_name_or_address(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).strip()
    # Noktalama BOŞLUKLA değiştirilir (silinmez): "No:5" -> "No 5", "Cad." ->
    # "Cad " -- aksi halde bitişik token'lar farklı iki yazımı yanlışlıkla
    # ayrı sözcük sayardı ("No:5" vs "No 5" birleşip "No5" olur, boşluklu
    # yazımla asla eşleşmezdi).
    text = _NAME_PUNCTUATION_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text.casefold()


def _normalize_digits(value: str) -> str:
    return _NON_DIGIT_RE.sub("", value)


def _normalize_email(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


_FIELD_REASON_CODES: dict[str, str] = {
    "name": "PARTY_NAME_MISMATCH",
    "tax_id": "PARTY_TAX_ID_MISMATCH",
    "contact_email": "PARTY_CONTACT_EMAIL_MISMATCH",
    "contact_phone": "PARTY_CONTACT_PHONE_MISMATCH",
    "address": "PARTY_ADDRESS_MISMATCH",
}

_FIELD_NORMALIZERS = {
    "name": _normalize_name_or_address,
    "tax_id": _normalize_digits,
    "contact_email": _normalize_email,
    "contact_phone": _normalize_digits,
    "address": _normalize_name_or_address,
}

PARTY_PROFILE_MISSING = "PARTY_PROFILE_MISSING"


@dataclass(frozen=True, slots=True)
class FieldMismatch:
    field: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """`compare_party_snapshots`'ın saf çıktısı — ham değer TAŞIMAZ, yalnız alan adı/reason code."""

    role: str
    missing_profile: bool = False
    mismatches: tuple[FieldMismatch, ...] = ()

    @property
    def has_findings(self) -> bool:
        return self.missing_profile or bool(self.mismatches)


def compare_party_snapshots(
    *,
    role: str,
    extracted: PartyProfileSnapshot | None,
    declared: PartyProfileSnapshot | None,
    confirmed: PartyProfileSnapshot | None,
) -> ReconciliationResult:
    """Confirmed (kullanıcı tarafından onaylanmış) görünümü extracted (sözleşmeden
    çıkarılan) görünümle karşılaştırır. `declared` frozen imzanın parçasıdır ama
    karşılaştırmaya girmez -- confirm sonrası `declared` zaten `confirmed`'e
    donduğu için (3B kuralı: confirmed sonrası declared değişmez) ayrı bir
    karşılaştırma bilgi taşımaz; yalnızca çağıranın üç snapshot'ı birlikte
    geçirebilmesi için imzada tutulur.

    `confirmed` yoksa (henüz onaylanmamış) blocking `missing_profile` sonucu
    üretilir -- extracted ile karşılaştırma yapılamaz.
    """
    del declared  # bkz. docstring: confirm sonrası declared==confirmed, ayrı bilgi taşımaz

    if confirmed is None:
        return ReconciliationResult(role=role, missing_profile=True)

    mismatches: list[FieldMismatch] = []
    for field_name, reason_code in _FIELD_REASON_CODES.items():
        extracted_value = getattr(extracted, field_name, None) if extracted is not None else None
        confirmed_value = getattr(confirmed, field_name, None)
        if extracted_value is None or confirmed_value is None:
            continue  # yalnız iki tarafta da non-null olan alanlar karşılaştırılır
        normalize = _FIELD_NORMALIZERS[field_name]
        if normalize(extracted_value) != normalize(confirmed_value):
            mismatches.append(FieldMismatch(field=field_name, reason_code=reason_code))

    return ReconciliationResult(role=role, mismatches=tuple(mismatches))


def open_party_mismatch_cases(
    conn: sqlite3.Connection,
    *,
    transaction_id: str,
    participant_id: str,
    rule_version_id: str,
    result: ReconciliationResult,
    actor_context: ActorContext,
) -> tuple[ReviewCase, ...]:
    """`compare_party_snapshots` sonucuna göre blocking `party_mismatch` case'leri açar.

    `source_id=participant_id` -- aynı participant için aynı reason_code'da
    tekrar çağrılırsa `review.open_case`'in idempotency'si sayesinde duplicate
    case açılmaz. Bulgu yoksa (`has_findings=False`) hiçbir case açılmaz VE
    eski case'ler dokunulmadan kalır (sessiz auto-resolve yok).
    """
    if result.missing_profile:
        case = review_service.open_case(
            conn,
            transaction_id=transaction_id,
            phase=ReviewPhase.pre_ratification.value,
            source_type=ReviewSourceType.party_mismatch.value,
            source_id=participant_id,
            reason_code=PARTY_PROFILE_MISSING,
            title=f"{result.role} tarafı için onaylanmış profil eksik",
            description=(
                f"{result.role} participant'ı henüz profilini onaylamadı; "
                f"rule-set {rule_version_id} ile mutabakat kontrolü yapılamıyor."
            ),
            severity=ReviewSeverity.blocking.value,
            actor_context=actor_context,
        )
        return (case,)

    opened: list[ReviewCase] = []
    for mismatch in result.mismatches:
        case = review_service.open_case(
            conn,
            transaction_id=transaction_id,
            phase=ReviewPhase.pre_ratification.value,
            source_type=ReviewSourceType.party_mismatch.value,
            source_id=participant_id,
            reason_code=mismatch.reason_code,
            title=f"{result.role} tarafı {mismatch.field} uyuşmazlığı",
            description=(
                f"Sözleşmeden çıkarılan {mismatch.field} ile onaylanmış profil arasında "
                f"uyuşmazlık tespit edildi (rule-set {rule_version_id})."
            ),
            severity=ReviewSeverity.blocking.value,
            actor_context=actor_context,
        )
        opened.append(case)
    return tuple(opened)
