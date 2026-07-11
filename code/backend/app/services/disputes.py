"""Frozen dispute lifecycle service (Plan 05 / Faz 5B, v2 §4.5/§5.16-5.17/§8.6).

```python
open_dispute(conn, *, transaction_id, milestone_id, reason_code, description,
             actor_context) -> Dispute
record_dispute_action(conn, *, dispute_id, actor_context, action, payload=None,
                       evidence_id=None) -> DisputeAction
list_disputes(conn, transaction_id) -> list[Dispute]
get_dispute(conn, dispute_id) -> Dispute
has_open_dispute(conn, transaction_id, milestone_id=None) -> bool
```

Dispute yalnız yetkili insan eylemidir: bu modül hiçbir zaman kendiliğinden
(video anomaly, review case, sistem) dispute açmaz veya action eklemez --
her çağrı, çağıranın (router) zaten doğruladığı bir authenticated participant
approver'ı temsil eden `ActorContext`'i taşımalıdır. HTTP/FastAPI bilmez,
provider çağırmaz, çağıranın connection'ını commit etmez.

Yetkilendirme kapısı (`participant approver`, `acting_entity_id` eşleşmesi)
`routers/disputes.py`'de yaşar; bu servis yalnız dispute'a ÖZGÜ, state'e
bağlı kuralları uygular: `cancel` yalnız opener, kapalı dispute'a yeni
state-changing action yok, `attach_evidence`/`escalate_dispute` çapraz-
transaction referans kabul etmez, serbest metin (description/comment)
`services/privacy.py` ile taranır.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from sqlite3 import Connection, Row
from typing import Any
from uuid import uuid4

from backend.app.repositories import disputes as disputes_repo
from backend.app.repositories import evidence as evidence_repo
from backend.app.repositories import reviews as reviews_repo
from backend.app.services import audit
from backend.app.services import privacy
from backend.app.services.access_control import ActorContext

_ACTIVE_STATUSES = frozenset({"open", "awaiting_response", "evidence_requested", "under_review"})
_PLATFORM_REVIEW_ROLES = frozenset({"reviewer", "admin"})

# action -> (yeni status | None, terminal-resolution mu)
_ACTION_TRANSITIONS: dict[str, tuple[str | None, bool]] = {
    "comment": (None, False),
    "attach_evidence": (None, False),
    "escalate_dispute": ("under_review", False),
    "resolve": ("resolved", True),
    "cancel": ("cancelled", True),
}

_TOKEN_LIKE_RE = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{24,}(?![A-Za-z0-9_-])")
_CODE_FORMAT_RE = re.compile(r"^[A-Z0-9_]+$")


class DisputeError(Exception):
    """Dispute domain hatalarının kökü."""


class DisputeNotFoundError(DisputeError):
    """Belirtilen dispute bulunamadı."""


class DisputeAlreadyOpenError(DisputeError):
    """Aynı (transaction, milestone) kapsamında zaten açık bir dispute var."""


class DisputeClosedError(DisputeError):
    """Dispute artık aktif durumda değil; yeni state-changing action reddedilir."""


class DisputeAuthorizationError(DisputeError):
    """Actor bu dispute action'ını yapmaya yetkili değil (ör. cancel yalnız opener)."""


class DisputeContentRejectedError(DisputeError):
    """`description`/`comment` içinde PII, kart verisi veya token/secret benzeri değer."""


class DisputeCrossTransactionReferenceError(DisputeError):
    """`evidence_id`/`review_case_id` dispute'un transaction'ına ait değil."""


@dataclass(frozen=True, slots=True)
class Dispute:
    id: str
    transaction_id: str
    milestone_id: str | None
    opened_by_user_id: str
    opened_by_entity_id: str
    reason_code: str
    description: str
    status: str
    resolution_code: str | None
    resolved_by_user_id: str | None
    created_at: str
    resolved_at: str | None


@dataclass(frozen=True, slots=True)
class DisputeAction:
    id: str
    dispute_id: str
    actor_user_id: str
    acting_entity_id: str
    action: str
    evidence_id: str | None
    payload: dict | None
    created_at: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _reject_if_sensitive_text(field_name: str, value: str | None) -> None:
    if not value:
        return
    report = privacy.analyze(value)
    if report.detected_types or report.mapping:
        raise DisputeContentRejectedError(
            f"{field_name} alanı PII veya kart verisi benzeri bir değer içeriyor."
        )
    if _TOKEN_LIKE_RE.search(value):
        raise DisputeContentRejectedError(
            f"{field_name} alanı token/secret benzeri opak bir değer içeriyor."
        )


