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
from backend.app.services.extraction import (  # noqa: E402
    ExtractionResult,
    make_extraction_service,
)
from backend.app.services.privacy import mask, restore  # noqa: E402
from backend.app.services.rag import Retriever  # noqa: E402

_RAG_QUERY_CHAR_LIMIT = 1000


def run_extraction(
    pdf_path: Path,
    *,
    settings: Settings,
    converter=None,
    retriever=None,
    extraction_service=None,
    collection: str | None = None,
    k: int = 5,
) -> ExtractionResult:
    """Tam extraction hattını çalıştırır: convert -> mask -> retrieve -> extract -> restore.

    Bağımlılıklar (`converter`, `retriever`, `extraction_service`) enjekte
    edilmezse `settings`'e göre gerçekleri kurulur (DI, `document_parser`
    stiliyle). Yalnızca MASKELENMİŞ metin `extraction_service.extract()`'e
    gider (§6.7).
    """
    converter = converter if converter is not None else DocumentConverter()
    retriever = retriever if retriever is not None else Retriever(settings)
    extraction_service = (
        extraction_service if extraction_service is not None else make_extraction_service(settings)
    )

    markdown = converter.convert(pdf_path)
    mr = mask(markdown)

    query = mr.masked_text[:_RAG_QUERY_CHAR_LIMIT]
    collection_name = collection if collection is not None else settings.legal_collection
    try:
        rag_context = retriever.retrieve(query, collection=collection_name, k=k)
    except Exception as exc:  # RAG ağır bağımlılıkları (chromadb/FlagEmbedding) eksik olabilir
        print(
            f"UYARI: RAG erişimi başarısız oldu, bağlamsız devam ediliyor ({exc})",
            file=sys.stderr,
        )
        rag_context = []

    result = extraction_service.extract(mr.masked_text, rag_context)

    if result.status != "ok":
        return result

    restored = restore(result.data.model_dump(), mr.mapping)
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
        help="RAG koleksiyon adı; verilmezse settings.legal_collection kullanılır.",
    )
    parser.add_argument("--k", type=int, default=5, help="RAG'dan alınacak parça sayısı.")
    parser.add_argument("--out", type=Path, default=None, help="Çıktı JSON dosyası (verilmezse stdout).")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    if args.provider is not None:
        settings = dataclasses.replace(settings, llm_provider=args.provider)

    collection = args.collection if args.collection is not None else settings.legal_collection

    try:
        result = run_extraction(
            args.pdf_path,
            settings=settings,
            collection=collection,
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
