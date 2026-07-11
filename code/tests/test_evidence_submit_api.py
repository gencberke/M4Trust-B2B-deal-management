"""Plan 05 / Faz 5A — `routers/evidence_submit.py` izole app authorization testleri."""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.errors import ApiError, api_error_handler, unhandled_exception_handler
from backend.app.config import Settings
from backend.app.db import connect, get_db, init_db
from backend.app.middleware.request_id import RequestIDMiddleware
from backend.app.repositories import participants as participants_repo
from backend.app.services import participants as participants_service
from backend.app.services.access_control import ActorContext, get_current_actor
from backend.app.services.tracking_policy import create_draft_policy

_evidence_migration = import_module("backend.app.db.migrations.013_evidence_records")

_TX_ID = "tx-5a-api"
_BUYER_ENTITY = "entity-buyer"
_SELLER_ENTITY = "entity-seller"


def _actor(user_id: str, entity_id: str) -> ActorContext:
    return ActorContext(
        actor_type="user", user_id=user_id, acting_entity_id=entity_id,
        auth_method="session", request_id="req-5a-api",
    )


def _create_user(conn, user_id: str, email: str) -> None:
    conn.execute(
        "INSERT INTO users (id, email_normalized, password_hash, first_name, last_name, "
        "status, platform_role, created_at, updated_at) VALUES (?, ?, 'unused', 'T', 'U', "
        "'active', NULL, datetime('now'), datetime('now'))",
        (user_id, email),
    )


def _create_entity(conn, entity_id: str, created_by_user_id: str) -> None:
    conn.execute(
        "INSERT INTO legal_entities (id, entity_type, legal_name, tax_identifier_type, "
        "tax_identifier_ciphertext, tax_identifier_lookup_hmac, tax_identifier_last4, "
        "verification_status, created_by_user_id, created_at, updated_at) "
        "VALUES (?, 'company', ?, 'vkn', 'cipher', 'hmac', '1234', 'self_declared', ?, "
        "datetime('now'), datetime('now'))",
        (entity_id, f"Legal Entity {entity_id}", created_by_user_id),
    )


@pytest.fixture()
def conn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    connection = connect(Settings(db_path=tmp_path / "5a_api.db"))
    monkeypatch.setenv("DOCUMENT_STORAGE_DIR", str(tmp_path / "documents"))
    init_db(connection)
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='evidence_records'"
    ).fetchone() is None:
        _evidence_migration.apply(connection)

    _create_user(connection, "u-manager", "manager@example.com")
    _create_user(connection, "u-seller-approver", "seller-approver@example.com")
    _create_user(connection, "u-buyer-approver", "buyer-approver@example.com")
    _create_user(connection, "u-intruder", "intruder@example.com")
    _create_entity(connection, _BUYER_ENTITY, "u-manager")
    _create_entity(connection, _SELLER_ENTITY, "u-manager")

    connection.execute(
        "INSERT INTO transactions (id, state, buyer_token, seller_token, manager_token, "
        "markdown, masked_markdown, created_at, lifecycle_version, owner_entity_id) "
        "VALUES (?, 'active', NULL, NULL, NULL, NULL, NULL, 'now', "
        "'account_v2', ?)",
        (_TX_ID, _BUYER_ENTITY),
    )

    manager_actor = _actor("u-manager", _BUYER_ENTITY)
    buyer_participant = participants_service.attach_creator(
        connection, _TX_ID, manager_actor, "buyer", _BUYER_ENTITY
    )
    participants_service.create_counterparty_placeholder(connection, _TX_ID, "seller", None)
    seller_row = participants_repo.get_participant(connection, _TX_ID, "seller")
    connection.execute(
        "UPDATE transaction_participants SET legal_entity_id = ? WHERE id = ?",
        (_SELLER_ENTITY, seller_row["id"]),
    )
    participants_repo.create_assignment(
        connection, transaction_id=_TX_ID, participant_id=seller_row["id"],
        user_id="u-seller-approver", legal_entity_id=_SELLER_ENTITY, role="approver",
    )
    participants_repo.create_assignment(
        connection, transaction_id=_TX_ID, participant_id=buyer_participant.id,
        user_id="u-buyer-approver", legal_entity_id=_BUYER_ENTITY, role="approver",
    )

    create_draft_policy(connection, _TX_ID)
    connection.execute(
        "UPDATE tracking_policies SET manager_physical_delivery_confirmed = 1, "
        "tracking_mode = 'document_and_video', status = 'locked', locked_at = 'now' "
        "WHERE transaction_id = ?",
        (_TX_ID,),
    )
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()


