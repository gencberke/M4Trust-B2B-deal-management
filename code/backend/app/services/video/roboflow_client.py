"""Roboflow'un serverless hosted inference REST API'si için ince bir sarmalayıcı.

Resmi bir SDK kullanılmıyor -- bu yazı itibarıyla PyPI'daki `inference-sdk`
Python 3.13'ü desteklemiyor. REST sözleşmesi yeterince basit olduğu için düz
bir `requests` POST isteği bu kısıtı tamamen atlıyor:

    POST https://serverless.roboflow.com/{model_id}?api_key={key}
    body: base64 encode edilmiş görsel byte'ları
    -> {"predictions": [{"class": ..., "confidence": ..., "x": ..., "y": ..., "width": ..., "height": ...}, ...]}
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import requests

from .exceptions import RoboflowAPIError
from .interfaces import Detection

logger = logging.getLogger(__name__)

API_URL = "https://serverless.roboflow.com"
REQUEST_TIMEOUT_SECONDS = 30


def infer(image_path: Path, model_id: str, api_key: str) -> list[Detection]:
    """Bir Roboflow modelini yerel bir görsel dosyasına karşı çalıştırır.

    model_id "{project}/{version}" formatındadır, örn. "logistics-sz9jr/2".
    """
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(image_path)

    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")

    try:
        response = requests.post(
            f"{API_URL}/{model_id}",
            params={"api_key": api_key},
            data=encoded,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RoboflowAPIError(f"Roboflow isteği başarısız ({model_id}): {exc}") from exc

    payload = response.json()
    predictions = payload.get("predictions", [])
    logger.info("model %s: %s için %d tespit", model_id, image_path.name, len(predictions))

    return [
        Detection(
            class_name=p["class"],
            confidence=p["confidence"],
            x=p["x"],
            y=p["y"],
            width=p["width"],
            height=p["height"],
        )
        for p in predictions
    ]
