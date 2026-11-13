# PDF Touch-up — Design

Date: 2026-11-13
Status: Draft, awaiting approval

## Why

Editing a PDF for free is hard: most editors (Adobe and similar sites) charge before you can change anything. Scanned documents are worse. When you only have a paper copy and scan it, every editor fails, because a scan is just a picture of a page with no text inside to edit.

PDF Touch-up is a free desktop app for **small text fixes** (a wrong name, date, figure or word) in both normal PDFs and scanned PDFs. The **result should look like the original page**. It's for the owner first, and for friends who download it from the owner's GitHub. There is no money for hosting, so it runs entirely on the user's computer.

## Goals

1. Open any PDF, whether it has real text or is a scan.
2. On scanned pages, find the words automatically (OCR) so the user can click one.
3. Let the user select a word or a run of words on one line, type the correction and see it in place.
4. Make the fix blend in: same position, a matching size and colour, the closest available font, and the original background (paper tone) behind it.
5. Actually remove the old text, not just hide it under a box, so it can't be copied or extracted afterwards.
6. Save as a new PDF. The original file is never overwritten silently.
7. Friends install it with one download: no Python, no Tesseract, nothing else.
8. Work fully offline. No documents ever leave the computer.

## Non-goals (v1)

- Signatures, form filling, adding/removing/reordering pages, merging or splitting files.
- Converting a whole document into an editable Word-style file (the "full rebuild" approach was rejected).
- Rewriting whole paragraphs or reflowing text across lines. Fixes stay on one line.
- Handwriting recognition.
- Languages other than English. (Tesseract supports more; adding a language pack later is easy.)
- Code signing (it costs money). Users accept the "unknown publisher" warning once.

## Anti-goals (failure even if it "works")

- The fix is obviously patched: a white box on cream paper, a wrong-size font, or misaligned text.
- Anything requires payment, an account, or uploading a document.
- A friend has to install Python or Tesseract, or use the command line.
- The old text can still be selected or extracted from the saved file.
- The user's original file gets damaged or overwritten without asking.

## Constraints

