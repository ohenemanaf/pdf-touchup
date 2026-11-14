"""Turning clicked words into one editable run of text."""
from __future__ import annotations

from .model import Rect, Word


class SelectionError(ValueError):
    """Selection is empty or crosses lines."""


def merge_selection(words: list[Word]) -> tuple[Rect, str]:
    if not words:
        raise SelectionError("Nothing selected")
    if len({w.line_id for w in words}) > 1:
        raise SelectionError("A fix can only cover one line")
    ordered = sorted(words, key=lambda w: w.rect[0])
    rect = (min(w.rect[0] for w in words), min(w.rect[1] for w in words),
            max(w.rect[2] for w in words), max(w.rect[3] for w in words))
    return rect, " ".join(w.text for w in ordered)
