"""The screen you see before opening a file: open button, drop zone, steps and recent files."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout, QWidget)

from .recent import RecentFile, relative_day

APP_NAME = "PDF Touch-up"


def app_mark() -> QLabel:
    mark = QLabel("T")
    mark.setObjectName("appMark")
    mark.setFixedSize(22, 22)
    mark.setAlignment(Qt.AlignCenter)
    return mark


class StartPage(QWidget):
    open_requested = Signal()
    recent_chosen = Signal(Path)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("startPage")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header: app mark + name, Open PDF on the right.
        header = QWidget()
        header.setObjectName("header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 10, 16, 10)
        hl.setSpacing(8)
        name = QLabel(APP_NAME)
        name.setObjectName("appName")
        self.open_button = QPushButton("Open PDF")
        self.open_button.setObjectName("primary")
        self.open_button.clicked.connect(self.open_requested)
        hl.addWidget(app_mark())
        hl.addWidget(name)
        hl.addStretch(1)
        hl.addWidget(self.open_button)
        root.addWidget(header)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        root.addLayout(body, 1)

        # Left: recent files.
        pane = QWidget()
        pane.setObjectName("recentPane")
        pane.setFixedWidth(240)
        pl = QVBoxLayout(pane)
        pl.setContentsMargins(12, 14, 12, 12)
        pl.setSpacing(6)
        label = QLabel("RECENT")
        label.setObjectName("sectionLabel")
        self.recent = QListWidget()
        self.recent.setObjectName("recent")
        self.recent.setIconSize(QSize(16, 16))
        self.recent.itemClicked.connect(self._chosen)
        self.empty_recent = QLabel("No recent files yet")
        self.empty_recent.setObjectName("hint")
        pl.addWidget(label)
        pl.addWidget(self.empty_recent)
        pl.addWidget(self.recent, 1)
        body.addWidget(pane)

        # Right: title, drop zone, steps — centred, compact.
        main = QWidget()
        ml = QVBoxLayout(main)
        ml.setContentsMargins(40, 40, 40, 40)
        ml.addStretch(1)
        column = QWidget()
        column.setMaximumWidth(520)
        cl = QVBoxLayout(column)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(6)
        title = QLabel("Open a PDF to start")
        title.setObjectName("title")
        hint = QLabel("Fix a word, name, date or number in any PDF — even a scan of paper. "
                      "Free, and nothing leaves your computer.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        cl.addWidget(title)
        cl.addWidget(hint)
        cl.addSpacing(12)

        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("dropZone")
        self.drop_zone.setMinimumHeight(170)
        dl = QVBoxLayout(self.drop_zone)
        dl.setAlignment(Qt.AlignCenter)
        dl.setSpacing(6)
        self.drop_icon = QLabel()
        self.drop_icon.setAlignment(Qt.AlignCenter)
        drop_title = QLabel("Drop a PDF here")
        drop_title.setObjectName("dropTitle")
        drop_title.setAlignment(Qt.AlignCenter)
        drop_or = QLabel("or")
        drop_or.setObjectName("hint")
        drop_or.setAlignment(Qt.AlignCenter)
        self.choose_button = QPushButton("Choose a file")
        self.choose_button.clicked.connect(self.open_requested)
        dl.addWidget(self.drop_icon)
        dl.addWidget(drop_title)
        dl.addWidget(drop_or)
        dl.addWidget(self.choose_button, 0, Qt.AlignCenter)
        cl.addWidget(self.drop_zone)
        cl.addSpacing(10)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        for text in ("① Click a word", "② Type the fix", "③ Save a copy"):
            chip = QLabel(text)
            chip.setObjectName("chip")
            chips.addWidget(chip)
        chips.addStretch(1)
        cl.addLayout(chips)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(column, 10)
        row.addStretch(1)
        ml.addLayout(row)
        ml.addStretch(2)
        body.addWidget(main, 1)

    def set_drop_icon(self, icon) -> None:
        self.drop_icon.setPixmap(icon.pixmap(28, 28))

    def set_file_icon(self, icon) -> None:
        self._file_icon = icon
        for label in self.recent.findChildren(QLabel, "recentIcon"):
            label.setPixmap(icon.pixmap(16, 16))

    def set_dragging(self, on: bool) -> None:
        self.drop_zone.setProperty("active", "true" if on else "false")
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)

    def set_recent(self, items: list[RecentFile]) -> None:
        self.recent.clear()
        now = datetime.now()
        for r in items:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, str(r.path))
            item.setToolTip(str(r.path))
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(6, 4, 6, 4)
            rl.setSpacing(8)
            file_icon = QLabel()
            file_icon.setObjectName("recentIcon")
            if getattr(self, "_file_icon", None) is not None:
                file_icon.setPixmap(self._file_icon.pixmap(16, 16))
            texts = QVBoxLayout()
            texts.setSpacing(0)
            name = QLabel(r.path.name)
            name.setObjectName("recentName")
            meta = QLabel(f"{r.kind} · {relative_day(r.opened_at, now)}")
            meta.setObjectName("cardMeta")
            texts.addWidget(name)
            texts.addWidget(meta)
            rl.addWidget(file_icon, 0, Qt.AlignTop)
            rl.addLayout(texts, 1)
            item.setSizeHint(row.sizeHint())
            self.recent.addItem(item)
            self.recent.setItemWidget(item, row)
        self.empty_recent.setVisible(not items)
        self.recent.setVisible(bool(items))

    def _chosen(self, item: QListWidgetItem) -> None:
        self.recent_chosen.emit(Path(item.data(Qt.UserRole)))
