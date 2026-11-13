import pymupdf


def test_native_fixture_has_text(native_pdf):
    assert "Kwame Mensah" in pymupdf.open(native_pdf)[0].get_text()


def test_scanned_fixture_has_no_text(scanned_pdf):
    page = pymupdf.open(scanned_pdf)[0]
    assert page.get_text().strip() == ""
    assert len(page.get_images()) == 1


def test_searchable_scan_has_text_and_image(searchable_scan_pdf):
    page = pymupdf.open(searchable_scan_pdf)[0]
    assert "Kwame Mensah" in page.get_text()
    assert len(page.get_images()) == 1


def test_rotated_fixture(rotated_scan_pdf):
    assert pymupdf.open(rotated_scan_pdf)[0].rotation == 90


def test_encrypted_fixture(encrypted_pdf):
    assert pymupdf.open(encrypted_pdf).needs_pass


def test_rotated_fixture_displays_portrait(rotated_scan_pdf):
    page = pymupdf.open(rotated_scan_pdf)[0]
    assert (page.rect.width, page.rect.height) == (595, 842)
