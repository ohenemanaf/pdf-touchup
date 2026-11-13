"""Where a page's words come from: its text layer, or OCR for scans."""
from __future__ import annotations

import pymupdf

from .model import Word


def to_display(page: pymupdf.Page, rect) -> tuple[float, float, float, float]:
    """Unrotated page coords (what PyMuPDF reports) -> display coords (what the user sees)."""
    r = (pymupdf.Rect(rect) * page.rotation_matrix).normalize()
    return (r.x0, r.y0, r.x1, r.y1)


def words_from_tuples(page: pymupdf.Page, raw) -> list[Word]:
    return [Word(w[4], to_display(page, w[:4]), (w[5], w[6])) for w in raw]


def native_words(page: pymupdf.Page) -> list[Word]:
    return words_from_tuples(page, page.get_text("words"))
