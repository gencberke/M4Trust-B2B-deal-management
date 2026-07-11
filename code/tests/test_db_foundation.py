"""Plan 02A migration, connection lifecycle ve repository kontratları."""

from __future__ import annotations

import inspect
import sqlite3
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.app.config import Settings
from backend.app.db import (
    UnknownLegacySchemaError,
    connect,
    get_db,
    init_db,
    open_background_connection,
    transaction,
)
from backend.app.db import connection as connection_module
from backend.app.db.migrations import baseline_current_schema
from backend.app.repositories.transactions import (
    list_transaction_events,
    list_transaction_payments,
    list_transaction_rows,
    load_transaction,
)
from backend.app.services.access_control import (
    ActorContext,
    get_current_actor,
    require_active_membership,
    require_authenticated_user,
)


def _settings(path: Path) -> Settings:
    return Settings(db_path=path)


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def test_empty_db_applies_complete_baseline(tmp_path: Path) -> None:
    conn = connect(_settings(tmp_path / "empty.db"))
    init_db(conn)

    assert _tables(conn) == {
        "schema_migrations",
        "transactions",
        "extracted_rules",
        "approvals",
        "events",
        "mock_payments",
        "evidence",
        "tracking_policies",
        "users",
        "sessions",
        "legal_entities",
        "memberships",
        "transaction_participants",
        "transaction_assignments",
        "transaction_invitations",
        "audit_events",
        "contract_documents",
        "extraction_runs",
        "rule_set_versions",
    }
    assert [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")] == [
        "001",
        "003",
        "004",
        "005",
        "006",
        "007",
        "008",
        "009",
    ]
    assert "manager_token" in {
        row[1] for row in conn.execute("PRAGMA table_info(transactions)")
    }
    assert "lifecycle_version" in {
        row[1] for row in conn.execute("PRAGMA table_info(transactions)")
    }
    conn.close()


def test_recognized_legacy_is_stamped_without_reapplying(tmp_path: Path) -> None:
    conn = connect(_settings(tmp_path / "legacy.db"))
    baseline_current_schema.apply(conn)
    conn.execute(
        "INSERT INTO transactions (id, state) VALUES ('kept', 'uploaded')"
    )
    conn.commit()

    init_db(conn)

    # 001 stamp edilir (yeniden uygulanmaz); 003-009 henüz uygulanmadığından
    # normal döngüyle eklenir — additive legacy upgrade.
    assert [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")] == [
        "001",
        "003",
        "004",
        "005",
        "006",
        "007",
        "008",
        "009",
    ]
    kept_row = conn.execute(
        "SELECT state, lifecycle_version FROM transactions WHERE id='kept'"
    ).fetchone()
    assert kept_row["state"] == "uploaded"
    assert kept_row["lifecycle_version"] == "legacy_v1"
    assert "users" in _tables(conn)
    assert "legal_entities" in _tables(conn)
    assert "transaction_participants" in _tables(conn)
    conn.close()


def test_already_migrated_is_idempotent(tmp_path: Path) -> None:
    conn = connect(_settings(tmp_path / "migrated.db"))
    init_db(conn)
    first = conn.execute("SELECT * FROM schema_migrations").fetchall()
    init_db(conn)
    assert conn.execute("SELECT * FROM schema_migrations").fetchall() == first
    conn.close()


def test_unknown_schema_is_fail_closed_without_mutation(tmp_path: Path) -> None:
    conn = connect(_settings(tmp_path / "unknown.db"))
    conn.execute("CREATE TABLE foreign_table (value TEXT)")
    conn.execute("INSERT INTO foreign_table VALUES ('kept')")
    conn.commit()
    before = conn.execute(
        "SELECT type, name, sql FROM sqlite_master ORDER BY name"
    ).fetchall()

    with pytest.raises(UnknownLegacySchemaError):
        init_db(conn)

    assert conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name").fetchall() == before
    assert conn.execute("SELECT value FROM foreign_table").fetchone()[0] == "kept"
    assert "schema_migrations" not in _tables(conn)
    conn.close()


