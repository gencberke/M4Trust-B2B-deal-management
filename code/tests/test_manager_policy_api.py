"""Manager capability, policy lock guard ve public projection için kritik API testleri."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "m4trust_manager_policy.db"))
    monkeypatch.setenv("LLM_PROVIDER", "fake")


@pytest.fixture()
def client() -> TestClient:
    from backend.app.main import app

    with TestClient(app) as test_client:
        yield test_client


def _upload(client: TestClient, tmp_path: Path) -> dict:
    contract_path = tmp_path / "sozlesme.md"
    contract_path.write_text("# Sözleşme\n\nFiziksel ürün satışı.", encoding="utf-8")
    with contract_path.open("rb") as contract_file:
        response = client.post(
            "/api/transactions",
            files={"file": ("sozlesme.md", contract_file, "text/markdown")},
        )
    assert response.status_code == 200, response.text
    return response.json()


def _token(link: str) -> str:
    return link.split("token=", 1)[1]


def _replace_with_video_only_contract(created: dict, tmp_path: Path) -> None:
    payload = {
        "contract_id": "video-only-contract",
        "parties": {
            "buyer": {"name": "Alıcı A.Ş.", "tax_id": "1234567890"},
            "seller": {"name": "Satıcı Ltd.", "tax_id": "9876543210"},
        },
        "commercial_terms": {
            "currency": "TRY",
            "total_amount": 100.0,
            "goods": [{"name": "Endüstriyel pompa", "quantity": 1, "unit": "adet"}],
            "delivery_deadline": None,
        },
        "payment_rules": [
            {
                "milestone": "Teslimat",
                "trigger": "delivery_video",
                "percentage": 100.0,
                "required_evidence": ["contract", "video"],
                "source_quote": "Video doğrulamasından sonra ödeme yapılır.",
                "confidence": 0.9,
            }
        ],
        "risk_flags": [],
        "needs_manual_review": False,
    }
    with sqlite3.connect(tmp_path / "m4trust_manager_policy.db") as conn:
        conn.execute(
            "UPDATE extracted_rules SET extraction_json = ? WHERE transaction_id = ?",
            (json.dumps(payload, ensure_ascii=False), created["id"]),
        )
        conn.commit()


def _replace_with_video_and_document_contract(created: dict, tmp_path: Path) -> None:
    payload = {
        "contract_id": "video-and-document-contract",
        "parties": {
            "buyer": {"name": "Alıcı A.Ş.", "tax_id": "1234567890"},
            "seller": {"name": "Satıcı Ltd.", "tax_id": "9876543210"},
        },
        "commercial_terms": {
            "currency": "TRY",
            "total_amount": 100.0,
            "goods": [{"name": "Endüstriyel pompa", "quantity": 1, "unit": "adet"}],
            "delivery_deadline": None,
        },
        "payment_rules": [
            {
                "milestone": "Teslimat",
                "trigger": "delivery_video",
                "percentage": 100.0,
                "required_evidence": ["contract", "e_irsaliye", "video"],
                "source_quote": "Belge ve video doğrulamasından sonra ödeme yapılır.",
                "confidence": 0.9,
            }
        ],
        "risk_flags": [],
        "needs_manual_review": False,
    }
    with sqlite3.connect(tmp_path / "m4trust_manager_policy.db") as conn:
        conn.execute(
            "UPDATE extracted_rules SET extraction_json = ? WHERE transaction_id = ?",
            (json.dumps(payload, ensure_ascii=False), created["id"]),
        )
        conn.commit()


def test_manager_view_rejects_party_capability_token(client: TestClient, tmp_path: Path) -> None:
    created = _upload(client, tmp_path)

    response = client.get(
        f"/api/transactions/{created['id']}/manager-view",
        params={"token": _token(created["buyer_link"])},
    )

    assert response.status_code == 403


def test_approval_requires_a_locked_policy_before_recording_approval(
    client: TestClient, tmp_path: Path
) -> None:
    created = _upload(client, tmp_path)

    response = client.post(
        f"/api/transactions/{created['id']}/approvals",
        json={"token": _token(created["buyer_link"])},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "POLICY_NOT_LOCKED"
    with sqlite3.connect(tmp_path / "m4trust_manager_policy.db") as conn:
        approval_count = conn.execute(
            "SELECT COUNT(*) FROM approvals WHERE transaction_id = ?", (created["id"],)
        ).fetchone()[0]
    assert approval_count == 0


def test_video_only_contract_requires_document_and_video_tracking(
    client: TestClient, tmp_path: Path
) -> None:
    """Sözleşmesel video: `off` da `document_only` da reddedilir.

    `document_only` seçilebilseydi video yalnızca "geldi mi?" diye sayılır,
    hasar/sayım ayrışması hiç değerlendirilmezdi.
    """
    created = _upload(client, tmp_path)
    _replace_with_video_only_contract(created, tmp_path)
    url = f"/api/transactions/{created['id']}/tracking-policy"
    manager_token = _token(created["manager_link"])

    off_response = client.put(
        url,
        json={
            "manager_token": manager_token,
            "physical_delivery_confirmed": False,
            "tracking_mode": "off",
        },
    )
    assert off_response.status_code == 409
    assert off_response.json()["detail"]["code"] == "POLICY_CONTRACT_CONFLICT"

    document_only_response = client.put(
        url,
        json={
            "manager_token": manager_token,
            "physical_delivery_confirmed": True,
            "tracking_mode": "document_only",
        },
    )
    assert document_only_response.status_code == 409
    assert document_only_response.json()["detail"]["code"] == "POLICY_CONTRACT_CONFLICT"
    assert document_only_response.json()["detail"]["conflicts"] == [
        "CONTRACTUAL_VIDEO_REQUIRES_VIDEO_TRACKING"
    ]

    accepted = client.put(
        url,
        json={
            "manager_token": manager_token,
            "physical_delivery_confirmed": True,
            "tracking_mode": "document_and_video",
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["updated"] is True


def test_contractual_document_and_video_reject_physical_delivery_off(
    client: TestClient, tmp_path: Path
) -> None:
    created = _upload(client, tmp_path)
    _replace_with_video_and_document_contract(created, tmp_path)

    response = client.put(
        f"/api/transactions/{created['id']}/tracking-policy",
        json={
            "manager_token": _token(created["manager_link"]),
            "physical_delivery_confirmed": False,
            "tracking_mode": "off",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "POLICY_CONTRACT_CONFLICT"


def test_policy_lock_is_idempotent_without_duplicate_event(client: TestClient, tmp_path: Path) -> None:
    created = _upload(client, tmp_path)
    manager_token = _token(created["manager_link"])
    update_url = f"/api/transactions/{created['id']}/tracking-policy"
    lock_url = f"{update_url}/lock"

    update_response = client.put(
        update_url,
        json={
            "manager_token": manager_token,
            "physical_delivery_confirmed": True,
            "tracking_mode": "off",
        },
    )
    assert update_response.status_code == 200, update_response.text

    first_lock = client.post(lock_url, json={"manager_token": manager_token})
    second_lock = client.post(lock_url, json={"manager_token": manager_token})

    assert first_lock.status_code == 200, first_lock.text
    assert second_lock.status_code == 200, second_lock.text
    assert first_lock.json()["locked"] is True
    assert second_lock.json()["locked"] is False
    assert first_lock.json()["tracking_policy"]["locked_at"] == second_lock.json()["tracking_policy"]["locked_at"]
    with sqlite3.connect(tmp_path / "m4trust_manager_policy.db") as conn:
        event_count = conn.execute(
            "SELECT COUNT(*) FROM events WHERE transaction_id = ? AND event_type = 'tracking_policy_locked'",
            (created["id"],),
        ).fetchone()[0]
    assert event_count == 1


def _capability_responses(client: TestClient, created: dict) -> list:
    """Capability token'ı gerektiren, dolayısıyla alıntıyı gösteren uçlar."""
    return [
        client.get(
            f"/api/transactions/{created['id']}/party-view",
            params={"token": _token(created["buyer_link"])},
        ),
        client.get(
            f"/api/transactions/{created['id']}/manager-view",
            params={"token": _token(created["manager_link"])},
        ),
        client.get(
            f"/api/transactions/{created['id']}/evidence",
            params={"token": _token(created["seller_link"])},
        ),
    ]


