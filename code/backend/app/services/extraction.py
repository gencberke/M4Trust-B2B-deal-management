"""ExtractionService — sözleşme metninden §4.2 şemasına uygun kural önerisi çıkarır.

Fake ve canlı (OpenAI-uyumlu) iki implementasyon aynı arayüzü paylaşır (§3
adapter+fake ilkesi). Canlı adapter yalnızca ZATEN MASKELENMİŞ markdown alır;
maskeleme upstream'de (`privacy.mask()`) yapılır — bu modül maskeleme yapmaz.

`openai` paketi yalnızca canlı adapter'ın istemci kurma metodunda lazy import
edilir; modül import edildiğinde openai yüklenmesi gerekmez, Fake yol hiçbir
zaman openai'ye ihtiyaç duymaz (§3).
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

from backend.app.config import Settings
from backend.app.schemas.extraction import ExtractionJSON
from backend.app.services.rag import Chunk

_SYSTEM_PROMPT_TEMPLATE = (
    "Sen bir B2B sözleşme analistisin. Sana verilen (önceden maskelenmiş) "
    "sözleşme metninden ödeme kurallarını ve ticari şartları çıkar. Yalnızca "
    "kural ÖNERİRSİN; ödeme kararını sen vermezsin, deterministik bir "
    "validator ve insan onayı bu öneriyi denetler.\n\n"
    "Yanıtın YALNIZCA aşağıdaki JSON Schema'ya uyan tek bir JSON nesnesi "
    "olmalıdır (başka hiçbir metin, açıklama veya markdown ekleme):\n\n"
    "{schema}"
)


@dataclass
class ExtractionResult:
    """`extract()` çağrısının sonucu — ya geçerli veri ya da manuel inceleme gerekçesi."""

    status: Literal["ok", "needs_review"]
    data: ExtractionJSON | None = None
    reason: str | None = None


class ExtractionService(ABC):
    """Sözleşme metninden `ExtractionJSON` öneren servislerin ortak arayüzü."""

    @abstractmethod
    def extract(self, masked_markdown: str, rag_context: list[Chunk]) -> ExtractionResult:
        """Maskelenmiş markdown ve RAG bağlamından bir extraction önerisi üretir."""
        raise NotImplementedError


def _fake_fixture() -> ExtractionJSON:
    """Demo-güvenli, her zaman şema-geçerli örnek çıktı."""
    return ExtractionJSON.model_validate(
        {
            "contract_id": "demo-sozlesme-001",
            "parties": {
                "buyer": {"name": "Örnek Alıcı A.Ş.", "tax_id": "1234567890"},
                "seller": {"name": "Örnek Satıcı Ltd. Şti.", "tax_id": "9876543210"},
            },
            "commercial_terms": {
                "currency": "TRY",
                "total_amount": 100000.0,
                "goods": [{"name": "Endüstriyel Pompa", "quantity": 10, "unit": "adet"}],
                "delivery_deadline": "2026-09-01",
            },
            "payment_rules": [
                {
                    "milestone": "Sipariş onayı",
                    "trigger": "approval",
                    "percentage": 30.0,
                    "required_evidence": ["contract"],
                    "source_quote": "Sipariş onayı ile birlikte tutarın %30'u ödenir.",
                    "confidence": 0.9,
                },
                {
                    "milestone": "Teslimat",
                    "trigger": "delivery_video",
                    "percentage": 70.0,
                    "required_evidence": ["e_irsaliye", "video"],
                    "source_quote": "Teslimat videosu onaylandığında kalan %70 ödenir.",
                    "confidence": 0.85,
                },
            ],
            "risk_flags": [],
            "needs_manual_review": False,
        }
    )


class FakeExtractionService(ExtractionService):
    """Ağa çıkmayan, her zaman başarılı demo-güvenli fake extraction servisi."""

    def extract(self, masked_markdown: str, rag_context: list[Chunk]) -> ExtractionResult:
        return ExtractionResult(status="ok", data=_fake_fixture())


class OpenAICompatibleExtractionService(ExtractionService):
    """OpenAI-uyumlu chat completions API'sini kullanan canlı extraction servisi."""

    def __init__(self, settings: Settings, *, client=None):
        self._settings = settings
        self._client = client

    def _get_client(self):
        if self._client is None:
            import openai

            self._client = openai.OpenAI(
                base_url=self._settings.llm_base_url,
                api_key=self._settings.llm_api_key,
                timeout=self._settings.llm_timeout,
            )
        return self._client

    def _build_messages(self, masked_markdown: str, rag_context: list[Chunk]) -> list[dict]:
        schema = json.dumps(ExtractionJSON.model_json_schema(), ensure_ascii=False)
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(schema=schema)

        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        if rag_context:
            context_text = "\n\n".join(chunk.text for chunk in rag_context)
            messages.append({"role": "system", "content": f"İlgili mevzuat:\n{context_text}"})

        messages.append({"role": "user", "content": masked_markdown})
        return messages

    def _call_once(self, messages: list[dict]) -> ExtractionJSON:
        """Tek bir API çağrısı yapar ve yanıtı doğrular; hata durumunda fırlatır."""
        client = self._get_client()
        response = client.chat.completions.create(
            model=self._settings.llm_model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = response.choices[0].message.content
        if not content:
            # Boş/None içerik: JSON hatası gibi ele al ki retry mantığına girsin.
            raise json.JSONDecodeError("boş yanıt (content boş/None)", content or "", 0)
        payload = json.loads(content)
        return ExtractionJSON.model_validate(payload)

    def extract(self, masked_markdown: str, rag_context: list[Chunk]) -> ExtractionResult:
        messages = self._build_messages(masked_markdown, rag_context)

        last_error: Exception | None = None
        for _attempt in range(2):
            try:
                data = self._call_once(messages)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                continue
            except Exception as exc:  # istemci/ağ/SDK hatası — fixture'a düşmez, yutulmaz
                return ExtractionResult(status="needs_review", reason=str(exc))
            else:
                return ExtractionResult(status="ok", data=data)

        return ExtractionResult(status="needs_review", reason=str(last_error))


def make_extraction_service(settings: Settings) -> ExtractionService:
    """`settings.llm_provider`'a göre Fake veya canlı OpenAI-uyumlu servis seçer."""
    if settings.llm_provider == "openai":
        return OpenAICompatibleExtractionService(settings)
    return FakeExtractionService()
