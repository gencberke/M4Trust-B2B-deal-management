"""VideoAnalyzer — teslimat kanıtından (fotoğraf veya video) obje sayımı ve
hasar sinyali üretir.

Fake ve canlı (Roboflow-tabanlı) iki implementasyon aynı arayüzü paylaşır
(§3 adapter+fake ilkesi). ARCHITECTURE.md §3.4:

    analyze(media_path) -> {counts, unit_count, damage_signals, confidence}
    -> delivery_video_analyzed event'i

`counts` sınıf başına ham dökümdür (kanıt/UI); `unit_count` taşıyıcı sınıflar
(palet) HARİÇ teslim birimi sayısıdır — decision engine yalnızca onu okur,
model sınıf adlarını bilmez. Video tek başına ödeme kararı veremez; ikincil
risk sinyalidir.
"""

from __future__ import annotations

import logging
import shutil
from abc import ABC, abstractmethod
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from backend.app.config import Settings

from .correlator import correlate
from .detectors import BoxPalletDetector, DamageDetector
from .frame_sampler import DEFAULT_SAMPLE_FPS, extract_frames

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

# Taşıyıcı/ambalaj sınıfları teslim birimi sayılmaz: sözleşmeler koliyi/adedi
# sayar, paleti değil. Sınıf→birim ayrımı bu adapter katmanında yapılır ki
# decision.py model etiketlerinden bağımsız kalsın (§3.4).
CARRIER_CLASSES = {"wood pallet"}


def _unit_count(counts: dict[str, int]) -> int:
    return sum(n for cls, n in counts.items() if cls not in CARRIER_CLASSES)


class VideoAnalyzer(ABC):
    """Teslimat kanıtı (fotoğraf/video) analiz eden servislerin ortak arayüzü."""

    @abstractmethod
    def analyze(self, media_path: Path) -> dict[str, Any]:
        """{counts, unit_count, damage_signals, confidence} döner (§3.4)."""
        raise NotImplementedError


class FakeVideoAnalyzer(VideoAnalyzer):
    """Ağa çıkmayan, demo-güvenli fake video analiz servisi.

    Dosya adı ipucu kuralları (dört demo senaryosunu sürebilmek için, §3.4):
    - varsayılan (ipucu yok)        -> unit_count=10, hasar yok   (tam teslimat)
    - dosya adında "eksik" varsa    -> unit_count=7,  hasar yok   (kısmi/çelişki)
    - dosya adında "hasarli" varsa  -> unit_count=10, hasar sinyali (dispute)
    İki ipucu da geçiyorsa "hasarli" önceliklidir (hasar tek başına dispute tetikler).
    """

    def analyze(self, media_path: Path) -> dict[str, Any]:
        name = Path(media_path).name.lower()
        box_count = 7 if "eksik" in name else 10
        damage_signals: list[dict[str, Any]] = []
        if "hasarli" in name:
            box_count = 10
            damage_signals = [{"type": "hasar_tespiti", "confidence": 0.9, "matched_box": True}]
        counts = {"cardboard box": box_count, "wood pallet": 2}
        return {
            "counts": counts,
            "unit_count": _unit_count(counts),
            "damage_signals": damage_signals,
            "confidence": 0.9,
        }


