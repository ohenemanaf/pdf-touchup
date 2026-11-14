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
