"""The page canvas: shows a rendered page and lets the user pick words on one line."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPen, QPixmap
from PySide6.QtWidgets import (QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene,
                               QGraphicsView, QLabel)

from ..model import Word

HOVER = QColor(47, 111, 235, 40)
SELECTED = QColor(47, 111, 235, 70)
OUTLINE = QColor(47, 111, 235, 160)


class WordItem(QGraphicsRectItem):
    def __init__(self, word: Word, scale: float):
        x0, y0, x1, y1 = word.rect
        super().__init__(QRectF(x0 * scale, y0 * scale, (x1 - x0) * scale, (y1 - y0) * scale))
        self.word = word
        self.selected = False
        self.setAcceptHoverEvents(True)
        self.setPen(QPen(Qt.NoPen))
        self.setCursor(Qt.IBeamCursor)
        self._paint(False)

    def _paint(self, hover: bool) -> None:
        if self.selected:
            self.setBrush(QBrush(SELECTED))
            self.setPen(QPen(OUTLINE, 1))
        elif hover:
            self.setBrush(QBrush(HOVER))
            self.setPen(QPen(OUTLINE, 1))
        else:
            self.setBrush(QBrush(Qt.transparent))
            self.setPen(QPen(Qt.NoPen))

    def set_selected(self, on: bool) -> None:
        self.selected = on
        self._paint(False)

    def hoverEnterEvent(self, event):  # noqa: N802 (Qt naming)
        self._paint(True)

    def hoverLeaveEvent(self, event):  # noqa: N802
        self._paint(False)


class PageView(QGraphicsView):
    selection_changed = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.setBackgroundBrush(QColor("#eef0f3"))
        self.word_items: list[WordItem] = []
        self.scale_factor = 1.0
        self._selection: list[WordItem] = []
        self._dragging = False
        self._busy = QLabel(self)
        self._busy.setObjectName("busyChip")
        self._busy.hide()

    def show_page(self, pixmap: QPixmap, words: list[Word], zoom: float) -> None:
        """zoom = screen pixels per PDF point used to render `pixmap`."""
        self.scene().clear()
        self.word_items = []
        self._selection = []
        self.scale_factor = zoom
        page = QGraphicsPixmapItem(pixmap)
        page.setShapeMode(QGraphicsPixmapItem.BoundingRectShape)
        self.scene().addItem(page)
        for word in words:
            item = WordItem(word, zoom)
            self.scene().addItem(item)
            self.word_items.append(item)
        self.scene().setSceneRect(QRectF(pixmap.rect()).adjusted(-16, -16, 16, 16))

    def current_pixmap(self) -> QPixmap:
        for item in self.scene().items():
            if isinstance(item, QGraphicsPixmapItem):
                return item.pixmap()
        return QPixmap()

    def update_pixmap(self, pixmap: QPixmap) -> None:
        for item in self.scene().items():
            if isinstance(item, QGraphicsPixmapItem):
                item.setPixmap(pixmap)

    def set_busy(self, text: str | None) -> None:
        if text:
            self._busy.setText(text)
            self._busy.adjustSize()
            self._busy.move(12, 12)
            self._busy.show()
        else:
            self._busy.hide()

    def selected_words(self) -> list[Word]:
        return [i.word for i in self._selection]

    def clear_selection(self) -> None:
        for item in self._selection:
            item.set_selected(False)
        self._selection = []
        self.selection_changed.emit([])

    def _word_at(self, pos) -> WordItem | None:
        for item in self.items(pos):
            if isinstance(item, WordItem):
                return item
        return None

    def _extend(self, item: WordItem) -> bool:
        if item in self._selection:
            return False
        if self._selection and item.word.line_id != self._selection[0].word.line_id:
            return False
        item.set_selected(True)
        self._selection.append(item)
        return True

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        item = self._word_at(event.position().toPoint())
        if event.modifiers() & Qt.ShiftModifier and self._selection:
            if item:
                self._extend(item)
        else:
            for old in self._selection:
                old.set_selected(False)
            self._selection = []
            if item:
                self._extend(item)
        self._dragging = item is not None
        self.selection_changed.emit(self.selected_words())

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._dragging and event.buttons() & Qt.LeftButton:
            item = self._word_at(event.position().toPoint())
            if item and self._extend(item):
                self.selection_changed.emit(self.selected_words())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._dragging = False
        super().mouseReleaseEvent(event)
