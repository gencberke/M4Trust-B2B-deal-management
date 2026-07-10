"""`TestClient` uçtan uca API akışı testleri — upload -> pipeline -> onay -> havuz ödemesi.

Faz 3B kapsamı: yalnızca transactions/approvals router'ları. Faz 5 kapsamı:
YOL_HARITASI §3'teki dört demo senaryosunun uçtan uca `TestClient` testleri
(bkz. dosya sonu) — tam teslim -> capture, kısmi teslim -> partial_capture,
çelişkili kanıt -> dispute (ödeme kilitli), bozuk sözleşme (%40+%50) -> REJECT
("altın an").

`with TestClient(app) as c:` (context-manager) formu kullanılır — bu FastAPI
sürümünde `startup`/lifespan (ve dolayısıyla `init_db`) yalnızca böyle tetiklenir.
`LLM_PROVIDER=fake` default'uyla fake fixture PASS + 100000 TRY + 2 kural (30/70)
üretir (bkz. `services/extraction.py::_fake_fixture`).
"""

from __future__ import annotations

import io
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


# --- Faz 5: dört demo senaryosu (YOL_HARITASI §3) ---------------------------


def _upload_and_activate(client: TestClient, tmp_path: Path) -> dict:
    """Upload + iki taraf onayı: state `active`, havuz ödemesi `pool` olarak döner."""
    created = _upload_sample(client, tmp_path)
    buyer_token = _extract_token(created["buyer_link"])
    seller_token = _extract_token(created["seller_link"])
    tx_id = created["id"]

    client.post(f"/api/transactions/{tx_id}/approvals", json={"token": buyer_token})
    seller_resp = client.post(f"/api/transactions/{tx_id}/approvals", json={"token": seller_token})
    assert seller_resp.status_code == 200
    assert seller_resp.json()["state"] == "active"

    return {"id": tx_id, "buyer_token": buyer_token, "seller_token": seller_token}


