"""`services/identity.py` — şifreleme, HMAC lookup ve entity servis testleri."""

from __future__ import annotations

import pytest

from backend.app.config import Settings
from backend.app.services import identity as identity_service
from tests._identity_support import identity_keys  # noqa: F401


def test_ciphertext_differs_from_plaintext(identity_keys) -> None:
    settings = Settings.from_env()
    ciphertext = identity_service.encrypt_tax_identifier("12345678901", settings=settings)
    assert "12345678901" not in ciphertext


def test_same_identifier_produces_different_ciphertext_due_to_random_nonce(identity_keys) -> None:
    settings = Settings.from_env()
    c1 = identity_service.encrypt_tax_identifier("12345678901", settings=settings)
    c2 = identity_service.encrypt_tax_identifier("12345678901", settings=settings)
    assert c1 != c2
    assert identity_service.decrypt_tax_identifier(c1, settings=settings) == "12345678901"
    assert identity_service.decrypt_tax_identifier(c2, settings=settings) == "12345678901"


def test_lookup_hmac_is_deterministic(identity_keys) -> None:
    settings = Settings.from_env()
    h1 = identity_service.tax_identifier_lookup_hmac("12345678901", settings=settings)
    h2 = identity_service.tax_identifier_lookup_hmac("12345678901", settings=settings)
    assert h1 == h2
    assert h1 != identity_service.tax_identifier_lookup_hmac("99999999999", settings=settings)


def test_last4_projection(identity_keys) -> None:
    assert identity_service.tax_identifier_last4("12345678901") == "8901"


def test_normalize_strips_non_digits() -> None:
    assert identity_service.normalize_tax_identifier("123 456-78 90") == "1234567890"


def test_missing_encryption_key_raises_configuration_error() -> None:
    settings = Settings(app_encryption_key="", app_hmac_key="")
    with pytest.raises(identity_service.KeyConfigurationError):
        identity_service.encrypt_tax_identifier("12345678901", settings=settings)
    with pytest.raises(identity_service.KeyConfigurationError):
        identity_service.tax_identifier_lookup_hmac("12345678901", settings=settings)


def test_settings_repr_masks_encryption_and_hmac_keys(identity_keys) -> None:
    settings = Settings.from_env()
    text = repr(settings)
    encryption_key, hmac_key = identity_keys
    assert encryption_key not in text
    assert hmac_key not in text
    assert "app_encryption_key='***'" in text
    assert "app_hmac_key='***'" in text
