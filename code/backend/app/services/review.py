"""Frozen `ReviewService` (v2 §8.3) — Plan 04 Wave A/B ve 4F-2 bu imzaları çağırır.

```python
open_case(conn, *, transaction_id, phase, source_type, source_id, reason_code,
          title, description, severity, actor_context) -> ReviewCase
record_action(conn, *, case_id, actor_context, action, payload=None) -> ReviewAction
resolve_case(conn, *, case_id, actor_context, resolution_code, resolution_note=None) -> ReviewCase
has_blocking_case(conn, transaction_id, *, phase=None) -> bool
```

Bu dört imza donmuştur. `services/access_control.py`'ye veya auth/identity iç
yapısına bağımlı DEĞİLDİR — yalnız donmuş `ActorContext` alanlarını okur.
Servisler kendi connection'ını açmaz, kendi commit/rollback/close yapmaz;
business mutation ve audit çağıranın transaction'ında birlikte yazılır.

Action -> status state machine (Wave A güvenlik sınırı dahil):

| action            | ön-koşul                          | sonuç status       |
|-------------------|------------------------------------|--------------------|
| comment           | case aktif olmalı                  | (değişmez)         |
| request_evidence  | case aktif olmalı                  | evidence_requested |
| escalate          | case aktif olmalı                  | escalated          |
| resolve_continue  | `severity=warning` OTOMATİK; `severity=blocking` yalnız aşağıdaki ön-koşullar sağlanırsa | resolved |
| resolve_reject    | case aktif olmalı                  | resolved           |
| cancel            | case aktif olmalı                  | cancelled          |

Faz 4F-2 — blocking case `resolve_continue` ön-koşulları (`pre_ratification`
fazı dışındaki blocking case'ler için hâlâ kayıtsız şartsız reddedilir):

* `validator` case: current rule version vardır, `PASS`+`ratifiable`dır, case'in
  açıldığı eski version artık current değildir, ve mevcut ratification package
  henüz `complete` (funding tetiklenmiş) değildir.
* `party_mismatch` case: current rule-set ile confirmed participant snapshot
  yeniden karşılaştırılır (`reconciliation.compare_party_snapshots`); case'in
  `reason_code`'una karşılık gelen mismatch artık yoktur. Snapshot sessizce
  değiştirilmez, yalnız okunur.

Ön-koşul sağlanmazsa `ReviewResolutionPreconditionError` (409
`REVIEW_RESOLUTION_PRECONDITION_FAILED`) fırlatılır. Ön-koşul sağlanıp case
resolve edildikten sonra `pre_ratification` fazında başka blocking case
kalmadıysa, donmuş `account_lifecycle.transition_account_state` helper'ıyla
account transaction `preparation`'a döner (legacy transaction state'i bu
helper zaten `account_v2` dışını reddederek korur). Review bypass eklenmez;
business mutation + audit aynı DB transaction'ındadır.
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from backend.app.repositories import reviews as reviews_repo
from backend.app.repositories import rule_sets as rule_sets_repo
from backend.app.schemas.reviews import (
    ACTIVE_REVIEW_STATUSES,
    ReviewAction,
    ReviewActionType,
    ReviewCase,
    ReviewPhase,
    ReviewSeverity,
    ReviewSourceType,
    ReviewStatus,
)
from backend.app.services import audit
from backend.app.services import privacy
from backend.app.services.access_control import ActorContext
from backend.app.services.account_lifecycle import AccountLifecycleError, transition_account_state

_ACCOUNT_STATES_RETURNABLE_TO_PREPARATION = frozenset(
    {"awaiting_review", "awaiting_approval", "awaiting_ratification", "preparation"}
)

# capability/session token'ları secrets.token_urlsafe(32) ile üretilir (~43
# karakter, [A-Za-z0-9_-]) -- 24+ karakterlik kesintisiz aynı-alfabe dizisi
# opak bir secret/token adayı sayılır ve fail-closed reddedilir.
_TOKEN_LIKE_RE = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{24,}(?![A-Za-z0-9_-])")

_ACTIVE_STATUS_VALUES = tuple(s.value for s in ACTIVE_REVIEW_STATUSES)

# action -> (yeni status, terminal-resolution mu)
_ACTION_TRANSITIONS: dict[str, tuple[str | None, bool]] = {
    "comment": (None, False),
    "request_evidence": (ReviewStatus.evidence_requested.value, False),
    "escalate": (ReviewStatus.escalated.value, False),
    "resolve_continue": (ReviewStatus.resolved.value, True),
    "resolve_reject": (ReviewStatus.resolved.value, True),
    "cancel": (ReviewStatus.cancelled.value, True),
}


class ReviewCaseNotFoundError(Exception):
    """Beklenen review case bulunamadı."""


class ReviewCaseClosedError(Exception):
    """Case artık aktif durumda değil; yeni state-changing action reddedilir."""


class ReviewActionForbiddenError(Exception):
    """`pre_ratification` fazı dışındaki blocking case `resolve_continue` ile bypass edilemez
    (bu fazlar için resolution semantiği henüz tanımlı değil — Plan 06/07)."""


class ReviewCommentRejectedError(Exception):
    """`comment`/`resolution_code` içinde PII, kart verisi veya token/secret benzeri
    bir değer tespit edildi — fail closed reddedilir (append-only + değiştirilemez
    olduğu için önce burada durdurulmalı, sonradan temizlenemez)."""


_RESOLUTION_CODE_FORMAT_RE = re.compile(r"^[A-Z0-9_]+$")


def _reject_if_sensitive_comment(value: str | None) -> None:
    if not value:
        return
    report = privacy.analyze(value)
    if report.detected_types or report.mapping:
        raise ReviewCommentRejectedError(
            "comment alanı PII veya kart verisi benzeri bir değer içeriyor."
        )
    if _TOKEN_LIKE_RE.search(value):
        raise ReviewCommentRejectedError(
            "comment alanı token/secret benzeri opak bir değer içeriyor."
        )


def _reject_if_invalid_resolution_code(value: str | None) -> None:
    """`resolution_code` serbest metin değildir -- yalnız `RATIFICATION_COMPLETE`
    gibi sabit kod formatı beklenir. Comment'teki genel 24+ karakter token
    deseni burada KULLANILMAZ: meşru uzun kodlar (ör.
    `VALIDATOR_REVISION_REVALIDATED`, 31 karakter) yanlışlıkla opak bir
    secret/token sayılırdı. Bunun yerine dar `^[A-Z0-9_]+$` format kontrolü
    kullanılır; PII/kart taraması yine de yapılır (savunma amaçlı)."""
    if not value:
        return
    report = privacy.analyze(value)
    if report.detected_types or report.mapping:
        raise ReviewCommentRejectedError(
            "resolution_code alanı PII veya kart verisi benzeri bir değer içeriyor."
        )
    if not _RESOLUTION_CODE_FORMAT_RE.fullmatch(value):
        raise ReviewCommentRejectedError(
            "resolution_code yalnız büyük harf/rakam/alt çizgi içerebilir "
            "(ör. RATIFICATION_COMPLETE)."
        )


class ReviewResolutionPreconditionError(Exception):
    """Faz 4F-2: blocking `resolve_continue` ön-koşulları (revision+revalidation veya
    mismatch'in gerçekten düzelmiş olması) sağlanmadı — 409 fail closed."""


def _row_to_case(row: sqlite3.Row) -> ReviewCase:
    return ReviewCase(
        id=row["id"],
        transaction_id=row["transaction_id"],
        phase=ReviewPhase(row["phase"]),
        source_type=ReviewSourceType(row["source_type"]),
        source_id=row["source_id"],
        reason_code=row["reason_code"],
        title=row["title"],
        description=row["description"],
        severity=ReviewSeverity(row["severity"]),
        status=ReviewStatus(row["status"]),
        assigned_to_user_id=row["assigned_to_user_id"],
        opened_by_actor_type=row["opened_by_actor_type"],
        opened_by_user_id=row["opened_by_user_id"],
        resolved_by_user_id=row["resolved_by_user_id"],
        resolution_code=row["resolution_code"],
        resolution_note=row["resolution_note"],
        created_at=row["created_at"],
        resolved_at=row["resolved_at"],
    )


def _row_to_action(row: sqlite3.Row) -> ReviewAction:
    return ReviewAction(
        id=row["id"],
        review_case_id=row["review_case_id"],
        actor_user_id=row["actor_user_id"],
        acting_entity_id=row["acting_entity_id"],
        action=ReviewActionType(row["action"]),
        payload=json.loads(row["payload_json"]) if row["payload_json"] else None,
        created_at=row["created_at"],
    )


def _validator_case_resolvable(conn: sqlite3.Connection, case: ReviewCase) -> bool:
    """Current rule version PASS+ratifiable ve case'in eski version'ından farklı mı?

    `rule_set_versions` her zaman en yeni non-superseded satırı `current` kabul
    eder (`repositories/rule_sets.py::get_latest_non_superseded`); dolayısıyla
    "current artık case'in source_id'sinden farklı" kontrolü zaten "eski version
    artık current değil veya superseded" koşulunu kapsar.
    """
    current = rule_sets_repo.get_current(conn, case.transaction_id)
    if current is None or current.rule_set_id is None:
        return False
    if current.rule_set_id == case.source_id:
        return False
    return current.status == "ratifiable" and current.validator_status == "PASS"


def _funding_not_yet_started(conn: sqlite3.Connection, transaction_id: str) -> bool:
    from backend.app.services import ratification_package

    package = ratification_package.get_current(conn, transaction_id)
    if package is None:
        return True
    return package.status.value != "complete"


def _party_mismatch_case_resolvable(conn: sqlite3.Connection, case: ReviewCase) -> bool:
    """Current rule-set'in extracted party'siyle confirmed snapshot'ı yeniden karşılaştırır.

    Snapshot'lar yalnız okunur, hiçbir şekilde değiştirilmez. `source_id`
    (`reconciliation.open_party_mismatch_cases`'te `participant_id`'dir.
    """
    from backend.app.repositories import participants as participants_repo
    from backend.app.schemas.participants import PartyProfileSnapshot
    from backend.app.services import reconciliation

    if not case.source_id:
        return False
    participant_row = participants_repo.get_participant_by_id(conn, case.source_id)
    if participant_row is None:
        return False

    current = rule_sets_repo.get_current(conn, case.transaction_id)
    if current is None or current.extraction is None:
        return False
    role = participant_row["role"]
    extracted_party = getattr(current.extraction.parties, role, None)
    if extracted_party is None:
        return False
    extracted = PartyProfileSnapshot(name=extracted_party.name, tax_id=extracted_party.tax_id)

    confirmed_json = participant_row["confirmed_snapshot_json"]
    confirmed = (
        PartyProfileSnapshot.model_validate(json.loads(confirmed_json)) if confirmed_json else None
    )
    declared_json = participant_row["declared_snapshot_json"]
    declared = (
        PartyProfileSnapshot.model_validate(json.loads(declared_json)) if declared_json else None
    )

    result = reconciliation.compare_party_snapshots(
        role=role, extracted=extracted, declared=declared, confirmed=confirmed
    )
    if case.reason_code == reconciliation.PARTY_PROFILE_MISSING:
        return not result.missing_profile
    if result.missing_profile:
        return False
    return case.reason_code not in {m.reason_code for m in result.mismatches}


def _blocking_resolve_continue_allowed(conn: sqlite3.Connection, case: ReviewCase) -> bool:
    if case.phase is not ReviewPhase.pre_ratification:
        return False
    if case.source_type is ReviewSourceType.validator:
        return _validator_case_resolvable(conn, case) and _funding_not_yet_started(
            conn, case.transaction_id
        )
    if case.source_type is ReviewSourceType.party_mismatch:
        return _party_mismatch_case_resolvable(conn, case)
    return False


def _return_account_transaction_to_preparation(
    conn: sqlite3.Connection, transaction_id: str, actor_context: ActorContext
) -> None:
    """Resolve sonrası `pre_ratification` fazında blocking case kalmadıysa `preparation`'a döner."""
    if has_blocking_case(conn, transaction_id, phase=ReviewPhase.pre_ratification.value):
        return
    try:
        transition_account_state(
            conn,
            transaction_id=transaction_id,
            expected_states=_ACCOUNT_STATES_RETURNABLE_TO_PREPARATION,
            target_state="preparation",
            actor_context=actor_context,
            reason_code="REVIEW_RESOLVED",
        )
    except AccountLifecycleError as exc:
        raise ReviewResolutionPreconditionError(str(exc)) from exc


def open_case(
    conn: sqlite3.Connection,
    *,
    transaction_id: str,
    phase: str,
    source_type: str,
    source_id: str | None,
    reason_code: str,
    title: str,
    description: str,
    severity: str,
    actor_context: ActorContext,
) -> ReviewCase:
    """Yeni bir review case açar; aynı active blocking source/reason için idempotenttir.

    Idempotency iki katmanlıdır: önce uygulama-seviyesi ön-kontrol
    (`find_active_case`, hızlı yol), ardından gerçek INSERT — DB'deki partial
    UNIQUE index (migration 010) source of truth'tur; eşzamanlı iki `open_case`
    çağrısı yarışırsa `sqlite3.IntegrityError` yakalanıp mevcut case fetch
    edilir (yalnız `severity="blocking"` için; warning case'ler için DB
    constraint'i yoktur, her çağrı yeni bir warning case açabilir).
    """
    if severity == ReviewSeverity.blocking.value:
        existing = reviews_repo.find_active_case(
            conn,
            transaction_id=transaction_id,
            phase=phase,
            source_type=source_type,
            source_id=source_id,
            reason_code=reason_code,
        )
        if existing is not None:
            return _row_to_case(existing)

    opened_by_actor_type = actor_context.actor_type
    opened_by_user_id = actor_context.user_id

    try:
        row = reviews_repo.create_case(
            conn,
            transaction_id=transaction_id,
            phase=phase,
            source_type=source_type,
            source_id=source_id,
            reason_code=reason_code,
            title=title,
            description=description,
            severity=severity,
            opened_by_actor_type=opened_by_actor_type,
            opened_by_user_id=opened_by_user_id,
        )
    except sqlite3.IntegrityError:
        existing = reviews_repo.find_active_case(
            conn,
            transaction_id=transaction_id,
            phase=phase,
            source_type=source_type,
            source_id=source_id,
            reason_code=reason_code,
        )
        if existing is None:
            raise
        return _row_to_case(existing)

    audit.record(
        conn,
        audit.AuditActor(
            actor_type="user" if opened_by_user_id else "system",
            user_id=opened_by_user_id,
            acting_entity_id=actor_context.acting_entity_id,
            request_id=actor_context.request_id,
        ),
        action="review.case_opened",
        target=f"review_case:{row['id']}",
        metadata_allowlist=frozenset({"reason_code", "severity", "phase"}),
        metadata={"reason_code": reason_code, "severity": severity, "phase": phase},
        transaction_id=transaction_id,
    )
    return _row_to_case(row)


def record_action(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_context: ActorContext,
    action: str,
    payload: dict[str, Any] | None = None,
) -> ReviewAction:
    """Her zaman bir `review_actions` satırı ekler; state-changing action'lar
    için case status'unü conditional olarak günceller (kapalı case'e yazılmaz)."""
    case_row = reviews_repo.get_case_by_id(conn, case_id)
    if case_row is None:
        raise ReviewCaseNotFoundError(f"Review case bulunamadı: {case_id}")

    if action not in _ACTION_TRANSITIONS:
        raise ValueError(f"Bilinmeyen review action: {action}")

    _reject_if_sensitive_comment((payload or {}).get("comment"))
    _reject_if_invalid_resolution_code((payload or {}).get("resolution_code"))

    new_status, is_resolution = _ACTION_TRANSITIONS[action]

    if action == "resolve_continue" and case_row["severity"] == ReviewSeverity.blocking.value:
        case = _row_to_case(case_row)
        if case.phase is not ReviewPhase.pre_ratification:
            raise ReviewActionForbiddenError(
                "Blocking case 'resolve_continue' ile bypass edilemez; bu faz için "
                "resolution semantiği henüz tanımlı değil."
            )
        if not _blocking_resolve_continue_allowed(conn, case):
            raise ReviewResolutionPreconditionError(
                "Blocking case 'resolve_continue' ön koşulları sağlanmıyor: revision + "
                "revalidation (validator case) veya mismatch'in gerçekten düzelmiş olması "
                "(party_mismatch case) gerekir."
            )

    if new_status is not None:
        if case_row["status"] not in _ACTIVE_STATUS_VALUES:
            raise ReviewCaseClosedError(
                f"Case '{case_row['status']}' durumunda; yeni state-changing action yazılamaz."
            )
        # `resolution_code` frozen `record_action` imzasında ayrı bir parametre
        # değildir -- çağıran (router) daha spesifik bir kod vermek isterse
        # `payload["resolution_code"]` ile taşır, yoksa action adı kod olur.
        resolution_code = ((payload or {}).get("resolution_code") or action) if is_resolution else None
        updated = reviews_repo.conditional_update_status(
            conn,
            case_id,
            expected_statuses=_ACTIVE_STATUS_VALUES,
            new_status=new_status,
            resolved=is_resolution,
            resolved_by_user_id=actor_context.user_id if is_resolution else None,
            resolution_code=resolution_code,
            resolution_note=(payload or {}).get("comment") if is_resolution else None,
        )
        if not updated:
            raise ReviewCaseClosedError(
                "Case eşzamanlı olarak kapatılmış; state-changing action yazılamaz."
            )

    action_row = reviews_repo.append_action(
        conn,
        review_case_id=case_id,
        actor_user_id=actor_context.user_id,
        acting_entity_id=actor_context.acting_entity_id,
        action=action,
        payload_json=json.dumps(payload) if payload else None,
    )

    audit.record(
        conn,
        audit.AuditActor(
            actor_type="user",
            user_id=actor_context.user_id,
            acting_entity_id=actor_context.acting_entity_id,
            request_id=actor_context.request_id,
        ),
        action=f"review.action.{action}",
        target=f"review_case:{case_id}",
        metadata_allowlist=frozenset(),
        transaction_id=case_row["transaction_id"],
    )

    if (
        action == "resolve_continue"
        and case_row["severity"] == ReviewSeverity.blocking.value
        and case_row["phase"] == ReviewPhase.pre_ratification.value
    ):
        _return_account_transaction_to_preparation(
            conn, case_row["transaction_id"], actor_context
        )

    return _row_to_action(action_row)


def resolve_case(
    conn: sqlite3.Connection,
    *,
    case_id: str,
    actor_context: ActorContext,
    resolution_code: str,
    resolution_note: str | None = None,
) -> ReviewCase:
    """Case'i doğrudan `resolved` durumuna alır (yalnız aktif bir durumdaysa).

    `record_action`'dan bağımsız, tek başına da çağrılabilir (örn. 4F-2'nin
    revision-sonrası otomatik çözüm akışı) -- bu yüzden bir `review_actions`
    satırı EKLEMEZ; yalnız case durumunu değiştirir + audit yazar. Router,
    kullanıcı-tetikli `resolve_reject`/`resolve_continue` için `record_action`'ı
    kullanır (action log + bu fonksiyonun yaptığı state transition'ı birlikte
    sağlamak için).
    """
    case_row = reviews_repo.get_case_by_id(conn, case_id)
    if case_row is None:
        raise ReviewCaseNotFoundError(f"Review case bulunamadı: {case_id}")
    if case_row["status"] not in _ACTIVE_STATUS_VALUES:
        raise ReviewCaseClosedError(f"Case zaten '{case_row['status']}' durumunda.")

    updated = reviews_repo.conditional_update_status(
        conn,
        case_id,
        expected_statuses=_ACTIVE_STATUS_VALUES,
        new_status=ReviewStatus.resolved.value,
        resolved=True,
        resolved_by_user_id=actor_context.user_id,
        resolution_code=resolution_code,
        resolution_note=resolution_note,
    )
    if not updated:
        raise ReviewCaseClosedError("Case eşzamanlı olarak kapatılmış.")

    audit.record(
        conn,
        audit.AuditActor(
            actor_type="user" if actor_context.user_id else "system",
            user_id=actor_context.user_id,
            acting_entity_id=actor_context.acting_entity_id,
            request_id=actor_context.request_id,
        ),
        action="review.case_resolved",
        target=f"review_case:{case_id}",
        metadata_allowlist=frozenset({"resolution_code"}),
        metadata={"resolution_code": resolution_code},
        transaction_id=case_row["transaction_id"],
    )
    return _row_to_case(reviews_repo.get_case_by_id(conn, case_id))


def has_blocking_case(
    conn: sqlite3.Connection, transaction_id: str, *, phase: str | None = None
) -> bool:
    return reviews_repo.has_blocking_case(conn, transaction_id, phase=phase)


def list_cases(conn: sqlite3.Connection, transaction_id: str) -> list[ReviewCase]:
    return [_row_to_case(row) for row in reviews_repo.list_cases_for_transaction(conn, transaction_id)]


def list_actions(conn: sqlite3.Connection, case_id: str) -> list[ReviewAction]:
    return [_row_to_action(row) for row in reviews_repo.list_actions_for_case(conn, case_id)]


def open_validator_case(
    conn: sqlite3.Connection,
    *,
    transaction_id: str,
    source_id: str,
    validator_status: str,
    finding_codes: list[str],
    actor_context: ActorContext,
) -> ReviewCase | None:
    """`NEEDS_REVIEW` için blocking `pre_ratification` case açar; `PASS` için hiçbir şey yapmaz.

    Legacy (`lifecycle_version=legacy_v1`) transaction'lar için otomatik case
    açılmaz -- çağıran (4A pipeline hook'u) bu fonksiyonu yalnız account-mode
    transaction'lar için çağırmalıdır; bu fonksiyon kendisi lifecycle_version
    sorgulamaz (transaction repository'sine bağımlı olmamak için) ve saf
    "NEEDS_REVIEW mi" kontrolü yapar. `finding_codes` deterministic/PII'siz
    olmalıdır (ham validator mesajı/exception metni asla `description`'a
    yazılmaz).
    """
    if validator_status != "NEEDS_REVIEW":
        return None

    reason_code = "VALIDATOR_NEEDS_REVIEW"
    codes = ",".join(sorted(finding_codes)) if finding_codes else "NONE"
    return open_case(
        conn,
        transaction_id=transaction_id,
        phase=ReviewPhase.pre_ratification.value,
        source_type=ReviewSourceType.validator.value,
        source_id=source_id,
        reason_code=reason_code,
        title="Kural seti manuel inceleme gerektiriyor",
        description=f"Validator NEEDS_REVIEW döndü (finding kodları: {codes}).",
        severity=ReviewSeverity.blocking.value,
        actor_context=actor_context,
    )
