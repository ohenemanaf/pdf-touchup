# PDF Touch-up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a free, offline Windows desktop app that makes small one-line text fixes in normal and scanned PDFs so the fix looks like the original, and ship it as a one-download installer on GitHub Releases.

**Architecture:** A pure-Python core (`document`, `text_source`, `ocr`, `selection`, `blend`, `style`, `edits`) does all PDF work with PyMuPDF and is fully unit-tested against generated fixture PDFs. A thin PySide6 UI (`viewer`, `edit_popover`, `app`) drives the core. Edits are kept as a list in memory and only burned into a fresh copy of the file on "Save as". PyInstaller + Inno Setup package the app with Tesseract and fonts bundled, and GitHub Actions builds releases on `v*` tags.

**Tech Stack:** Python 3.12, PyMuPDF ≥ 1.24, Tesseract 5 (English), numpy ≥ 1.26, PySide6 ≥ 6.7, pytest + pytest-qt, PyInstaller ≥ 6, Inno Setup 6, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-13-pdf-touchup-design.md`

## Global Constraints

- Free and offline: no network calls at runtime, no accounts, no uploads.
- English OCR only (`eng.traineddata`).
- Edits are confined to one line. Multi-line selections are rejected.
- Always "Save as" a new file. Saving onto the source path raises `ValueError`.
- Old text must be truly removed (text spans redacted and/or image pixels replaced), never only covered.
- Bundled fonts: Liberation Serif / Sans / Mono Regular (OFL), families keyed `"serif"`, `"sans"`, `"mono"`.
- Width fit: horizontal scale clamped to `0.90–1.10`, applied only when `0.8 ≤ len(new)/len(old) ≤ 1.25`, otherwise `1.0`.
- OCR render DPI = 300. OCR runs per page on first view and is cached for the session.
- License AGPL-3.0 (PyMuPDF). Repo name `pdf-touchup`, app name "PDF Touch-up".
- UI compact: ~14px body text, 40px controls, 10–14px radii, sentence-case buttons.
- Windows must work for v1. The macOS build is best-effort (`continue-on-error` in CI).
- Default output name `<original>-edited.pdf`.

## Review Focus

1. **"Searchable" scans** (scanner apps put an invisible text layer over the page image). Redacting only the text would leave the old word visible in the image. These pages must be treated as scans for removal and blending while reusing their text layer instead of OCR. → Task 2 `page_kind` test and Task 6 apply test.
2. **Rotated pages** (scans saved sideways with `/Rotate 90`). The fix must land where the old word was, upright. → Task 6 `test_apply_on_rotated_page`.
3. **Characters missing from the font** (e.g. `₵`, accented names). The app must not silently drop glyphs: fall back to the bundled family font, and if still missing, block Apply with a message. → Task 4 `missing_glyphs` test, Task 8 popover test.
4. **Long scans** (30+ pages). The UI must not freeze, and only viewed pages get OCR'd. → Task 3 cache-laziness test, Task 7 worker-thread test.
5. **Password-protected PDFs**. These need a prompt, not a crash. → Task 2 `NeedsPassword` test, Task 7 open-flow handling.

---

## File Structure

```
pyproject.toml                 # deps, pytest config, entry point
LICENSE                        # AGPL-3.0
README.md                      # what it is, download, "More info → Run anyway", dev setup
pdf_touchup/
  __init__.py
  __main__.py                  # python -m pdf_touchup
  resources.py                 # resource_dir(), tesseract_paths()
  model.py                     # Word, PageText, Style, Edit dataclasses
  document.py                  # open_document(), NeedsPassword, page_kind()
  text_source.py               # native_words(), PageTextCache
  ocr.py                       # ocr_words()
  selection.py                 # merge_selection(), SelectionError
  fonts.py                     # font_path(), load_font(), missing_glyphs()
  fonts/                       # Liberation*.ttf + OFL license
  blend.py                     # pixel estimation (bg, ink colour, size, family, width scale)
  style.py                     # detect_style()
  edits.py                     # EditList, apply_edits(), save_as(), render_with_edits()
  ui/viewer.py                 # PageView (QGraphicsView), word overlay, selection signals
  ui/edit_popover.py           # EditPopover widget
  ui/app.py                    # MainWindow, OCR worker, main()
  ui/style.qss                 # compact stylesheet
