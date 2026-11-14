"""Light and dark themes (style B: neutral, compact, one blue accent) and small line icons."""
from __future__ import annotations

from string import Template

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

THEME_KEY = "theme"

PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#ffffff", "surface": "#ffffff", "surface_alt": "#f7f8fa", "border": "#e3e6ea",
        "input_border": "#d9dde3", "hover": "#f1f3f6", "pressed": "#e6e9ee",
        "text": "#1f2329", "text_muted": "#5b6470", "text_faint": "#8a929c",
        "accent": "#2f6feb", "accent_hover": "#2a63d4", "accent_soft": "#e8effd", "accent_text": "#ffffff",
        "accent_disabled": "#a9c1f3", "canvas": "#eef0f3",
        "danger": "#c62f2f", "success": "#1d7a45", "success_soft": "#e8f6ee",
        "toast_bg": "#1f2329", "toast_text": "#ffffff", "drop_bg": "#fafbfc", "drop_border": "#c6ccd5",
    },
    "dark": {
        "bg": "#16181d", "surface": "#1d2026", "surface_alt": "#1a1d22", "border": "#2c3038",
        "input_border": "#3a404b", "hover": "#262a31", "pressed": "#2e333b",
        "text": "#e6e8ec", "text_muted": "#9aa3ae", "text_faint": "#78818c",
        "accent": "#4c84ff", "accent_hover": "#6b98ff", "accent_soft": "#22304d", "accent_text": "#ffffff",
        "accent_disabled": "#2b3f66", "canvas": "#111317",
        "danger": "#ff6b6b", "success": "#5bd38f", "success_soft": "#1c3328",
        "toast_bg": "#e6e8ec", "toast_text": "#16181d", "drop_bg": "#1a1d22", "drop_border": "#3a404b",
    },
}

