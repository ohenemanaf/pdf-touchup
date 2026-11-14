import numpy as np
import pymupdf
import pytest

from pdf_touchup.ocr import ocr_words
from pdf_touchup.scan_pixels import decode, find_scan_image, place_patch, px_box


def _lum(a):
    a = a.astype(float) / 255
    return a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114


def test_find_scan_image_on_scan(scanned_pdf, native_pdf):
    page = pymupdf.open(scanned_pdf)[0]
    scan = find_scan_image(page)
    assert scan is not None and scan.shared is False
    pix = pymupdf.Pixmap(page.parent, scan.xref)
    assert (scan.width, scan.height) == (pix.width, pix.height)
    assert find_scan_image(pymupdf.open(native_pdf)[0]) is None


def test_shared_image_detected(multipage_scan_pdf):
    page = pymupdf.open(multipage_scan_pdf)[0]
    assert find_scan_image(page).shared is (len({x[0] for p in page.parent for x in p.get_images()}) == 1)


@pytest.mark.ocr
@pytest.mark.parametrize("fixture", ["scanned_pdf", "rotated_scan_pdf"])
def test_px_box_hits_the_word_ink(request, fixture):
    page = pymupdf.open(request.getfixturevalue(fixture))[0]
    scan = find_scan_image(page)
    img = decode(page, scan)
    word = next(w for w in ocr_words(page) if w.text == "Mensah")
    x0, y0, x1, y1 = px_box(scan, word.rect)
    inside = _lum(img[y0:y1, x0:x1])
    assert (inside < 0.5).mean() >= 0.05
    # The same-size box well to the right of the line is blank paper.
    away = (word.rect[0] + 150, word.rect[1], word.rect[2] + 150, word.rect[3])
    ax0, ay0, ax1, ay1 = px_box(scan, away)
    assert (_lum(img[ay0:ay1, ax0:ax1]) < 0.5).mean() < 0.01


def test_place_patch_maps_top_left_on_rotated_page(rotated_scan_pdf):
    page = pymupdf.open(rotated_scan_pdf)[0]
    scan = find_scan_image(page)
    s = scan.px_per_pt
    patch = np.zeros((20, 40))
    patch[0:3, 0:3] = 1.0
    box, warped = place_patch(scan, patch, (100.0, 200.0), s)
    expected = pymupdf.Point(100.0, 200.0) * scan.to_px
    ys, xs = np.nonzero(warped > 0.5)
    got_x, got_y = box[0] + xs.mean(), box[1] + ys.mean()
    assert abs(got_x - expected.x) <= 3 and abs(got_y - expected.y) <= 3
    assert warped.shape == (box[3] - box[1], box[2] - box[0])
