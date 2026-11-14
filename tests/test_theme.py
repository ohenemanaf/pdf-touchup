from PySide6.QtWidgets import QApplication

from pdf_touchup.ui.theme import ICONS, PALETTES, apply_theme, icon, save_theme, saved_theme, stylesheet


def test_stylesheet_uses_tokens():
    light, dark = stylesheet("light"), stylesheet("dark")
    assert PALETTES["light"]["accent"].lower() == "#2f6feb"
    assert "#2f6feb" in light.lower()
    assert PALETTES["light"]["bg"] in light and PALETTES["dark"]["bg"] in dark
    assert PALETTES["light"]["bg"] != PALETTES["dark"]["bg"]
    assert "$" not in light and "$" not in dark  # every token was filled in


def test_icons_render(qtbot):
    for name in ICONS:
        assert not icon(name, "#1f2329").pixmap(18, 18).isNull(), name


def test_theme_persists(settings):
    assert saved_theme(settings) == "light"  # default
    save_theme(settings, "dark")
    assert saved_theme(settings) == "dark"


def test_dark_theme_keeps_page_untinted(qtbot, settings, native_pdf):
    from pdf_touchup.ui.app import MainWindow

    apply_theme(QApplication.instance(), "dark")
    try:
        w = MainWindow(settings=settings)
        w.show()
        w.open_path(native_pdf)
        img = w.view.current_pixmap().toImage()
        assert img.pixelColor(2, 2).name() == "#ffffff"
        w._saved_version = w.edits.version
        w.close()
    finally:
        apply_theme(QApplication.instance(), "light")


def test_theme_switch_recolours_page_background(qtbot, settings, native_pdf):
    from pdf_touchup.ui.app import MainWindow

    app = QApplication.instance()
    apply_theme(app, "light")
    w = MainWindow(settings=settings)
    try:
        w.show()
        assert w.view.backgroundBrush().color().name() == PALETTES["light"]["canvas"]
        w.toggle_theme()
        assert w.view.backgroundBrush().color().name() == PALETTES["dark"]["canvas"]
        assert saved_theme(settings) == "dark"
    finally:
        apply_theme(app, "light")
        w.close()


def _contrast(a, b):
    def lum(c):
        def ch(v):
            v /= 255
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


import pytest  # noqa: E402


@pytest.mark.parametrize("theme,os_bg", [("light", "#1e1e1e"), ("dark", "#f0f0f0")])
def test_dialog_text_readable_whatever_the_windows_theme(qtbot, theme, os_bg):
    """Message boxes must get the theme's background too, not just its text colour: in light theme
    on dark-mode Windows the unsaved-fixes prompt was dark text on a dark background."""
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QMessageBox

    app = QApplication.instance()
    old = app.palette()
    pal = QPalette(old)
    for role in (QPalette.Window, QPalette.Base, QPalette.Button):
        pal.setColor(role, QColor(os_bg))  # pretend the OS theme is the opposite one
    app.setPalette(pal)
    try:
        apply_theme(app, theme)
        box = QMessageBox(QMessageBox.Question, "PDF Touch-up", "You have unsaved fixes. Save them first?")
        qtbot.addWidget(box)
        box.show()
        img = box.grab().toImage()
        bg = img.pixelColor(3, 3)
        assert _contrast(bg, QColor(PALETTES[theme]["text"])) >= 4.5, (bg.name(), theme)
    finally:
        app.setPalette(old)
        apply_theme(app, "light")
