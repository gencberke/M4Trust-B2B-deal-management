"""Additive OCR/RAG/LLM/analyzer provenance columns (Plan 09 / 9B)."""

from __future__ import annotations

import sqlite3

VERSION = "022"
NAME = "extraction_provenance_extensions"

STATEMENTS = (
    "ALTER TABLE extraction_runs ADD COLUMN ocr_engine TEXT",
    "ALTER TABLE extraction_runs ADD COLUMN ocr_version TEXT",
    "ALTER TABLE extraction_runs ADD COLUMN ocr_confidence REAL CHECK (ocr_confidence IS NULL OR (ocr_confidence >= 0 AND ocr_confidence <= 1))",
    "ALTER TABLE extraction_runs ADD COLUMN llm_provider_version TEXT",
    "ALTER TABLE extraction_runs ADD COLUMN rag_collection_versions_json TEXT NOT NULL DEFAULT '{}'",
    "ALTER TABLE extraction_runs ADD COLUMN source_locator_json TEXT NOT NULL DEFAULT '{}'",
    "ALTER TABLE evidence_records ADD COLUMN analyzer_model TEXT",
    "ALTER TABLE evidence_records ADD COLUMN analyzer_model_version TEXT",
)


def apply(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)
