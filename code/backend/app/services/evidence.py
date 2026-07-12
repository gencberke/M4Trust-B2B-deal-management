"""Güvenli evidence bundle ve explicit snapshot üretim seam'i.

Bundle'ın deterministik kısmı (`build_bundle_core`) yalnız kalıcı business
durumundan türetilir. `generated_at` response metadata'sıdır ve snapshot hash'i
hesabına girmez. Bu ayrım, read-only bundle GET'i ile insanın açıkça istediği
immutable snapshot yazımını birbirinden ayırır.

5A merge edilene kadar `evidence_records` tablosu bulunmayabilir. Bu modül
tabloyu yazmaz; varsa Yusuf'un first-class evidence kayıtlarını güvenli bir
projection olarak okur. Böylece 5C branch'i migration 013'e bağımlı olmadan
geliştirilebilir, closure'da aynı endpoint yeni tabloyu otomatik kullanır.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from sqlite3 import Connection, Row
from typing import Any

from backend.app.repositories import packages as packages_repo
from backend.app.repositories import ratifications as ratifications_repo
from backend.app.repositories import rule_sets as rule_sets_repo
from backend.app.services.extraction_projection import redacted_extraction_projection
from backend.app.services.tracking_policy import load_tracking_policy


_SENSITIVE_KEY_MARKERS = (
    "token",
    "password",
    "secret",
    "traceback",
    "stacktrace",
    "raw",
    "markdown",
    "storage_ref",
    "local_path",
    "filepath",
    "file_path",
    "privacy",
    "mapping",
    "response_body",
    "request_body",
    "user_agent",
    "ip_hash",
)
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?i)\bTR\s*[0-9]{2}(?:[\s-]*[0-9]){22}\b"),
    re.compile(r"(?i)\b[^\s@]+@[^\s@]+\.[^\s@]+\b"),
    re.compile(r"\b[0-9]{10,19}\b"),
)
_SAFE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_bundle_json(core: dict[str, Any]) -> str:
    """Deterministic UTF-8 JSON representation used by snapshot hashing."""

    return json.dumps(
        core,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def compute_snapshot_hash(core: dict[str, Any]) -> str:
    """SHA-256 of the deterministic bundle core only."""

    return hashlib.sha256(canonical_bundle_json(core).encode("utf-8")).hexdigest()


def _table_exists(conn: Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)
    ).fetchone()
    return row is not None


def _row_value(row: Row, *names: str) -> Any:
    keys = set(row.keys())
    for name in names:
        if name in keys:
            return row[name]
    return None


def _safe_reference(value: Any) -> str | None:
    """Keep only opaque reference-shaped values; suppress PII/free text."""

    if not isinstance(value, str) or not _SAFE_REFERENCE.fullmatch(value):
        return None
    if any(pattern.search(value) for pattern in _SENSITIVE_VALUE_PATTERNS):
        return None
    return value


def _safe_event_value(value: Any) -> Any:
    """Recursively project event payloads without secrets, raw content or PII."""

    if isinstance(value, dict):
        projected: dict[str, Any] = {}
        for key, nested in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in _SENSITIVE_KEY_MARKERS):
                continue
            safe_nested = _safe_event_value(nested)
            if safe_nested is not None:
                projected[str(key)] = safe_nested
        return projected
    if isinstance(value, list):
        return [_safe_event_value(item) for item in value]
    if isinstance(value, tuple):
        return [_safe_event_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and any(
            pattern.search(value) for pattern in _SENSITIVE_VALUE_PATTERNS
        ):
            return None
        return value
    return None


def _safe_event_payload(raw_payload: str | None) -> Any:
    if not raw_payload:
        return None
    try:
        payload = json.loads(raw_payload)
    except (TypeError, ValueError):
        return None
    return _safe_event_value(payload)


def _collect_events(conn: Connection, transaction_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, event_type, payload, source, created_at FROM events "
        "WHERE transaction_id = ? ORDER BY id ASC",
        (transaction_id,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "event_type": row["event_type"],
            "payload": _safe_event_payload(row["payload"]),
            "source": row["source"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _collect_evidence_records(conn: Connection, transaction_id: str) -> list[dict[str, Any]]:
    """5A kayıtlarının raw payload/path içermeyen stable projection'ı."""

    if not _table_exists(conn, "evidence_records"):
        return []

    rows = conn.execute(
        "SELECT * FROM evidence_records WHERE transaction_id = ? "
        "ORDER BY created_at ASC, id ASC",
        (transaction_id,),
    ).fetchall()
    records: list[dict[str, Any]] = []
    for row in rows:
        record: dict[str, Any] = {
            "id": _row_value(row, "id"),
            "evidence_type": _row_value(row, "evidence_type", "kind", "type"),
            "source": _row_value(row, "source"),
            "verification_status": _row_value(row, "verification_status", "status"),
            "submitted_by_entity_id": _safe_reference(
                _row_value(row, "submitted_by_entity_id", "entity_id", "acting_entity_id")
            ),
            "submitted_by_role": _safe_reference(
                _row_value(row, "submitted_by_role", "actor_role", "role")
            ),
            "external_reference": _safe_reference(
                _row_value(row, "external_reference", "external_ref")
            ),
            "file_sha256": _safe_reference(_row_value(row, "file_sha256")),
            "analyzer_provider": _safe_reference(
                _row_value(row, "analyzer_provider", "provider")
            ),
            "analyzer_version": _safe_reference(
                _row_value(row, "analyzer_version", "provider_version", "version")
            ),
            "created_at": _row_value(row, "created_at"),
            "verified_at": _row_value(row, "verified_at"),
            "milestone_id": _safe_reference(_row_value(row, "milestone_id")),
        }
        records.append(record)
    return records