tests/
  conftest.py                  # fixture PDFs (native, scanned, searchable-scan, rotated, encrypted, multipage scan)
  test_document.py  test_text_source.py  test_ocr.py  test_selection.py
  test_fonts.py  test_blend.py  test_style.py  test_edits.py
  test_ui.py
packaging/
  pdf_touchup.spec             # PyInstaller
  installer.iss                # Inno Setup
.github/workflows/ci.yml       # tests on push
.github/workflows/release.yml  # build + release on v* tag
```

---

### Task 1: Project scaffold, models and test fixtures

**Files:**
- Create: `pyproject.toml`, `LICENSE`, `.gitignore`, `pdf_touchup/__init__.py`, `pdf_touchup/model.py`, `pdf_touchup/fonts/` (3 TTFs + `OFL.txt`), `tests/conftest.py`, `tests/test_fixtures.py`, `.github/workflows/ci.yml`

**Interfaces:**
- Produces (`pdf_touchup/model.py`, all `@dataclass(frozen=True)` except `Edit`):
  - `Rect = tuple[float, float, float, float]`  (x0, y0, x1, y1 in PDF points, page display space)
  - `RGB = tuple[float, float, float]`  (0–1 floats)
  - `Word(text: str, rect: Rect, line_id: tuple[int, int])`  (block_no, line_no)
  - `PageText(page_index: int, kind: str, words: list[Word])`  (`kind` ∈ `"native" | "scanned" | "searchable_scan"`)
  - `Style(family: str, size: float, color: RGB, background: RGB, h_scale: float = 1.0, font_buffer: bytes | None = None)`
  - `Edit(page_index: int, rect: Rect, old_text: str, new_text: str, style: Style, kind: str)`
- Produces (`tests/conftest.py`, pytest fixtures returning `pathlib.Path` in `tmp_path`):
  - `native_pdf`: A4, line 1 `"Name: Kwame Mensah"` at (72, 100) in Liberation Serif 11pt, black. Line 2 `"Date: 12 March 2024"` at (72, 120). Call `doc.subset_fonts()` before saving so the embedded font is a real subset, like most real-world PDFs.
  - `scanned_pdf`: `native_pdf` page 1 rendered at 200 DPI, background tinted to RGB (245, 240, 225), ink colour (40, 40, 60), Gaussian noise σ=4 (numpy, seed 0), inserted as a full-page image in a new A4 PDF. No text layer.
  - `searchable_scan_pdf`: `scanned_pdf` plus the same two lines inserted with `render_mode=3` (invisible) at the same positions.
  - `rotated_scan_pdf`: `scanned_pdf` with `page.set_rotation(90)`.
  - `encrypted_pdf`: `native_pdf` saved with user password `"secret"` (`encryption=fitz.PDF_ENCRYPT_AES_256`).
  - `multipage_scan_pdf`: 5 copies of the `scanned_pdf` page.

- [ ] **Step 1: Environment.** Create a venv (`py -3.12 -m venv .venv`). Install Tesseract for development with `winget install UB-Mannheim.TesseractOCR`, then confirm `& "C:\Program Files\Tesseract-OCR\tesseract.exe" --version` prints 5.x.
- [ ] **Step 2: `pyproject.toml`.** Project `pdf-touchup`, `requires-python = ">=3.12"`. Deps: `pymupdf>=1.24`, `numpy>=1.26`, `pyside6>=6.7`. Dev extra: `pytest`, `pytest-qt`, `pyinstaller>=6`. Script `pdf-touchup = "pdf_touchup.ui.app:main"`. Pytest marker `ocr: needs Tesseract`. Run `pip install -e .[dev]`. `.gitignore`: `.venv/ build/ dist/ __pycache__/ *.egg-info/ packaging/vendor/`.
- [ ] **Step 3: Fonts.** Download `liberation-fonts-ttf-2.1.5` from the github.com/liberationfonts/liberation-fonts releases. Copy `LiberationSerif-Regular.ttf`, `LiberationSans-Regular.ttf`, `LiberationMono-Regular.ttf` and the licence (as `OFL.txt`) into `pdf_touchup/fonts/`. Add the AGPL-3.0 text as `LICENSE`.
- [ ] **Step 4: Write failing tests** in `tests/test_fixtures.py`:
  - `test_native_fixture_has_text`: `"Kwame Mensah"` is in `page.get_text()`.
  - `test_scanned_fixture_has_no_text`: `page.get_text().strip() == ""` and `len(page.get_images()) == 1`.
  - `test_searchable_scan_has_text_and_image`: both are true.
  - `test_rotated_fixture`: `page.rotation == 90`.
  - `test_encrypted_fixture`: `fitz.open(p).needs_pass` is true.
- [ ] **Step 5:** Run `pytest tests/test_fixtures.py -v`. Expected: FAIL (fixtures not defined).
- [ ] **Step 6:** Implement `model.py` and the `conftest.py` fixtures as specified above.
- [ ] **Step 7:** Run `pytest -v`. Expected: 5 passed.
- [ ] **Step 8: CI.** Add `ci.yml`: windows-latest, Python 3.12, `choco install tesseract -y`, add `C:\Program Files\Tesseract-OCR` to PATH, `pip install -e .[dev]`, `pytest -v` (with `QT_QPA_PLATFORM=offscreen`).
- [ ] **Step 9: Commit** `chore: scaffold project, models, fixtures`. Push if a remote exists.

### Task 2: Opening documents, page kinds, native words, selection

**Files:**
- Create: `pdf_touchup/document.py`, `pdf_touchup/text_source.py` (native part), `pdf_touchup/selection.py`
- Test: `tests/test_document.py`, `tests/test_selection.py`, `tests/test_text_source.py`

**Interfaces:**
- Consumes: `Word`, `Rect` (Task 1).
- Produces:
  - `class NeedsPassword(Exception)`, `class WrongPassword(Exception)`
  - `open_document(path: Path, password: str | None = None) -> fitz.Document`
  - `page_kind(page: fitz.Page) -> str`: `"native"` when the page has visible text. `"scanned"` when it has no text and one image covering ≥ 80% of the page area. `"searchable_scan"` when it has such an image and all of its text spans have render mode 3 (invisible) or sit on top of that image. Determine visibility via `page.get_texttrace()` (`type` 3 means invisible).
  - `native_words(page: fitz.Page) -> list[Word]` from `page.get_text("words")`, with `line_id = (block_no, line_no)`.
  - `merge_selection(words: list[Word]) -> tuple[Rect, str]`: the union rect and the words joined by single spaces in reading (x) order. Raises `SelectionError` if `words` is empty or spans more than one `line_id`.

- [ ] **Step 1: Write failing tests:**
  - `test_open_plain` opens `native_pdf`.
  - `test_open_encrypted_requires_password`: `open_document(encrypted_pdf)` raises `NeedsPassword`, `password="nope"` raises `WrongPassword`, and `password="secret"` returns a doc whose `page_count == 1`.
  - `test_page_kind`: returns `"native"`, `"scanned"` and `"searchable_scan"` for the three fixtures respectively.
  - `test_native_words_finds_name`: the words include `"Kwame"` and `"Mensah"` with the same `line_id`, and `"Kwame"`'s rect x0 ≈ 72 + width("Name: ") (assert `rect[0] > 72`).
  - `test_merge_selection_joins_in_x_order`: passing `[Mensah, Kwame]` returns text `"Kwame Mensah"` and a rect that is the union of both.
  - `test_merge_selection_rejects_two_lines` raises `SelectionError`.
  - `test_merge_selection_rejects_empty` raises `SelectionError`.
- [ ] **Step 2:** Run `pytest tests/test_document.py tests/test_selection.py tests/test_text_source.py -v`. Expected: FAIL (import errors).
- [ ] **Step 3:** Implement the interfaces above.
- [ ] **Step 4:** Run the same command. Expected: all pass.
- [ ] **Step 5: Commit** `feat: open documents, classify pages, native words, selection`. Push.

### Task 3: OCR and the lazy page-text cache

**Files:**
- Create: `pdf_touchup/resources.py`, `pdf_touchup/ocr.py`
- Modify: `pdf_touchup/text_source.py` (add `PageTextCache`)
- Test: `tests/test_ocr.py`, `tests/test_text_source.py`

**Interfaces:**
- Consumes: `native_words`, `page_kind` (Task 2), `Word`, `PageText` (Task 1).
- Produces:
  - `resource_dir() -> Path`: `Path(sys._MEIPASS) / "pdf_touchup"` when `getattr(sys, "frozen", False)`, otherwise the package directory.
  - `tesseract_paths() -> tuple[Path, Path] | None`: returns `(tesseract_exe_dir, tessdata_dir)`. It checks these in order: frozen bundle `_MEIPASS/tesseract`, env `PDF_TOUCHUP_TESSERACT`, `shutil.which("tesseract")`, `C:\Program Files\Tesseract-OCR`. Returns `None` if none is found.
  - `class OcrUnavailable(Exception)`
  - `ocr_words(page: fitz.Page, dpi: int = 300) -> list[Word]`: prepend the exe dir to `PATH`, then call `page.get_textpage_ocr(dpi=dpi, full=True, language="eng", tessdata=str(tessdata_dir))` followed by `page.get_text("words", textpage=tp)`. Raises `OcrUnavailable` when `tesseract_paths()` is `None`.
  - `class PageTextCache`: `__init__(self, doc: fitz.Document, ocr: Callable[[fitz.Page], list[Word]] = ocr_words)` and `get(self, page_index: int) -> PageText`. Use `native_words` for `"native"` and `"searchable_scan"` pages and `ocr` for `"scanned"` pages, computed once per index.

- [ ] **Step 1: Write failing tests:**
  - `test_ocr_reads_scanned_name` (`@pytest.mark.ocr`, skip if `tesseract_paths()` is `None`): the `ocr_words` texts on `scanned_pdf` page 0 include `"Kwame"` and `"Mensah"` on the same `line_id`. Each word's rect is within 3pt of the matching word's rect from `native_words` on `native_pdf`.
  - `test_ocr_unavailable_raises`: monkeypatch `tesseract_paths` to return `None`, then `ocr_words` raises `OcrUnavailable`.
  - `test_cache_is_lazy_and_memoised`: on `multipage_scan_pdf` with a counting fake `ocr`, calling `get(2)` twice gives call count 1, and the page indices passed to the fake are `[2]`.
  - `test_cache_uses_text_layer_for_searchable_scan`: the fake `ocr` is never called, `kind == "searchable_scan"`, and the words include `"Kwame"`.
- [ ] **Step 2:** Run `pytest tests/test_ocr.py tests/test_text_source.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `resources.py`, `ocr.py` and `PageTextCache`.
- [ ] **Step 4:** Run the same command. Expected: all pass. The OCR test must run, not skip, on this machine.
- [ ] **Step 5: Commit** `feat: OCR via bundled Tesseract, lazy page-text cache`. Push.

