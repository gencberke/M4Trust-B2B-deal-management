"""Explicit pre-Plan-09 encrypted-storage migration CLI."""

from __future__ import annotations

import argparse
import json

from backend.app.config import Settings
from backend.app.db import connect, init_db
from backend.app.services.document_storage import LocalDocumentStorageProvider
from backend.app.services.storage_migration import migrate_storage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Encrypt legacy M4Trust document storage")
    parser.add_argument("--execute", action="store_true", help="default is dry-run")
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    conn = connect()
    try:
        init_db(conn)
        result = migrate_storage(
            conn,
            LocalDocumentStorageProvider(
                root=settings.document_storage_dir,
                encryption_key=settings.app_encryption_key,
            ),
            dry_run=not args.execute,
        )
        if args.execute:
            conn.commit()
        print(json.dumps(result.as_safe_dict(), sort_keys=True))
        return 0
    except Exception:
        conn.rollback()
        print(json.dumps({"error": "STORAGE_MIGRATION_FAILED"}, sort_keys=True))
        return 4
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
