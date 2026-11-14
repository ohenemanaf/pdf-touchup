# UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give PDF Touch-up a clean, professional (style B) start screen and an editor with a fixes panel, drag-and-drop, toasts, shortcuts and light/dark themes.

**Architecture:** Keep the core untouched apart from an undoable `EditList.remove`. Split the UI into small widgets: `theme.py` (palette → QSS, icons), `recent.py` (recent files in QSettings), `start_page.py`, `fixes_panel.py`, `toast.py`. `MainWindow` hosts a `QStackedWidget` (start | editor) and wires them together.

**Tech Stack:** Python 3.12, PySide6, pytest-qt.

**Spec:** `docs/superpowers/specs/2026-11-14-ui-redesign-design.md`

## Global Constraints

- Compact sizing: base font 14 px (13 px secondary), controls 32–36 px high, radii 8–12 px, sentence-case labels, a single accent `#2F6FEB`.
- The light theme is the default. The theme choice persists in `QSettings("PDF Touch-up", "PDF Touch-up")`, key `theme`.
- Recent files persist in the same QSettings under key `recent`: a JSON list of `{path, kind, opened_at}`, newest first, at most 8, and missing files are dropped on read.
- Tests must not touch the real user settings. A `settings` fixture points QSettings to a temporary INI file.
- Existing behaviour stays: background OCR, the unsaved-fixes prompt, "Save as" never overwriting the source.

## Review Focus

1. **Per-fix Undo, then Ctrl+Z, then Ctrl+Y** must round-trip exactly. → Task 1 `test_remove_is_undoable`.
2. **Recent file deleted or moved** must disappear from the list and not crash. → Task 1 `test_recent_drops_missing_files`.
3. **Dropping a non-PDF or several files**: show a message and open nothing. → Task 3 `test_drop_non_pdf_shows_message`.
4. **Closing with unsaved fixes from the editor page** must still prompt. → existing tests keep passing.
5. **Dark theme**: the PDF page itself is never tinted. → Task 2 `test_dark_theme_keeps_page_untinted`.

---

### Task 1: Undoable remove, recent files

**Files:** Modify `pdf_touchup/edits.py`. Create `pdf_touchup/ui/recent.py`. Test `tests/test_edits.py`, `tests/test_recent.py`, `tests/conftest.py` (add the `settings` fixture).

**Interfaces:**
- `EditList.remove(edit: Edit) -> None`: undoable. `items()` leaves out removed fixes. `undo()` restores the fix and `redo()` removes it again. `on_change` and `version` behave as for `add`.
- `RecentFiles(settings: QSettings)`, with `add(path: Path, kind: str) -> None`, `items() -> list[RecentFile]` and `clear()`. `RecentFile` is a dataclass with `path`, `kind` and `opened_at` (datetime).
- `relative_day(when: datetime, now: datetime) -> str` returns "today", "yesterday", "3 days ago" or "12 Mar".

- [ ] Write failing tests: `test_remove_is_undoable`, `test_remove_after_replace_chain`, `test_recent_keeps_newest_first_max_8`, `test_recent_moves_reopened_file_to_top`, `test_recent_drops_missing_files`, `test_relative_day`. Run them and confirm they FAIL.
- [ ] Implement. Store `EditList` history as ops (`("add", e)` / `("remove", e)`) and keep the existing public API.
- [ ] Run the full `pytest` → PASS. Commit `feat: undoable per-fix remove; recent files store`, then push.

### Task 2: Theme and icons

**Files:** Create `pdf_touchup/ui/theme.py`. Delete `pdf_touchup/ui/style.qss` (generated now) and update `pyproject.toml` package-data and `packaging/pdf_touchup.spec` datas. Test `tests/test_theme.py`.

**Interfaces:**
- `PALETTES: dict[str, dict[str, str]]` with keys `"light"` and `"dark"`. Tokens: `bg`, `surface`, `surface_alt`, `border`, `text`, `text_muted`, `accent`, `accent_hover`, `accent_soft`, `canvas`, `danger`, `success`, `success_soft`.
- `stylesheet(name: str) -> str` (QSS).
- `icon(name: str, color: str, size: int = 18) -> QIcon` from inline SVG, for `undo`, `redo`, `minus`, `plus`, `sun`, `moon`, `file`, `folder`, `upload`.
- `apply_theme(app: QApplication, name: str) -> None`, `saved_theme(settings) -> str` and `save_theme(settings, name)`.

