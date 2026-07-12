"""Identity çekirdeği şemaları — user/session/legal-entity/membership (Faz 3A).

Bu modeller platformun operasyonel identity/erişim katmanını temsil eder;
``ExtractionJSON``a (§4.2) hiçbir alan eklemez ve ondan bağımsızdır.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

_TCKN_LENGTH = 11
_VKN_LENGTH = 10
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserStatus(str, Enum):
    active = "active"
    disabled = "disabled"


class PlatformRole(str, Enum):
    reviewer = "reviewer"
    admin = "admin"


class EntityType(str, Enum):
    individual = "individual"
    company = "company"


class TaxIdentifierType(str, Enum):
    tckn = "tckn"
    vkn = "vkn"


class VerificationStatus(str, Enum):
    self_declared = "self_declared"
    pending = "pending"
    verified = "verified"


class MembershipRole(str, Enum):
    owner = "owner"
    admin = "admin"
    member = "member"


class MembershipStatus(str, Enum):
    active = "active"
    revoked = "revoked"


class _EmailFieldModel(BaseModel):
    """`email` alanı için ortak biçim doğrulaması taşıyan taban sınıf."""

    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def _validate_email_shape(cls, value: str) -> str:
        if not _EMAIL_PATTERN.match(value):
            raise ValueError("Geçerli bir e-posta adresi girin.")
        return value


class RegisterRequest(_EmailFieldModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=8, max_length=256)
    first_name: str = Field(min_length=1, max_length=200)
    last_name: str = Field(min_length=1, max_length=200)


class LoginRequest(_EmailFieldModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=256)


class PasswordResetRequest(_EmailFieldModel):
    model_config = ConfigDict(extra="forbid")


class PasswordResetConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=512)
    new_password: str = Field(min_length=8, max_length=256)


class EmailVerificationConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=512)


class UserPublic(BaseModel):
    """Response projection — password_hash asla dönmez."""

    model_config = ConfigDict(extra="forbid")

    id: str
    email: str
    first_name: str
    last_name: str
    status: UserStatus
    platform_role: PlatformRole | None = None
    email_verified_at: str | None = None
    created_at: str


class EntityCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_type: EntityType
    legal_name: str = Field(min_length=1, max_length=300)
    tax_identifier_type: TaxIdentifierType
    tax_identifier: str
    tax_office: str | None = Field(default=None, max_length=200)
    address_json: dict[str, Any] | None = None

    @field_validator("tax_identifier")
    @classmethod
    def _validate_tax_identifier_shape(cls, value: str, info) -> str:
        digits = re.sub(r"\D", "", value)
        tax_type = info.data.get("tax_identifier_type")
        expected_length = _TCKN_LENGTH if tax_type == TaxIdentifierType.tckn else _VKN_LENGTH
        if tax_type is not None and len(digits) != expected_length:
            raise ValueError(
                f"{tax_type.value} {expected_length} haneli rakamlardan oluşmalıdır."
            )
        if not digits:
            raise ValueError("tax_identifier yalnızca rakam içermelidir.")
        return digits


class EntityUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legal_name: str | None = Field(default=None, min_length=1, max_length=300)
    tax_office: str | None = Field(default=None, max_length=200)
    address_json: dict[str, Any] | None = None


class EntityPublic(BaseModel):
    """Response projection — ciphertext/HMAC/tam kimlik numarası asla dönmez."""

    model_config = ConfigDict(extra="forbid")

    id: str
    entity_type: EntityType
    legal_name: str
    tax_identifier_type: TaxIdentifierType
    tax_identifier_last4: str
    tax_office: str | None = None
    address_json: dict[str, Any] | None = None
    verification_status: VerificationStatus
    my_role: MembershipRole
    created_at: str
    updated_at: str
