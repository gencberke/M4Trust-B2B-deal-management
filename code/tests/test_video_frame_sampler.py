import cv2
import numpy as np
import pytest

from backend.app.services.video.exceptions import VideoAnalyzerError
from backend.app.services.video.frame_sampler import extract_frames


def make_video(tmp_path, num_frames=30, fps=30, size=(64, 64)):
    path = tmp_path / "sample.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    for i in range(num_frames):
        frame = np.full((size[1], size[0], 3), fill_value=i % 255, dtype=np.uint8)
        writer.write(frame)
    writer.release()
    return path


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
