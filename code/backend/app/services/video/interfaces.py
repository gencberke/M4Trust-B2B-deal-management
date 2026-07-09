"""Tespit portu: her concrete detector bu sözleşmeyi uygular."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Detection:
    """Bir modelin döndürdüğü tek bir bounding-box tahmini.

    x/y kutunun merkezidir, piksel cinsinden (Roboflow'un ham JSON cevabıyla
    birebir aynı) -- sessizce bir koordinat dönüşümü yapılmaz.
    """

    class_name: str
    confidence: float
    x: float
    y: float
    width: float
    height: float

    @property
    def left(self) -> float:
        return self.x - self.width / 2

    @property
    def right(self) -> float:
        return self.x + self.width / 2

    @property
    def top(self) -> float:
        return self.y - self.height / 2

    @property
    def bottom(self) -> float:
        return self.y + self.height / 2

    def contains_point(self, px: float, py: float) -> bool:
        return self.left <= px <= self.right and self.top <= py <= self.bottom


class Detector(ABC):
    """Bir Roboflow modelini bir görsel üzerinde çalıştırıp tespitlerini döndürür."""

    @abstractmethod
    def detect(self, image_path: Path) -> list[Detection]:
        raise NotImplementedError
