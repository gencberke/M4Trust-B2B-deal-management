"""Bir teslimat videosundan sabit bir örnekleme oranında durağan kareler çıkarır.

Kareler geçici bir klasöre JPEG olarak yazılır ki mevcut görsel-tabanlı
detector/analyzer (dosya yolu bekleyen) değişmeden çalışabilsin -- video
desteği tespit katmanı yeniden yazılmadan üzerine eklenir.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import cv2

from .exceptions import VideoAnalyzerError

logger = logging.getLogger(__name__)

DEFAULT_SAMPLE_FPS = 1.0


def extract_frames(video_path: Path, sample_fps: float = DEFAULT_SAMPLE_FPS) -> list[Path]:
    """Videodan saniyede `sample_fps` kare örnekler, dosya yollarını döndürür.

    Çağıran, işi bitince kare dosyalarının üst klasörünü (frame_paths[0].parent)
    silmekten sorumludur.
    """
    video_path = Path(video_path)
    if not video_path.exists():
        raise FileNotFoundError(video_path)

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise VideoAnalyzerError(f"Video dosyası açılamadı: {video_path}")

    native_fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    frame_interval = max(1, round(native_fps / sample_fps))

    out_dir = Path(tempfile.mkdtemp(prefix="m4trust_frames_"))
    frame_paths: list[Path] = []

    frame_index = 0
    saved_index = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index % frame_interval == 0:
                frame_path = out_dir / f"frame_{saved_index:05d}.jpg"
                cv2.imwrite(str(frame_path), frame)
                frame_paths.append(frame_path)
                saved_index += 1
            frame_index += 1
    finally:
        capture.release()

    logger.info(
        "%s videosundan %d kare örneklendi (~%.1f fps native, her %d karede bir)",
        video_path.name,
        len(frame_paths),
        native_fps,
        frame_interval,
    )
    return frame_paths
