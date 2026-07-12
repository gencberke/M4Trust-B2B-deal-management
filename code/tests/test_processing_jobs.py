"""Plan 07 processing job state machine testleri."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.db import connect, init_db
from backend.app.repositories import processing_jobs as jobs_repo
from backend.app.services import processing_jobs


def _conn(tmp_path):
    conn = connect(type("Settings", (), {"db_path": tmp_path / "jobs.db"})())
    init_db(conn)
    return conn


def test_job_idempotency_attempts_and_safe_reason_codes(tmp_path) -> None:
    conn = _conn(tmp_path)
    first = processing_jobs.ensure_job(
        conn,
        kind="release",
        source_id="unit-1",
        transaction_id=None,
        idempotency_key="release:unit-1",
    )
    duplicate = processing_jobs.ensure_job(
        conn,
        kind="release",
        source_id="unit-1",
        transaction_id=None,
        idempotency_key="release:unit-1",
    )
    assert first["id"] == duplicate["id"]

    running = processing_jobs.start_attempt(conn, first["id"])
    assert running["status"] == "running"
    assert running["attempt_count"] == 1
    failed = processing_jobs.mark_failed(
        conn, first["id"], reason_code="raw traceback should not persist"
    )
    assert failed["status"] == "failed"
    assert failed["last_error_code"] == "JOB_FAILED"
    assert conn.execute("SELECT COUNT(*) FROM processing_jobs").fetchone()[0] == 1
    conn.close()


def test_stale_running_job_becomes_retry_pending_without_commit_side_effect(tmp_path) -> None:
    conn = _conn(tmp_path)
    job = jobs_repo.ensure_job(
        conn,
        kind="reconcile",
        source_id="unit-2",
        idempotency_key="reconcile:unit-2",
    )
    stale = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    jobs_repo.start_attempt(conn, job["id"], now=stale)
    recovered = jobs_repo.recover_stale_jobs(
        conn,
        stale_before=datetime.now(timezone.utc).isoformat(),
        now=datetime.now(timezone.utc).isoformat(),
    )
    assert recovered[0]["status"] == "retry_pending"
    assert recovered[0]["last_error_code"] == "STALE_JOB_RECOVERED"
    conn.close()
