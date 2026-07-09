"""`extract_contract.py` CLI hattı testleri.

Kapsam: `run_extraction()` çekirdeğinin doğru sırayla çalışması (convert ->
mask -> retrieve -> extract -> restore -> validate), §6.7 seam garantisi
(maskelenmiş metnin extraction service'e gittiği, ham PII'nin gitmediği) ve
`main()` CLI smoke testi (gerçek DocumentConverter + mask + restore ile).
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.app.config import Settings
from backend.app.schemas.extraction import ExtractionJSON
from backend.app.services.extraction import ExtractionResult

from extract_contract import main, run_extraction

_KNOWN_IBAN = "TR33 0006 1005 1978 6457 8413 26"
_KNOWN_TAX_ID = "1234567890"


class FakeConverter:
    """`DocumentConverter.convert()`'i taklit eden, sabit markdown döndüren fake."""

    def __init__(self, markdown: str):
        self._markdown = markdown
        self.calls: list[Path] = []

    def convert(self, file_path: Path) -> str:
        self.calls.append(file_path)
        return self._markdown


class FakeRetriever:
    """Her zaman boş sonuç döndüren fake retriever."""

    def retrieve(self, query, collection=None, k=5):
        return []


class BrokenRetriever:
    """Ağır bağımlılıklar eksikmiş gibi davranıp `ImportError` fırlatan retriever."""

    def retrieve(self, query, collection=None, k=5):
        raise ImportError("chromadb/FlagEmbedding yüklü değil")


class SpyExtractionService:
    """`extract()`'e gelen `masked_markdown`'ı kaydeden ve geçerli sonuç döndüren fake.

    Dönen `ExtractionJSON.payment_rules[0].source_quote` alanına, aldığı
    maskelenmiş metni aynen yansıtır; böylece restore round-trip'i test
    edilebilir (§6.7 seam garantisi).
    """

    def __init__(self):
        self.received_masked_markdown: str | None = None
        self.received_context = None

    def extract(self, masked_markdown: str, context) -> ExtractionResult:
        self.received_masked_markdown = masked_markdown
        self.received_context = context
        data = ExtractionJSON.model_validate(
            {
                "contract_id": "test-sozlesme-001",
                "parties": {
                    "buyer": {"name": "Test Alici A.S.", "tax_id": "1234567890"},
                    "seller": {"name": "Test Satici Ltd.", "tax_id": "9876543210"},
                },
                "commercial_terms": {
                    "currency": "TRY",
                    "total_amount": 5000.0,
                    "goods": [{"name": "Test Mal", "quantity": 1, "unit": "adet"}],
                    "delivery_deadline": "2026-12-01",
                },
                "payment_rules": [
                    {
                        "milestone": "Teslimat",
                        "trigger": "delivery_video",
                        "percentage": 100.0,
                        "required_evidence": ["video"],
                        "source_quote": masked_markdown,
                        "confidence": 0.9,
                    }
                ],
                "risk_flags": [],
                "needs_manual_review": False,
            }
        )
        return ExtractionResult(status="ok", data=data)


def _markdown_with_pii() -> str:
    return (
        f"Sözleşme metni.\nIBAN: {_KNOWN_IBAN}\n"
        f"Vergi No: {_KNOWN_TAX_ID}\nTeslimatta %100 ödenir.\n"
    )


def test_run_extraction_returns_ok_with_valid_schema():
    converter = FakeConverter(_markdown_with_pii())
    retriever = FakeRetriever()
    extraction_service = SpyExtractionService()
    settings = Settings()

    result = run_extraction(
        Path("herhangi.pdf"),
        settings=settings,
        converter=converter,
        retriever=retriever,
        extraction_service=extraction_service,
    )

    assert result.status == "ok"
    assert isinstance(result.data, ExtractionJSON)


def test_extraction_service_receives_masked_text_without_raw_iban():
    converter = FakeConverter(_markdown_with_pii())
    retriever = FakeRetriever()
    extraction_service = SpyExtractionService()
    settings = Settings()

    run_extraction(
        Path("herhangi.pdf"),
        settings=settings,
        converter=converter,
        retriever=retriever,
        extraction_service=extraction_service,
    )

    assert extraction_service.received_masked_markdown is not None
    assert _KNOWN_IBAN not in extraction_service.received_masked_markdown
    assert "[[PII_IBAN_1]]" in extraction_service.received_masked_markdown


def test_restore_round_trip_returns_original_iban():
    converter = FakeConverter(_markdown_with_pii())
    retriever = FakeRetriever()
    extraction_service = SpyExtractionService()
    settings = Settings()

    result = run_extraction(
        Path("herhangi.pdf"),
        settings=settings,
        converter=converter,
        retriever=retriever,
        extraction_service=extraction_service,
    )

    echoed = result.data.payment_rules[0].source_quote
    assert _KNOWN_IBAN in echoed


