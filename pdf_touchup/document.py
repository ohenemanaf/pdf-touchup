"""Opening PDFs and deciding what kind of page we are looking at."""
from __future__ import annotations

from pathlib import Path

import pymupdf

FULL_PAGE_IMAGE = 0.8  # an image covering this share of the page makes it a scan
_VISIBLE_TEXT = ("fill-text", "stroke-text")
_ANY_TEXT = _VISIBLE_TEXT + ("ignore-text",)


class NeedsPassword(Exception):
    """The file is encrypted and no password was given."""


class WrongPassword(Exception):
    """The given password did not open the file."""


def open_document(path: Path, password: str | None = None) -> pymupdf.Document:
    doc = pymupdf.open(path)
    if doc.needs_pass:
        if password is None:
            raise NeedsPassword(str(path))
        if not doc.authenticate(password):
            raise WrongPassword(str(path))
    return doc


def page_kind(page: pymupdf.Page) -> str:
    """"native", "scanned" or "searchable_scan" (scan with an invisible/hidden text layer)."""
    page_area = abs(page.rect)
    log = page.get_bboxlog()
    image_at = -1
    for i, (kind, bbox) in enumerate(log):
        if kind == "fill-image" and abs(pymupdf.Rect(bbox) & page.mediabox) >= FULL_PAGE_IMAGE * page_area:
            image_at = i
    has_text = any(kind in _ANY_TEXT for kind, _ in log)
    # Text drawn after the scan image (and not invisible) is what a reader actually sees.
    visible_after_image = any(kind in _VISIBLE_TEXT for kind, _ in log[image_at + 1:])
    if image_at < 0:
        return "native"
    if not has_text:
        return "scanned"
    return "native" if visible_after_image else "searchable_scan"
