# Scan Pixel Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make fixes on scanned pages inside the scan image's pixels (texture-filled erase, blur-matched text), and make re-fixing a word replace the earlier fix instead of stacking.

**Architecture:** A new pure-numpy module `scan_pixels.py` finds the page's scan image, maps display coordinates to image pixels, erases with paper texture, estimates blur and composites the new word. `edits.apply_edits` uses it for scan kinds instead of the vector overlay. `Edit.replaces` plus `display_words()` give re-editing. The UI routes clicks on fixed words to their edit.

**Tech Stack:** Python 3.12, PyMuPDF 2.1 (`pymupdf`), numpy, PySide6, pytest.

**Spec:** `docs/superpowers/specs/2026-11-14-scan-pixel-fixes-design.md`

## Global Constraints

- Scan kinds = `"scanned"`, `"searchable_scan"`. `"native"` keeps the v1 path unchanged.
- Original file is never written. `save_as` refuses source path (existing).
- JPEG source images stay JPEG (quality 92). Output file ≤ 2× the source size for a single fix.
- Only axis-aligned image placements (rotations of 90°, flips). Other placements fall back to the v1 overlay.
- Shared image xref (used on more than one page): overlay a new image on this page, never mutate the shared one.
- Preview on a ~6.5 MP scan: < 700 ms per render on this PC.

## Review Focus

1. **Rotated scans** (image stored sideways, `/Rotate 90`): erase and new text land on the right pixels, upright. → Task 1 mapping test on `rotated_scan_pdf`, Task 3 rotated OCR test.
2. **Shaded/tinted paper** (gradient across the word): the fill continues the gradient, with no step. → Task 2 `test_paper_fill_follows_gradient`.
3. **Neighbouring lines close above/below**: the erase band must not eat neighbours' ink. → Task 2 `test_paper_fill_ignores_neighbour_ink`, Task 3 tight-lines pixel test.
4. **Same image reused across pages**: other pages unchanged. → Task 3 `test_shared_image_other_pages_untouched`.
5. **Re-edit then undo**: the earlier fix comes back, not the original. → Task 4 `test_undo_replacement_restores_previous_fix`.

---

### Task 1: Locate the scan image and map coordinates

**Files:** Create `pdf_touchup/scan_pixels.py`. Test `tests/test_scan_pixels.py`.

**Interfaces (produces):**
- `@dataclass ScanImage: xref: int; width: int; height: int; to_px: pymupdf.Matrix; shared: bool; ext: str`
  - `to_px` maps display coords → image pixel coords.
- `find_scan_image(page) -> ScanImage | None`: the image covering ≥ 80% of the mediabox. `shared` is true when the xref appears in `get_images()` of any other page. Returns `None` when the transform is not axis-aligned.
- `px_box(scan: ScanImage, rect: Rect) -> tuple[int, int, int, int]`: the normalised, clipped pixel box.
- `orientation(scan) -> tuple[int, bool]`: (quarter turns `k` for `np.rot90`, `flip_lr`) that turn an upright display patch into image orientation.

- [ ] **Step 1: Write failing tests:**
  - `test_find_scan_image_on_scan`: on `scanned_pdf` it is non-None, with width/height equal to the embedded image size and `shared is False`. On `native_pdf` it returns `None`.
  - `test_px_box_hits_the_word_ink` (scanned and rotated, parametrised): take the OCR rect of "Mensah", compute `px_box`, and decode the image (`pymupdf.Pixmap(doc, xref)`). The box crop contains ≥ 5% dark pixels (lum < 0.5), and the same-size box 40 px to the right of the word line's end contains < 1%.
  - `test_orientation_round_trip_rotated`: on `rotated_scan_pdf`, a display patch with a mark at its top-left lands, after the orientation transform, at the pixel corner that `to_px` maps the display top-left to.
- [ ] **Step 2:** `pytest tests/test_scan_pixels.py -v` → FAIL (import).
- [ ] **Step 3:** Implement. `to_px = page.derotation_matrix * ~Matrix(info["transform"]) * Matrix(width, height)`.
- [ ] **Step 4:** Same command → PASS.
- [ ] **Step 5:** Commit `feat: locate scan image and map display coords to pixels`, then push.

### Task 2: Pixel operations (erase, blur estimate, text mask, composite)

**Files:** Modify `pdf_touchup/scan_pixels.py`. Test `tests/test_scan_pixels.py`.

**Interfaces (produces), all on `img: np.ndarray` H×W×3 uint8 and pixel boxes:**
- `gaussian_blur(a: np.ndarray, sigma: float) -> np.ndarray`: separable, 2D float. `sigma <= 0` returns a copy.
- `paper_fill(img, box, band: int, rng) -> None` (in place): for each column, linearly interpolate between the median paper colour of the `band` rows above and below the box, using only pixels whose lum is ≥ (paper lum − 0.12). Fall back to the overall paper median. Then add Gaussian grain with the σ measured from those paper pixels.
- `text_mask(text, family, font_buffer, size_px, h_scale) -> tuple[np.ndarray, float]`: anti-aliased coverage 0..1 (H×W float), returned with the baseline row offset.
- `estimate_blur(img, box, old_text, family, font_buffer, size_px) -> float`: σ from {0, 0.5, 1, 1.5, 2, 3} maximising NCC between the old ink and the blurred `text_mask(old_text)` resized to the ink bbox.
- `composite(img, mask, top_left, ink: RGB, grain_sigma, rng) -> None` (in place).

