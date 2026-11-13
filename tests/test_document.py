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
