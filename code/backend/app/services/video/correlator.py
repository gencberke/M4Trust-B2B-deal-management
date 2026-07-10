"""Hasar tespitlerini, fiziksel olarak üzerine düştükleri koli tespitlerine bağlar.

Merkezi hiçbir kolinin içine düşmeyen hasar tespitleri atılmaz, "eşleşmemiş"
olarak saklanır -- gerçek bir fotoğrafta, koli tespit edicinin tanıyamadığı
bir kolide hasar görünebilir (örn. yırtılıp açılmış, aşırı yakın çekim), ve
video kanıtı bir hüküm değil bir risk sinyalidir (ARCHITECTURE.md §3.4) --
bu yüzden atıf mükemmel olmasa da sinyali atmıyoruz.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .interfaces import Detection

# Roboflow'un logistics modeli Person/Truck/Forklift/vb. de döndürüyor;
# biz yalnızca sözleşmedeki teslimat miktarının atıfta bulunduğu sınıfları sayarız.
COUNTABLE_CLASSES = {"cardboard box", "wood pallet"}


@dataclass
class BoxWithDamage:
    box: Detection
    damages: list[Detection] = field(default_factory=list)


@dataclass
class CorrelationResult:
    boxes: list[BoxWithDamage]
    unmatched_damages: list[Detection]


def correlate(box_detections: list[Detection], damage_detections: list[Detection]) -> CorrelationResult:
    boxes = [
        BoxWithDamage(box=d) for d in box_detections if d.class_name.lower() in COUNTABLE_CLASSES
    ]
    unmatched: list[Detection] = []

    for damage in damage_detections:
        matches = [b for b in boxes if b.box.contains_point(damage.x, damage.y)]
        if matches:
            for b in matches:
                b.damages.append(damage)
        else:
            unmatched.append(damage)

    return CorrelationResult(boxes=boxes, unmatched_damages=unmatched)