def _build_app(conn, actor: ActorContext | None) -> FastAPI:
    from backend.app.routers import evidence_submit

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(evidence_submit.router)

    def _get_db():
        try:
            yield conn
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()

    app.dependency_overrides[get_db] = _get_db
    if actor is not None:
        app.dependency_overrides[get_current_actor] = lambda: actor
    return app


def _post_e_irsaliye(conn, actor, external_reference="ext-1", delivered_quantity=10.0):
    app = _build_app(conn, actor)
    client = TestClient(app)
    return client.post(
        f"/api/transactions/{_TX_ID}/evidence/e-irsaliye",
        json={"external_reference": external_reference, "delivered_quantity": delivered_quantity},
    )


def test_anonymous_evidence_submission_is_rejected(conn) -> None:
    response = _post_e_irsaliye(conn, ActorContext(actor_type="anonymous"))
    assert response.status_code == 401


def test_unrelated_user_is_rejected(conn) -> None:
    response = _post_e_irsaliye(conn, _actor("u-intruder", _BUYER_ENTITY))
    assert response.status_code == 403
    assert response.json()["code"] == "EVIDENCE_SUBMITTER_FORBIDDEN"


def test_buyer_approver_is_rejected(conn) -> None:
    response = _post_e_irsaliye(conn, _actor("u-buyer-approver", _BUYER_ENTITY))
    assert response.status_code == 403
    assert response.json()["code"] == "EVIDENCE_SUBMITTER_FORBIDDEN"


def test_seller_assignment_is_accepted(conn) -> None:
    response = _post_e_irsaliye(conn, _actor("u-seller-approver", _SELLER_ENTITY))
    assert response.status_code == 200, response.text
    assert response.json()["verification_status"] == "verified"


def test_evidence_before_funding_is_rejected(conn) -> None:
    conn.execute(
        "UPDATE transactions SET state = 'awaiting_ratification' WHERE id = ?", (_TX_ID,)
    )
    conn.commit()

    response = _post_e_irsaliye(conn, _actor("u-seller-approver", _SELLER_ENTITY))

    assert response.status_code == 409
    assert response.json()["code"] == "EVIDENCE_SUBMISSION_STATE_INVALID"


def test_manager_is_accepted(conn) -> None:
    response = _post_e_irsaliye(conn, _actor("u-manager", _BUYER_ENTITY))
    assert response.status_code == 200, response.text


def test_acting_entity_mismatch_is_rejected(conn) -> None:
    # u-seller-approver gerçek assignment'ı entity-seller'a bağlı; buyer entity ile gelirse reddedilir.
    response = _post_e_irsaliye(conn, _actor("u-seller-approver", _BUYER_ENTITY))
    assert response.status_code == 403
    assert response.json()["code"] == "EVIDENCE_SUBMITTER_FORBIDDEN"


def test_duplicate_external_reference_conflict_returns_409(conn) -> None:
    actor = _actor("u-manager", _BUYER_ENTITY)
    first = _post_e_irsaliye(conn, actor, external_reference="ext-dup", delivered_quantity=10.0)
    assert first.status_code == 200
    second = _post_e_irsaliye(conn, actor, external_reference="ext-dup", delivered_quantity=99.0)
    assert second.status_code == 409
    assert second.json()["code"] == "EVIDENCE_IDEMPOTENCY_CONFLICT"


