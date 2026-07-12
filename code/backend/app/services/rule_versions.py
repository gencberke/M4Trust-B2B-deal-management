"""Immutable rule-set version service and deterministic validation seam."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from sqlite3 import Connection, Row
from uuid import uuid4

from backend.app.repositories import rule_sets as rule_sets_repo
from backend.app.schemas.extraction import ExtractionJSON
from backend.app.schemas.rule_sets import CurrentRuleSet, RuleSetVersion
from backend.app.services.access_control import ActorContext
from backend.app.services.validator import validate


class RuleSetVersionNotFoundError(Exception):
    """Expected rule-set version row is missing."""


class RuleRevisionPayloadError(ValueError):
    """Revision payload parent quote reconstruction failed safely."""


def canonical_rules_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_rules_hash(canonical_json: str) -> str:
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_rule_set_version(row: Row) -> RuleSetVersion:
    validator_report = row["validator_report_json"]
    if validator_report:
        validator_report = json.loads(validator_report)
    return RuleSetVersion(
        id=row["id"],
        transaction_id=row["transaction_id"],
        version=row["version"],
        parent_version_id=row["parent_version_id"],
        source_extraction_run_id=row["source_extraction_run_id"],
        extraction=ExtractionJSON.model_validate(json.loads(row["rules_json"])),
        rules_hash=row["rules_hash"],
        validator_status=row["validator_status"],
        validator_report=validator_report,
        status=row["status"],
        created_by_user_id=row["created_by_user_id"],
        created_by_actor_type=row["created_by_actor_type"],
        created_at=row["created_at"],
    )


def _get_or_raise(conn: Connection, version_id: str) -> Row:
    row = rule_sets_repo.get_by_id(conn, version_id)
    if row is None:
        raise RuleSetVersionNotFoundError(version_id)
    return row


def create_initial_from_extraction(
    conn: Connection,
    *,
    transaction_id: str,
    extraction_run_id: str,
    rules_payload: dict,
    created_by_actor_type: str = "system",
    created_by_user_id: str | None = None,
) -> RuleSetVersion:
    extraction = ExtractionJSON.model_validate(rules_payload)
    canonical = canonical_rules_json(extraction.model_dump(mode="json"))
    rules_hash = compute_rules_hash(canonical)
    version_id = uuid4().hex
    now = _utc_now_iso()

    rule_sets_repo.insert_rule_set_version(
        conn,
        version_id=version_id,
        transaction_id=transaction_id,
        version=1,
        parent_version_id=None,
        source_extraction_run_id=extraction_run_id,
        rules_json=canonical,
        rules_hash=rules_hash,
        status="draft",
        created_by_user_id=created_by_user_id,
        created_by_actor_type=created_by_actor_type,
        now=now,
    )
    return _row_to_rule_set_version(_get_or_raise(conn, version_id))


def _reconstruct_revision_extraction(
    conn: Connection, *, parent_version_id: str, rules_payload: dict
) -> ExtractionJSON:
    """Merge omitted quotes from the current parent, then validate all fields."""

    parent = _get_or_raise(conn, parent_version_id)
    parent_extraction = ExtractionJSON.model_validate(json.loads(parent["rules_json"]))
    reconstructed_payload = dict(rules_payload)
    submitted_rules = reconstructed_payload.get("payment_rules")
    if not isinstance(submitted_rules, list):
        raise RuleRevisionPayloadError("payment_rules revision payload must be a list.")

    merged_rules: list[dict] = []
    for index, submitted_rule in enumerate(submitted_rules):
        if not isinstance(submitted_rule, dict):
            raise RuleRevisionPayloadError(f"payment_rules[{index}] must be an object.")
        rule = dict(submitted_rule)
        if rule.get("source_quote") is None:
            if index >= len(parent_extraction.payment_rules):
                raise RuleRevisionPayloadError(
                    f"payment_rules[{index}].source_quote is required for a new rule index."
                )
            # Rule index is the validated identity used for safe quote merging.
            rule["source_quote"] = parent_extraction.payment_rules[index].source_quote
        merged_rules.append(rule)

    reconstructed_payload["payment_rules"] = merged_rules
    # The frozen ExtractionJSON is the final validation gate for immutable data.
    return ExtractionJSON.model_validate(reconstructed_payload)


def create_revision(
    conn: Connection,
    *,
    transaction_id: str,
    parent_version_id: str,
    rules_payload: dict,
    actor_context: ActorContext,
) -> RuleSetVersion:
    extraction = _reconstruct_revision_extraction(
        conn, parent_version_id=parent_version_id, rules_payload=rules_payload
    )
    canonical = canonical_rules_json(extraction.model_dump(mode="json"))
    rules_hash = compute_rules_hash(canonical)
    version_id = uuid4().hex
    next_version = rule_sets_repo.get_max_version(conn, transaction_id) + 1
    now = _utc_now_iso()

    rule_sets_repo.insert_rule_set_version(
        conn,
        version_id=version_id,
        transaction_id=transaction_id,
        version=next_version,
        parent_version_id=parent_version_id,
        source_extraction_run_id=None,
        rules_json=canonical,
        rules_hash=rules_hash,
        status="draft",
        created_by_user_id=actor_context.user_id,
        created_by_actor_type="user",
        now=now,
    )
    return _row_to_rule_set_version(_get_or_raise(conn, version_id))


def validate_version(
    conn: Connection, *, version_id: str, confidence_threshold: float
) -> RuleSetVersion:
    row = _get_or_raise(conn, version_id)
    extraction = ExtractionJSON.model_validate(json.loads(row["rules_json"]))
    report = validate(extraction, confidence_threshold=confidence_threshold)
    findings_payload = [
        {"code": f.code, "severity": f.severity, "message": f.message} for f in report.findings
    ]
    new_status = "ratifiable" if report.status == "PASS" else "validated"

    rule_sets_repo.update_validation(
        conn,
        version_id=version_id,
        status=new_status,
        validator_status=report.status,
        validator_report_json=json.dumps(findings_payload, ensure_ascii=False),
    )
    return _row_to_rule_set_version(_get_or_raise(conn, version_id))


def get_current(conn: Connection, transaction_id: str) -> CurrentRuleSet | None:
    row = rule_sets_repo.get_latest_non_superseded(conn, transaction_id)
    return None if row is None else rule_sets_repo.rule_set_version_row_to_current(row)


def list_versions(conn: Connection, transaction_id: str) -> list[RuleSetVersion]:
    return [_row_to_rule_set_version(row) for row in rule_sets_repo.list_for_transaction(conn, transaction_id)]


def supersede(conn: Connection, *, version_id: str, reason_code: str) -> RuleSetVersion:
    del reason_code
    _get_or_raise(conn, version_id)
    rule_sets_repo.mark_superseded(conn, version_id=version_id)
    return _row_to_rule_set_version(_get_or_raise(conn, version_id))
