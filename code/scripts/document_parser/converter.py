"""Runtime document -> markdown conversion: the single entry point callers use.

    from document_parser import DocumentConverter
    text = DocumentConverter().convert(Path("sozlesme.pdf"))
"""

import logging
from pathlib import Path
from typing import Optional

from .exceptions import EmptyDocumentError, ExtractionError
from .factory import ExtractorFactory
from .normalizer import MarkdownNormalizer

logger = logging.getLogger(__name__)


class DocumentConverter:
    """Converts an uploaded PDF/DOCX file into clean markdown text."""

    def __init__(
        self,
        factory: Optional[ExtractorFactory] = None,
        normalizer: Optional[MarkdownNormalizer] = None,
    ):
        self._factory = factory or ExtractorFactory()
        self._normalizer = normalizer or MarkdownNormalizer()
        self.last_provenance: dict = {}

    def convert(self, file_path: Path) -> str:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(file_path)

        logger.info("Document conversion started")
        extractor = self._factory.get_extractor(file_path)

        try:
            raw_text = extractor.extract(file_path)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError("Unexpected document extraction error.") from exc

        clean_text = self._normalizer.normalize(raw_text)
        if not clean_text:
            raise EmptyDocumentError("Document produced no usable text after extraction")

        self.last_provenance = dict(getattr(extractor, "last_provenance", {}) or {})
        self.last_provenance["normalizer_version"] = "markdown-normalizer-v1"
        logger.info("Document conversion completed (%d characters)", len(clean_text))
        return clean_text