_QSS = Template("""
* { font-family: "Segoe UI", "Inter", sans-serif; font-size: 14px; color: $text; }
QMainWindow, QStackedWidget, QWidget#editorPage, QWidget#startPage { background: $bg; }
QToolTip { background: $toast_bg; color: $toast_text; border: none; padding: 4px 8px; border-radius: 6px; }

/* header */
QWidget#header { background: $surface; border-bottom: 1px solid $border; }
QLabel#appName { font-size: 14px; font-weight: 600; }
QLabel#appMark { background: $accent; color: $accent_text; border-radius: 6px; font-weight: 700; font-size: 12px; }
QLabel#fileName { font-weight: 600; }
QLabel#fileMeta, QLabel#zoomLabel { color: $text_muted; font-size: 13px; }
QToolButton#iconButton { min-width: 32px; min-height: 32px; max-height: 32px; border-radius: 8px;
    border: 1px solid transparent; background: transparent; padding: 0; }
QToolButton#iconButton:hover { background: $hover; }
QToolButton#iconButton:pressed { background: $pressed; }
QToolButton#iconButton:disabled { background: transparent; }

/* buttons */
QPushButton { min-height: 32px; padding: 0 14px; border-radius: 8px; border: 1px solid $input_border;
    background: $surface; }
QPushButton:hover { background: $hover; }
QPushButton#primary { background: $accent; border-color: $accent; color: $accent_text; font-weight: 600; }
QPushButton#primary:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton#primary:disabled { background: $accent_disabled; border-color: $accent_disabled; color: $accent_text; }
QPushButton#linkButton { min-height: 0; padding: 0; border: none; background: transparent; color: $accent;
    font-size: 13px; }
QPushButton#linkButton:hover { text-decoration: underline; background: transparent; }
QPushButton#swatch { min-width: 32px; max-width: 32px; padding: 0; }

/* inputs */
QLineEdit, QComboBox, QDoubleSpinBox { min-height: 32px; padding: 0 8px; border: 1px solid $input_border;
    border-radius: 8px; background: $surface; selection-background-color: $accent_soft; selection-color: $text; }
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus { border-color: $accent; }
QComboBox QAbstractItemView { background: $surface; border: 1px solid $border; selection-background-color: $accent_soft; }

/* start page */
QWidget#recentPane { background: $surface_alt; border-right: 1px solid $border; }
QLabel#sectionLabel { color: $text_muted; font-size: 12px; font-weight: 600; letter-spacing: 0.3px; }
QListWidget#recent { background: transparent; border: none; outline: none; }
QListWidget#recent::item { border-radius: 8px; padding: 2px; margin-bottom: 2px; }
QLabel#recentName { font-size: 13px; }
QListWidget#recent QLabel { background: transparent; }
QListWidget#recent::item:hover { background: $hover; }
QListWidget#recent::item:selected { background: $accent_soft; color: $accent; }
QLabel#title { font-size: 22px; font-weight: 600; }
QLabel#hint, QLabel#emptyState { color: $text_muted; font-size: 13px; }
QFrame#dropZone { background: $drop_bg; border: 1.5px dashed $drop_border; border-radius: 12px; }
QFrame#dropZone[active="true"] { border-color: $accent; background: $accent_soft; }
QLabel#dropTitle { font-weight: 600; }
QLabel#chip { background: $hover; color: $text_muted; border-radius: 12px; padding: 4px 10px; font-size: 13px; }

/* editor */
QListWidget#thumbs { background: $surface_alt; border: none; border-right: 1px solid $border; padding: 8px 6px; outline: none; }
QListWidget#thumbs::item { border-radius: 8px; padding: 6px 4px; margin-bottom: 4px; color: $text_muted; }
QListWidget#thumbs::item:selected { background: $accent_soft; color: $accent; }
QListWidget#thumbs::item:hover:!selected { background: $hover; }
QGraphicsView { border: none; background: $canvas; }
QWidget#fixesPanel { background: $surface; border-left: 1px solid $border; }
QScrollArea#fixesScroll, QWidget#fixesList { background: transparent; border: none; }
QFrame#fixCard { background: $surface; border: 1px solid $border; border-radius: 10px; }
QFrame#fixCard:hover { border-color: $accent; }
QFrame#fixCard[current="true"] { border-color: $accent; background: $accent_soft; }
QLabel#oldText { color: $text_faint; text-decoration: line-through; font-size: 13px; }
QLabel#newText { font-weight: 600; }
QLabel#cardMeta { color: $text_muted; font-size: 12px; }
QLabel#busyChip { background: $toast_bg; color: $toast_text; border-radius: 10px; padding: 4px 10px; font-size: 13px; }
QFrame#toast { background: $toast_bg; border-radius: 10px; }
QFrame#toast QLabel { color: $toast_text; font-size: 13px; }
QFrame#toast QPushButton#linkButton { color: $accent_soft; font-weight: 600; }
QStatusBar { background: $surface_alt; border-top: 1px solid $border; color: $text_muted; min-height: 24px; }
QStatusBar QLabel { color: $text_muted; padding: 0 8px; font-size: 12px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $input_border; border-radius: 4px; min-height: 30px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: $input_border; border-radius: 4px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

/* edit popover */
QFrame#editPopover { background: $surface; border: 1px solid $input_border; border-radius: 12px; }
QFrame#editPopover QLabel { color: $text_muted; font-size: 13px; }
QFrame#editPopover QLabel#warning { color: $danger; }
""")


def stylesheet(name: str) -> str:
    return _QSS.substitute(PALETTES[name])


def apply_theme(app, name: str) -> None:
    app.setStyleSheet(stylesheet(name))
    app.setProperty("themeName", name)


def current_theme(app) -> str:
    return app.property("themeName") or "light"


def saved_theme(settings) -> str:
    name = settings.value(THEME_KEY, "light")
    return name if name in PALETTES else "light"


def save_theme(settings, name: str) -> None:
    settings.setValue(THEME_KEY, name)
    settings.sync()


# Simple 24x24 line icons (stroke uses the theme's text colour).
ICONS: dict[str, str] = {
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "redo": '<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    "minus": '<path d="M5 12h14"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4'
           'M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    "moon": '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "upload": '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
}


def icon(name: str, color: str, size: int = 18) -> QIcon:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg>')
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    result = QIcon()
    for scale in (1, 2):  # crisp on high-DPI screens
        pm = QPixmap(QSize(size * scale, size * scale))
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        renderer.render(painter)
        painter.end()
        pm.setDevicePixelRatio(scale)
        result.addPixmap(pm)
    return result
