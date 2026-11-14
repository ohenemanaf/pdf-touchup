from pathlib import Path

import numpy as np
import pymupdf
import pytest

from helpers import px_box, render
from pdf_touchup.document import open_document
from pdf_touchup.edits import EditList, apply_edits, default_output_path, render_with_edits, save_as
from pdf_touchup.model import Edit
from pdf_touchup.ocr import ocr_words
from pdf_touchup.selection import merge_selection
from pdf_touchup.style import detect_style
from pdf_touchup.text_source import PageTextCache

CREAM = np.array((245, 240, 225)) / 255


def make_edit(path, old_words=("Mensah",), new_text="Asante", password=None):
    doc = open_document(path, password)
    pt = PageTextCache(doc).get(0)
    rect, old = merge_selection([w for w in pt.words if w.text in old_words])
    style = detect_style(doc[0], rect, old, new_text, pt.kind)
    return Edit(0, rect, old, new_text, style, pt.kind)


def overlaps(a, b):
    return pymupdf.Rect(a).intersects(pymupdf.Rect(b))


def test_editlist_undo_redo():
    a, b, c = (Edit(0, (0, 0, 1, 1), "x", n, None, "native") for n in "abc")
    edits = EditList()
    changes = []
    edits.on_change = lambda: changes.append(len(edits.items()))
    edits.add(a)
    edits.add(b)
    assert edits.undo() is b
    assert edits.items() == [a]
    assert edits.redo() is b
    assert edits.undo() is b
    edits.add(c)
    assert edits.can_redo is False
    assert edits.items() == [a, c]
    assert edits.can_undo
    assert changes == [1, 2, 1, 2, 1, 2]


def test_native_edit_replaces_text(native_pdf, tmp_path):
    edit = make_edit(native_pdf)
    out = tmp_path / "out.pdf"
    save_as(native_pdf, [edit], out)
    page = pymupdf.open(out)[0]
    text = page.get_text()
    assert "Asante" in text  # drawn as its own text block, so not joined to "Kwame" in extraction
    assert "Mensah" not in text
    new = next(w for w in page.get_text("words") if w[4] == "Asante")
    assert abs((new[1] + new[3]) / 2 - (edit.rect[1] + edit.rect[3]) / 2) <= 1.5
    assert abs(new[0] - edit.rect[0]) <= 1.0


@pytest.mark.ocr
def test_scanned_edit_erases_old_pixels(scanned_pdf, tmp_path):
    edit = make_edit(scanned_pdf, new_text="")
    out = tmp_path / "out.pdf"
    save_as(scanned_pdf, [edit], out)
    x0, y0, x1, y1 = px_box(edit.rect)
    crop = render(out)[y0:y1, x0:x1].reshape(-1, 3) / 255
    # Paper with grain (by design), no ink left.
    assert np.abs(crop.mean(axis=0) - CREAM).max() <= 0.03
    lum = crop @ np.array([0.299, 0.587, 0.114])
    assert lum.min() >= 0.6


@pytest.mark.ocr
def test_scanned_edit_replaces_word(scanned_pdf, tmp_path):
    edit = make_edit(scanned_pdf)
    out = tmp_path / "out.pdf"
    save_as(scanned_pdf, [edit], out)
    page = pymupdf.open(out)[0]
    words = [w.text for w in ocr_words(page)]
    assert "Asante" in words and "Mensah" not in words
    # The fix is part of the scan picture, like every other word on the page.
    assert "Asante" not in page.get_text()


@pytest.mark.ocr
def test_searchable_scan_edit_removes_both(searchable_scan_pdf, tmp_path):
    edit = make_edit(searchable_scan_pdf, new_text="")
    out = tmp_path / "out.pdf"
    save_as(searchable_scan_pdf, [edit], out)
    assert "Mensah" not in pymupdf.open(out)[0].get_text()
    words = [w.text for w in ocr_words(pymupdf.open(out)[0])]
    assert "Mensah" not in words and "Kwame" in words


@pytest.mark.ocr
def test_apply_on_rotated_page(rotated_scan_pdf, tmp_path):
    edit = make_edit(rotated_scan_pdf)
    out = tmp_path / "out.pdf"
    save_as(rotated_scan_pdf, [edit], out)
    words = {w.text: w for w in ocr_words(pymupdf.open(out)[0])}
    assert "Mensah" not in words
    assert "Asante" in words
    assert overlaps(words["Asante"].rect, edit.rect)


def test_save_as_refuses_overwrite(native_pdf):
    with pytest.raises(ValueError):
        save_as(native_pdf, [], native_pdf)


