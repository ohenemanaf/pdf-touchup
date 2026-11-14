"""Bundled replacement fonts (Liberation, metric-compatible with Times/Arial/Courier)."""
from __future__ import annotations

from pathlib import Path

import pymupdf

from .resources import resource_dir

FAMILIES = ("serif", "sans", "mono")
_FILES = {"serif": "LiberationSerif-Regular.ttf",
          "sans": "LiberationSans-Regular.ttf",
          "mono": "LiberationMono-Regular.ttf"}


def font_path(family: str) -> Path:
    return resource_dir() / "fonts" / _FILES[family]


def load_font(family: str | None = None, buffer: bytes | None = None) -> pymupdf.Font:
    if buffer is not None:
        return pymupdf.Font(fontbuffer=buffer)
    return pymupdf.Font(fontfile=str(font_path(family or "serif")))


def missing_glyphs(font: pymupdf.Font, text: str) -> list[str]:
    seen: list[str] = []
    for c in text:
        if not c.isspace() and c not in seen and not font.has_glyph(ord(c)):
            seen.append(c)
    return seen
