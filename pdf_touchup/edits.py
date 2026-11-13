"""Keeping a list of fixes, and burning them into a copy of the PDF."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Callable

import pymupdf

from .document import open_document
from .fonts import font_path, load_font
from .model import Edit

SCAN_KINDS = ("scanned", "searchable_scan")
PAD_X, PAD_Y = 0.5, 1.0  # points of extra erase around a box, to catch anti-aliased ink edges
DESCENDERS = set("gjpqy")
OCR_DESCENT = 0.21  # typical descender depth as a share of font size


class EditList:
    def __init__(self) -> None:
        self._done: list[Edit] = []
        self._undone: list[Edit] = []
        self.on_change: Callable[[], None] | None = None

    def _changed(self) -> None:
        if self.on_change:
            self.on_change()

    def add(self, edit: Edit) -> None:
        self._done.append(edit)
        self._undone.clear()
        self._changed()

    def undo(self) -> Edit | None:
        if not self._done:
            return None
        edit = self._done.pop()
        self._undone.append(edit)
        self._changed()
        return edit

    def redo(self) -> Edit | None:
        if not self._undone:
            return None
        edit = self._undone.pop()
        self._done.append(edit)
        self._changed()
        return edit

    def items(self) -> list[Edit]:
        return list(self._done)

    @property
    def can_undo(self) -> bool:
        return bool(self._done)

    @property
    def can_redo(self) -> bool:
        return bool(self._undone)


def _baseline(edit: Edit, font: pymupdf.Font) -> float:
    """Display-space y of the baseline the new text should sit on."""
    size = edit.style.size
    if edit.kind == "scanned":  # OCR boxes hug the ink
        return edit.rect[3] - (OCR_DESCENT * size if DESCENDERS & set(edit.old_text) else 0.0)
    return edit.rect[3] + font.descender * size  # text-layer boxes run to the font's descender


def _insert(page: pymupdf.Page, edit: Edit, n: int) -> None:
    if not edit.new_text:
        return
    style = edit.style
    font = load_font(style.family, style.font_buffer)
    origin = pymupdf.Point(edit.rect[0], _baseline(edit, font)) * page.derotation_matrix
    fontname = f"PTU{n}"
    kwargs = {"fontbuffer": style.font_buffer} if style.font_buffer else {"fontfile": str(font_path(style.family))}
    morph = None
    if abs(style.h_scale - 1.0) > 1e-3:
        # Scale along the *displayed* horizontal, expressed in unrotated page space.
        m = page.rotation_matrix * pymupdf.Matrix(style.h_scale, 1) * page.derotation_matrix
        morph = (origin, pymupdf.Matrix(m.a, m.b, m.c, m.d, 0, 0))  # morph wants the linear part only
    page.insert_text(origin, edit.new_text, fontsize=style.size, fontname=fontname,
                     color=style.color, rotate=page.rotation, morph=morph, **kwargs)


def apply_edits(doc: pymupdf.Document, edits: list[Edit]) -> None:
    by_page: dict[int, list[Edit]] = defaultdict(list)
    for edit in edits:
        by_page[edit.page_index].append(edit)
    for index, page_edits in by_page.items():
        page = doc[index]
        for edit in page_edits:
            r = pymupdf.Rect(edit.rect)
            r = pymupdf.Rect(r.x0 - PAD_X, r.y0 - PAD_Y, r.x1 + PAD_X, r.y1 + PAD_Y)
            page.add_redact_annot((r * page.derotation_matrix).normalize(), fill=edit.style.background)
        scan = any(e.kind in SCAN_KINDS for e in page_edits)
        page.apply_redactions(
            images=pymupdf.PDF_REDACT_IMAGE_PIXELS if scan else pymupdf.PDF_REDACT_IMAGE_NONE,
            graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
            text=pymupdf.PDF_REDACT_TEXT_REMOVE,
        )
        for n, edit in enumerate(page_edits):
            _insert(page, edit, n)


def default_output_path(source: Path) -> Path:
    return source.with_name(f"{source.stem}-edited.pdf")


def save_as(source: Path, edits: list[Edit], out: Path, password: str | None = None) -> None:
    if Path(out).resolve() == Path(source).resolve():
        raise ValueError("Save to a new file; the original is never overwritten")
    doc = open_document(source, password)
    encrypted = doc.is_encrypted or password is not None
    apply_edits(doc, edits)
    options = {"garbage": 3, "deflate": True}
    if encrypted and password is not None:
        options.update(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password)
    doc.save(out, **options)


def render_with_edits(doc: pymupdf.Document, page_index: int, edits: list[Edit], zoom: float) -> pymupdf.Pixmap:
    tmp = pymupdf.open()
    tmp.insert_pdf(doc, from_page=page_index, to_page=page_index)
    apply_edits(tmp, [replace(e, page_index=0) for e in edits if e.page_index == page_index])
    return tmp[0].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
