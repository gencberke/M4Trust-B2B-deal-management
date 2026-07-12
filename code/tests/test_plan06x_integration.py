"""Plan 06X remediation gate'leri.

Milestone binding ve settlement video resolution'ını gerçek servis/HTTP
seam'leri üzerinden küçük, deterministik senaryolarla sabitler.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.repositories import milestones as milestones_repo
from backend.app.services import evidence_records, settlement
from reviews_fixtures import create_real_session, create_real_user
from test_settlement_funding_cutover import _actor, _seed_funded_account


def test_evidence_requires_milestone_when_multiple_candidates_exist(tmp_path) -> None:
    conn, transaction_id, package_id = _seed_funded_account(tmp_path, tx_id="tx-06x-binding")
    first = milestones_repo.list_for_transaction(conn, transaction_id)[0]
    conn.execute(
        "UPDATE milestones SET required_evidence_json = '[\"e_irsaliye\"]', "
        "trigger_type = 'e_invoice' WHERE id = ?",
        (first["id"],),
    )
    conn.execute(
        "INSERT INTO milestones ("
        "id, transaction_id, ratification_package_id, rule_set_version_id, rule_index, "
        "title, trigger_type, percentage_basis_points, amount_minor, currency, "
        "required_evidence_json, release_mode, status, released_amount_minor, created_at, updated_at"
        ") VALUES (?, ?, ?, ?, 1, 'İkinci teslim', 'e_invoice', 1, 1, 'TRY', ?, "
        "'all_or_nothing', 'pending', 0, 'now', 'now')",
        (
            "milestone-06x-2",
            transaction_id,
            package_id,
            first["rule_set_version_id"],
            json.dumps(["e_irsaliye"]),
        ),
    )
    with pytest.raises(evidence_records.EvidenceMilestoneError) as exc_info:
        evidence_records.submit_evidence(
            conn,
            transaction_id=transaction_id,
            milestone_id=None,
            evidence_type="e_irsaliye",
            source="external_api",
            actor_context=_actor("u-seller", "entity-seller"),
            payload={"delivered_quantity": 10},
            verification_status="verified",
            external_reference="06x-ambiguous",
        )
    assert exc_info.value.code == "EVIDENCE_MILESTONE_REQUIRED"
    conn.close()


def test_settlement_video_false_positive_resolves_through_real_app(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "6c.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    conn, transaction_id, _ = _seed_funded_account(tmp_path, tx_id="tx-06x-review")
    create_real_user(
        conn,
        email_normalized="06x-reviewer@example.com",
        user_id="u-06x-reviewer",
        platform_role="reviewer",
    )
    video = evidence_records.submit_evidence(
        conn,
        transaction_id=transaction_id,
        milestone_id=None,
        evidence_type="video",
        source="analyzer",
        actor_context=_actor("u-seller", "entity-seller"),
        payload={
            "counts": {},
            "unit_count": 10,
            "damage_signals": [
                {"type": "hasar_tespiti", "confidence": 0.95, "matched_box": True}
            ],
            "confidence": 0.95,
        },
        verification_status="review_required",
        external_reference="06x-video-damage",
        storage_ref="06x/video",
        file_sha256="c" * 64,
        analyzer_provider="fake",
        analyzer_version="v1",
    )
    conn.commit()
    first = settlement.evaluate_settlement(conn, transaction_id, Settings(db_path=db_path))
    assert first is not None and first["approved_unit_ids"] == []
    case = conn.execute(
        "SELECT id FROM review_cases WHERE transaction_id = ? AND source_type = 'video' "
        "AND phase = 'settlement' AND status = 'open'",
        (transaction_id,),
    ).fetchone()
    assert case is not None
    session = create_real_session(conn, user_id="u-06x-reviewer")
    conn.commit()
    conn.close()

    from backend.app.main import create_app

    with TestClient(create_app()) as client:
        client.cookies.set("m4t_session", session.raw_token)
        response = client.post(
            f"/api/reviews/{case['id']}/actions",
            json={
                "action": "resolve_continue",
                "resolution_code": "VIDEO_FALSE_POSITIVE",
            },
            headers={"X-CSRF-Token": session.raw_csrf_token},
        )
    assert response.status_code == 200, response.text

    # Re-open through the repository fixture helper's connection factory.
    from backend.app.db import connect

    checked = connect(Settings(db_path=db_path))
    try:
        assert checked.execute(
            "SELECT verification_status FROM evidence_records WHERE id = ?", (video.id,)
        ).fetchone()[0] == "rejected"
        assert checked.execute(
            "SELECT state FROM transactions WHERE id = ?", (transaction_id,)
        ).fetchone()[0] == "settled"
    finally:
        checked.close()
