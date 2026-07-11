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
    # Teslim birimi sayımı taşıyıcı sınıfları (palet) DIŞLAR (§3.4 unit_count).
    assert result["unit_count"] == 2
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
    assert result["unit_count"] == 2


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


def test_fake_analyzer_filename_hints_drive_demo_scenarios(tmp_path):
    """Dosya adı ipuçları ikincil video dallarını sürer (§3.4): uyumlu/ayrışan/hasar/düşük güven."""
    analyzer = FakeVideoAnalyzer()

    default = analyzer.analyze(tmp_path / "teslimat.mp4")
    assert default["unit_count"] == 10
    assert default["damage_signals"] == []
    assert default["confidence"] == 0.9

    eksik = analyzer.analyze(tmp_path / "teslimat_eksik.mp4")
    assert eksik["unit_count"] == 7
    assert eksik["damage_signals"] == []
    assert eksik["confidence"] == 0.9

    hasarli = analyzer.analyze(tmp_path / "teslimat_hasarli.mp4")
    assert hasarli["unit_count"] == 10
    assert [s["type"] for s in hasarli["damage_signals"]] == ["hasar_tespiti"]
    assert hasarli["damage_signals"][0]["matched_box"] is True

    # İki ipucu birden: "hasarli" kazanır (sayım ipucu ezilir).
    both = analyzer.analyze(tmp_path / "teslimat_eksik_hasarli.mp4")
    assert both["unit_count"] == 10
    assert both["damage_signals"]

    # Düşük güven ipucu diğerlerinden bağımsızdır: sayım korunur, güven düşer.
    dusuk = analyzer.analyze(tmp_path / "teslimat_eksik_dusuk_guven.mp4")
    assert dusuk["unit_count"] == 7
    assert dusuk["confidence"] == 0.5


def test_make_video_analyzer_returns_fake_by_default():
    settings = Settings(video_provider="fake")
    analyzer = make_video_analyzer(settings)
    assert isinstance(analyzer, FakeVideoAnalyzer)


def test_make_video_analyzer_returns_roboflow_when_configured():
    settings = Settings(video_provider="roboflow", roboflow_api_key="key123")
    analyzer = make_video_analyzer(settings)
    assert isinstance(analyzer, RoboflowVideoAnalyzer)


# --- ek senaryolar: sahte video/foto ipuçları + Roboflow edge-case'leri ---


def test_fake_analyzer_filename_hints_are_case_insensitive():
    """Dosya adı büyük/karışık harfle gelse de ipuçları aynı şekilde tanınmalı."""
    analyzer = FakeVideoAnalyzer()

    result = analyzer.analyze(Path("TESLIMAT_HASARLI.MP4"))
    assert [s["type"] for s in result["damage_signals"]] == ["hasar_tespiti"]

    result = analyzer.analyze(Path("Teslimat_Eksik.Mp4"))
    assert result["unit_count"] == 7


def test_fake_analyzer_hints_work_identically_for_photo_extensions(tmp_path):
    """Fake analyzer uzantıya bakmaz -- ipuçları .jpg/.png foto için de aynı sonucu üretmeli
    (Roboflow'un aksine, fake analyzer video/foto ayrımı yapmaz)."""
    analyzer = FakeVideoAnalyzer()

    video_result = analyzer.analyze(tmp_path / "teslimat_hasarli.mp4")
    photo_result = analyzer.analyze(tmp_path / "teslimat_hasarli.jpg")

    assert video_result["unit_count"] == photo_result["unit_count"]
    assert [s["type"] for s in video_result["damage_signals"]] == [
        s["type"] for s in photo_result["damage_signals"]
    ]


def test_analyze_image_with_no_detections_reports_zero_confidence(tmp_path):
    """Hiç koli/hasar tespiti yoksa (boş/karanlık fotoğraf) confidence 0'a düşmeli,
    ortalamanın 0/0'a bölünmesi (ZeroDivisionError) yaşanmamalı."""
    image_path = tmp_path / "bos_fotograf.jpg"
    image_path.write_bytes(b"x")
    analyzer = RoboflowVideoAnalyzer(
        api_key="key", box_detector=FakeDetector([]), damage_detector=FakeDetector([])
    )

    result = analyzer.analyze(image_path)

    assert result["counts"] == {}
    assert result["unit_count"] == 0
    assert result["damage_signals"] == []
    assert result["confidence"] == 0.0


def test_analyze_image_merges_counts_across_class_name_casing(tmp_path):
    """Model bazen 'Cardboard Box' bazen 'cardboard box' dönebilir -- sayım
    büyük/küçük harften bağımsız tek sınıf altında toplanmalı (aksi halde
    unit_count yanlış bölünmüş görünür)."""
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"x")
    boxes = [
        det(100, 100, "Cardboard Box", 0.9),
        det(300, 300, "cardboard box", 0.8),
    ]
    analyzer = RoboflowVideoAnalyzer(
        api_key="key", box_detector=FakeDetector(boxes), damage_detector=FakeDetector([])
    )

    result = analyzer.analyze(image_path)

    assert result["counts"] == {"cardboard box": 2}
    assert result["unit_count"] == 2


def test_damage_on_carrier_class_box_still_produces_signal_despite_unit_count_exclusion(tmp_path):
    """Palet (taşıyıcı sınıf) unit_count'a girmez ama üzerindeki hasar sinyali
    kaybolmamalı -- decision engine risk sinyalini görebilmeli (§3.4)."""
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"x")
    boxes = [det(100, 100, "wood pallet", 0.9, w=200, h=200)]
    damages = [det(100, 100, "wet", 0.5, w=10, h=10)]
    analyzer = RoboflowVideoAnalyzer(
        api_key="key", box_detector=FakeDetector(boxes), damage_detector=FakeDetector(damages)
    )

    result = analyzer.analyze(image_path)

    assert result["unit_count"] == 0
    assert [s["type"] for s in result["damage_signals"]] == ["wet"]
    assert result["damage_signals"][0]["matched_box"] is True


def test_analyze_dispatches_image_for_non_mp4_photo_extensions(tmp_path):
    """.png/.jpeg gibi diğer foto uzantıları da görsel yoluna gitmeli, video'ya değil."""
    analyzer = RoboflowVideoAnalyzer(
        api_key="key", box_detector=FakeDetector([]), damage_detector=FakeDetector([])
    )

    for suffix in (".png", ".jpeg", ".JPG"):
        image_path = tmp_path / f"delivery{suffix}"
        image_path.write_bytes(b"x")
        with patch.object(analyzer, "_analyze_video") as mock_video, patch.object(
            analyzer, "_analyze_image"
        ) as mock_image:
            analyzer.analyze(image_path)
            mock_image.assert_called_once()
            mock_video.assert_not_called()


def test_analyze_dispatches_video_for_uppercase_video_extension(tmp_path):
    """Uzantı büyük harfle gelse bile (.MP4) video yoluna gitmeli."""
    analyzer = RoboflowVideoAnalyzer(
        api_key="key", box_detector=FakeDetector([]), damage_detector=FakeDetector([])
    )
    video_path = tmp_path / "delivery.MP4"
    video_path.write_bytes(b"x")

    with patch.object(analyzer, "_analyze_video") as mock_video, patch.object(
        analyzer, "_analyze_image"
    ) as mock_image:
        analyzer.analyze(video_path)
        mock_video.assert_called_once()
        mock_image.assert_not_called()
