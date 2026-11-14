"""Turning clicked words into one editable run of text."""
from __future__ import annotations

from .model import Edit, Rect, Word


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


def display_words(words: list[Word], edits: list[Edit]) -> list[Word]:
    """The clickable words for a page after fixes: words under a fix are hidden and each fix
    becomes one word (its new text, its box) with line_id ("edit", i) for the i-th fix."""
    def inside(word: Word, rect: Rect) -> bool:
        cx = (word.rect[0] + word.rect[2]) / 2
        cy = (word.rect[1] + word.rect[3]) / 2
        return rect[0] <= cx <= rect[2] and rect[1] <= cy <= rect[3]

    shown = [w for w in words if not any(inside(w, e.rect) for e in edits)]
    shown += [Word(e.new_text, e.rect, ("edit", i)) for i, e in enumerate(edits)]
    return shown
