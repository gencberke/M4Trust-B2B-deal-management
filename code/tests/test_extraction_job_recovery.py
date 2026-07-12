"""Plan 07 extraction job recovery testleri (Faz 7 follow-up remediation, Major 6).

`POST /api/transactions/{id}/extraction/retry` — stuck `extracting` account_v2
transaction'lar için explicit, operatör-tetiklemeli tek retry seam'i.

`TestClient` background task'ları senkron koşturduğu için "crash sonrası
stuck" senaryosu, `transaction_pipeline.run_pipeline`'ı geçici olarak
`_crash_before_extraction` ile değiştirerek üretilir: gerçek upload (kalıcı
`contract_documents`/storage) tamamlanır ama extraction hiç çalışmadan
"process ölür" (job `running`'de kalır) -- ardından startup recovery'nin
yapacağı gibi job `retry_pending`'e taşınır. Bu, gerçek bir crash'in ürettiği
durumla birebir eşleşir: `rule_set_versions`/`extraction_runs` HİÇ
oluşmamıştır (yalnız BAŞARILI bir ilk çalıştırmadan sonra tekrar extraction
denemek `rule_set_versions` UNIQUE(transaction_id, version) ihlaline düşer --
bu, retry'ın kapsamı DIŞINDADIR: zaten tamamlanmış bir transaction'ı yeniden
extraction'a almak `rule-revision` uçlarının işidir, bu endpoint'in değil)."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from backend.app.db import connect
from backend.app.repositories import processing_jobs as jobs_repo
from backend.app.services.access_control import ActorContext, get_current_actor
from extraction_fixtures import patch_extraction
from tests._identity_support import identity_keys  # noqa: F401

_SAMPLE_MARKDOWN = (
    "# Örnek Sözleşme\n\n"
    "Alıcı ile Satıcı arasında endüstriyel pompa alım satımı sözleşmesidir.\n"
    "Tarafların onayıyla ödeme yapılır.\n"
)

_ENTITY_PAYLOAD = {
    "entity_type": "company",
    "legal_name": "ABC Sanayi A.Ş.",
    "tax_identifier_type": "vkn",
    "tax_identifier": "1234567890",
}

_PASS_PAYLOAD = {
    "contract_id": "demo-extraction-recovery",
    "parties": {
        "buyer": {"name": "Örnek Alıcı A.Ş.", "tax_id": "1234567890"},
        "seller": {"name": "Örnek Satıcı Ltd. Şti.", "tax_id": "9876543210"},
    },
    "commercial_terms": {
        "currency": "TRY",
        "total_amount": 100000.0,
        "goods": [{"name": "Endüstriyel Pompa", "quantity": 10, "unit": "adet"}],
        "delivery_deadline": "2026-09-01",
    },
    "payment_rules": [
        {
            "milestone": "Teslimat",
            "trigger": "approval",
            "percentage": 100.0,
            "required_evidence": ["contract"],
            "source_quote": "Teslimat onaylandığında tutarın tamamı ödenir.",
            "confidence": 0.9,
        }
    ],
    "risk_flags": [],
    "needs_manual_review": False,
}

_RAW_EXCEPTION_TEXT = "simulated provider outage — must never persist raw"


class _RaisingExtractionService:
    """`extract()` her çağrıda ham bir exception fırlatan test dublörü."""

    def extract(self, masked_markdown, context):
        raise RuntimeError(_RAW_EXCEPTION_TEXT)


@pytest.fixture(autouse=True)
def _isolated_document_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCUMENT_STORAGE_DIR", str(tmp_path / "documents"))


def _register_login(client: TestClient, email: str) -> None:
    r = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123", "first_name": "A", "last_name": "B"},
    )
    assert r.status_code == 201, r.text
    r = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert r.status_code == 200, r.text


def _csrf(client: TestClient) -> dict:
    return {"X-CSRF-Token": client.cookies.get("m4t_csrf")}


def _acting_csrf(client: TestClient, created: dict) -> dict:
    return {
        **_csrf(client),
        "X-Acting-Entity-ID": created["acting_entity_id"],
    }


def _create_entity(client: TestClient) -> str:
    r = client.post("/api/entities", json=_ENTITY_PAYLOAD, headers=_csrf(client))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _upload_account_mode(client: TestClient, *, acting_entity_id: str) -> dict:
    response = client.post(
        "/api/transactions",
        data={"acting_entity_id": acting_entity_id, "own_role": "buyer"},
        files={"file": ("sozlesme.md", io.BytesIO(_SAMPLE_MARKDOWN.encode()), "text/markdown")},
        headers={**_csrf(client), "X-Acting-Entity-ID": acting_entity_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _account_transaction(client: TestClient, monkeypatch, email: str = "buyer@example.com") -> dict:
    """`buyer`/manager olarak yeni account_v2 transaction açar; PASS extraction ile
    NORMAL/TAM olarak tamamlanır (crash simülasyonu yok)."""
    patch_extraction(monkeypatch, _PASS_PAYLOAD)
    _register_login(client, email)
    entity_id = _create_entity(client)
    return _upload_account_mode(client, acting_entity_id=entity_id)


def _crash_before_extraction(transaction_id, is_passthrough, settings, mode_input) -> None:
    """`run_pipeline`'ın gerçek ilk adımlarını (job+state) taklit eder ama
    `_execute_pipeline`'ı hiç çağırmadan döner -- process crash simülasyonu.
    `rule_set_versions`/`extraction_runs` bu transaction için HİÇ oluşmaz."""
    from backend.app.db import open_background_connection
    from backend.app.services import processing_jobs as processing_jobs_service

    conn = open_background_connection(settings)
    try:
        job = processing_jobs_service.ensure_job(
            conn,
            kind="extraction",
            source_id=transaction_id,
            transaction_id=transaction_id,
            idempotency_key=f"extraction:transaction:{transaction_id}",
        )
        processing_jobs_service.start_attempt(conn, job["id"])
        conn.execute(
            "UPDATE transactions SET state = 'extracting' WHERE id = ?", (transaction_id,)
        )
        conn.commit()
    finally:
        conn.close()


def _stuck_account_transaction(client: TestClient, monkeypatch, email: str) -> dict:
    """Crash sonrası startup recovery'nin bulacağı TAM durumu üretir: gerçek
    kalıcı upload (contract_documents/storage) + extraction hiç tamamlanmadan
    process çökmüş -> job `retry_pending`, transaction `extracting`."""
    monkeypatch.setattr(
        "backend.app.services.transaction_pipeline.run_pipeline", _crash_before_extraction
    )
    _register_login(client, email)
    entity_id = _create_entity(client)
    created = _upload_account_mode(client, acting_entity_id=entity_id)
    transaction_id = created["id"]

    conn = connect()
    job = jobs_repo.get_by_idempotency(
        conn, kind="extraction", idempotency_key=f"extraction:transaction:{transaction_id}"
    )
    assert job is not None
    assert job["status"] == "running"
    assert job["attempt_count"] == 1
    jobs_repo.mark_retry_pending(conn, job["id"], reason_code="SIMULATED_CRASH_RECOVERY")
    conn.commit()
    conn.close()
    assert _tx_state(transaction_id) == "extracting"
    return created


def _job_row(job_id: str):
    conn = connect()
    row = jobs_repo.get_by_id(conn, job_id)
    conn.close()
    return row


def _job_for_transaction(transaction_id: str):
    conn = connect()
    row = jobs_repo.get_by_idempotency(
        conn, kind="extraction", idempotency_key=f"extraction:transaction:{transaction_id}"
    )
    conn.close()
    return row


def _tx_state(transaction_id: str) -> str:
    conn = connect()
    row = conn.execute(
        "SELECT state FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()
    conn.close()
    return row["state"]


def test_retry_pending_job_reruns_pipeline(client: TestClient, identity_keys, monkeypatch) -> None:
    created = _stuck_account_transaction(client, monkeypatch, "buyer1@example.com")
    transaction_id = created["id"]

    patch_extraction(monkeypatch, _PASS_PAYLOAD)
    resp = client.post(
        f"/api/transactions/{transaction_id}/extraction/retry",
        headers=_acting_csrf(client, created),
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["job_status"] == "succeeded"
    assert body["transaction_state"] != "extracting"


def test_successful_retry_clears_extracting_and_succeeds_job(
    client: TestClient, identity_keys, monkeypatch
) -> None:
    created = _stuck_account_transaction(client, monkeypatch, "buyer2@example.com")
    transaction_id = created["id"]
    job_id = _job_for_transaction(transaction_id)["id"]

    patch_extraction(monkeypatch, _PASS_PAYLOAD)
    resp = client.post(
        f"/api/transactions/{transaction_id}/extraction/retry",
        headers=_acting_csrf(client, created),
    )

    assert resp.status_code == 200, resp.text
    assert _job_row(job_id)["status"] == "succeeded"
    assert _tx_state(transaction_id) == "awaiting_approval"


def test_pipeline_failure_marks_job_failed_and_transaction_awaiting_review(
    client: TestClient, identity_keys, monkeypatch
) -> None:
    created = _stuck_account_transaction(client, monkeypatch, "buyer3@example.com")
    transaction_id = created["id"]
    job_id = _job_for_transaction(transaction_id)["id"]

    monkeypatch.setattr(
        "backend.app.services.transaction_pipeline.make_extraction_service",
        lambda settings: _RaisingExtractionService(),
    )
    resp = client.post(
        f"/api/transactions/{transaction_id}/extraction/retry",
        headers=_acting_csrf(client, created),
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["job_status"] == "failed"
    assert body["transaction_state"] == "awaiting_review"
    job = _job_row(job_id)
    assert job["status"] == "failed"
    assert job["last_error_code"] == "PIPELINE_ERROR"


def test_concurrent_retry_returns_409_and_pipeline_runs_once(
    client: TestClient, identity_keys, monkeypatch
) -> None:
    created = _stuck_account_transaction(client, monkeypatch, "buyer4@example.com")
    transaction_id = created["id"]
    job_id = _job_for_transaction(transaction_id)["id"]

    # Başka bir worker/process aynı job'ı zaten claim etmiş gibi simüle eder.
    conn = connect()
    claimed = jobs_repo.claim_for_retry(
        conn, job_id, from_statuses=("queued", "retry_pending", "failed", "unknown")
    )
    assert claimed is True
    conn.commit()
    conn.close()

    call_count = {"n": 0}

    class _CountingExtractionService:
        def extract(self, masked_markdown, context):
            call_count["n"] += 1
            raise AssertionError("pipeline kaybeden çağrı için hiç çalışmamalıydı")

    monkeypatch.setattr(
        "backend.app.services.transaction_pipeline.make_extraction_service",
        lambda settings: _CountingExtractionService(),
    )

    resp = client.post(
        f"/api/transactions/{transaction_id}/extraction/retry",
        headers=_acting_csrf(client, created),
    )

    assert resp.status_code == 409
    assert resp.json()["code"] == "EXTRACTION_RETRY_IN_PROGRESS"
    assert call_count["n"] == 0


def test_succeeded_job_is_not_retried(client: TestClient, identity_keys, monkeypatch) -> None:
    created = _account_transaction(client, monkeypatch)
    transaction_id = created["id"]
    # Normal tamamlanmış upload: extracting'de değil, job succeeded -- retry uygun değil.
    assert _tx_state(transaction_id) != "extracting"
    assert _job_for_transaction(transaction_id)["status"] == "succeeded"

    resp = client.post(
        f"/api/transactions/{transaction_id}/extraction/retry",
        headers=_acting_csrf(client, created),
    )

    assert resp.status_code == 409
    assert resp.json()["code"] == "EXTRACTION_RETRY_CONFLICT"


def test_non_account_v2_transaction_is_rejected(client: TestClient, identity_keys, monkeypatch) -> None:
    # Anonim legacy_v1 upload — acting_entity_id/own_role verilmez.
    patch_extraction(monkeypatch, _PASS_PAYLOAD)
    legacy_resp = client.post(
        "/api/transactions",
        files={"file": ("sozlesme.md", io.BytesIO(_SAMPLE_MARKDOWN.encode()), "text/markdown")},
    )
    assert legacy_resp.status_code == 200, legacy_resp.text
    legacy_id = legacy_resp.json()["id"]

    _register_login(client, "someone@example.com")
    resp = client.post(f"/api/transactions/{legacy_id}/extraction/retry", headers=_csrf(client))

    assert resp.status_code == 409
    assert resp.json()["code"] == "EXTRACTION_RETRY_CONFLICT"


def test_unrelated_authenticated_user_gets_403(client: TestClient, identity_keys, monkeypatch) -> None:
    created = _stuck_account_transaction(client, monkeypatch, "buyer5@example.com")
    transaction_id = created["id"]

    # Aynı client'a farklı bir kullanıcı olarak login olur -- session cookie'si
    # değişir, bu işlemle hiçbir ilişkisi (assignment) yoktur.
    _register_login(client, "stranger@example.com")
    resp = client.post(
        f"/api/transactions/{transaction_id}/extraction/retry",
        headers=_acting_csrf(client, created),
    )

    assert resp.status_code == 403
    assert resp.json()["code"] == "EXTRACTION_RETRY_FORBIDDEN"


def test_platform_reviewer_can_retry(client: TestClient, identity_keys, monkeypatch) -> None:
    created = _stuck_account_transaction(client, monkeypatch, "buyer6@example.com")
    transaction_id = created["id"]

    from backend.app.main import app

    app.dependency_overrides[get_current_actor] = lambda: ActorContext(
        actor_type="user",
        user_id="platform-reviewer-1",
        acting_entity_id=None,
        platform_role="reviewer",
        auth_method="session",
        request_id="req-extraction-retry",
    )
    try:
        patch_extraction(monkeypatch, _PASS_PAYLOAD)
        resp = client.post(
            f"/api/transactions/{transaction_id}/extraction/retry",
            headers=_acting_csrf(client, created),
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, resp.text
    assert resp.json()["job_status"] == "succeeded"


def test_retry_reuses_persisted_document_no_new_upload(
    client: TestClient, identity_keys, monkeypatch
) -> None:
    created = _stuck_account_transaction(client, monkeypatch, "buyer7@example.com")
    transaction_id = created["id"]

    conn = connect()
    before_count = conn.execute(
        "SELECT COUNT(*) FROM contract_documents WHERE transaction_id = ?", (transaction_id,)
    ).fetchone()[0]
    original_doc_id = conn.execute(
        "SELECT id FROM contract_documents WHERE transaction_id = ?", (transaction_id,)
    ).fetchone()[0]
    conn.close()
    assert before_count == 1

    patch_extraction(monkeypatch, _PASS_PAYLOAD)
    resp = client.post(
        f"/api/transactions/{transaction_id}/extraction/retry",
        headers=_acting_csrf(client, created),
    )
    assert resp.status_code == 200, resp.text

    conn = connect()
    after_count = conn.execute(
        "SELECT COUNT(*) FROM contract_documents WHERE transaction_id = ?", (transaction_id,)
    ).fetchone()[0]
    retried_run_doc_id = conn.execute(
        "SELECT document_id FROM extraction_runs WHERE transaction_id = ? "
        "ORDER BY created_at DESC LIMIT 1",
        (transaction_id,),
    ).fetchone()[0]
    conn.close()
    assert after_count == 1
    assert retried_run_doc_id == original_doc_id


def test_attempt_count_only_increments_on_real_execution(
    client: TestClient, identity_keys, monkeypatch
) -> None:
    created = _stuck_account_transaction(client, monkeypatch, "buyer8@example.com")
    transaction_id = created["id"]
    job_id = _job_for_transaction(transaction_id)["id"]
    before_attempts = _job_row(job_id)["attempt_count"]
    assert before_attempts == 1  # crash simülasyonundaki tek gerçek attempt

    patch_extraction(monkeypatch, _PASS_PAYLOAD)
    resp = client.post(
        f"/api/transactions/{transaction_id}/extraction/retry",
        headers=_acting_csrf(client, created),
    )
    assert resp.status_code == 200, resp.text
    assert _job_row(job_id)["attempt_count"] == before_attempts + 1


def test_raw_exception_and_pii_never_leak(client: TestClient, identity_keys, monkeypatch) -> None:
    created = _stuck_account_transaction(client, monkeypatch, "buyer9@example.com")
    transaction_id = created["id"]
    job_id = _job_for_transaction(transaction_id)["id"]

    monkeypatch.setattr(
        "backend.app.services.transaction_pipeline.make_extraction_service",
        lambda settings: _RaisingExtractionService(),
    )
    resp = client.post(
        f"/api/transactions/{transaction_id}/extraction/retry",
        headers=_acting_csrf(client, created),
    )
    assert resp.status_code == 200, resp.text
    assert _RAW_EXCEPTION_TEXT not in resp.text

    conn = connect()
    job = jobs_repo.get_by_id(conn, job_id)
    assert job["last_error_code"] == "PIPELINE_ERROR"
    assert _RAW_EXCEPTION_TEXT not in (job["last_error_code"] or "")
    events = conn.execute(
        "SELECT payload FROM events WHERE transaction_id = ?", (transaction_id,)
    ).fetchall()
    conn.close()
    assert all(_RAW_EXCEPTION_TEXT not in (row["payload"] or "") for row in events)


def test_startup_alone_does_not_call_provider(monkeypatch, tmp_path) -> None:
    db_path = tmp_path / "startup-recovery.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("LLM_PROVIDER", "fake")

    from backend.app.db import init_db

    conn = connect()
    init_db(conn)
    conn.execute(
        "INSERT INTO transactions (id, state, buyer_token, seller_token, manager_token, "
        "markdown, masked_markdown, created_at, lifecycle_version) VALUES "
        "('tx-startup-stuck', 'extracting', NULL, NULL, NULL, NULL, NULL, 'now', 'account_v2')"
    )
    conn.commit()
    conn.close()

    call_count = {"n": 0}

    class _BoomExtractionService:
        def extract(self, masked_markdown, context):
            call_count["n"] += 1
            raise AssertionError("startup provider/LLM'i hiç çağırmamalıydı")

    monkeypatch.setattr(
        "backend.app.services.transaction_pipeline.make_extraction_service",
        lambda settings: _BoomExtractionService(),
    )

    from backend.app.main import app

    with TestClient(app):
        pass

    assert call_count["n"] == 0
    conn = connect()
    tx = conn.execute(
        "SELECT state FROM transactions WHERE id = 'tx-startup-stuck'"
    ).fetchone()
    job = conn.execute(
        "SELECT status FROM processing_jobs WHERE kind = 'extraction' AND idempotency_key = ?",
        ("extraction:transaction:tx-startup-stuck",),
    ).fetchone()
    conn.close()
    assert tx["state"] == "extracting"
    assert job is not None
    assert job["status"] == "queued"
