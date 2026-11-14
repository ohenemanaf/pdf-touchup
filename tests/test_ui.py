import os
import time

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QInputDialog

from pdf_touchup.model import Word
from pdf_touchup.ui.app import MainWindow


def slow_fake_ocr(page):
    """Runs in the OCR worker process: reports which process it ran in."""
    time.sleep(0.5)
    return [Word(f"pid{os.getpid()}", (72, 90, 120, 101), (0, 0))]


@pytest.fixture
def window(qtbot):
    w = MainWindow()
    w.resize(1000, 800)
    w.show()
    yield w
    # Closed here rather than by qtbot, so the "save first?" prompt can be skipped.
    w._saved_version = w.edits.version
    w.close()


def _click_word(qtbot, view, text, modifier=Qt.NoModifier):
    item = next(i for i in view.word_items if i.word.text == text)
    pos = view.mapFromScene(item.sceneBoundingRect().center())
    qtbot.mouseClick(view.viewport(), Qt.LeftButton, modifier, pos)


def test_open_native_shows_words(window, native_pdf):
    window.open_path(native_pdf)
    assert window.page_status() == "Normal page"
    assert len(window.view.word_items) >= 6


def test_ocr_runs_in_background(qtbot, native_pdf, scanned_pdf):
    w = MainWindow(ocr=slow_fake_ocr)
    qtbot.addWidget(w)
    w.show()
    try:
        start = time.perf_counter()
        w.open_path(scanned_pdf)
        assert time.perf_counter() - start < 0.5
        assert w.page_status() == "Reading page…"
        qtbot.waitUntil(lambda: w.page_status() == "Scanned page · text found", timeout=20000)
        texts = [i.word.text for i in w.view.word_items]
        assert texts and texts[0] != f"pid{os.getpid()}"
    finally:
        w.shutdown()


def test_selection_stays_on_one_line(qtbot, window, native_pdf):
    window.open_path(native_pdf)
    with qtbot.waitSignal(window.view.selection_changed) as first:
        _click_word(qtbot, window.view, "Kwame")
    assert [w.text for w in first.args[0]] == ["Kwame"]
    with qtbot.waitSignal(window.view.selection_changed) as second:
        _click_word(qtbot, window.view, "March", Qt.ShiftModifier)
    assert [w.text for w in second.args[0]] == ["Kwame"]
    with qtbot.waitSignal(window.view.selection_changed) as third:
        _click_word(qtbot, window.view, "Mensah", Qt.ShiftModifier)
    assert sorted(w.text for w in third.args[0]) == ["Kwame", "Mensah"]


def test_password_prompt(window, encrypted_pdf, monkeypatch):
    answers = iter([("nope", True), ("secret", True)])
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: next(answers))
    window.open_path(encrypted_pdf)
    assert window.doc is not None and window.doc.page_count == 1
    assert len(window.view.word_items) >= 6


def test_password_cancel_keeps_window_empty(window, encrypted_pdf, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("", False))
    window.open_path(encrypted_pdf)
    assert window.doc is None


# ---- Task 8: edit popover and save flow ------------------------------------------

def _select_name(qtbot, window):
    _click_word(qtbot, window.view, "Kwame")
    _click_word(qtbot, window.view, "Mensah", Qt.ShiftModifier)
    qtbot.waitUntil(lambda: window.popover.isVisible())


def _image(window):
    return window.view.current_pixmap().toImage()


def test_popover_prefills_selection(qtbot, window, native_pdf):
    window.open_path(native_pdf)
    _select_name(qtbot, window)
    assert window.popover.old_text.text() == "Kwame Mensah"
    assert window.popover.new_text.text() == "Kwame Mensah"
    assert window.popover.family.currentData() == "serif"
    assert abs(window.popover.size.value() - 11.0) < 0.01


