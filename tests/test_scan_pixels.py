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


# ---- Task 2: pixel operations --------------------------------------------------------
from pdf_touchup.scan_pixels import composite, estimate_blur, gaussian_blur, paper_fill, text_mask  # noqa: E402

CREAM = np.array((245, 240, 225)) / 255
INK = (40 / 255, 40 / 255, 60 / 255)


def _paper(h, w, seed=0, sigma=4):
    rng = np.random.default_rng(seed)
    img = np.array((245, 240, 225), float) + rng.normal(0, sigma, (h, w, 3))
    return np.clip(img, 0, 255).astype(np.uint8)


def _draw_text(img, text, size_px, top_left, sigma=0.0):
    mask, _ = text_mask(text, "serif", None, size_px, 1.0)
    mask = gaussian_blur(mask, sigma)
    y, x = top_left
    h, w = mask.shape
    region = img[y:y + h, x:x + w].astype(float)
    a = mask[..., None]
    img[y:y + h, x:x + w] = np.clip(region * (1 - a) + np.array(INK) * 255 * a, 0, 255).astype(np.uint8)
    ys, xs = np.nonzero(mask > 0.1)
    return (x + xs.min(), y + ys.min(), x + xs.max() + 1, y + ys.max() + 1)


def test_gaussian_blur_preserves_mean_and_softens():
    a = np.zeros((40, 40))
    a[18:22, 18:22] = 1.0
    b = gaussian_blur(a, 2.0)
    assert abs(b.sum() - a.sum()) < 0.5
    assert b.max() < 0.6
    assert np.array_equal(gaussian_blur(a, 0), a)


def test_paper_fill_matches_grain():
    img = _paper(200, 400)
    box = _draw_text(img, "Mensah", 40, (40, 60), sigma=1.0)
    ref_sigma = (img[5:30, :, 0].astype(float)).std() / 255
    paper_fill(img, box, band=8, rng=np.random.default_rng(1))
    x0, y0, x1, y1 = box
    fill = img[y0:y1, x0:x1].astype(float) / 255
    assert np.abs(fill.reshape(-1, 3).mean(axis=0) - CREAM).max() <= 0.03
    assert 0.5 * ref_sigma <= fill[..., 0].std() <= 2 * ref_sigma
    assert _lum(img[y0:y1, x0:x1]).min() >= 0.6


def test_paper_fill_follows_gradient():
    ys, xs = np.mgrid[0:60, 0:100]
    base = 120 + xs * 0.5 + ys * 1.0
    img = np.repeat(base[..., None], 3, axis=2).astype(np.uint8)
    img[20:40, 30:70] = 0
    paper_fill(img, (30, 20, 70, 40), band=6, rng=np.random.default_rng(0))
    top = img[20, 30:70, 0].astype(int)
    above = img[19, 30:70, 0].astype(int)
    bottom = img[39, 30:70, 0].astype(int)
    below = img[40, 30:70, 0].astype(int)
    assert np.abs(top - above).max() <= 4
    assert np.abs(bottom - below).max() <= 4


def test_paper_fill_ignores_neighbour_ink():
    img = _paper(90, 200)
    img[25:29, 20:180] = (30, 30, 40)  # line of ink just above
    img[47:51, 20:180] = (30, 30, 40)  # and just below
    img[31:45, 40:160] = (30, 30, 40)  # the word being erased
    paper_fill(img, (40, 31, 160, 45), band=8, rng=np.random.default_rng(0))
    assert _lum(img[31:45, 40:160]).min() >= 0.6


@pytest.mark.parametrize("sigma", [0.0, 1.5, 2.5])
def test_estimate_blur_recovers_sigma(sigma):
    img = _paper(200, 400, sigma=2)
    box = _draw_text(img, "Mensah", 40, (30, 40), sigma=sigma)
    got = estimate_blur(img, box, "Mensah", "serif", None, 40)
    assert abs(got - sigma) <= 0.5, got


def test_text_mask_width_scales():
    a, _ = text_mask("Mensah", "serif", None, 40, 1.0)
    b, _ = text_mask("Mensah", "serif", None, 40, 1.1)
    wa = np.nonzero(a.max(axis=0) > 0.1)[0]
    wb = np.nonzero(b.max(axis=0) > 0.1)[0]
    ratio = (wb.max() - wb.min()) / (wa.max() - wa.min())
    assert abs(ratio - 1.1) <= 0.033


def test_composite_draws_ink_with_grain():
    img = _paper(80, 300)
    mask = np.zeros((20, 100))
    mask[5:15, 10:90] = 1.0
    composite(img, mask, (50, 30), INK, grain_sigma=0.02, rng=np.random.default_rng(0))
    core = img[35:45, 60:140].astype(float) / 255
    assert np.abs(core.reshape(-1, 3).mean(axis=0) - np.array(INK)).max() <= 0.03
    assert core[..., 0].std() > 0.005  # not a flat fill


