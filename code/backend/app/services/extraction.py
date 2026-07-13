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
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

from backend.app.config import Settings
from backend.app.schemas.extraction import ExtractionJSON
from backend.app.services.context_builder import ContextPack

_SYSTEM_PROMPT_TEMPLATE = (
    "Sen bir B2B sözleşme analistisin. Sana verilen (önceden maskelenmiş) "
    "sözleşme metninden ödeme kurallarını ve ticari şartları çıkar. Yalnızca "
    "kural ÖNERİRSİN; ödeme kararını sen vermezsin, deterministik bir "
    "validator ve insan onayı bu öneriyi denetler.\n\n"
    "Yanıtın YALNIZCA aşağıdaki JSON Schema'ya uyan tek bir JSON nesnesi "
    "olmalıdır (başka hiçbir metin, açıklama veya markdown ekleme):\n\n"
    "{schema}"
)

# Kaynaklı bağlam mesajının başına eklenen yönerge (retrieval sonuçlarına güven sınırı).
_SOURCE_GUIDANCE = (
    "Aşağıdaki kaynaklar retrieval sistemi tarafından seçilmiştir. Yalnızca bu "
    "kaynakları sözleşme metniyle birlikte kullan. Kaynaklarda olmayan hukuki "
    "iddiaları kesin hüküm gibi sunma. Ödeme kararı verme; sadece kural öner."
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
    def extract(self, masked_markdown: str, context: ContextPack | None) -> ExtractionResult:
        """Maskelenmiş markdown ve (opsiyonel) ContextPack'ten bir extraction önerisi üretir."""
        raise NotImplementedError


# Fake extraction profil marker'ı — FakeVideoAnalyzer'ın dosya-adı ipucu deseninin
# muadili: masked markdown içinde `[[m4trust-fake-profile: delivery]]` geçerse ilgili
# fixture seçilir (env `LLM_FAKE_PROFILE`'ı override eder). Marker maskeleme kapsamı
# dışıdır (PII değildir), bu yüzden masked_markdown'da korunur.
_FAKE_PROFILE_MARKER = re.compile(r"\[\[m4trust-fake-profile:\s*(\w+)\s*\]\]")
_KNOWN_FAKE_PROFILES = frozenset({"approval", "delivery"})


def _resolve_fake_profile(masked_markdown: str, default: str) -> str:
    """Marker > env default; bilinmeyen profil güvenli biçimde approval'a düşer."""
    match = _FAKE_PROFILE_MARKER.search(masked_markdown or "")
    candidate = match.group(1).lower() if match else (default or "approval").lower()
    return candidate if candidate in _KNOWN_FAKE_PROFILES else "approval"


def _fake_fixture() -> ExtractionJSON:
    """Demo-güvenli, approval-only örnek çıktı (default profil — bit-bit korunur)."""
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
                    "percentage": 100.0,
                    "required_evidence": ["contract"],
                    "source_quote": "Tarafların onayıyla tutarın tamamı ödenir.",
                    "confidence": 0.9,
                },
            ],
            "risk_flags": [],
            "needs_manual_review": False,
        }
    )


def _fake_fixture_delivery() -> ExtractionJSON:
    """Teslimat-odaklı demo fixture'ı — aynı taraflar, iki e-irsaliye tranşı.

    İki `e_invoice` tetikli tranş (%50 + %50, `required_evidence=["e_irsaliye"]`,
    miktarlı mal): funding schedule iki funding unit üretir, tracking policy doğal
    olarak açılır (e-irsaliye şartı), böylece e-irsaliye → milestone evaluator →
    settlement zinciri uçtan uca gösterilebilir olur. Şema DEĞİŞMEZ.
    """
    return ExtractionJSON.model_validate(
        {
            "contract_id": "demo-sozlesme-delivery-001",
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
                    "milestone": "İlk teslimat partisi (e-irsaliye)",
                    "trigger": "e_invoice",
                    "percentage": 50.0,
                    "required_evidence": ["e_irsaliye"],
                    "source_quote": (
                        "İlk teslimatın e-irsaliyesi kesildiğinde tutarın %50'si ödenir."
                    ),
                    "confidence": 0.9,
                },
                {
                    "milestone": "İkinci teslimat partisi (e-irsaliye)",
                    "trigger": "e_invoice",
                    "percentage": 50.0,
                    "required_evidence": ["e_irsaliye"],
                    "source_quote": (
                        "Kalan teslimatın e-irsaliyesi kesildiğinde kalan %50 ödenir."
                    ),
                    "confidence": 0.9,
                },
            ],
            "risk_flags": [],
            "needs_manual_review": False,
        }
    )


_FAKE_FIXTURES = {
    "approval": _fake_fixture,
    "delivery": _fake_fixture_delivery,
}


class FakeExtractionService(ExtractionService):
    """Ağa çıkmayan, her zaman başarılı demo-güvenli fake extraction servisi.

    Profil seçimi: masked markdown içindeki `[[m4trust-fake-profile: …]]` marker'ı
    varsa onu, yoksa `settings.llm_fake_profile`'ı (default `approval`) kullanır.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._default_profile = settings.llm_fake_profile if settings else "approval"

    def extract(self, masked_markdown: str, context: ContextPack | None) -> ExtractionResult:
        profile = _resolve_fake_profile(masked_markdown, self._default_profile)
        return ExtractionResult(status="ok", data=_FAKE_FIXTURES[profile]())


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

    def _build_messages(self, masked_markdown: str, context: ContextPack | None) -> list[dict]:
        schema = json.dumps(ExtractionJSON.model_json_schema(), ensure_ascii=False)
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(schema=schema)

        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        if context is not None and context.formatted_for_llm:
            messages.append(
                {"role": "system", "content": f"{_SOURCE_GUIDANCE}\n\n{context.formatted_for_llm}"}
            )

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

    def extract(self, masked_markdown: str, context: ContextPack | None) -> ExtractionResult:
        messages = self._build_messages(masked_markdown, context)

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
    return FakeExtractionService(settings)
