"""Fixing scanned pages inside the scan image's pixels, so a fix looks printed, not stuck on.

Coordinates: "display" space is what the user sees (PDF points, page rotation applied).
`ScanImage.to_px` maps display points to pixel coordinates of the embedded scan image.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
import pymupdf

from .model import Rect

FULL_PAGE_IMAGE = 0.8


@dataclass
class ScanImage:
    xref: int
    width: int
    height: int
    to_px: pymupdf.Matrix  # display point -> image pixel
    shared: bool  # the same image object is drawn on other pages too
    ext: str  # original encoding, e.g. "jpeg", "png"
    bbox: pymupdf.Rect  # where the image sits on the unrotated page

    @property
    def px_per_pt(self) -> float:
        """Average image pixels per display point."""
        sx, sy = self.px_per_pt_xy
        return (sx + sy) / 2

    @property
    def px_per_pt_xy(self) -> tuple[float, float]:
        """Image pixels per display point along the display's x and y axes (scans are rarely
        exactly square, e.g. 1653 px over 595 pt but 2339 px over 842 pt)."""
        m = self.to_px
        return float(np.hypot(m.a, m.b)), float(np.hypot(m.c, m.d))


def _xy(s) -> tuple[float, float]:
    return (float(s), float(s)) if np.isscalar(s) else (float(s[0]), float(s[1]))


def _axis_aligned(m: pymupdf.Matrix) -> bool:
    eps = 1e-6
    return (abs(m.b) < eps and abs(m.c) < eps) or (abs(m.a) < eps and abs(m.d) < eps)


def find_scan_image(page: pymupdf.Page) -> ScanImage | None:
    """The image covering most of the page, if it is placed without skew."""
    area = abs(page.mediabox)
    best = None
    for info in page.get_image_info(xrefs=True):
        cover = abs(pymupdf.Rect(info["bbox"]) & page.mediabox)
        if info.get("xref", 0) > 0 and cover >= FULL_PAGE_IMAGE * area:
            if best is None or cover > abs(pymupdf.Rect(best["bbox"]) & page.mediabox):
                best = info
    if best is None:
        return None
    transform = pymupdf.Matrix(best["transform"])
    if not _axis_aligned(transform):
        return None
    xref = best["xref"]
    width, height = best["width"], best["height"]
    to_px = page.derotation_matrix * ~transform * pymupdf.Matrix(width, height)
    doc = page.parent
    shared = any(xref in (img[0] for img in doc[i].get_images())
                 for i in range(doc.page_count) if i != page.number)
    ext = doc.extract_image(xref).get("ext", "png")
    return ScanImage(xref, width, height, to_px, shared, ext, pymupdf.Rect(best["bbox"]))


def decode(page: pymupdf.Page, scan: ScanImage) -> np.ndarray:
    """The scan image as an H x W x 3 uint8 RGB array."""
    pix = pymupdf.Pixmap(page.parent, scan.xref)
    if pix.alpha:
        pix = pymupdf.Pixmap(pix, 0)
    if pix.colorspace is None or pix.colorspace.n != 3:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).copy()


def px_box(scan: ScanImage, rect: Rect) -> tuple[int, int, int, int]:
    r = (pymupdf.Rect(rect) * scan.to_px).normalize()
    eps = 1e-3  # ignore float noise, e.g. 506.00003 must not round up to 507
    x0 = max(0, int(np.floor(r.x0 + eps)))
    y0 = max(0, int(np.floor(r.y0 + eps)))
    x1 = min(scan.width, int(np.ceil(r.x1 - eps)))
    y1 = min(scan.height, int(np.ceil(r.y1 - eps)))
    return x0, y0, x1, y1


def place_patch(scan: ScanImage, patch: np.ndarray, origin: tuple[float, float], s):
    """Map an upright display-space patch (s pixels per point, or (sx, sy), top-left at
    `origin`) into the image's orientation. Returns (pixel box, warped patch sized to it)."""
    sx, sy = _xy(s)
    h, w = patch.shape[:2]
    x0, y0 = origin
    corners = pymupdf.Rect(x0, y0, x0 + w / sx, y0 + h / sy)
    box = px_box(scan, corners)
    bx0, by0, bx1, by1 = box
    if bx1 <= bx0 or by1 <= by0:
        return box, np.zeros((max(0, by1 - by0), max(0, bx1 - bx0)), dtype=patch.dtype)
    inv = ~scan.to_px  # image pixel -> display point
    ys, xs = np.mgrid[by0:by1, bx0:bx1].astype(float) + 0.5
    dx = xs * inv.a + ys * inv.c + inv.e
    dy = xs * inv.b + ys * inv.d + inv.f
    u = np.floor((dx - x0) * sx).astype(int)
    v = np.floor((dy - y0) * sy).astype(int)
    valid = (u >= 0) & (u < w) & (v >= 0) & (v < h)
    out = np.zeros((by1 - by0, bx1 - bx0) + patch.shape[2:], dtype=patch.dtype)
    out[valid] = patch[v[valid], u[valid]]
    return box, out