class RoboflowVideoAnalyzer(VideoAnalyzer):
    """Roboflow'da barındırılan iki YOLO modelini (koli/palet + hasar) kullanan
    canlı analiz servisi.

    Ayrı bir palet-özel model (Roboflow Universe: pallet-detection-ith6b)
    denendi ve gerçek fotoğraflarla test edilince bırakıldı: istiflenmiş
    paletlerde tüm görseli kaplayan tek bir kutu döndürdü, 5 ayrık paletlik
    kolay bir fotoğrafta bile 5/5 yerine 1 buldu. Palet sayımı bu yüzden
    logistics-sz9jr'da kalıyor.
    """

    def __init__(
        self,
        api_key: str,
        box_detector: Optional[BoxPalletDetector] = None,
        damage_detector: Optional[DamageDetector] = None,
    ):
        self.box_detector = box_detector or BoxPalletDetector(api_key=api_key)
        self.damage_detector = damage_detector or DamageDetector(api_key=api_key)

    def analyze(self, media_path: Path) -> dict[str, Any]:
        media_path = Path(media_path)
        if media_path.suffix.lower() in VIDEO_EXTENSIONS:
            return self._analyze_video(media_path)
        return self._analyze_image(media_path)

    def _analyze_image(self, image_path: Path) -> dict[str, Any]:
        box_detections = self.box_detector.detect(image_path)
        damage_detections = self.damage_detector.detect(image_path)
        result = correlate(box_detections, damage_detections)

        counts = Counter(b.box.class_name.lower() for b in result.boxes)

        damage_signals: list[dict[str, Any]] = [
            {"type": damage.class_name, "confidence": damage.confidence, "matched_box": True}
            for b in result.boxes
            for damage in b.damages
        ] + [
            {"type": d.class_name, "confidence": d.confidence, "matched_box": False}
            for d in result.unmatched_damages
        ]

        all_confidences = [b.box.confidence for b in result.boxes] + [
            s["confidence"] for s in damage_signals
        ]
        overall_confidence = sum(all_confidences) / len(all_confidences) if all_confidences else 0.0

        return {
            "counts": dict(counts),
            "unit_count": _unit_count(counts),
            "damage_signals": damage_signals,
            "confidence": round(overall_confidence, 3),
        }

    def _analyze_video(self, video_path: Path, sample_fps: float = DEFAULT_SAMPLE_FPS) -> dict[str, Any]:
        """Videodan kare örnekler ve kare-bazlı sonuçları birleştirir.

        Dedup stratejisi (bilinçli olarak basit, YOL_HARITASI.md'nin MVP
        notuna göre): kareler arası nesne takibi yok -- sayımlar sınıf
        başına herhangi bir karede görülen maksimumu alır (kamera aynı
        öğelerin üzerinden tekrar tekrar geçerse sayı katlanmasın), hasar
        sinyalleri ise tüm karelerin birleşimidir (hasar yalnızca bir
        açıdan/karede görünebilir, o yüzden sadece "en iyi" kareye bakıp
        sinyal kaybetmek istemeyiz).

        Ayrı ayrı yüklenen birden fazla video/fotoğrafı (örn. 30 kolinin
        15'i bir videoda, 15'i başka bir videoda) TOPLAMAK bu fonksiyonun
        kapsamı DIŞINDADIR -- her çağrı tek bir medya dosyasını analiz eder.
        Birden fazla kanıtı birleştirme mantığı (ve bunun istismar riski:
        aynı kolilerin iki ayrı videoda gösterilip sayının şişirilmesi) üst
        katmanda, e-irsaliye ile çapraz kontrol ve gerekirse insan onayı ile
        ele alınmalıdır -- video sayımı tek başına otomatik onay
        tetiklememelidir (ARCHITECTURE.md §3.4, §6.1).
        """
        frame_paths = extract_frames(video_path, sample_fps=sample_fps)
        if not frame_paths:
            raise ValueError(f"{video_path} içinden hiç kare örneklenemedi")

        try:
            frame_results = [self._analyze_image(frame) for frame in frame_paths]
        finally:
            shutil.rmtree(frame_paths[0].parent, ignore_errors=True)

        max_counts: Counter = Counter()
        for frame_result in frame_results:
            for class_name, count in frame_result["counts"].items():
                max_counts[class_name] = max(max_counts[class_name], count)

        all_damage_signals = [s for r in frame_results for s in r["damage_signals"]]

        frame_confidences = [r["confidence"] for r in frame_results if r["confidence"] > 0]
        overall_confidence = (
            sum(frame_confidences) / len(frame_confidences) if frame_confidences else 0.0
        )

        logger.info(
            "%s videosundan %d kare analiz edildi -> counts=%s, %d hasar sinyali",
            video_path.name,
            len(frame_results),
            dict(max_counts),
            len(all_damage_signals),
        )

        return {
            "counts": dict(max_counts),
            "unit_count": _unit_count(max_counts),
            "damage_signals": all_damage_signals,
            "confidence": round(overall_confidence, 3),
        }


def make_video_analyzer(settings: Settings) -> VideoAnalyzer:
    """`settings.video_provider`'a göre Fake veya canlı Roboflow servisi seçer."""
    if settings.video_provider == "roboflow":
        return RoboflowVideoAnalyzer(api_key=settings.roboflow_api_key)
    return FakeVideoAnalyzer()
