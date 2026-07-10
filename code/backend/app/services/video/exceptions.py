"""Teslimat kanıtı (video/görsel) analiz servisi için hata hiyerarşisi."""


class VideoAnalyzerError(Exception):
    """Video/görsel analiz servisinin fırlattığı tüm hataların temel sınıfı."""


class RoboflowAPIError(VideoAnalyzerError):
    """Roboflow inference isteği başarısız olduğunda (ağ, kimlik doğrulama, hatalı cevap)."""
