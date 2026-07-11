"""`routers/reviews.py` — izole app ile authorization/API testleri.

StubActor testleri `get_current_actor`'ı override eder (hızlı yol, gerçek
session cookie'si yok -> CSRF otomatik no-op). CSRF/Origin testleri gerçek
session+CSRF akışını (`services/auth.py`) uçtan uca kurar.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.repositories import participants as participants_repo
from backend.app.services import review as review_service
from backend.app.services.access_control import ActorContext
from participants_fixtures import create_test_transaction
from reviews_fixtures import build_reviews_app, create_real_session, create_real_user, make_full_reviews_db


@pytest.fixture()
def conn():
    connection = make_full_reviews_db()
    try:
        yield connection
    finally:
        connection.close()


def actor(user_id="u1", platform_role=None) -> ActorContext:
    return ActorContext(actor_type="user", user_id=user_id, platform_role=platform_role, request_id="req-1")


def _open_case(conn, tx_id, **overrides):
    kwargs = dict(
        transaction_id=tx_id,
        phase="pre_ratification",
        source_type="validator",
        source_id="s1",
        reason_code="RC1",
        title="t",
        description="d",
        severity="blocking",
        actor_context=actor(),
    )
    kwargs.update(overrides)
    return review_service.open_case(conn, **kwargs)


def _assign(conn, tx_id, user_id, role):
    participants_repo.create_assignment(
        conn, transaction_id=tx_id, participant_id=None, user_id=user_id,
        legal_entity_id="entity-1", role=role,
    )


# --- list access -------------------------------------------------------------------


def test_list_requires_auth(conn) -> None:
    tx_id = create_test_transaction(conn)
    app = build_reviews_app(conn, actor_context=ActorContext(actor_type="anonymous"))
    response = TestClient(app).get(f"/api/transactions/{tx_id}/reviews")
    assert response.status_code == 401


def test_list_visible_to_transaction_participant(conn) -> None:
    tx_id = create_test_transaction(conn)
    _assign(conn, tx_id, "u1", "approver")
    _open_case(conn, tx_id)
    app = build_reviews_app(conn, actor_context=actor("u1"))
    response = TestClient(app).get(f"/api/transactions/{tx_id}/reviews")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_list_denies_unrelated_user_idor(conn) -> None:
    tx_id = create_test_transaction(conn)
    _assign(conn, tx_id, "u1", "manager")
    app = build_reviews_app(conn, actor_context=actor("intruder"))
    response = TestClient(app).get(f"/api/transactions/{tx_id}/reviews")
    assert response.status_code == 403


def test_list_visible_to_platform_reviewer_without_assignment(conn) -> None:
    tx_id = create_test_transaction(conn)
    _open_case(conn, tx_id)
    app = build_reviews_app(conn, actor_context=actor("reviewer-1", "reviewer"))
    response = TestClient(app).get(f"/api/transactions/{tx_id}/reviews")
    assert response.status_code == 200


def test_list_visible_to_platform_admin_without_assignment(conn) -> None:
    tx_id = create_test_transaction(conn)
    app = build_reviews_app(conn, actor_context=actor("admin-1", "admin"))
    response = TestClient(app).get(f"/api/transactions/{tx_id}/reviews")
    assert response.status_code == 200


def test_get_does_not_write_to_db(conn) -> None:
    tx_id = create_test_transaction(conn)
    _assign(conn, tx_id, "u1", "manager")
    case = _open_case(conn, tx_id)
    conn.commit()
    before = dict(conn.execute("SELECT status FROM review_cases WHERE id = ?", (case.id,)).fetchone())

    app = build_reviews_app(conn, actor_context=actor("u1"))
    client = TestClient(app)
    client.get(f"/api/transactions/{tx_id}/reviews")
    client.get(f"/api/transactions/{tx_id}/reviews")

    after = dict(conn.execute("SELECT status FROM review_cases WHERE id = ?", (case.id,)).fetchone())
    assert before == after


# --- comment authorization ----------------------------------------------------------


def test_manager_can_comment(conn) -> None:
    tx_id = create_test_transaction(conn)
    _assign(conn, tx_id, "u1", "manager")
    case = _open_case(conn, tx_id)
    app = build_reviews_app(conn, actor_context=actor("u1"))
    response = TestClient(app).post(
        f"/api/reviews/{case.id}/actions", json={"action": "comment", "comment": "hello"}
    )
    assert response.status_code == 200


def test_approver_can_comment(conn) -> None:
    tx_id = create_test_transaction(conn)
    _assign(conn, tx_id, "u2", "approver")
    case = _open_case(conn, tx_id)
    app = build_reviews_app(conn, actor_context=actor("u2"))
    response = TestClient(app).post(
        f"/api/reviews/{case.id}/actions", json={"action": "comment", "comment": "hi"}
    )
    assert response.status_code == 200


def test_unrelated_user_cannot_comment(conn) -> None:
    tx_id = create_test_transaction(conn)
    case = _open_case(conn, tx_id)
    app = build_reviews_app(conn, actor_context=actor("intruder"))
    response = TestClient(app).post(
        f"/api/reviews/{case.id}/actions", json={"action": "comment", "comment": "hi"}
    )
    assert response.status_code == 403


# --- state-changing actions: platform reviewer/admin, except commercial escalation --


def test_commercial_participant_cannot_resolve(conn) -> None:
    tx_id = create_test_transaction(conn)
    _assign(conn, tx_id, "u1", "manager")
    case = _open_case(conn, tx_id)
    app = build_reviews_app(conn, actor_context=actor("u1"))
    response = TestClient(app).post(
        f"/api/reviews/{case.id}/actions", json={"action": "resolve_reject"}
    )
    assert response.status_code == 403


def test_platform_reviewer_can_resolve(conn) -> None:
    tx_id = create_test_transaction(conn)
    case = _open_case(conn, tx_id)
    app = build_reviews_app(conn, actor_context=actor("reviewer-1", "reviewer"))
    response = TestClient(app).post(
        f"/api/reviews/{case.id}/actions", json={"action": "resolve_reject", "resolution_code": "CONFLICT"}
    )
    assert response.status_code == 200


def test_platform_admin_can_resolve(conn) -> None:
    tx_id = create_test_transaction(conn)
    case = _open_case(conn, tx_id)
    app = build_reviews_app(conn, actor_context=actor("admin-1", "admin"))
    response = TestClient(app).post(
        f"/api/reviews/{case.id}/actions", json={"action": "resolve_reject", "resolution_code": "CONFLICT"}
    )
    assert response.status_code == 200


def test_unknown_case_returns_404(conn) -> None:
    app = build_reviews_app(conn, actor_context=actor("reviewer-1", "reviewer"))
    response = TestClient(app).post(
        "/api/reviews/does-not-exist/actions", json={"action": "comment", "comment": "x"}
    )
    assert response.status_code == 404


def test_blocking_resolve_continue_returns_409() -> None:
    """Faz 4F-2: revision+revalidation olmadan blocking resolve_continue hâlâ 409 --
    `rule_sets_repo`'nun ihtiyaç duyduğu tablolar için ayrı, tam fixture kullanılır."""
    from reviews_fixtures import make_reviews_db_with_rule_sets

    conn = make_reviews_db_with_rule_sets()
    tx_id = create_test_transaction(conn)
    case = _open_case(conn, tx_id, severity="blocking")
    app = build_reviews_app(conn, actor_context=actor("reviewer-1", "reviewer"))
    response = TestClient(app).post(
        f"/api/reviews/{case.id}/actions", json={"action": "resolve_continue"}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "REVIEW_RESOLUTION_PRECONDITION_FAILED"
    conn.close()


def test_action_body_rejects_unknown_fields(conn) -> None:
    tx_id = create_test_transaction(conn)
    case = _open_case(conn, tx_id)
    app = build_reviews_app(conn, actor_context=actor("reviewer-1", "reviewer"))
    response = TestClient(app).post(
        f"/api/reviews/{case.id}/actions",
        json={"action": "comment", "comment": "x", "nested": {"a": 1}},
    )
    assert response.status_code == 422


# --- dependency override cleanup -----------------------------------------------------


def test_dependency_override_cleanup(dependency_override_cleanup) -> None:
    from backend.app.services.access_control import get_current_actor

    dependency_override_cleanup[get_current_actor] = lambda: ActorContext(actor_type="anonymous")
    from backend.app.main import app as real_app

    assert real_app.dependency_overrides.get(get_current_actor) is not None


def test_real_app_registers_review_routes() -> None:
    from backend.app.main import app as real_app

    client = TestClient(real_app)
    assert client.get("/api/transactions/tx/reviews").status_code == 401
    assert client.post(
        "/api/reviews/case/actions", json={"action": "comment", "comment": "x"}
    ).status_code == 401


# --- real session + CSRF/Origin -------------------------------------------------------


@pytest.fixture()
def session_conn(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Gerçek dosya tabanlı DB + `DB_PATH` env eşleşmesi.

    `services.access_control._resolve_session_actor`, `Depends(get_db)`
    üzerinden DEĞİL doğrudan `backend.app.db.connect()` (yeni bağlantı,
    `DB_PATH` env'ini okur) ile session'ı çözer -- bu yüzden CSRF/session
    testlerinde `:memory:` kullanılamaz (görünmeyen ikinci bir DB olurdu);
    gerçek dosya + `DB_PATH` eşleşmesi bu ayrımı ortadan kaldırır.
    """
    db_path = tmp_path / "reviews_session_test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    connection = make_full_reviews_db(str(db_path))
    try:
        yield connection
    finally:
        connection.close()


def test_missing_csrf_header_rejected_with_real_session(session_conn) -> None:
    conn = session_conn
    user_id = create_real_user(conn, email_normalized="reviewer@example.com", platform_role="reviewer")
    session = create_real_session(conn, user_id=user_id)
    conn.commit()
    tx_id = create_test_transaction(conn)
    conn.commit()
    case = _open_case(conn, tx_id)
    conn.commit()

    app = build_reviews_app(conn, actor_context=None)
    client = TestClient(app)
    client.cookies.set("m4t_session", session.raw_token)

    response = client.post(f"/api/reviews/{case.id}/actions", json={"action": "resolve_reject"})
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_TOKEN_INVALID"


def test_wrong_csrf_token_rejected(session_conn) -> None:
    conn = session_conn
    user_id = create_real_user(conn, email_normalized="reviewer2@example.com", platform_role="reviewer")
    session = create_real_session(conn, user_id=user_id)
    conn.commit()
    tx_id = create_test_transaction(conn)
    conn.commit()
    case = _open_case(conn, tx_id)
    conn.commit()

    app = build_reviews_app(conn, actor_context=None)
    client = TestClient(app)
    client.cookies.set("m4t_session", session.raw_token)

    response = client.post(
        f"/api/reviews/{case.id}/actions",
        json={"action": "resolve_reject"},
        headers={"X-CSRF-Token": "totally-wrong-token"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_TOKEN_INVALID"


def test_correct_csrf_token_accepted(session_conn) -> None:
    conn = session_conn
    user_id = create_real_user(conn, email_normalized="reviewer3@example.com", platform_role="reviewer")
    session = create_real_session(conn, user_id=user_id)
    conn.commit()
    tx_id = create_test_transaction(conn)
    conn.commit()
    case = _open_case(conn, tx_id)
    conn.commit()

    app = build_reviews_app(conn, actor_context=None)
    client = TestClient(app)
    client.cookies.set("m4t_session", session.raw_token)

    response = client.post(
        f"/api/reviews/{case.id}/actions",
        json={"action": "resolve_reject", "resolution_code": "OK"},
        headers={"X-CSRF-Token": session.raw_csrf_token},
    )
    assert response.status_code == 200


def test_wrong_origin_rejected(session_conn) -> None:
    conn = session_conn
    user_id = create_real_user(conn, email_normalized="reviewer4@example.com", platform_role="reviewer")
    session = create_real_session(conn, user_id=user_id)
    conn.commit()
    tx_id = create_test_transaction(conn)
    conn.commit()
    case = _open_case(conn, tx_id)
    conn.commit()

    app = build_reviews_app(conn, actor_context=None)
    client = TestClient(app)
    client.cookies.set("m4t_session", session.raw_token)

    response = client.post(
        f"/api/reviews/{case.id}/actions",
        json={"action": "resolve_reject", "resolution_code": "OK"},
        headers={"X-CSRF-Token": session.raw_csrf_token, "Origin": "https://evil.example.com"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_ORIGIN_MISMATCH"
