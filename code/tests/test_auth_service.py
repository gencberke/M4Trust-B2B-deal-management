"""`services/auth.py` — parola/oturum/CSRF servis-seviyesi testleri.

`DB_PATH` izolasyonu `tests/conftest.py::isolated_db` (autouse) tarafından
sağlanır; bu dosya yalnız kendi bağlantısını `connect()`/`init_db()` ile açar.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.api.errors import ApiError
from backend.app.config import Settings
from backend.app.db import connect, init_db
from backend.app.repositories import users as users_repo
from backend.app.services import auth as auth_service


@pytest.fixture()
def conn():
    connection = connect()
    init_db(connection)
    yield connection
    connection.close()


def test_password_hash_is_not_plaintext(conn) -> None:
    user_id = auth_service.register_user(
        conn, email="a@b.com", password="supersecret1", first_name="A", last_name="B"
    )
    row = users_repo.get_user_by_id(conn, user_id)
    assert row["password_hash"] != "supersecret1"
    assert auth_service.verify_password(row["password_hash"], "supersecret1")
    assert not auth_service.verify_password(row["password_hash"], "wrong")


def test_register_rejects_case_insensitive_duplicate_email(conn) -> None:
    auth_service.register_user(
        conn, email="Test@Example.com", password="supersecret1", first_name="A", last_name="B"
    )
    with pytest.raises(ApiError) as exc:
        auth_service.register_user(
            conn, email="test@example.com", password="another1", first_name="C", last_name="D"
        )
    assert exc.value.status_code == 409


def test_unknown_email_and_wrong_password_produce_same_generic_error(conn) -> None:
    auth_service.register_user(
        conn, email="known@example.com", password="correct-password", first_name="A", last_name="B"
    )

    with pytest.raises(ApiError) as unknown_exc:
        auth_service.authenticate_user(conn, email="unknown@example.com", password="whatever")
    with pytest.raises(ApiError) as wrong_exc:
        auth_service.authenticate_user(conn, email="known@example.com", password="wrong-password")

    assert unknown_exc.value.status_code == wrong_exc.value.status_code == 401
    assert unknown_exc.value.message == wrong_exc.value.message


def test_disabled_user_cannot_authenticate(conn) -> None:
    user_id = auth_service.register_user(
        conn, email="disabled@example.com", password="correct-password", first_name="A", last_name="B"
    )
    conn.execute("UPDATE users SET status='disabled' WHERE id=?", (user_id,))
    conn.commit()

    with pytest.raises(ApiError) as exc:
        auth_service.authenticate_user(conn, email="disabled@example.com", password="correct-password")
    assert exc.value.status_code == 401


def test_session_stores_only_hashes_not_raw_tokens(conn) -> None:
    user_id = auth_service.register_user(
        conn, email="s@example.com", password="correct-password", first_name="A", last_name="B"
    )
    issued = auth_service.create_session(conn, user_id=user_id, settings=Settings())
    row = users_repo.get_session_by_token_hash(conn, auth_service.hash_token(issued.raw_token))
    assert row is not None
    assert row["token_hash"] != issued.raw_token
    assert row["csrf_token_hash"] != issued.raw_csrf_token
    stored_values = [row["token_hash"], row["csrf_token_hash"]]
    assert issued.raw_token not in stored_values
    assert issued.raw_csrf_token not in stored_values


def test_resolve_session_principal_valid_session(conn) -> None:
    user_id = auth_service.register_user(
        conn, email="p@example.com", password="correct-password", first_name="A", last_name="B"
    )
    issued = auth_service.create_session(conn, user_id=user_id, settings=Settings())
    principal = auth_service.resolve_session_principal(conn, issued.raw_token)
    assert principal is not None
    assert principal.user_id == user_id


def test_resolve_session_principal_rejects_unknown_token(conn) -> None:
    assert auth_service.resolve_session_principal(conn, "not-a-real-token") is None


def test_resolve_session_principal_rejects_revoked_session(conn) -> None:
    user_id = auth_service.register_user(
        conn, email="r@example.com", password="correct-password", first_name="A", last_name="B"
    )
    issued = auth_service.create_session(conn, user_id=user_id, settings=Settings())
    assert auth_service.revoke_session_by_token(conn, raw_token=issued.raw_token) is True
    assert auth_service.resolve_session_principal(conn, issued.raw_token) is None


def test_resolve_session_principal_rejects_expired_session(conn) -> None:
    user_id = auth_service.register_user(
        conn, email="e@example.com", password="correct-password", first_name="A", last_name="B"
    )
    issued = auth_service.create_session(
        conn, user_id=user_id, settings=Settings(session_ttl_seconds=-1)
    )
    assert auth_service.resolve_session_principal(conn, issued.raw_token) is None


def test_resolve_session_principal_rejects_disabled_user(conn) -> None:
    user_id = auth_service.register_user(
        conn, email="d2@example.com", password="correct-password", first_name="A", last_name="B"
    )
    issued = auth_service.create_session(conn, user_id=user_id, settings=Settings())
    conn.execute("UPDATE users SET status='disabled' WHERE id=?", (user_id,))
    conn.commit()
    assert auth_service.resolve_session_principal(conn, issued.raw_token) is None


def test_revoke_all_sessions_revokes_every_active_session(conn) -> None:
    user_id = auth_service.register_user(
        conn, email="multi@example.com", password="correct-password", first_name="A", last_name="B"
    )
    first = auth_service.create_session(conn, user_id=user_id, settings=Settings())
    second = auth_service.create_session(conn, user_id=user_id, settings=Settings())

    revoked_count = auth_service.revoke_all_sessions(conn, user_id=user_id)

    assert revoked_count == 2
    assert auth_service.resolve_session_principal(conn, first.raw_token) is None
    assert auth_service.resolve_session_principal(conn, second.raw_token) is None


def test_last_seen_at_is_throttled_to_60_seconds(conn) -> None:
    user_id = auth_service.register_user(
        conn, email="throttle@example.com", password="correct-password", first_name="A", last_name="B"
    )
    issued = auth_service.create_session(conn, user_id=user_id, settings=Settings())

    auth_service.resolve_session_principal(conn, issued.raw_token)
    row = users_repo.get_session_by_token_hash(conn, auth_service.hash_token(issued.raw_token))
    first_seen = row["last_seen_at"]
    assert first_seen is not None

    # Hemen tekrar çağrı: throttle nedeniyle last_seen_at değişmemeli.
    auth_service.resolve_session_principal(conn, issued.raw_token)
    row_again = users_repo.get_session_by_token_hash(conn, auth_service.hash_token(issued.raw_token))
    assert row_again["last_seen_at"] == first_seen

    # 60 saniyeden eski last_seen_at simüle edilirse bir sonraki çağrı günceller.
    stale_time = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    conn.execute(
        "UPDATE sessions SET last_seen_at = ? WHERE id = ?", (stale_time, row["id"])
    )
    conn.commit()
    auth_service.resolve_session_principal(conn, issued.raw_token)
    row_updated = users_repo.get_session_by_token_hash(conn, auth_service.hash_token(issued.raw_token))
    assert row_updated["last_seen_at"] != stale_time