def test_default_output_path():
    assert default_output_path(Path("C:/x/form.pdf")) == Path("C:/x/form-edited.pdf")


def test_render_with_edits_does_not_mutate(native_pdf):
    doc = open_document(native_pdf)
    before = doc[0].get_text()
    pix = render_with_edits(doc, 0, [make_edit(native_pdf)], zoom=1.0)
    assert pix.width > 0
    assert doc[0].get_text() == before


def test_render_with_edits_shows_change(native_pdf):
    doc = open_document(native_pdf)
    plain = render_with_edits(doc, 0, [], zoom=1.0)
    edited = render_with_edits(doc, 0, [make_edit(native_pdf)], zoom=1.0)
    assert plain.samples != edited.samples


def test_encrypted_save_keeps_password(encrypted_pdf, tmp_path):
    edit = make_edit(encrypted_pdf, password="secret")
    out = tmp_path / "out.pdf"
    save_as(encrypted_pdf, [edit], out, password="secret")
    doc = pymupdf.open(out)
    assert doc.needs_pass
    assert doc.authenticate("secret")
    assert "Asante" in doc[0].get_text()


def test_apply_edits_in_place(native_pdf):
    doc = open_document(native_pdf)
    apply_edits(doc, [make_edit(native_pdf)])
    assert "Asante" in doc[0].get_text()


# ---- final-review fixes -------------------------------------------------------------

def test_save_with_reused_original_font(native_fullfont_pdf, tmp_path):
    edit = make_edit(native_fullfont_pdf)
    assert edit.style.font_buffer is not None
    out = tmp_path / "out.pdf"
    save_as(native_fullfont_pdf, [edit], out)
    text = pymupdf.open(out)[0].get_text()
    assert "Asante" in text and "Mensah" not in text


def test_fix_keeps_tightly_spaced_neighbour_lines(tmp_path):
    from conftest import FONTS

    src = tmp_path / "tight.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    for i, line in enumerate(["Upper words here", "Name: Kwame Mensah", "Lower words here"]):
        page.insert_text((72, 100 + 11 * i), line, fontsize=11, fontname="F0",
                         fontfile=str(FONTS / "LiberationSerif-Regular.ttf"))
    doc.save(src)
    out = tmp_path / "out.pdf"
    save_as(src, [make_edit(src)], out)
    text = pymupdf.open(out)[0].get_text()
    assert "Upper words here" in text
    assert "Lower words here" in text
    assert "Mensah" not in text and "Asante" in text


def test_editlist_version_changes_on_every_change():
    a, b = (Edit(0, (0, 0, 1, 1), "x", n, None, "native") for n in "ab")
    edits = EditList()
    seen = {edits.version}
    edits.add(a)
    seen.add(edits.version)
    edits.undo()
    seen.add(edits.version)
    edits.add(b)
    seen.add(edits.version)
    assert len(seen) == 4  # same edit count as earlier, different version


# ---- scan fixes made in the image pixels -----------------------------------------------
from pdf_touchup.scan_pixels import decode, estimate_blur, find_scan_image  # noqa: E402
from pdf_touchup.scan_pixels import px_box as scan_px_box  # noqa: E402


def _rendered(path, dpi=200):
    return render(path, dpi=dpi).astype(float) / 255


@pytest.mark.ocr
def test_scan_fix_is_inside_the_image(scanned_pdf, tmp_path):
    out = tmp_path / "out.pdf"
    save_as(scanned_pdf, [make_edit(scanned_pdf)], out)
    page = pymupdf.open(out)[0]
    assert page.get_text().strip() == ""
    assert len(page.get_images()) == 1
    words = [w.text for w in ocr_words(page)]
    assert "Asante" in words and "Mensah" not in words


@pytest.mark.ocr
def test_scan_fix_has_no_flat_patch(scanned_pdf, tmp_path):
    edit = make_edit(scanned_pdf, new_text="")
    out = tmp_path / "out.pdf"
    save_as(scanned_pdf, [edit], out)
    img = _rendered(out)
    x0, y0, x1, y1 = px_box_200(edit.rect)
    erased = img[y0:y1, x0:x1, 0]
    nearby = img[y0 - 40:y0 - 15, x0:x1, 0]
    assert erased.std() >= 0.5 * nearby.std()


def px_box_200(rect, dpi=200):
    s = dpi / 72
    return tuple(int(round(v * s)) for v in rect)


