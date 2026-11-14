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
    assert np.abs(crop - CREAM).max() <= 0.06


@pytest.mark.ocr
def test_scanned_edit_replaces_word(scanned_pdf, tmp_path):
    edit = make_edit(scanned_pdf)
    out = tmp_path / "out.pdf"
    save_as(scanned_pdf, [edit], out)
    page = pymupdf.open(out)[0]
    words = [w.text for w in ocr_words(page)]
    assert "Asante" in words and "Mensah" not in words
    # The fix is drawn as real text, and the scan image keeps no copy of the old word.
    assert "Asante" in page.get_text()


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
