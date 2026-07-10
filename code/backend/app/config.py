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
    payment_provider: str = "mock"                   # "mock" (§3.3 MockMokaProvider) | ileride "real"
    db_path: Path = _DEFAULT_DB_PATH                   # sqlite3 dosya yolu (§5)
    validator_confidence_threshold: float = 0.7        # validator NEEDS_REVIEW eşiği (§6.2)
    video_advisory_confidence_threshold: float = 0.80  # ikincil video sinyali eşiği
    video_provider: str = "fake"                      # "fake" (demo-güvenli) | "roboflow" (canlı)
    roboflow_api_key: str = ""
    demo_public_dashboard: bool = False                # demo günü açık liste görünümü

    @classmethod
    def from_env(cls) -> "Settings":
        chroma = os.environ.get("CHROMA_DIR")
        db_path = os.environ.get("DB_PATH")
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
            db_path=Path(db_path).resolve() if db_path else _DEFAULT_DB_PATH,
            validator_confidence_threshold=float(_env("VALIDATOR_CONFIDENCE_THRESHOLD", "0.7")),
            video_advisory_confidence_threshold=float(
                _env("VIDEO_ADVISORY_CONFIDENCE_THRESHOLD", "0.80")
            ),
            video_provider=_env("VIDEO_PROVIDER", "fake"),
            roboflow_api_key=os.environ.get("ROBOFLOW_API_KEY", ""),
            demo_public_dashboard=_env_bool("DEMO_PUBLIC_DASHBOARD", False),
        )

    def __repr__(self) -> str:
        # API anahtarlarını asla açık yazma — log/traceback sızıntısını önler.
        llm_masked = "***" if self.llm_api_key else ""
        roboflow_masked = "***" if self.roboflow_api_key else ""
        return (
            f"Settings(llm_provider={self.llm_provider!r}, llm_base_url={self.llm_base_url!r}, "
            f"llm_model={self.llm_model!r}, llm_api_key={llm_masked!r}, "
            f"llm_timeout={self.llm_timeout!r}, chroma_dir={str(self.chroma_dir)!r}, "
            f"rag_model_name={self.rag_model_name!r}, legal_collection={self.legal_collection!r}, "
            f"contract_collection={self.contract_collection!r}, "
            f"security_collection={self.security_collection!r}, "
            f"payment_provider={self.payment_provider!r}, "
            f"video_provider={self.video_provider!r}, roboflow_api_key={roboflow_masked!r}, "
            f"demo_public_dashboard={self.demo_public_dashboard!r}, "
            f"db_path={str(self.db_path)!r}, "
            f"validator_confidence_threshold={self.validator_confidence_threshold!r}, "
            f"video_advisory_confidence_threshold="
            f"{self.video_advisory_confidence_threshold!r})"
        )
