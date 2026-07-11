"""Faz 3A testleri için paylaşılan yardımcılar (conftest.py'ye eklenmez —
Yusuf'un sahip olduğu dosyanın kapsamı dışında tutulur; bu modül yalnızca
identity testleri kendi dosyalarına import ederek fixture olarak kullanır).
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest


def _random_b64_key() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")


@pytest.fixture()
def identity_keys(monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    """`APP_ENCRYPTION_KEY`/`APP_HMAC_KEY`'i test başına rastgele üretir."""

    encryption_key = _random_b64_key()
    hmac_key = _random_b64_key()
    monkeypatch.setenv("APP_ENCRYPTION_KEY", encryption_key)
    monkeypatch.setenv("APP_HMAC_KEY", hmac_key)
    return encryption_key, hmac_key


def build_app_with_routers(*routers) -> "FastAPI":  # noqa: F821 - lazy import aşağıda
    from fastapi import FastAPI

    from backend.app.api.errors import ApiError, api_error_handler

    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    for router in routers:
        app.include_router(router)
    return app