def _reject_if_invalid_code(field_name: str, value: str) -> None:
    report = privacy.analyze(value)
    if report.detected_types or report.mapping:
        raise DisputeContentRejectedError(
            f"{field_name} alanı PII veya kart verisi benzeri bir değer içeriyor."
        )
    if not _CODE_FORMAT_RE.fullmatch(value):
        raise DisputeContentRejectedError(
            f"{field_name} yalnız büyük harf/rakam/alt çizgi içerebilir."
        )


def _row_to_dispute(row: Row) -> Dispute:
    return Dispute(
        id=row["id"],
        transaction_id=row["transaction_id"],
        milestone_id=row["milestone_id"],
        opened_by_user_id=row["opened_by_user_id"],
        opened_by_entity_id=row["opened_by_entity_id"],
        reason_code=row["reason_code"],
        description=row["description"],
        status=row["status"],
        resolution_code=row["resolution_code"],
        resolved_by_user_id=row["resolved_by_user_id"],
        created_at=row["created_at"],
        resolved_at=row["resolved_at"],
    )


def _row_to_action(row: Row) -> DisputeAction:
    return DisputeAction(
        id=row["id"],
        dispute_id=row["dispute_id"],
        actor_user_id=row["actor_user_id"],
        acting_entity_id=row["acting_entity_id"],
        action=row["action"],
        evidence_id=row["evidence_id"],
        payload=json.loads(row["payload_json"]) if row["payload_json"] else None,
        created_at=row["created_at"],
    )


def _actor_for_audit(actor: ActorContext) -> audit.AuditActor:
    return audit.AuditActor(
        actor_type="user" if actor.user_id else "system",
        user_id=actor.user_id,
        acting_entity_id=actor.acting_entity_id,
        request_id=actor.request_id,
    )


def open_dispute(
    conn: Connection,
    *,
    transaction_id: str,
    milestone_id: str | None,
    reason_code: str,
    description: str,
    actor_context: ActorContext,
) -> Dispute:
    """Yeni bir dispute açar. Aynı (transaction, milestone) kapsamında zaten
    açık bir dispute varsa `DisputeAlreadyOpenError` (fail closed; sessizce
    eskisine eklenmez, tekrar açma isteği reddedilir)."""
    if actor_context.user_id is None or actor_context.acting_entity_id is None:
        raise DisputeAuthorizationError("open_dispute authenticated user + acting_entity_id gerektirir.")

    _reject_if_invalid_code("reason_code", reason_code)
    _reject_if_sensitive_text("description", description)

    existing = disputes_repo.get_open_for_scope(
        conn, transaction_id=transaction_id, milestone_id=milestone_id
    )
    if existing is not None:
        raise DisputeAlreadyOpenError(
            f"Bu kapsamda (transaction={transaction_id!r}, milestone={milestone_id!r}) "
            "zaten açık bir dispute var."
        )

    dispute_id = uuid4().hex
    created_at = _utc_now_iso()
    try:
        disputes_repo.insert_dispute(
            conn,
            id=dispute_id,
            transaction_id=transaction_id,
            milestone_id=milestone_id,
            opened_by_user_id=actor_context.user_id,
            opened_by_entity_id=actor_context.acting_entity_id,
            reason_code=reason_code,
            description=description,
            created_at=created_at,
        )
    except sqlite3.IntegrityError as exc:
        # UNIQUE(transaction_id, milestone_id) WHERE terminal değil -- eşzamanlı
        # yarışta source of truth DB'dir.
        raise DisputeAlreadyOpenError(
            f"Bu kapsamda (transaction={transaction_id!r}, milestone={milestone_id!r}) "
            "zaten açık bir dispute var (eşzamanlı yarış)."
        ) from exc

    audit.record(
        conn,
        _actor_for_audit(actor_context),
        action="dispute.opened",
        target=f"dispute:{dispute_id}",
        metadata_allowlist=frozenset({"reason_code"}),
        metadata={"reason_code": reason_code},
        transaction_id=transaction_id,
    )
    return _row_to_dispute(disputes_repo.get_by_id(conn, dispute_id))


