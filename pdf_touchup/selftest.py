"""Hidden `--self-test <pdf>` check used by the release build: proves the packaged app can
open a PDF and read a scanned page with its bundled OCR data. Exit code 0 = OK."""
from __future__ import annotations

from pathlib import Path

from .document import open_document
from .text_source import PageTextCache

EXPECTED_WORD = "Kwame"


def run(pdf: Path) -> int:
    try:
        words = PageTextCache(open_document(Path(pdf))).get(0).words
    except Exception:
        return 1
    return 0 if any(w.text == EXPECTED_WORD for w in words) else 1
