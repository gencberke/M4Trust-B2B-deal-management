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
