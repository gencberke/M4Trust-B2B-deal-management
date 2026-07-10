"""`TestClient` uçtan uca delivery/decision/evidence akışı testleri (Faz 4B).

Kapsam: `POST .../events/e-irsaliye`, `POST .../delivery-video`,
`GET .../evidence` — tam teslimat (capture), kısmi teslimat (partial_capture),
çelişki (dispute + ödeme kilitli), fonlanmamış işlemde 409, evidence bundle'da
ham markdown sızmaması.

`LLM_PROVIDER=fake` fixture'ı PASS + 100000 TRY + tek kalem (10 adet Endüstriyel
Pompa) üretir, İKİ ödeme kuralı taşır: "Sipariş onayı" (`required_evidence=[contract]`)
ve "Teslimat" (`required_evidence=[e_irsaliye, video]`) — bkz.
`services/extraction.py::_fake_fixture`. `decide()`'ın kanıt birleşimi
(`_required_evidence_union`) TÜM kuralların `required_evidence`'ını birleştirdiğinden
(§ decision.py) bu fixture ile decision yalnızca hem e-irsaliye HEM video kanıtı
toplandıktan sonra `hold` dışına çıkar — yalnızca e-irsaliye göndermek `hold`
sonucu üretir (video eksik). Bu yüzden capture/partial senaryoları iki event'lik
(e-irsaliye + video) bir akışla sürülür; dispute senaryosu görevde tarif edildiği
gibi bu iki adımla zaten doğal olarak örtüşür.
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
    db_path = tmp_path / "m4trust_test.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("LLM_PROVIDER", "fake")


@pytest.fixture()
def client():
    from backend.app.main import app

    with TestClient(app) as c:
        yield c


def _extract_token(link: str) -> str:
    return link.split("token=", 1)[1]


def _upload_and_activate(client: TestClient, tmp_path: Path) -> dict:
    """Upload + iki taraf onayı: state `active`, havuz ödemesi `pool` olarak döner."""
    md_path = tmp_path / "sozlesme.md"
    md_path.write_text(_SAMPLE_MARKDOWN, encoding="utf-8")
    with md_path.open("rb") as fh:
        created = client.post(
            "/api/transactions", files={"file": ("sozlesme.md", fh, "text/markdown")}
        ).json()

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


def test_full_delivery_triggers_capture(client: TestClient, tmp_path: Path) -> None:
    tx = _upload_and_activate(client, tmp_path)

    # 1. adım: yalnızca e-irsaliye — video kanıtı henüz yok -> hold, state evidence_pending.
    e_irsaliye_resp = client.post(
        f"/api/transactions/{tx['id']}/events/e-irsaliye",
        json={"delivered_quantity": 10},
    )
    assert e_irsaliye_resp.status_code == 200, e_irsaliye_resp.text
    first_body = e_irsaliye_resp.json()
    assert first_body["state"] == "evidence_pending"
    assert first_body["decision"]["action"] == "hold"

    # 2. adım: uyumlu video (ipucu yok -> counts=10, hasar yok) -> capture.
    video_body = _post_video(client, tx["id"], "teslimat.mp4")
    assert video_body["state"] == "decided"
    assert video_body["decision"]["action"] == "capture"
    assert video_body["decision"]["capture_ratio"] == 1.0

    detail = client.get(f"/api/transactions/{tx['id']}").json()
    assert detail["state"] == "decided"
    assert len(detail["payment"]) == 1
    assert detail["payment"][0]["status"] == "released"

    event_types = [ev["event_type"] for ev in detail["events"]]
    assert "e_irsaliye_received" in event_types
    assert "delivery_video_analyzed" in event_types
    assert "payment_decision_created" in event_types
    assert "mock_payment_executed" in event_types


def test_partial_delivery_triggers_partial_capture(client: TestClient, tmp_path: Path) -> None:
    tx = _upload_and_activate(client, tmp_path)

    client.post(
        f"/api/transactions/{tx['id']}/events/e-irsaliye",
        json={"delivered_quantity": 6},
    )
    # "eksik" ipucu -> video counts=7, hasar yok; |6-7|/10 = %10 ayrışma (eşiğin
    # ÜSTÜNDE değil, eşitse dispute tetiklenmez) -> partial_capture, oran=6/10.
    video_body = _post_video(client, tx["id"], "teslimat_eksik.mp4")
    assert video_body["decision"]["action"] == "partial_capture"
    assert video_body["decision"]["capture_ratio"] == pytest.approx(0.6)

    detail = client.get(f"/api/transactions/{tx['id']}").json()
    assert detail["payment"][0]["status"] == "partially_released"


def test_damaged_video_triggers_dispute_without_release(client: TestClient, tmp_path: Path) -> None:
    tx = _upload_and_activate(client, tmp_path)

    e_irsaliye_resp = client.post(
        f"/api/transactions/{tx['id']}/events/e-irsaliye",
        json={"delivered_quantity": 10},
    )
    assert e_irsaliye_resp.status_code == 200
    assert e_irsaliye_resp.json()["decision"]["action"] == "hold"

    video_body = _post_video(client, tx["id"], "teslimat_hasarli.mp4")
    assert video_body["analysis"]["damage_signals"] == ["hasar_tespiti"]
    assert video_body["decision"]["action"] == "dispute"

    detail = client.get(f"/api/transactions/{tx['id']}").json()
    assert detail["state"] == "decided"
    event_types = [ev["event_type"] for ev in detail["events"]]
    assert "dispute_opened" in event_types
    assert "payment_decision_created" in event_types
    # Dispute'ta capture ASLA yapılmaz — havuz durumu değişmeden kalır, hiçbir
    # `mock_payment_executed` event'i üretilmez.
    assert not any(ev["event_type"] == "mock_payment_executed" for ev in detail["events"])
    assert all(p["status"] == "pool" for p in detail["payment"])


def test_premature_evidence_before_approval_returns_409(client: TestClient, tmp_path: Path) -> None:
    md_path = tmp_path / "sozlesme.md"
    md_path.write_text(_SAMPLE_MARKDOWN, encoding="utf-8")
    with md_path.open("rb") as fh:
        created = client.post(
            "/api/transactions", files={"file": ("sozlesme.md", fh, "text/markdown")}
        ).json()

    detail = client.get(f"/api/transactions/{created['id']}").json()
    assert detail["state"] == "awaiting_approval"

    response = client.post(
        f"/api/transactions/{created['id']}/events/e-irsaliye",
        json={"delivered_quantity": 10},
    )
    assert response.status_code == 409


def test_evidence_bundle_excludes_raw_markdown(client: TestClient, tmp_path: Path) -> None:
    tx = _upload_and_activate(client, tmp_path)

    client.post(
        f"/api/transactions/{tx['id']}/events/e-irsaliye",
        json={"delivered_quantity": 10},
    )
    video_body = _post_video(client, tx["id"], "teslimat.mp4")
    assert video_body["decision"]["action"] == "capture"

    response = client.get(f"/api/transactions/{tx['id']}/evidence")
    assert response.status_code == 200, response.text
    bundle = response.json()

    assert bundle["transaction"]["id"] == tx["id"]
    assert bundle["extraction"] is not None
    assert len(bundle["events"]) > 0
    assert len(bundle["payments"]) == 1
    assert bundle["decision"]["action"] == "capture"
    assert "generated_at" in bundle

    serialized = str(bundle)
    assert _SAMPLE_MARKDOWN not in serialized
    assert "Alıcı ile Satıcı arasında endüstriyel pompa" not in serialized
