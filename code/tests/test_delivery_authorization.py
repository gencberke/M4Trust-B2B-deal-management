"""Teslimat kanıtı yetkilendirme regresyon testleri (H0 hotfix).

Kapsam: `plans/ready/00_delivery_authorization_hotfix.md`. Bugüne kadar
`GET /api/transactions` kimliksiz tüm işlem id'lerini veriyordu ve
`POST .../events/e-irsaliye` / `POST .../delivery-video` hiç token istemiyordu
— listeden bir id bulan herkes sahte teslimat bildirip mock release
tetikleyebiliyordu. Bu dosya, kapatılan deliğin gerçekten kapandığını ve
mevcut karar/kanıt semantiğinin bu guard'larla bozulmadığını doğrular.

Token'lar burada bilinçli olarak HER çağrıda açıkça geçiliyor (paylaşılan bir
autouse fixture'a gizlenmiyor) — aksi halde ileride bir uç yanlışlıkla
yetkilendirmesiz bırakılırsa test bunu fark edemez.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


_SAMPLE_MARKDOWN = (
    "# Örnek Sözleşme\n\n"
    "Alıcı ile Satıcı arasında endüstriyel pompa alım satımı sözleşmesidir.\n"
    "Tarafların onayıyla ödeme yapılır.\n"
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


def _upload(client: TestClient, tmp_path: Path) -> dict:
    md_path = tmp_path / "sozlesme.md"
    md_path.write_text(_SAMPLE_MARKDOWN, encoding="utf-8")
    with md_path.open("rb") as fh:
        response = client.post(
            "/api/transactions", files={"file": ("sozlesme.md", fh, "text/markdown")}
        )
    assert response.status_code == 200, response.text
    return response.json()


def _lock_policy(client: TestClient, created: dict, *, mode: str) -> None:
    tx_id = created["id"]
    manager_token = _extract_token(created["manager_link"])
    update = client.put(
        f"/api/transactions/{tx_id}/tracking-policy",
        json={
            "manager_token": manager_token,
            "physical_delivery_confirmed": True,
            "tracking_mode": mode,
        },
    )
    assert update.status_code == 200, update.text
    lock = client.post(
        f"/api/transactions/{tx_id}/tracking-policy/lock",
        json={"manager_token": manager_token},
    )
    assert lock.status_code == 200, lock.text


def _approve_both(client: TestClient, created: dict) -> str:
    tx_id = created["id"]
    client.post(
        f"/api/transactions/{tx_id}/approvals",
        json={"token": _extract_token(created["buyer_link"])},
    )
    seller = client.post(
        f"/api/transactions/{tx_id}/approvals",
        json={"token": _extract_token(created["seller_link"])},
    )
    assert seller.status_code == 200, seller.text
    return seller.json()["state"]


def _prepare(client: TestClient, tmp_path: Path, *, mode: str = "document_only") -> dict:
    """Policy kilitli + iki taraf onaylı, teslimat uçlarını çağırmaya hazır bir işlem."""
    created = _upload(client, tmp_path)
    _lock_policy(client, created, mode=mode)
    _approve_both(client, created)
    return created


def _post_e_irsaliye(client: TestClient, tx_id: str, quantity: float, *, token: str | None):
    params = {"token": token} if token is not None else {}
    return client.post(
        f"/api/transactions/{tx_id}/events/e-irsaliye",
        json={"delivered_quantity": quantity},
        params=params,
    )


def _post_video(client: TestClient, tx_id: str, filename: str, *, token: str | None):
    params = {"token": token} if token is not None else {}
    return client.post(
        f"/api/transactions/{tx_id}/delivery-video",
        files={"file": (filename, io.BytesIO(b"fake-video-bytes"), "video/mp4")},
        params=params,
    )


# --- E-irsaliye: token yetkilendirmesi ---------------------------------------


def test_e_irsaliye_anonymous_is_forbidden(client: TestClient, tmp_path: Path) -> None:
    created = _prepare(client, tmp_path)
    response = _post_e_irsaliye(client, created["id"], 10, token=None)
    assert response.status_code == 403


def test_e_irsaliye_buyer_token_is_forbidden(client: TestClient, tmp_path: Path) -> None:
    created = _prepare(client, tmp_path)
    response = _post_e_irsaliye(
        client, created["id"], 10, token=_extract_token(created["buyer_link"])
    )
    assert response.status_code == 403


def test_e_irsaliye_seller_token_is_accepted(client: TestClient, tmp_path: Path) -> None:
    created = _prepare(client, tmp_path)
    response = _post_e_irsaliye(
        client, created["id"], 10, token=_extract_token(created["seller_link"])
    )
    assert response.status_code == 200, response.text


def test_e_irsaliye_manager_token_is_accepted(client: TestClient, tmp_path: Path) -> None:
    created = _prepare(client, tmp_path)
    response = _post_e_irsaliye(
        client, created["id"], 10, token=_extract_token(created["manager_link"])
    )
    assert response.status_code == 200, response.text


# --- Video: token yetkilendirmesi --------------------------------------------


def test_video_anonymous_is_forbidden(client: TestClient, tmp_path: Path) -> None:
    created = _prepare(client, tmp_path, mode="document_and_video")
    response = _post_video(client, created["id"], "teslimat.mp4", token=None)
    assert response.status_code == 403


def test_video_buyer_token_is_forbidden(client: TestClient, tmp_path: Path) -> None:
    created = _prepare(client, tmp_path, mode="document_and_video")
    response = _post_video(
        client, created["id"], "teslimat.mp4", token=_extract_token(created["buyer_link"])
    )
    assert response.status_code == 403


def test_video_seller_token_is_accepted(client: TestClient, tmp_path: Path) -> None:
    created = _prepare(client, tmp_path, mode="document_and_video")
    response = _post_video(
        client, created["id"], "teslimat.mp4", token=_extract_token(created["seller_link"])
    )
    assert response.status_code == 200, response.text


def test_video_manager_token_is_accepted(client: TestClient, tmp_path: Path) -> None:
    created = _prepare(client, tmp_path, mode="document_and_video")
    response = _post_video(
        client, created["id"], "teslimat.mp4", token=_extract_token(created["manager_link"])
    )
    assert response.status_code == 200, response.text


def test_e_irsaliye_wrong_token_is_forbidden(client: TestClient, tmp_path: Path) -> None:
    """Başka bir işlemin geçerli token'ı bile bu işlemde işe yaramamalı."""
    created = _prepare(client, tmp_path)
    other = _prepare(client, tmp_path)
    response = _post_e_irsaliye(
        client, created["id"], 10, token=_extract_token(other["seller_link"])
    )
    assert response.status_code == 403


