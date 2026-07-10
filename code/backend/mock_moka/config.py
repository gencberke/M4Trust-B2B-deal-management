"""Mock Moka servisinin kendi ayarları.

Ana backend'in `backend/app/config.py`'sine dokunulmaz/bağımlı değildir —
bu kırmızı çizgi gereği tamamen ayrı bir env alanı seti okunur
(`MOCK_MOKA_*` öneki, plans/ready/01_moka_contract_mock_and_client.md).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# config.py -> mock_moka/ -> backend/ -> code/
_CODE_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB_PATH = _CODE_ROOT / "data" / "runtime" / "mock_moka.db"


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class MockMokaSettings:
    """`MockMokaSettings.from_env()` ile kurulur; `Password` asla `__repr__`'e sızmaz."""

    dealer_code: str = "DEALER-DEMO-001"
    username: str = "m4trust_demo"
    password: str = "demo-secret"
    virtual_pos_enabled: bool = True
    faults_enabled: bool = False
    db_path: Path = _DEFAULT_DB_PATH

    @classmethod
    def from_env(cls) -> "MockMokaSettings":
        db_path = os.environ.get("MOCK_MOKA_DB_PATH")
        return cls(
            dealer_code=os.environ.get("MOCK_MOKA_DEALER_CODE", "DEALER-DEMO-001"),
            username=os.environ.get("MOCK_MOKA_USERNAME", "m4trust_demo"),
            password=os.environ.get("MOCK_MOKA_PASSWORD", "demo-secret"),
            virtual_pos_enabled=_env_bool("MOCK_MOKA_VIRTUAL_POS_ENABLED", True),
            faults_enabled=_env_bool("MOCK_MOKA_FAULTS_ENABLED", False),
            db_path=Path(db_path).resolve() if db_path else _DEFAULT_DB_PATH,
        )

    def __repr__(self) -> str:
        return (
            f"MockMokaSettings(dealer_code={self.dealer_code!r}, username={self.username!r}, "
            f"password='***', virtual_pos_enabled={self.virtual_pos_enabled!r}, "
            f"faults_enabled={self.faults_enabled!r}, db_path={str(self.db_path)!r})"
        )
