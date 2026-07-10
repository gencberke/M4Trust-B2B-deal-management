"""Moka PaymentDealer CheckKey üretimi (§2.3)."""

from __future__ import annotations

from hashlib import sha256


def generate_check_key(*, dealer_code: str, username: str, password: str) -> str:
    """``DealerCode + MK + Username + PD + Password`` SHA-256 değerini üretir."""

    material = f"{dealer_code}MK{username}PD{password}".encode("utf-8")
    return sha256(material).hexdigest()