- Free and offline. Windows is the primary target and macOS is second (best effort).
- Python 3.12 (already installed on the owner's machine).
- **License:** PyMuPDF is AGPL, so the app's repo must be open source under AGPL-3.0. That fits a public GitHub download.
- UI must be compact and professional: about 14px text, 40px controls, no oversized "zoomed" look.

## Approaches considered

| Approach | Trade-off | Outcome |
|---|---|---|
| Browser app on GitHub Pages (pdf.js + pdf-lib + Tesseract.js) | Free hosting and nothing to install, but slower OCR in the browser and weaker text-replacement tools | Not chosen |
| Electron desktop app, installer on GitHub Releases | ~100+ MB, "unknown publisher" warning, JS PDF libraries are weaker at true text removal | Chosen at first, then dropped |
| **Python desktop app (PyMuPDF + Tesseract + PySide6), bundled installer on GitHub Releases** | Strongest PDF editing and OCR. Installer is ~80–120 MB, Tesseract must be bundled, unsigned-app warning | **Chosen by the owner** |

For the scanned-page job, two editing styles were weighed: a **touch-up** (patch the old words, keep the page looking like the scan) and a **full rebuild** (turn the page into a clean editable document). The owner chose touch-up.

## How it works (decided)

### Stack
- **PyMuPDF (fitz):** render pages, read text spans, redact (truly remove) content, insert new text, save.
- **Tesseract OCR**, bundled inside the app with English `tessdata`, called through PyMuPDF's OCR support or `pytesseract`.
- **PySide6 (Qt):** the desktop window.
- **PyInstaller:** produces a self-contained app. **Inno Setup** wraps it into a Windows `Setup.exe`. On macOS, a `.app` goes in a `.dmg`.
- **GitHub Actions:** on a version tag (`v*`), builds the Windows (and macOS) installers and attaches them to a GitHub Release. The README links to the latest release and explains "More info → Run anyway".

### User flow
```
┌ PDF Touch-up ─────────────────────────────────────────────┐
│ Open   Save as…   Undo  Redo        Page 2 / 5   − 100% + │
├──────────┬────────────────────────────────────────────────┤
│ [pg 1]   │                                                │
│ [pg 2]◀  │   Name:  [Kwame Mensah]  ← hover highlights    │
│ [pg 3]   │   Date:  12 March 2024      words; click to   │
│          │                             select            │
│          │   ┌ Edit ───────────────────────────┐          │
│          │   │ Kwame Mensah → [Kwame Asante  ] │          │
│          │   │ Font [Serif ▾] Size 11.5 ■ col  │          │
│          │   │            Cancel   Apply       │          │
│          │   └─────────────────────────────────┘          │
├──────────┴────────────────────────────────────────────────┤
│ Edits on this file: 2      Scanned page · text found      │
└───────────────────────────────────────────────────────────┘
```
1. **Open** a PDF. Pages show in a viewer with thumbnails.
2. For each page, the app checks whether it has a real text layer. If not (a scan), it runs OCR **on demand when the page is first viewed**, rendering at 300 DPI, and caches the word boxes for the session. A small status shows "Reading page…" and then "Scanned page · text found".
3. Hovering shows word outlines. Clicking selects a word, and shift-click or dragging extends the selection across neighbouring words on the **same line**.
4. An edit popover shows the current text (OCR result, editable if OCR misread it) and a field for the new text. It also shows the auto-detected font family, size and colour, all overridable. A live preview draws the replacement on the page before the user applies it.
5. **Apply** adds the edit to an edit list. Undo/redo works on that list.
6. **Save as…** writes a new PDF (default name `<original>-edited.pdf`). Edits are only burned into the file at save time.

### Making the fix blend in
- **Background:** sample the pixels in a thin ring just outside the selection box and use their median colour as the fill (this matches cream or grey paper, not pure white).
- **Removing the old text:**
  - On scans, use a PyMuPDF redaction with image-pixel redaction so the old word's pixels are replaced by the background colour inside the image itself.
  - On normal PDFs, use a redaction that removes the text spans.
- **Text colour:** the dominant dark colour of the pixels inside the original box (scans), or the span's colour (normal PDFs).
- **Size and position:** from the box height and baseline (scans), or from the span's size and origin (normal PDFs). The new text sits on the same baseline and starts at the same left edge.
- **Font:**
  - On normal PDFs, reuse the original font when it is embedded and contains the needed characters. Otherwise use the closest bundled font.
  - On scans, guess serif vs sans vs monospace and let the user switch.
  - Bundle free fonts that resemble the common document fonts: Liberation Serif/Sans/Mono (metric-compatible with Times New Roman, Arial and Courier New).
- **Width:** if the new text is roughly the same length as the old text, compress or stretch it slightly (within about ±10%) to fill the same width. Otherwise let it run naturally.

### Project layout (repo: `pdf-touchup`)
```
pdf_touchup/
  app.py            # entry point, main window
  viewer.py         # page rendering, zoom, word overlay, selection
  ocr.py            # Tesseract wrapper, word boxes, caching
  edits.py          # edit model, undo/redo, apply-at-save
  blend.py          # background/colour/size/font estimation
  fonts/            # bundled Liberation fonts
tests/              # pytest: blend estimation, edit apply, round-trip saves
packaging/          # PyInstaller spec, Inno Setup script
.github/workflows/release.yml
```

## Calls made without the owner (correct any of these)
- App name "PDF Touch-up", repo `pdf-touchup`, in `C:\Users\ohene\Projects\pdf-touchup`.
- English OCR only for v1.
- OCR runs per page on demand, not on the whole file up front, to keep big scans responsive.
- Edits are limited to one line at a time.
- Always "Save as" a new file. No in-place overwrite in v1.
- The repo is licensed AGPL-3.0 (required by PyMuPDF).
- Windows first. macOS builds are attempted in CI, but Windows is what has to work for v1.
- Liberation fonts are bundled for the closest match.

## Left to the builder
- PyMuPDF OCR integration vs calling `pytesseract` directly, whichever gives reliable word boxes with the bundled Tesseract.
- Exact heuristics and thresholds for serif/sans detection, colour clustering and width fitting, tuned against sample scans.
- Where the bundled Tesseract binary comes from for each OS and how PyInstaller picks it up.
- Test fixtures: a generated native PDF plus a generated "scan" (rendered to an image, with noise and a paper tint) for automated tests, and a few real phone/scanner scans for manual checks.