def _post_video(client: TestClient, tx_id: str, filename: str) -> dict:
    video_bytes = io.BytesIO(b"fake-video-bytes")
    response = client.post(
        f"/api/transactions/{tx_id}/delivery-video",
        files={"file": (filename, video_bytes, "video/mp4")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_demo_full_delivery_capture(client: TestClient, tmp_path: Path) -> None:
    """Senaryo 1: tam teslim -> capture — havuzdaki tutar tamamen serbest bırakılır."""
    tx = _upload_and_activate(client, tmp_path)

    e_irsaliye_resp = client.post(
        f"/api/transactions/{tx['id']}/events/e-irsaliye",
        json={"delivered_quantity": 10},
    )
    assert e_irsaliye_resp.status_code == 200, e_irsaliye_resp.text
    assert e_irsaliye_resp.json()["state"] == "evidence_pending"
    assert e_irsaliye_resp.json()["decision"]["action"] == "hold"

    # İpucusuz dosya adı -> fake analiz sözleşme miktarını (10) sayar, hasar yok.
    video_body = _post_video(client, tx["id"], "teslimat.mp4")
    assert video_body["state"] == "decided"
    assert video_body["decision"]["action"] == "capture"
    assert video_body["decision"]["capture_ratio"] == 1.0

    detail = client.get(f"/api/transactions/{tx['id']}").json()
    assert detail["state"] == "decided"
    assert len(detail["payment"]) == 1
    assert detail["payment"][0]["status"] == "released"

    event_types = [ev["event_type"] for ev in detail["events"]]
    assert "payment_decision_created" in event_types
    assert "mock_payment_executed" in event_types

    evidence_resp = client.get(f"/api/transactions/{tx['id']}/evidence")
    assert evidence_resp.status_code == 200


def test_demo_partial_delivery_partial_capture(client: TestClient, tmp_path: Path) -> None:
    """Senaryo 2: kısmi teslim -> partial_capture — havuzun yalnızca oranı kadarı serbest kalır."""
    tx = _upload_and_activate(client, tmp_path)

    e_irsaliye_resp = client.post(
        f"/api/transactions/{tx['id']}/events/e-irsaliye",
        json={"delivered_quantity": 7},
    )
    assert e_irsaliye_resp.status_code == 200, e_irsaliye_resp.text
    assert e_irsaliye_resp.json()["decision"]["action"] == "hold"

    # "eksik" ipucu -> fake analiz unit_count=7 üretir; |7-7|/10 = %0 ayrışma
    # (çelişki eşiğinin altında) -> partial_capture, oran = 7/10.
    video_body = _post_video(client, tx["id"], "teslimat_eksik.mp4")
    assert video_body["decision"]["action"] == "partial_capture"
    assert video_body["decision"]["capture_ratio"] == pytest.approx(0.7)

    detail = client.get(f"/api/transactions/{tx['id']}").json()
    assert detail["state"] == "decided"
    assert detail["payment"][0]["status"] == "partially_released"

    evidence_resp = client.get(f"/api/transactions/{tx['id']}/evidence")
    assert evidence_resp.status_code == 200


def test_demo_conflicting_evidence_dispute(client: TestClient, tmp_path: Path) -> None:
    """Senaryo 3: çelişkili/hasarlı kanıt -> dispute — capture ASLA yapılmaz, havuz kilitli kalır."""
    tx = _upload_and_activate(client, tmp_path)

    e_irsaliye_resp = client.post(
        f"/api/transactions/{tx['id']}/events/e-irsaliye",
        json={"delivered_quantity": 10},
    )
    assert e_irsaliye_resp.status_code == 200
    assert e_irsaliye_resp.json()["decision"]["action"] == "hold"

    # "hasarli" ipucu -> fake analiz damage_signals doldurur -> dispute.
    video_body = _post_video(client, tx["id"], "teslimat_hasarli.mp4")
    assert video_body["state"] == "decided"
    assert video_body["decision"]["action"] == "dispute"

    detail = client.get(f"/api/transactions/{tx['id']}").json()
    assert detail["state"] == "decided"
    event_types = [ev["event_type"] for ev in detail["events"]]
    assert "dispute_opened" in event_types
    assert not any(ev["event_type"] == "mock_payment_executed" for ev in detail["events"])
    assert all(p["status"] == "pool" for p in detail["payment"])

    evidence_resp = client.get(f"/api/transactions/{tx['id']}/evidence")
    assert evidence_resp.status_code == 200


def _bad_extraction_json():
    """Yüzde toplamı 90 (%40+%50) olan, aksi halde geçerli bir `ExtractionJSON` üretir.

    Validator'ın "altın an" kontrolünü ("PERCENTAGE_SUM") tetiklemek için
    özel olarak bozuk kurgulanmıştır — `_fake_fixture` ile aynı alan şeklini
    taşır (bkz. `services/extraction.py::_fake_fixture`), yalnızca yüzdeler
    değiştirilmiştir.
    """
    from backend.app.schemas.extraction import ExtractionJSON

    return ExtractionJSON.model_validate(
        {
            "contract_id": "demo-sozlesme-broken-001",
            "parties": {
                "buyer": {"name": "Örnek Alıcı A.Ş.", "tax_id": "1234567890"},
                "seller": {"name": "Örnek Satıcı Ltd. Şti.", "tax_id": "9876543210"},
            },
            "commercial_terms": {
                "currency": "TRY",
                "total_amount": 100000.0,
                "goods": [{"name": "Endüstriyel Pompa", "quantity": 10, "unit": "adet"}],
                "delivery_deadline": "2026-09-01",
            },
            "payment_rules": [
                {
                    "milestone": "Sipariş onayı",
                    "trigger": "approval",
                    "percentage": 40.0,
                    "required_evidence": ["contract"],
                    "source_quote": "Sipariş onayı ile birlikte tutarın %40'ı ödenir.",
                    "confidence": 0.9,
                },
                {
                    "milestone": "Teslimat",
                    "trigger": "delivery_video",
                    "percentage": 50.0,
                    "required_evidence": ["e_irsaliye", "video"],
                    "source_quote": "Teslimat videosu onaylandığında kalan %50 ödenir.",
                    "confidence": 0.85,
                },
            ],
            "risk_flags": [],
            "needs_manual_review": False,
        }
    )


class _StubBadExtractionService:
    """Yüzde toplamı bozuk sabit bir extraction döndüren test dublörü (§6.3 adapter+fake)."""

    def extract(self, masked_markdown: str, context) -> "ExtractionResult":
        from backend.app.services.extraction import ExtractionResult

        return ExtractionResult(status="ok", data=_bad_extraction_json())


def test_demo_broken_contract_reject(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Senaryo 4 ("altın an"): yüzde toplamı 100 değil -> REJECT, akış durur."""
    # Pipeline'ın çağırdığı `make_extraction_service` adı `routers.transactions`
    # içine import edildiği için monkeypatch de o modül-yerel adı hedefler
    # (TestClient içindeki background task senkron koştuğu için upload'tan
    # ÖNCE, `with TestClient(app) as c:` bloğunun içinde uygulanmalı).
    monkeypatch.setattr(
        "backend.app.routers.transactions.make_extraction_service",
        lambda settings: _StubBadExtractionService(),
    )

    created = _upload_sample(client, tmp_path)
    tx_id = created["id"]

    detail = client.get(f"/api/transactions/{tx_id}").json()
    assert detail["state"] == "rejected"
    assert detail["validator"]["status"] == "REJECT"
    finding_codes = [f["code"] for f in detail["validator"]["findings"]]
    assert "PERCENTAGE_SUM" in finding_codes
    percentage_finding = next(
        f for f in detail["validator"]["findings"] if f["code"] == "PERCENTAGE_SUM"
    )
    assert "yüzde" in percentage_finding["message"].lower()

    party_view = client.get(
        f"/api/transactions/{tx_id}/party-view",
        params={"token": _extract_token(created["buyer_link"])},
    ).json()
    assert party_view["state"] == "rejected"
    assert any(f["code"] == "PERCENTAGE_SUM" for f in party_view["validator_findings"])

    # Akış durmuştur: onay denemesi de kabul edilmemelidir.
    approval_resp = client.post(
        f"/api/transactions/{tx_id}/approvals",
        json={"token": _extract_token(created["buyer_link"])},
    )
    assert approval_resp.status_code == 409

    evidence_resp = client.get(f"/api/transactions/{tx_id}/evidence")
    assert evidence_resp.status_code == 200
