import pymupdf

from pdf_touchup.text_source import native_words


def test_native_words_finds_name(native_pdf):
    words = {w.text: w for w in native_words(pymupdf.open(native_pdf)[0])}
    assert words["Kwame"].line_id == words["Mensah"].line_id
    assert words["Kwame"].rect[0] > 72
    assert words["Kwame"].rect[0] < words["Mensah"].rect[0]


def test_native_words_in_display_space(native_pdf):
    doc = pymupdf.open(native_pdf)
    page = doc[0]
    page.set_rotation(90)
    kwame = next(w for w in native_words(page) if w.text == "Kwame")
    raw = next(w for w in page.get_text("words") if w[4] == "Kwame")
    expected = pymupdf.Rect(raw[:4]) * page.rotation_matrix
    assert pymupdf.Rect(kwame.rect) == expected
    assert page.rect.contains(pymupdf.Rect(kwame.rect))


def test_cache_is_lazy_and_memoised(multipage_scan_pdf):
    from pdf_touchup.text_source import PageTextCache

    seen = []

    def fake_ocr(page):
        seen.append(page.number)
        return []

    cache = PageTextCache(pymupdf.open(multipage_scan_pdf), ocr=fake_ocr)
    first = cache.get(2)
    assert cache.get(2) is first
    assert seen == [2]
    assert first.kind == "scanned"


def test_cache_uses_text_layer_for_searchable_scan(searchable_scan_pdf):
    from pdf_touchup.text_source import PageTextCache

    def fake_ocr(page):
        raise AssertionError("OCR must not run on a page that already has a text layer")

    got = PageTextCache(pymupdf.open(searchable_scan_pdf), ocr=fake_ocr).get(0)
    assert got.kind == "searchable_scan"
    assert "Kwame" in [w.text for w in got.words]


def test_cache_put_and_has(scanned_pdf):
    from pdf_touchup.model import PageText
    from pdf_touchup.text_source import PageTextCache

    cache = PageTextCache(pymupdf.open(scanned_pdf), ocr=lambda p: 1 / 0)
    assert not cache.has(0)
    pt = PageText(0, "scanned", [])
    cache.put(pt)
    assert cache.has(0) and cache.get(0) is pt
