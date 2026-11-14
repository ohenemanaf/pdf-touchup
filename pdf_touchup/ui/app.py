"""Main window: open a PDF, browse pages, pick words to fix, save a copy."""
from __future__ import annotations

import multiprocessing
import sys
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import pymupdf
from PySide6.QtCore import QObject, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QKeySequence, QPixmap
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QSizePolicy, QToolBar, QToolButton, QWidget)

from ..document import NeedsPassword, WrongPassword, open_document, page_kind
from ..edits import EditList, default_output_path, render_with_edits, save_as
from ..model import Edit, PageText
from ..ocr import OcrUnavailable, run_ocr_job
from ..resources import resource_dir
from ..selection import SelectionError, merge_selection
from ..style import detect_style
from ..text_source import PageTextCache
from .edit_popover import EditPopover
from .viewer import PageView

APP_NAME = "PDF Touch-up"
SCREEN_PX_PER_PT = 96 / 72
ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 50, 300, 25
THUMB_SCALE = 0.18
THUMB_BATCH = 3  # thumbnails rendered per event-loop turn, so long files open instantly

STATUS_NATIVE = "Normal page"
STATUS_READING = "Reading page…"
STATUS_FOUND = "Scanned page · text found"
STATUS_NONE = "Scanned page · no text found"
STATUS_NO_OCR = "Text reader missing — reinstall the app"


def to_qpixmap(pix: pymupdf.Pixmap) -> QPixmap:
    fmt = QImage.Format_RGB888 if pix.n == 3 else QImage.Format_RGBA8888
    return QPixmap.fromImage(QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy())


class _Bridge(QObject):
    """Carries OCR results from the worker's callback thread onto the GUI thread."""

    ocr_done = Signal(int, int, object)  # generation, page index, list[Word] | Exception


