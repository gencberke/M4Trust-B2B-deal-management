"""CheckKey formülü ve kimlik doğrulama kuralları (§2.3, §14.3)."""

from __future__ import annotations

import hashlib

from backend.app.services.payments.moka.contracts import PaymentDealerAuthentication
from backend.app.services.payments.moka.errors import (
    AUTH_INVALID_ACCOUNT,
    AUTH_INVALID_REQUEST,
    AUTH_VIRTUAL_POS_NOT_FOUND,
)

from .config import MockMokaSettings


def compute_check_key(dealer_code: str, username: str, password: str) -> str:
    """SHA-256(DealerCode + "MK" + Username + "PD" + Password), lowercase hex (§2.3)."""

    material = f"{dealer_code}MK{username}PD{password}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def authenticate(auth: PaymentDealerAuthentication, settings: MockMokaSettings) -> str | None:
    """Auth bloğunu doğrular; hata varsa ilgili public ResultCode'u, yoksa None döner.

    Sıra (§14.3): boş/whitespace alan -> InvalidRequest; yanlış kimlik/checkkey ->
    InvalidAccount; kimlik doğruyken sanal pos kapalıysa -> VirtualPosNotFound.
    """

    if (
        not auth.DealerCode.strip()
        or not auth.Username.strip()
        or not auth.Password.strip()
        or not auth.CheckKey.strip()
    ):
        return AUTH_INVALID_REQUEST

    expected_check_key = compute_check_key(auth.DealerCode, auth.Username, auth.Password)
    if (
        auth.DealerCode != settings.dealer_code
        or auth.Username != settings.username
        or auth.Password != settings.password
        or auth.CheckKey.lower() != expected_check_key
    ):
        return AUTH_INVALID_ACCOUNT

    if not settings.virtual_pos_enabled:
        return AUTH_VIRTUAL_POS_NOT_FOUND

    return None
