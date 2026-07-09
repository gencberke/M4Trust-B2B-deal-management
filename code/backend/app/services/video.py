"""VideoAnalyzer adapter — teslimat videosundan sayım/hasar sinyali çıkarır (§3.4).

`VideoAnalyzer` gerçek bir görüntü işleme servisinin arayüzünü tanımlar;
`FakeVideoAnalyzer` hiçbir video işlemez, demo senaryolarını sürebilmek için
dosya adındaki ipuçlarına bakar (§6.3 adapter+fake ilkesi). Video tek başına
ödeme kararı veremez — yalnızca `decision.DeliveryEvidence.video` girdisidir.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from backend.app.config import Settings


class VideoAnalyzer(ABC):
    """Teslimat videosu analiz adaptörünün arayüzü."""

    @abstractmethod
    def analyze(self, video_path: str | Path) -> dict:
        """Videoyu analiz eder, `{"counts": int, "damage_signals": list, "confidence": float}` döner."""


class FakeVideoAnalyzer(VideoAnalyzer):
    """Gerçek görüntü işleme yapmayan sahte analizör.

    Dosya adı ipucu kuralları (demo senaryolarını sürebilmek için):
    - varsayılan (ipucu yok)              -> counts=10, damage_signals=[],            confidence=0.9
    - dosya adında "eksik" geçiyorsa      -> counts=7,  damage_signals=[],            confidence=0.9  (kısmi/çelişki senaryosu)
    - dosya adında "hasarli" geçiyorsa    -> counts=10, damage_signals=["hasar_tespiti"], confidence=0.9  (dispute senaryosu)
    İki ipucu da geçiyorsa "hasarli" önceliklidir (hasar sinyali tek başına dispute tetikler).
    """

    def analyze(self, video_path: str | Path) -> dict:
        name = Path(video_path).name.lower()

        if "hasarli" in name:
            return {"counts": 10, "damage_signals": ["hasar_tespiti"], "confidence": 0.9}
        if "eksik" in name:
            return {"counts": 7, "damage_signals": [], "confidence": 0.9}
        return {"counts": 10, "damage_signals": [], "confidence": 0.9}


def make_video_analyzer(settings: Settings) -> VideoAnalyzer:
    """`settings.video_analyzer`'a göre adaptör seçer (§3.4 seçim env'i)."""

    if settings.video_analyzer == "fake":
        return FakeVideoAnalyzer()
    raise NotImplementedError(f"Bilinmeyen video analyzer: {settings.video_analyzer}")
