"""SQLite bağlantı üretimi ve request/background yaşam döngüsü."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from backend.app.config import Settings


def connect(settings: Settings | None = None) -> sqlite3.Connection:
    settings = settings or Settings.from_env()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(settings.db_path), check_same_thread=False, timeout=5.0
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def open_background_connection(settings: Settings | None = None) -> sqlite3.Connection:
    """Background task sahibine ait, request connection'ından bağımsız bağlantı."""
    return connect(settings)


def get_db() -> Iterator[sqlite3.Connection]:
    """Başarıda commit, hatada açık rollback ve her durumda close uygular."""
    conn = connect()
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()
    finally:
        conn.close()
