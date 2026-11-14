# UI Redesign (start screen + fixes panel) — Design

Date: 2026-11-14
Status: Draft for approval

## Why

The owner opened the app and found it blank and plain: "it should be very, very nice… cute, nice, interactable". They picked visual direction **B, clean & professional** (neutral greys, one blue accent, compact, ClassFlow-like) and editor layout **1, fixes panel on the right** from browser mockups.

## Goals

1. **Start screen** (no file open):
   - Header with app mark and name, and a primary "Open PDF" button.
   - Title "Open a PDF to start" with a one-line hint.
   - A large dashed drop zone.
   - Three step chips: ① Click a word ② Type the fix ③ Save a copy.
   - A **Recent** list on the left: the last 8 files, each with name, "Scanned/Typed" and a relative date. Files that no longer exist are dropped. Clicking one opens it.
2. **Open by dragging** a PDF onto the window, on the start screen or while editing. Dragging a non-PDF shows a polite message.
3. **Editor header:**
   - File name · kind (Scanned / Typed / Mixed) · page count.
   - Undo and redo icon buttons, and zoom − % +.
   - Primary **"Save copy"** button.
   - Light/dark switch.
4. **Fixes panel** (right, ~240 px):
   - "FIXES · n" heading, and one card per active fix: old text struck through → new text in bold, then "Page n · Undo".
   - Clicking a card jumps to its page and highlights the fix.
   - "Undo" on a card removes **just that fix**. Ctrl+Z reverses that removal.
   - Empty state: "Click any word on the page to fix it."
5. **Page thumbnails** show a small blue badge with the number of fixes on that page.
6. **Feedback:**
   - Words highlight on hover (existing).
   - The edit box and toasts fade in and out (about 150 ms).
   - A small "Fixed" toast after Apply, and a "Saved name.pdf" toast with an "Open folder" link after saving.
7. **Keyboard:** Ctrl+O open, Ctrl+S save copy, Ctrl+Z / Ctrl+Y undo/redo, Esc closes the edit box, Ctrl+= / Ctrl+− zoom.
8. **Light and dark themes**, switchable in the header and remembered between runs. Light is the default.

## Non-goals

- New editing abilities. Same fixes as today.
- Animations beyond short fades. No bouncing, no confetti.
- Custom window chrome. Keep the normal Windows title bar.

## Anti-goals

- An oversized or "zoomed" UI. Keep the owner's compact rules: ~14 px text, 32–40 px controls, 8–12 px radii, sentence-case buttons, one accent colour (#2F6FEB).
- Anything that slows opening a long scan. Thumbnails stay lazy, OCR stays in the background.
- Losing work: the unsaved-fixes prompt must still appear when you close the app or open another file.

## Approaches considered

| Choice | Options shown | Picked |
|---|---|---|
| Visual style | A soft & friendly (pastel), B clean & professional, C bold & playful (dark) | **B** |
| Editor layout | 1 fixes panel on the right, 2 floating toolbar + bubble editor | **1** |
| Building it | Keep PySide6 widgets plus a stylesheet (QSS) and a few custom-painted widgets; *or* switch the UI to a web view (HTML/CSS) | **PySide6 widgets** (builder's call: no new dependency or rewrite, and it keeps the installer small) |

## How it works (decided)

- **Window structure:** a `QStackedWidget` with two pages, the **Start page** and the **Editor page**. The editor holds the thumbnails, the page view and the fixes panel.
- **Recent files:** stored with `QSettings("PDF Touch-up", "PDF Touch-up")` as a list of `{path, kind, opened_at}`, newest first, at most 8.
- **Removing one fix:** `EditList` gains an undoable `remove(edit)`. Undo restores the removed fix. Redo removes it again.
- **Themes:** two QSS files (`light.qss`, `dark.qss`) built from one palette of colour tokens. The page canvas stays light grey in light mode and becomes dark grey in dark mode. The PDF page itself is never tinted.
- **Toasts:** a small reusable `Toast` widget over the page view with an opacity animation that hides itself after 2.5 s.
- **Icons:** simple inline SVG (undo, redo, zoom, theme, file), drawn in the theme's text colour.

## Left to the builder

- Exact spacing and colour token values within the B palette.
- Wording of empty states and toasts. Keep it short and plain.
- Whether the "Mixed" kind label is worth computing (only when some pages are scanned and others typed).