- [ ] Write failing tests: `test_stylesheet_uses_tokens` (light has `#2F6FEB` and `bg`; dark's `bg` differs), `test_icons_render` (non-null pixmap for every name), `test_theme_persists`, `test_dark_theme_keeps_page_untinted` (render a page in a dark-themed window: the page pixmap's corner pixel is still the PDF's white). Run → FAIL.
- [ ] Implement. Move the rules from `style.qss` into the template using tokens.
- [ ] Run → PASS. Commit `feat: light/dark themes and icons`, then push.

### Task 3: Start page, drag-and-drop, stacked window

**Files:** Create `pdf_touchup/ui/start_page.py`. Modify `pdf_touchup/ui/app.py`. Test `tests/test_ui.py`.

**Interfaces:**
- `StartPage(QWidget)` with signals `open_requested()` and `recent_chosen(Path)`, and `set_recent(items: list[RecentFile])`. It shows the header, title, hint, drop zone, step chips and recent list (empty state: "No recent files yet").
- `MainWindow`:
  - `stack: QStackedWidget` (0 = start, 1 = editor) and `settings: QSettings` (injectable: `MainWindow(ocr=None, settings=None)`).
  - The window shows the start page until a file opens. `open_path` records the file in recent.
  - Window-level `dragEnterEvent`/`dropEvent` accept a single `.pdf`. Anything else shows "Drop one PDF file to open it."
- [ ] Write failing tests: `test_starts_on_start_page`, `test_open_records_recent_and_shows_editor`, `test_recent_click_opens_file`, `test_drop_pdf_opens_it` (send a `QDropEvent` with mime urls), `test_drop_non_pdf_shows_message`. Run → FAIL.
- [ ] Implement.
- [ ] Run the full `pytest` → PASS. Take a screenshot of the start page in light and dark (real Windows platform, window off-screen) and check it visually. Commit `feat: start screen with recent files and drag-and-drop`, then push.

### Task 4: Editor header, fixes panel, thumbnail badges

**Files:** Create `pdf_touchup/ui/fixes_panel.py`. Modify `pdf_touchup/ui/app.py`. Test `tests/test_ui.py`.

**Interfaces:**
- `FixesPanel(QWidget)` with `set_fixes(edits: list[Edit])`, signal `jump_requested(Edit)` and signal `remove_requested(Edit)`. Each card shows struck old text, then new text, then "Page n · Undo". Empty state: "Click any word on the page to fix it."
- Editor header: file name label, kind label ("Scanned"/"Typed"/"Mixed"), page count, undo/redo icon buttons, zoom −/%/+, theme toggle button and a primary "Save copy" button. The old `QToolBar` is replaced; the existing actions (`open_action`, `save_action`, `undo_action`, `redo_action`) are kept for shortcuts and tests.
- Thumbnail badges: thumbnails are redrawn with a blue count badge when the fixes change.
- [ ] Write failing tests: `test_fixes_panel_lists_fixes`, `test_panel_undo_removes_one_fix_and_ctrl_z_restores`, `test_panel_click_jumps_to_page` (multipage scan with a native fix stub on page 2), `test_thumbnail_badge_counts`. Run → FAIL.
- [ ] Implement.
- [ ] Run the full `pytest` → PASS. Take a screenshot of the editor with two fixes, in light and dark. Commit `feat: editor header and fixes panel`, then push.

### Task 5: Toasts, fades, shortcuts

**Files:** Create `pdf_touchup/ui/toast.py`. Modify `pdf_touchup/ui/app.py` and `pdf_touchup/ui/edit_popover.py` (fade in). Test `tests/test_ui.py`.

**Interfaces:**
- `Toast(QFrame)`: `show_message(text: str, action: tuple[str, Callable] | None = None, ms: int = 2500)`. Fades in and out with a `QPropertyAnimation` on a `QGraphicsOpacityEffect`.
- `MainWindow.toast` shows "Fixed" after apply, "Fix removed" after a panel undo, and "Saved name.pdf" with an "Open folder" action after saving (the action uses `QDesktopServices.openUrl` on the folder).
- Shortcuts: Ctrl+O, Ctrl+S, Ctrl+Z, Ctrl+Y, Ctrl+= / Ctrl+−, Esc.
- [ ] Write failing tests: `test_toast_after_apply`, `test_toast_after_save_has_open_folder` (monkeypatch `QDesktopServices.openUrl`), `test_shortcuts_exist` (`save_action.shortcut() == Ctrl+S`, zoom shortcuts change `zoom_pct`). Run → FAIL.
- [ ] Implement.
- [ ] Run the full `pytest` → PASS. Do a final visual pass (start page and editor, light and dark). Commit `feat: toasts, fades and shortcuts`, then push.
