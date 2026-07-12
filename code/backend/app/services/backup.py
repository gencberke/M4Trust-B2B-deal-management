"""Consistent SQLite + encrypted-blob backup/restore helpers (Plan 09)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

_FORMAT_VERSION = 1
_MEANINGFUL_TABLES = (
    "schema_migrations",
    "transactions",
    "users",
    "contract_documents",
    "rule_set_versions",
    "evidence_records",
    "funding_units",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file())


def verify_backup(source: Path) -> dict:
    source = source.resolve()
    manifest_path = source / "manifest.json"
    db_path = source / "m4trust.sqlite3"
    if not manifest_path.is_file() or not db_path.is_file():
        raise ValueError("backup manifest veya database eksik")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format_version") != _FORMAT_VERSION:
        raise ValueError("backup format version desteklenmiyor")
    if _sha256(db_path) != manifest.get("database_sha256"):
        raise ValueError("backup database hash uyuşmuyor")
    for item in manifest.get("blobs", []):
        relative = Path(item["ref"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("backup blob reference güvenli değil")
        blob = source / "documents" / relative
        if not blob.is_file() or _sha256(blob) != item["sha256"]:
            raise ValueError("backup blob bütünlüğü doğrulanamadı")
    with closing(sqlite3.connect(db_path)) as conn:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("sqlite integrity_check başarısız")
        counts = {}
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table in _MEANINGFUL_TABLES:
            if table in tables:
                counts[table] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    return {"verified": True, "record_counts": counts, "blob_count": len(manifest.get("blobs", []))}


def create_backup(db_path: Path, storage_root: Path, destination: Path) -> dict:
    db_path = db_path.resolve()
    storage_root = storage_root.resolve()
    destination = destination.resolve()
    if not db_path.is_file():
        raise FileNotFoundError("runtime database bulunamadı")
    if destination.exists():
        raise FileExistsError("backup destination zaten var")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".m4trust-backup-", dir=destination.parent))
    try:
        backup_db = temp / "m4trust.sqlite3"
        (temp / "documents").mkdir()
        with closing(sqlite3.connect(db_path)) as source, closing(
            sqlite3.connect(backup_db)
        ) as target:
            source.backup(target)
        blobs = []
        for path in _safe_relative_files(storage_root):
            relative = path.relative_to(storage_root)
            target = temp / "documents" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            blobs.append({"ref": relative.as_posix(), "sha256": _sha256(target)})
        manifest = {
            "format_version": _FORMAT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "database_sha256": _sha256(backup_db),
            "blobs": blobs,
        }
        (temp / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8"
        )
        # Windows environments may deny directory rename. Publish the
        # manifest last as the completeness marker; verification rejects any
        # interrupted/partial directory fail-closed.
        destination.mkdir()
        shutil.copy2(backup_db, destination / "m4trust.sqlite3")
        shutil.copytree(temp / "documents", destination / "documents")
        shutil.copy2(temp / "manifest.json", destination / "manifest.json")
        shutil.rmtree(temp)
        temp = None
        return verify_backup(destination)
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    finally:
        if temp is not None:
            shutil.rmtree(temp, ignore_errors=True)


def restore_backup(
    source: Path,
    target_db: Path,
    target_storage: Path,
) -> dict:
    source = source.resolve()
    target_db = target_db.resolve()
    target_storage = target_storage.resolve()
    verification = verify_backup(source)
    if target_db.exists() or target_storage.exists():
        raise FileExistsError("restore target mevcut; overwrite yasak")
    target_db.parent.mkdir(parents=True, exist_ok=True)
    target_storage.parent.mkdir(parents=True, exist_ok=True)
    tmp_db = target_db.with_name(f".{target_db.name}.tmp")
    tmp_storage = target_storage.with_name(f".{target_storage.name}.tmp")
    try:
        shutil.copy2(source / "m4trust.sqlite3", tmp_db)
        shutil.copytree(source / "documents", tmp_storage, dirs_exist_ok=False)
        os.replace(tmp_db, target_db)
        shutil.copytree(tmp_storage, target_storage)
        shutil.rmtree(tmp_storage)
    finally:
        tmp_db.unlink(missing_ok=True)
        if tmp_storage.exists():
            shutil.rmtree(tmp_storage, ignore_errors=True)
    return verification
