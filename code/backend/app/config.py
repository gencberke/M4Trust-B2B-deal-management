"""Uygulama ayarları — env'den okunur, kod her yerde bu tek kaynağı kullanır.

Dış bağımlılık seçimleri (LLM sağlayıcı) ve yerel yollar burada toplanır; §3
adapter'ları `llm_provider` env'i ile seçilir. `llm_api_key` yalnızca env/.env'den
gelir ve ASLA loglanmaz/repr'e sızmaz (§secrets kuralı).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

# config.py -> app/ -> backend/ -> code/
_CODE_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_CHROMA_DIR = _CODE_ROOT / "data" / "processed" / "embeddings" / "chroma"
_DEFAULT_DB_PATH = _CODE_ROOT / "data" / "runtime" / "m4trust.db"
_DEFAULT_DOCUMENT_STORAGE_DIR = _CODE_ROOT / "data" / "runtime" / "documents"
_DOTENV_PATH = _CODE_ROOT / ".env"


def _read_known_dotenv() -> dict[str, str]:
    """Yalnız bilinen ``code/.env`` dosyasını process env'ini değiştirmeden oku."""

    try:
        values = dotenv_values(_DOTENV_PATH)
    except (OSError, ValueError):
        return {}
    return {key: value for key, value in values.items() if isinstance(value, str) and value}


def _env(name: str, default: str, dotenv: dict[str, str] | None = None) -> str:
    """Process env > bilinen dotenv > default; boş değer bir sonraki kaynağa düşer."""

    value = os.environ.get(name)
    if value:
        return value
    file_value = (dotenv or {}).get(name)
    return file_value if file_value else default


