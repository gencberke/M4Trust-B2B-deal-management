import json

from backend.app.config import Settings
from backend.app.schemas.extraction import ExtractionJSON
from backend.app.services.context_builder import ContextPack, ContextSource
from backend.app.services.extraction import (
    ExtractionResult,
    FakeExtractionService,
    OpenAICompatibleExtractionService,
    make_extraction_service,
)


def _valid_payload() -> dict:
    return {
        "contract_id": "sozlesme-001",
        "parties": {
            "buyer": {"name": "Alici A.S.", "tax_id": "1234567890"},
            "seller": {"name": "Satici Ltd.", "tax_id": None},
        },
        "commercial_terms": {
            "currency": "TRY",
            "total_amount": 15000.50,
            "goods": [{"name": "Cimento", "quantity": 100, "unit": "ton"}],
            "delivery_deadline": "2026-01-01",
        },
        "payment_rules": [
            {
                "milestone": "Teslimat",
                "trigger": "e_invoice",
                "percentage": 50.0,
                "required_evidence": ["e_irsaliye"],
                "source_quote": "Teslimatta %50 ödenir.",
                "confidence": 0.8,
            }
        ],
        "risk_flags": [],
        "needs_manual_review": False,
    }


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    """`client.chat.completions.create(...)`'i taklit eden, çağrıları kaydeden fake."""

    def __init__(self, contents: list[str] | None = None, error: Exception | None = None):
        self._contents = list(contents) if contents is not None else []
        self._error = error
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        content = self._contents.pop(0)
        return _FakeResponse(content)


class _FakeChat:
    def __init__(self, completions: _FakeCompletions):
        self.completions = completions


class _FakeClient:
    def __init__(self, contents: list[str] | None = None, error: Exception | None = None):
        self.completions = _FakeCompletions(contents=contents, error=error)
        self.chat = _FakeChat(self.completions)


def test_fake_extraction_service_returns_ok_with_valid_schema():
    service = FakeExtractionService()

    result = service.extract("herhangi bir maskelenmis metin", None)

    assert result.status == "ok"
    assert isinstance(result.data, ExtractionJSON)


def test_live_adapter_valid_json_returns_ok():
    client = _FakeClient(contents=[json.dumps(_valid_payload())])
    service = OpenAICompatibleExtractionService(Settings(), client=client)

    result = service.extract("maskelenmis metin", None)

    assert result.status == "ok"
    assert result.data.contract_id == "sozlesme-001"
    assert client.completions.calls[0]["response_format"] == {"type": "json_object"}


def test_live_adapter_retries_once_on_invalid_then_valid():
    client = _FakeClient(contents=["bozuk json {", json.dumps(_valid_payload())])
    service = OpenAICompatibleExtractionService(Settings(), client=client)

    result = service.extract("maskelenmis metin", None)

    assert result.status == "ok"
    assert len(client.completions.calls) == 2


def test_live_adapter_needs_review_when_invalid_twice():
    client = _FakeClient(contents=["bozuk json {", "hala bozuk {"])
    service = OpenAICompatibleExtractionService(Settings(), client=client)

    result = service.extract("maskelenmis metin", None)

    assert result.status == "needs_review"
    assert result.reason
    assert len(client.completions.calls) == 2


def test_live_adapter_needs_review_when_client_raises():
    client = _FakeClient(error=RuntimeError("baglanti koptu"))
    service = OpenAICompatibleExtractionService(Settings(), client=client)

    result = service.extract("maskelenmis metin", None)

    assert result.status == "needs_review"
    assert "baglanti koptu" in result.reason


def test_make_extraction_service_returns_fake_for_fake_provider():
    service = make_extraction_service(Settings(llm_provider="fake"))
    assert isinstance(service, FakeExtractionService)


def test_make_extraction_service_returns_live_for_openai_provider():
    settings = Settings(llm_provider="openai")
    client = _FakeClient(contents=[json.dumps(_valid_payload())])
    service = OpenAICompatibleExtractionService(settings, client=client)
    assert isinstance(service, OpenAICompatibleExtractionService)

    factory_service = make_extraction_service(settings)
    assert isinstance(factory_service, OpenAICompatibleExtractionService)


def _context_pack_with_one_source() -> ContextPack:
    source = ContextSource(
        source_type="legal",
        source="6098kk",
        text="MADDE 21 - teslimat hükmü",
        score=0.2,
        collection="legal_articles",
        madde_no="21",
    )
    return ContextPack(
        queries=[],
        sources=[source],
        formatted_for_llm="[LEGAL_SOURCE_1] source: 6098kk\nMADDE 21 - teslimat hükmü",
        risk_flags=[],
    )


def test_live_adapter_injects_context_as_system_message():
    client = _FakeClient(contents=[json.dumps(_valid_payload())])
    service = OpenAICompatibleExtractionService(Settings(), client=client)

    service.extract("maskelenmis metin", _context_pack_with_one_source())

    messages = client.completions.calls[0]["messages"]
    system_texts = "\n".join(m["content"] for m in messages if m["role"] == "system")
    assert "MADDE 21 - teslimat hükmü" in system_texts
    assert "retrieval sistemi tarafından seçilmiştir" in system_texts  # yönerge satırı


def test_live_adapter_no_context_message_when_pack_empty():
    client = _FakeClient(contents=[json.dumps(_valid_payload())])
    service = OpenAICompatibleExtractionService(Settings(), client=client)

    service.extract("maskelenmis metin", ContextPack())  # boş pack

    messages = client.completions.calls[0]["messages"]
    # Yalnızca ana system prompt + user; kaynaklı ikinci system mesajı yok.
    assert sum(1 for m in messages if m["role"] == "system") == 1
