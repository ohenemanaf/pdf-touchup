"""Opening PDFs and deciding what kind of page we are looking at."""
from __future__ import annotations

from pathlib import Path

import pymupdf

FULL_PAGE_IMAGE = 0.8  # an image covering this share of the page makes it a scan
# Visible text over a scan must cover at least this share of the page to count as a real
# typed page; less than that is a watermark or stamp ("Scanned with CamScanner", page no.).
MIN_VISIBLE_TEXT_SHARE = 0.03
# A hidden text layer must hold at least this many words to be trusted instead of OCR.
# Scanner apps often hide just their own name ("CamScanner") under the image.
MIN_LAYER_WORDS = 10
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
    area = abs(page.mediabox)
    log = page.get_bboxlog()  # same coordinate space as the mediabox
    image_at = -1
    for i, (kind, bbox) in enumerate(log):
        if kind == "fill-image" and abs(pymupdf.Rect(bbox) & page.mediabox) >= FULL_PAGE_IMAGE * area:
            image_at = i
    if image_at < 0:
        return "native"
    # Text drawn after the scan image (and not invisible) is what a reader actually sees.
    visible = [pymupdf.Rect(b) for kind, b in log[image_at + 1:] if kind in _VISIBLE_TEXT]
    if sum(abs(r) for r in visible) >= MIN_VISIBLE_TEXT_SHARE * area:
        return "native"
    hidden_layer = not visible and len(page.get_text("words")) >= MIN_LAYER_WORDS
    return "searchable_scan" if hidden_layer else "scanned"
