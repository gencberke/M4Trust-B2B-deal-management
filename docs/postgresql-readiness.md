# PostgreSQL readiness inventory (no migration performed)

The current runtime is single-worker SQLite with WAL. This document is an inventory, not authorization to migrate.

## SQLite-specific seams

- `backend/app/db/__init__.py`: `PRAGMA foreign_keys`, WAL, `busy_timeout`, `sqlite3.Row`, `BEGIN IMMEDIATE` and file-path connection ownership.
- Migrations use `PRAGMA table_info`, `sqlite_master`, partial indexes, triggers, `ALTER TABLE ... RENAME`, table rebuild/copy and `INSERT OR IGNORE`.
- Repositories use `?` placeholders, SQLite date functions, `last_insert_rowid` assumptions and transaction-level compare-and-set updates.
- Backup uses `sqlite3.Connection.backup`; PostgreSQL requires provider-native logical/physical backup and point-in-time recovery.
- In-process FastAPI background tasks and the SQLite `processing_jobs` table are not a production worker queue.

## Required migration work

1. Introduce a database adapter/connection pool and preserve request-scoped short transactions. Never hold a database transaction open across Moka, LLM, OCR or analyzer network calls.
2. Replace SQLite migration branches with dialect-specific, transactional PostgreSQL migrations and explicit lock/statement timeouts.
3. Convert exactly-once provider orchestration to an outbox/worker model. Atomically commit domain state + outbox, then claim work with `FOR UPDATE SKIP LOCKED`; keep stable idempotency keys.
4. Revalidate partial unique indexes, immutable triggers, CAS row-count semantics, JSON storage, decimal/minor-unit types and timestamp timezone behavior.
5. Add/verify indexes on every referencing/lookup column, especially `transaction_assignments(transaction_id,user_id,legal_entity_id,status)`, `review_cases(transaction_id,status,severity)`, `funding_units(transaction_id,status)`, `release_instructions(funding_unit_id,status)`, `processing_jobs(status,locked_at)` and token-hash lookups.
6. Load-test pool sizing, deadlocks, serialization/retry policy and multi-worker startup recovery. A timeout remains unknown, never definite failure.

## Release gate

Do not claim PostgreSQL readiness until schema parity, migration-from-production-copy, concurrent payment fault tests, backup/PITR restore, connection-pool saturation and rollback drills pass in a staging environment.