def record_dispute_action(
    conn: Connection,
    *,
    dispute_id: str,
    actor_context: ActorContext,
    action: str,
    payload: dict[str, Any] | None = None,
    evidence_id: str | None = None,
) -> DisputeAction:
    """Her zaman bir `dispute_actions` satırı ekler; state-changing action'lar
    için dispute status'ünü conditional olarak günceller (kapalı dispute'a yazılmaz)."""
    if actor_context.user_id is None or actor_context.acting_entity_id is None:
        raise DisputeAuthorizationError(
            "record_dispute_action authenticated user + acting_entity_id gerektirir."
        )
    if action not in _ACTION_TRANSITIONS:
        raise ValueError(f"Bilinmeyen dispute action: {action}")

    dispute_row = disputes_repo.get_by_id(conn, dispute_id)
    if dispute_row is None:
        raise DisputeNotFoundError(dispute_id)

    if action in {"cancel", "resolve"}:
        is_opener = (
            dispute_row["opened_by_user_id"] == actor_context.user_id
            and dispute_row["opened_by_entity_id"] == actor_context.acting_entity_id
        )
        is_platform_reviewer = actor_context.platform_role in _PLATFORM_REVIEW_ROLES
        if action == "cancel" and not is_opener:
            raise DisputeAuthorizationError("cancel yalnız dispute'u açan kullanıcı tarafından yapılabilir.")
        if action == "resolve" and not (is_opener or is_platform_reviewer):
            raise DisputeAuthorizationError(
                "resolve yalnız dispute'u açan taraf veya platform reviewer/admin tarafından yapılabilir."
            )

    if evidence_id is not None:
        evidence_row = evidence_repo.get_by_id(conn, evidence_id)
        if evidence_row is None or evidence_row["transaction_id"] != dispute_row["transaction_id"]:
            raise DisputeCrossTransactionReferenceError(
                "evidence_id bu dispute'un transaction'ına ait değil."
            )

    comment = (payload or {}).get("comment")
    _reject_if_sensitive_text("comment", comment)
    resolution_code = (payload or {}).get("resolution_code")
    if resolution_code is not None:
        _reject_if_invalid_code("resolution_code", resolution_code)
    review_case_id = (payload or {}).get("review_case_id")
    if action == "escalate_dispute":
        if not review_case_id:
            raise ValueError("escalate_dispute için review_case_id zorunludur.")
        review_case_row = reviews_repo.get_case_by_id(conn, review_case_id)
        if review_case_row is None or review_case_row["transaction_id"] != dispute_row["transaction_id"]:
            raise DisputeCrossTransactionReferenceError(
                "review_case_id bu dispute'un transaction'ına ait değil."
            )

    new_status, is_resolution = _ACTION_TRANSITIONS[action]

    if new_status is not None:
        if dispute_row["status"] not in _ACTIVE_STATUSES:
            raise DisputeClosedError(
                f"Dispute '{dispute_row['status']}' durumunda; yeni state-changing action yazılamaz."
            )
        resolved_at = _utc_now_iso() if is_resolution else None
        disputes_repo.update_status(
            conn,
            dispute_id=dispute_id,
            status=new_status,
            resolution_code=resolution_code if is_resolution else None,
            resolved_by_user_id=actor_context.user_id if is_resolution else None,
            resolved_at=resolved_at,
        )
    elif dispute_row["status"] not in _ACTIVE_STATUSES:
        # comment/attach_evidence: status değişmez ama kapalı dispute'a
        # yeni eylem eklenemez (timeline "donmuş" kabul edilir).
        raise DisputeClosedError(
            f"Dispute '{dispute_row['status']}' durumunda; yeni action yazılamaz."
        )

    action_id = uuid4().hex
    created_at = _utc_now_iso()
    safe_payload = dict(payload) if payload else None
    disputes_repo.append_action(
        conn,
        id=action_id,
        dispute_id=dispute_id,
        actor_user_id=actor_context.user_id,
        acting_entity_id=actor_context.acting_entity_id,
        action=action,
        evidence_id=evidence_id,
        payload_json=json.dumps(safe_payload, ensure_ascii=False) if safe_payload else None,
        created_at=created_at,
    )

    audit.record(
        conn,
        _actor_for_audit(actor_context),
        action=f"dispute.action.{action}",
        target=f"dispute:{dispute_id}",
        metadata_allowlist=frozenset(),
        transaction_id=dispute_row["transaction_id"],
    )

    return _row_to_action(disputes_repo.list_actions(conn, dispute_id)[-1])


def list_disputes(conn: Connection, transaction_id: str) -> list[Dispute]:
    return [_row_to_dispute(row) for row in disputes_repo.list_for_transaction(conn, transaction_id)]


def get_dispute(conn: Connection, dispute_id: str) -> Dispute:
    row = disputes_repo.get_by_id(conn, dispute_id)
    if row is None:
        raise DisputeNotFoundError(dispute_id)
    return _row_to_dispute(row)


def list_dispute_actions(conn: Connection, dispute_id: str) -> list[DisputeAction]:
    return [_row_to_action(row) for row in disputes_repo.list_actions(conn, dispute_id)]


def has_open_dispute(conn: Connection, transaction_id: str, milestone_id: str | None = None) -> bool:
    """Saf okuma: HTTP/provider bilmez, kendi connection'ını açmaz, commit çağırmaz
    (yalnız çağıranın connection'ıyla SELECT yapar -- settlement release guard'ının
    çağıracağı seam budur)."""
    return disputes_repo.has_open_dispute(conn, transaction_id=transaction_id, milestone_id=milestone_id)
