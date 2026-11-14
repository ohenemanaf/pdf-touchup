"""Reading words off scanned pages with Tesseract (through PyMuPDF)."""
from __future__ import annotations

import os

import pymupdf

from .model import Word
from .resources import tesseract_paths
from .text_source import words_from_tuples

OCR_DPI = 300


class OcrUnavailable(Exception):
    """No Tesseract language data was found."""


def ocr_words(page: pymupdf.Page, dpi: int = OCR_DPI) -> list[Word]:
    paths = tesseract_paths()
    if paths is None:
        raise OcrUnavailable("English OCR data not found")
    exe_dir, tessdata = paths
    if str(exe_dir) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{exe_dir}{os.pathsep}{os.environ.get('PATH', '')}"
    tp = page.get_textpage_ocr(dpi=dpi, full=True, language="eng", tessdata=str(tessdata))
    return words_from_tuples(page, page.get_text("words", textpage=tp))


def run_ocr_job(path: str, password: str | None, page_index: int, ocr=None) -> list[Word]:
    """Entry point for the background OCR process. It opens its own copy of the file,
    because PyMuPDF objects must never be shared between threads or processes."""
    from .document import open_document

    doc = open_document(path, password)
    return (ocr or ocr_words)(doc[page_index])