def test_apply_flow_native(qtbot, window, native_pdf):
    window.open_path(native_pdf)
    original = _image(window)
    _select_name(qtbot, window)
    window.popover.new_text.setText("Kwame Asante")
    qtbot.mouseClick(window.popover.apply_button, Qt.LeftButton)
    assert len(window.edits.items()) == 1
    assert window.edits.items()[0].new_text == "Kwame Asante"
    assert "*" in window.windowTitle()
    assert not window.popover.isVisible()
    assert _image(window) != original
    window.undo_action.trigger()
    assert len(window.edits.items()) == 0
    assert _image(window) == original


def test_preview_updates_before_apply(qtbot, window, native_pdf):
    window.open_path(native_pdf)
    original = _image(window)
    _select_name(qtbot, window)
    window.popover.new_text.setText("Kwame Asante")
    qtbot.waitUntil(lambda: _image(window) != original, timeout=2000)
    qtbot.mouseClick(window.popover.cancel_button, Qt.LeftButton)
    assert _image(window) == original
    assert window.edits.items() == []


def test_apply_disabled_for_missing_glyph(qtbot, window, native_pdf):
    from test_fonts import _absent_char

    window.open_path(native_pdf)
    _select_name(qtbot, window)
    c = _absent_char()
    window.popover.new_text.setText(f"Kwame {c}")
    assert not window.popover.apply_button.isEnabled()
    assert window.popover.warning.isVisible()
    assert c in window.popover.warning.text()
    window.popover.new_text.setText("")
    assert not window.popover.apply_button.isEnabled()


def test_save_as_flow(qtbot, window, native_pdf, tmp_path, monkeypatch):
    import pymupdf
    from PySide6.QtWidgets import QFileDialog

    out = tmp_path / "out.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(out), ""))
    source_bytes = native_pdf.read_bytes()
    window.open_path(native_pdf)
    _select_name(qtbot, window)
    window.popover.new_text.setText("Kwame Asante")
    qtbot.mouseClick(window.popover.apply_button, Qt.LeftButton)
    window.save_action.trigger()
    assert "Asante" in pymupdf.open(out)[0].get_text()
    assert "*" not in window.windowTitle()
    assert native_pdf.read_bytes() == source_bytes


def test_save_as_rejects_source_path(qtbot, window, native_pdf, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    warnings = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(native_pdf), ""))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a[2]))
    source_bytes = native_pdf.read_bytes()
    window.open_path(native_pdf)
    _select_name(qtbot, window)
    window.popover.new_text.setText("Kwame Asante")
    qtbot.mouseClick(window.popover.apply_button, Qt.LeftButton)
    window.save_action.trigger()
    assert warnings and "original" in warnings[0].lower()
    assert native_pdf.read_bytes() == source_bytes
    assert "*" in window.windowTitle()


# ---- final-review fixes -------------------------------------------------------------

def _apply(qtbot, window, new_text):
    _select_name(qtbot, window)
    window.popover.new_text.setText(new_text)
    qtbot.mouseClick(window.popover.apply_button, Qt.LeftButton)


def test_dirty_after_undo_then_different_fix(qtbot, window, native_pdf, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(tmp_path / "o.pdf"), ""))
    window.open_path(native_pdf)
    _apply(qtbot, window, "Kwame Asante")
    window.save_action.trigger()
    assert not window.dirty
    window.undo_action.trigger()
    _apply(qtbot, window, "Kwame Boateng")
    assert window.dirty
    assert "*" in window.windowTitle()


def test_long_scan_opens_without_freezing(qtbot, tmp_path, native_pdf):
    from conftest import make_scanned

    long_scan = make_scanned(tmp_path / "long.pdf", native_pdf, pages=40)
    w = MainWindow(ocr=slow_fake_ocr)
    w.show()
    try:
        start = time.perf_counter()
        w.open_path(long_scan)
        assert time.perf_counter() - start < 1.0
        assert w.thumbs.count() == 40
        qtbot.waitUntil(lambda: w.thumbnails_done(), timeout=60000)
    finally:
        w._saved_version = w.edits.version
        w.close()


