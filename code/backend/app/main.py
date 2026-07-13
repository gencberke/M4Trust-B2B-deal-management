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

import logging

from fastapi import FastAPI

from backend.app.api.errors import ApiError, api_error_handler, unhandled_exception_handler
from backend.app.config import Settings
from backend.app.db import connect, init_db
from backend.app.middleware.request_id import RequestIDMiddleware
from backend.app.structured_logging import configure_structured_logging
from backend.app.services import processing_jobs
from backend.app.routers import (
    approvals,
    auth,
    delivery,
    demo_tools,
    disputes,
    entities,
    evidence,
    evidence_submit,
    extraction_ops,
    fulfillment,
    invitations,
    participants,
    ratifications,
    payment_ops,
    reviews,
    rule_sets,
    transactions,
)

_logger = logging.getLogger("backend.main")


def create_app() -> FastAPI:
    configure_structured_logging()
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
    app.include_router(fulfillment.router)
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

    _mount_demo_tools_if_enabled(app)

    return app


def _mount_demo_tools_if_enabled(app: FastAPI) -> None:
    """Demo router'ını YALNIZ `DEMO_TOOLS_ENABLED=true` iken ve prod değilken mount eder.

    Tripwire (§Plan 14 / D3): secure session cookie prod proxy'sinin işaretidir;
    demo araçları açıkken secure cookie görülürse mount REDDEDİLİR + structured
    warning yazılır (yanlışlıkla prod'da demo yüzeyi açılmasını engeller).
    """
    settings = Settings.from_env()
    if not settings.demo_tools_enabled:
        return
    if settings.session_cookie_secure:
        _logger.warning(
            "demo tools mount rejected",
            extra={
                "action": "demo_tools.mount_rejected",
                "outcome": "rejected",
                "reason_code": "SESSION_COOKIE_SECURE",
            },
        )
        return
    app.include_router(demo_tools.router)


app = create_app()


def _recover_operational_jobs(conn) -> None:
    """Startup'ta yalnız recoverable state/job kaydı üretir; provider çağırmaz."""

    settings = Settings.from_env()
    processing_jobs.recover_stale_jobs(
        conn, stale_after_seconds=settings.processing_job_stale_seconds
    )

    extracting_transactions = conn.execute(
        "SELECT id FROM transactions WHERE state IN ('uploaded', 'extracting') "
        "ORDER BY created_at"
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
