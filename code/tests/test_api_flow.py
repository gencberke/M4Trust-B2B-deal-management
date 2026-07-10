"""`TestClient` uçtan uca API akışı testleri — upload -> pipeline -> onay -> havuz ödemesi.

Dosya sonunda demo senaryoları uçtan uca sürülür: approval-only (hizmet),
document-only fiziksel teslimat, ikincil videonun uyumlu ve yüksek-güvenli
anomali dalları, sözleşmesel video ve bozuk sözleşme ("altın an": %40+%50 ->
validator REJECT).

`with TestClient(app) as c:` (context-manager) formu kullanılır — bu FastAPI
sürümünde `startup`/lifespan (ve dolayısıyla `init_db`) yalnızca böyle tetiklenir.
`LLM_PROVIDER=fake` default'uyla fake fixture PASS + 100000 TRY + tek approval
kuralı üretir (bkz. `services/extraction.py::_fake_fixture`): sözleşme harici
teslimat kanıtı istemez, e-irsaliye/video yalnızca takip politikasıyla açılır.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from extraction_fixtures import (
    broken_percentage_contract,
    contractual_video_contract,
    patch_extraction,
)

_SAMPLE_MARKDOWN = (
    "# Örnek Sözleşme\n\n"
    "Alıcı ile Satıcı arasında endüstriyel pompa alım satımı sözleşmesidir.\n"
    "Tarafların onayıyla ödeme yapılır.\n"
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


def test_upload_passthrough_settles_to_awaiting_approval(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Liste ucu artık DEMO_PUBLIC_DASHBOARD kapısının arkasında (H0 hotfix).
    monkeypatch.setenv("DEMO_PUBLIC_DASHBOARD", "true")
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


def _lock_policy(client: TestClient, created: dict, *, mode: str = "off") -> None:
    """Yönetici capability'siyle takip policy'sini seçip kilitler."""
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


def _lock_off_policy(client: TestClient, created: dict) -> None:
    _lock_policy(client, created, mode="off")


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
    assert len(body["extraction_summary"]["payment_rules"]) == 1
    # Taraflar onaydan önce takip politikasını sade biçimde görür.
    assert body["tracking_summary"]["video_role"] == "advisory"
    assert body["tracking_summary"]["video_tracking_enabled"] is False

    bogus = client.get(
        f"/api/transactions/{created['id']}/party-view", params={"token": "bogus-token"}
    )
    assert bogus.status_code == 403


def test_double_approval_releases_approval_only_payment_once(
    client: TestClient, tmp_path: Path
) -> None:
    created = _upload_sample(client, tmp_path)
    _lock_off_policy(client, created)
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
    assert body["state"] == "decided"
    assert body["approvals"] == {"buyer": True, "seller": True}

    detail = client.get(f"/api/transactions/{tx_id}").json()
    assert detail["state"] == "decided"
    assert detail["payment"] is not None
    assert len(detail["payment"]) == 1
    assert detail["payment"][0]["status"] == "released"
    assert detail["payment"][0]["amount"] == 100000.0

    # Yeniden onay (idempotent) — durum ve onay sayısı değişmez.
    repeat_resp = client.post(f"/api/transactions/{tx_id}/approvals", json={"token": buyer_token})
    assert repeat_resp.status_code == 200
    repeat_body = repeat_resp.json()
    assert repeat_body["state"] == "decided"
    assert repeat_body["approvals"] == {"buyer": True, "seller": True}

    detail_after = client.get(f"/api/transactions/{tx_id}").json()
    assert len(detail_after["payment"]) == 1
    assert detail_after["payment"][0]["status"] == "released"


def test_approval_with_wrong_token_returns_403(client: TestClient, tmp_path: Path) -> None:
    created = _upload_sample(client, tmp_path)
    response = client.post(
        f"/api/transactions/{created['id']}/approvals", json={"token": "wrong-token"}
    )
    assert response.status_code == 403


# --- Demo senaryoları (YOL_HARITASI §3) -------------------------------------


def _post_video(client: TestClient, tx_id: str, filename: str, *, token: str):
    """`token` zorunlu (H0 hotfix): teslimat kanıtı yalnız seller/manager kabul edilir."""
    return client.post(
        f"/api/transactions/{tx_id}/delivery-video",
        files={"file": (filename, io.BytesIO(b"fake-video-bytes"), "video/mp4")},
        params={"token": token},
    )


def _post_e_irsaliye(client: TestClient, tx_id: str, quantity: float, *, token: str):
    """`token` zorunlu (H0 hotfix): teslimat kanıtı yalnız seller/manager kabul edilir."""
    return client.post(
        f"/api/transactions/{tx_id}/events/e-irsaliye",
        json={"delivered_quantity": quantity},
        params={"token": token},
    )


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


def _finding_codes(decision: dict) -> list[str]:
    return [finding["code"] for finding in decision["findings"]]


def test_demo_a_service_contract_settles_on_approvals_alone(
    client: TestClient, tmp_path: Path
) -> None:
    """Demo A — hizmet/approval-only: harici teslimat kanıtı beklenmez."""
    created = _upload_sample(client, tmp_path)
    _lock_policy(client, created, mode="off")

    assert _approve_both(client, created) == "decided"

    detail = client.get(f"/api/transactions/{created['id']}").json()
    assert detail["payment"][0]["status"] == "released"
    event_types = [event["event_type"] for event in detail["events"]]
    assert "e_irsaliye_received" not in event_types
    assert "delivery_video_analyzed" not in event_types


def test_demo_b_physical_goods_document_only_capture(client: TestClient, tmp_path: Path) -> None:
    """Demo B — fiziksel mal/document-only: e-irsaliye tam teslim -> capture, video yok."""
    created = _upload_sample(client, tmp_path)
    _lock_policy(client, created, mode="document_only")
    _approve_both(client, created)
    seller_token = _extract_token(created["seller_link"])

    body = _post_e_irsaliye(client, created["id"], 10, token=seller_token).json()

    assert body["state"] == "decided"
    assert body["decision"]["action"] == "capture"
    assert (
        _post_video(client, created["id"], "teslimat.mp4", token=seller_token).status_code
        == 409
    )

    detail = client.get(f"/api/transactions/{created['id']}").json()
    assert detail["payment"][0]["status"] == "released"


def test_demo_c_advisory_video_supports_capture(client: TestClient, tmp_path: Path) -> None:
    """Demo C — document+video uyumlu: video destekleyici, oran yine e-irsaliyeden."""
    created = _upload_sample(client, tmp_path)
    _lock_policy(client, created, mode="document_and_video")
    _approve_both(client, created)
    seller_token = _extract_token(created["seller_link"])

    assert (
        _post_video(client, created["id"], "teslimat.mp4", token=seller_token).status_code
        == 200
    )
    body = _post_e_irsaliye(client, created["id"], 10, token=seller_token).json()

    assert body["state"] == "decided"
    assert body["decision"]["action"] == "capture"
    assert body["decision"]["capture_ratio"] == 1.0
    # Video yalnızca destekleyici bir bulgu üretir; oranı e-irsaliye belirler.
    assert "VIDEO_COUNT_ALIGNED" in _finding_codes(body["decision"])

    detail = client.get(f"/api/transactions/{created['id']}").json()
    assert detail["payment"][0]["status"] == "released"


def test_demo_d_high_confidence_anomaly_holds_without_release_or_dispute(
    client: TestClient, tmp_path: Path
) -> None:
    """Demo D — document+video anomali: hold + manuel inceleme, release/dispute yok."""
    created = _upload_sample(client, tmp_path)
    _lock_policy(client, created, mode="document_and_video")
    _approve_both(client, created)
    seller_token = _extract_token(created["seller_link"])

    _post_video(client, created["id"], "teslimat_hasarli.mp4", token=seller_token)
    body = _post_e_irsaliye(client, created["id"], 10, token=seller_token).json()

    assert body["decision"]["action"] == "hold"
    assert body["decision"]["manual_review_required"] is True
    assert body["state"] == "evidence_pending"

    detail = client.get(f"/api/transactions/{created['id']}").json()
    event_types = [event["event_type"] for event in detail["events"]]
    assert "dispute_opened" not in event_types
    assert "mock_payment_executed" not in event_types
    assert all(payment["status"] == "pool" for payment in detail["payment"])


def test_demo_e_contractual_video_survives_manager_preference(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demo E — sözleşmesel video: yönetici zayıflatamaz; video eksikken hold."""
    patch_extraction(monkeypatch, contractual_video_contract())
    created = _upload_sample(client, tmp_path)

    # Sözleşmesel video, video analizini gerçekten yapan tek modu zorunlu kılar.
    for rejected_mode in ("off", "document_only"):
        attempt = client.put(
            f"/api/transactions/{created['id']}/tracking-policy",
            json={
                "manager_token": _extract_token(created["manager_link"]),
                "physical_delivery_confirmed": True,
                "tracking_mode": rejected_mode,
            },
        )
        assert attempt.status_code == 409, rejected_mode
        assert attempt.json()["detail"]["code"] == "POLICY_CONTRACT_CONFLICT"

    _lock_policy(client, created, mode="document_and_video")
    _approve_both(client, created)

    body = _post_e_irsaliye(
        client, created["id"], 10, token=_extract_token(created["seller_link"])
    ).json()
    assert body["decision"]["action"] == "hold"
    assert "MISSING_REQUIRED_EVIDENCE" in _finding_codes(body["decision"])


def test_demo_f_broken_contract_reject_blocks_policy_and_approval(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demo F ("altın an"): yüzde toplamı 100 değil -> REJECT; policy/onay/ödeme başlamaz."""
    patch_extraction(monkeypatch, broken_percentage_contract())
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

    # REJECT akışı durdurur: takip politikası yapılandırılamaz, onay kabul edilmez.
    lock_attempt = client.post(
        f"/api/transactions/{tx_id}/tracking-policy/lock",
        json={"manager_token": _extract_token(created["manager_link"])},
    )
    assert lock_attempt.status_code == 409
    assert lock_attempt.json()["detail"]["code"] == "POLICY_NOT_CONFIGURABLE"

    approval_resp = client.post(
        f"/api/transactions/{tx_id}/approvals",
        json={"token": _extract_token(created["buyer_link"])},
    )
    assert approval_resp.status_code == 409

    evidence_resp = client.get(
        f"/api/transactions/{tx_id}/evidence",
        params={"token": _extract_token(created["buyer_link"])},
    )
    assert evidence_resp.status_code == 200
