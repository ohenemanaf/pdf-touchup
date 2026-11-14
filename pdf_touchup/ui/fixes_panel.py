"""Right-hand list of every fix on the file: old → new, the page, and Undo for that one fix."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout,
                               QWidget)

from ..model import Edit

PANEL_WIDTH = 240


class FixCard(QFrame):
    clicked = Signal(object)  # Edit
    undo_clicked = Signal(object)  # Edit

    def __init__(self, edit: Edit, parent=None):
        super().__init__(parent)
        self.edit = edit
        self.setObjectName("fixCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Show this fix on the page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(1)
        self.old_label = QLabel(edit.old_text)
        self.old_label.setObjectName("oldText")
        self.new_label = QLabel(edit.new_text)
        self.new_label.setObjectName("newText")
        for label in (self.old_label, self.new_label):
            label.setWordWrap(True)
        meta = QHBoxLayout()
        meta.setContentsMargins(0, 3, 0, 0)
        self.meta_label = QLabel(f"Page {edit.page_index + 1}")
        self.meta_label.setObjectName("cardMeta")
        self.undo_button = QPushButton("Undo")
        self.undo_button.setObjectName("linkButton")
        self.undo_button.setCursor(Qt.PointingHandCursor)
        self.undo_button.setToolTip("Remove just this fix (Ctrl+Z brings it back)")
        self.undo_button.clicked.connect(lambda: self.undo_clicked.emit(self.edit))
        meta.addWidget(self.meta_label)
        meta.addStretch(1)
        meta.addWidget(self.undo_button)
        layout.addWidget(self.old_label)
        layout.addWidget(self.new_label)
        layout.addLayout(meta)

    def set_current(self, on: bool) -> None:
        self.setProperty("current", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):  # noqa: N802 (Qt naming)
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.edit)
        super().mousePressEvent(event)


class FixesPanel(QWidget):
    jump_requested = Signal(object)  # Edit
    remove_requested = Signal(object)  # Edit

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("fixesPanel")
        self.setFixedWidth(PANEL_WIDTH)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.cards: list[FixCard] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 14, 12, 12)
        outer.setSpacing(8)
        self.heading = QLabel("FIXES")
        self.heading.setObjectName("sectionLabel")
        self.empty_state = QLabel("Click any word on the page to fix it.")
        self.empty_state.setObjectName("emptyState")
        self.empty_state.setWordWrap(True)
        scroll = QScrollArea()
        scroll.setObjectName("fixesScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        holder = QWidget()
        holder.setObjectName("fixesList")
        self._list = QVBoxLayout(holder)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(6)
        self._list.addStretch(1)
        scroll.setWidget(holder)
        outer.addWidget(self.heading)
        outer.addWidget(self.empty_state)
        outer.addWidget(scroll, 1)

    def set_fixes(self, edits: list[Edit]) -> None:
        for card in self.cards:
            card.setParent(None)
            card.deleteLater()
        self.cards = []
        for edit in sorted(edits, key=lambda e: (e.page_index, e.rect[1], e.rect[0])):
            card = FixCard(edit)
            card.clicked.connect(self._jump)
            card.undo_clicked.connect(self.remove_requested)
            self._list.insertWidget(self._list.count() - 1, card)
            self.cards.append(card)
        self.heading.setText(f"FIXES · {len(edits)}" if edits else "FIXES")
        self.empty_state.setVisible(not edits)

    def _jump(self, edit: Edit) -> None:
        for card in self.cards:
            card.set_current(card.edit is edit)
        self.jump_requested.emit(edit)
