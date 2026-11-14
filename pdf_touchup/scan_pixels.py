"""Fixing scanned pages inside the scan image's pixels, so a fix looks printed, not stuck on.

Coordinates: "display" space is what the user sees (PDF points, page rotation applied).
`ScanImage.to_px` maps display points to pixel coordinates of the embedded scan image.
"""
from __future__ import annotations

from dataclasses import dataclass

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
        m = self.to_px
        return float(np.hypot(m.a, m.b))


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
    x0 = max(0, int(np.floor(r.x0)))
    y0 = max(0, int(np.floor(r.y0)))
    x1 = min(scan.width, int(np.ceil(r.x1)))
    y1 = min(scan.height, int(np.ceil(r.y1)))
    return x0, y0, x1, y1


def place_patch(scan: ScanImage, patch: np.ndarray, origin: tuple[float, float], s: float):
    """Map an upright display-space patch (s pixels per point, top-left at `origin`) into the
    image's orientation. Returns (pixel box, warped patch sized to that box)."""
    h, w = patch.shape[:2]
    x0, y0 = origin
    corners = pymupdf.Rect(x0, y0, x0 + w / s, y0 + h / s)
    box = px_box(scan, corners)
    bx0, by0, bx1, by1 = box
    if bx1 <= bx0 or by1 <= by0:
        return box, np.zeros((max(0, by1 - by0), max(0, bx1 - bx0)), dtype=patch.dtype)
    inv = ~scan.to_px  # image pixel -> display point
    ys, xs = np.mgrid[by0:by1, bx0:bx1].astype(float) + 0.5
    dx = xs * inv.a + ys * inv.c + inv.e
    dy = xs * inv.b + ys * inv.d + inv.f
    u = np.floor((dx - x0) * s).astype(int)
    v = np.floor((dy - y0) * s).astype(int)
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
              h_scale: float) -> tuple[np.ndarray, tuple[float, float]]:
    """Anti-aliased ink coverage (0..1) of `text` at `size_px`, and the (x, y) pixel position of
    the text origin (left end of the baseline) inside the mask."""
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


def estimate_blur(img: np.ndarray, box, old_text: str, family: str, font_buffer: bytes | None,
                  size_px: float) -> float:
    """How soft the scanned ink is: the Gaussian sigma (in image pixels) that makes a clean
    rendering of the old text look most like the scan."""
    target = _crop_ink(_coverage(img, box))
    if target.size == 0 or target.max() <= 0.3:
        return 1.0
    h, w = target.shape
    clean, _ = text_mask(old_text, family, font_buffer, size_px, 1.0)
    best, best_score = 0.0, -2.0
    for sigma in BLUR_CANDIDATES:
        candidate = _crop_ink(gaussian_blur(clean, sigma))
        score = _ncc(target, _resize(candidate, h, w))
        if score > best_score:
            best, best_score = sigma, score
    return best


def _band(img: np.ndarray, y0: int, y1: int, x0: int, x1: int) -> np.ndarray:
    y0, y1 = max(0, y0), min(img.shape[0], y1)
    return img[y0:y1, x0:x1].astype(float) if y1 > y0 else np.zeros((0, x1 - x0, 3))


def paper_fill(img: np.ndarray, box, band: int, rng: np.random.Generator) -> None:
    """Replace `box` with paper: per column, interpolate between the paper just above and just
    below (ink excluded), then add grain measured from that paper. Edits `img` in place."""
    x0, y0, x1, y1 = box
    if x1 <= x0 or y1 <= y0:
        return
    above = _band(img, y0 - band, y0, x0, x1)
    below = _band(img, y1, y1 + band, x0, x1)
    def paper_mask(b: np.ndarray) -> np.ndarray:
        # Judge "paper" against each band's own brightness: shading can differ above and below.
        lum = _lum(b)
        return lum >= np.percentile(lum, 90) - PAPER_TOLERANCE

    masks = [paper_mask(b) if b.shape[0] else np.zeros(b.shape[:2], bool) for b in (above, below)]
    paper = np.concatenate([b[m] for b, m in zip((above, below), masks)], axis=0)
    if paper.size == 0:
        return
    overall = np.median(paper, axis=0)

    def column_paper(b: np.ndarray, m: np.ndarray) -> np.ndarray | None:
        if b.shape[0] == 0:
            return None
        masked = np.where(m[..., None], b, np.nan)
        with np.errstate(all="ignore"):
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
