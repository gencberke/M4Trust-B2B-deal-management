"""Migration `003_identity_sessions` + `004_legal_entities_memberships` testleri."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.db import connect, init_db


def _settings(path: Path) -> Settings:
    return Settings(db_path=path)


def test_requirements_core_declares_identity_dependencies_without_heavy_profiles() -> None:
    root = Path(__file__).parents[1]
    core = (root / "requirements-core.txt").read_text().lower()
    ci = (root / "requirements-ci.txt").read_text().lower()
    assert "argon2-cffi" in core
    assert "cryptography" in core
    # CI, core'u `-r requirements-core.txt` ile alır — ağır RAG/video profilleri kurulmaz.
    combined = (ci + core).lower()
    for heavy in ("chromadb", "flagembedding", "torch", "opencv"):
        assert heavy not in combined


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def test_003_and_004_tables_present_after_empty_db_migration(tmp_path: Path) -> None:
    conn = connect(_settings(tmp_path / "empty.db"))
    init_db(conn)

    assert {"users", "sessions", "legal_entities", "memberships"} <= _tables(conn)
    assert {row[1] for row in conn.execute("PRAGMA table_info(users)")} == {
        "id",
        "email_normalized",
        "password_hash",
        "first_name",
        "last_name",
        "phone_ciphertext",
        "status",
        "platform_role",
        "email_verified_at",
        "created_at",
        "updated_at",
    }
    assert {row[1] for row in conn.execute("PRAGMA table_info(sessions)")} == {
        "id",
        "user_id",
        "token_hash",
        "csrf_token_hash",
        "expires_at",
        "revoked_at",
        "created_at",
        "last_seen_at",
    }
    conn.close()


def test_migration_is_idempotent_across_repeated_runs(tmp_path: Path) -> None:
    conn = connect(_settings(tmp_path / "repeat.db"))
    init_db(conn)
    init_db(conn)
    init_db(conn)
    versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
    assert versions == ["001", "003", "004", "005", "006", "007", "008", "009", "010", "011", "012", "013", "014", "015", "016", "017", "018", "023", "024"]
    conn.close()


def test_existing_001_only_db_upgrades_additively_with_003_and_004(tmp_path: Path) -> None:
    from backend.app.db.migrations import baseline_current_schema

    conn = connect(_settings(tmp_path / "legacy_001.db"))
    baseline_current_schema.apply(conn)
    conn.execute("INSERT INTO transactions (id, state) VALUES ('kept', 'uploaded')")
    conn.commit()

    init_db(conn)

    assert conn.execute("SELECT state FROM transactions WHERE id='kept'").fetchone()[0] == "uploaded"
    assert {"users", "sessions", "legal_entities", "memberships"} <= _tables(conn)
    conn.close()


def test_users_email_normalized_is_unique(tmp_path: Path) -> None:
    conn = connect(_settings(tmp_path / "unique_email.db"))
    init_db(conn)
    conn.execute(
        "INSERT INTO users (id, email_normalized, password_hash, first_name, last_name, "
        "created_at, updated_at) VALUES ('u1', 'a@b.com', 'h', 'A', 'B', 't', 't')"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO users (id, email_normalized, password_hash, first_name, last_name, "
            "created_at, updated_at) VALUES ('u2', 'a@b.com', 'h', 'A', 'B', 't', 't')"
        )
    conn.close()


def test_sessions_token_hash_is_unique(tmp_path: Path) -> None:
    conn = connect(_settings(tmp_path / "unique_token.db"))
    init_db(conn)
    conn.execute(
        "INSERT INTO users (id, email_normalized, password_hash, first_name, last_name, "
        "created_at, updated_at) VALUES ('u1', 'a@b.com', 'h', 'A', 'B', 't', 't')"
    )
    conn.execute(
        "INSERT INTO sessions (id, user_id, token_hash, csrf_token_hash, expires_at, created_at) "
        "VALUES ('s1', 'u1', 'tok', 'csrf', 'exp', 't')"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO sessions (id, user_id, token_hash, csrf_token_hash, expires_at, created_at) "
            "VALUES ('s2', 'u1', 'tok', 'csrf2', 'exp', 't')"
        )
    conn.close()


def test_sessions_cascade_delete_with_user(tmp_path: Path) -> None:
    conn = connect(_settings(tmp_path / "cascade.db"))
    init_db(conn)
    conn.execute(
        "INSERT INTO users (id, email_normalized, password_hash, first_name, last_name, "
        "created_at, updated_at) VALUES ('u1', 'a@b.com', 'h', 'A', 'B', 't', 't')"
    )
    conn.execute(
        "INSERT INTO sessions (id, user_id, token_hash, csrf_token_hash, expires_at, created_at) "
        "VALUES ('s1', 'u1', 'tok', 'csrf', 'exp', 't')"
    )
    conn.commit()
    conn.execute("DELETE FROM users WHERE id='u1'")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    conn.close()


def test_memberships_user_entity_pair_is_unique(tmp_path: Path) -> None:
    conn = connect(_settings(tmp_path / "unique_membership.db"))
    init_db(conn)
    conn.execute(
        "INSERT INTO users (id, email_normalized, password_hash, first_name, last_name, "
        "created_at, updated_at) VALUES ('u1', 'a@b.com', 'h', 'A', 'B', 't', 't')"
    )
    conn.execute(
        "INSERT INTO legal_entities (id, entity_type, legal_name, tax_identifier_type, "
        "tax_identifier_ciphertext, tax_identifier_lookup_hmac, tax_identifier_last4, "
        "verification_status, created_by_user_id, created_at, updated_at) "
        "VALUES ('e1', 'company', 'ABC', 'vkn', 'c', 'h', '1234', 'self_declared', 'u1', 't', 't')"
    )
    conn.execute(
        "INSERT INTO memberships (id, user_id, legal_entity_id, role, status, created_at) "
        "VALUES ('m1', 'u1', 'e1', 'owner', 'active', 't')"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO memberships (id, user_id, legal_entity_id, role, status, created_at) "
            "VALUES ('m2', 'u1', 'e1', 'admin', 'active', 't')"
        )
    conn.close()