### Task 4: Fonts and pixel blending estimates

**Files:**
- Create: `pdf_touchup/fonts.py`, `pdf_touchup/blend.py`
- Test: `tests/test_fonts.py`, `tests/test_blend.py`

**Interfaces:**
- Consumes: `resource_dir` (Task 3), `RGB` (Task 1).
- Produces (`fonts.py`):
  - `FAMILIES = ("serif", "sans", "mono")`
  - `font_path(family: str) -> Path`
  - `load_font(family: str | None = None, buffer: bytes | None = None) -> fitz.Font` (buffer wins when given)
  - `missing_glyphs(font: fitz.Font, text: str) -> list[str]` returns the distinct characters (not spaces) for which `font.has_glyph(ord(c)) == 0`.
- Produces (`blend.py`). All functions take `img: np.ndarray` (H×W×3 uint8, the page rendered at a known DPI) and `box: tuple[int, int, int, int]` (pixel coords):
  - `background_color(img, box, ring: int = 4) -> RGB`: per-channel median of the ring of pixels just outside `box`, clipped to the image.
  - `ink_color(img, box, background: RGB) -> RGB`: per-channel median of the pixels inside `box` whose luminance is in the darkest 20% and differs from the background luminance by > 0.15.
  - `font_size_pt(box_height_pt: float, text: str) -> float`: ratio 0.93 if `text` contains any of `gjpqy`, else 0.72 if it contains an uppercase letter, a digit or any of `bdfhklt`, else 0.50. Returns `round(box_height_pt / ratio, 1)`.
  - `guess_family(img, box, text: str, size_px: float, background: RGB) -> str`: for each family, render `text` with `fitz` (via a `Pixmap` of a temporary page) at `size_px`, scale it to the box size, and compute the normalised cross-correlation with the grayscale crop. Return the family with the highest score.
  - `width_scale(old_text: str, new_text: str, font: fitz.Font, size: float, box_width_pt: float) -> float`: returns `1.0` unless `0.8 ≤ len(new)/len(old) ≤ 1.25`. In that case it returns `box_width_pt / font.text_length(new_text, size)` clamped to `[0.90, 1.10]`.

