"""CLI: sözleşme PDF/DOCX dosyasından §4.2 şemasına uygun extraction JSON üretir.

Hat (pipeline), sırasıyla: convert (document_parser) -> mask (privacy) ->
retrieve (rag) -> extract (extraction service) -> restore + re-validate.

§6.7 (değişmez): dış LLM çağrısına yalnızca maskelenmiş metin gider; bu modül
`extraction_service.extract(...)`'e her zaman `mask()` çıktısını iletir, ham
metni asla iletmez.

Kullanım:
    python scripts/extract_contract.py sozlesme.pdf --provider fake
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

# Import köprüsü: bu betik `code/scripts/` altında yaşar. Proje paketleri iki
# farklı kökten import edilir; her ikisi de `sys.path`'e eklenmeli (backend
# paketleri için `code/`, `document_parser` için `code/scripts/`).
_SCRIPTS_ROOT = Path(__file__).resolve().parent
_CODE_ROOT = _SCRIPTS_ROOT.parent
for _root in (str(_CODE_ROOT), str(_SCRIPTS_ROOT)):
    if _root not in sys.path:
        sys.path.insert(0, _root)

from document_parser import (  # noqa: E402
    DocumentConverter,
    EmptyDocumentError,
    ExtractionError,
    UnsupportedFileTypeError,
)

from pydantic import ValidationError  # noqa: E402

from backend.app.config import Settings  # noqa: E402
from backend.app.schemas.extraction import ExtractionJSON  # noqa: E402
from backend.app.services.context_builder import ContextBuilder, ContextPack  # noqa: E402
from backend.app.services.extraction import (  # noqa: E402
    ExtractionResult,
    make_extraction_service,
)
from backend.app.services.privacy import PrivacyReport, analyze, restore  # noqa: E402
from backend.app.services.rag import Retriever  # noqa: E402

_RAG_QUERY_CHAR_LIMIT = 1000


def _print_rationale(context: ContextPack, report: PrivacyReport | None = None) -> None:
    """Kullanılan query'leri, seçilen kaynakları ve güvenlik sinyallerini stderr'e yazar.

    Demo anlatısının "kanıtlanabilir rule sheet" ayağı: LLM önerisinin hangi
    mevzuat/örnek kaynaklara dayandığı + hangi güvenlik risk/blocking sinyalleri
    tetiklendiği görünür olur. stdout temiz JSON kalır.
    """
    print("--- DAYANAKLAR ---", file=sys.stderr)
    print(f"Query'ler ({len(context.queries)}):", file=sys.stderr)
    for q in context.queries:
        print(f"  [{q.collection}] {q.purpose}: {q.text[:80]}", file=sys.stderr)
    if not context.sources:
        print("Kaynak: (yok — bağlamsız devam)", file=sys.stderr)
    else:
        print(f"Seçilen kaynaklar ({len(context.sources)}):", file=sys.stderr)
        for s in context.sources:
            locator = s.madde_no or s.heading or "-"
            print(
                f"  [{s.source_type}] {s.source} · {locator} · score={s.score:.4f}",
                file=sys.stderr,
            )
    if report is not None:
        if report.risk_flags:
            print(f"Risk flag'leri: {', '.join(report.risk_flags)}", file=sys.stderr)
        if report.blocking_findings:
            print(
                f"BLOCKING (dış LLM atlanır): {'; '.join(report.blocking_findings)}",
                file=sys.stderr,
            )
    print("------------------", file=sys.stderr)


def _merge_risk_flags(payload: dict, risk_flags: list[str], *, needs_review: bool) -> dict:
    """privacy_report risk_flags'ini extraction JSON'a birleştirir (şema değişmez).

    Yalnızca `payload` bir dict ise (data doluyken) çağrılır; blocking'de
    `needs_manual_review=true` set edilir.
    """
    existing = list(payload.get("risk_flags") or [])
    for flag in risk_flags:
        if flag not in existing:
            existing.append(flag)
    payload["risk_flags"] = existing
    if needs_review:
        payload["needs_manual_review"] = True
    return payload


def run_extraction(
    pdf_path: Path,
    *,
    settings: Settings,
    converter=None,
    retriever=None,
    extraction_service=None,
    collection: str | None = None,
    k: int = 3,
) -> ExtractionResult:
    """Tam extraction hattını çalıştırır: convert -> mask -> ContextBuilder -> extract -> restore.

    Bağımlılıklar (`converter`, `retriever`, `extraction_service`) enjekte
    edilmezse `settings`'e göre gerçekleri kurulur (DI, `document_parser`
    stiliyle). Yalnızca MASKELENMİŞ metin `extraction_service.extract()`'e
    gider (§6.7).

    `collection` verilirse (deprecated --collection debug yolu) ContextBuilder
    query planlaması bypass edilir ve tek koleksiyondan tek query ile retrieval
    yapılır; verilmezse ContextBuilder çoklu-query/çoklu-koleksiyon planlar.
    """
    converter = converter if converter is not None else DocumentConverter()
    retriever = retriever if retriever is not None else Retriever(settings)
    extraction_service = (
        extraction_service if extraction_service is not None else make_extraction_service(settings)
    )

    markdown = converter.convert(pdf_path)
    report = analyze(markdown)  # §6.7: mask + kart-verisi sınıflandırma (canlı çağrıdan ÖNCE)

    builder = ContextBuilder(settings, retriever)
    if collection is not None:
        print(
            "UYARI: --collection deprecated; ContextBuilder bypass edilip tek-koleksiyon "
            "debug yoluna düşülüyor.",
            file=sys.stderr,
        )
        query = report.masked_text[:_RAG_QUERY_CHAR_LIMIT]
        try:
            chunks = retriever.retrieve(query, collection=collection, k=k)
        except Exception as exc:  # RAG ağır bağımlılıkları (chromadb/FlagEmbedding) eksik olabilir
            print(
                f"UYARI: RAG erişimi başarısız oldu, bağlamsız devam ediliyor ({exc})",
                file=sys.stderr,
            )
            chunks = []
        context = builder.pack_from_chunks(chunks, collection)
    else:
        context = builder.build(report.masked_text, privacy_report=report)

    _print_rationale(context, report)

    # §6.7 / PCI: SAD (CVV/track/PIN) tespitinde CANLI (openai) provider çağrılmaz.
    # Deterministik tip-tutarlı fallback döner (sahte ExtractionJSON üretilmez).
    if report.blocking_findings and settings.llm_provider == "openai":
        return ExtractionResult(
            status="needs_review",
            data=None,
            reason=(
                "Hassas ödeme doğrulama verisi tespit edildi; dış LLM çağrısı atlandı: "
                + "; ".join(report.blocking_findings)
            ),
        )

    result = extraction_service.extract(report.masked_text, context)

    if result.status != "ok":
        return result

    restored = restore(result.data.model_dump(), report.mapping)
    restored = _merge_risk_flags(
        restored, report.risk_flags, needs_review=bool(report.blocking_findings)
    )
    try:
        validated = ExtractionJSON.model_validate(restored)
    except ValidationError as exc:
        # Hattın "asla çökme, needs_review'a düş" garantisi: restore sonrası
        # doğrulama bozulursa traceback fırlatma, manuel incelemeye yönlendir.
        return ExtractionResult(
            status="needs_review",
            reason=f"restore sonrası doğrulama başarısız: {exc}",
        )
    return ExtractionResult(status="ok", data=validated)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sözleşme dosyasından extraction JSON üretir (§4.2 şeması)."
    )
    parser.add_argument("pdf_path", type=Path, help="Girdi sözleşme dosyası (PDF/DOCX).")
    parser.add_argument(
        "--provider",
        choices=["fake", "openai"],
        default=None,
        help="LLM sağlayıcı; verilmezse env/Settings'ten gelir.",
    )
    parser.add_argument(
        "--collection",
        default=None,
        help="DEPRECATED: verilirse ContextBuilder bypass edilip tek koleksiyonda debug "
        "retrieval yapılır. Verilmezse ContextBuilder çoklu-koleksiyon planlar (varsayılan).",
    )
    parser.add_argument(
        "--k", type=int, default=3, help="Yalnızca --collection debug yolunda: alınacak parça sayısı."
    )
    parser.add_argument("--out", type=Path, default=None, help="Çıktı JSON dosyası (verilmezse stdout).")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    if args.provider is not None:
        settings = dataclasses.replace(settings, llm_provider=args.provider)

    try:
        result = run_extraction(
            args.pdf_path,
            settings=settings,
            collection=args.collection,
            k=args.k,
        )
    except (FileNotFoundError, ExtractionError, EmptyDocumentError, UnsupportedFileTypeError) as exc:
        print(f"HATA: {exc}", file=sys.stderr)
        return 1

    if result.status != "ok":
        print(f"MANUEL İNCELEME GEREKLİ: {result.reason}", file=sys.stderr)
        return 2

    payload = json.dumps(result.data.model_dump(), ensure_ascii=False, indent=2)
    if args.out is not None:
        args.out.write_text(payload, encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
