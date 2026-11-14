# PDF Touch-up

Free, offline app for **small text fixes in PDFs**, including **scanned** pages. Fix a wrong
name, date, figure or word, and the fix blends in with the page.

- Works on normal PDFs and on scans of paper documents. On scans it reads the words for you (OCR).
- Matches the paper colour, ink colour, size and the closest font, so the page still looks original.
- The old text is truly removed, not just covered up.
- Always saves a **new** file (`yourfile-edited.pdf`). Your original is never changed.
- Free, no account, nothing uploaded. Everything stays on your computer.

## Download

Get the latest **`PDF-Touchup-Setup-x.y.z.exe`** from the
[Releases page](../../releases/latest), run it, and open **PDF Touch-up** from the Start menu.

> **"Windows protected your PC"?** Click **More info → Run anyway**. The warning appears
> because the app isn't signed with a paid certificate. It isn't a sign that anything is wrong.
> You only see it once.

## How to fix something

1. **Open** a PDF.
2. Click the word you want to change. Shift-click or drag to take more words **on the same line**.
3. Type the correction in the box that appears. The page previews it straight away.
4. **Apply**, then **Save as…** to write a fixed copy.

Undo and redo work until you save (Ctrl+Z / Ctrl+Y).

## Limits (version 1)

- One line per fix (no rewriting paragraphs).
- Scans are read in English. Handwriting isn't supported.
- No signatures, forms, page changes or merging yet.

## For developers

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
winget install UB-Mannheim.TesseractOCR   # OCR language data for development
pip install -e .[dev]
pytest
python -m pdf_touchup                     # run the app
```

Building the installer locally:

```powershell
./packaging/fetch_tessdata.ps1
pyinstaller packaging/pdf_touchup.spec --noconfirm --distpath dist --workpath build/pyi
iscc /DAppVersion=0.1.0 packaging\installer.iss
```

Pushing a tag such as `v0.1.0` makes GitHub Actions build the installer and publish a release.

## Licence

AGPL-3.0 (see `LICENSE`), because the app uses [PyMuPDF](https://pymupdf.readthedocs.io).
Bundled fonts: [Liberation Fonts](https://github.com/liberationfonts/liberation-fonts) (SIL OFL, `pdf_touchup/fonts/OFL.txt`).
OCR language data: [Tesseract](https://github.com/tesseract-ocr/tessdata) (Apache-2.0).
