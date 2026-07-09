"""Teslimat kanıtı analiz servisi: fotoğraf/video üzerinden koli/palet sayımı
ve hasar sinyali üretir (ARCHITECTURE.md §3.4, "VideoAnalyzer").
"""

from .analyzer import FakeVideoAnalyzer, RoboflowVideoAnalyzer, VideoAnalyzer, make_video_analyzer
from .exceptions import RoboflowAPIError, VideoAnalyzerError
from .interfaces import Detection, Detector

__all__ = [
    "VideoAnalyzer",
    "FakeVideoAnalyzer",
    "RoboflowVideoAnalyzer",
    "make_video_analyzer",
    "Detection",
    "Detector",
    "VideoAnalyzerError",
    "RoboflowAPIError",
]
