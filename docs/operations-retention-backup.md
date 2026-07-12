# Retention, encrypted storage migration, backup and restore

All commands run from `code/` with the same `APP_ENCRYPTION_KEY`, `DB_PATH` and `DOCUMENT_STORAGE_DIR` as the target environment. Stop application writes or take a consistent maintenance window first.

## Retention

Retention is explicit and defaults to dry-run. Exactly one scope is required:

```powershell
.\.venv\Scripts\python.exe -m scripts.retention_cleanup --transaction-id <opaque-id>
.\.venv\Scripts\python.exe -m scripts.retention_cleanup --older-than-days 90
```

Review the PII-free counts, then add `--execute`. Only terminal transactions (`settled`, `decided`, `rejected`, `cancelled`) are eligible. The command deletes encrypted contract/evidence/markdown blobs, tolerates missing blobs, tombstones references, clears legacy plaintext markdown and is replay-safe. Do not manually delete storage directories because that bypasses reference consistency.

## Pre-Plan-09 storage migration

Normal runtime reads reject plaintext blobs. Preview and then execute the explicit migration:

```powershell
.\.venv\Scripts\python.exe -m scripts.migrate_document_storage
.\.venv\Scripts\python.exe -m scripts.migrate_document_storage --execute
```

The migration verifies stored SHA-256 values, encrypts legacy files atomically, moves plaintext markdown to encrypted references and is idempotent. Preserve a verified backup first.

## Backup and restore

```powershell
.\.venv\Scripts\python.exe -m scripts.backup_restore backup <backup-dir>
.\.venv\Scripts\python.exe -m scripts.backup_restore verify <backup-dir>
.\.venv\Scripts\python.exe -m scripts.backup_restore restore <backup-dir> --target-db <new-db> --target-storage <new-storage-dir>
```

The backup uses SQLite's online backup API, copies encrypted blobs and records SHA-256 hashes plus meaningful table counts in a manifest. Restore refuses to overwrite existing targets. After restore, run `verify`, start the app against the new paths, check `/health`, and read a known encrypted document using the original encryption key. Backups are encrypted only at the blob level; the SQLite file and manifest require separate encrypted-at-rest media and access control.

Rollback for migrations 019–025 is forward-fix/restore-from-backup only; destructive down migrations are intentionally not provided.
