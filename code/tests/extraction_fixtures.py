"""E2E senaryoları için açık isimli extraction fixture'ları ve stub servisi.

Varsayılan `FakeExtractionService` artık approval-only bir sözleşme üretir
(videoyu varsayılan zorunluluk yapmaz). Sözleşmesel video/e-irsaliye şartını
veya bozuk yüzdeleri test etmek isteyen senaryolar, pipeline'ın çağırdığı
`make_extraction_service` adını bu modüldeki stub ile değiştirir — böylece
gerçek validator yolu korunur (fixture doğrudan DB'ye yazılmaz).
"""

from __future__ import annotations

from typing import Any

_PARTIES = {
    "buyer": {"name": "Örnek Alıcı A.Ş.", "tax_id": "1234567890"},
    "seller": {"name": "Örnek Satıcı Ltd. Şti.", "tax_id": "9876543210"},
}
_COMMERCIAL_TERMS = {
    "currency": "TRY",
    "total_amount": 100000.0,
    "goods": [{"name": "Endüstriyel Pompa", "quantity": 10, "unit": "adet"}],
    "delivery_deadline": "2026-09-01",
}


def _contract(contract_id: str, payment_rules: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "contract_id": contract_id,
        "parties": _PARTIES,
        "commercial_terms": _COMMERCIAL_TERMS,
        "payment_rules": payment_rules,
        "risk_flags": [],
        "needs_manual_review": False,
    }


def contractual_video_contract() -> dict[str, Any]:
    """Sözleşme videoyu açıkça zorunlu kılar — yönetici bunu kapatamaz."""
    return _contract(
        "demo-sozlesme-contractual-video",
        [
            {
                "milestone": "Teslimat",
                "trigger": "delivery_video",
                "percentage": 100.0,
                "required_evidence": ["contract", "video"],
                "source_quote": "Teslimat videosu doğrulandığında tutarın tamamı ödenir.",
                "confidence": 0.9,
            }
        ],
    )


def broken_percentage_contract() -> dict[str, Any]:
    """Yüzde toplamı 90 (%40+%50) — validator'ın `PERCENTAGE_SUM` REJECT'i için."""
    return _contract(
        "demo-sozlesme-broken-001",
        [
            {
                "milestone": "Sipariş onayı",
                "trigger": "approval",
                "percentage": 40.0,
                "required_evidence": ["contract"],
                "source_quote": "Sipariş onayı ile birlikte tutarın %40'ı ödenir.",
                "confidence": 0.9,
            },
            {
                "milestone": "Teslimat",
                "trigger": "delivery_video",
                "percentage": 50.0,
                "required_evidence": ["e_irsaliye", "video"],
                "source_quote": "Teslimat videosu onaylandığında kalan %50 ödenir.",
                "confidence": 0.85,
            },
        ],
    )


class StubExtractionService:
    """Sabit bir extraction payload'ı döndüren test dublörü (§6.3 adapter+fake)."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def extract(self, masked_markdown: str, context: Any) -> Any:
        from backend.app.schemas.extraction import ExtractionJSON
        from backend.app.services.extraction import ExtractionResult

        return ExtractionResult(
            status="ok", data=ExtractionJSON.model_validate(self._payload)
        )


def patch_extraction(monkeypatch, payload: dict[str, Any]) -> None:
    """Pipeline'ın modül-yerel `make_extraction_service` adını stub'a bağlar.

    Pipeline mantığı Plan 04 / Faz 4A'da `services/transaction_pipeline.py`'ye
    taşındı (bkz. `plans/done/04a_...md`); stub artık orada patch'lenir.
    `TestClient` içinde background task senkron koştuğu için upload'tan ÖNCE
    çağrılmalıdır.
    """
    monkeypatch.setattr(
        "backend.app.services.transaction_pipeline.make_extraction_service",
        lambda settings: StubExtractionService(payload),
    )