def test_interrupted_migration_rolls_back_and_is_safely_rerunnable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = connect(_settings(tmp_path / "interrupted.db"))
    original_apply = baseline_current_schema.apply

    def interrupted(target: sqlite3.Connection) -> None:
        target.execute("CREATE TABLE interrupted_artifact (id INTEGER)")
        raise RuntimeError("simulated interruption")

    monkeypatch.setattr(baseline_current_schema, "apply", interrupted)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        init_db(conn)
    assert "interrupted_artifact" not in _tables(conn)
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 0

    monkeypatch.setattr(baseline_current_schema, "apply", original_apply)
    init_db(conn)
    assert conn.execute("SELECT version FROM schema_migrations").fetchone()[0] == "001"
    conn.close()


class _TrackingConnection:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def test_get_db_commits_and_closes_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _TrackingConnection()
    monkeypatch.setattr(connection_module, "connect", lambda: fake)
    dependency = get_db()
    assert next(dependency) is fake
    with pytest.raises(StopIteration):
        next(dependency)
    assert fake.committed and fake.closed and not fake.rolled_back


def test_get_db_rolls_back_closes_and_reraises(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _TrackingConnection()
    monkeypatch.setattr(connection_module, "connect", lambda: fake)
    dependency = get_db()
    next(dependency)
    with pytest.raises(RuntimeError, match="request failed"):
        dependency.throw(RuntimeError("request failed"))
    assert fake.rolled_back and fake.closed and not fake.committed


def test_background_connections_have_independent_ownership(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "background.db")
    first = open_background_connection(settings)
    second = open_background_connection(settings)
    assert first is not second
    first.close()
    second.execute("SELECT 1")
    second.close()


def test_transaction_helper_commit_and_rollback(tmp_path: Path) -> None:
    conn = connect(_settings(tmp_path / "tx.db"))
    conn.execute("CREATE TABLE sample (value TEXT)")
    conn.commit()
    with transaction(conn, immediate=True):
        conn.execute("INSERT INTO sample VALUES ('committed')")
    with pytest.raises(ValueError):
        with transaction(conn):
            conn.execute("INSERT INTO sample VALUES ('rolled-back')")
            raise ValueError("nope")
    assert [row[0] for row in conn.execute("SELECT value FROM sample")] == ["committed"]
    conn.close()


def test_repository_load_list_and_detail_queries(tmp_path: Path) -> None:
    conn = connect(_settings(tmp_path / "repository.db"))
    init_db(conn)
    conn.execute("INSERT INTO transactions (id, state, created_at) VALUES ('t1', 'uploaded', '1')")
    conn.execute("INSERT INTO events (transaction_id, event_type) VALUES ('t1', 'created')")
    conn.execute("INSERT INTO mock_payments (transaction_id, status) VALUES ('t1', 'pool')")
    assert load_transaction(conn, "t1")["state"] == "uploaded"
    assert [row["id"] for row in list_transaction_rows(conn)] == ["t1"]
    assert list_transaction_events(conn, "t1")[0]["event_type"] == "created"
    assert list_transaction_payments(conn, "t1")[0]["status"] == "pool"
    conn.close()


def test_actor_context_is_immutable_and_public_signatures_are_frozen() -> None:
    actor = ActorContext(actor_type="anonymous", request_id="req-1")
    with pytest.raises(AttributeError):
        actor.user_id = "changed"  # type: ignore[misc]
    assert list(inspect.signature(get_current_actor).parameters) == ["request"]
    assert list(inspect.signature(require_authenticated_user).parameters) == ["actor"]
    assert list(inspect.signature(require_active_membership).parameters) == ["actor"]
    with pytest.raises(HTTPException) as exc:
        require_authenticated_user(actor)
    assert exc.value.status_code == 401


def test_requirements_ci_excludes_heavy_profiles() -> None:
    root = Path(__file__).parents[1]
    ci = (root / "requirements-ci.txt").read_text()
    core = (root / "requirements-core.txt").read_text().lower()
    combined = (ci + core).lower()
    assert "chromadb" not in combined
    assert "flagembedding" not in combined
    assert "torch" not in combined
    assert "opencv" not in combined
