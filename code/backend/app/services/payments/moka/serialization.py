"""Moka sınırında para birimi ve Decimal-safe JSON serileştirme."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import simplejson

from backend.app.services.payments.moka.errors import ProviderValidationError

_INTERNAL_TO_MOKA_CURRENCY = {"TRY": "TL", "USD": "USD", "EUR": "EUR"}
_MOKA_TO_INTERNAL_CURRENCY = {value: key for key, value in _INTERNAL_TO_MOKA_CURRENCY.items()}
_UNSUPPORTED_CURRENCY = "PROVIDER_UNSUPPORTED_CURRENCY"


def to_moka_currency(currency: str) -> str:
    """Internal para birimini Moka contract değerine çevirir."""

    normalized = currency.strip().upper()
    try:
        return _INTERNAL_TO_MOKA_CURRENCY[normalized]
    except KeyError as exc:
        raise ProviderValidationError(
            result_code=_UNSUPPORTED_CURRENCY,
            result_message=f"Desteklenmeyen internal para birimi: {currency!r}",
        ) from exc


def from_moka_currency(currency: str) -> str:
    """Moka contract para birimini internal değere çevirir."""

    normalized = currency.strip().upper()
    try:
        return _MOKA_TO_INTERNAL_CURRENCY[normalized]
    except KeyError as exc:
        raise ProviderValidationError(
            result_code=_UNSUPPORTED_CURRENCY,
            result_message=f"Desteklenmeyen Moka para birimi: {currency!r}",
        ) from exc


def minor_units_to_decimal(amount_minor: int) -> Decimal:
    """Integer minor-unit tutarı binary float kullanmadan Decimal'a çevirir."""

    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int):
        raise ValueError("amount_minor tam sayı olmalıdır.")
    return (Decimal(amount_minor) / Decimal(100)).quantize(Decimal("0.01"))


def dumps_json(payload: Any) -> str:
    """Decimal değerleri JSON number olarak koruyan deterministik serializer."""

    return simplejson.dumps(
        payload,
        use_decimal=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def loads_json(payload: bytes | str) -> Any:
    """Provider JSON'unu Decimal kaybı olmadan parse eder."""

    return simplejson.loads(payload, use_decimal=True)