# ---- pixel operations ------------------------------------------------------------------

BLUR_CANDIDATES = (0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0)
PAPER_TOLERANCE = 0.12  # pixels this much darker than the paper are treated as ink


def _lum(a: np.ndarray) -> np.ndarray:
    a = np.asarray(a, dtype=float)
    return (a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114) / 255


def _blur_1d(a: np.ndarray, kernel: np.ndarray, axis: int) -> np.ndarray:
    r = len(kernel) // 2
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r, r)
    p = np.pad(a, pad, mode="reflect" if a.shape[axis] > r else "edge")
    out = np.zeros_like(a, dtype=float)
    n = a.shape[axis]
    for i, k in enumerate(kernel):
        out += k * np.take(p, range(i, i + n), axis=axis)
    return out


def gaussian_blur(a: np.ndarray, sigma: float) -> np.ndarray:
    a = np.asarray(a, dtype=float)
    if sigma <= 0:
        return a.copy()
    r = max(1, int(np.ceil(3 * sigma)))
    x = np.arange(-r, r + 1)
    kernel = np.exp(-(x * x) / (2 * sigma * sigma))
    kernel /= kernel.sum()
    return _blur_1d(_blur_1d(a, kernel, 0), kernel, 1)


def text_mask(text: str, family: str, font_buffer: bytes | None, size_px: float,
              h_scale: float, weight: float = 0.0) -> tuple[np.ndarray, tuple[float, float]]:
    """Anti-aliased ink coverage (0..1) of `text` at `size_px`, and the (x, y) pixel position of
    the text origin (left end of the baseline) inside the mask. `weight` thickens strokes (an
    outline of that width, relative to the font size) to imitate ink spread on printed paper."""
    from .fonts import font_path, load_font

    font = load_font(family, font_buffer)
    pad = size_px * 0.5
    width = font.text_length(text, size_px) * h_scale + 2 * pad
    height = size_px * 1.6 + 2 * pad
    origin = (pad, pad + size_px * 1.15)
    doc = pymupdf.open()
    page = doc.new_page(width=max(width, 4), height=height)
    if font_buffer:
        page.insert_font(fontname="F", fontbuffer=font_buffer)
        kwargs = {}
    else:
        kwargs = {"fontfile": str(font_path(family))}
    morph = (pymupdf.Point(origin), pymupdf.Matrix(h_scale, 1)) if abs(h_scale - 1) > 1e-3 else None
    if weight > 0:
        kwargs.update(render_mode=2, color=(0, 0, 0), fill=(0, 0, 0), border_width=weight)
    page.insert_text(origin, text, fontsize=size_px, fontname="F", morph=morph, **kwargs)
    pix = page.get_pixmap(colorspace=pymupdf.csGRAY, alpha=False)
    gray = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).astype(float)
    return 1.0 - gray / 255.0, origin


def _coverage(img: np.ndarray, box) -> np.ndarray:
    """How much ink is in each pixel of `box`, from 0 (paper) to 1 (full ink)."""
    x0, y0, x1, y1 = box
    lum = _lum(img[y0:y1, x0:x1])
    paper, ink = np.percentile(lum, 90), np.percentile(lum, 2)
    if paper - ink < 0.1:
        return np.zeros_like(lum)
    return np.clip((paper - lum) / (paper - ink), 0, 1)


def _crop_ink(a: np.ndarray, threshold: float = 0.3) -> np.ndarray:
    ys, xs = np.nonzero(a > threshold)
    if len(ys) == 0:
        return a
    return a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _resize(a: np.ndarray, h: int, w: int) -> np.ndarray:
    ys = np.clip(((np.arange(h) + 0.5) * a.shape[0] / h).astype(int), 0, a.shape[0] - 1)
    xs = np.clip(((np.arange(w) + 0.5) * a.shape[1] / w).astype(int), 0, a.shape[1] - 1)
    return a[ys][:, xs]