def test_video_evidence_upload_happy_path(conn) -> None:
    app = _build_app(conn, _actor("u-manager", _BUYER_ENTITY))
    client = TestClient(app)
    response = client.post(
        f"/api/transactions/{_TX_ID}/evidence/video",
        files={"file": ("delivery.mp4", b"fake-bytes", "video/mp4")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["storage_ref"] is not None
    assert len(body["file_sha256"]) == 64
    assert body["verification_status"] in {"verified", "review_required"}


def test_video_exact_replay_does_not_create_file_or_rerun_analyzer(
    conn, tmp_path: Path, monkeypatch
) -> None:
    from backend.app.routers import evidence_submit

    calls = 0
    original_factory = evidence_submit.make_video_analyzer

    class CountingAnalyzer:
        def analyze(self, path):
            nonlocal calls
            calls += 1
            return original_factory(Settings.from_env()).analyze(path)

    monkeypatch.setattr(
        evidence_submit, "make_video_analyzer", lambda _settings: CountingAnalyzer()
    )
    app = _build_app(conn, _actor("u-manager", _BUYER_ENTITY))
    client = TestClient(app)
    first = client.post(
        f"/api/transactions/{_TX_ID}/evidence/video",
        files={"file": ("delivery.mp4", b"same-video", "video/mp4")},
    )
    assert first.status_code == 200, first.text
    file_count_after_first = len(list((tmp_path / "documents").rglob("*")))

    second = client.post(
        f"/api/transactions/{_TX_ID}/evidence/video",
        files={"file": ("renamed.mp4", b"same-video", "video/mp4")},
    )
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
    assert calls == 1
    assert len(list((tmp_path / "documents").rglob("*"))) == file_count_after_first


def test_video_analyzer_failure_cleans_up_storage(
    conn, tmp_path: Path, monkeypatch
) -> None:
    from backend.app.routers import evidence_submit

    class BrokenAnalyzer:
        def analyze(self, _path):
            raise RuntimeError("simulated analyzer failure")

    monkeypatch.setattr(
        evidence_submit, "make_video_analyzer", lambda _settings: BrokenAnalyzer()
    )
    app = _build_app(conn, _actor("u-manager", _BUYER_ENTITY))
    response = TestClient(app).post(
        f"/api/transactions/{_TX_ID}/evidence/video",
        files={"file": ("broken.mp4", b"broken-video", "video/mp4")},
    )
    assert response.status_code == 422
    assert not [path for path in (tmp_path / "documents").rglob("*") if path.is_file()]


def test_concurrent_same_video_failure_cannot_delete_successful_upload(
    conn, tmp_path: Path, monkeypatch
) -> None:
    """Aynı hash'in analyzer yarışı başarılı kaydın dosyasını silemez."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, Lock

    from backend.app.routers import evidence_submit

    success_recorded = Event()
    call_lock = Lock()
    call_count = 0
    original_factory = evidence_submit.make_video_analyzer
    original_submit = evidence_submit.evidence_records_service.submit_evidence

    class OneSuccessOneFailureAnalyzer:
        def analyze(self, path):
            nonlocal call_count
            with call_lock:
                call_count += 1
                call_number = call_count
            if call_number == 1:
                return original_factory(Settings.from_env()).analyze(path)
            if not success_recorded.wait(timeout=5):
                raise RuntimeError("successful evidence was not recorded")
            raise RuntimeError("simulated concurrent analyzer failure")

    def submit_and_signal(*args, **kwargs):
        record = original_submit(*args, **kwargs)
        if kwargs.get("evidence_type") == "video":
            success_recorded.set()
        return record

    monkeypatch.setattr(
        evidence_submit, "make_video_analyzer", lambda _settings: OneSuccessOneFailureAnalyzer()
    )
    monkeypatch.setattr(
        evidence_submit.evidence_records_service, "submit_evidence", submit_and_signal
    )

    conn2 = connect(Settings(db_path=tmp_path / "5a_api.db"))
    actor = _actor("u-manager", _BUYER_ENTITY)
    app_a = _build_app(conn, actor)
    app_b = _build_app(conn2, actor)
    try:
        with TestClient(app_a) as client_a, TestClient(app_b) as client_b:
            def post(client):
                return client.post(
                    f"/api/transactions/{_TX_ID}/evidence/video",
                    files={"file": ("same-a.mp4", b"concurrent-video", "video/mp4")},
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(post, (client_a, client_b)))

        assert sorted(response.status_code for response in responses) == [200, 422]
        success = next(response for response in responses if response.status_code == 200)
        storage_path = tmp_path / "documents" / success.json()["storage_ref"]
        assert storage_path.is_file()
        assert storage_path.read_bytes() == b"concurrent-video"
        assert conn.execute(
            "SELECT COUNT(*) FROM evidence_records WHERE transaction_id = ? AND evidence_type = 'video'",
            (_TX_ID,),
        ).fetchone()[0] == 1
    finally:
        conn2.close()


# --- static checks -----------------------------------------------------------------


def test_router_has_no_manual_commit_call() -> None:
    """Statik AST kontrolü -- docstring'lerdeki `conn.commit()` sözcük geçişini
    değil, gerçek fonksiyon çağrısı düğümlerini arar (transaction ownership
    tamamen `get_db` dependency'sinde kalmalı)."""
    module_path = (
        Path(__file__).resolve().parents[1] / "backend" / "app" / "routers" / "evidence_submit.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr in {"commit", "rollback"} and (
            isinstance(node.func.value, ast.Name) and node.func.value.id == "conn"
        ):
            pytest.fail(f"Beklenmeyen conn.{node.func.attr}() çağrısı router'da bulundu.")


def test_router_imports_no_payment_provider() -> None:
    module_path = (
        Path(__file__).resolve().parents[1] / "backend" / "app" / "routers" / "evidence_submit.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    forbidden_prefixes = (
        "backend.app.services.payment_provider",
        "backend.app.services.payments.moka",
        "backend.app.services.payments.ports",
    )
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for name in imported:
        assert not any(name == p or name.startswith(p + ".") for p in forbidden_prefixes), name
