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
