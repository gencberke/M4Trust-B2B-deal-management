"""Processing job state machine (Plan 07).

Bu servis yalnız caller connection'ını kullanır. last_error_code güvenli
reason-code'dur; exception mesajı, traceback veya provider response'u buraya
asla yazılmaz.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from sqlite3 import Connection

from backend.app.repositories import processing_jobs as jobs_repo

_REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


class ProcessingJobError(ValueError):
    """Job input/state hatası."""


def safe_reason_code(reason_code: str | None, *, fallback: str = "UNKNOWN_ERROR") -> str:
    if isinstance(reason_code, str) and _REASON_CODE.fullmatch(reason_code):
        return reason_code
    return fallback


def ensure_job(
    conn: Connection,
    *,
    kind: str,
    source_id: str,
    idempotency_key: str,
    transaction_id: str | None = None,
):
    if kind not in {"extraction", "funding", "release", "reconcile"}:
        raise ProcessingJobError(f"Desteklenmeyen job türü: {kind}")
    if not source_id or not idempotency_key:
        raise ProcessingJobError("Job source_id ve idempotency_key gerektirir.")
    return jobs_repo.ensure_job(
        conn,
        kind=kind,
        source_id=source_id,
        idempotency_key=idempotency_key,
        transaction_id=transaction_id,
    )


def start_attempt(conn: Connection, job_id: str, *, allow_succeeded: bool = False):
    return jobs_repo.start_attempt(conn, job_id, allow_succeeded=allow_succeeded)


def mark_succeeded(conn: Connection, job_id: str):
    return jobs_repo.mark_succeeded(conn, job_id)


def mark_failed(conn: Connection, job_id: str, *, reason_code: str):
    return jobs_repo.mark_failed(
        conn, job_id, reason_code=safe_reason_code(reason_code, fallback="JOB_FAILED")
    )


def mark_unknown(conn: Connection, job_id: str, *, reason_code: str):
    return jobs_repo.mark_unknown(
        conn, job_id, reason_code=safe_reason_code(reason_code, fallback="PROVIDER_UNKNOWN")
    )


def mark_retry_pending(conn: Connection, job_id: str, *, reason_code: str | None = None):
    safe_code = safe_reason_code(reason_code, fallback="RETRY_PENDING") if reason_code else None
    return jobs_repo.mark_retry_pending(conn, job_id, reason_code=safe_code)


def recover_stale_jobs(
    conn: Connection, *, stale_after_seconds: float = 300.0
) -> list:
    now = datetime.now(timezone.utc)
    stale_before = (now - timedelta(seconds=max(stale_after_seconds, 0))).isoformat()
    return jobs_repo.recover_stale_jobs(conn, stale_before=stale_before, now=now.isoformat())
