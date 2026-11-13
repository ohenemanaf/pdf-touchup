import numpy as np
import pymupdf


def render(path, dpi=200, page_no=0):
    pix = pymupdf.open(path)[page_no].get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)


def px_box(rect, dpi=200):
    s = dpi / 72
    return tuple(int(round(v * s)) for v in rect)


def word_rect(path, text):
    words = pymupdf.open(path)[0].get_text("words")
    return next(w[:4] for w in words if w[4] == text)
