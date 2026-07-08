"""Extraction port: every concrete extractor implements this contract."""

from abc import ABC, abstractmethod
from pathlib import Path


class TextExtractor(ABC):
    """Extracts raw text from a single document.

    Implementations must not clean or reformat the text -- normalization is
    MarkdownNormalizer's job, kept separate so extraction and cleaning can be
    tested and changed independently.
    """

    @abstractmethod
    def extract(self, file_path: Path) -> str:
        raise NotImplementedError