- [ ] **Step 1: Write failing tests:**
  - `test_font_paths_exist` covers all 3 families.
  - `test_missing_glyphs`: `missing_glyphs(load_font("serif"), "Kwame") == []`. A char that Liberation lacks (pick one by probing `has_glyph`, e.g. `"₵"` if absent, else `"𝔄"`) appears in the result.
  - `test_background_color_on_scan`: render `scanned_pdf` at 200 DPI and take the box of `"Kwame"`. The result is within 0.03 of (245, 240, 225)/255 per channel.
  - `test_ink_color_on_scan`: within 0.08 of (40, 40, 60)/255.
  - `test_font_size_ratios`: `font_size_pt(9.3, "gyp") == 10.0`, `font_size_pt(7.2, "Kwame") == 10.0`, `font_size_pt(5.0, "ace") == 10.0`.
  - `test_guess_family_serif`: on `scanned_pdf` (rendered in Liberation Serif) for `"Mensah"`, the result is `"serif"`. Add a sans fixture variant inline (Liberation Sans) and assert `"sans"`.
  - `test_width_scale_clamps`: returns 1.0 for a 2× longer replacement, and stays within [0.90, 1.10] for `"Mensah"` → `"Asante"`.
- [ ] **Step 2:** Run `pytest tests/test_fonts.py tests/test_blend.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `fonts.py` and `blend.py`.
- [ ] **Step 4:** Run the same command. Expected: all pass.
- [ ] **Step 5: Commit** `feat: bundled fonts and blending estimates`. Push.

### Task 5: Style detection

**Files:**
- Create: `pdf_touchup/style.py`
- Test: `tests/test_style.py`

**Interfaces:**
- Consumes: `blend.*`, `fonts.load_font`, `fonts.missing_glyphs` (Task 4), `Style`, `Rect` (Task 1).
- Produces: `detect_style(page: fitz.Page, rect: Rect, old_text: str, new_text: str, kind: str) -> Style`
  - **For `"native"` pages:** take the first span from `page.get_text("dict")` whose bbox intersects `rect`, and read its size and colour from that span. `background` is `background_color` from a 150 DPI render. `family` maps from the span font name: contains `"Courier"`/`"Mono"` → mono; contains `"Arial"`/`"Helvetica"`/`"Sans"` → sans; otherwise serif. Set `font_buffer` to the embedded font bytes (`doc.extract_font(xref)`, matching the span font name against `page.get_fonts()` basefont with the subset prefix `ABCDEF+` stripped) only when `missing_glyphs` for `new_text` is empty.
  - **For scanned / searchable pages:** render at 300 DPI, convert `rect` to pixel box, then compute `background_color`, `ink_color`, `font_size_pt` and `guess_family`.
  - **For all kinds:** `h_scale = width_scale(...)` using the chosen font.

- [ ] **Step 1: Write failing tests:**
  - `test_native_style`: on the `native_pdf` rect of `"Kwame Mensah"`, size is 11.0 ± 0.1, colour ≈ black, family `"serif"`, background ≈ white.
  - `test_native_reuses_embedded_font_when_glyphs_present`: `font_buffer is not None` for new text `"Kwame Asante"`.
  - `test_native_drops_embedded_font_when_glyph_missing`: `font_buffer is None` when new text contains a char absent from the subset (e.g. `"Zz"` if `"Z"` was not in the fixture text).
  - `test_scanned_style`: size 11.0 ± 1.0, family `"serif"`, background ≈ cream (tolerance 0.03), ink ≈ (40, 40, 60)/255 (tolerance 0.08).
- [ ] **Step 2:** Run `pytest tests/test_style.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `detect_style`.
- [ ] **Step 4:** Run the same command. Expected: all pass.
- [ ] **Step 5: Commit** `feat: detect replacement style for native and scanned text`. Push.

