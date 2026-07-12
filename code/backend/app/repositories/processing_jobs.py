"""Processing job persistence seam (Plan 07).

Repository fonksiyonları caller connection'ını kullanır; commit/rollback veya
connection ownership içermez. Job state geçişlerinin tek SQL kapısı burada
tutulur.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_by_id(conn: sqlite3.Connection, job_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM processing_jobs WHERE id = ?", (job_id,)).fetchone()


def get_by_idempotency(
    conn: sqlite3.Connection, *, kind: str, idempotency_key: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM processing_jobs WHERE kind = ? AND idempotency_key = ?",
        (kind, idempotency_key),
    ).fetchone()


def ensure_job(
    conn: sqlite3.Connection,
    *,
    kind: str,
    source_id: str,
    idempotency_key: str,
    transaction_id: str | None = None,
) -> sqlite3.Row:
    """Aynı (kind, idempotency_key) için tek job satırı üretir."""

    existing = get_by_idempotency(conn, kind=kind, idempotency_key=idempotency_key)
    if existing is not None:
        return existing

    now = _now()
    job_id = uuid4().hex
    try:
        conn.execute(
            """INSERT INTO processing_jobs (
                id, transaction_id, kind, source_id, idempotency_key,
                status, attempt_count, last_error_code, locked_at, started_at,
                finished_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'queued', 0, NULL, NULL, NULL, NULL, ?, ?)""",
            (
                job_id,
                transaction_id,
                kind,
                source_id,
                idempotency_key,
                now,
                now,
            ),
        )
    except sqlite3.IntegrityError:
        existing = get_by_idempotency(conn, kind=kind, idempotency_key=idempotency_key)
        if existing is None:
            raise
        return existing
    return get_by_id(conn, job_id)  # type: ignore[return-value]


def start_attempt(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    now: str | None = None,
    allow_succeeded: bool = False,
) -> sqlite3.Row:
    """Job'ı running'e alır ve gerçek çalışma attempt sayısını artırır."""

    row = get_by_id(conn, job_id)
    if row is None:
        raise KeyError(f"Processing job bulunamadı: {job_id}")
    if row["status"] == "running":
        return row
    if row["status"] == "succeeded" and not allow_succeeded:
        return row

    timestamp = now or _now()
    cursor = conn.execute(
        """UPDATE processing_jobs SET
            status = 'running', attempt_count = attempt_count + 1,
            locked_at = ?, started_at = COALESCE(started_at, ?),
            finished_at = NULL, last_error_code = NULL, updated_at = ?
        WHERE id = ? AND status != 'running'""",
        (timestamp, timestamp, timestamp, job_id),
    )
    if cursor.rowcount != 1:
        return get_by_id(conn, job_id)  # type: ignore[return-value]
    return get_by_id(conn, job_id)  # type: ignore[return-value]


def _mark(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    status: str,
    reason_code: str | None = None,
    now: str | None = None,
) -> sqlite3.Row:
    timestamp = now or _now()
    conn.execute(
        """UPDATE processing_jobs SET
            status = ?, last_error_code = ?, locked_at = NULL,
            finished_at = ?, updated_at = ?
        WHERE id = ?""",
        (status, reason_code, timestamp, timestamp, job_id),
    )
    row = get_by_id(conn, job_id)
    if row is None:
        raise KeyError(f"Processing job bulunamadı: {job_id}")
    return row


def mark_succeeded(
    conn: sqlite3.Connection, job_id: str, *, now: str | None = None
) -> sqlite3.Row:
    return _mark(conn, job_id, status="succeeded", now=now)


def mark_failed(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    reason_code: str,
    now: str | None = None,
) -> sqlite3.Row:
    return _mark(conn, job_id, status="failed", reason_code=reason_code, now=now)


def mark_unknown(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    reason_code: str,
    now: str | None = None,
) -> sqlite3.Row:
    return _mark(conn, job_id, status="unknown", reason_code=reason_code, now=now)


def mark_retry_pending(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    reason_code: str | None = None,
    now: str | None = None,
) -> sqlite3.Row:
    return _mark(conn, job_id, status="retry_pending", reason_code=reason_code, now=now)


def recover_stale_jobs(
    conn: sqlite3.Connection,
    *,
    stale_before: str,
    now: str | None = None,
) -> list[sqlite3.Row]:
    """Process ölümüyle running kalan job'ları tekrar kuyruğa alır."""

    timestamp = now or _now()
    ids = [
        row["id"]
        for row in conn.execute(
            "SELECT id FROM processing_jobs WHERE status = 'running' "
            "AND locked_at IS NOT NULL AND locked_at < ?",
            (stale_before,),
        ).fetchall()
    ]
    for job_id in ids:
        conn.execute(
            """UPDATE processing_jobs SET status = 'retry_pending',
                last_error_code = 'STALE_JOB_RECOVERED', locked_at = NULL,
                finished_at = ?, updated_at = ?
            WHERE id = ? AND status = 'running'""",
            (timestamp, timestamp, job_id),
        )
    return [row for job_id in ids if (row := get_by_id(conn, job_id)) is not None]


def list_recoverable(
    conn: sqlite3.Connection, *, kind: str | None = None
) -> list[sqlite3.Row]:
    if kind is None:
        return conn.execute(
            "SELECT * FROM processing_jobs WHERE status IN "
            "('queued', 'retry_pending', 'unknown') ORDER BY created_at"
        ).fetchall()
    return conn.execute(
        "SELECT * FROM processing_jobs WHERE kind = ? AND status IN "
        "('queued', 'retry_pending', 'unknown') ORDER BY created_at",
        (kind,),
    ).fetchall()
