"""`TestClient` uçtan uca API akışı testleri — upload -> pipeline -> onay -> havuz ödemesi.

Faz 3B kapsamı: yalnızca transactions/approvals router'ları. Delivery/decision/
evidence akışı (Faz 4) burada test EDİLMEZ — dört demo senaryosu (capture,
partial, dispute, REJECT) ileride ayrı bir testte eklenir.

`with TestClient(app) as c:` (context-manager) formu kullanılır — bu FastAPI
sürümünde `startup`/lifespan (ve dolayısıyla `init_db`) yalnızca böyle tetiklenir.
`LLM_PROVIDER=fake` default'uyla fake fixture PASS + 100000 TRY + 2 kural (30/70)
üretir (bkz. `services/extraction.py::_fake_fixture`).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_SAMPLE_MARKDOWN = (
    "# Örnek Sözleşme\n\n"
    "Alıcı ile Satıcı arasında endüstriyel pompa alım satımı sözleşmesidir.\n"
    "Sipariş onayı ile %30, teslimatta %70 ödenir.\n"
)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Her test kendi sqlite dosyasını kullanır — gerçek runtime DB'ye dokunulmaz."""
    db_path = tmp_path / "m4trust_test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("LLM_PROVIDER", "fake")


@pytest.fixture()
def client():
    from backend.app.main import app

    with TestClient(app) as c:
        yield c


def _upload_sample(client: TestClient, tmp_path: Path) -> dict:
    md_path = tmp_path / "sozlesme.md"
    md_path.write_text(_SAMPLE_MARKDOWN, encoding="utf-8")
    with md_path.open("rb") as fh:
        response = client.post(
            "/api/transactions",
            files={"file": ("sozlesme.md", fh, "text/markdown")},
        )
    assert response.status_code == 200, response.text
    return response.json()


def test_upload_passthrough_settles_to_awaiting_approval(client: TestClient, tmp_path: Path) -> None:
    created = _upload_sample(client, tmp_path)
    assert "id" in created
    assert created["buyer_link"].startswith(f"/t/{created['id']}/party?token=")
    assert created["seller_link"].startswith(f"/t/{created['id']}/party?token=")
    assert created["buyer_link"] != created["seller_link"]

    detail = client.get(f"/api/transactions/{created['id']}").json()
    assert detail["state"] == "awaiting_approval"
    assert detail["extraction"] is not None
    assert detail["extraction"]["commercial_terms"]["total_amount"] == 100000.0
    assert detail["validator"]["status"] == "PASS"
    assert detail["validator"]["findings"] == []

    listed = client.get("/api/transactions").json()
    assert any(item["id"] == created["id"] for item in listed)
    matching = next(item for item in listed if item["id"] == created["id"])
    assert matching["buyer_name"] == "Örnek Alıcı A.Ş."
    assert matching["seller_name"] == "Örnek Satıcı Ltd. Şti."


def test_get_detail_404_for_unknown_transaction(client: TestClient) -> None:
    response = client.get("/api/transactions/does-not-exist")
    assert response.status_code == 404


def _extract_token(link: str) -> str:
    return link.split("token=", 1)[1]


def test_party_view_valid_and_bogus_token(client: TestClient, tmp_path: Path) -> None:
    created = _upload_sample(client, tmp_path)
    buyer_token = _extract_token(created["buyer_link"])

    ok = client.get(
        f"/api/transactions/{created['id']}/party-view", params={"token": buyer_token}
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["party"] == "buyer"
    assert body["state"] == "awaiting_approval"
    assert body["extraction_summary"]["total_amount"] == 100000.0
    assert len(body["extraction_summary"]["payment_rules"]) == 2

    bogus = client.get(
        f"/api/transactions/{created['id']}/party-view", params={"token": "bogus-token"}
    )
    assert bogus.status_code == 403


def test_double_approval_creates_pool_payment_and_activates(client: TestClient, tmp_path: Path) -> None:
    created = _upload_sample(client, tmp_path)
    buyer_token = _extract_token(created["buyer_link"])
    seller_token = _extract_token(created["seller_link"])
    tx_id = created["id"]

    buyer_resp = client.post(f"/api/transactions/{tx_id}/approvals", json={"token": buyer_token})
    assert buyer_resp.status_code == 200
    body = buyer_resp.json()
    assert body["state"] == "awaiting_approval"
    assert body["approvals"] == {"buyer": True, "seller": False}

    detail = client.get(f"/api/transactions/{tx_id}").json()
    assert detail["payment"] is None

    seller_resp = client.post(f"/api/transactions/{tx_id}/approvals", json={"token": seller_token})
    assert seller_resp.status_code == 200
    body = seller_resp.json()
    assert body["state"] == "active"
    assert body["approvals"] == {"buyer": True, "seller": True}

    detail = client.get(f"/api/transactions/{tx_id}").json()
    assert detail["state"] == "active"
    assert detail["payment"] is not None
    assert len(detail["payment"]) == 1
    assert detail["payment"][0]["status"] == "pool"
    assert detail["payment"][0]["amount"] == 100000.0

    # Yeniden onay (idempotent) — durum ve onay sayısı değişmez.
    repeat_resp = client.post(f"/api/transactions/{tx_id}/approvals", json={"token": buyer_token})
    assert repeat_resp.status_code == 200
    repeat_body = repeat_resp.json()
    assert repeat_body["state"] == "active"
    assert repeat_body["approvals"] == {"buyer": True, "seller": True}

    detail_after = client.get(f"/api/transactions/{tx_id}").json()
    assert len(detail_after["payment"]) == 1


def test_approval_with_wrong_token_returns_403(client: TestClient, tmp_path: Path) -> None:
    created = _upload_sample(client, tmp_path)
    response = client.post(
        f"/api/transactions/{created['id']}/approvals", json={"token": "wrong-token"}
    )
    assert response.status_code == 403
