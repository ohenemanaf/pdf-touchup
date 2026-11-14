"""Main window: open a PDF, browse pages, pick words to fix, save a copy."""
from __future__ import annotations

import multiprocessing
import sys
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import replace
from pathlib import Path

import pymupdf
from PySide6.QtCore import QObject, QPointF, QRectF, QSettings, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QImage, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QPushButton, QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from ..document import NeedsPassword, WrongPassword, open_document, page_kind
from ..edits import EditList, default_output_path, render_with_edits, save_as
from ..model import Edit, PageText
from ..ocr import OcrUnavailable, run_ocr_job
from ..selection import SelectionError, display_words, merge_selection
from ..style import detect_style
from ..text_source import PageTextCache
from .edit_popover import EditPopover
from .toast import Toast
from .fixes_panel import FixesPanel
from .recent import RecentFiles
from .start_page import StartPage, app_mark
from .theme import PALETTES, apply_theme, current_theme, icon, save_theme, saved_theme
from .viewer import PageView

APP_NAME = "PDF Touch-up"
SCREEN_PX_PER_PT = 96 / 72
ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 50, 300, 25
THUMB_SCALE = 0.18
BADGE_ROLE = Qt.UserRole + 1  # number of fixes on a page, drawn as a badge on its thumbnail
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
    def __init__(self, ocr=None, settings: QSettings | None = None):
        super().__init__()
        self._ocr = ocr
        self.settings = settings if settings is not None else app_settings()
        self._pool: ProcessPoolExecutor | None = None
        self._bridge = _Bridge()
        self._bridge.ocr_done.connect(self._on_ocr_done)
        self._inflight: tuple[int, int] | None = None  # (generation, page) being read now
        self._crash_retried: set[int] = set()
        self._ocr_failed: set[int] = set()
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

        self._build_actions()
        self.editor_page = QWidget(self)
        self.editor_page.setObjectName("editorPage")
        editor = QVBoxLayout(self.editor_page)
        editor.setContentsMargins(0, 0, 0, 0)
        editor.setSpacing(0)
        editor.addWidget(self._build_header())
        self.editor_body = QHBoxLayout()
        self.editor_body.setContentsMargins(0, 0, 0, 0)
        self.editor_body.setSpacing(0)
        self.editor_body.addWidget(self.thumbs)
        self.editor_body.addWidget(self.view, 1)
        self.fixes_panel = FixesPanel(self)
        self.fixes_panel.jump_requested.connect(self._jump_to_fix)
        self.fixes_panel.remove_requested.connect(self._remove_fix)
        self.editor_body.addWidget(self.fixes_panel)
        self._thumb_base: dict[int, QPixmap] = {}
        editor.addLayout(self.editor_body, 1)

        self.start_page = StartPage(self)
        self.start_page.open_requested.connect(self._choose_file)
        self.start_page.recent_chosen.connect(self._open_recent)
        self.stack = QStackedWidget(self)
        self.stack.addWidget(self.start_page)
        self.stack.addWidget(self.editor_page)
        self.setCentralWidget(self.stack)
        self.setAcceptDrops(True)
        self.view.setAcceptDrops(False)
        self.view.viewport().setAcceptDrops(False)

        self.popover = EditPopover(self.view.viewport())
        self.toast = Toast(self.view)
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
        self._apply_icons()
        self.show_start()
        self._refresh_actions()

    # ---- building -----------------------------------------------------------------
    def _action(self, text: str, slot, shortcut=None) -> QAction:
        act = QAction(text, self)
        act.triggered.connect(slot)
        if shortcut is not None:
            act.setShortcut(shortcut)
        return act

    def _build_actions(self) -> None:
        """Window-wide actions: they carry the keyboard shortcuts and drive the header buttons."""
        self.open_action = self._action("Open", self._choose_file, QKeySequence.Open)
        self.save_action = self._action("Save copy", self.save_as_dialog, QKeySequence.Save)
        self.undo_action = self._action("Undo", self.undo, QKeySequence.Undo)
        self.redo_action = self._action("Redo", self.redo, QKeySequence("Ctrl+Y"))
        self.zoom_in_action = self._action("Zoom in", lambda: self.set_zoom(self.zoom_pct + ZOOM_STEP),
                                           QKeySequence("Ctrl+="))
        self.zoom_out_action = self._action("Zoom out", lambda: self.set_zoom(self.zoom_pct - ZOOM_STEP),
                                            QKeySequence("Ctrl+-"))
        for act in (self.open_action, self.save_action, self.undo_action, self.redo_action,
                    self.zoom_in_action, self.zoom_out_action):
            self.addAction(act)

    def _icon_button(self, tip: str, slot) -> QToolButton:
        button = QToolButton()
        button.setObjectName("iconButton")
        button.setToolTip(tip)
        button.setAutoRaise(True)
        button.setIconSize(QSize(18, 18))
        button.clicked.connect(slot)
        return button

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 8, 14, 8)
        hl.setSpacing(6)
        hl.addWidget(app_mark())
        hl.addSpacing(4)
        self.file_name = QLabel("")
        self.file_name.setObjectName("fileName")
        self.file_meta = QLabel("")
        self.file_meta.setObjectName("fileMeta")
        hl.addWidget(self.file_name)
        hl.addWidget(self.file_meta)
        hl.addStretch(1)
        self.open_button = self._icon_button("Open another PDF (Ctrl+O)", self.open_action.trigger)
        self.undo_button = self._icon_button("Undo (Ctrl+Z)", self.undo_action.trigger)
        self.redo_button = self._icon_button("Redo (Ctrl+Y)", self.redo_action.trigger)
        self.zoom_out = self._icon_button("Zoom out (Ctrl+-)", self.zoom_out_action.trigger)
        self.zoom_in = self._icon_button("Zoom in (Ctrl+=)", self.zoom_in_action.trigger)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("zoomLabel")
        self.zoom_label.setFixedWidth(44)
        self.zoom_label.setAlignment(Qt.AlignCenter)
        self.page_label = QLabel("")
        self.page_label.setObjectName("fileMeta")
        self.theme_button = self._icon_button("Switch light / dark", self.toggle_theme)
        self.save_button = QPushButton("Save copy")
        self.save_button.setObjectName("primary")
        self.save_button.setToolTip("Save a fixed copy (Ctrl+S). Your original is never changed.")
        self.save_button.clicked.connect(self.save_action.trigger)
        for w in (self.open_button, self.undo_button, self.redo_button):
            hl.addWidget(w)
        hl.addSpacing(8)
        for w in (self.zoom_out, self.zoom_label, self.zoom_in):
            hl.addWidget(w)
        hl.addSpacing(8)
        hl.addWidget(self.page_label)
        hl.addWidget(self.theme_button)
        hl.addSpacing(4)
        hl.addWidget(self.save_button)
        return header

    # ---- theme ----------------------------------------------------------------------
    def _theme(self) -> str:
        app = QApplication.instance()
        return current_theme(app) if app is not None else "light"

    def _apply_icons(self) -> None:
        palette = PALETTES[self._theme()]
        colour, muted = palette["text"], palette["text_muted"]
        for button, name in ((self.open_button, "folder"), (self.undo_button, "undo"),
                             (self.redo_button, "redo"), (self.zoom_out, "minus"), (self.zoom_in, "plus")):
            button.setIcon(icon(name, colour))
        self.theme_button.setIcon(icon("moon" if self._theme() == "light" else "sun", colour))
        self.view.setBackgroundBrush(QColor(palette["canvas"]))
        self.start_page.set_drop_icon(icon("upload", palette["accent"], 28))
        self.start_page.set_file_icon(icon("file", muted, 16))

    def toggle_theme(self) -> None:
        name = "dark" if self._theme() == "light" else "light"
        apply_theme(QApplication.instance(), name)
        save_theme(self.settings, name)
        self._apply_icons()

    # ---- start page and drag-and-drop ----------------------------------------------
    def show_start(self) -> None:
        self.start_page.set_recent(RecentFiles(self.settings).items())
        self.stack.setCurrentWidget(self.start_page)
        self.statusBar().hide()

    def _open_recent(self, path: Path) -> None:
        if self._confirm_discard():
            self.open_path(path)

    @staticmethod
    def _dropped_pdf(mime) -> Path | None:
        urls = [u for u in mime.urls() if u.isLocalFile()] if mime.hasUrls() else []
        if len(urls) == 1 and urls[0].toLocalFile().lower().endswith(".pdf"):
            return Path(urls[0].toLocalFile())
        return None

    def dragEnterEvent(self, event):  # noqa: N802 (Qt naming)
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.start_page.set_dragging(True)

    def dragLeaveEvent(self, event):  # noqa: N802
        self.start_page.set_dragging(False)

    def dropEvent(self, event):  # noqa: N802
        self.start_page.set_dragging(False)
        path = self._dropped_pdf(event.mimeData())
        if path is None:
            QMessageBox.information(self, APP_NAME, "Drop one PDF file to open it.")
            return
        event.acceptProposedAction()
        if self._confirm_discard():
            self.open_path(path)

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
        self.save_button.setEnabled(self.save_action.isEnabled())
        self.undo_button.setEnabled(self.undo_action.isEnabled())
        self.redo_button.setEnabled(self.redo_action.isEnabled())
        n = len(self.edits.items())
        self._edits_label.setText("No edits" if n == 0 else f"Edits on this file: {n}")
        name = self.path.name if self.path else ""
        self.setWindowTitle(f"{name}{' *' if self.dirty else ''} — {APP_NAME}" if name else APP_NAME)

    def _on_edits_changed(self) -> None:
        self._refresh_actions()
        self.fixes_panel.set_fixes(self.edits.items())
        if self.doc is not None:
            self._refresh_page()
            self._update_badges()

    # ---- fixes panel and thumbnail badges -------------------------------------------
    def _jump_to_fix(self, edit: Edit) -> None:
        if edit.page_index != self.page_index:
            self.go_to_page(edit.page_index)
        x0, y0, x1, y1 = edit.rect
        s = self.view.scale_factor
        self.view.centerOn((x0 + x1) / 2 * s, (y0 + y1) / 2 * s)
        self.view.flash_rect(QRectF(x0 * s, y0 * s, (x1 - x0) * s, (y1 - y0) * s))

    def _remove_fix(self, edit: Edit) -> None:
        self.popover.hide()
        self.edits.remove(edit)
        self.toast.show_message("Fix removed")

    def _fix_counts(self) -> dict[int, int]:
        counts: dict[int, int] = {}
        for e in self.edits.items():
            counts[e.page_index] = counts.get(e.page_index, 0) + 1
        return counts

    def thumb_badge(self, index: int) -> int:
        item = self.thumbs.item(index)
        return int(item.data(BADGE_ROLE) or 0) if item is not None else 0

    def _set_thumb_icon(self, index: int, count: int) -> None:
        item = self.thumbs.item(index)
        if item is None:
            return
        item.setData(BADGE_ROLE, count)
        base = self._thumb_base.get(index)
        if base is None:
            return
        pm = base.copy()
        if count:
            painter = QPainter(pm)
            painter.setRenderHint(QPainter.Antialiasing)
            r = 9
            cx, cy = pm.width() - r - 3, r + 3
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(PALETTES["light"]["accent"]))
            painter.drawEllipse(QPointF(cx, cy), r, r)
            painter.setPen(QColor("#ffffff"))
            font = painter.font()
            font.setPixelSize(11)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(QRectF(cx - r, cy - r, 2 * r, 2 * r), Qt.AlignCenter, str(count))
            painter.end()
        icon_ = QIcon(pm)
        icon_.addPixmap(pm, QIcon.Selected)  # no blue tint over the selected page
        item.setIcon(icon_)

    def _update_badges(self) -> None:
        counts = self._fix_counts()
        for i in range(self.thumbs.count()):
            self._set_thumb_icon(i, counts.get(i, 0))

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
        self._crash_retried.clear()
        self._ocr_failed.clear()
        self.doc, self.path, self.password = doc, path, password
        self.cache = PageTextCache(doc)
        self.edits = EditList()
        self.edits.on_change = self._on_edits_changed
        self._saved_version = self.edits.version
        self.page_index = 0
        kind = self._doc_kind()
        RecentFiles(self.settings).add(path, kind)
        pages = doc.page_count
        self.file_name.setText(path.name)
        self.file_meta.setText(f"· {kind} · {pages} page{'s' if pages != 1 else ''}")
        self.stack.setCurrentWidget(self.editor_page)
        self.statusBar().show()
        self.fixes_panel.set_fixes([])
        self._fill_thumbs()
        self.go_to_page(0)
        self._refresh_actions()

    def _doc_kind(self, sample: int = 5) -> str:
        """"Scanned", "Typed" or "Mixed", judged from the first few pages."""
        kinds = {page_kind(self.doc[i]) != "native" for i in range(min(sample, self.doc.page_count))}
        if kinds == {True}:
            return "Scanned"
        return "Typed" if kinds == {False} else "Mixed"

    def _fill_thumbs(self) -> None:
        """Placeholders first; real thumbnails are drawn a few at a time so the window
        never stalls on long scans."""
        self._thumb_timer.stop()
        self._thumb_base = {}
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
            self._thumb_base[i] = to_qpixmap(pix)
            self._set_thumb_icon(i, self._fix_counts().get(i, 0))
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
        if self.doc is None:
            return
        self.zoom_pct = max(ZOOM_MIN, min(ZOOM_MAX, pct))
        self.zoom_label.setText(f"{self.zoom_pct}%")
        if self.doc is not None:
            self.go_to_page(self.page_index)

    def go_to_page(self, index: int) -> None:
        self.popover.hide()
        self.page_index = index
        self.page_label.setText(f"{index + 1} / {self.doc.page_count}")
        if self.thumbs.currentRow() != index:
            self.thumbs.blockSignals(True)
            self.thumbs.setCurrentRow(index)
            self.thumbs.blockSignals(False)
        pixmap = self._render(index)
        if self.cache.has(index) or page_kind(self.doc[index]) != "scanned":
            page_text = self.cache.get(index)
            self.view.show_page(pixmap, self._words(index), self.scale)
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
    # One page at a time: the worker process prefetches queued jobs, so queued jobs could not
    # be cancelled reliably. Instead, when a job finishes, the page on screen *now* goes next.
    def _start_ocr(self, index: int) -> None:
        if self._inflight is not None:
            return  # _ocr_next() picks up the current page when the worker is free
        if self._pool is None:
            self._pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
        generation = self._generation
        self._inflight = (generation, index)
        future = self._pool.submit(run_ocr_job, str(self.path), self.password, index, self._ocr)

        def done(f: Future) -> None:
            try:
                result = f.result()
            except Exception as exc:  # handed to the GUI thread below
                result = exc
            self._bridge.ocr_done.emit(generation, index, result)

        future.add_done_callback(done)

    def _ocr_next(self) -> None:
        index = self.page_index
        if (self.doc is None or self._inflight is not None or self.cache.has(index)
                or index in self._ocr_failed or page_kind(self.doc[index]) != "scanned"):
            return
        self._start_ocr(index)

    def _on_ocr_done(self, generation: int, index: int, result) -> None:
        self._inflight = None
        if generation == self._generation:
            self._handle_ocr_result(index, result)
        self._ocr_next()

    def _handle_ocr_result(self, index: int, result) -> None:
        if isinstance(result, BrokenProcessPool):
            # The worker died (crash, out of memory). Start a fresh one; retry this page once.
            self._pool = None
            if index not in self._crash_retried:
                self._crash_retried.add(index)
                return
        if isinstance(result, Exception):
            self._ocr_failed.add(index)
            if index == self.page_index:
                self._set_status(STATUS_NO_OCR if isinstance(result, OcrUnavailable) else STATUS_NONE)
            return
        page_text = PageText(index, "scanned", result)
        self.cache.put(page_text)
        if index == self.page_index:
            self.view.show_page(self._render(index), self._words(index), self.scale)
            self._set_status(self._status_for(page_text))

    # ---- making a fix -------------------------------------------------------------
    def _page_edits(self, index: int) -> list[Edit]:
        return [e for e in self.edits.items() if e.page_index == index]

    def _words(self, index: int) -> list:
        """Clickable words: the page's words, with each fixed spot shown as its fix."""
        return display_words(self.cache.get(index).words, self._page_edits(index))

    def _refresh_page(self) -> None:
        """Redraw the current page and its clickable words after fixes change."""
        index = self.page_index
        if self.cache.has(index) or page_kind(self.doc[index]) != "scanned":
            self.view.show_page(self._render(index), self._words(index), self.scale)
        else:
            self.view.update_pixmap(self._render(index))

    def _on_selection(self, words: list) -> None:
        if not words or self.doc is None:
            self._on_cancelled()
            return
        fixed = [w for w in words if w.line_id[0] == "edit"]
        if fixed:
            # Clicking a fixed word re-opens that fix; applying replaces it (no stacking).
            earlier = self._page_edits(self.page_index)[fixed[0].line_id[1]]
            edit = replace(earlier, replaces=earlier)
            rect = edit.rect
        else:
            try:
                rect, old = merge_selection(words)
            except SelectionError:
                return
            page_text = self.cache.get(self.page_index)
            kind = page_text.kind
            line = [w for w in page_text.words if w.line_id == words[0].line_id]
            style = detect_style(self.doc[self.page_index], rect, old, old, kind, line_words=line)
            edit = Edit(self.page_index, rect, old, old, style, kind)
        s = self.view.scale_factor
        scene_rect = QRectF(rect[0] * s, rect[1] * s, (rect[2] - rect[0]) * s, (rect[3] - rect[1]) * s)
        anchor = self.view.mapFromScene(scene_rect).boundingRect()
        self.popover.start(edit, anchor)

    def _on_preview(self, edit: Edit) -> None:
        others = [e for e in self.edits.items() if e is not edit.replaces]
        pix = render_with_edits(self.doc, self.page_index, others + [edit], self.scale)
        self.view.update_pixmap(to_qpixmap(pix))

    def _on_applied(self, edit: Edit) -> None:
        self.view.clear_selection()
        self.edits.add(edit)
        self.toast.show_message("Fixed")

    def _on_cancelled(self) -> None:
        self.popover.hide()
        if self.doc is not None:
            self._refresh_page()

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
        folder = QUrl.fromLocalFile(str(out.parent))
        self.toast.show_message(f"Saved {out.name}", ("Open folder", lambda: QDesktopServices.openUrl(folder)))

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


def app_settings() -> QSettings:
    return QSettings(APP_NAME, APP_NAME)


def main() -> None:
    multiprocessing.freeze_support()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    settings = app_settings()
    apply_theme(app, saved_theme(settings))
    window = MainWindow(settings=settings)
    window.resize(1200, 860)
    window.show()
    if len(sys.argv) > 1:
        window.open_path(Path(sys.argv[1]))
    sys.exit(app.exec())