def _ncc(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a - a.mean(), b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d else 0.0


BLUR_SEARCH_PAD = 4  # px added around the word box so whole glyphs are always included


def _best_slide_ncc(target: np.ndarray, candidate: np.ndarray) -> float:
    """Highest NCC of `candidate` placed at any offset fully inside `target`."""
    th, tw = target.shape
    ch, cw = candidate.shape
    if ch > th or cw > tw:  # candidate larger: slide the target inside it instead
        target, candidate = candidate, target
        th, tw, ch, cw = ch, cw, th, tw
    best = -1.0
    for dy in range(th - ch + 1):
        for dx in range(tw - cw + 1):
            best = max(best, _ncc(target[dy:dy + ch, dx:dx + cw], candidate))
    return best


WEIGHT_CANDIDATES = (0.0, 0.02, 0.04, 0.06, 0.08, 0.10)


SLIDE_MARGIN = 8  # px of blank paper added around the search area so any candidate fits
FIT_PAD_Y = 0.15  # share of the box height looked at above and below when measuring width


def fit_size_px(img: np.ndarray, box, text: str, family: str, font_buffer: bytes | None,
                size_px: float, h_scale: float = 1.0) -> float:
    """Correct a font-size guess so `text` renders exactly as wide as the scanned ink in `box`.
    The box is grown a little vertically first: a slightly tight box can clip serifs at the
    baseline, which are often the widest part of a word."""
    x0, y0, x1, y1 = box
    grow = int(round((y1 - y0) * FIT_PAD_Y))
    box = (x0, max(0, y0 - grow), x1, min(img.shape[0], y1 + grow))
    ink = _crop_ink(_coverage(img, box), 0.3)
    if ink.size == 0 or ink.max() <= 0.3 or ink.shape[1] < 3:
        return size_px
    clean_width = _crop_ink(text_mask(text, family, font_buffer, size_px, h_scale)[0], 0.3).shape[1]
    return size_px * ink.shape[1] / clean_width if clean_width >= 3 else size_px


ALIGN_SEARCH = 3  # px searched around the ink-box alignment
GAIN_RANGE = (1.0, 4.0)


class InkLook(NamedTuple):
    """How scanned letters look compared with clean text."""
    sigma: float  # edge softness (Gaussian blur, image pixels)
    weight: float  # extra stroke thickness, relative to the font size
    size_px: float  # font size that matches the scanned word's width
    gain: float  # contrast boost: scanner apps make ink cores solid


def _solidity(cov: np.ndarray) -> float:
    ink = cov[cov > 0.05]
    return float((ink > 0.8).mean()) if ink.size else 0.0


def _match_gain(blurred: np.ndarray, solidity: float) -> float:
    """Contrast boost that gives `blurred` the target share of solid ink."""
    lo, hi = GAIN_RANGE
    if _solidity(np.clip(blurred * lo, 0, 1)) >= solidity:
        return lo
    for _ in range(10):
        mid = (lo + hi) / 2
        if _solidity(np.clip(blurred * mid, 0, 1)) < solidity:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _ink_origin(a: np.ndarray, threshold: float = 0.3) -> tuple[int, int]:
    ys, xs = np.nonzero(a > threshold)
    return (int(ys.min()), int(xs.min())) if len(ys) else (0, 0)


def _aligned_ncc(target: np.ndarray, candidate: np.ndarray) -> float:
    """NCC of `candidate` over `target`, aligning their ink boxes, then trying small shifts."""
    ty, tx = _ink_origin(target)
    cy, cx = _ink_origin(candidate)
    ch, cw = candidate.shape
    best = -1.0
    for dy in range(-ALIGN_SEARCH, ALIGN_SEARCH + 1):
        for dx in range(-ALIGN_SEARCH, ALIGN_SEARCH + 1):
            y, x = ty - cy + dy, tx - cx + dx
            if y < 0 or x < 0 or y + ch > target.shape[0] or x + cw > target.shape[1]:
                continue
            best = max(best, _ncc(target[y:y + ch, x:x + cw], candidate))
    return best


def ink_mask(text: str, family: str, font_buffer: bytes | None, look: InkLook,
             h_scale: float = 1.0) -> np.ndarray:
    """Coverage of `text` drawn the way the scanned ink looks."""
    clean, _ = text_mask(text, family, font_buffer, look.size_px, h_scale, look.weight)
    return np.clip(gaussian_blur(clean, look.sigma) * look.gain, 0, 1)


def estimate_ink(img: np.ndarray, box, old_text: str, family: str, font_buffer: bytes | None,
                 size_px: float, h_scale: float = 1.0) -> InkLook:
    """Measure how the scanned word in `box` looks: the font size that matches its width, then
    the softness, stroke weight and contrast boost that make clean text look like it. Shapes are
    compared with NCC; solidity (share of full-strength ink) is matched through the gain."""
    x0, y0, x1, y1 = box
    pad = BLUR_SEARCH_PAD
    padded = (max(0, x0 - pad), max(0, y0 - pad), min(img.shape[1], x1 + pad), min(img.shape[0], y1 + pad))
    target = _coverage(img, padded)
    if target.size == 0 or target.max() <= 0.3:
        return InkLook(1.0, 0.0, size_px, 1.0)
    size_px = fit_size_px(img, padded, old_text, family, font_buffer, size_px, h_scale)
    solidity = _solidity(target)
    target = np.pad(target, SLIDE_MARGIN)
    best, best_score = InkLook(0.0, 0.0, size_px, 1.0), -2.0
    for weight in WEIGHT_CANDIDATES:
        clean, _ = text_mask(old_text, family, font_buffer, size_px, h_scale, weight)
        for sigma in BLUR_CANDIDATES:
            blurred = gaussian_blur(clean, sigma)
            gain = _match_gain(blurred, solidity)
            candidate = _crop_ink(np.clip(blurred * gain, 0, 1), threshold=0.05)
            score = _aligned_ncc(target, candidate)
            if score > best_score:
                best, best_score = InkLook(sigma, weight, size_px, gain), score
    return best


def estimate_blur(img: np.ndarray, box, old_text: str, family: str, font_buffer: bytes | None,
                  size_px: float, h_scale: float = 1.0) -> float:
    """Blur sigma (image pixels) of the scanned ink; see estimate_ink."""
    return estimate_ink(img, box, old_text, family, font_buffer, size_px, h_scale).sigma


def _band(img: np.ndarray, y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
    y0, y1 = max(0, y0), min(img.shape[0], y1)
    return img[y0:y1, x0:x1].astype(float) if y1 > y0 else np.zeros((0, x1 - x0, 3))


def paper_fill(img: np.ndarray, box, band: int, rng: np.random.Generator) -> float:
    """Replace `box` with paper: per column, interpolate between the paper just above and just
    below (ink excluded), then add grain measured from that paper. Edits `img` in place and
    returns the grain strength (0..1 scale) so new ink can be given the same grain."""
    x0, y0, x1, y1 = box
    if x1 <= x0 or y1 <= y0:
        return 0.0
    above = _band(img, y0 - band, y0, x0, x1)
    below = _band(img, y1, y1 + band, x0, x1)
    def paper_mask(b: np.ndarray) -> np.ndarray:
        # Judge "paper" against each band's own brightness: shading can differ above and below.
        lum = _lum(b)
        return lum >= np.percentile(lum, 90) - PAPER_TOLERANCE

    masks = [paper_mask(b) if b.shape[0] else np.zeros(b.shape[:2], bool) for b in (above, below)]
    paper = np.concatenate([b[m] for b, m in zip((above, below), masks)], axis=0)
    if paper.size == 0:
        return 0.0
    overall = np.median(paper, axis=0)

    def column_paper(b: np.ndarray, m: np.ndarray) -> np.ndarray | None:
        if b.shape[0] == 0:
            return None
        masked = np.where(m[..., None], b, np.nan)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # columns with no paper -> overall
            med = np.nanmedian(masked, axis=0)  # (W, 3)
        return np.where(np.isnan(med), overall, med)

    top, bottom = column_paper(above, masks[0]), column_paper(below, masks[1])
    top = bottom if top is None else top
    bottom = top if bottom is None else bottom
    # Interpolate between the centres of the two bands so linear shading continues exactly.
    top_y = y0 - above.shape[0] / 2 if above.shape[0] else y0
    bottom_y = y1 + below.shape[0] / 2 if below.shape[0] else y1
    rows = np.arange(y0, y1) + 0.5
    t = ((rows - top_y) / max(bottom_y - top_y, 1e-6))[:, None, None]
    fill = top[None] * (1 - t) + bottom[None] * t

    # Grain from neighbouring paper pixels: horizontal differences ignore smooth shading.
    diffs = []
    for b, m in zip((above, below), masks):
        if b.shape[0] and b.shape[1] > 1:
            ok = m[:, 1:] & m[:, :-1]
            diffs.append((b[:, 1:] - b[:, :-1])[ok])
    diffs = np.concatenate(diffs, axis=0) if diffs else np.zeros((0, 3))
    grain = diffs.std(axis=0) / np.sqrt(2) if len(diffs) > 1 else np.zeros(3)
    fill = fill + rng.normal(0, 1, fill.shape) * grain
    img[y0:y1, x0:x1] = np.clip(np.round(fill), 0, 255).astype(np.uint8)
    return float(np.mean(grain)) / 255


def composite(img: np.ndarray, mask: np.ndarray, top_left: tuple[int, int], ink, grain_sigma: float,
              rng: np.random.Generator) -> None:
    """Draw ink with coverage `mask` at pixel (x, y) = `top_left`, with grain. In place."""
    x, y = top_left
    h, w = mask.shape
    ix0, iy0 = max(0, x), max(0, y)
    ix1, iy1 = min(img.shape[1], x + w), min(img.shape[0], y + h)
    if ix1 <= ix0 or iy1 <= iy0:
        return
    a = np.clip(mask[iy0 - y:iy1 - y, ix0 - x:ix1 - x], 0, 1)[..., None]
    base = img[iy0:iy1, ix0:ix1].astype(float)
    ink_px = np.array(ink, dtype=float) * 255
    noise = rng.normal(0, grain_sigma * 255, base.shape) * a
    out = base * (1 - a) + ink_px * a + noise
    img[iy0:iy1, ix0:ix1] = np.clip(np.round(out), 0, 255).astype(np.uint8)


# ---- applying fixes ----------------------------------------------------------------------

DESCENDERS = set("gjpqy")
OCR_DESCENT = 0.21  # typical descender depth as a share of font size
ERASE_PAD_Y = 0.15  # share of the line height erased above and below the word box
ERASE_PAD_X_PX = 2  # image pixels erased left and right of the word box
BAND_SHARE = 0.25  # paper band height used for the fill, as a share of the line height


def baseline_y(rect: Rect, kind: str, old_text: str, size: float, font: pymupdf.Font) -> float:
    """Display-space y of the baseline new text should sit on."""
    if kind == "scanned":  # OCR boxes hug the ink
        return rect[3] - (OCR_DESCENT * size if DESCENDERS & set(old_text) else 0.0)
    return rect[3] + font.descender * size  # text-layer boxes run to the font's descender


def snap_region(scan: ScanImage, region: pymupdf.Rect) -> pymupdf.Rect:
    """Grow `region` to whole image pixels, so cutting it out and writing it back maps every
    image pixel exactly once (no duplicated or dropped rows that would smear the text)."""
    x0, y0, x1, y1 = px_box(scan, region)
    return (pymupdf.Rect(x0, y0, x1, y1) * ~scan.to_px).normalize()


def _sample_upright(img: np.ndarray, scan: ScanImage, region: pymupdf.Rect, s) -> np.ndarray:
    """The part of the image under display `region`, turned upright, at s pixels per point."""
    sx, sy = _xy(s)
    w = max(1, int(round(region.width * sx)))
    h = max(1, int(round(region.height * sy)))
    vs, us = np.mgrid[0:h, 0:w].astype(float) + 0.5
    dx = region.x0 + us / sx
    dy = region.y0 + vs / sy
    m = scan.to_px
    px = np.clip(np.floor(dx * m.a + dy * m.c + m.e).astype(int), 0, scan.width - 1)
    py = np.clip(np.floor(dx * m.b + dy * m.d + m.f).astype(int), 0, scan.height - 1)
    return img[py, px]


def _write_back(img: np.ndarray, scan: ScanImage, upright: np.ndarray, region: pymupdf.Rect, s) -> None:
    box, warped = place_patch(scan, upright, (region.x0, region.y0), s)
    _, valid = place_patch(scan, np.ones(upright.shape[:2], dtype=bool), (region.x0, region.y0), s)
    x0, y0, x1, y1 = box
    target = img[y0:y1, x0:x1]
    target[valid] = warped[valid]


JPEG_QUALITY = 92


def _is_jpeg(ext: str) -> bool:
    return ext.lower() in ("jpeg", "jpg", "jpx")


def _encode(img: np.ndarray, ext: str) -> bytes:
    h, w = img.shape[:2]
    pix = pymupdf.Pixmap(pymupdf.csRGB, w, h, np.ascontiguousarray(img).tobytes(), False)
    return pix.tobytes("jpg", jpg_quality=JPEG_QUALITY) if _is_jpeg(ext) else pix.tobytes("png")


def _replace_in_place(doc: pymupdf.Document, scan: ScanImage, img: np.ndarray, preview: bool = False) -> None:
    """Overwrite the image object's data, keeping its xref (so the page draws it unchanged).
    Page.replace_image would leave a second full copy of the picture in the file.
    For a preview the pixels are stored uncompressed: encoding is the slow part and a preview
    is thrown away after rendering."""
    h, w = img.shape[:2]
    xref = scan.xref
    for key in ("DecodeParms", "Decode", "Filter", "Mask"):
        doc.xref_set_key(xref, key, "null")
    if preview:
        doc.update_stream(xref, np.ascontiguousarray(img).tobytes(), compress=False)
    elif _is_jpeg(scan.ext):
        doc.update_stream(xref, _encode(img, "jpeg"), compress=False)
        doc.xref_set_key(xref, "Filter", "/DCTDecode")
    else:
        doc.update_stream(xref, np.ascontiguousarray(img).tobytes(), compress=True)
    doc.xref_set_key(xref, "Width", str(w))
    doc.xref_set_key(xref, "Height", str(h))
    doc.xref_set_key(xref, "ColorSpace", "/DeviceRGB")
    doc.xref_set_key(xref, "BitsPerComponent", "8")


_LOOK_CACHE: dict = {}  # measured ink look per word, so live preview doesn't re-measure


def apply_scan_edits(page: pymupdf.Page, edits: list, preview: bool = False) -> bool:
    """Make each fix inside the page's scan image. Returns False (and changes nothing) when the
    page has no usable scan image, so the caller can fall back to drawing on top."""
    from .fonts import load_font

    scan = find_scan_image(page)
    if scan is None or (scan.shared and abs(page.rotation) % 360):
        return False
    img = decode(page, scan)
    sx, sy = s = scan.px_per_pt_xy
    rng = np.random.default_rng(0)
    for edit in edits:
        st = edit.style
        r = pymupdf.Rect(edit.rect)
        line_h = r.height
        erase = pymupdf.Rect(r.x0 - ERASE_PAD_X_PX / sx, r.y0 - ERASE_PAD_Y * line_h,
                             r.x1 + ERASE_PAD_X_PX / sx, r.y1 + ERASE_PAD_Y * line_h)
        band_pt = max(3 / sy, BAND_SHARE * line_h)
        region = snap_region(scan, pymupdf.Rect(erase.x0, erase.y0 - band_pt,
                                                erase.x1 + 2 * st.size, erase.y1 + band_pt))
        upright = _sample_upright(img, scan, region, s)

        def local(rect: pymupdf.Rect) -> tuple[int, int, int, int]:
            return (int(round((rect.x0 - region.x0) * sx)), int(round((rect.y0 - region.y0) * sy)),
                    int(round((rect.x1 - region.x0) * sx)), int(round((rect.y1 - region.y0) * sy)))

        size_px = st.size * sy
        aspect = sx / sy  # non-square pixels: stretch text masks to match
        # The size comes from the edit (detect_style already fitted it; the user may change it).
        key = (scan.width, scan.height, tuple(round(v, 2) for v in edit.rect), edit.old_text,
               st.family, round(st.size, 2), st.font_buffer is None)
        look = _LOOK_CACHE.get(key)
        if look is None:
            look = estimate_ink(upright, local(r), edit.old_text, st.family, st.font_buffer, size_px, aspect)
            if len(_LOOK_CACHE) > 128:
                _LOOK_CACHE.clear()
            _LOOK_CACHE[key] = look
        grain = paper_fill(upright, local(erase), band=max(3, int(round(band_pt * sy))), rng=rng)
        if edit.new_text:
            font = load_font(st.family, st.font_buffer)
            mask, (ox, oy) = text_mask(edit.new_text, st.family, st.font_buffer, size_px,
                                       st.h_scale * aspect, look.weight)
            mask = np.clip(gaussian_blur(mask, look.sigma) * look.gain, 0, 1)
            base = baseline_y(edit.rect, edit.kind, edit.old_text, st.size, font)
            top_left = (int(round((r.x0 - region.x0) * sx - ox)), int(round((base - region.y0) * sy - oy)))
            composite(upright, mask, top_left, st.color, grain, rng)
        _write_back(img, scan, upright, region, s)
    if scan.shared:
        # Never change an image other pages also show: draw the fixed copy over it on this page.
        page.insert_image(scan.bbox, stream=_encode(img, scan.ext), overlay=True)
    else:
        _replace_in_place(page.parent, scan, img, preview)
    return True