def test_broken_retriever_degrades_gracefully_with_empty_rag_context():
    converter = FakeConverter(_markdown_with_pii())
    retriever = BrokenRetriever()
    extraction_service = SpyExtractionService()
    settings = Settings()

    result = run_extraction(
        Path("herhangi.pdf"),
        settings=settings,
        converter=converter,
        retriever=retriever,
        extraction_service=extraction_service,
    )

    assert result.status == "ok"
    # ContextBuilder tüm query'lerde ImportError alır -> boş pack ile graceful devam.
    assert extraction_service.received_context is not None
    assert extraction_service.received_context.sources == []
    assert extraction_service.received_context.formatted_for_llm == ""


def test_restore_failure_degrades_to_needs_review(monkeypatch):
    """restore sonrası doğrulama bozulursa CLI çökmez, needs_review'a düşer.

    Bu senaryo normal girdiyle erişilemez (extraction service restore'dan önce
    zaten doğruluyor); guard'ı doğrudan test etmek için `restore` monkeypatch'lenir.
    """
    import copy

    import extract_contract

    def bad_restore(obj, mapping):
        corrupted = copy.deepcopy(obj)
        corrupted["commercial_terms"]["delivery_deadline"] = "GECERSIZ-TARIH"
        return corrupted

    monkeypatch.setattr(extract_contract, "restore", bad_restore)

    result = run_extraction(
        Path("herhangi.pdf"),
        settings=Settings(),
        converter=FakeConverter(_markdown_with_pii()),
        retriever=FakeRetriever(),
        extraction_service=SpyExtractionService(),
    )

    assert result.status == "needs_review"
    assert "doğrulama" in (result.reason or "")


def _markdown_with_cvv() -> str:
    return "Ödeme kartla alınır. Kart doğrulama CVV: 123. Teslimatta %100 ödenir.\n"


def test_blocking_live_provider_skips_extraction():
    """SAD (CVV) + canlı provider -> extract() hiç çağrılmaz, deterministik needs_review."""
    converter = FakeConverter(_markdown_with_cvv())
    extraction_service = SpyExtractionService()
    settings = Settings(llm_provider="openai")

    result = run_extraction(
        Path("herhangi.pdf"),
        settings=settings,
        converter=converter,
        retriever=FakeRetriever(),
        extraction_service=extraction_service,
    )

    assert result.status == "needs_review"
    assert result.data is None
    assert "atlandı" in (result.reason or "")
    assert extraction_service.received_masked_markdown is None  # canlı çağrı yapılmadı


def test_blocking_fake_provider_runs_but_flags_manual_review():
    """SAD + fake provider -> fake çalışır (dışarı veri gitmez) ama needs_manual_review=true."""
    converter = FakeConverter(_markdown_with_cvv())
    extraction_service = SpyExtractionService()
    settings = Settings(llm_provider="fake")

    result = run_extraction(
        Path("herhangi.pdf"),
        settings=settings,
        converter=converter,
        retriever=FakeRetriever(),
        extraction_service=extraction_service,
    )

    assert result.status == "ok"
    assert extraction_service.received_masked_markdown is not None  # fake çalıştı
    assert "123" not in extraction_service.received_masked_markdown  # CVV maskeli
    assert result.data.needs_manual_review is True


def test_pan_risk_flag_merged_into_output():
    """PAN (blocking değil) tespiti risk_flags'e birleşir, needs_manual_review zorlanmaz."""
    converter = FakeConverter("Kart no: 4111111111111111 ile ödeme yapılır.\n")
    extraction_service = SpyExtractionService()
    settings = Settings(llm_provider="fake")

    result = run_extraction(
        Path("herhangi.pdf"),
        settings=settings,
        converter=converter,
        retriever=FakeRetriever(),
        extraction_service=extraction_service,
    )

    assert result.status == "ok"
    assert "PAN_DETECTED" in result.data.risk_flags
    assert result.data.needs_manual_review is False  # PAN SAD değil


def test_cli_main_smoke_end_to_end(tmp_path, capsys):
    import pymupdf

    pdf_path = tmp_path / "sozlesme.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Sozlesme metni. %30 pesin %70 teslimatta odenir.")
    doc.save(str(pdf_path))
    doc.close()

    exit_code = main([str(pdf_path), "--provider", "fake"])
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    validated = ExtractionJSON.model_validate(payload)
    assert isinstance(validated, ExtractionJSON)
