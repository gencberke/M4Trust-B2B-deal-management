"""Transaction participant/invitation/assignment domain şemaları (Plan 03 / Faz 3B).

`ExtractionJSON`den (§4.2) bağımsızdır — sözleşme yorumunu değil, bir tarafın
onboarding/kimlik durumunu temsil eder. `PartyProfileSnapshot`, extraction'ın
`parties.buyer/seller` şeklini genişletir ama şemayı DEĞİŞTİRMEZ (ayrı model).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class ParticipantRole(str, Enum):
    buyer = "buyer"
    seller = "seller"


class ParticipantStatus(str, Enum):
    invited = "invited"
    profile_incomplete = "profile_incomplete"
    ready = "ready"
    confirmed = "confirmed"


class AssignmentRole(str, Enum):
    manager = "manager"
    approver = "approver"
    viewer = "viewer"


class AssignmentStatus(str, Enum):
    active = "active"
    revoked = "revoked"


class InvitationStatus(str, Enum):
    pending = "pending"
    opened = "opened"
    accepted = "accepted"
    expired = "expired"
    revoked = "revoked"


class PartyProfileSnapshot(BaseModel):
    """Bir tarafın kimlik/iletişim görünümü — extraction/declared/confirmed
    aşamalarının hepsinde aynı şekli paylaşır."""

    model_config = ConfigDict(extra="forbid")

    name: str
    tax_id: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    address: str | None = None


class Participant(BaseModel):
    """`transaction_participants` satırının servis-katmanı görünümü (dahili)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    transaction_id: str
    role: ParticipantRole
    legal_entity_id: str | None = None
    status: ParticipantStatus
    extracted_snapshot: PartyProfileSnapshot | None = None
    declared_snapshot: PartyProfileSnapshot | None = None
    confirmed_snapshot: PartyProfileSnapshot | None = None
    confirmed_at: str | None = None
    created_at: str
    updated_at: str


class ParticipantPublicView(BaseModel):
    """`GET .../participants` cevabı — ham iletişim/tax bilgisi taşımaz.

    Yalnız karşı tarafın rol/durumunu ve gösterilebilir adını döner; tax_id,
    e-posta, telefon, adres hiçbir koşulda bu görünüme girmez (§6 PII ilkesi).
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    role: ParticipantRole
    status: ParticipantStatus
    display_name: str | None = None
    confirmed: bool
    confirmed_at: str | None = None


class ProfileUpdateRequest(BaseModel):
    """`PUT .../participants/me/profile` gövdesi — açık kullanıcı girdisi."""

    model_config = ConfigDict(extra="forbid")

    snapshot: PartyProfileSnapshot


class InvitationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    participant_role: ParticipantRole
    invited_email: str


class InvitationCreateResult(BaseModel):
    """Create cevabı — `invite_link` yalnız bu anda, tek seferliktir."""

    model_config = ConfigDict(extra="forbid")

    invitation_id: str
    participant_role: ParticipantRole
    expires_at: str
    invite_link: str


class InvitationListItem(BaseModel):
    """`GET /api/transactions/{id}/invitations` — creator-scoped davet satırı (token yok)."""

    model_config = ConfigDict(extra="forbid")

    invitation_id: str
    participant_role: ParticipantRole
    invited_email: str
    status: InvitationStatus
    created_at: str
    expires_at: str
    accepted_at: str | None = None


class InvitationPreview(BaseModel):
    """`GET /api/invitations/{token}/preview` — auth'suz, PII'siz güvenli önizleme."""

    model_config = ConfigDict(extra="forbid")

    participant_role: ParticipantRole
    transaction_reference: str


class InvitationAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legal_entity_id: str
