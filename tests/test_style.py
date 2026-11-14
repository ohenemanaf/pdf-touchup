import numpy as np
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
    assert abs(s.size - 11.0) <= 0.4, s.size
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


@pytest.mark.ocr
@pytest.mark.parametrize("grow", [-0.5, 2.0])
def test_scanned_size_survives_loose_ocr_box(scanned_pdf, grow):
    """OCR boxes on real scans are often taller or shorter than the ink (one line gave 12.1 pt
    and 15.7 pt for neighbouring words). The size must come from the ink, not the box height."""
    from pdf_touchup.ocr import ocr_words

    page = pymupdf.open(scanned_pdf)[0]
    w = next(w for w in ocr_words(page) if w.text == "March")
    x0, y0, x1, y1 = w.rect
    loose = (x0, y0 - grow, x1, y1 + grow)
    size = detect_style(page, loose, "March", "March", "scanned").size
    assert abs(size - 11.0) <= 0.6, size


@pytest.mark.ocr
def test_scanned_size_fit_is_capped_when_ocr_text_misses_spaces(tmp_path):
    """OCR often merges "7 / I ." into one word "7/1."; fitting that text to the wider ink must
    not blow the size up (a reviewer probe got 15.6 pt for 11 pt text)."""
    import sys

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from test_edits import _scan_of
    from pdf_touchup.ocr import ocr_words

    src = _scan_of(tmp_path, "merged", [((72, 100), "Date: 1 March 2024, Ref 7 / I . ill 11")])
    page = pymupdf.open(src)[0]
    sizes = {w.text: detect_style(page, w.rect, w.text, w.text, "scanned").size
             for w in ocr_words(page) if 85 < w.rect[3] < 110}
    assert all(11 * 0.85 - 0.6 <= v <= 11 * 1.15 + 0.6 for v in sizes.values()), sizes


@pytest.mark.ocr
def test_scanned_size_uses_the_whole_line(tmp_path):
    """Words on one line share a size: a misread or oddly boxed word is outvoted by its line."""
    import sys

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from test_edits import _scan_of
    from pdf_touchup.ocr import ocr_words

    src = _scan_of(tmp_path, "line", [((72, 100), "Date: 1 March 2024, Ref 7 / I . ill 11")])
    page = pymupdf.open(src)[0]
    line = [w for w in ocr_words(page) if 85 < w.rect[3] < 110]
    merged = next(w for w in line if "/" in w.text)
    size = detect_style(page, merged.rect, merged.text, merged.text, "scanned", line_words=line).size
    assert abs(size - 11.0) <= 0.6, size
