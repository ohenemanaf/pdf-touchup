import pymupdf
import pytest

from pdf_touchup.document import NeedsPassword, WrongPassword, open_document, page_kind


def test_open_plain(native_pdf):
    assert open_document(native_pdf).page_count == 1


def test_open_encrypted_requires_password(encrypted_pdf):
    with pytest.raises(NeedsPassword):
        open_document(encrypted_pdf)
    with pytest.raises(WrongPassword):
        open_document(encrypted_pdf, password="nope")
    assert open_document(encrypted_pdf, password="secret").page_count == 1


def test_page_kind(native_pdf, scanned_pdf, searchable_scan_pdf, rotated_scan_pdf):
    assert page_kind(pymupdf.open(native_pdf)[0]) == "native"
    assert page_kind(pymupdf.open(scanned_pdf)[0]) == "scanned"
    assert page_kind(pymupdf.open(searchable_scan_pdf)[0]) == "searchable_scan"
    assert page_kind(pymupdf.open(rotated_scan_pdf)[0]) == "scanned"


def _scan_with_visible_text(path, scanned_pdf, lines):
    from conftest import FONTS

    doc = pymupdf.open(scanned_pdf)
    page = doc[0]
    for i, text in enumerate(lines):
        page.insert_text((72, 400 + 14 * i), text, fontsize=11, fontname="F0",
                         fontfile=str(FONTS / "LiberationSans-Regular.ttf"))
    doc.save(path)
    return pymupdf.open(path)[0]


def test_scan_with_small_watermark_is_still_a_scan(tmp_path, scanned_pdf):
    page = _scan_with_visible_text(tmp_path / "wm.pdf", scanned_pdf, ["Scanned with CamScanner"])
    assert page_kind(page) == "scanned"


def test_text_page_over_background_image_is_native(tmp_path, scanned_pdf):
    lines = [f"This is line number {i} of a real typed letter body text" for i in range(25)]
    page = _scan_with_visible_text(tmp_path / "bg.pdf", scanned_pdf, lines)
    assert page_kind(page) == "native"