def test_capability_views_show_source_quote_but_never_tax_id(
    client: TestClient, tmp_path: Path
) -> None:
    """Taraf, onaylayacağı kuralın sözleşmedeki dayanağını görebilmeli; vergi no görmemeli."""
    created = _upload(client, tmp_path)

    for response in _capability_responses(client, created):
        assert response.status_code == 200, response.text
        body = json.dumps(response.json(), ensure_ascii=False)
        assert "tax_id" not in body
        assert "1234567890" not in body  # buyer tax_id
        assert "Tarafların onayıyla tutarın tamamı ödenir." in body


def test_tokenless_transaction_detail_never_exposes_source_quote(
    client: TestClient, tmp_path: Path
) -> None:
    """Genel detay token istemiyor; maskeleme NER olmadığı için alıntı dönmez."""
    created = _upload(client, tmp_path)

    response = client.get(f"/api/transactions/{created['id']}")

    assert response.status_code == 200, response.text
    body = json.dumps(response.json(), ensure_ascii=False)
    assert "source_quote" not in body
    assert "Tarafların onayıyla tutarın tamamı ödenir." not in body
    assert "tax_id" not in body


def test_evidence_bundle_requires_a_capability_token(client: TestClient, tmp_path: Path) -> None:
    created = _upload(client, tmp_path)
    url = f"/api/transactions/{created['id']}/evidence"

    assert client.get(url).status_code == 422  # token query parametresi zorunlu
    assert client.get(url, params={"token": "bogus-token"}).status_code == 403
    for link in ("buyer_link", "seller_link", "manager_link"):
        assert client.get(url, params={"token": _token(created[link])}).status_code == 200, link


