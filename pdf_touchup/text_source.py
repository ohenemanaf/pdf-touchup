"""Where a page's words come from: its text layer, or OCR for scans."""
from __future__ import annotations

import pymupdf

from .document import page_kind
from .model import PageText, Word


def to_display(page: pymupdf.Page, rect) -> tuple[float, float, float, float]:
    """Unrotated page coords (what PyMuPDF reports) -> display coords (what the user sees)."""
    r = (pymupdf.Rect(rect) * page.rotation_matrix).normalize()
    return (r.x0, r.y0, r.x1, r.y1)


def words_from_tuples(page: pymupdf.Page, raw) -> list[Word]:
    return [Word(w[4], to_display(page, w[:4]), (w[5], w[6])) for w in raw]


def native_words(page: pymupdf.Page) -> list[Word]:
    return words_from_tuples(page, page.get_text("words"))


class PageTextCache:
    """Words per page, computed the first time a page is asked for (OCR only for scans)."""

    def __init__(self, doc: pymupdf.Document, ocr=None):
        if ocr is None:
            from .ocr import ocr_words as ocr
        self._doc = doc
        self._ocr = ocr
        self._pages: dict[int, PageText] = {}

    def get(self, page_index: int) -> PageText:
        if page_index not in self._pages:
            page = self._doc[page_index]
            kind = page_kind(page)
            words = self._ocr(page) if kind == "scanned" else native_words(page)
            self._pages[page_index] = PageText(page_index, kind, words)
        return self._pages[page_index]

    def has(self, page_index: int) -> bool:
        return page_index in self._pages

    def put(self, page_text: PageText) -> None:
        """Store words computed elsewhere (e.g. by the background OCR process)."""
        self._pages[page_text.page_index] = page_text
