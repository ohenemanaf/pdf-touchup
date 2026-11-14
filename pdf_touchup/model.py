"""Plain data shared by the core and the UI."""
from __future__ import annotations

from dataclasses import dataclass, field

Rect = tuple[float, float, float, float]  # x0, y0, x1, y1 in PDF points (display space)
RGB = tuple[float, float, float]  # 0-1 floats


@dataclass(frozen=True)
class Word:
    text: str
    rect: Rect
    line_id: tuple[int, int]  # (block_no, line_no)


@dataclass(frozen=True)
class PageText:
    page_index: int
    kind: str  # "native" | "scanned" | "searchable_scan"
    words: list[Word] = field(default_factory=list)


@dataclass(frozen=True)
class Style:
    family: str  # "serif" | "sans" | "mono"
    size: float
    color: RGB
    background: RGB
    h_scale: float = 1.0
    font_buffer: bytes | None = None


@dataclass
class Edit:
    page_index: int
    rect: Rect
    old_text: str
    new_text: str
    style: Style
    kind: str
    # A re-fix of an earlier fix: while this edit is active, the earlier one is not applied.
    replaces: "Edit | None" = field(default=None, repr=False, compare=False)
