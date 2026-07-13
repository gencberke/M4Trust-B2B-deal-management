from pathlib import Path

import docx
import fitz
import pytest

from document_parser.exceptions import ExtractionError
from document_parser.extractors import DigitalPdfExtractor, DocxExtractor, HybridPdfExtractor


def make_pdf(tmp_path: Path, text: str) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    path = tmp_path / "sample.pdf"
    doc.save(path)
    doc.close()
    return path


def make_blank_pdf(tmp_path: Path) -> Path:
    doc = fitz.open()
    doc.new_page()
    path = tmp_path / "blank.pdf"
    doc.save(path)
    doc.close()
    return path


def make_docx(tmp_path: Path, paragraphs: list) -> Path:
    document = docx.Document()
    for para in paragraphs:
        document.add_paragraph(para)
    path = tmp_path / "sample.docx"
    document.save(path)
    return path


class FakePageExtractor:
    """Stand-in for OcrPdfExtractor so hybrid-routing tests don't need a real
    Tesseract install."""

    def __init__(self, page_text: str):
        self.page_text = page_text
        self.calls = 0

    def extract_page(self, page):
        self.calls += 1
        return self.page_text


def test_digital_pdf_extractor_reads_text_layer(tmp_path):
    pdf_path = make_pdf(tmp_path, "Test metni")
    text = DigitalPdfExtractor().extract(pdf_path)
    assert "Test metni" in text


def test_digital_pdf_extractor_raises_extraction_error_for_bad_file(tmp_path):
    bad_path = tmp_path / "not_a_pdf.pdf"
    bad_path.write_text("this is not a real pdf")
    with pytest.raises(ExtractionError):
        DigitalPdfExtractor().extract(bad_path)


def test_docx_extractor_reads_paragraphs(tmp_path):
    docx_path = make_docx(tmp_path, ["Madde 1", "Madde 2"])
    text = DocxExtractor().extract(docx_path)
    assert "Madde 1" in text
    assert "Madde 2" in text


def test_docx_extractor_raises_extraction_error_for_bad_file(tmp_path):
    bad_path = tmp_path / "not_a_docx.docx"
    bad_path.write_text("this is not a real docx")
    with pytest.raises(ExtractionError):
        DocxExtractor().extract(bad_path)


def test_hybrid_pdf_extractor_uses_digital_text_when_present(tmp_path):
    pdf_path = make_pdf(tmp_path, "Bu bir dijital sayfa metnidir ve yeterince uzundur.")
    ocr = FakePageExtractor("OCR SONUCU")
    extractor = HybridPdfExtractor(ocr_extractor=ocr)

    text = extractor.extract(pdf_path)

    assert "dijital sayfa metnidir" in text
    assert ocr.calls == 0
    assert extractor.last_provenance["ocr_engine"] is None
    assert extractor.last_provenance["page_count"] == 1


def test_hybrid_pdf_extractor_falls_back_to_ocr_for_blank_page(tmp_path):
    pdf_path = make_blank_pdf(tmp_path)
    ocr = FakePageExtractor("OCR SONUCU")
    extractor = HybridPdfExtractor(ocr_extractor=ocr)

    text = extractor.extract(pdf_path)

    assert text == "OCR SONUCU"
    assert ocr.calls == 1
    assert extractor.last_provenance["ocr_engine"] == "tesseract"
    assert extractor.last_provenance["ocr_pages"] == [1]
