"""CLI for Plan 09 retention cleanup; stdout is PII-free JSON only."""

from __future__ import annotations

import argparse
import json

from backend.app.config import Settings
from backend.app.db import connect, init_db
from backend.app.services.document_storage import make_document_storage_provider
from backend.app.services.retention import cleanup_transactions, select_transaction_ids


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="M4Trust raw document retention cleanup")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--transaction-id")
    scope.add_argument("--older-than-days", type=int)
    parser.add_argument("--execute", action="store_true", help="default is dry-run")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = Settings.from_env()
    conn = connect()
    try:
        init_db(conn)
        ids = select_transaction_ids(
            conn,
            transaction_id=args.transaction_id,
            older_than_days=args.older_than_days,
        )
        result = cleanup_transactions(
            conn,
            make_document_storage_provider(settings),
            ids,
            dry_run=not args.execute,
        )
        if args.execute:
            conn.commit()
        print(json.dumps(result.as_safe_dict(), sort_keys=True))
        return 3 if result.skipped_active else 0
    except ValueError as exc:
        conn.rollback()
        print(json.dumps({"error": "INVALID_SCOPE", "message": str(exc)}, sort_keys=True))
        return 2
    except Exception:
        conn.rollback()
        print(json.dumps({"error": "RETENTION_FAILED"}, sort_keys=True))
        return 4
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
