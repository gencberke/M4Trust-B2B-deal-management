"""Public API'ler için extraction JSON'ın daraltılmış, PII'siz görünümü."""

from __future__ import annotations

from backend.app.services.privacy import analyze


def _masked_source_quote(value: object) -> str | None:
    """Kuralın sözleşmedeki dayanağını PII/kart verisi sızdırmadan gösterir.

    "AI önerir, taraflar dayanağı görüp onaylar" zincirinin taraf tarafındaki
    halkası budur; alıntıyı tümden düşürmek izlenebilirliği kaybettirirdi.
    `analyze()` (yalnız `mask()` değil) kullanılır: TCKN/VKN/IBAN/telefon/e-posta
    placeholder'a döner, PAN ve diğer kart verisi de maskelenir.
    """
    if not isinstance(value, str) or not value:
        return None
    return analyze(value).masked_text


def redacted_extraction_projection(extraction: dict | None) -> dict | None:
    """Yalnızca public contract için izinli extraction alanlarını döndürür.

    DB'deki özgün extraction, validator/decision akışının girdisi olarak
    değişmeden kalır. Bu projection vergi numarasını, placeholder mapping'ini
    veya beklenmeyen alanları kopyalamaz; `source_quote` yalnızca maskelenmiş
    biçimde geçer.
    """
    if extraction is None:
        return None

    parties = extraction.get("parties") or {}
    commercial = extraction.get("commercial_terms") or {}

    def party_projection(party: object) -> dict:
        data = party if isinstance(party, dict) else {}
        return {"name": data.get("name")}

    def goods_projection(goods: object) -> dict:
        data = goods if isinstance(goods, dict) else {}
        return {
            "name": data.get("name"),
            "quantity": data.get("quantity"),
            "unit": data.get("unit"),
        }

    def rule_projection(rule: object) -> dict:
        data = rule if isinstance(rule, dict) else {}
        return {
            "milestone": data.get("milestone"),
            "trigger": data.get("trigger"),
            "percentage": data.get("percentage"),
            "required_evidence": data.get("required_evidence") or [],
            "source_quote": _masked_source_quote(data.get("source_quote")),
            "confidence": data.get("confidence"),
        }

    return {
        "contract_id": extraction.get("contract_id"),
        "parties": {
            "buyer": party_projection(parties.get("buyer")),
            "seller": party_projection(parties.get("seller")),
        },
        "commercial_terms": {
            "currency": commercial.get("currency"),
            "total_amount": commercial.get("total_amount"),
            "goods": [goods_projection(goods) for goods in commercial.get("goods") or []],
            "delivery_deadline": commercial.get("delivery_deadline"),
        },
        "payment_rules": [rule_projection(rule) for rule in extraction.get("payment_rules") or []],
        "risk_flags": extraction.get("risk_flags") or [],
        "needs_manual_review": bool(extraction.get("needs_manual_review", False)),
    }
