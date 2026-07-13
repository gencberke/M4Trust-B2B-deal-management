"""CLI wrapper for verified SQLite + encrypted document backup/restore."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.app.config import Settings
from backend.app.services.backup import create_backup, restore_backup, verify_backup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M4Trust backup/restore")
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup")
    backup.add_argument("destination", type=Path)
    restore = sub.add_parser("restore")
    restore.add_argument("source", type=Path)
    restore.add_argument("--target-db", type=Path, required=True)
    restore.add_argument("--target-storage", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("source", type=Path)
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
        if args.command == "backup":
            result = create_backup(settings.db_path, settings.document_storage_dir, args.destination)
        elif args.command == "restore":
            result = restore_backup(args.source, args.target_db, args.target_storage)
        else:
            result = verify_backup(args.source)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print(json.dumps({"error": "BACKUP_OPERATION_FAILED"}, sort_keys=True))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
