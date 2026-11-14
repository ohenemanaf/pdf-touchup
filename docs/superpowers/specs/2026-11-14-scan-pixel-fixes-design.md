# Scan fixes that look printed — Design

Date: 2026-11-14
Status: Approved approach (option 1); design for review

## Why

When the owner fixed a word on a real CamScanner scan, the result looked "stuck on top". All four symptoms were confirmed:

- **A.** The new word is sharper and cleaner than the blurry scanned words around it.
- **B.** A flat patch is visible where the paper's grain and shading stop.
- **C.** Faint edges of the old word remain around the fix.
- **D.** Fixing the same spot again stacks a new fix on top of the earlier one.

**Root cause of A–C:** v1 draws the fix as a separate vector layer over the scan (a flat colour box plus crisp text).

**Root cause of D:** after a fix, the page's clickable words still describe the old text.

## Goals

1. On scanned pages (`scanned`, `searchable_scan`), the fix is made **inside the scan image's pixels**. The page stays one picture.
2. The old word is replaced with paper texture that continues the surrounding shading and grain. There is no flat box.
3. The new word is drawn in the measured ink colour and blurred to match the softness of the neighbouring scanned text, with matching grain.
4. No trace of the old word remains: the erase covers the ink's soft edges.
5. Clicking a fixed word reopens **that fix** (Found = the original text, Change to = the current fix). Applying replaces the fix instead of stacking. Undo restores the previous fix.
6. Normal typed PDFs keep the v1 behaviour (it already looks right).

## Non-goals

- Making the new word selectable or searchable text on scans. It becomes part of the picture, like every other word on a scan.
- Handwriting, colour photos of documents at an angle, or skewed lines.
- Scans whose resolution is too low to read (under about 100 dpi). Those fixes may still look rough.

## Anti-goals

- A visible rectangle, colour step or grain change around the fix.
- The new word visibly crisper or bolder than its neighbours at normal zoom.
- File size blowing up (for example, an 800 KB JPEG scan becoming 8 MB).
- The original file changed. "Save as" is still a new file.

## Approaches considered

| Approach | Trade-off | Outcome |
|---|---|---|
| **1. Edit the scan's pixels** | New word isn't selectable text. Slower save/preview (image decode and re-encode). | **Chosen** |
| 2. Keep the vector overlay with a textured patch and lighter text | Fixes B and C partly, but text stays crisp (A remains) | Rejected |
| 3. Tune the current overlay | A and B mostly remain | Rejected |

## How it works

### Finding the image and mapping coordinates

- The scan image is the image covering ≥80% of the page (`page.get_image_info(xrefs=True)`).
- An affine map goes from display coordinates to image pixels: display → unrotated page (derotation matrix) → image unit square (inverse of the image's `transform`) → pixels (× width, height).
- Only axis-aligned placements (0/90/180/270°, with flips) are supported. Text patches are rotated or flipped into the image's orientation.

### Erasing the old word

- The erase box is the old word's box in image pixels, padded by about 15% of the line height and 1–2 px horizontally to catch soft ink edges.
- Fill, column by column: interpolate between the **paper** pixels in bands just above and just below the box. Ink pixels are excluded by luminance. This continues shading gradients. Then add Gaussian grain with the σ measured from nearby paper pixels.

### Drawing the new word

- Render the text in the chosen font at the image's own resolution (font size in points × image dpi / 72) with `h_scale`, as an anti-aliased coverage mask.
- **Blur match:** before erasing, compare the old word's ink against re-renders of the old text blurred with σ ∈ {0, 0.5, 1, 1.5, 2, 3} px. Pick the best normalised correlation and apply that σ to the new word's mask.
- Composite: pixel = paper·(1−a) + ink·a, then add the measured grain inside the ink as well.
- Position: same left edge and baseline rules as v1 (OCR boxes hug the ink).

### Writing back

- Encode as JPEG (quality ≈ 92) when the original image is JPEG, otherwise PNG, then call `page.replace_image(xref, stream=…)`.
- **Shared image** (the same xref drawn on several pages): insert the edited picture as a new image on this page over the old one instead of changing the shared image. This is a known limitation: the old word stays in the hidden shared image data.
- For `searchable_scan`, the hidden text layer's old words are still removed (v1 pass 1).

### Re-editing (D)

- `Edit` gains `replaces: Edit | None`. `EditList.items()` leaves out any edit replaced by a later active edit. Undo of the replacing edit brings the earlier one back automatically.
- Core helper `display_words(words, edits) -> list[Word]`: hides original words whose centre lies inside an applied edit's box, and adds one clickable word per edit (its new text, its box).
- Clicking an edit's word opens the popover for that edit. Applying creates a new edit with the original `old_text` and `rect`, `replaces=` the earlier one.

## Left to the builder

- Exact padding, band heights and grain estimation constants, tuned on the generated scan plus a visual check of the owner's real scan. (The real scan is not stored in the repo, because it's a private medical document.)
- Performance: preview must stay usable on a 2144×3052 scan. Target under about 700 ms per preview.
