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
    qtbot.addWidget(w)
    w.resize(1000, 800)
    w.show()
    yield w
    w.shutdown()


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