class MainWindow(QMainWindow):
    def __init__(self, ocr=None):
        super().__init__()
        self._ocr = ocr
        self._pool: ProcessPoolExecutor | None = None
        self._bridge = _Bridge()
        self._bridge.ocr_done.connect(self._on_ocr_done)
        self._futures: dict[int, Future] = {}
        self._crash_retried: set[int] = set()
        self._generation = 0
        self.doc: pymupdf.Document | None = None
        self.path: Path | None = None
        self.password: str | None = None
        self.cache: PageTextCache | None = None
        self.edits = EditList()
        self.edits.on_change = self._on_edits_changed
        self._saved_version = 0
        self.page_index = 0
        self.zoom_pct = 100
        self._thumb_next = 0
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setInterval(0)
        self._thumb_timer.timeout.connect(self._render_thumb_batch)

        self.setWindowTitle(APP_NAME)
        self.view = PageView(self)
        self.thumbs = QListWidget(self)
        self.thumbs.setObjectName("thumbs")
        self.thumbs.setFixedWidth(132)
        self.thumbs.setIconSize(QSize(100, 140))
        self.thumbs.setViewMode(QListWidget.IconMode)
        self.thumbs.setFlow(QListWidget.TopToBottom)
        self.thumbs.setWrapping(False)
        self.thumbs.setMovement(QListWidget.Static)
        self.thumbs.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.thumbs.currentRowChanged.connect(self._on_thumb)

        body = QWidget(self)
        layout = QHBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.thumbs)
        layout.addWidget(self.view, 1)
        self.setCentralWidget(body)
        self._build_toolbar()

        self.popover = EditPopover(self.view.viewport())
        self.view.selection_changed.connect(self._on_selection)
        self.popover.preview_requested.connect(self._on_preview)
        self.popover.applied.connect(self._on_applied)
        self.popover.cancelled.connect(self._on_cancelled)

        self._edits_label = QLabel("No edits")
        self._status_label = QLabel("Open a PDF to start")
        self._status_label.setMinimumWidth(260)
        self._status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.statusBar().addWidget(self._edits_label)
        self.statusBar().addPermanentWidget(self._status_label)
        self._refresh_actions()

    # ---- building -----------------------------------------------------------------
    def _action(self, text: str, slot, shortcut=None) -> QAction:
        act = QAction(text, self)
        act.triggered.connect(slot)
        if shortcut is not None:
            act.setShortcut(shortcut)
        return act

    def _build_toolbar(self) -> None:
        bar = QToolBar("Main", self)
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(bar)
        self.open_action = self._action("Open", self._choose_file, QKeySequence.Open)
        self.save_action = self._action("Save as…", self.save_as_dialog, QKeySequence.SaveAs)
        self.undo_action = self._action("Undo", self.undo, QKeySequence.Undo)
        self.redo_action = self._action("Redo", self.redo, QKeySequence("Ctrl+Y"))
        for act in (self.open_action, self.save_action, self.undo_action, self.redo_action):
            bar.addAction(act)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(spacer)
        self.page_label = QLabel("")
        self.page_label.setObjectName("pageLabel")
        bar.addWidget(self.page_label)
        self.zoom_out = QToolButton(text="−")
        self.zoom_in = QToolButton(text="+")
        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("zoomLabel")
        self.zoom_out.clicked.connect(lambda: self.set_zoom(self.zoom_pct - ZOOM_STEP))
        self.zoom_in.clicked.connect(lambda: self.set_zoom(self.zoom_pct + ZOOM_STEP))
        for w in (self.zoom_out, self.zoom_label, self.zoom_in):
            bar.addWidget(w)

    # ---- state helpers ------------------------------------------------------------
    def page_status(self) -> str:
        return self._status_label.text()

    def _set_status(self, text: str) -> None:
        self._status_label.setText(text)
        self.view.set_busy(text if text == STATUS_READING else None)

    @property
    def dirty(self) -> bool:
        return self.edits.version != self._saved_version

    def _refresh_actions(self) -> None:
        has_doc = self.doc is not None
        self.save_action.setEnabled(has_doc and bool(self.edits.items()))
        self.undo_action.setEnabled(self.edits.can_undo)
        self.redo_action.setEnabled(self.edits.can_redo)
        n = len(self.edits.items())
        self._edits_label.setText("No edits" if n == 0 else f"Edits on this file: {n}")
        name = self.path.name if self.path else ""
        self.setWindowTitle(f"{name}{' *' if self.dirty else ''} — {APP_NAME}" if name else APP_NAME)

    def _on_edits_changed(self) -> None:
        self._refresh_actions()
        if self.doc is not None:
            self.view.update_pixmap(self._render(self.page_index))

    # ---- opening ------------------------------------------------------------------
    def _choose_file(self) -> None:
        if not self._confirm_discard():
            return
        name, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF files (*.pdf)")
        if name:
            self.open_path(Path(name))

    def open_path(self, path: Path) -> None:
        path = Path(path)
        password = None
        prompt = "This PDF is protected. Enter its password:"
        while True:
            try:
                doc = open_document(path, password)
                break
            except (NeedsPassword, WrongPassword) as exc:
                if isinstance(exc, WrongPassword):
                    prompt = "Wrong password. Try again:"
                password, ok = QInputDialog.getText(self, "Password", prompt, QLineEdit.Password)
                if not ok:
                    return
            except Exception as exc:  # corrupt file or not a PDF
                QMessageBox.warning(self, APP_NAME, f"Couldn't open this file.\n\n{exc}")
                return
        self._generation += 1
        self._cancel_ocr()
        self._crash_retried.clear()
        self.doc, self.path, self.password = doc, path, password
        self.cache = PageTextCache(doc)
        self.edits = EditList()
        self.edits.on_change = self._on_edits_changed
        self._saved_version = self.edits.version
        self.page_index = 0
        self._fill_thumbs()
        self.go_to_page(0)
        self._refresh_actions()

    def _fill_thumbs(self) -> None:
        """Placeholders first; real thumbnails are drawn a few at a time so the window
        never stalls on long scans."""
        self._thumb_timer.stop()
        self.thumbs.blockSignals(True)
        self.thumbs.clear()
        for i, page in enumerate(self.doc):
            r = page.rect
            blank = QPixmap(max(1, int(r.width * THUMB_SCALE)), max(1, int(r.height * THUMB_SCALE)))
            blank.fill(QColor("#e9ecf0"))
            self.thumbs.addItem(QListWidgetItem(QIcon(blank), str(i + 1)))
        self.thumbs.setCurrentRow(0)
        self.thumbs.blockSignals(False)
        self._thumb_next = 0
        self._thumb_timer.start()

    def _render_thumb_batch(self) -> None:
        end = min(self._thumb_next + THUMB_BATCH, self.doc.page_count if self.doc else 0)
        for i in range(self._thumb_next, end):
            pix = self.doc[i].get_pixmap(matrix=pymupdf.Matrix(THUMB_SCALE, THUMB_SCALE), alpha=False)
            pm = to_qpixmap(pix)
            icon = QIcon(pm)
            icon.addPixmap(pm, QIcon.Selected)  # no blue tint over the selected page
            self.thumbs.item(i).setIcon(icon)
        self._thumb_next = end
        if self.doc is None or end >= self.doc.page_count:
            self._thumb_timer.stop()

    def thumbnails_done(self) -> bool:
        return self.doc is not None and self._thumb_next >= self.doc.page_count

    # ---- pages --------------------------------------------------------------------
    @property
    def scale(self) -> float:
        return self.zoom_pct / 100 * SCREEN_PX_PER_PT

    def _render(self, index: int) -> QPixmap:
        return to_qpixmap(render_with_edits(self.doc, index, self.edits.items(), self.scale))

    def _on_thumb(self, row: int) -> None:
        if row >= 0 and self.doc is not None and row != self.page_index:
            self.go_to_page(row)

    def set_zoom(self, pct: int) -> None:
        self.zoom_pct = max(ZOOM_MIN, min(ZOOM_MAX, pct))
        self.zoom_label.setText(f"{self.zoom_pct}%")
        if self.doc is not None:
            self.go_to_page(self.page_index)

    def go_to_page(self, index: int) -> None:
        self.popover.hide()
        self.page_index = index
        self.page_label.setText(f"Page {index + 1} / {self.doc.page_count}")
        if self.thumbs.currentRow() != index:
            self.thumbs.blockSignals(True)
            self.thumbs.setCurrentRow(index)
            self.thumbs.blockSignals(False)
        self._cancel_ocr(keep=index)  # pages flicked past don't hold up this one
        pixmap = self._render(index)
        if self.cache.has(index) or page_kind(self.doc[index]) != "scanned":
            page_text = self.cache.get(index)
            self.view.show_page(pixmap, page_text.words, self.scale)
            self._set_status(self._status_for(page_text))
        else:
            self.view.show_page(pixmap, [], self.scale)
            self._set_status(STATUS_READING)
            self._start_ocr(index)

    @staticmethod
    def _status_for(page_text: PageText) -> str:
        if page_text.kind == "native":
            return STATUS_NATIVE
        return STATUS_FOUND if page_text.words else STATUS_NONE

    # ---- background OCR -----------------------------------------------------------
    def _start_ocr(self, index: int) -> None:
        if index in self._futures:
            return
        if self._pool is None:
            self._pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
        generation = self._generation
        future = self._pool.submit(run_ocr_job, str(self.path), self.password, index, self._ocr)
        self._futures[index] = future

        def done(f: Future) -> None:
            if f.cancelled():
                return
            try:
                result = f.result()
            except Exception as exc:  # handed to the GUI thread below
                result = exc
            self._bridge.ocr_done.emit(generation, index, result)

        future.add_done_callback(done)

    def _cancel_ocr(self, keep: int | None = None) -> None:
        """Drop queued OCR jobs (a job already running finishes and is cached)."""
        for index, future in list(self._futures.items()):
            if index != keep and future.cancel():
                del self._futures[index]

    def _on_ocr_done(self, generation: int, index: int, result) -> None:
        if generation != self._generation:
            return  # a different file has been opened since
        self._futures.pop(index, None)
        if isinstance(result, BrokenProcessPool):
            # The worker died (crash, out of memory). Start a fresh one; retry this page once.
            self._pool = None
            self._futures.clear()
            if index == self.page_index and index not in self._crash_retried:
                self._crash_retried.add(index)
                self._start_ocr(index)
                return
        if isinstance(result, Exception):
            if index == self.page_index:
                self._set_status(STATUS_NO_OCR if isinstance(result, OcrUnavailable) else STATUS_NONE)
            return
        page_text = PageText(index, "scanned", result)
        self.cache.put(page_text)
        if index == self.page_index:
            self.view.show_page(self._render(index), page_text.words, self.scale)
            self._set_status(self._status_for(page_text))

    # ---- making a fix -------------------------------------------------------------
    def _on_selection(self, words: list) -> None:
        if not words or self.doc is None:
            self._on_cancelled()
            return
        try:
            rect, old = merge_selection(words)
        except SelectionError:
            return
        kind = self.cache.get(self.page_index).kind
        style = detect_style(self.doc[self.page_index], rect, old, old, kind)
        edit = Edit(self.page_index, rect, old, old, style, kind)
        s = self.view.scale_factor
        scene_rect = QRectF(rect[0] * s, rect[1] * s, (rect[2] - rect[0]) * s, (rect[3] - rect[1]) * s)
        anchor = self.view.mapFromScene(scene_rect).boundingRect()
        self.popover.start(edit, anchor)

    def _on_preview(self, edit: Edit) -> None:
        pix = render_with_edits(self.doc, self.page_index, self.edits.items() + [edit], self.scale)
        self.view.update_pixmap(to_qpixmap(pix))

    def _on_applied(self, edit: Edit) -> None:
        self.view.clear_selection()
        self.edits.add(edit)

    def _on_cancelled(self) -> None:
        self.popover.hide()
        if self.doc is not None:
            self.view.update_pixmap(self._render(self.page_index))

    # ---- edit history and saving --------------------------------------------------
    def undo(self) -> None:
        self.popover.hide()
        self.edits.undo()

    def redo(self) -> None:
        self.popover.hide()
        self.edits.redo()

    def save_as_dialog(self) -> None:
        if self.doc is None or not self.edits.items():
            return
        name, _ = QFileDialog.getSaveFileName(self, "Save a fixed copy", str(default_output_path(self.path)),
                                              "PDF files (*.pdf)")
        if not name:
            return
        out = Path(name)
        if out.resolve() == self.path.resolve():
            QMessageBox.warning(self, APP_NAME, "Please choose a different name. "
                                "Your original file is always kept as it is.")
            return
        try:
            save_as(self.path, self.edits.items(), out, self.password)
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"Couldn't save the file.\n\n{exc}")
            return
        self._saved_version = self.edits.version
        self._refresh_actions()
        self.statusBar().showMessage(f"Saved {out.name}", 5000)

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = QMessageBox.question(
            self, APP_NAME, "You have unsaved fixes. Save them first?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if answer == QMessageBox.Save:
            self.save_as_dialog()
            return not self.dirty
        return answer == QMessageBox.Discard

    def closeEvent(self, event):  # noqa: N802 (Qt naming)
        if self._confirm_discard():
            self.shutdown()
            event.accept()
        else:
            event.ignore()

    def shutdown(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None


def main() -> None:
    multiprocessing.freeze_support()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    qss = resource_dir() / "ui" / "style.qss"
    if qss.is_file():
        app.setStyleSheet(qss.read_text(encoding="utf-8"))
    window = MainWindow()
    window.resize(1200, 860)
    window.show()
    if len(sys.argv) > 1:
        window.open_path(Path(sys.argv[1]))
    sys.exit(app.exec())
