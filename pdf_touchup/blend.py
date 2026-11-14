"""Estimating how a fix should look so it blends into the page.

All image functions take an H x W x 3 uint8 render of the page and a pixel box (x0, y0, x1, y1).
"""
from __future__ import annotations

import numpy as np
import pymupdf

from .fonts import FAMILIES, font_path
from .model import RGB

DESCENDERS = set("gjpqy")
TALL = set("bdfhklt")
INK_QUANTILE = 0.1  # darkest share of pixels treated as ink
SCALE_MIN, SCALE_MAX = 0.90, 1.10
LENGTH_RATIO_MIN, LENGTH_RATIO_MAX = 0.8, 1.25


def _clip(img: np.ndarray, box) -> tuple[int, int, int, int]:
    h, w = img.shape[:2]
    x0, y0, x1, y1 = box
    return max(0, x0), max(0, y0), min(w, x1), min(h, y1)


def _rgb(values: np.ndarray) -> RGB:
    return tuple(float(v) / 255 for v in np.median(values.reshape(-1, 3), axis=0))  # type: ignore[return-value]


def _lum(rgb) -> np.ndarray | float:
    rgb = np.asarray(rgb, dtype=float)
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def background_color(img: np.ndarray, box, ring: int = 4) -> RGB:
    x0, y0, x1, y1 = box
    ox0, oy0, ox1, oy1 = _clip(img, (x0 - ring, y0 - ring, x1 + ring, y1 + ring))
    mask = np.ones((oy1 - oy0, ox1 - ox0), dtype=bool)
    ix0, iy0, ix1, iy1 = _clip(img, box)
    mask[iy0 - oy0:iy1 - oy0, ix0 - ox0:ix1 - ox0] = False
    return _rgb(img[oy0:oy1, ox0:ox1][mask])


def ink_color(img: np.ndarray, box, background: RGB) -> RGB:
    x0, y0, x1, y1 = _clip(img, box)
    pixels = img[y0:y1, x0:x1].reshape(-1, 3).astype(float)
    lum = _lum(pixels) / 255
    candidates = pixels[(lum <= np.quantile(lum, INK_QUANTILE)) & (_lum(background) - lum > 0.15)]
    if len(candidates) == 0:
        return (0.0, 0.0, 0.0)
    return _rgb(candidates)


def font_size_pt(box_height_pt: float, text: str) -> float:
    if DESCENDERS & set(text):
        ratio = 0.93
    elif any(c.isupper() or c.isdigit() or c in TALL for c in text):
        ratio = 0.72
    else:
        ratio = 0.50
    return round(box_height_pt / ratio, 1)


def _ink_mask(gray: np.ndarray, threshold: float) -> np.ndarray:
    return gray < threshold


def _crop_to_ink(mask: np.ndarray) -> np.ndarray:
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return mask
    return mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def _resize(mask: np.ndarray, h: int, w: int) -> np.ndarray:
    ys = (np.arange(h) * mask.shape[0] / h).astype(int)
    xs = (np.arange(w) * mask.shape[1] / w).astype(int)
    return mask[ys][:, xs].astype(float)


def _render_text(text: str, family: str, size_px: float) -> np.ndarray:
    font = pymupdf.Font(fontfile=str(font_path(family)))
    width = font.text_length(text, size_px) + size_px
    doc = pymupdf.open()
    page = doc.new_page(width=width, height=size_px * 1.6)
    page.insert_text((size_px / 2, size_px * 1.15), text, fontsize=size_px,
                     fontname="F", fontfile=str(font_path(family)))
    pix = page.get_pixmap(colorspace=pymupdf.csGRAY, alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).astype(float) / 255


def _ncc(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a - a.mean(), b - b.mean()
    denom = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / denom) if denom else 0.0


def guess_family(img: np.ndarray, box, text: str, size_px: float, background: RGB) -> str:
    """Render the text in each bundled family and pick the one whose shape best matches the scan."""
    x0, y0, x1, y1 = _clip(img, box)
    gray = _lum(img[y0:y1, x0:x1].astype(float)) / 255
    threshold = (_lum(background) + gray.min()) / 2
    target = _crop_to_ink(_ink_mask(gray, threshold))
    h, w = max(target.shape[0], 8), max(target.shape[1], 8)
    target = _resize(target, h, w)
    scores = {}
    for family in FAMILIES:
        candidate = _crop_to_ink(_ink_mask(_render_text(text, family, size_px), 0.5))
        scores[family] = _ncc(target, _resize(candidate, h, w))
    return max(scores, key=scores.get)


def width_scale(old_text: str, new_text: str, font: pymupdf.Font, size: float, box_width_pt: float) -> float:
    if not old_text or not new_text:
        return 1.0
    ratio = len(new_text) / len(old_text)
    if not LENGTH_RATIO_MIN <= ratio <= LENGTH_RATIO_MAX:
        return 1.0
    natural = font.text_length(new_text, size)
    if natural <= 0:
        return 1.0
    return min(SCALE_MAX, max(SCALE_MIN, box_width_pt / natural))
