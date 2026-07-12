"""Narrow, assignment-safe milestone and funding-unit read projection."""

from __future__ import annotations

import json
from sqlite3 import Connection

from backend.app.repositories import milestones as milestones_repo
from backend.app.repositories import packages as packages_repo
from backend.app.schemas.projections import (
    FundingUnitProjection,
    MilestoneFundingProjection,
    MilestoneProjection,
)

_ELIGIBILITY_KEYS = frozenset(
    {"rule_index", "milestone_title", "tranche_index", "tranche_count"}
)


def _safe_eligibility_payload(raw: str | None) -> dict[str, str | int | bool | None]:
    try:
        payload = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    projected: dict[str, str | int | bool | None] = {}
    for key, value in payload.items():
        if key not in _ELIGIBILITY_KEYS:
            continue
        if isinstance(value, (str, int, bool)) or value is None:
            projected[key] = value
    return projected


def project_transaction_milestones(
    conn: Connection, transaction_id: str
) -> MilestoneFundingProjection:
    package = packages_repo.get_current(conn, transaction_id)
    if package is None:
        return MilestoneFundingProjection(
            transaction_id=transaction_id,
            package_id=None,
            milestones=[],
        )

    milestones: list[MilestoneProjection] = []
    for milestone in milestones_repo.list_for_package(conn, package["id"]):
        required_evidence = json.loads(milestone["required_evidence_json"] or "[]")
        if not isinstance(required_evidence, list):
            required_evidence = []
        units = conn.execute(
            "SELECT fu.*, ri.id AS release_instruction_id, "
            "ri.status AS release_instruction_status "
            "FROM funding_units fu LEFT JOIN release_instructions ri "
            "ON ri.funding_unit_id = fu.id AND ri.operation_type = 'approve_pool_payment' "
            "WHERE fu.milestone_id = ? ORDER BY fu.sequence ASC, fu.id ASC",
            (milestone["id"],),
        ).fetchall()
        unit_projection = [
            FundingUnitProjection(
                id=unit["id"],
                transaction_id=unit["transaction_id"],
                milestone_id=unit["milestone_id"],
                sequence=unit["sequence"],
                title=unit["title"],
                amount_minor=unit["amount_minor"],
                currency=unit["currency"],
                eligibility_type=unit["eligibility_type"],
                eligibility_payload=_safe_eligibility_payload(
                    unit["eligibility_payload_json"]
                ),
                status=unit["status"],
                release_instruction_id=unit["release_instruction_id"],
                release_instruction_status=unit["release_instruction_status"],
            )
            for unit in units
        ]
        milestones.append(
            MilestoneProjection(
                id=milestone["id"],
                transaction_id=milestone["transaction_id"],
                rule_set_version_id=milestone["rule_set_version_id"],
                rule_index=milestone["rule_index"],
                title=milestone["title"],
                trigger_type=milestone["trigger_type"],
                percentage_basis_points=milestone["percentage_basis_points"],
                amount_minor=milestone["amount_minor"],
                currency=milestone["currency"],
                required_evidence=[
                    value for value in required_evidence if isinstance(value, str)
                ],
                release_mode=milestone["release_mode"],
                status=milestone["status"],
                released_amount_minor=milestone["released_amount_minor"],
                created_at=milestone["created_at"],
                updated_at=milestone["updated_at"],
                funding_units=unit_projection,
            )
        )

    return MilestoneFundingProjection(
        transaction_id=transaction_id,
        package_id=package["id"],
        milestones=milestones,
    )
