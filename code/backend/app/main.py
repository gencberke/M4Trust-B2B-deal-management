"""FastAPI app factory — ortak middleware/handler'lar + tüm router'lar.

`startup` hook'unda migration runner çalışır; Request-ID ve yeni API hata
zarfı Plan 02 integration contract'ı olarak burada kaydedilir. Plan 03
(Faz 3A/3B/3C) router kayıtları — `auth`/`entities`/`participants`/
`invitations` — bu entegrasyon checkpoint'inde eklendi (program_haritasi §3,
Revizyon #3: router kayıtları Berke'nin entegrasyon commit'idir). Plan 04
Wave A kapanışında `reviews`, Faz 4F-1'de `rule_sets` router'ı da aynı
app-factory wiring'ine eklendi.
"""

from __future__ import annotations

from fastapi import FastAPI

from backend.app.api.errors import ApiError, api_error_handler, unhandled_exception_handler
from backend.app.config import Settings
from backend.app.db import connect, init_db
from backend.app.middleware.request_id import RequestIDMiddleware
from backend.app.services import processing_jobs
from backend.app.routers import (
    approvals,
    auth,
    delivery,
    disputes,
    entities,
    evidence,
    evidence_submit,
    extraction_ops,
    invitations,
    participants,
    ratifications,
    payment_ops,
    reviews,
    rule_sets,
    transactions,
)


def create_app() -> FastAPI:
    app = FastAPI(title="M4Trust API")
    app.add_middleware(RequestIDMiddleware)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.on_event("startup")
    def _startup() -> None:
        conn = connect()
        try:
            init_db(conn)
            _recover_operational_jobs(conn)
            conn.commit()
        finally:
            conn.close()

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(transactions.router)
    app.include_router(approvals.router)
    app.include_router(delivery.router)
    app.include_router(evidence.router)
    app.include_router(evidence_submit.router)
    app.include_router(disputes.router)
    app.include_router(auth.router)
    app.include_router(entities.router)
    app.include_router(participants.router)
    app.include_router(invitations.router)
    app.include_router(reviews.router)
    app.include_router(rule_sets.router)
    app.include_router(ratifications.router)
    app.include_router(payment_ops.router)
    app.include_router(extraction_ops.router)

    return app


app = create_app()


def _recover_operational_jobs(conn) -> None:
    """Startup'ta yalnız recoverable state/job kaydı üretir; provider çağırmaz."""

    settings = Settings.from_env()
    processing_jobs.recover_stale_jobs(
        conn, stale_after_seconds=settings.processing_job_stale_seconds
    )

    extracting_transactions = conn.execute(
        "SELECT id FROM transactions WHERE state = 'extracting' ORDER BY created_at"
    ).fetchall()
    for transaction in extracting_transactions:
        job = processing_jobs.ensure_job(
            conn,
            kind="extraction",
            source_id=transaction["id"],
            transaction_id=transaction["id"],
            idempotency_key=f"extraction:transaction:{transaction['id']}",
        )
        if job["status"] == "succeeded":
            processing_jobs.mark_retry_pending(
                conn, job["id"], reason_code="EXTRACTION_STATE_RECOVERY"
            )

    unknown_units = conn.execute(
        "SELECT id, transaction_id FROM funding_units "
        "WHERE status IN ('pool_creation_unknown', 'approval_unknown') "
        "ORDER BY transaction_id, sequence"
    ).fetchall()
    for unit in unknown_units:
        job = processing_jobs.ensure_job(
            conn,
            kind="reconcile",
            source_id=unit["id"],
            transaction_id=unit["transaction_id"],
            idempotency_key=f"reconcile:funding-unit:{unit['id']}",
        )
        if job["status"] == "succeeded":
            processing_jobs.mark_retry_pending(
                conn, job["id"], reason_code="PAYMENT_UNKNOWN_RECOVERY"
            )
