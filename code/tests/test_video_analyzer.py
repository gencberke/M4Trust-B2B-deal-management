from pathlib import Path
from unittest.mock import patch

from backend.app.config import Settings
from backend.app.services.video.analyzer import (
    FakeVideoAnalyzer,
    RoboflowVideoAnalyzer,
    make_video_analyzer,
)
from backend.app.services.video.interfaces import Detection


def det(x, y, class_name, confidence, w=100, h=100):
    return Detection(class_name=class_name, confidence=confidence, x=x, y=y, width=w, height=h)


class FakeDetector:
    def __init__(self, detections):
        self._detections = detections

    def detect(self, image_path):
        return self._detections


class PerFramePathDetector:
    """Frame yoluna göre farklı tespitler döndürür -- farklı frame'lerin
    farklı şeyler gördüğü bir videoyu simüle etmek için."""

    def __init__(self, by_path):
        self._by_path = by_path

    def detect(self, path):
        return self._by_path.get(Path(path).name, [])


# --- görsel analiz (tek fotoğraf) ---


def test_analyze_image_counts_boxes_and_pallets_separately(tmp_path):
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"x")
    boxes = [
        det(100, 100, "cardboard box", 0.9),
        det(300, 300, "cardboard box", 0.8),
        det(500, 500, "wood pallet", 0.7),
    ]
    analyzer = RoboflowVideoAnalyzer(
        api_key="key", box_detector=FakeDetector(boxes), damage_detector=FakeDetector([])
    )

    result = analyzer.analyze(image_path)

    assert result["counts"] == {"cardboard box": 2, "wood pallet": 1}
    assert result["damage_signals"] == []


def test_analyze_image_reports_matched_and_unmatched_damage(tmp_path):
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"x")
    boxes = [det(100, 100, "cardboard box", 0.9, w=50, h=50)]
    damages = [
        det(100, 100, "hole", 0.6, w=5, h=5),
        det(900, 900, "wet", 0.5, w=5, h=5),
    ]
    analyzer = RoboflowVideoAnalyzer(
        api_key="key", box_detector=FakeDetector(boxes), damage_detector=FakeDetector(damages)
    )

    result = analyzer.analyze(image_path)

    matched = [s for s in result["damage_signals"] if s["matched_box"]]
    unmatched = [s for s in result["damage_signals"] if not s["matched_box"]]
    assert len(matched) == 1 and matched[0]["type"] == "hole"
    assert len(unmatched) == 1 and unmatched[0]["type"] == "wet"


# --- video analiz (kare örnekleme + agregasyon) ---


def test_analyze_video_takes_max_count_across_frames(tmp_path):
    frame1 = tmp_path / "frame_00000.jpg"
    frame2 = tmp_path / "frame_00001.jpg"
    frame1.write_bytes(b"x")
    frame2.write_bytes(b"x")

    box_detector = PerFramePathDetector(
        {
            "frame_00000.jpg": [det(100, 100, "cardboard box", 0.9)],
            "frame_00001.jpg": [
                det(100, 100, "cardboard box", 0.9),
                det(300, 300, "cardboard box", 0.8),
            ],
        }
    )
    analyzer = RoboflowVideoAnalyzer(
        api_key="key", box_detector=box_detector, damage_detector=PerFramePathDetector({})
    )

    with patch(
        "backend.app.services.video.analyzer.extract_frames", return_value=[frame1, frame2]
    ):
        result = analyzer.analyze(tmp_path / "fake.mp4")

    # frame2'de 2 koli, frame1'de 1 -- kareler arası maksimum kazanır, toplam değil
    assert result["counts"] == {"cardboard box": 2}


def test_analyze_video_unions_damage_signals_across_frames(tmp_path):
    frame1 = tmp_path / "frame_00000.jpg"
    frame2 = tmp_path / "frame_00001.jpg"
    frame1.write_bytes(b"x")
    frame2.write_bytes(b"x")

    box_detector = PerFramePathDetector(
        {
            "frame_00000.jpg": [det(100, 100, "cardboard box", 0.9, w=50, h=50)],
            "frame_00001.jpg": [det(100, 100, "cardboard box", 0.9, w=50, h=50)],
        }
    )
    damage_detector = PerFramePathDetector(
        {
            "frame_00000.jpg": [det(100, 100, "hole", 0.6, w=5, h=5)],
            "frame_00001.jpg": [det(900, 900, "wet", 0.4, w=5, h=5)],
        }
    )
    analyzer = RoboflowVideoAnalyzer(api_key="key", box_detector=box_detector, damage_detector=damage_detector)

    with patch(
        "backend.app.services.video.analyzer.extract_frames", return_value=[frame1, frame2]
    ):
        result = analyzer.analyze(tmp_path / "fake.mp4")

    types = sorted(s["type"] for s in result["damage_signals"])
    assert types == ["hole", "wet"]


def test_analyze_video_cleans_up_frame_directory(tmp_path):
    frame_dir = tmp_path / "frames"
    frame_dir.mkdir()
    frame1 = frame_dir / "frame_00000.jpg"
    frame1.write_bytes(b"x")

    analyzer = RoboflowVideoAnalyzer(
        api_key="key",
        box_detector=PerFramePathDetector({"frame_00000.jpg": []}),
        damage_detector=PerFramePathDetector({}),
    )

    with patch("backend.app.services.video.analyzer.extract_frames", return_value=[frame1]):
        analyzer.analyze(tmp_path / "fake.mp4")

    assert not frame_dir.exists()


def test_analyze_video_raises_when_no_frames_sampled(tmp_path):
    analyzer = RoboflowVideoAnalyzer(
        api_key="key", box_detector=PerFramePathDetector({}), damage_detector=PerFramePathDetector({})
    )

    with patch("backend.app.services.video.analyzer.extract_frames", return_value=[]):
        try:
            analyzer.analyze(tmp_path / "fake.mp4")
            assert False, "ValueError bekleniyordu"
        except ValueError:
            pass


def test_analyze_dispatches_by_extension_video_vs_image(tmp_path):
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"x")
    analyzer = RoboflowVideoAnalyzer(
        api_key="key", box_detector=FakeDetector([]), damage_detector=FakeDetector([])
    )

    with patch.object(analyzer, "_analyze_video") as mock_video, patch.object(
        analyzer, "_analyze_image"
    ) as mock_image:
        analyzer.analyze(tmp_path / "delivery.mp4")
        mock_video.assert_called_once()
        mock_image.assert_not_called()

        mock_video.reset_mock()
        analyzer.analyze(image_path)
        mock_image.assert_called_once()
        mock_video.assert_not_called()


# --- Fake + factory ---


def test_fake_video_analyzer_returns_canned_result_without_network(tmp_path):
    analyzer = FakeVideoAnalyzer()
    result = analyzer.analyze(tmp_path / "anything.jpg")
    assert result["counts"]
    assert result["confidence"] > 0


def test_make_video_analyzer_returns_fake_by_default():
    settings = Settings(video_provider="fake")
    analyzer = make_video_analyzer(settings)
    assert isinstance(analyzer, FakeVideoAnalyzer)


def test_make_video_analyzer_returns_roboflow_when_configured():
    settings = Settings(video_provider="roboflow", roboflow_api_key="key123")
    analyzer = make_video_analyzer(settings)
    assert isinstance(analyzer, RoboflowVideoAnalyzer)
