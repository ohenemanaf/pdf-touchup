"""The small box that appears under a selection: type the fix, adjust the look, apply."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QColorDialog, QComboBox, QDoubleSpinBox, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget)

from ..blend import width_scale
from ..fonts import load_font, missing_glyphs
from ..model import Edit

PREVIEW_DELAY_MS = 200
ORIGINAL = "original"
FAMILY_LABELS = (("Serif", "serif"), ("Sans", "sans"), ("Mono", "mono"))
MARGIN = 8


class EditPopover(QFrame):
    preview_requested = Signal(object)  # Edit
    applied = Signal(object)  # Edit
    cancelled = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("editPopover")
        self.setFixedWidth(380)
        self._base: Edit | None = None
        self._color = (0.0, 0.0, 0.0)

        self.old_text = QLineEdit()
        self.old_text.setToolTip("What the page says now. Correct it if the scan was misread.")
        self.new_text = QLineEdit()
        self.new_text.setPlaceholderText("Type the corrected text")
        self.family = QComboBox()
        self.size = QDoubleSpinBox()
        self.size.setRange(4, 72)
        self.size.setSingleStep(0.5)
        self.size.setDecimals(1)
        self.size.setSuffix(" pt")
        self.swatch = QPushButton()
        self.swatch.setObjectName("swatch")
        self.swatch.setToolTip("Text colour")
        self.warning = QLabel()
        self.warning.setObjectName("warning")
        self.warning.setWordWrap(True)
        self.warning.hide()
        self.cancel_button = QPushButton("Cancel")
        self.apply_button = QPushButton("Apply")
        self.apply_button.setObjectName("primary")
        self.apply_button.setDefault(True)

        grid = QGridLayout(self)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.addWidget(QLabel("Found"), 0, 0)
        grid.addWidget(self.old_text, 0, 1, 1, 3)
        grid.addWidget(QLabel("Change to"), 1, 0)
        grid.addWidget(self.new_text, 1, 1, 1, 3)
        grid.addWidget(QLabel("Font"), 2, 0)
        grid.addWidget(self.family, 2, 1)
        grid.addWidget(self.size, 2, 2)
        grid.addWidget(self.swatch, 2, 3)
        grid.addWidget(self.warning, 3, 0, 1, 4)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.apply_button)
        grid.addLayout(buttons, 4, 0, 1, 4)
        grid.setColumnStretch(1, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(PREVIEW_DELAY_MS)
        self._timer.timeout.connect(self._emit_preview)

        for signal in (self.old_text.textChanged, self.new_text.textChanged,
                       self.family.currentIndexChanged, self.size.valueChanged):
            signal.connect(self._changed)
        self.swatch.clicked.connect(self._pick_color)
        self.apply_button.clicked.connect(self._apply)
        self.cancel_button.clicked.connect(self._cancel)
        self.new_text.returnPressed.connect(self._apply)
        QShortcut(QKeySequence(Qt.Key_Escape), self, self._cancel)
        self.hide()

    # ---- public ---------------------------------------------------------------------
    def start(self, edit: Edit, anchor: QRect) -> None:
        """Show for a fresh selection. `anchor` is the selection in parent-widget pixels."""
        self._base = edit
        self._color = edit.style.color
        for w in (self.old_text, self.new_text, self.family, self.size):
            w.blockSignals(True)
        self.old_text.setText(edit.old_text)
        self.new_text.setText(edit.new_text)
        self.family.clear()
        if edit.style.font_buffer is not None:
            self.family.addItem("Original font", ORIGINAL)
        for label, key in FAMILY_LABELS:
            self.family.addItem(label, key)
        self.family.setCurrentIndex(0 if edit.style.font_buffer is not None
                                    else self.family.findData(edit.style.family))
        self.size.setValue(edit.style.size)
        for w in (self.old_text, self.new_text, self.family, self.size):
            w.blockSignals(False)
        self._paint_swatch()
        self._validate()
        self.adjustSize()
        self._place(anchor)
        self.show()
        self.raise_()
        self.new_text.setFocus()
        self.new_text.selectAll()

    def current_edit(self) -> Edit:
        assert self._base is not None
        base = self._base
        choice = self.family.currentData()
        buffer = base.style.font_buffer if choice == ORIGINAL else None
        family = base.style.family if choice == ORIGINAL else choice
        old, new, size = self.old_text.text(), self.new_text.text(), self.size.value()
        font = load_font(family, buffer)
        style = replace(base.style, family=family, size=size, color=self._color, font_buffer=buffer,
                        h_scale=width_scale(old, new, font, size, base.rect[2] - base.rect[0]))
        return replace(base, old_text=old, new_text=new, style=style)

    # ---- internals ------------------------------------------------------------------
    def _place(self, anchor: QRect) -> None:
        parent = self.parentWidget().rect()
        x = min(max(MARGIN, anchor.left()), parent.width() - self.width() - MARGIN)
        y = anchor.bottom() + MARGIN
        if y + self.height() > parent.height() - MARGIN:  # no room below: go above
            y = anchor.top() - self.height() - MARGIN
        self.move(max(MARGIN, x), max(MARGIN, y))

    def _missing(self) -> list[str]:
        choice = self.family.currentData()
        if choice is None or self._base is None:
            return []
        buffer = self._base.style.font_buffer if choice == ORIGINAL else None
        family = self._base.style.family if choice == ORIGINAL else choice
        return missing_glyphs(load_font(family, buffer), self.new_text.text())

    def _validate(self) -> bool:
        missing = self._missing()
        if missing:
            self.warning.setText("This font can't show: " + " ".join(missing))
        self.warning.setVisible(bool(missing))
        ok = bool(self.new_text.text().strip()) and not missing
        self.apply_button.setEnabled(ok)
        return ok

    def _changed(self, *_):
        if self._validate():
            self._timer.start()

    def _emit_preview(self) -> None:
        if self.isVisible() and self._validate():
            self.preview_requested.emit(self.current_edit())

    def _paint_swatch(self) -> None:
        r, g, b = (int(round(c * 255)) for c in self._color)
        self.swatch.setStyleSheet(f"background: rgb({r},{g},{b}); border: 1px solid #d9dde3;")

    def _pick_color(self) -> None:
        r, g, b = (int(round(c * 255)) for c in self._color)
        chosen = QColorDialog.getColor(QColor(r, g, b), self, "Text colour")
        if chosen.isValid():
            self._color = (chosen.redF(), chosen.greenF(), chosen.blueF())
            self._paint_swatch()
            self._changed()

    def _apply(self) -> None:
        if not self._validate():
            return
        self._timer.stop()
        edit = self.current_edit()
        self.hide()
        self.applied.emit(edit)

    def _cancel(self) -> None:
        self._timer.stop()
        if self.isVisible():
            self.hide()
            self.cancelled.emit()
