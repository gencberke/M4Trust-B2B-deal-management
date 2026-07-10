"""Public API'ler için extraction JSON'ın daraltılmış, PII'siz görünümü."""

from __future__ import annotations


def redacted_extraction_projection(extraction: dict | None) -> dict | None:
    """Yalnızca public contract için izinli extraction alanlarını döndürür.

    DB'deki özgün extraction, validator/decision akışının girdisi olarak
    değişmeden kalır. Bu projection vergi numarası, source quote, placeholder
    mapping veya beklenmeyen alanları kopyalamaz.
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