def test_skipped_pages_are_not_ocrd(qtbot, multipage_scan_pdf):
    w = MainWindow(ocr=slow_fake_ocr)
    w.show()
    try:
        w.open_path(multipage_scan_pdf)  # page 0 starts reading
        for i in (1, 2, 3, 4):
            w.go_to_page(i)
        qtbot.waitUntil(lambda: w.page_status() == "Scanned page · text found", timeout=20000)
        assert w.page_index == 4
        assert not any(w.cache.has(i) for i in (1, 2, 3))
    finally:
        w.close()


def crash_once_ocr(page):
    """First call kills the worker process; later calls succeed."""
    marker = os.environ["PDF_TOUCHUP_TEST_MARKER"]
    if not os.path.exists(marker):
        open(marker, "w").close()
        os._exit(1)
    return [Word("Kwame", (72, 90, 120, 101), (0, 0))]


def test_ocr_recovers_after_worker_crash(qtbot, scanned_pdf, tmp_path, monkeypatch):
    monkeypatch.setenv("PDF_TOUCHUP_TEST_MARKER", str(tmp_path / "crashed"))
    w = MainWindow(ocr=crash_once_ocr)
    w.show()
    try:
        w.open_path(scanned_pdf)
        qtbot.waitUntil(lambda: w.page_status() == "Scanned page · text found", timeout=30000)
    finally:
        w.close()


def test_refix_replaces_instead_of_stacking(qtbot, window, native_pdf):
    window.open_path(native_pdf)
    _apply(qtbot, window, "Kwame Asante")
    _click_word(qtbot, window.view, "Kwame Asante")
    qtbot.waitUntil(lambda: window.popover.isVisible())
    assert window.popover.old_text.text() == "Kwame Mensah"
    assert window.popover.new_text.text() == "Kwame Asante"
    window.popover.new_text.setText("Kwame Boateng")
    qtbot.mouseClick(window.popover.apply_button, Qt.LeftButton)
    assert [e.new_text for e in window.edits.items()] == ["Kwame Boateng"]
    assert [i.word.text for i in window.view.word_items if i.word.line_id[0] == "edit"] == ["Kwame Boateng"]
    window.undo_action.trigger()
    assert [e.new_text for e in window.edits.items()] == ["Kwame Asante"]


# ---- start screen, recent files, drag and drop ----------------------------------------
from PySide6.QtCore import QMimeData, QPointF, QUrl  # noqa: E402
from PySide6.QtGui import QDropEvent  # noqa: E402

from pdf_touchup.ui.recent import RecentFiles  # noqa: E402


def _drop(window, paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    event = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    window.dropEvent(event)


def test_starts_on_start_page(window):
    assert window.stack.currentWidget() is window.start_page
    assert window.start_page.recent.count() == 0
    assert window.start_page.empty_recent.isVisibleTo(window.start_page)


def test_open_records_recent_and_shows_editor(window, native_pdf, scanned_pdf):
    window.open_path(native_pdf)
    assert window.stack.currentWidget() is window.editor_page
    first = RecentFiles(window.settings).items()[0]
    assert first.path == native_pdf.resolve() and first.kind == "Typed"
    assert "Typed" in window.file_meta.text() and "1 page" in window.file_meta.text()
    window.open_path(scanned_pdf)
    assert RecentFiles(window.settings).items()[0].kind == "Scanned"


def test_recent_click_opens_file(window, native_pdf):
    RecentFiles(window.settings).add(native_pdf, "Typed")
    window.show_start()
    assert window.start_page.recent.count() == 1
    item = window.start_page.recent.item(0)
    window.start_page.recent.itemClicked.emit(item)
    assert window.doc is not None and window.path == native_pdf


def test_drop_pdf_opens_it(window, native_pdf):
    _drop(window, [native_pdf])
    assert window.doc is not None
    assert window.stack.currentWidget() is window.editor_page


def test_drop_non_pdf_shows_message(window, tmp_path, native_pdf, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    note = tmp_path / "notes.txt"
    note.write_text("hello")
    _drop(window, [note])
    _drop(window, [native_pdf, native_pdf])
    assert window.doc is None
    assert len(shown) == 2 and all("one PDF" in m for m in shown)
