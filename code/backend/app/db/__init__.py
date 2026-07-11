"""Geriye uyumlu SQLite API yüzeyi."""

from .connection import connect, get_db, open_background_connection
from .migrate import UnknownLegacySchemaError, init_db, run_migrations
from .tx import transaction

__all__ = [
    "UnknownLegacySchemaError",
    "connect",
    "get_db",
    "init_db",
    "open_background_connection",
    "run_migrations",
    "transaction",
]
