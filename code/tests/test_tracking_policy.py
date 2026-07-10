"""Tracking policy Faz 1 için temel davranış testleri."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "m4trust_tracking_policy.db"))
    monkeypatch.setenv("LLM_PROVIDER", "fake")


@pytest.fixture()
def client():
    from backend.app.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_new_transaction_keeps_manager_token_out_of_events_and_creates_draft_policy(
    client: TestClient, tmp_path: Path
) -> None:
    contract_path = tmp_path / "sozlesme.md"
    contract_path.write_text("# Hizmet sözleşmesi", encoding="utf-8")
    with contract_path.open("rb") as contract_file:
        response = client.post(
            "/api/transactions",
            files={"file": ("sozlesme.md", contract_file, "text/markdown")},
        )

    assert response.status_code == 200
    created = response.json()
    assert created["manager_link"].startswith(f"/t/{created['id']}/manager?token=")

    manager_token = created["manager_link"].split("token=", 1)[1]
    import sqlite3

    with sqlite3.connect(tmp_path / "m4trust_tracking_policy.db") as conn:
        policy = conn.execute(
            "SELECT tracking_mode, video_role, status FROM tracking_policies "
            "WHERE transaction_id = ?",
            (created["id"],),
        ).fetchone()
        event_payloads = [
            row[0]
            for row in conn.execute(
                "SELECT payload FROM events WHERE transaction_id = ?", (created["id"],)
            )
        ]

    assert policy == ("off", "advisory", "draft")
    assert all(manager_token not in (payload or "") for payload in event_payloads)


@pytest.mark.parametrize(
    ("goods", "required_evidence", "expected_recommendation", "expected_reason"),
    [
        (
            [{"name": "Endüstriyel pompa", "quantity": 10, "unit": "adet"}],
            ["contract"],
            "yes",
            "PHYSICAL_UNIT",
        ),
        (
            [{"name": "Yazılım danışmanlığı", "quantity": 12, "unit": "saat"}],
            ["contract"],
            "no",
            "SERVICE_ONLY",
        ),
        ([], ["video"], "uncertain", "INSUFFICIENT_SIGNAL"),
        (
            [
                {"name": "Endüstriyel pompa", "quantity": 10, "unit": "adet"},
                {"name": "Kurulum danışmanlığı", "quantity": 8, "unit": "saat"},
            ],
            ["contract"],
            "uncertain",
            "CONFLICTING_SIGNALS",
        ),
        ([], ["e_irsaliye"], "yes", "CONTRACTUAL_E_IRSALIYE"),
    ],
)
def test_recommend_physical_delivery_returns_safe_deterministic_reason_codes(
    goods: list[dict],
    required_evidence: list[str],
    expected_recommendation: str,
    expected_reason: str,
) -> None:
    from backend.app.schemas.extraction import ExtractionJSON
    from backend.app.services.tracking_policy import recommend_physical_delivery

    extraction = ExtractionJSON.model_validate(
        {
            "contract_id": "tracking-policy-test",
            "parties": {
                "buyer": {"name": "Alıcı", "tax_id": None},
                "seller": {"name": "Satıcı", "tax_id": None},
            },
            "commercial_terms": {
                "currency": "TRY",
                "total_amount": 100.0,
                "goods": goods,
                "delivery_deadline": None,
            },
            "payment_rules": [
                {
                    "milestone": "Sözleşme tamamlanması",
                    "trigger": "approval",
                    "percentage": 100.0,
                    "required_evidence": required_evidence,
                    "source_quote": "Sözleşme maddesi.",
                    "confidence": 0.9,
                }
            ],
            "risk_flags": [],
            "needs_manual_review": False,
        }
    )

    result = recommend_physical_delivery(extraction)

    assert result.recommendation.value == expected_recommendation
    assert expected_reason in [reason.value for reason in result.reason_codes]
    assert all(reason.value.isupper() for reason in result.reason_codes)