### Task 6: Edit list, applying edits, saving and preview

**Files:**
- Create: `pdf_touchup/edits.py`
- Test: `tests/test_edits.py`

**Interfaces:**
- Consumes: `Edit`, `Style` (Task 1), `load_font` (Task 4), `open_document` (Task 2).
- Produces:
  - `class EditList`: `add(e: Edit)`, `undo() -> Edit | None`, `redo() -> Edit | None`, `items() -> list[Edit]`, `can_undo: bool`, `can_redo: bool`, `changed` callback slot (`on_change: Callable[[], None] | None`). Calling `add` clears the redo stack.
  - `apply_edits(doc: fitz.Document, edits: list[Edit]) -> None`. Per page:
    1. Add a redact annot for each edit with `fill=style.background`.
    2. Call `apply_redactions` once, with `images=fitz.PDF_REDACT_IMAGE_PIXELS` if any edit on the page has kind `"scanned"`/`"searchable_scan"`, else `fitz.PDF_REDACT_IMAGE_NONE`, plus `text=fitz.PDF_REDACT_TEXT_REMOVE`.
    3. Insert each `new_text` at the original baseline (left = `rect.x0`, baseline ≈ `rect.y1 − descent`) with `color=style.color`, `fontsize=style.size`, the font from `font_buffer` or the family, and horizontal scale `style.h_scale` via `morph=(origin, fitz.Matrix(h_scale, 1))`. The rotation must be correct on rotated pages (use the page's derotation matrix / `rotate=page.rotation`).
  - `save_as(source: Path, edits: list[Edit], out: Path, password: str | None = None) -> None`: raises `ValueError` if `out.resolve() == source.resolve()`. Opens a fresh copy, applies the edits, then saves with `garbage=3, deflate=True`.
  - `default_output_path(source: Path) -> Path` returns `<stem>-edited.pdf` in the same folder.
  - `render_with_edits(doc: fitz.Document, page_index: int, edits: list[Edit], zoom: float) -> fitz.Pixmap`: copies the single page into a temporary doc (`insert_pdf`), applies that page's edits (re-indexed to 0) and renders. The source `doc` is never mutated.

- [ ] **Step 1: Write failing tests** (use `detect_style` to build each `Edit`):
  - `test_editlist_undo_redo`: add a, add b, undo → b, redo → b, add c clears redo, and `can_redo is False`.
  - `test_native_edit_replaces_text`: after `save_as`, the output text contains `"Kwame Asante"` and not `"Mensah"`. The new `"Asante"` word rect's y-centre is within 1.5pt of the old one.
  - `test_scanned_edit_removes_pixels`: render the output page and crop the old `"Mensah"` box. The pixels outside the new text's ink are within 0.05 of the cream background. The OCR of the output (marked `ocr`) contains `"Asante"` and not `"Mensah"`.
  - `test_searchable_scan_edit_removes_both`: the output text layer has no `"Mensah"`, and the image pixels in the old box are background (same check as above).
  - `test_apply_on_rotated_page`: the OCR (`ocr` marker) of the output finds `"Asante"`, its rect overlaps the old `"Mensah"` rect, and `"Mensah"` is absent.
  - `test_save_as_refuses_overwrite`: `save_as(p, [], p)` raises `ValueError`.
  - `test_default_output_path`: `C:/x/form.pdf` → `C:/x/form-edited.pdf`.
  - `test_render_with_edits_does_not_mutate`: the source page text is unchanged after rendering.
  - `test_encrypted_save`: `save_as(encrypted_pdf, [edit], out, password="secret")` produces a readable output.
- [ ] **Step 2:** Run `pytest tests/test_edits.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `edits.py`.
- [ ] **Step 4:** Run `pytest -v`. Expected: the whole suite passes.
- [ ] **Step 5: Commit** `feat: apply edits with true removal, save as, preview`. Push.

### Task 7: Main window and page viewer

**Files:**
- Create: `pdf_touchup/__main__.py`, `pdf_touchup/ui/__init__.py`, `pdf_touchup/ui/viewer.py`, `pdf_touchup/ui/app.py`, `pdf_touchup/ui/style.qss`
- Test: `tests/test_ui.py`

**Interfaces:**
- Consumes: `open_document`, `NeedsPassword`, `WrongPassword` (Task 2), `PageTextCache`, `OcrUnavailable` (Task 3), `merge_selection` (Task 2), `render_with_edits`, `EditList` (Task 6).
- Produces:
  - `class PageView(QGraphicsView)`: `show_page(pixmap: QPixmap, words: list[Word], zoom: float)`, `set_busy(text: str | None)`. Signal `selection_changed(list[Word])`. Hovering outlines a word. Click selects it. Shift-click or drag adds words, only from the same line as the first word (other words are ignored).
  - `class MainWindow(QMainWindow)`:
    - Toolbar: Open, Save as…, Undo, Redo, page indicator, zoom −/+ (50–300%, step 25%).
    - Left thumbnail list (`QListWidget`, 120px wide).
    - Status bar: edit count and page status (`"Normal page"`, `"Reading page…"`, `"Scanned page · text found"`, `"Scanned page · no text found"`, or `"Text reader missing — reinstall the app"` on `OcrUnavailable`).
    - Methods: `open_path(path: Path)`, `go_to_page(i: int)`.
    - OCR runs in a `QThreadPool` worker per page, and the result is delivered back to the GUI thread via a signal.
    - Open flow: on `NeedsPassword`, show a `QInputDialog` password prompt. On `WrongPassword`, re-prompt with "Wrong password", and cancel aborts.
    - The window title shows the file name, with `*` while unsaved edits exist. Closing with unsaved edits asks Save / Discard / Cancel.
  - `main() -> None`: creates the `QApplication`, loads `style.qss` and shows `MainWindow`. An optional argv[1] path is opened.
  - `style.qss`: 14px base font, 40px-high buttons/inputs, 10px radii, neutral greys with a single accent `#2F6FEB`.

- [ ] **Step 1: Write failing tests** (pytest-qt, `QT_QPA_PLATFORM=offscreen`):
  - `test_open_native_shows_words`: `open_path(native_pdf)` leads to a status of `"Normal page"` and `PageView` holding ≥ 6 word items.
  - `test_ocr_runs_off_gui_thread`: inject a fake slow `ocr` (sleeps 0.5s, records `threading.current_thread()`). `open_path(scanned_pdf)` returns in < 0.2s, the status shows `"Reading page…"`, then `qtbot.waitUntil` sees `"Scanned page · text found"`, and the recorded thread is not the main thread.
  - `test_selection_stays_on_one_line`: simulate click on `"Kwame"` then shift-click on `"March"` (line 2). `selection_changed` last emits `["Kwame"]` only.
  - `test_password_prompt`: monkeypatch `QInputDialog.getText` to return `("secret", True)`, then `open_path(encrypted_pdf)` opens it.
- [ ] **Step 2:** Run `pytest tests/test_ui.py -v`. Expected: FAIL.
- [ ] **Step 3:** Implement the viewer, window, `__main__.py` and stylesheet. Allow `MainWindow(ocr=...)` injection for the test.
- [ ] **Step 4:** Run `pytest -v`. Expected: all pass.
- [ ] **Step 5: Manual check.** Run `python -m pdf_touchup tests-out\scanned.pdf`, or any real phone scan. The page shows, "Reading page…" appears and the UI stays responsive while scrolling thumbnails, then words highlight on hover.
- [ ] **Step 6: Commit** `feat: main window, page viewer, background OCR`. Push.

### Task 8: Edit popover and the full edit/save flow

**Files:**
- Create: `pdf_touchup/ui/edit_popover.py`
- Modify: `pdf_touchup/ui/app.py`
- Test: `tests/test_ui.py`

**Interfaces:**
- Consumes: `detect_style` (Task 5), `missing_glyphs`, `load_font`, `FAMILIES` (Task 4), `EditList`, `render_with_edits`, `save_as`, `default_output_path` (Task 6), `PageView.selection_changed` (Task 7).
- Produces: `class EditPopover(QFrame)` with:
  - Fields: `old_text: QLineEdit` (prefilled, editable, for fixing OCR misreads), `new_text: QLineEdit`, `family: QComboBox` (Serif / Sans / Mono, plus "Original font" when `font_buffer` is set), `size: QDoubleSpinBox` (4–72, step 0.5), and a colour swatch button (`QColorDialog`).
  - Signals: `preview_requested(Edit)` (debounced 200ms on any change) and `applied(Edit)`. `cancelled()`.
  - The Apply button is disabled while `new_text` is empty, and also while `missing_glyphs` for the chosen font is non-empty. In that case a red caption reads `"This font can't show: ₵"` (listing the characters).
  - It is positioned just below the selection, kept inside the viewport.

- [ ] **Step 1: Write failing tests:**
  - `test_apply_flow_native`: select `"Kwame Mensah"`, type `"Kwame Asante"` and Apply. The edit count is 1, the title has `*`, the viewer pixmap differs from before Apply, and Undo restores the count to 0 and the original pixmap.
  - `test_apply_disabled_for_missing_glyph`: new text containing the char from Task 4's missing-glyph test leaves `apply_button.isEnabled()` false and shows the caption text.
  - `test_save_as_flow`: monkeypatch `QFileDialog.getSaveFileName` → `(str(tmp/"out.pdf"), "")`. Apply one edit, trigger Save as, and `out.pdf` text contains `"Asante"`. The title loses `*`, and the source file bytes are unchanged.
  - `test_save_as_rejects_source_path`: the dialog returns the source path, a warning `QMessageBox` is shown (monkeypatched) and nothing is written.
- [ ] **Step 2:** Run `pytest tests/test_ui.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3:** Implement `EditPopover` and wire it into `MainWindow`: selection → `merge_selection` → `detect_style` → popover → preview via `render_with_edits` on the current page (applied edits plus the pending one) → `EditList.add`. Undo/Redo actions use `Ctrl+Z` / `Ctrl+Y`. Save as uses `default_output_path` as the dialog default.
- [ ] **Step 4:** Run `pytest -v`. Expected: all pass.
- [ ] **Step 5: Manual check** on one real scanned document and one real normal PDF. Fix a name and a date on each and save. Open the output in a normal PDF viewer: the fix blends in, and Ctrl+F for the old word finds nothing.
- [ ] **Step 6: Commit** `feat: edit popover, preview, undo/redo, save as`. Push.

### Task 9: Packaging, installer and release workflow

**Files:**
- Create: `packaging/pdf_touchup.spec`, `packaging/installer.iss`, `packaging/fetch_tesseract.ps1`, `.github/workflows/release.yml`, `README.md`
- Test: manual install check (below) plus a CI smoke step

**Interfaces:**
- Consumes: `resource_dir`, `tesseract_paths` (Task 3), `main` (Task 7).
- Produces: `dist/PDF-Touchup-Setup-<version>.exe` (Windows) and `dist/PDF-Touchup-<version>.dmg` (macOS, best effort), attached to the GitHub Release for the tag.

- [ ] **Step 1:** `fetch_tesseract.ps1` copies `tesseract.exe`, its DLLs and `tessdata/eng.traineddata` (and `osd.traineddata`) from `C:\Program Files\Tesseract-OCR` into `packaging/vendor/tesseract/` (gitignored).
- [ ] **Step 2:** PyInstaller spec, one-dir, windowed:
  - Entry: `pdf_touchup/__main__.py`.
  - `datas`: `pdf_touchup/fonts`, `pdf_touchup/ui/style.qss` and `packaging/vendor/tesseract` → `tesseract`.
  - Name: `PDF Touch-up`.
  - Version is read from the `PDF_TOUCHUP_VERSION` env var.
- [ ] **Step 3: Frozen smoke test.** Add a hidden `--self-test <pdf>` flag in `__main__.py`. It runs `PageTextCache(open_document(p)).get(0)` and exits 0 if the words include `"Kwame"`, else 1. Build with `pyinstaller packaging/pdf_touchup.spec`, then run `dist\PDF Touch-up\PDF Touch-up.exe --self-test <scanned fixture>` **from a shell where Tesseract is not on PATH** (temporarily rename `C:\Program Files\Tesseract-OCR`, or use a clean CI runner). Expected: exit code 0.
- [ ] **Step 4: Inno Setup.** The `installer.iss` script does the following:
  - Per-user install into `{localappdata}\Programs\PDF Touch-up`, no admin needed.
  - Start menu and optional desktop shortcut.
  - "Open with" association for `.pdf` (opt-in checkbox, off by default).
  - Uninstaller.
  - Output `PDF-Touchup-Setup-{version}.exe`.
- [ ] **Step 5: `release.yml`.** On push of tag `v*`:
  - **Windows job:** `choco install tesseract innosetup -y`, then fetch_tesseract, pyinstaller, iscc, the `--self-test` step and uploading the setup exe.
  - **macOS job** (`continue-on-error: true`): `brew install tesseract`, copy the binary, dylibs and tessdata into vendor, run pyinstaller, then `hdiutil create` the dmg.
  - **Release job:** `softprops/action-gh-release@v2` attaches the artifacts.
- [ ] **Step 6: README.** Plain language:
  - What the app does (small fixes on normal and scanned PDFs, offline, free).
  - A download link to Releases/latest.
  - The "Windows protected your PC → More info → Run anyway" note with the reason (the app isn't paid-signed).
  - Limits (one line per fix, English scans, no handwriting).
  - Developer setup (venv, winget Tesseract, `pip install -e .[dev]`, `pytest`).
  - AGPL licence and font credits.
- [ ] **Step 7: Manual install check.** Run the built Setup.exe, launch from the Start menu, open a real scan, fix a word and save. Then uninstall cleanly.
- [ ] **Step 8: Commit** `build: PyInstaller bundle, installer, release workflow`. Push. Tagging `v0.1.0` is done only after the owner says so.
