"""A small message that fades in over the page, then fades away ("Fixed", "Saved … · Open folder")."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton, QWidget

FADE_MS = 150
MARGIN = 16


def fade(widget: QWidget, show: bool, ms: int = FADE_MS, done: Callable[[], None] | None = None) -> None:
    """Fade a widget in (showing it first) or out (hiding it at the end)."""
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(ms)
    anim.setEasingCurve(QEasingCurve.OutCubic)
    anim.setStartValue(effect.opacity() if widget.isVisible() else 0.0)
    anim.setEndValue(1.0 if show else 0.0)
    if show:
        widget.show()
        widget.raise_()

    def finished() -> None:
        if not show:
            widget.hide()
        if done:
            done()

    anim.finished.connect(finished)
    widget._fade_anim = anim  # keep a reference while it runs
    anim.start()


class Toast(QFrame):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("toast")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(12)
        self._label = QLabel()
        self.action_button = QPushButton()
        self.action_button.setObjectName("linkButton")
        self.action_button.setCursor(Qt.PointingHandCursor)
        self.action_button.clicked.connect(self._run_action)
        layout.addWidget(self._label)
        layout.addWidget(self.action_button)
        self._action: Callable[[], None] | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: fade(self, False))
        self.hide()

    def text(self) -> str:
        return self._label.text()

    def show_message(self, text: str, action: tuple[str, Callable[[], None]] | None = None,
                     ms: int = 2500) -> None:
        self._label.setText(text)
        self._action = action[1] if action else None
        self.action_button.setText(action[0] if action else "")
        self.action_button.setVisible(action is not None)
        self.adjustSize()
        parent = self.parentWidget().rect()
        self.move((parent.width() - self.width()) // 2, parent.height() - self.height() - MARGIN)
        fade(self, True)
        self._timer.start(ms + (2000 if action else 0))  # linger longer when there's a button

    def _run_action(self) -> None:
        if self._action:
            self._action()
        self._timer.start(0)
