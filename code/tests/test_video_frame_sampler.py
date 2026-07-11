import pytest

cv2 = pytest.importorskip("cv2", reason="Opsiyonel video profili kurulu değil")
np = pytest.importorskip("numpy", reason="Opsiyonel video profili kurulu değil")

from backend.app.services.video.exceptions import VideoAnalyzerError
from backend.app.services.video.frame_sampler import extract_frames


def make_video(tmp_path, num_frames=30, fps=30, size=(64, 64)):
    """Sentetik test videosu üretir.

    Yazılabilir codec ortama göre değişir (örn. macOS/AVFoundation OpenCV
    build'i `mp4v` yazamıyor ve writer sessizce açılmıyor — dosya hiç
    oluşmuyor); sırayla dener, hiçbiri açılmazsa testi atlar. `extract_frames`
    okurken uzantıya bakmaz, `.avi` de geçerli bir girdidir.
    """
    candidates = [("mp4v", ".mp4"), ("MJPG", ".avi"), ("avc1", ".mp4")]
    for fourcc_name, ext in candidates:
        path = tmp_path / f"sample{ext}"
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*fourcc_name), fps, size)
        if not writer.isOpened():
            writer.release()
            continue
        for i in range(num_frames):
            frame = np.full((size[1], size[0], 3), fill_value=i % 255, dtype=np.uint8)
            writer.write(frame)
        writer.release()
        return path
    pytest.skip("OpenCV bu ortamda hiçbir test codec'iyle video yazamıyor")


def test_extract_frames_samples_at_requested_rate(tmp_path):
    video_path = make_video(tmp_path, num_frames=30, fps=30)

    frames = extract_frames(video_path, sample_fps=1.0)

    assert 1 <= len(frames) <= 2
    for frame_path in frames:
        assert frame_path.exists()


def test_extract_frames_raises_for_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        extract_frames(tmp_path / "missing.mp4")


def test_extract_frames_raises_for_unreadable_file(tmp_path):
    bad_path = tmp_path / "not_a_video.mp4"
    bad_path.write_text("this is not a real video")
    with pytest.raises(VideoAnalyzerError):
        extract_frames(bad_path)


def test_extract_frames_count_scales_with_sample_fps(tmp_path):
    """3 saniyelik (90 kare, 30fps) sentetik videoda örnekleme oranı arttıkça
    çıkan kare sayısı da orantılı artmalı (frame_interval = native_fps/sample_fps)."""
    video_path = make_video(tmp_path, num_frames=90, fps=30)

    sparse = extract_frames(video_path, sample_fps=1.0)
    dense = extract_frames(video_path, sample_fps=3.0)

    assert len(dense) > len(sparse)
    # ~3 kare (1 fps) vs ~9 kare (3 fps) -- codec/timestamp yuvarlamasına tolerans bırakılır.
    assert 2 <= len(sparse) <= 4
    assert 7 <= len(dense) <= 11


def test_extract_frames_returns_readable_jpegs_in_capture_order(tmp_path):
    """Döndürülen kare dosyaları hem gerçek okunabilir JPEG olmalı hem de
    videodaki sırayla (artan piksel değeriyle) gelmeli -- analyzer'ın kare
    bazlı agregasyonu dosya adı sırasına güvenir."""
    video_path = make_video(tmp_path, num_frames=30, fps=30)

    frames = extract_frames(video_path, sample_fps=1.0)

    assert frames == sorted(frames)
    pixel_values = []
    for frame_path in frames:
        image = cv2.imread(str(frame_path))
        assert image is not None
        pixel_values.append(int(image[0, 0, 0]))
    assert pixel_values == sorted(pixel_values)
