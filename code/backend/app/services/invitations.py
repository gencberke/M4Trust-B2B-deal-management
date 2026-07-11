"""Invitation yaşam döngüsü: create/preview/revoke (`accept` frozen
`ParticipantService.accept_invitation`'da yaşar, bkz. `services/participants.py`).

Raw invitation token yalnız `create_invitation`'ın dönüş değerinde, tek
seferlik bulunur -- ne DB'ye, ne audit'e, ne kalıcı log'a yazılır. Servisler
kendi commit'lerini atmaz.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from backend.app.repositories import invitations as invitations_repo
from backend.app.repositories import participants as participants_repo
from backend.app.schemas.participants import InvitationPreview, ParticipantRole
from backend.app.services import audit
from backend.app.services import participants as participants_service
from backend.app.services.access_control import ActorContext
from backend.app.services.notifications import NotificationDeliveryError, NotificationProvider

DEFAULT_INVITATION_TTL = timedelta(days=7)


class InvitationAuthorizationError(Exception):
    """Actor bu invitation aksiyonunu yapmaya yetkili değil."""


class InvitationNotFoundError(Exception):
    """Token hash veya invitation_id hiçbir kayda karşılık gelmiyor."""


class InvitationNotRevocableError(Exception):
    """Invitation zaten `pending` dışında bir durumda (accepted/expired/revoked)."""


@dataclass(frozen=True, slots=True)
class CreatedInvitation:
    """Create sonucunun servis-katmanı görünümü — `raw_token` yalnız burada bulunur.

    `notification_delivered=False`, provider gönderemediğinde de invitation
    satırının (ve audit kaydının) commit'e gideceğini belirtir -- bildirim
    kanalı başarısız olsa bile invitation her zaman kullanılabilir/tutarlı bir
    `pending` satır olarak kalır (business mutation'ı belirsiz bırakmaz)."""

    invitation_id: str
    transaction_id: str
    participant_role: str
    expires_at: str
    raw_token: str
    notification_delivered: bool


def _hash_invitation_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_expired(expires_at_iso: str) -> bool:
    expires_at = datetime.fromisoformat(expires_at_iso)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= expires_at


def actor_is_transaction_manager(
    conn: sqlite3.Connection, transaction_id: str, user_id: str
) -> bool:
    """Invitation create/revoke yetkisi: manager assignment sahibi olmak yeterlidir."""
    return (
        participants_repo.get_active_assignment(conn, transaction_id, user_id, role="manager")
        is not None
    )


def create_invitation(
    conn: sqlite3.Connection,
    transaction_id: str,
    participant_role: str,
    invited_email_normalized: str,
    actor_context: ActorContext,
    notification_provider: NotificationProvider,
    *,
    invite_link_builder,
    ttl: timedelta = DEFAULT_INVITATION_TTL,
) -> CreatedInvitation:
    """`invite_link_builder(raw_token) -> str` çağrılır -- URL şekli router'ın işidir."""
    if actor_context.user_id is None:
        raise InvitationAuthorizationError("create_invitation authenticated user gerektirir.")
    if not actor_is_transaction_manager(conn, transaction_id, actor_context.user_id):
        raise InvitationAuthorizationError(
            "Yalnız transaction manager/creator davet oluşturabilir."
        )

    # `accept_invitation`in bağlanacağı bir participant satırı garanti edilir.
    # 3C'nin upload-anı akışı (extracted_snapshot ile) bunu zaten önceden
    # oluşturmuş olabilir -- `create_counterparty_placeholder` idempotent
    # olduğu için burada tekrar çağrılması duplicate/veri kaybı üretmez.
    participants_service.create_counterparty_placeholder(
        conn, transaction_id, participant_role, None
    )

    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_invitation_token(raw_token)
    expires_at = (datetime.now(timezone.utc) + ttl).isoformat()

    row = invitations_repo.create_invitation(
        conn,
        transaction_id=transaction_id,
        participant_role=participant_role,
        invited_email_normalized=invited_email_normalized,
        token_hash=token_hash,
        expires_at=expires_at,
        created_by_user_id=actor_context.user_id,
    )

    audit.record(
        conn,
        audit.AuditActor(
            actor_type="user",
            user_id=actor_context.user_id,
            acting_entity_id=actor_context.acting_entity_id,
            request_id=actor_context.request_id,
        ),
        action="invitation.created",
        target=f"invitation:{row['id']}",
        metadata_allowlist=frozenset({"role"}),
        metadata={"role": participant_role},
        transaction_id=transaction_id,
    )

    invite_link = invite_link_builder(raw_token)
    try:
        notification_provider.send_invitation(
            to_email=invited_email_normalized,
            transaction_id=transaction_id,
            invite_link=invite_link,
        )
        notification_delivered = True
    except NotificationDeliveryError:
        notification_delivered = False

    return CreatedInvitation(
        invitation_id=row["id"],
        transaction_id=transaction_id,
        participant_role=participant_role,
        expires_at=expires_at,
        raw_token=raw_token,
        notification_delivered=notification_delivered,
    )


def preview_invitation(conn: sqlite3.Connection, invitation_token: str) -> InvitationPreview:
    """Auth'suz, side-effect'siz -- invitation durumunu YAZMAZ, yalnız okur."""
    token_hash = _hash_invitation_token(invitation_token)
    row = invitations_repo.get_invitation_by_token_hash(conn, token_hash)
    if row is None:
        raise InvitationNotFoundError("Davet bulunamadı.")
    if row["status"] != "pending":
        raise InvitationNotFoundError(f"Davet '{row['status']}' durumunda.")
    if _is_expired(row["expires_at"]):
        raise InvitationNotFoundError("Davetin süresi dolmuş.")

    return InvitationPreview(
        participant_role=ParticipantRole(row["participant_role"]),
        transaction_reference=row["transaction_id"][:8],
    )


def revoke_invitation(
    conn: sqlite3.Connection, transaction_id: str, invitation_id: str, actor_context: ActorContext
) -> None:
    if actor_context.user_id is None:
        raise InvitationAuthorizationError("revoke_invitation authenticated user gerektirir.")

    row = invitations_repo.get_invitation_by_id(conn, invitation_id)
    if row is None or row["transaction_id"] != transaction_id:
        raise InvitationNotFoundError("Davet bulunamadı.")

    is_creator = row["created_by_user_id"] == actor_context.user_id
    is_manager = actor_is_transaction_manager(conn, transaction_id, actor_context.user_id)
    if not (is_creator or is_manager):
        raise InvitationAuthorizationError("Yalnız yetkili manager/creator daveti iptal edebilir.")

    revoked = invitations_repo.mark_revoked(conn, invitation_id)
    if not revoked:
        raise InvitationNotRevocableError(f"Davet '{row['status']}' durumunda, iptal edilemez.")

    audit.record(
        conn,
        audit.AuditActor(
            actor_type="user",
            user_id=actor_context.user_id,
            acting_entity_id=actor_context.acting_entity_id,
            request_id=actor_context.request_id,
        ),
        action="invitation.revoked",
        target=f"invitation:{invitation_id}",
        metadata_allowlist=frozenset(),
        transaction_id=transaction_id,
    )
