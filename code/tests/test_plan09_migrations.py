"""Clean and latest-pre-Plan-09 additive migration verification."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.app.db import init_db
from backend.app.db import migrate as migrate_module


_PLAN09 = {"019", "020", "021", "022", "025"}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}


def test_latest_pre_plan09_database_upgrades_without_data_loss(tmp_path: Path) -> None:
    path = tmp_path / "pre09.sqlite"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "CREATE TABLE schema_migrations (version TEXT PRIMARY KEY,name TEXT NOT NULL,applied_at TEXT NOT NULL)"
    )
    for migration in migrate_module._migrations():
        if migration.version in _PLAN09:
            continue
        migration.module.apply(conn)
        conn.execute(
            "INSERT INTO schema_migrations(version,name,applied_at) VALUES (?,?,?)",
            (migration.version, migration.name, "pre09"),
        )
    conn.execute(
        "INSERT INTO users(id,email_normalized,password_hash,first_name,last_name,status,created_at,updated_at) "
        "VALUES ('user-pre09','pre09@example.com','hash','Pre','Nine','active','now','now')"
    )
    conn.execute(
        "INSERT INTO transactions(id,state,markdown,masked_markdown,created_at,lifecycle_version) "
        "VALUES ('tx-pre09','active','legacy markdown','masked','now','account_v2')"
    )
    conn.commit()

    init_db(conn)
    init_db(conn)

    assert conn.execute(
        "SELECT markdown FROM transactions WHERE id='tx-pre09'"
    ).fetchone()[0] == "legacy markdown"
    assert conn.execute(
        "SELECT email_normalized FROM users WHERE id='user-pre09'"
    ).fetchone()[0] == "pre09@example.com"
    assert {"failed_login_count", "locked_until"} <= _columns(conn, "users")
    assert {"markdown_storage_ref", "markdown_deleted_at"} <= _columns(
        conn, "transactions"
    )
    assert {"ocr_engine", "ocr_confidence", "llm_provider_version"} <= _columns(
        conn, "extraction_runs"
    )
    assert {"analyzer_model", "analyzer_model_version"} <= _columns(
        conn, "evidence_records"
    )
    assert {
        row[0]
        for row in conn.execute(
            "SELECT version FROM schema_migrations WHERE version IN ('019','020','021','022','025')"
        )
    } == _PLAN09
    conn.close()
