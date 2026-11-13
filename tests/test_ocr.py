import pymupdf
import pytest

from pdf_touchup import ocr
from pdf_touchup.ocr import OcrUnavailable, ocr_words
from pdf_touchup.resources import tesseract_paths
from pdf_touchup.text_source import native_words

needs_tesseract = pytest.mark.skipif(tesseract_paths() is None, reason="Tesseract not installed")


def _by_text(words):
    return {w.text: w for w in words}


def _close(a, b, tol=3.0):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


@pytest.mark.ocr
@needs_tesseract
def test_ocr_reads_scanned_name(scanned_pdf, native_pdf):
    got = _by_text(ocr_words(pymupdf.open(scanned_pdf)[0]))
    ref = _by_text(native_words(pymupdf.open(native_pdf)[0]))
    assert got["Kwame"].line_id == got["Mensah"].line_id
    for name in ("Kwame", "Mensah"):
        assert _close(got[name].rect, ref[name].rect), (got[name].rect, ref[name].rect)


@pytest.mark.ocr
@needs_tesseract
def test_ocr_rotated_page_in_display_space(rotated_scan_pdf, native_pdf):
    got = _by_text(ocr_words(pymupdf.open(rotated_scan_pdf)[0]))
    ref = _by_text(native_words(pymupdf.open(native_pdf)[0]))
    assert _close(got["Mensah"].rect, ref["Mensah"].rect), (got["Mensah"].rect, ref["Mensah"].rect)


def test_ocr_unavailable_raises(scanned_pdf, monkeypatch):
    monkeypatch.setattr(ocr, "tesseract_paths", lambda: None)
    with pytest.raises(OcrUnavailable):
        ocr_words(pymupdf.open(scanned_pdf)[0])