- [ ] **Step 1: Write failing tests:**
  - `test_gaussian_blur_preserves_mean_and_softens`.
  - `test_paper_fill_matches_grain`: on the scanned fixture image, fill the "Mensah" box. The fill's mean is within 0.03 of cream, its σ is between 0.5× and 2× the σ of nearby paper, and no pixel has lum < 0.6.
  - `test_paper_fill_follows_gradient`: on a synthetic left-to-right/top-to-bottom gradient image with a black box, the filled values at top/bottom rows are within 4 levels of the neighbouring rows.
  - `test_paper_fill_ignores_neighbour_ink`: with text lines 2 px above/below the box, the fill has no pixel with lum < 0.6.
  - `test_estimate_blur_recovers_sigma`: synthetic render of "Mensah" blurred with σ = 1.5 gives an estimate of 1.5 ± 0.5. Unblurred gives ≤ 0.5.
  - `test_text_mask_width_scales`: the width at `h_scale` 1.1 is 1.1 × (±3%) the width at 1.0.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat: paper-texture erase, blur estimate, text compositing`, then push.

### Task 3: Apply scan fixes in pixels

**Files:** Modify `pdf_touchup/edits.py`, `pdf_touchup/scan_pixels.py` (add `apply_scan_edits(page, edits)`). Test `tests/test_edits.py`.

**Interfaces:**
- `apply_scan_edits(page, edits: list[Edit]) -> bool`: returns `False` when no usable scan image is found (the caller falls back to the v1 overlay). It decodes the image once, and for each edit runs `estimate_blur` (before erase), `paper_fill`, `text_mask`, rotate/flip to the image orientation, and `composite`. It then encodes (JPEG q92 if `ext` is jpeg/jpx, else PNG) and replaces the image, or overlays a new image when `shared`.
- `apply_edits`: pass 1 (text band removal) is unchanged. For scan kinds, try `apply_scan_edits` first, and use the old pass 2 plus `_insert` only on `False`. Native is unchanged.

- [ ] **Step 1: Write failing tests:**
  - `test_scan_fix_is_inside_the_image`: after `save_as` on `scanned_pdf`, the output page has no text containing "Asante" (`get_text()` empty) and still has exactly one image. OCR finds "Asante" and not "Mensah".
  - `test_scan_fix_has_no_flat_patch`: the rendered erase area σ ≥ 0.5 × the σ of surrounding paper.
  - `test_scan_fix_blur_matches_neighbours`: `estimate_blur` on the new word ≈ `estimate_blur` on "Kwame" (± 0.75).
  - `test_scan_fix_keeps_jpeg_and_size`: a fixture saved with a JPEG image produces output < 2× the source bytes, and the image ext stays jpeg.
  - `test_shared_image_other_pages_untouched`: on `multipage_scan_pdf` (one shared xref), fix page 0. OCR of page 1 still finds "Mensah", and page 0 doesn't.
  - Existing `test_scanned_edit_*`, `test_apply_on_rotated_page` and `test_searchable_scan_edit_removes_both` must still pass. Update `test_scanned_edit_replaces_word`, whose "Asante in get_text" assertion becomes "Asante not in get_text" (the new word is in the pixels).
- [ ] **Step 2:** Run `pytest tests/test_edits.py -v` → new tests FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Full `pytest` → PASS. Then do a visual check on the generated scan (zoomed crop before/after) and, locally only, on the owner's CamScanner file. Delete those crops afterwards. Time `render_with_edits` on that file (< 700 ms).
- [ ] **Step 5:** Commit `feat: make scan fixes in the image pixels`, then push.

### Task 4: Re-editing a fixed word

**Files:** Modify `pdf_touchup/model.py` (`Edit.replaces: Edit | None = None`), `pdf_touchup/edits.py` (`EditList.items`), `pdf_touchup/selection.py` (`display_words`), `pdf_touchup/ui/viewer.py` and `pdf_touchup/ui/app.py`. Test `tests/test_edits.py`, `tests/test_selection.py`, `tests/test_ui.py`.

**Interfaces:**
- `EditList.items()` returns the active edits in order, excluding any edit that appears as `.replaces` of a later active edit (identity comparison).
- `display_words(words: list[Word], edits: list[Edit]) -> list[Word]`: removes words whose centre is inside an edit rect, and appends `Word(e.new_text, e.rect, ("edit", i))` per edit.
- `PageView` keeps `edit_for_word: dict[int, Edit]` (by `id(word)`). `MainWindow` shows `display_words(...)` for the current page and refreshes on edit changes. Clicking a fixed word opens the popover with `old_text = edit.old_text`, `new_text = edit.new_text` and the edit's style. Apply adds `replace(edit, new_text=…, style=…, replaces=edit)`.

- [ ] **Step 1: Write failing tests:**
  - `test_items_hides_replaced_edit`.
  - `test_undo_replacement_restores_previous_fix`.
  - `test_display_words_swaps_fixed_words`.
  - UI `test_refix_replaces_instead_of_stacking`: apply "Kwame Asante", click the fixed word, the popover's Found field shows "Kwame Mensah" and Change to shows "Kwame Asante". Change it to "Kwame Boateng" and apply. `len(edits.items()) == 1`, and its `new_text` is "Kwame Boateng".
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Full `pytest` → PASS.
- [ ] **Step 5:** Commit `feat: clicking a fixed word re-opens and replaces that fix`, then push. Merge to `main` after the final review.