def test_source_quote_is_masked_before_leaving_the_backend(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ham alıntı DB'de durur; capability projection'ı PII'yi placeholder'a çevirir."""
    from extraction_fixtures import patch_extraction

    payload = {
        "contract_id": "pii-in-quote",
        "parties": {
            "buyer": {"name": "Alıcı A.Ş.", "tax_id": "1234567890"},
            "seller": {"name": "Satıcı Ltd.", "tax_id": "9876543210"},
        },
        "commercial_terms": {
            "currency": "TRY",
            "total_amount": 100.0,
            "goods": [{"name": "Endüstriyel pompa", "quantity": 1, "unit": "adet"}],
            "delivery_deadline": None,
        },
        "payment_rules": [
            {
                "milestone": "Onay",
                "trigger": "approval",
                "percentage": 100.0,
                "required_evidence": ["contract"],
                "source_quote": "Ödeme TR330006100519786457841326 IBAN'ına yapılır.",
                "confidence": 0.9,
            }
        ],
        "risk_flags": [],
        "needs_manual_review": False,
    }
    patch_extraction(monkeypatch, payload)
    created = _upload(client, tmp_path)

    for response in _capability_responses(client, created):
        body = json.dumps(response.json(), ensure_ascii=False)
        assert "TR330006100519786457841326" not in body
        assert "[[PII_IBAN_1]]" in body

    # Ham alıntı karar/kanıt akışının girdisi olarak DB'de değişmeden durur.
    with sqlite3.connect(tmp_path / "m4trust_manager_policy.db") as conn:
        stored = conn.execute(
            "SELECT extraction_json FROM extracted_rules WHERE transaction_id = ?",
            (created["id"],),
        ).fetchone()[0]
    assert "TR330006100519786457841326" in stored
