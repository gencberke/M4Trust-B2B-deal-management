"""Frozen `ParticipantService` (v2 §8.1) — Plan 03C bu üç imzayı çağırır.

```python
attach_creator(conn, transaction_id, actor_context, own_role, legal_entity_id) -> Participant
create_counterparty_placeholder(conn, transaction_id, counterparty_role, extracted_snapshot) -> Participant
accept_invitation(conn, invitation_token, actor_context, legal_entity_id) -> Participant
```

Bu üç imza donmuştur: parametre adları/sırası, dönüş tipi ve exception
taksonomisi Plan 03 sonunda kilitlenir. 3B, `services/access_control.py`'ye
veya auth/identity iç yapısına (session/user repository) bağımlı DEĞİLDİR —
yalnız donmuş `ActorContext` alanlarını (`user_id`, `request_id`, ...) okur ve
`users`/`memberships` tablolarına (Berke'nin 3A migration'ları, v2 §5.1/§5.4)
dar, salt-okunur SQL ile bakar (`repositories/participants.py::
get_user_email_normalized`/`has_active_membership`) — Berke'nin repository/
service modüllerini import etmez.

Servisler kendi commit'lerini atmaz; transaction sınırı çağıranındır (router).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from backend.app.repositories import invitations as invitations_repo
from backend.app.repositories import participants as participants_repo
from backend.app.schemas.participants import Participant, ParticipantRole, ParticipantStatus
from backend.app.services import audit
from backend.app.services.access_control import ActorContext

_OTHER_ROLE = {"buyer": "seller", "seller": "buyer"}


class ParticipantAuthorizationError(Exception):
    """Actor bu aksiyonu yapmaya yetkili değil (kimliksiz veya yanlış context)."""


class ParticipantConflictError(Exception):
    """v2 §6.3 conflict kuralı ihlali (örn. aynı entity buyer+seller)."""


class ParticipantNotFoundError(Exception):
    """Beklenen participant satırı yok (tutarsız çağrı sırası)."""


class InvitationNotFoundError(Exception):
    """Token hash hiçbir invitation'a karşılık gelmiyor."""


class InvitationNotAcceptableError(Exception):
    """Invitation `pending` değil veya süresi dolmuş (expired/reused/revoked)."""


