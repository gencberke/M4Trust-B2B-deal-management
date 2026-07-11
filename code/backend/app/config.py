"""Uygulama ayarları — env'den okunur, kod her yerde bu tek kaynağı kullanır.

Dış bağımlılık seçimleri (LLM sağlayıcı) ve yerel yollar burada toplanır; §3
adapter'ları `llm_provider` env'i ile seçilir. `llm_api_key` yalnızca env/.env'den
gelir ve ASLA loglanmaz/repr'e sızmaz (§secrets kuralı).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# config.py -> app/ -> backend/ -> code/
_CODE_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_CHROMA_DIR = _CODE_ROOT / "data" / "processed" / "embeddings" / "chroma"
_DEFAULT_DB_PATH = _CODE_ROOT / "data" / "runtime" / "m4trust.db"
_DEFAULT_DOCUMENT_STORAGE_DIR = _CODE_ROOT / "data" / "runtime" / "documents"


def _env(name: str, default: str) -> str:
    """Env değişkenini oku; tanımsız VEYA boş string ise default'a düş."""
    value = os.environ.get(name)
    return value if value else default


def _env_bool(name: str, default: bool) -> bool:
    """Env'deki yaygın true biçimlerini bool'a çevir; boşsa default'u koru."""
    value = os.environ.get(name)
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Tüm runtime ayarları. `Settings.from_env()` ile env'den kurulur."""

    llm_provider: str = "fake"                       # "fake" (demo-güvenli) | "openai" (canlı)
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-5.4-mini"                  # ekip kararı; env ile override edilebilir
    llm_api_key: str = ""
    llm_timeout: float = 60.0
    chroma_dir: Path = _DEFAULT_CHROMA_DIR
    rag_model_name: str = "BAAI/bge-m3"
    legal_collection: str = "legal_articles"
    contract_collection: str = "contract_examples"
    security_collection: str = "security_controls"
    payment_provider: str = "mock"                   # "mock" | "moka_http" (M1'de ana akışa bağlı değil)
    moka_base_url: str = "http://127.0.0.1:8001"
    moka_dealer_code: str = ""
    moka_username: str = ""
    moka_password: str = ""
    moka_card_token: str = ""
    moka_software: str = "M4Trust"
    moka_timeout_seconds: float = 20.0
    moka_contract_profile: str = "moka_payment_dealer_pool_v1"
    db_path: Path = _DEFAULT_DB_PATH                   # sqlite3 dosya yolu (§5)
    validator_confidence_threshold: float = 0.7        # validator NEEDS_REVIEW eşiği (§6.2)
    video_advisory_confidence_threshold: float = 0.80  # ikincil video sinyali eşiği
    video_provider: str = "fake"                      # "fake" (demo-güvenli) | "roboflow" (canlı)
    roboflow_api_key: str = ""
    demo_public_dashboard: bool = False                # demo günü açık liste görünümü
    app_encryption_key: str = ""                       # base64, 32 byte (AES-256-GCM) — legal_entities tax ID
    app_hmac_key: str = ""                             # base64 — tax identifier lookup HMAC-SHA256
    session_cookie_secure: bool = False                # prod'da true; local http demo'da false
    session_ttl_seconds: float = 604800.0              # 7 gün — oturum süresi
    legacy_capability_access_enabled: bool = True       # Wave 3'e kadar true; legacy token erişimi
    document_storage_dir: Path = _DEFAULT_DOCUMENT_STORAGE_DIR  # LocalDocumentStorageProvider kökü (§2.11)

    @classmethod
    def from_env(cls) -> "Settings":
        chroma = os.environ.get("CHROMA_DIR")
        db_path = os.environ.get("DB_PATH")
        document_storage_dir = os.environ.get("DOCUMENT_STORAGE_DIR")
        return cls(
            llm_provider=_env("LLM_PROVIDER", "fake"),
            llm_base_url=_env("LLM_BASE_URL", "https://api.openai.com/v1"),
            llm_model=_env("LLM_MODEL", "gpt-5.4-mini"),
            llm_api_key=os.environ.get("LLM_API_KEY", ""),
            llm_timeout=float(_env("LLM_TIMEOUT", "60")),
            chroma_dir=Path(chroma).resolve() if chroma else _DEFAULT_CHROMA_DIR,
            rag_model_name=_env("RAG_MODEL", "BAAI/bge-m3"),
            legal_collection=_env("RAG_LEGAL_COLLECTION", "legal_articles"),
            contract_collection=_env("RAG_CONTRACT_COLLECTION", "contract_examples"),
            security_collection=_env("RAG_SECURITY_COLLECTION", "security_controls"),
            payment_provider=_env("PAYMENT_PROVIDER", "mock"),
            moka_base_url=_env("MOKA_BASE_URL", "http://127.0.0.1:8001"),
            moka_dealer_code=os.environ.get("MOKA_DEALER_CODE", ""),
            moka_username=os.environ.get("MOKA_USERNAME", ""),
            moka_password=os.environ.get("MOKA_PASSWORD", ""),
            moka_card_token=os.environ.get("MOKA_CARD_TOKEN", ""),
            moka_software=_env("MOKA_SOFTWARE", "M4Trust"),
            moka_timeout_seconds=float(_env("MOKA_TIMEOUT_SECONDS", "20")),
            moka_contract_profile=_env(
                "MOKA_CONTRACT_PROFILE", "moka_payment_dealer_pool_v1"
            ),
            db_path=Path(db_path).resolve() if db_path else _DEFAULT_DB_PATH,
            validator_confidence_threshold=float(_env("VALIDATOR_CONFIDENCE_THRESHOLD", "0.7")),
            video_advisory_confidence_threshold=float(
                _env("VIDEO_ADVISORY_CONFIDENCE_THRESHOLD", "0.80")
            ),
            video_provider=_env("VIDEO_PROVIDER", "fake"),
            roboflow_api_key=os.environ.get("ROBOFLOW_API_KEY", ""),
            demo_public_dashboard=_env_bool("DEMO_PUBLIC_DASHBOARD", False),
            app_encryption_key=os.environ.get("APP_ENCRYPTION_KEY", ""),
            app_hmac_key=os.environ.get("APP_HMAC_KEY", ""),
            session_cookie_secure=_env_bool("SESSION_COOKIE_SECURE", False),
            session_ttl_seconds=float(_env("SESSION_TTL_SECONDS", "604800")),
            legacy_capability_access_enabled=_env_bool(
                "LEGACY_CAPABILITY_ACCESS_ENABLED", True
            ),
            document_storage_dir=(
                Path(document_storage_dir).resolve()
                if document_storage_dir
                else _DEFAULT_DOCUMENT_STORAGE_DIR
            ),
        )

    def __repr__(self) -> str:
        # API anahtarlarını asla açık yazma — log/traceback sızıntısını önler.
        llm_masked = "***" if self.llm_api_key else ""
        roboflow_masked = "***" if self.roboflow_api_key else ""
        moka_password_masked = "***" if self.moka_password else ""
        moka_card_token_masked = "***" if self.moka_card_token else ""
        encryption_key_masked = "***" if self.app_encryption_key else ""
        hmac_key_masked = "***" if self.app_hmac_key else ""
        return (
            f"Settings(llm_provider={self.llm_provider!r}, llm_base_url={self.llm_base_url!r}, "
            f"llm_model={self.llm_model!r}, llm_api_key={llm_masked!r}, "
            f"llm_timeout={self.llm_timeout!r}, chroma_dir={str(self.chroma_dir)!r}, "
            f"rag_model_name={self.rag_model_name!r}, legal_collection={self.legal_collection!r}, "
            f"contract_collection={self.contract_collection!r}, "
            f"security_collection={self.security_collection!r}, "
            f"payment_provider={self.payment_provider!r}, "
            f"moka_base_url={self.moka_base_url!r}, "
            f"moka_dealer_code={self.moka_dealer_code!r}, moka_username={self.moka_username!r}, "
            f"moka_password={moka_password_masked!r}, "
            f"moka_card_token={moka_card_token_masked!r}, "
            f"moka_software={self.moka_software!r}, "
            f"moka_timeout_seconds={self.moka_timeout_seconds!r}, "
            f"moka_contract_profile={self.moka_contract_profile!r}, "
            f"video_provider={self.video_provider!r}, roboflow_api_key={roboflow_masked!r}, "
            f"demo_public_dashboard={self.demo_public_dashboard!r}, "
            f"db_path={str(self.db_path)!r}, "
            f"validator_confidence_threshold={self.validator_confidence_threshold!r}, "
            f"video_advisory_confidence_threshold="
            f"{self.video_advisory_confidence_threshold!r}, "
            f"app_encryption_key={encryption_key_masked!r}, "
            f"app_hmac_key={hmac_key_masked!r}, "
            f"session_cookie_secure={self.session_cookie_secure!r}, "
            f"session_ttl_seconds={self.session_ttl_seconds!r}, "
            f"legacy_capability_access_enabled="
            f"{self.legacy_capability_access_enabled!r}, "
            f"document_storage_dir={str(self.document_storage_dir)!r})"
        )
