"""Extraction JSON şeması — ARCHITECTURE §4.2 ile alan-alan aynıdır (ikili sözleşme).

Bu modül tek doğruluk kaynağıdır; fake ve gerçek extraction aynı şemayı döndürür.
Değişiklik (alan ekleme/çıkarma/yeniden adlandırma) ekip mutabakatı gerektirir.
"""

import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, field_validator

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Currency(str, Enum):
    """Desteklenen para birimleri."""

    TRY = "TRY"
    USD = "USD"
    EUR = "EUR"
    OTHER = "OTHER"


class Trigger(str, Enum):
    """Ödeme kuralını tetikleyen olay tipi."""

    approval = "approval"
    e_invoice = "e_invoice"
    delivery_video = "delivery_video"
    manual_review = "manual_review"


class RequiredEvidence(str, Enum):
    """Bir ödeme kuralı için gereken kanıt türü."""

    contract = "contract"
    e_irsaliye = "e_irsaliye"
    video = "video"


class Party(BaseModel):
    """Sözleşmenin bir tarafı (alıcı veya satıcı)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    tax_id: str | None = None


class Parties(BaseModel):
    """Sözleşmenin taraf çifti."""

    model_config = ConfigDict(extra="forbid")

    buyer: Party
    seller: Party


class Goods(BaseModel):
    """Sözleşme konusu mal/hizmet kalemi."""

    model_config = ConfigDict(extra="forbid")

    name: str
    quantity: float
    unit: str


class CommercialTerms(BaseModel):
    """Ticari şartlar: para birimi, tutar, mallar, teslim tarihi."""

    model_config = ConfigDict(extra="forbid")

    currency: Currency
    total_amount: float
    goods: list[Goods]
    delivery_deadline: str | None

    @field_validator("delivery_deadline")
    @classmethod
    def _validate_delivery_deadline(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not _DATE_PATTERN.match(value):
            raise ValueError("delivery_deadline 'YYYY-MM-DD' formatında olmalı veya null olmalı")
        return value


class PaymentRule(BaseModel):
    """Sözleşmeden çıkarılan önerilen ödeme kuralı (LLM önerir, validator denetler)."""

    model_config = ConfigDict(extra="forbid")

    milestone: str
    trigger: Trigger
    percentage: float
    required_evidence: list[RequiredEvidence]
    source_quote: str
    confidence: float

    @field_validator("percentage")
    @classmethod
    def _validate_percentage(cls, value: float) -> float:
        if not 0 <= value <= 100:
            raise ValueError("percentage 0 ile 100 arasında olmalı")
        return value

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("confidence 0.0 ile 1.0 arasında olmalı")
        return value


class ExtractionJSON(BaseModel):
    """Extraction hattının ürettiği tam çıktı — §4.2 ikili sözleşme kökü."""

    model_config = ConfigDict(extra="forbid")

    contract_id: str
    parties: Parties
    commercial_terms: CommercialTerms
    payment_rules: list[PaymentRule]
    risk_flags: list[str]
    needs_manual_review: bool = False
