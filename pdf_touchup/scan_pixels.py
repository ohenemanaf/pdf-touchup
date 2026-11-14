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
