"""Her biri bir Roboflow modeline karşılık gelen concrete Detector'lar.

İkisi de aynı REST çağrısını (roboflow_client.infer) sabit bir model_id ile
sarmalıyor -- tek bir genel detector yerine ayrı sınıflar olarak tutulmasının
sebebi, her birinin amacının çağrı noktasında açık olması ve testlerde
birbirinden bağımsız sahtelenebilmesi (mock'lanabilmesi).

Ayrık koli/palet/görsel öğe eklerinde (Roboflow Universe: pallet-detection-
ith6b) denendi ve gerçek fotoğraflarla test edilince bırakıldı: istiflenmiş
paletlerde tek, tüm görseli kaplayan bir kutu döndürüyordu (5 ayrık palet
fotoğrafında bile 5/5 yerine 1) -- palet sayımı logistics-sz9jr'da kalıyor.
"""

from __future__ import annotations

from pathlib import Path

from . import roboflow_client
from .interfaces import Detection, Detector

BOX_PALLET_MODEL_ID = "logistics-sz9jr/2"
DAMAGE_MODEL_ID = "detecting-a-damaged-parcel/11"


class BoxPalletDetector(Detector):
    """Karton koli / ahşap palet tespit eder (modelin döndürdüğü diğer
    lojistik sınıfları -- Person/Truck/Forklift vb. -- görmezden geliriz)."""

    def __init__(self, api_key: str, model_id: str = BOX_PALLET_MODEL_ID):
        self.api_key = api_key
        self.model_id = model_id

    def detect(self, image_path: Path) -> list[Detection]:
        return roboflow_client.infer(image_path, self.model_id, self.api_key)


class DamageDetector(Detector):
    """Bir parselde hasar belirtisi tespit eder: hole (delik), wet (ıslanma), screw (vida)."""

    def __init__(self, api_key: str, model_id: str = DAMAGE_MODEL_ID):
        self.api_key = api_key
        self.model_id = model_id

    def detect(self, image_path: Path) -> list[Detection]:
        return roboflow_client.infer(image_path, self.model_id, self.api_key)
