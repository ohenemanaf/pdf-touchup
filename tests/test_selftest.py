import pymupdf
import pytest

from pdf_touchup.selftest import run


@pytest.mark.ocr
def test_selftest_passes_on_scanned_sample(scanned_pdf):
    assert run(scanned_pdf) == 0


def test_selftest_fails_on_blank(tmp_path):
    blank = tmp_path / "blank.pdf"
    doc = pymupdf.open()
    doc.new_page()
    doc.save(blank)
    assert run(blank) == 1
