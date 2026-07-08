from pathlib import Path

import pytest

from document_parser.exceptions import UnsupportedFileTypeError
from document_parser.extractors import DocxExtractor, HybridPdfExtractor
from document_parser.factory import ExtractorFactory


def test_returns_pdf_extractor_for_pdf_extension():
    factory = ExtractorFactory()
    assert isinstance(factory.get_extractor(Path("contract.pdf")), HybridPdfExtractor)


def test_returns_docx_extractor_for_docx_extension():
    factory = ExtractorFactory()
    assert isinstance(factory.get_extractor(Path("contract.docx")), DocxExtractor)


def test_extension_matching_is_case_insensitive():
    factory = ExtractorFactory()
    assert isinstance(factory.get_extractor(Path("contract.PDF")), HybridPdfExtractor)


def test_raises_for_unsupported_extension():
    factory = ExtractorFactory()
    with pytest.raises(UnsupportedFileTypeError):
        factory.get_extractor(Path("contract.txt"))