def _env_bool(name: str, default: bool, dotenv: dict[str, str] | None = None) -> bool:
    """Env'deki yaygın true biçimlerini bool'a çevir; boşsa default'u koru."""
    value = _env(name, "", dotenv)
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Tüm runtime ayarları. `Settings.from_env()` ile env'den kurulur."""

    llm_provider: str = "fake"                       # "fake" (demo-güvenli) | "openai" (canlı)
    llm_fake_profile: str = "approval"               # "approval" (default, bit-bit korunur) | "delivery"
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
    demo_tools_enabled: bool = False                   # gizli demo araçları (router flag arkasında)
    app_encryption_key: str = ""                       # base64, 32 byte (AES-256-GCM) — legal_entities tax ID
    app_hmac_key: str = ""                             # base64 — tax identifier lookup HMAC-SHA256
    session_cookie_secure: bool = False                # prod'da true; local http demo'da false
    session_ttl_seconds: float = 604800.0              # 7 gün — oturum süresi
    auth_rate_limit_enabled: bool = True
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: float = 300.0
    account_lockout_threshold: int = 5
    account_lockout_window_seconds: float = 900.0
    account_lockout_seconds: float = 900.0
    password_reset_token_ttl_seconds: float = 1800.0
    email_verification_token_ttl_seconds: float = 86400.0
    email_verification_required: bool = False
    trust_proxy_headers: bool = False
    frontend_base_url: str = "http://127.0.0.1:5173"
    notification_provider: str = "fake"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_starttls: bool = True
    smtp_timeout_seconds: float = 10.0
    legacy_capability_access_enabled: bool = False      # Plan 06 closure: default off (env ile açılır)
    processing_job_stale_seconds: float = 300.0         # Plan 07 startup recovery eşiği
    document_storage_dir: Path = _DEFAULT_DOCUMENT_STORAGE_DIR  # LocalDocumentStorageProvider kökü (§2.11)
    max_contract_upload_bytes: int = 25 * 1024 * 1024
    max_evidence_upload_bytes: int = 25 * 1024 * 1024

    @classmethod
    def from_env(cls) -> "Settings":
        dotenv = _read_known_dotenv()
        chroma = _env("CHROMA_DIR", "", dotenv)
        db_path = _env("DB_PATH", "", dotenv)
        document_storage_dir = _env("DOCUMENT_STORAGE_DIR", "", dotenv)
        return cls(
            llm_provider=_env("LLM_PROVIDER", "fake", dotenv),
            llm_fake_profile=_env("LLM_FAKE_PROFILE", "approval", dotenv),
            llm_base_url=_env("LLM_BASE_URL", "https://api.openai.com/v1", dotenv),
            llm_model=_env("LLM_MODEL", "gpt-5.4-mini", dotenv),
            llm_api_key=_env("LLM_API_KEY", "", dotenv),
            llm_timeout=float(_env("LLM_TIMEOUT", "60", dotenv)),
            chroma_dir=Path(chroma).resolve() if chroma else _DEFAULT_CHROMA_DIR,
            rag_model_name=_env("RAG_MODEL", "BAAI/bge-m3", dotenv),
            legal_collection=_env("RAG_LEGAL_COLLECTION", "legal_articles", dotenv),
            contract_collection=_env("RAG_CONTRACT_COLLECTION", "contract_examples", dotenv),
            security_collection=_env("RAG_SECURITY_COLLECTION", "security_controls", dotenv),
            payment_provider=_env("PAYMENT_PROVIDER", "mock", dotenv),
            moka_base_url=_env("MOKA_BASE_URL", "http://127.0.0.1:8001", dotenv),
            moka_dealer_code=_env("MOKA_DEALER_CODE", "", dotenv),
            moka_username=_env("MOKA_USERNAME", "", dotenv),
            moka_password=_env("MOKA_PASSWORD", "", dotenv),
            moka_card_token=_env("MOKA_CARD_TOKEN", "", dotenv),
            moka_software=_env("MOKA_SOFTWARE", "M4Trust", dotenv),
            moka_timeout_seconds=float(_env("MOKA_TIMEOUT_SECONDS", "20", dotenv)),
            moka_contract_profile=_env(
                "MOKA_CONTRACT_PROFILE", "moka_payment_dealer_pool_v1", dotenv
            ),
            db_path=Path(db_path).resolve() if db_path else _DEFAULT_DB_PATH,
            validator_confidence_threshold=float(
                _env("VALIDATOR_CONFIDENCE_THRESHOLD", "0.7", dotenv)
            ),
            video_advisory_confidence_threshold=float(
                _env("VIDEO_ADVISORY_CONFIDENCE_THRESHOLD", "0.80", dotenv)
            ),
            video_provider=_env("VIDEO_PROVIDER", "fake", dotenv),
            roboflow_api_key=_env("ROBOFLOW_API_KEY", "", dotenv),
            demo_public_dashboard=_env_bool("DEMO_PUBLIC_DASHBOARD", False, dotenv),
            demo_tools_enabled=_env_bool("DEMO_TOOLS_ENABLED", False, dotenv),
            app_encryption_key=_env("APP_ENCRYPTION_KEY", "", dotenv),
            app_hmac_key=_env("APP_HMAC_KEY", "", dotenv),
            session_cookie_secure=_env_bool("SESSION_COOKIE_SECURE", False, dotenv),
            session_ttl_seconds=float(_env("SESSION_TTL_SECONDS", "604800", dotenv)),
            auth_rate_limit_enabled=_env_bool("AUTH_RATE_LIMIT_ENABLED", True, dotenv),
            login_rate_limit_attempts=int(_env("LOGIN_RATE_LIMIT_ATTEMPTS", "5", dotenv)),
            login_rate_limit_window_seconds=float(
                _env("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "300", dotenv)
            ),
            account_lockout_threshold=int(
                _env("ACCOUNT_LOCKOUT_THRESHOLD", "5", dotenv)
            ),
            account_lockout_window_seconds=float(
                _env("ACCOUNT_LOCKOUT_WINDOW_SECONDS", "900", dotenv)
            ),
            account_lockout_seconds=float(
                _env("ACCOUNT_LOCKOUT_SECONDS", "900", dotenv)
            ),
            password_reset_token_ttl_seconds=float(
                _env("PASSWORD_RESET_TOKEN_TTL_SECONDS", "1800", dotenv)
            ),
            email_verification_token_ttl_seconds=float(
                _env("EMAIL_VERIFICATION_TOKEN_TTL_SECONDS", "86400", dotenv)
            ),
            email_verification_required=_env_bool(
                "EMAIL_VERIFICATION_REQUIRED", False, dotenv
            ),
            trust_proxy_headers=_env_bool("TRUST_PROXY_HEADERS", False, dotenv),
            frontend_base_url=_env(
                "FRONTEND_BASE_URL", "http://127.0.0.1:5173", dotenv
            ),
            notification_provider=_env("NOTIFICATION_PROVIDER", "fake", dotenv),
            smtp_host=_env("SMTP_HOST", "", dotenv),
            smtp_port=int(_env("SMTP_PORT", "587", dotenv)),
            smtp_username=_env("SMTP_USERNAME", "", dotenv),
            smtp_password=_env("SMTP_PASSWORD", "", dotenv),
            smtp_from_email=_env("SMTP_FROM_EMAIL", "", dotenv),
            smtp_starttls=_env_bool("SMTP_STARTTLS", True, dotenv),
            smtp_timeout_seconds=float(_env("SMTP_TIMEOUT_SECONDS", "10", dotenv)),
            legacy_capability_access_enabled=_env_bool(
                "LEGACY_CAPABILITY_ACCESS_ENABLED", False, dotenv
            ),
            processing_job_stale_seconds=float(
                _env("PROCESSING_JOB_STALE_SECONDS", "300", dotenv)
            ),
            document_storage_dir=(
                Path(document_storage_dir).resolve()
                if document_storage_dir
                else _DEFAULT_DOCUMENT_STORAGE_DIR
            ),
            max_contract_upload_bytes=int(
                _env("MAX_CONTRACT_UPLOAD_BYTES", str(25 * 1024 * 1024), dotenv)
            ),
            max_evidence_upload_bytes=int(
                _env("MAX_EVIDENCE_UPLOAD_BYTES", str(25 * 1024 * 1024), dotenv)
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
        smtp_password_masked = "***" if self.smtp_password else ""
        return (
            f"Settings(llm_provider={self.llm_provider!r}, "
            f"llm_fake_profile={self.llm_fake_profile!r}, llm_base_url={self.llm_base_url!r}, "
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
            f"demo_tools_enabled={self.demo_tools_enabled!r}, "
            f"db_path={str(self.db_path)!r}, "
            f"validator_confidence_threshold={self.validator_confidence_threshold!r}, "
            f"video_advisory_confidence_threshold="
            f"{self.video_advisory_confidence_threshold!r}, "
            f"app_encryption_key={encryption_key_masked!r}, "
            f"app_hmac_key={hmac_key_masked!r}, "
            f"session_cookie_secure={self.session_cookie_secure!r}, "
            f"session_ttl_seconds={self.session_ttl_seconds!r}, "
            f"auth_rate_limit_enabled={self.auth_rate_limit_enabled!r}, "
            f"login_rate_limit_attempts={self.login_rate_limit_attempts!r}, "
            f"email_verification_required={self.email_verification_required!r}, "
            f"trust_proxy_headers={self.trust_proxy_headers!r}, "
            f"notification_provider={self.notification_provider!r}, "
            f"smtp_host={self.smtp_host!r}, smtp_port={self.smtp_port!r}, "
            f"smtp_username={self.smtp_username!r}, "
            f"smtp_password={smtp_password_masked!r}, "
            f"smtp_from_email={self.smtp_from_email!r}, "
            f"smtp_starttls={self.smtp_starttls!r}, "
            f"legacy_capability_access_enabled="
            f"{self.legacy_capability_access_enabled!r}, "
            f"processing_job_stale_seconds={self.processing_job_stale_seconds!r}, "
            f"document_storage_dir={str(self.document_storage_dir)!r}, "
            f"max_contract_upload_bytes={self.max_contract_upload_bytes!r}, "
            f"max_evidence_upload_bytes={self.max_evidence_upload_bytes!r})"
        )
