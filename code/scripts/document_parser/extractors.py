"""Concrete TextExtractor implementations, one per source format.

DigitalPdfExtractor and OcrPdfExtractor are single-purpose. HybridPdfExtractor
composes them (digital text first, OCR fallback per page) so callers never
have to know or check whether a given PDF is a scan -- mixed documents
(some digital pages, some scanned) are handled transparently.
"""

import logging
import shutil
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
import pytesseract
from docx import Document
from PIL import Image

from .exceptions import ExtractionError
from .interfaces import TextExtractor

logger = logging.getLogger(__name__)

# Below this many characters of digital text, a PDF page is treated as a
# scan (image-only) rather than as a page with a real text layer.
MIN_DIGITAL_CHARS_PER_PAGE = 20

# The Windows installer sometimes skips "add to PATH" even when the binary
# itself is installed. Fall back to the well-known default install location
# so OCR still works without requiring a manual PATH edit on every machine.
_WINDOWS_DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if not shutil.which("tesseract") and Path(_WINDOWS_DEFAULT_TESSERACT).exists():
    pytesseract.pytesseract.tesseract_cmd = _WINDOWS_DEFAULT_TESSERACT
    logger.info("tesseract not on PATH, using default install path %s", _WINDOWS_DEFAULT_TESSERACT)
OCR_RENDER_DPI = 300
OCR_LANGUAGE = "tur"


class DigitalPdfExtractor(TextExtractor):
    """Extracts text from PDF pages that already carry a text layer."""

    def extract_page(self, page: "fitz.Page") -> str:
        return page.get_text().strip()

    def extract(self, file_path: Path) -> str:
        try:
            with fitz.open(file_path) as doc:
                return "\n\n".join(self.extract_page(page) for page in doc)
        except Exception as exc:
            raise ExtractionError(f"Digital PDF extraction failed for {file_path}: {exc}") from exc


class OcrPdfExtractor(TextExtractor):
    """Extracts text from PDF pages via Tesseract, rendering each page to an image first.

    Requires the Tesseract binary to be installed on the host machine --
    pytesseract is only a wrapper around that executable, not an OCR engine
    itself.
    """

    def __init__(self, dpi: int = OCR_RENDER_DPI, lang: str = OCR_LANGUAGE):
        self.dpi = dpi
        self.lang = lang

    def extract_page(self, page: "fitz.Page") -> str:
        pixmap = page.get_pixmap(dpi=self.dpi)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        return pytesseract.image_to_string(image, lang=self.lang).strip()

    def extract(self, file_path: Path) -> str:
        try:
            with fitz.open(file_path) as doc:
                return "\n\n".join(self.extract_page(page) for page in doc)
        except pytesseract.TesseractNotFoundError as exc:
            raise ExtractionError(
                "Tesseract OCR engine not found on this machine. It is a "
                "system binary, not a pip package -- install it separately "
                "and make sure it is on PATH."
            ) from exc
        except Exception as exc:
            raise ExtractionError(f"OCR extraction failed for {file_path}: {exc}") from exc


class HybridPdfExtractor(TextExtractor):
    """The PDF extractor registered with the factory.

    Tries digital text extraction per page; any page that comes back
    (near-)empty is assumed to be a scanned image and is re-extracted via
    OCR, so mixed PDFs are handled without the caller having to know which
    pages are which.
    """

    def __init__(
        self,
        digital_extractor: Optional[DigitalPdfExtractor] = None,
        ocr_extractor: Optional[OcrPdfExtractor] = None,
        min_digital_chars: int = MIN_DIGITAL_CHARS_PER_PAGE,
    ):
        self.digital_extractor = digital_extractor or DigitalPdfExtractor()
        self.ocr_extractor = ocr_extractor or OcrPdfExtractor()
        self.min_digital_chars = min_digital_chars

    def extract(self, file_path: Path) -> str:
        try:
            with fitz.open(file_path) as doc:
                pages = []
                for i, page in enumerate(doc):
                    text = self.digital_extractor.extract_page(page)
                    if len(text) < self.min_digital_chars:
                        logger.info(
                            "Page %d of %s has no digital text layer, falling back to OCR",
                            i,
                            file_path.name,
                        )
                        text = self.ocr_extractor.extract_page(page)
                    pages.append(text)
                return "\n\n".join(pages)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"PDF extraction failed for {file_path}: {exc}") from exc


class DocxExtractor(TextExtractor):
    """Extracts text from DOCX files, including paragraph and table content."""

    def extract(self, file_path: Path) -> str:
        try:
            document = Document(file_path)
        except Exception as exc:
            raise ExtractionError(f"DOCX extraction failed for {file_path}: {exc}") from exc

        parts = [p.text for p in document.paragraphs if p.text.strip()]
        for table in document.tables:
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    parts.append(" | ".join(cells))
        return "\n\n".join(parts)
