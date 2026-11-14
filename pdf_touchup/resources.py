"""Locating bundled files (fonts, stylesheet, OCR language data) in dev and in the installed app."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_DEFAULT_WINDOWS = Path(r"C:\Program Files\Tesseract-OCR")


def resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "pdf_touchup"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def _tess_dir(base: Path) -> tuple[Path, Path] | None:
    tessdata = base / "tessdata"
    if (tessdata / "eng.traineddata").is_file():
        return base, tessdata
    return None


def tesseract_paths() -> tuple[Path, Path] | None:
    """(tesseract dir, tessdata dir), or None when no English OCR data can be found.
    The data shipped inside the package comes first; a system Tesseract is only a fallback."""
    candidates: list[Path] = [resource_dir()]
    if os.environ.get("PDF_TOUCHUP_TESSERACT"):
        candidates.append(Path(os.environ["PDF_TOUCHUP_TESSERACT"]))
    exe = shutil.which("tesseract")
    if exe:
        candidates.append(Path(exe).resolve().parent)
    candidates.append(_DEFAULT_WINDOWS)
    for base in candidates:
        found = _tess_dir(base)
        if found:
            return found
    return None