# --- Public liste env kapısı --------------------------------------------------


def test_transaction_list_forbidden_when_dashboard_flag_unset(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEMO_PUBLIC_DASHBOARD", raising=False)
    _upload(client, tmp_path)
    response = client.get("/api/transactions")
    assert response.status_code == 403


def test_transaction_list_forbidden_when_dashboard_flag_false(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMO_PUBLIC_DASHBOARD", "false")
    _upload(client, tmp_path)
    response = client.get("/api/transactions")
    assert response.status_code == 403


def test_transaction_list_allowed_when_dashboard_flag_true(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMO_PUBLIC_DASHBOARD", "true")
    created = _upload(client, tmp_path)
    response = client.get("/api/transactions")
    assert response.status_code == 200
    assert any(item["id"] == created["id"] for item in response.json())


# --- Token sızıntısı ----------------------------------------------------------


def test_capability_tokens_do_not_leak_into_events_or_evidence(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEMO_PUBLIC_DASHBOARD", "true")
    created = _prepare(client, tmp_path)
    seller_token = _extract_token(created["seller_link"])
    buyer_token = _extract_token(created["buyer_link"])
    manager_token = _extract_token(created["manager_link"])

    assert _post_e_irsaliye(client, created["id"], 10, token=seller_token).status_code == 200

    detail = client.get(f"/api/transactions/{created['id']}")
    events_serialized = str(detail.json())
    for token in (seller_token, buyer_token, manager_token):
        assert token not in events_serialized

    evidence = client.get(
        f"/api/transactions/{created['id']}/evidence", params={"token": buyer_token}
    )
    assert evidence.status_code == 200, evidence.text
    evidence_serialized = str(evidence.json())
    for token in (seller_token, buyer_token, manager_token):
        assert token not in evidence_serialized

    listing = client.get("/api/transactions")
    assert listing.status_code == 200
    listing_serialized = str(listing.json())
    for token in (seller_token, buyer_token, manager_token):
        assert token not in listing_serialized


# --- Regresyon: karar/takip semantiği değişmedi ------------------------------


def test_seller_token_full_delivery_still_captures(client: TestClient, tmp_path: Path) -> None:
    """Guard eklendikten sonra da seller token'lı tam teslim aynı capture kararına ulaşır."""
    created = _prepare(client, tmp_path, mode="document_only")

    response = _post_e_irsaliye(
        client, created["id"], 10, token=_extract_token(created["seller_link"])
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "decided"
    assert body["decision"]["action"] == "capture"
    assert body["decision"]["capture_ratio"] == 1.0

    detail = client.get(f"/api/transactions/{created['id']}").json()
    assert detail["payment"][0]["status"] == "released"


def test_channel_guard_still_rejects_video_when_tracking_off(
    client: TestClient, tmp_path: Path
) -> None:
    """Kanal guard'ı (document_only'de video kapalı) yetkilendirme guard'ından SONRA hâlâ çalışıyor."""
    created = _prepare(client, tmp_path, mode="document_only")

    response = _post_video(
        client, created["id"], "teslimat.mp4", token=_extract_token(created["seller_link"])
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "TRACKING_NOT_ENABLED"
