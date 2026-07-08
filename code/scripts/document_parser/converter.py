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

    def convert(self, file_path: Path) -> str:
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(file_path)

        logger.info("Converting %s", file_path.name)
        extractor = self._factory.get_extractor(file_path)

        try:
            raw_text = extractor.extract(file_path)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Unexpected error extracting {file_path}: {exc}") from exc

        clean_text = self._normalizer.normalize(raw_text)
        if not clean_text:
            raise EmptyDocumentError(f"{file_path.name} produced no usable text after extraction")

        logger.info("Converted %s -> %d characters", file_path.name, len(clean_text))
        return clean_text