@pytest.mark.parametrize("fixture", ["scanned_pdf", "rotated_scan_pdf"])
def test_upright_round_trip_is_lossless(request, fixture):
    """Cutting a piece out of the scan and writing it back must not duplicate or drop pixels."""
    from pdf_touchup.scan_pixels import _sample_upright, _write_back, snap_region

    page = pymupdf.open(request.getfixturevalue(fixture))[0]
    scan = find_scan_image(page)
    img = decode(page, scan)
    region = snap_region(scan, pymupdf.Rect(100.37, 91.13, 181.9, 108.55))
    upright = _sample_upright(img, scan, region, scan.px_per_pt_xy)
    # Every image pixel in the region appears exactly once in the upright piece.
    x0, y0, x1, y1 = px_box(scan, region)
    assert upright.shape[0] * upright.shape[1] == (x1 - x0) * (y1 - y0)
    copy = img.copy()
    _write_back(copy, scan, upright, region, scan.px_per_pt_xy)
    assert np.array_equal(copy, img)


@pytest.mark.parametrize("sigma", [0.0, 1.0])
@pytest.mark.parametrize("shift", [-2, -1, 1, 2])
def test_estimate_blur_is_stable_when_box_is_off_by_pixels(shift, sigma):
    """OCR boxes are never pixel-perfect; a box 1-2 px off must not change the answer."""
    img = _paper(200, 400, sigma=2)
    x0, y0, x1, y1 = _draw_text(img, "Mensah", 30, (30, 40), sigma=sigma)
    got = estimate_blur(img, (x0 + shift, y0, x1 + shift, y1), "Mensah", "serif", None, 30)
    assert abs(got - sigma) <= 0.5, got


# ---- ink spread (scanned letters are bolder than clean text) ---------------------------
from pdf_touchup.scan_pixels import estimate_ink, ink_mask  # noqa: E402


def test_text_mask_weight_makes_strokes_heavier():
    thin, _ = text_mask("Mensah", "serif", None, 30, 1.0)
    bold, _ = text_mask("Mensah", "serif", None, 30, 1.0, weight=0.04)
    assert bold.sum() > 1.15 * thin.sum()


@pytest.mark.parametrize("weight", [0.0, 0.04])
def test_estimate_ink_recovers_weight(weight):
    img = _paper(200, 400, sigma=2)
    mask, _ = text_mask("Mensah", "serif", None, 30, 1.0, weight=weight)
    mask = gaussian_blur(mask, 1.0)
    y, x = 40, 30
    h, w = mask.shape
    a = mask[..., None]
    img[y:y + h, x:x + w] = np.clip(img[y:y + h, x:x + w] * (1 - a) + np.array(INK) * 255 * a, 0, 255).astype(np.uint8)
    ys, xs = np.nonzero(mask > 0.1)
    box = (x + xs.min(), y + ys.min(), x + xs.max() + 1, y + ys.max() + 1)
    sigma, got, _, _ = estimate_ink(img, box, "Mensah", "serif", None, 30)
    assert abs(got - weight) <= 0.015, got
    assert abs(sigma - 1.0) <= 0.5, sigma


@pytest.mark.parametrize("size_error", [0.9, 1.1])
def test_estimate_ink_survives_wrong_size_guess(size_error):
    """OCR-based size guesses are often 5-30% off; the ink estimate must still be right and
    must report the size that actually fits the scanned word."""
    img = _paper(200, 400, sigma=2)
    mask, _ = text_mask("Counting", "serif", None, 32, 1.0, weight=0.02)
    mask = gaussian_blur(mask, 1.0)
    y, x = 40, 20
    h, w = mask.shape
    a = mask[..., None]
    img[y:y + h, x:x + w] = np.clip(img[y:y + h, x:x + w] * (1 - a) + np.array(INK) * 255 * a, 0, 255).astype(np.uint8)
    ys, xs = np.nonzero(mask > 0.1)
    box = (x + xs.min(), y + ys.min(), x + xs.max() + 1, y + ys.max() + 1)
    sigma, weight, size, _ = estimate_ink(img, box, "Counting", "serif", None, 32 * size_error)
    assert abs(sigma - 1.0) <= 0.5, sigma
    assert weight <= 0.04, weight
    assert abs(size - 32) <= 1.6, size


def _solidity(cov):
    ink = cov[cov > 0.05]
    return float((ink > 0.8).mean()) if ink.size else 0.0


def test_estimate_ink_matches_solid_contrast_boosted_scans():
    """Scanner apps boost contrast: letters become thick, solid ink. The fix must match how
    solid the ink is, not only its shape, or the new word looks grey next to its neighbours."""
    img = _paper(200, 420, sigma=2)
    mask, _ = text_mask("Counting", "serif", None, 42, 1.0, weight=0.06)
    mask = np.clip(gaussian_blur(mask, 1.0) * 1.5, 0, 1)  # contrast boost
    y, x = 40, 20
    h, w = mask.shape
    a = mask[..., None]
    img[y:y + h, x:x + w] = np.clip(img[y:y + h, x:x + w] * (1 - a) + np.array(INK) * 255 * a, 0, 255).astype(np.uint8)
    ys, xs = np.nonzero(mask > 0.1)
    box = (x + xs.min(), y + ys.min(), x + xs.max() + 1, y + ys.max() + 1)
    look = estimate_ink(img, box, "Counting", "serif", None, 42)
    ours = ink_mask("Counting", "serif", None, look)
    assert abs(_solidity(ours) - _solidity(mask)) <= 0.35 * _solidity(mask), (_solidity(ours), _solidity(mask))


def test_estimate_ink_is_fast():
    import time

    img = _paper(200, 420, sigma=2)
    box = _draw_text(img, "Counting", 42, (40, 20), sigma=1.0)
    start = time.perf_counter()
    estimate_ink(img, box, "Counting", "serif", None, 42)
    assert time.perf_counter() - start < 0.35
