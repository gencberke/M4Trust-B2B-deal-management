"""Plan 07 extraction job recovery (Faz 7 follow-up remediation, Major 6).

Genel amaçlı bir worker/scheduler DEĞİLDİR: yalnız stuck `extracting`
account_v2 transaction'lar için explicit, operatör-tetiklemeli tek bir retry
seam'i sağlar. Startup hook zaten stale job'ları `retry_pending`'e taşır ve
`extracting` transaction'lar için recoverable job kaydı üretir/işaretler
(`main.py::_recover_operational_jobs`) ama hiçbir işi gerçekten yeniden
çalıştırmaz -- provider/LLM çağrısı yalnız burada, yetkili bir insan
aksiyonuyla (`retry_extraction`) tetiklenir.

Mevcut kalıcı `contract_documents` + storage referansı kullanılır; yeni upload
istenmez. Extraction pipeline mantığı (convert/extract/validate) burada
KOPYALANMAZ -- yalnız mevcut `transaction_pipeline.run_pipeline` yeniden
çağrılır.
"""

from __future__ import annotations

from pathlib import Path
from sqlite3 import Connection

from backend.app.config import Settings
from backend.app.repositories import documents as documents_repo
from backend.app.repositories import processing_jobs as jobs_repo
from backend.app.services import processing_jobs
from backend.app.services import review as review_service
from backend.app.services.access_control import ActorContext
from backend.app.services.transaction_pipeline import AccountPipelineInput, run_pipeline

_EXTRACTION_KIND = "extraction"
_CLAIMABLE_STATUSES = ("queued", "retry_pending", "failed", "unknown")

# `routers/transactions.py::_validate_suffix`'in aynadığı sınıflandırma --
# yeni bir extraction/conversion kararı ÜRETMEZ, yalnız orijinal upload
# sırasında zaten seçilmiş suffix'i persisted `original_filename`'den
# yeniden türetir.
_CONVERTIBLE_SUFFIXES = {".pdf", ".docx", ".png", ".jpg", ".jpeg"}
_PASSTHROUGH_SUFFIXES = {".md", ".txt"}
_ALLOWED_SUFFIXES = _CONVERTIBLE_SUFFIXES | _PASSTHROUGH_SUFFIXES


class ExtractionRetryError(Exception):
    """Extraction retry input/state hatası (router 409'a çevirir)."""


class ExtractionRetryForbiddenError(ExtractionRetryError):
    """Yetkisiz aktör (router 403'e çevirir)."""


class ExtractionRetryNotFoundError(ExtractionRetryError):
    """İşlem/doküman bulunamadı (router 404'e çevirir)."""


class ExtractionRetryConflictError(ExtractionRetryError):
    """İşlem/job retry için uygun durumda değil veya zaten claim edilmiş (router 409'a çevirir)."""


def _suffix_for_retry(original_filename: str) -> str:
    suffix = Path(original_filename or "").suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        # Persisted kayıt bozulmuş/tanınmayan bir uzantı taşıyor -- fail-closed.
        raise ExtractionRetryError(
            "Kalıcı doküman kaydının dosya türü tanınmıyor; retry yapılamaz."
        )
    return suffix


def retry_extraction(
    conn: Connection,
    *,
    transaction_id: str,
    actor_context: ActorContext,
    settings: Settings | None = None,
) -> dict:
    """Stuck `extracting` bir account_v2 transaction için extraction pipeline'ını
    mevcut kalıcı doküman/storage referansından yeniden çalıştırır.

    Yalnız claim'i kazanan çağrı `transaction_pipeline.run_pipeline`'ı çağırır;
    kaybeden çağrı `ExtractionRetryConflictError` alır (router 409'a çevirir,
    provider/LLM'e hiç gidilmez)."""

    transaction = conn.execute(
        "SELECT id, state, lifecycle_version FROM transactions WHERE id = ?",
        (transaction_id,),
    ).fetchone()
    if transaction is None:
        raise ExtractionRetryNotFoundError("İşlem bulunamadı.")
    if transaction["lifecycle_version"] != "account_v2":
        raise ExtractionRetryError(
            "Extraction retry yalnız account_v2 işlemler için kullanılabilir."
        )

    if not (
        review_service.is_platform_reviewer_or_admin(actor_context)
        or review_service.is_transaction_manager(conn, transaction_id, actor_context)
    ):
        raise ExtractionRetryForbiddenError(
            "Extraction retry için transaction manager veya platform reviewer/admin gerekir."
        )

    idempotency_key = f"extraction:transaction:{transaction_id}"
    job = jobs_repo.get_by_idempotency(
        conn, kind=_EXTRACTION_KIND, idempotency_key=idempotency_key
    )
    recoverable_job = job is not None and job["status"] in {
        "retry_pending",
        "failed",
        "unknown",
    }
    if transaction["state"] != "extracting" and not recoverable_job:
        # `ExtractionRetryConflictError` DEĞİL -- o yalnız atomik claim kaybı
        # (gerçek concurrent retry) için ayrılmıştır; router onu ayrı bir
        # `EXTRACTION_RETRY_IN_PROGRESS` koduna çevirir.
        raise ExtractionRetryError(
            "İşlem 'extracting' durumunda değil ve kurtarılabilir bir extraction "
            "job'ı yok; retry yapılamaz."
        )

    if job is None:
        job = processing_jobs.ensure_job(
            conn,
            kind=_EXTRACTION_KIND,
            source_id=transaction_id,
            transaction_id=transaction_id,
            idempotency_key=idempotency_key,
        )

    document = documents_repo.get_current_active(conn, transaction_id)
    if document is None:
        raise ExtractionRetryNotFoundError(
            "Kalıcı sözleşme dokümanı bulunamadı; retry yapılamaz."
        )
    suffix = _suffix_for_retry(document["original_filename"])
    is_passthrough = suffix in _PASSTHROUGH_SUFFIXES

    claimed = processing_jobs.claim_for_retry(
        conn, job["id"], from_statuses=_CLAIMABLE_STATUSES
    )
    if not claimed:
        raise ExtractionRetryConflictError(
            "Extraction retry şu anda başka bir çağrı tarafından yürütülüyor."
        )

    conn.execute(
        "UPDATE transactions SET state = 'extracting' WHERE id = ?", (transaction_id,)
    )
    conn.commit()

    resolved_settings = settings or Settings.from_env()
    run_pipeline(
        transaction_id,
        is_passthrough,
        resolved_settings,
        AccountPipelineInput(
            document_id=document["id"],
            storage_ref=document["storage_ref"],
            suffix=suffix,
        ),
    )

    refreshed_job = jobs_repo.get_by_id(conn, job["id"])
    refreshed_transaction = conn.execute(
        "SELECT state FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()
    return {
        "transaction_id": transaction_id,
        "job_id": job["id"],
        "job_status": refreshed_job["status"] if refreshed_job is not None else None,
        "attempt_count": (
            refreshed_job["attempt_count"] if refreshed_job is not None else None
        ),
        "transaction_state": (
            refreshed_transaction["state"] if refreshed_transaction is not None else None
        ),
    }
