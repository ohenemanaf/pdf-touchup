import pymupdf
import pytest

from pdf_touchup.selection import merge_selection
from pdf_touchup.style import detect_style
from pdf_touchup.text_source import native_words

CREAM = tuple(c / 255 for c in (245, 240, 225))
INK = tuple(c / 255 for c in (40, 40, 60))


def _near(a, b, tol):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def _name_rect(path):
    page = pymupdf.open(path)[0]
    words = [w for w in native_words(page) if w.text in ("Kwame", "Mensah")]
    return merge_selection(words)[0]


def test_native_style(native_pdf):
    page = pymupdf.open(native_pdf)[0]
    s = detect_style(page, _name_rect(native_pdf), "Kwame Mensah", "Kwame Asante", "native")
    assert abs(s.size - 11.0) <= 0.1
    assert _near(s.color, (0, 0, 0), 0.05)
    assert s.family == "serif"
    assert _near(s.background, (1, 1, 1), 0.02)


def test_native_reuses_embedded_font_when_glyphs_present(native_fullfont_pdf):
    page = pymupdf.open(native_fullfont_pdf)[0]
    s = detect_style(page, _name_rect(native_fullfont_pdf), "Kwame Mensah", "Kwame Asante", "native")
    assert s.font_buffer is not None


def test_native_drops_embedded_font_when_glyph_missing(native_fullfont_pdf):
    from test_fonts import _absent_char

    page = pymupdf.open(native_fullfont_pdf)[0]
    s = detect_style(page, _name_rect(native_fullfont_pdf), "Kwame Mensah", f"Kwame {_absent_char()}", "native")
    assert s.font_buffer is None


def test_native_subset_font_falls_back_to_bundled(native_pdf):
    # Subset Type0/Identity-H fonts carry no character map, so they cannot be reused safely.
    page = pymupdf.open(native_pdf)[0]
    s = detect_style(page, _name_rect(native_pdf), "Kwame Mensah", "Kwame Asante", "native")
    assert s.font_buffer is None
    assert s.family == "serif"


def _ocr_name_rect(page):
    from pdf_touchup.ocr import ocr_words

    return merge_selection([w for w in ocr_words(page) if w.text in ("Kwame", "Mensah")])[0]


@pytest.mark.ocr
def test_scanned_style(scanned_pdf):
    page = pymupdf.open(scanned_pdf)[0]
    s = detect_style(page, _ocr_name_rect(page), "Kwame Mensah", "Kwame Asante", "scanned")
    assert abs(s.size - 11.0) <= 1.0, s.size
    assert s.family == "serif"
    assert _near(s.background, CREAM, 0.03)
    assert _near(s.color, INK, 0.08)
    assert s.font_buffer is None


def test_searchable_scan_style_uses_text_layer_size(searchable_scan_pdf):
    page = pymupdf.open(searchable_scan_pdf)[0]
    s = detect_style(page, _name_rect(searchable_scan_pdf), "Kwame Mensah", "Kwame Asante", "searchable_scan")
    assert abs(s.size - 11.0) <= 0.1
    assert s.family == "serif"
    assert _near(s.background, CREAM, 0.03)
    assert _near(s.color, INK, 0.08)
    assert s.font_buffer is None
