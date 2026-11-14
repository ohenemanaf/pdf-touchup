"""Working out how replacement text should look (font, size, colour, background, width)."""
from __future__ import annotations

import numpy as np
import pymupdf

from .blend import background_color, font_size_pt, guess_family, ink_color, width_scale
from .fonts import load_font, missing_glyphs
from .model import Rect, Style
from .scan_pixels import fit_size_px

NATIVE_DPI = 150
SCAN_DPI = 300
SIZE_FIT_LIMIT = 0.15
_FONT_TYPES = {"ttf", "otf", "cff", "pfa", "pfb", "ttc"}


def _render(page: pymupdf.Page, dpi: int) -> np.ndarray:
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)


def _px_box(rect: Rect, dpi: int) -> tuple[int, int, int, int]:
    s = dpi / 72
    return (int(rect[0] * s), int(rect[1] * s), int(np.ceil(rect[2] * s)), int(np.ceil(rect[3] * s)))


def _family_from_name(name: str) -> str:
    lowered = name.lower()
    if "courier" in lowered or "mono" in lowered:
        return "mono"
    if any(k in lowered for k in ("arial", "helvetica", "sans", "calibri", "verdana", "tahoma")):
        return "sans"
    return "serif"


def _span_at(page: pymupdf.Page, rect: Rect) -> dict | None:
    target = (pymupdf.Rect(rect) * page.derotation_matrix).normalize()
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                if span["text"].strip() and pymupdf.Rect(span["bbox"]).intersects(target):
                    return span
    return None


def _norm_font_name(name: str) -> str:
    name = "".join(c for c in name.split("+", 1)[-1].lower() if c.isalnum())
    for suffix in ("psmt", "mt", "regular", "roman"):
        name = name.removesuffix(suffix)
    return name


def _embedded_font(page: pymupdf.Page, span_font: str, new_text: str) -> bytes | None:
    for xref, ext, _type, basefont, *_ in page.get_fonts():
        if ext not in _FONT_TYPES:
            continue
        if _norm_font_name(basefont) != _norm_font_name(span_font):
            continue
        buffer = page.parent.extract_font(xref)[3]
        if buffer and not missing_glyphs(load_font(buffer=buffer), new_text):
            return buffer
        return None
    return None


def _scan_size(img, box, text: str, family: str, size: float) -> float:
    """Font size (pt) of one scanned word, fitted to its ink width; held within SIZE_FIT_LIMIT
    of its ink height, which misread text (missing spaces/letters) cannot inflate."""
    px = size * SCAN_DPI / 72
    by_width = fit_size_px(img, box, text, family, None, px) * 72 / SCAN_DPI
    by_height = fit_size_px(img, box, text, family, None, px, by="height") * 72 / SCAN_DPI
    lo, hi = by_height * (1 - SIZE_FIT_LIMIT), by_height * (1 + SIZE_FIT_LIMIT)
    return min(max(by_width, lo), hi)


LINE_NEIGHBOURS = 6  # neighbouring words on the line used to agree on a font size


def detect_style(page: pymupdf.Page, rect: Rect, old_text: str, new_text: str, kind: str,
                 line_words: list | None = None) -> Style:
    """`line_words`: OCR words on the same line. Words on a line share one size, so for scans the
    size is the median over the selection and its neighbours (outvoting misread words)."""
    width = rect[2] - rect[0]
    if kind == "native":
        span = _span_at(page, rect)
        img = _render(page, NATIVE_DPI)
        background = background_color(img, _px_box(rect, NATIVE_DPI))
        if span is None:
            size, color, family, buffer = font_size_pt(rect[3] - rect[1], old_text), (0.0, 0.0, 0.0), "serif", None
        else:
            size = round(span["size"], 1)
            color = pymupdf.sRGB_to_pdf(span["color"])
            family = _family_from_name(span["font"])
            buffer = _embedded_font(page, span["font"], new_text)
    else:
        img = _render(page, SCAN_DPI)
        box = _px_box(rect, SCAN_DPI)
        background = background_color(img, box)
        color = ink_color(img, box, background)
        span = _span_at(page, rect) if kind == "searchable_scan" else None
        # A hidden text layer knows the real size; OCR boxes are tight around the ink.
        size = round(span["size"], 1) if span else font_size_pt(rect[3] - rect[1], old_text)
        family = guess_family(img, box, old_text, size * SCAN_DPI / 72, background)
        if span is None:  # OCR boxes give only a rough size; fit it to the word's ink width
            sizes = [_scan_size(img, box, old_text, family, size)]
            cx = (rect[0] + rect[2]) / 2
            others = [w for w in (line_words or [])
                      if len(w.text) >= 2 and any(c.isalpha() for c in w.text) and w.rect != tuple(rect)
                      and not (w.rect[0] >= rect[0] and w.rect[2] <= rect[2])]
            others.sort(key=lambda w: abs((w.rect[0] + w.rect[2]) / 2 - cx))
            for w in others[:LINE_NEIGHBOURS]:
                guess = font_size_pt(w.rect[3] - w.rect[1], w.text)
                sizes.append(_scan_size(img, _px_box(w.rect, SCAN_DPI), w.text, family, guess))
            size = round(float(np.median(sizes)), 1)
        buffer = None
    font = load_font(family, buffer)
    return Style(family=family, size=size, color=tuple(color), background=background,
                 h_scale=width_scale(old_text, new_text, font, size, width), font_buffer=buffer)