def _collect_ratification_package(
    conn: Connection, transaction_id: str
) -> dict[str, Any] | None:
    """Current package + yalnız buyer/seller ratification durum özeti."""

    if not _table_exists(conn, "ratification_packages"):
        return None
    package = packages_repo.get_current(conn, transaction_id)
    if package is None:
        return None

    ratified_roles: dict[str, dict[str, Any]] = {
        "buyer": {"ratified": False, "approved_at": None},
        "seller": {"ratified": False, "approved_at": None},
    }
    if _table_exists(conn, "ratifications"):
        for row in ratifications_repo.list_by_package(conn, package["id"]):
            role = row["participant_role"]
            if role in ratified_roles:
                ratified_roles[role] = {
                    "ratified": True,
                    "approved_at": row["approved_at"],
                }

    return {
        "id": package["id"],
        "version": package["version"],
        "status": package["status"],
        "package_hash": package["package_hash"],
        "created_at": package["created_at"],
        "opened_at": package["opened_at"],
        "completed_at": package["completed_at"],
        "ratifications": ratified_roles,
    }


def _collect_payments(conn: Connection, transaction_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT other_trx_code, virtual_pos_order_id, status, amount, created_at "
        "FROM mock_payments WHERE transaction_id = ? ORDER BY created_at ASC, rowid ASC",
        (transaction_id,),
    ).fetchall()
    return [
        {
            "other_trx_code": row["other_trx_code"],
            "virtual_pos_order_id": row["virtual_pos_order_id"],
            "status": row["status"],
            "amount": row["amount"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _collect_approvals(conn: Connection, transaction_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT party, created_at FROM approvals WHERE transaction_id = ? "
        "ORDER BY created_at ASC, party ASC",
        (transaction_id,),
    ).fetchall()
    return [{"party": row["party"], "created_at": row["created_at"]} for row in rows]


def build_bundle_core(
    conn: Connection, transaction_id: str, *, include_source_quote: bool = False
) -> dict[str, Any]:
    """Build the stable, side-effect-free canonical bundle core."""

    tx_row = conn.execute(
        "SELECT id, state, created_at FROM transactions WHERE id = ?", (transaction_id,)
    ).fetchone()
    transaction_summary = (
        {"id": tx_row["id"], "state": tx_row["state"], "created_at": tx_row["created_at"]}
        if tx_row is not None
        else None
    )

    current_rules = rule_sets_repo.get_current(conn, transaction_id)
    extraction = None
    validator_report = None
    if current_rules is not None:
        if current_rules.extraction is not None:
            extraction = redacted_extraction_projection(
                current_rules.extraction.model_dump(mode="json"),
                include_source_quote=include_source_quote,
            )
        validator_report = {
            "status": current_rules.validator_status,
            "findings": current_rules.validator_report,
        }

    events = _collect_events(conn, transaction_id)
    decision = None
    for event in reversed(events):
        if event["event_type"] == "payment_decision_created":
            decision = event["payload"]
            break

    tracking_policy = load_tracking_policy(conn, transaction_id)
    return {
        "transaction": transaction_summary,
        "extraction": extraction,
        "validator_report": validator_report,
        "tracking_policy": tracking_policy.model_dump(mode="json") if tracking_policy else None,
        "approvals": _collect_approvals(conn, transaction_id),
        "events": events,
        "payments": _collect_payments(conn, transaction_id),
        "evidence_records": _collect_evidence_records(conn, transaction_id),
        "ratification_package": _collect_ratification_package(conn, transaction_id),
        "decision": decision,
    }


def build_bundle(
    conn: Connection, transaction_id: str, *, include_source_quote: bool = False
) -> dict[str, Any]:
    """Return safe bundle + snapshot hash + volatile response timestamp.

    Bu fonksiyon salt-okunurdur: evidence/events/audit veya başka business
    tablosuna INSERT/UPDATE yapmaz ve commit çağırmaz.
    """

    core = build_bundle_core(
        conn, transaction_id, include_source_quote=include_source_quote
    )
    return {
        **core,
        "snapshot_hash": compute_snapshot_hash(core),
        "generated_at": _utc_now_iso(),
    }


def find_snapshot_by_hash(
    conn: Connection, transaction_id: str, snapshot_hash: str
) -> dict[str, Any] | None:
    """Find an explicit snapshot already persisted in the legacy evidence table."""

    rows = conn.execute(
        "SELECT bundle_json FROM evidence WHERE transaction_id = ? ORDER BY rowid ASC",
        (transaction_id,),
    ).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["bundle_json"])
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict) and payload.get("snapshot_hash") == snapshot_hash:
            return payload
    return None


def persist_snapshot(
    conn: Connection,
    transaction_id: str,
    *,
    bundle: dict[str, Any],
) -> tuple[str, dict[str, Any], bool]:
    """Persist or replay one immutable canonical snapshot.

    Caller must hold the request-scoped ``BEGIN IMMEDIATE`` transaction. This
    helper deliberately does not commit; the DB dependency owns the boundary.
    """

    core = {key: value for key, value in bundle.items() if key not in {"generated_at", "snapshot_hash"}}
    snapshot_hash = compute_snapshot_hash(core)
    existing = find_snapshot_by_hash(conn, transaction_id, snapshot_hash)
    if existing is not None:
        return snapshot_hash, existing, False

    stored_bundle = {
        **core,
        "snapshot_hash": snapshot_hash,
        "generated_at": bundle.get("generated_at") or _utc_now_iso(),
    }
    conn.execute(
        "INSERT INTO evidence (transaction_id, bundle_json, created_at) VALUES (?, ?, ?)",
        (
            transaction_id,
            json.dumps(stored_bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            stored_bundle["generated_at"],
        ),
    )
    return snapshot_hash, stored_bundle, True
