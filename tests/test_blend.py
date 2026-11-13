import pytest

from helpers import px_box, render, word_rect
from pdf_touchup.blend import background_color, font_size_pt, guess_family, ink_color, width_scale
from pdf_touchup.fonts import load_font

CREAM = tuple(c / 255 for c in (245, 240, 225))
INK = tuple(c / 255 for c in (40, 40, 60))


def _near(a, b, tol):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def test_background_color_on_scan(scanned_pdf, native_pdf):
    box = px_box(word_rect(native_pdf, "Kwame"))
    assert _near(background_color(render(scanned_pdf), box), CREAM, 0.03)


def test_ink_color_on_scan(scanned_pdf, native_pdf):
    img = render(scanned_pdf)
    box = px_box(word_rect(native_pdf, "Kwame"))
    assert _near(ink_color(img, box, background_color(img, box)), INK, 0.08)


def test_font_size_ratios():
    assert font_size_pt(9.3, "gyp") == 10.0
    assert font_size_pt(7.2, "Kwame") == 10.0
    assert font_size_pt(5.0, "ace") == 10.0


@pytest.mark.parametrize("fixture,native,expected", [
    ("scanned_pdf", "native_pdf", "serif"),
    ("scanned_sans_pdf", "native_sans_pdf", "sans"),
])
def test_guess_family(request, fixture, native, expected):
    scan, ref = request.getfixturevalue(fixture), request.getfixturevalue(native)
    img = render(scan)
    box = px_box(word_rect(ref, "Mensah"))
    assert guess_family(img, box, "Mensah", 11 * 200 / 72, background_color(img, box)) == expected


def test_width_scale_clamps():
    font = load_font("serif")
    old_w = font.text_length("Mensah", 11)
    assert width_scale("Mensah", "Mensah Kofi Boateng", font, 11, old_w) == 1.0
    s = width_scale("Mensah", "Asante", font, 11, old_w)
    assert 0.90 <= s <= 1.10
    assert width_scale("Mensah", "Mmmmmm", font, 11, old_w) == 0.90

