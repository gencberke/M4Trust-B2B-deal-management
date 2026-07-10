"""Evidence router — kanıt demeti üretir + `evidence` tablosuna snapshot yazar (§4.1, Faz 4B)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from backend.app.config import Settings
from backend.app.db import connect
from backend.app.routers.transactions import load_transaction
from backend.app.services.evidence import build_bundle

router = APIRouter(prefix="/api/transactions", tags=["evidence"])


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/{transaction_id}/evidence")
def get_evidence(transaction_id: str) -> dict:
    settings = Settings.from_env()
    conn = connect(settings)
    try:
        row = load_transaction(conn, transaction_id)
        if row is None:
            raise HTTPException(status_code=404, detail="İşlem bulunamadı.")

        bundle = build_bundle(conn, transaction_id)

        conn.execute(
            "INSERT INTO evidence (transaction_id, bundle_json, created_at) VALUES (?, ?, ?)",
            (transaction_id, json.dumps(bundle, ensure_ascii=False), _utc_now_iso()),
        )
        conn.commit()

        return bundle
    finally:
        conn.close()