@pytest.mark.ocr
def test_scan_fix_blur_matches_neighbours(scanned_pdf, tmp_path):
    edit = make_edit(scanned_pdf)
    out = tmp_path / "out.pdf"
    save_as(scanned_pdf, [edit], out)
    page = pymupdf.open(out)[0]
    scan = find_scan_image(page)
    img = decode(page, scan)
    words = {w.text: w for w in ocr_words(page)}
    size_px = edit.style.size * scan.px_per_pt
    new = estimate_blur(img, scan_px_box(scan, words["Asante"].rect), "Asante", "serif", None, size_px,
                        h_scale=edit.style.h_scale)
    old = estimate_blur(img, scan_px_box(scan, words["Kwame"].rect), "Kwame", "serif", None, size_px)
    assert abs(new - old) <= 0.75, (new, old)


@pytest.mark.ocr
def test_scan_fix_keeps_jpeg_and_size(native_pdf, tmp_path):
    from conftest import scan_image

    src = tmp_path / "jpeg-scan.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=scan_image(native_pdf).tobytes("jpg", jpg_quality=85))
    doc.save(src)
    out = tmp_path / "out.pdf"
    save_as(src, [make_edit(src)], out)
    assert out.stat().st_size < 2 * src.stat().st_size
    page = pymupdf.open(out)[0]
    assert page.parent.extract_image(page.get_images()[0][0])["ext"] in ("jpeg", "jpg")


@pytest.mark.ocr
def test_shared_image_other_pages_untouched(native_pdf, tmp_path):
    from conftest import scan_image

    src = tmp_path / "shared.pdf"
    doc = pymupdf.open()
    first = doc.new_page(width=595, height=842)
    xref = first.insert_image(first.rect, stream=scan_image(native_pdf).tobytes("png"))
    second = doc.new_page(width=595, height=842)
    second.insert_image(second.rect, xref=xref)
    doc.save(src)
    out = tmp_path / "out.pdf"
    save_as(src, [make_edit(src)], out)
    result = pymupdf.open(out)
    assert "Mensah" not in [w.text for w in ocr_words(result[0])]
    assert "Mensah" in [w.text for w in ocr_words(result[1])]


@pytest.mark.ocr
def test_scan_fix_keeps_tight_neighbour_lines(native_pdf, tmp_path):
    from conftest import FONTS, scan_image

    native = tmp_path / "tight-native.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    for i, line in enumerate(["Upper words here", "Name: Kwame Mensah", "Lower words here"]):
        page.insert_text((72, 100 + 12 * i), line, fontsize=11, fontname="F0",
                         fontfile=str(FONTS / "LiberationSerif-Regular.ttf"))
    doc.save(native)
    src = tmp_path / "tight-scan.pdf"
    scan = pymupdf.open()
    p = scan.new_page(width=595, height=842)
    p.insert_image(p.rect, stream=scan_image(native).tobytes("png"))
    scan.save(src)
    out = tmp_path / "out.pdf"
    save_as(src, [make_edit(src)], out)
    words = [w.text for w in ocr_words(pymupdf.open(out)[0])]
    assert words.count("words") == 2 and words.count("here") == 2
    assert "Asante" in words and "Mensah" not in words


@pytest.mark.ocr
def test_fast_preview_matches_saved_result(native_pdf, tmp_path):
    from conftest import scan_image

    src = tmp_path / "jpeg-scan.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=scan_image(native_pdf).tobytes("jpg", jpg_quality=85))
    doc.save(src)
    edit = make_edit(src)
    saved = tmp_path / "out.pdf"
    save_as(src, [edit], saved)
    preview = render_with_edits(open_document(src), 0, [edit], zoom=2.0)
    final = pymupdf.open(saved)[0].get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
    a = np.frombuffer(preview.samples, np.uint8).astype(int)
    b = np.frombuffer(final.samples, np.uint8).astype(int)
    assert np.abs(a - b).mean() < 2.0  # only JPEG rounding differs


def test_preview_skips_jpeg_encoding(native_pdf, tmp_path, monkeypatch):
    from conftest import scan_image
    import pdf_touchup.scan_pixels as sp

    src = tmp_path / "jpeg-scan.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=scan_image(native_pdf).tobytes("jpg", jpg_quality=85))
    doc.save(src)
    edit = make_edit(src)
    calls = []
    real = sp._encode
    monkeypatch.setattr(sp, "_encode", lambda *a, **k: calls.append(1) or real(*a, **k))
    render_with_edits(open_document(src), 0, [edit], zoom=1.0)
    assert calls == []
