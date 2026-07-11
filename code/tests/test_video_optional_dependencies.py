"""OpenCV olmadan video servislerinin import ve hata davranışı."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from backend.app.services.video.analyzer import FakeVideoAnalyzer
from backend.app.services.video.exceptions import VideoAnalyzerError
from backend.app.services.video.frame_sampler import extract_frames


def test_fake_analyzer_remains_available_without_opencv(tmp_path: Path) -> None:
    with patch("backend.app.services.video.frame_sampler.import_module", side_effect=ModuleNotFoundError):
        result = FakeVideoAnalyzer().analyze(tmp_path / "teslimat.jpg")
    assert result["unit_count"] == 10


def test_real_frame_sampling_reports_missing_optional_profile(tmp_path: Path) -> None:
    video = tmp_path / "teslimat.mp4"
    video.write_bytes(b"not-read-because-opencv-is-missing")

    with patch("backend.app.services.video.frame_sampler.import_module", side_effect=ModuleNotFoundError):
        with pytest.raises(VideoAnalyzerError, match="requirements-video.txt"):
            extract_frames(video)
