"""Maps file extensions to the TextExtractor that handles them.

Adding support for a new file type means registering one more entry here --
existing extractors and callers stay untouched (open/closed principle).
"""

from pathlib import Path
from typing import Dict, Optional

from .exceptions import UnsupportedFileTypeError
from .extractors import DocxExtractor, HybridPdfExtractor
from .interfaces import TextExtractor


class ExtractorFactory:
    def __init__(self, registry: Optional[Dict[str, TextExtractor]] = None):
        self._registry = registry or {
            ".pdf": HybridPdfExtractor(),
            ".docx": DocxExtractor(),
        }

    def get_extractor(self, file_path: Path) -> TextExtractor:
        suffix = file_path.suffix.lower()
        try:
            return self._registry[suffix]
        except KeyError:
            raise UnsupportedFileTypeError(
                f"No extractor registered for '{suffix}' files ({file_path.name}). "
                f"Supported types: {', '.join(sorted(self._registry))}"
            ) from None
