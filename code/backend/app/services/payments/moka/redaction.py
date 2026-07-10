"""Moka HTTP trace'leri için derin, side-effect'siz redaction."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any, Iterable

_FULLY_MASKED_KEYS = {
    "password",
    "pan",
    "cardnumber",
    "card_number",
    "cvc",
    "cvv",
    "securitycode",
    "security_code",
    "clientip",
}
_CONTACT_KEYS = {
    "buyerinformations",
    "buyerinformation",
    "cardholderfullname",
    "email",
    "phone",
    "phonenumber",
    "address",
}


def _mask_check_key(value: object) -> str:
    text = str(value)
    if len(text) <= 10:
        return "***"
    return f"{text[:6]}...{text[-4:]}"


def _mask_card_token(value: object) -> str:
    text = str(value)
    suffix = text[-4:] if len(text) >= 4 else ""
    return f"token_****{suffix}"


def redact_payload(payload: Any, *, sensitive_values: Iterable[str] = ()) -> Any:
    """Request/response değerini kopyalar ve secret/PII alanlarını maskeler."""

    secrets = tuple(value for value in sensitive_values if value)

    def _redact(value: Any, key: str | None = None) -> Any:
        normalized_key = key.lower() if key else ""
        if normalized_key == "checkkey":
            return _mask_check_key(value)
        if normalized_key == "cardtoken":
            return _mask_card_token(value)
        if normalized_key in _FULLY_MASKED_KEYS or normalized_key in _CONTACT_KEYS:
            return "***"
        if isinstance(value, dict):
            return {item_key: _redact(item, item_key) for item_key, item in value.items()}
        if isinstance(value, list):
            return [_redact(item) for item in value]
        if isinstance(value, tuple):
            return tuple(_redact(item) for item in value)
        if isinstance(value, Decimal):
            return format(value, "f")
        if isinstance(value, str):
            redacted = value
            for secret in secrets:
                redacted = redacted.replace(secret, "***")
            return redacted
        return deepcopy(value)

    return _redact(payload)


def build_redacted_trace(
    *,
    endpoint: str,
    request: dict,
    response: object,
    sensitive_values: Iterable[str] = (),
) -> dict:
    """HTTP request/response çiftinin yalnız güvenli trace görünümünü üretir."""

    return {
        "endpoint": endpoint,
        "request": redact_payload(request, sensitive_values=sensitive_values),
        "response": redact_payload(response, sensitive_values=sensitive_values),
    }
