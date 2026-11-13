"""Generated fixture PDFs: native, scanned, searchable scan, rotated, encrypted, multipage."""
from pathlib import Path

import numpy as np
import pymupdf
import pytest

FONTS = Path(__file__).resolve().parent.parent / "pdf_touchup" / "fonts"
CREAM = (245, 240, 225)
INK = (40, 40, 60)
LINES = [((72, 100), "Name: Kwame Mensah"), ((72, 120), "Date: 12 March 2024")]


def make_native(path: Path, family: str = "Serif") -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    for pos, text in LINES:
        page.insert_text(pos, text, fontsize=11, fontname="F0",
                         fontfile=str(FONTS / f"Liberation{family}-Regular.ttf"))
    doc.subset_fonts()
    doc.save(path)
    return path


def scan_image(native: Path, dpi: int = 200, seed: int = 0) -> pymupdf.Pixmap:
    pix = pymupdf.open(native)[0].get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    v = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).astype(float) / 255
    v = v[..., None]
    img = np.array(CREAM) * v + np.array(INK) * (1 - v)
    img += np.random.default_rng(seed).normal(0, 4, img.shape)
    img = np.clip(img, 0, 255).astype(np.uint8)
    return pymupdf.Pixmap(pymupdf.csRGB, pix.width, pix.height, img.tobytes(), False)


def make_scanned(path: Path, native: Path, pages: int = 1, invisible_text: bool = False,
                 rotation: int = 0) -> Path:
    png = scan_image(native).tobytes("png")
    doc = pymupdf.open()
    for _ in range(pages):
        if rotation:
            # Sideways scan: landscape mediabox, image stored sideways, /Rotate makes it upright.
            page = doc.new_page(width=842, height=595)
            page.set_rotation(rotation)
            page.insert_image(page.rect * page.derotation_matrix, stream=png, rotate=rotation)
            continue
        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=png)
        if invisible_text:
            for pos, text in LINES:
                page.insert_text(pos, text, fontsize=11, fontname="F0", render_mode=3,
                                 fontfile=str(FONTS / "LiberationSerif-Regular.ttf"))
    doc.save(path)
    return path


@pytest.fixture
def native_pdf(tmp_path):
    return make_native(tmp_path / "native.pdf")


@pytest.fixture
def native_sans_pdf(tmp_path):
    return make_native(tmp_path / "native_sans.pdf", "Sans")


@pytest.fixture
def scanned_pdf(tmp_path, native_pdf):
    return make_scanned(tmp_path / "scanned.pdf", native_pdf)


@pytest.fixture
def scanned_sans_pdf(tmp_path, native_sans_pdf):
    return make_scanned(tmp_path / "scanned_sans.pdf", native_sans_pdf)


@pytest.fixture
def searchable_scan_pdf(tmp_path, native_pdf):
    return make_scanned(tmp_path / "searchable.pdf", native_pdf, invisible_text=True)


@pytest.fixture
def rotated_scan_pdf(tmp_path, native_pdf):
    return make_scanned(tmp_path / "rotated.pdf", native_pdf, rotation=90)


@pytest.fixture
def multipage_scan_pdf(tmp_path, native_pdf):
    return make_scanned(tmp_path / "multi.pdf", native_pdf, pages=5)


@pytest.fixture
def encrypted_pdf(tmp_path, native_pdf):
    out = tmp_path / "encrypted.pdf"
    pymupdf.open(native_pdf).save(out, encryption=pymupdf.PDF_ENCRYPT_AES_256,
                                  user_pw="secret", owner_pw="owner-secret")
    return out
