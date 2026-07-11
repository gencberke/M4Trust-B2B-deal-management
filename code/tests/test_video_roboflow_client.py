import base64
from unittest.mock import MagicMock, patch

import pytest
import requests

from backend.app.services.video import roboflow_client
from backend.app.services.video.exceptions import RoboflowAPIError


def make_response(json_body, status_ok=True):
    response = MagicMock()
    response.json.return_value = json_body
    if status_ok:
        response.raise_for_status = MagicMock()
    else:
        response.raise_for_status.side_effect = requests.HTTPError("bad status")
    return response


def test_infer_parses_predictions_into_detections(tmp_path):
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake image bytes")

    payload = {
        "predictions": [
            {"class": "cardboard box", "confidence": 0.9, "x": 10, "y": 20, "width": 30, "height": 40}
        ]
    }

    with patch(
        "backend.app.services.video.roboflow_client.requests.post", return_value=make_response(payload)
    ) as mock_post:
        detections = roboflow_client.infer(image_path, "some-model/1", api_key="key123")

    assert len(detections) == 1
    assert detections[0].class_name == "cardboard box"
    assert detections[0].confidence == 0.9

    args, kwargs = mock_post.call_args
    assert args[0] == "https://serverless.roboflow.com/some-model/1"
    assert kwargs["params"] == {"api_key": "key123"}


def test_infer_returns_empty_list_when_no_predictions(tmp_path):
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake image bytes")

    with patch(
        "backend.app.services.video.roboflow_client.requests.post",
        return_value=make_response({"predictions": []}),
    ):
        detections = roboflow_client.infer(image_path, "some-model/1", api_key="key123")

    assert detections == []


def test_infer_raises_roboflow_api_error_on_http_failure(tmp_path):
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake image bytes")

    with patch(
        "backend.app.services.video.roboflow_client.requests.post",
        return_value=make_response({}, status_ok=False),
    ):
        with pytest.raises(RoboflowAPIError):
            roboflow_client.infer(image_path, "some-model/1", api_key="key123")


def test_infer_raises_file_not_found_for_missing_image(tmp_path):
    missing_path = tmp_path / "missing.jpg"
    with pytest.raises(FileNotFoundError):
        roboflow_client.infer(missing_path, "some-model/1", api_key="key123")


def test_infer_sends_base64_encoded_body_with_expected_headers_and_timeout(tmp_path):
    """İstek gövdesinin gerçekten görselin base64'ü olduğunu, form-encoded
    header'ı ve zaman aşımını doğrular -- yalnız URL/params kontrolü, gövdenin
    ham byte'ları mı yoksa yanlışlıkla dosya yolunu mu gönderdiğimizi yakalamaz."""
    image_bytes = b"\xff\xd8\xff\xe0fake-jpeg-bytes"
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(image_bytes)

    payload = {"predictions": []}
    with patch(
        "backend.app.services.video.roboflow_client.requests.post",
        return_value=make_response(payload),
    ) as mock_post:
        roboflow_client.infer(image_path, "some-model/1", api_key="key123")

    args, kwargs = mock_post.call_args
    assert args[0] == "https://serverless.roboflow.com/some-model/1"
    assert kwargs["params"] == {"api_key": "key123"}
    assert kwargs["data"] == base64.b64encode(image_bytes).decode("ascii")
    assert kwargs["headers"] == {"Content-Type": "application/x-www-form-urlencoded"}
    assert kwargs["timeout"] == roboflow_client.REQUEST_TIMEOUT_SECONDS


def test_infer_encodes_different_image_bytes_to_different_bodies(tmp_path):
    """Base64 kodlamasının gerçekten dosya içeriğine bağlı olduğunu doğrular
    (sabit/placeholder bir string gönderilmediğinden emin olmak için)."""
    path_a = tmp_path / "a.jpg"
    path_b = tmp_path / "b.jpg"
    path_a.write_bytes(b"content-a")
    path_b.write_bytes(b"content-b-different-length")

    bodies = []
    with patch(
        "backend.app.services.video.roboflow_client.requests.post",
        return_value=make_response({"predictions": []}),
    ) as mock_post:
        roboflow_client.infer(path_a, "some-model/1", api_key="key123")
        bodies.append(mock_post.call_args.kwargs["data"])
        roboflow_client.infer(path_b, "some-model/1", api_key="key123")
        bodies.append(mock_post.call_args.kwargs["data"])

    assert bodies[0] != bodies[1]
    assert bodies[0] == base64.b64encode(b"content-a").decode("ascii")
    assert bodies[1] == base64.b64encode(b"content-b-different-length").decode("ascii")


@pytest.mark.parametrize(
    "network_exception",
    [
        requests.exceptions.ConnectionError("dns çözümlenemedi"),
        requests.exceptions.Timeout("30 saniye içinde cevap gelmedi"),
    ],
)
def test_infer_wraps_network_level_failures_before_any_response(
    tmp_path, network_exception: Exception
) -> None:
    """`raise_for_status()`'a hiç ulaşmadan, `requests.post()`'un kendisi
    patladığında (DNS/timeout/bağlantı kopması) da `RoboflowAPIError`'a
    sarılmalı -- mevcut testler yalnız 'cevap geldi ama status kötüydü'
    dalını kapsıyordu, 'cevap hiç gelmedi' dalını değil."""
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake image bytes")

    with patch(
        "backend.app.services.video.roboflow_client.requests.post",
        side_effect=network_exception,
    ):
        with pytest.raises(RoboflowAPIError) as exc_info:
            roboflow_client.infer(image_path, "some-model/1", api_key="key123")

    assert "some-model/1" in str(exc_info.value)


def test_infer_omits_api_key_from_error_message_on_failure(tmp_path):
    """Hata mesajına yalnızca model_id/exception metni girer -- `api_key` asla
    loglara/hata mesajına sızmamalı (secret hygiene)."""
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake image bytes")

    with patch(
        "backend.app.services.video.roboflow_client.requests.post",
        side_effect=requests.exceptions.ConnectionError("boom"),
    ):
        with pytest.raises(RoboflowAPIError) as exc_info:
            roboflow_client.infer(image_path, "some-model/1", api_key="super-secret-key-999")

    assert "super-secret-key-999" not in str(exc_info.value)


def test_infer_propagates_roboflow_api_error_unchanged_through_detectors(tmp_path):
    """`BoxPalletDetector`/`DamageDetector` yalnızca ince bir sarmalayıcıdır --
    `roboflow_client.infer`'ın fırlattığı `RoboflowAPIError`'ı yutmadan/
    tipini değiştirmeden olduğu gibi yukarı taşımalı."""
    from backend.app.services.video.detectors import BoxPalletDetector, DamageDetector

    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake image bytes")

    with patch(
        "backend.app.services.video.roboflow_client.requests.post",
        side_effect=requests.exceptions.ConnectionError("boom"),
    ):
        with pytest.raises(RoboflowAPIError):
            BoxPalletDetector(api_key="key123").detect(image_path)
        with pytest.raises(RoboflowAPIError):
            DamageDetector(api_key="key123").detect(image_path)
