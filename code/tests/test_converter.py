import pytest

from document_parser.converter import DocumentConverter
from document_parser.exceptions import EmptyDocumentError, ExtractionError
from document_parser.normalizer import MarkdownNormalizer


class FakeFactory:
    def __init__(self, extractor):
        self._extractor = extractor

    def get_extractor(self, file_path):
        return self._extractor


class FakeExtractor:
    def __init__(self, text=None, error=None):
        self._text = text
        self._error = error

    def extract(self, file_path):
        if self._error:
            raise self._error
        return self._text


def test_convert_returns_normalized_text(tmp_path):
    file_path = tmp_path / "sozlesme.pdf"
    file_path.write_bytes(b"")
    factory = FakeFactory(FakeExtractor(text="Madde   1\n\n\n\nMadde 2"))
    converter = DocumentConverter(factory=factory, normalizer=MarkdownNormalizer())

    result = converter.convert(file_path)

    assert result == "Madde 1\n\nMadde 2"
    assert converter.last_provenance["normalizer_version"] == "markdown-normalizer-v1"


def test_convert_raises_for_missing_file(tmp_path):
    converter = DocumentConverter(factory=FakeFactory(FakeExtractor(text="x")))
    with pytest.raises(FileNotFoundError):
        converter.convert(tmp_path / "missing.pdf")


def test_convert_raises_empty_document_error_when_nothing_extracted(tmp_path):
    file_path = tmp_path / "sozlesme.pdf"
    file_path.write_bytes(b"")
    factory = FakeFactory(FakeExtractor(text="   \n\n  "))
    converter = DocumentConverter(factory=factory, normalizer=MarkdownNormalizer())

    with pytest.raises(EmptyDocumentError):
        converter.convert(file_path)


def test_convert_wraps_unexpected_extractor_errors(tmp_path):
    file_path = tmp_path / "sozlesme.pdf"
    file_path.write_bytes(b"")
    factory = FakeFactory(FakeExtractor(error=RuntimeError("boom")))
    converter = DocumentConverter(factory=factory)

    with pytest.raises(ExtractionError):
        converter.convert(file_path)


def test_convert_propagates_extraction_error_unwrapped(tmp_path):
    file_path = tmp_path / "sozlesme.pdf"
    file_path.write_bytes(b"")
    factory = FakeFactory(FakeExtractor(error=ExtractionError("already specific")))
    converter = DocumentConverter(factory=factory)

    with pytest.raises(ExtractionError, match="already specific"):
        converter.convert(file_path)
