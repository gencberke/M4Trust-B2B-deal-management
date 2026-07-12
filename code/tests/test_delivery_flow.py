"""`TestClient` uçtan uca delivery/settlement/evidence akışı testleri.

Kapsam: `POST .../events/e-irsaliye`, `POST .../delivery-video`, `GET .../evidence`
— takip politikasına göre kanal guard'ları, e-irsaliye birincil kanıt olarak
capture/partial_capture, ikincil (advisory) videonun karar üzerindeki sınırlı
etkisi ve `hold` durumunda release/dispute üretilmemesi.

Varsayılan `LLM_PROVIDER=fake` fixture'ı PASS + 100000 TRY + tek kalem (10 adet
Endüstriyel Pompa) + tek approval kuralı (`required_evidence=[contract]`) üretir.
Yani sözleşme hiçbir harici teslimat kanıtı istemez; e-irsaliye/video yalnızca
yöneticinin kilitlediği takip politikasıyla devreye girer.

`FakeVideoAnalyzer` dosya adı ipuçları (bkz. `services/video/analyzer.py`):
ipucu yok -> uyumlu (unit_count=10, güven 0.9) · `eksik` -> unit_count=7 ·
`hasarli` -> eşleşmiş hasar sinyali · `dusuk_guven` -> güven eşiğin altında.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

# Plan 06 closure: legacy capability davranışı yalnız bu dar sette (env ile açık).
pytestmark = pytest.mark.legacy_compat
from fastapi.testclient import TestClient

from extraction_fixtures import contractual_video_contract, patch_extraction

_SAMPLE_MARKDOWN = (
    "# Örnek Sözleşme\n\n"
    "Alıcı ile Satıcı arasında endüstriyel pompa alım satımı sözleşmesidir.\n"
    "Tarafların onayıyla ödeme yapılır.\n"
)




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


def _lock_policy(
    client: TestClient, created: dict, *, mode: str, physical: bool = True
) -> None:
    """Yönetici capability'siyle takip politikasını seçer ve kilitler."""
    tx_id = created["id"]
    manager_token = _extract_token(created["manager_link"])

    update = client.put(
        f"/api/transactions/{tx_id}/tracking-policy",
        json={
            "manager_token": manager_token,
            "physical_delivery_confirmed": physical,
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


def _prepare(client: TestClient, tmp_path: Path, *, mode: str) -> dict:
    created = _upload(client, tmp_path)
    _lock_policy(client, created, mode=mode)
    _approve_both(client, created)
    return created


def _post_e_irsaliye(client: TestClient, created: dict, quantity: float):
    """Seller token'ıyla gönderir (H0 hotfix: teslimat kanıtı artık yetkilendirme ister,
    bkz. `test_delivery_authorization.py` -- burada kimin gönderdiği değil, ne olduğu test edilir)."""
    return client.post(
        f"/api/transactions/{created['id']}/events/e-irsaliye",
        json={"delivered_quantity": quantity},
        params={"token": _extract_token(created["seller_link"])},
    )


def _post_video(client: TestClient, created: dict, filename: str):
    """Seller token'ıyla gönderir (H0 hotfix) -- bkz. `_post_e_irsaliye` notu."""
    return client.post(
        f"/api/transactions/{created['id']}/delivery-video",
        files={"file": (filename, io.BytesIO(b"fake-video-bytes"), "video/mp4")},
        params={"token": _extract_token(created["seller_link"])},
    )


def _finding_codes(decision: dict) -> list[str]:
    return [finding["code"] for finding in decision["findings"]]


def _event_types(client: TestClient, tx_id: str) -> list[str]:
    detail = client.get(f"/api/transactions/{tx_id}").json()
    return [event["event_type"] for event in detail["events"]]


# --- document_only: e-irsaliye birincil nicel kanıt --------------------------


def test_document_only_full_delivery_captures_without_any_video(
    client: TestClient, tmp_path: Path
) -> None:
    created = _prepare(client, tmp_path, mode="document_only")

    response = _post_e_irsaliye(client, created, 10)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "decided"
    assert body["decision"]["action"] == "capture"
    assert body["decision"]["capture_ratio"] == 1.0

    detail = client.get(f"/api/transactions/{created['id']}").json()
    assert detail["payment"][0]["status"] == "released"
    assert "delivery_video_analyzed" not in [e["event_type"] for e in detail["events"]]


def test_document_only_partial_delivery_ratio_comes_from_e_irsaliye(
    client: TestClient, tmp_path: Path
) -> None:
    created = _prepare(client, tmp_path, mode="document_only")

    body = _post_e_irsaliye(client, created, 6).json()

    assert body["decision"]["action"] == "partial_capture"
    assert body["decision"]["capture_ratio"] == pytest.approx(0.6)

    detail = client.get(f"/api/transactions/{created['id']}").json()
    assert detail["payment"][0]["status"] == "partially_released"


def test_document_only_rejects_video_upload(client: TestClient, tmp_path: Path) -> None:
    created = _prepare(client, tmp_path, mode="document_only")

    response = _post_video(client, created, "teslimat.mp4")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "TRACKING_NOT_ENABLED"


# --- document_and_video: video yalnızca ikincil sinyal -----------------------


def test_missing_advisory_video_does_not_block_capture(
    client: TestClient, tmp_path: Path
) -> None:
    created = _prepare(client, tmp_path, mode="document_and_video")

    body = _post_e_irsaliye(client, created, 10).json()

    assert body["decision"]["action"] == "capture"
    assert "VIDEO_NOT_PROVIDED" in _finding_codes(body["decision"])
    assert body["state"] == "decided"


def test_aligned_advisory_video_supports_capture_without_changing_ratio(
    client: TestClient, tmp_path: Path
) -> None:
    created = _prepare(client, tmp_path, mode="document_and_video")

    video = _post_video(client, created, "teslimat.mp4")
    assert video.status_code == 200, video.text
    # Video tek başına miktar üretemez: birincil kanıt gelene kadar hold.
    assert video.json()["decision"]["action"] == "hold"
    assert "MISSING_REQUIRED_EVIDENCE" in _finding_codes(video.json()["decision"])

    body = _post_e_irsaliye(client, created, 10).json()

    assert body["decision"]["action"] == "capture"
    assert body["decision"]["capture_ratio"] == 1.0
    assert "VIDEO_COUNT_ALIGNED" in _finding_codes(body["decision"])


def test_low_confidence_video_divergence_only_warns(client: TestClient, tmp_path: Path) -> None:
    created = _prepare(client, tmp_path, mode="document_and_video")

    # unit_count=7 ama güven eşiğin altında -> sayım sinyali karar verdirmez.
    _post_video(client, created, "teslimat_eksik_dusuk_guven.mp4")
    body = _post_e_irsaliye(client, created, 10).json()

    assert body["decision"]["action"] == "capture"
    assert body["decision"]["manual_review_required"] is False
    assert "VIDEO_LOW_CONFIDENCE" in _finding_codes(body["decision"])


def test_high_confidence_divergence_holds_without_release_or_dispute(
    client: TestClient, tmp_path: Path
) -> None:
    created = _prepare(client, tmp_path, mode="document_and_video")

    # unit_count=7, güven 0.9; e-irsaliye 10 -> |10-7|/10 = %30 > %10 eşiği.
    _post_video(client, created, "teslimat_eksik.mp4")
    body = _post_e_irsaliye(client, created, 10).json()

    assert body["decision"]["action"] == "hold"
    assert body["decision"]["capture_ratio"] == 0.0
    assert body["decision"]["manual_review_required"] is True
    assert "VIDEO_COUNT_DIVERGENCE" in _finding_codes(body["decision"])
    assert body["state"] == "evidence_pending"

    detail = client.get(f"/api/transactions/{created['id']}").json()
    event_types = [event["event_type"] for event in detail["events"]]
    assert "dispute_opened" not in event_types
    assert "mock_payment_executed" not in event_types
    assert all(payment["status"] == "pool" for payment in detail["payment"])


def test_matched_high_confidence_damage_holds_for_manual_review(
    client: TestClient, tmp_path: Path
) -> None:
    created = _prepare(client, tmp_path, mode="document_and_video")

    _post_video(client, created, "teslimat_hasarli.mp4")
    body = _post_e_irsaliye(client, created, 10).json()

    assert body["decision"]["action"] == "hold"
    assert body["decision"]["manual_review_required"] is True
    assert "VIDEO_DAMAGE_MATCHED" in _finding_codes(body["decision"])
    assert "dispute_opened" not in _event_types(client, created["id"])


# --- kanal guard'ları ve idempotency ----------------------------------------


def test_approval_only_transaction_rejects_e_irsaliye_channel(
    client: TestClient, tmp_path: Path
) -> None:
    created = _upload(client, tmp_path)
    _lock_policy(client, created, mode="off")
    assert _approve_both(client, created) == "decided"

    response = _post_e_irsaliye(client, created, 10)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "TRACKING_NOT_ENABLED"


def test_late_video_on_decided_transaction_is_rejected_before_analysis(
    client: TestClient, tmp_path: Path
) -> None:
    created = _prepare(client, tmp_path, mode="document_and_video")
    assert _post_e_irsaliye(client, created, 10).json()["state"] == "decided"

    response = _post_video(client, created, "teslimat.mp4")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "TRANSACTION_DECIDED"
    assert "delivery_video_analyzed" not in _event_types(client, created["id"])


def test_premature_evidence_before_approval_returns_409(
    client: TestClient, tmp_path: Path
) -> None:
    created = _upload(client, tmp_path)
    _lock_policy(client, created, mode="document_only")

    response = _post_e_irsaliye(client, created, 10)

    assert response.status_code == 409


def test_repeated_e_irsaliye_does_not_produce_a_second_release(
    client: TestClient, tmp_path: Path
) -> None:
    created = _prepare(client, tmp_path, mode="document_only")
    assert _post_e_irsaliye(client, created, 10).status_code == 200

    repeat = _post_e_irsaliye(client, created, 10)

    assert repeat.status_code == 409
    detail = client.get(f"/api/transactions/{created['id']}").json()
    assert len(detail["payment"]) == 1
    executed = [e for e in detail["events"] if e["event_type"] == "mock_payment_executed"]
    assert len(executed) == 1


# --- sözleşmesel video: yönetici kapatamaz -----------------------------------


def test_contractual_video_cannot_be_disabled_and_holds_until_video_arrives(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    patch_extraction(monkeypatch, contractual_video_contract())
    created = _upload(client, tmp_path)
    manager_token = _extract_token(created["manager_link"])

    for rejected_mode in ("off", "document_only"):
        attempt = client.put(
            f"/api/transactions/{created['id']}/tracking-policy",
            json={
                "manager_token": manager_token,
                "physical_delivery_confirmed": True,
                "tracking_mode": rejected_mode,
            },
        )
        assert attempt.status_code == 409, rejected_mode
        assert attempt.json()["detail"]["code"] == "POLICY_CONTRACT_CONFLICT"

    _lock_policy(client, created, mode="document_and_video")
    _approve_both(client, created)

    # Sözleşmesel video hâlâ zorunlu: e-irsaliye tek başına release üretmez.
    e_irsaliye = _post_e_irsaliye(client, created, 10).json()
    assert e_irsaliye["decision"]["action"] == "hold"
    assert "MISSING_REQUIRED_EVIDENCE" in _finding_codes(e_irsaliye["decision"])

    video = _post_video(client, created, "teslimat.mp4")
    assert video.status_code == 200, video.text
    assert video.json()["decision"]["action"] == "capture"


def test_contractual_video_anomaly_blocks_release(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zorunlu video yalnızca "geldi mi?" diye sayılmaz; hasar sinyali release'i durdurur."""
    patch_extraction(monkeypatch, contractual_video_contract())
    created = _upload(client, tmp_path)
    _lock_policy(client, created, mode="document_and_video")
    _approve_both(client, created)

    _post_e_irsaliye(client, created, 10)
    body = _post_video(client, created, "teslimat_hasarli.mp4").json()

    assert body["decision"]["action"] == "hold"
    assert body["decision"]["manual_review_required"] is True
    assert "VIDEO_DAMAGE_MATCHED" in _finding_codes(body["decision"])
    assert body["state"] == "evidence_pending"

    detail = client.get(f"/api/transactions/{created['id']}").json()
    event_types = [event["event_type"] for event in detail["events"]]
    assert "mock_payment_executed" not in event_types
    assert "dispute_opened" not in event_types
    assert all(payment["status"] == "pool" for payment in detail["payment"])


# --- evidence bundle ---------------------------------------------------------


def test_evidence_bundle_carries_policy_snapshot_without_raw_markdown_or_tokens(
    client: TestClient, tmp_path: Path
) -> None:
    created = _prepare(client, tmp_path, mode="document_only")
    _post_e_irsaliye(client, created, 10)

    response = client.get(
        f"/api/transactions/{created['id']}/evidence",
        params={"token": _extract_token(created["buyer_link"])},
    )
    assert response.status_code == 200, response.text
    bundle = response.json()

    assert bundle["transaction"]["id"] == created["id"]
    assert bundle["decision"]["action"] == "capture"
    assert bundle["tracking_policy"]["tracking_mode"] == "document_only"
    assert bundle["tracking_policy"]["status"] == "locked"
    assert "generated_at" in bundle

    serialized = str(bundle)
    assert _SAMPLE_MARKDOWN not in serialized
    assert "Alıcı ile Satıcı arasında endüstriyel pompa" not in serialized
    for link in ("buyer_link", "seller_link", "manager_link"):
        assert _extract_token(created[link]) not in serialized
