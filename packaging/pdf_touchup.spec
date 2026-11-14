# PyInstaller spec: one-folder, windowed build with fonts, stylesheet and OCR data bundled.
# Build from the repo root:  pyinstaller packaging/pdf_touchup.spec --noconfirm
from pathlib import Path

ROOT = Path(SPECPATH).parent
PKG = ROOT / "pdf_touchup"

a = Analysis(
    [str(PKG / "__main__.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(PKG / "fonts"), "pdf_touchup/fonts"),
        (str(PKG / "ui" / "style.qss"), "pdf_touchup/ui"),
        (str(PKG / "tessdata"), "pdf_touchup/tessdata"),
    ],
    hiddenimports=["pdf_touchup.ocr", "pdf_touchup.selftest"],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtQml", "PySide6.QtQuick",
              "PySide6.QtMultimedia", "PySide6.Qt3DCore", "PySide6.QtCharts"],
    noarchive=False,
)
# Drop parts of Qt and PyMuPDF the app never uses (~100 MB).
UNUSED = ("opengl32sw.dll", "qt6quick", "qt6qml", "qt6pdf", "qt6virtualkeyboard", "qt6network",
          "qtvirtualkeyboardplugin", "imageformats/qpdf", "pyside6/translations", "plugins/tls",
          "plugins/networkinformation", "pymupdf/layout", "pymupdf/mupdf-devel")


def _keep(entry):
    name = entry[0].replace("\\", "/").lower()
    return not any(u in name for u in UNUSED)


a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]
a.pure = [m for m in a.pure if not m[0].startswith("pymupdf.layout")]

pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PDFTouchup",
          console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="PDFTouchup", upx=False)
app = BUNDLE(coll, name="PDF Touch-up.app", bundle_identifier="io.github.pdftouchup") \
    if __import__("sys").platform == "darwin" else None
