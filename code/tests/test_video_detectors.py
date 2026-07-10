from unittest.mock import patch

from backend.app.services.video.detectors import (
    BOX_PALLET_MODEL_ID,
    DAMAGE_MODEL_ID,
    BoxPalletDetector,
    DamageDetector,
)
from backend.app.services.video.interfaces import Detection


def fake_detection():
    return [Detection(class_name="cardboard box", confidence=0.9, x=1, y=2, width=3, height=4)]


def test_box_pallet_detector_calls_correct_model_id(tmp_path):
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"x")

    with patch(
        "backend.app.services.video.detectors.roboflow_client.infer", return_value=fake_detection()
    ) as mock_infer:
        detector = BoxPalletDetector(api_key="key123")
        result = detector.detect(image_path)

    mock_infer.assert_called_once_with(image_path, BOX_PALLET_MODEL_ID, "key123")
    assert result == fake_detection()


def test_damage_detector_calls_correct_model_id(tmp_path):
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"x")

    with patch(
        "backend.app.services.video.detectors.roboflow_client.infer", return_value=[]
    ) as mock_infer:
        detector = DamageDetector(api_key="key123")
        detector.detect(image_path)

    mock_infer.assert_called_once_with(image_path, DAMAGE_MODEL_ID, "key123")


def test_detector_accepts_custom_model_id(tmp_path):
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"x")

    with patch(
        "backend.app.services.video.detectors.roboflow_client.infer", return_value=[]
    ) as mock_infer:
        detector = BoxPalletDetector(api_key="key123", model_id="custom-model/3")
        detector.detect(image_path)

    mock_infer.assert_called_once_with(image_path, "custom-model/3", "key123")