class InvitationEmailMismatchError(Exception):
    """Actor'ın hesap e-postası, davetin gönderildiği e-posta ile eşleşmiyor."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_participant(row: sqlite3.Row) -> Participant:
    return Participant(
        id=row["id"],
        transaction_id=row["transaction_id"],
        role=ParticipantRole(row["role"]),
        legal_entity_id=row["legal_entity_id"],
        status=ParticipantStatus(row["status"]),
        extracted_snapshot=json.loads(row["extracted_snapshot_json"])
        if row["extracted_snapshot_json"]
        else None,
        declared_snapshot=json.loads(row["declared_snapshot_json"])
        if row["declared_snapshot_json"]
        else None,
        confirmed_snapshot=json.loads(row["confirmed_snapshot_json"])
        if row["confirmed_snapshot_json"]
        else None,
        confirmed_at=row["confirmed_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _hash_invitation_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _is_expired(expires_at_iso: str) -> bool:
    expires_at = datetime.fromisoformat(expires_at_iso)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= expires_at


def _assert_no_same_entity_conflict(
    conn: sqlite3.Connection, transaction_id: str, own_role: str, legal_entity_id: str
) -> None:
    other_role = _OTHER_ROLE[own_role]
    counterpart = participants_repo.get_participant(conn, transaction_id, other_role)
    if counterpart is not None and counterpart["legal_entity_id"] == legal_entity_id:
        raise ParticipantConflictError(
            "Aynı legal entity aynı işlemde hem buyer hem seller olamaz."
        )


def attach_creator(
    conn: sqlite3.Connection,
    transaction_id: str,
    actor_context: ActorContext,
    own_role: str,
    legal_entity_id: str,
) -> Participant:
    """İşlemi başlatan actor'ı `own_role` participant'ı olarak bağlar + manager assignment'ı açar.

    Idempotent: aynı `(transaction_id, own_role)` için tekrar çağrılırsa (aynı
    `legal_entity_id` ile) mevcut participant'ı döner, duplicate üretmez.
    """
    if actor_context.user_id is None:
        raise ParticipantAuthorizationError("attach_creator authenticated user gerektirir.")

    existing = participants_repo.get_participant(conn, transaction_id, own_role)
    if existing is not None:
        if existing["legal_entity_id"] != legal_entity_id:
            raise ParticipantConflictError(
                f"{own_role} participant'ı zaten başka bir legal entity ile bağlı."
            )
    else:
        _assert_no_same_entity_conflict(conn, transaction_id, own_role, legal_entity_id)
        existing = participants_repo.create_participant(
            conn,
            transaction_id=transaction_id,
            role=own_role,
            legal_entity_id=legal_entity_id,
            status="ready",
        )

    if participants_repo.get_active_assignment(conn, transaction_id, actor_context.user_id) is None:
        participants_repo.create_assignment(
            conn,
            transaction_id=transaction_id,
            participant_id=existing["id"],
            user_id=actor_context.user_id,
            legal_entity_id=legal_entity_id,
            role="manager",
        )

    audit.record(
        conn,
        audit.AuditActor(
            actor_type="user",
            user_id=actor_context.user_id,
            acting_entity_id=legal_entity_id,
            request_id=actor_context.request_id,
        ),
        action="participant.creator_attached",
        target=f"transaction:{transaction_id}",
        metadata_allowlist=frozenset({"role"}),
        metadata={"role": own_role},
        transaction_id=transaction_id,
    )
    return _row_to_participant(existing)


def create_counterparty_placeholder(
    conn: sqlite3.Connection,
    transaction_id: str,
    counterparty_role: str,
    extracted_snapshot: dict[str, Any] | None,
) -> Participant:
    """Karşı taraf için `invited` durumunda bir placeholder açar.

    Idempotent: aynı `(transaction_id, counterparty_role)` için tekrar
    çağrılırsa mevcut satırı döner, confirmed/declared veri UYDURMAZ.
    """
    existing = participants_repo.get_participant(conn, transaction_id, counterparty_role)
    if existing is not None:
        return _row_to_participant(existing)

    row = participants_repo.create_participant(
        conn,
        transaction_id=transaction_id,
        role=counterparty_role,
        legal_entity_id=None,
        status="invited",
        extracted_snapshot=extracted_snapshot,
    )
    audit.record(
        conn,
        audit.AuditActor(actor_type="system"),
        action="participant.counterparty_placeholder_created",
        target=f"transaction:{transaction_id}",
        metadata_allowlist=frozenset({"role"}),
        metadata={"role": counterparty_role},
        transaction_id=transaction_id,
    )
    return _row_to_participant(row)


def accept_invitation(
    conn: sqlite3.Connection,
    invitation_token: str,
    actor_context: ActorContext,
    legal_entity_id: str,
) -> Participant:
    """Bir daveti kabul eder: participant'ı entity'ye bağlar + approver assignment açar.

    Sıra (hepsi fail-closed):
    authenticated -> bulunur (token hash) -> pending+süresiz -> creator != actor
    -> email eşleşir -> aktif membership -> aynı-entity conflict yok ->
    concurrency-safe tek kullanımlık accept -> participant bağla -> assignment
    -> audit (aynı transaction'da).
    """
    if actor_context.user_id is None:
        raise ParticipantAuthorizationError("accept_invitation authenticated user gerektirir.")

    token_hash = _hash_invitation_token(invitation_token)
    invitation = invitations_repo.get_invitation_by_token_hash(conn, token_hash)
    if invitation is None:
        raise InvitationNotFoundError("Davet bulunamadı.")

    if invitation["status"] != "pending":
        raise InvitationNotAcceptableError(f"Davet '{invitation['status']}' durumunda.")

    if _is_expired(invitation["expires_at"]):
        raise InvitationNotAcceptableError("Davetin süresi dolmuş.")

    if invitation["created_by_user_id"] == actor_context.user_id:
        raise ParticipantConflictError("Daveti oluşturan kendi davetini kabul edemez.")

    user_email = participants_repo.get_user_email_normalized(conn, actor_context.user_id)
    if user_email is None or user_email != invitation["invited_email_normalized"]:
        raise InvitationEmailMismatchError(
            "Hesap e-postası davetin gönderildiği e-posta ile eşleşmiyor."
        )

    if not participants_repo.has_active_membership(conn, actor_context.user_id, legal_entity_id):
        raise ParticipantAuthorizationError("Actor seçilen legal entity'de aktif üye değil.")

    own_role = invitation["participant_role"]
    _assert_no_same_entity_conflict(conn, invitation["transaction_id"], own_role, legal_entity_id)

    accepted = invitations_repo.try_mark_accepted(
        conn, invitation["id"], accepted_by_user_id=actor_context.user_id
    )
    if not accepted:
        raise InvitationNotAcceptableError(
            "Davet artık pending değil (eşzamanlı kabul veya iptal)."
        )

    participant_row = participants_repo.get_participant(conn, invitation["transaction_id"], own_role)
    if participant_row is None:
        raise ParticipantNotFoundError(
            "Beklenen participant placeholder'ı yok; tutarsız işlem durumu."
        )
    updated = participants_repo.link_participant_to_entity(
        conn, participant_row["id"], legal_entity_id=legal_entity_id, status="ready"
    )
    if updated is None:
        raise ParticipantConflictError(
            "Participant daha önce bağlanmış veya uygun başlangıç durumunda değil."
        )

    invitations_repo.revoke_pending_for_role(
        conn,
        invitation["transaction_id"],
        own_role,
        exclude_invitation_id=invitation["id"],
    )

    if (
        participants_repo.get_active_assignment(conn, invitation["transaction_id"], actor_context.user_id)
        is None
    ):
        participants_repo.create_assignment(
            conn,
            transaction_id=invitation["transaction_id"],
            participant_id=participant_row["id"],
            user_id=actor_context.user_id,
            legal_entity_id=legal_entity_id,
            role="approver",
        )

    audit.record(
        conn,
        audit.AuditActor(
            actor_type="user",
            user_id=actor_context.user_id,
            acting_entity_id=legal_entity_id,
            request_id=actor_context.request_id,
        ),
        action="invitation.accepted",
        target=f"invitation:{invitation['id']}",
        metadata_allowlist=frozenset({"role"}),
        metadata={"role": own_role},
        transaction_id=invitation["transaction_id"],
    )
    return _row_to_participant(updated)


# --- yardımcılar (frozen interface'in DIŞINDA — routers/participants.py kullanır) ---


def has_transaction_access(conn: sqlite3.Connection, transaction_id: str, user_id: str) -> bool:
    """Actor'ın bu işlemde herhangi bir aktif assignment'ı (manager/approver/viewer) var mı."""
    return participants_repo.get_active_assignment(conn, transaction_id, user_id) is not None


def get_my_participant(
    conn: sqlite3.Connection, transaction_id: str, user_id: str
) -> Participant | None:
    """Actor'ın bu işlemde temsil ettiği kendi participant satırı (varsa)."""
    assignment = participants_repo.get_active_assignment(conn, transaction_id, user_id)
    if assignment is None or assignment["participant_id"] is None:
        return None
    row = participants_repo.get_participant_by_id(conn, assignment["participant_id"])
    return _row_to_participant(row) if row is not None else None


def list_participants(conn: sqlite3.Connection, transaction_id: str) -> list[Participant]:
    return [_row_to_participant(row) for row in participants_repo.list_participants(conn, transaction_id)]


def update_declared_profile(
    conn: sqlite3.Connection,
    transaction_id: str,
    actor_context: ActorContext,
    snapshot: dict[str, Any],
) -> Participant:
    """`PUT .../participants/me/profile` — yalnız actor'ın KENDİ participant'ına yazar."""
    if actor_context.user_id is None:
        raise ParticipantAuthorizationError("update_declared_profile authenticated user gerektirir.")
    my_participant = get_my_participant(conn, transaction_id, actor_context.user_id)
    if my_participant is None:
        raise ParticipantNotFoundError("Actor'ın bu işlemde bir participant kaydı yok.")
    if my_participant.status == ParticipantStatus.confirmed:
        raise ParticipantConflictError(
            "Confirmed participant profili değiştirilemez (silent overwrite yasak)."
        )

    updated = participants_repo.update_declared_snapshot(
        conn, my_participant.id, declared_snapshot=snapshot, status="ready"
    )
    audit.record(
        conn,
        audit.AuditActor(
            actor_type="user",
            user_id=actor_context.user_id,
            acting_entity_id=actor_context.acting_entity_id,
            request_id=actor_context.request_id,
        ),
        action="participant.profile_updated",
        target=f"participant:{my_participant.id}",
        metadata_allowlist=frozenset(),
        transaction_id=transaction_id,
    )
    return _row_to_participant(updated)


def confirm_my_profile(
    conn: sqlite3.Connection, transaction_id: str, actor_context: ActorContext
) -> Participant:
    """`POST .../participants/me/confirm` — immutable confirmed snapshot + `confirmed_at` üretir."""
    if actor_context.user_id is None:
        raise ParticipantAuthorizationError("confirm_my_profile authenticated user gerektirir.")
    my_participant = get_my_participant(conn, transaction_id, actor_context.user_id)
    if my_participant is None:
        raise ParticipantNotFoundError("Actor'ın bu işlemde bir participant kaydı yok.")
    if my_participant.status == ParticipantStatus.confirmed:
        raise ParticipantConflictError(
            "Participant zaten confirmed (silent overwrite yasak)."
        )
    source_snapshot = my_participant.declared_snapshot or my_participant.extracted_snapshot
    if source_snapshot is None:
        raise ParticipantConflictError(
            "Confirm etmeden önce declared profil doldurulmalı."
        )

    updated = participants_repo.confirm_participant(
        conn, my_participant.id, confirmed_snapshot=source_snapshot.model_dump()
    )
    audit.record(
        conn,
        audit.AuditActor(
            actor_type="user",
            user_id=actor_context.user_id,
            acting_entity_id=actor_context.acting_entity_id,
            request_id=actor_context.request_id,
        ),
        action="participant.profile_confirmed",
        target=f"participant:{my_participant.id}",
        metadata_allowlist=frozenset(),
        transaction_id=transaction_id,
    )
    return _row_to_participant(updated)
