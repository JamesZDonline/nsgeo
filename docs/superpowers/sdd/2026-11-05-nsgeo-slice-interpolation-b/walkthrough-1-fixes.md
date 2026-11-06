# Walkthrough round 1 fixes (user decisions, 2026-11-06)

The user walked the deployed build in profile `ns_geo_mincurv`. Almost everything passed. One annoyance remains, from one cause, plus a related wording problem. The user chose a fix: **"Short indicator by slider"**.

## What the user saw

**W1 (check D1).** With Minimum curvature at a 0.1 m cell, the user rests the cursor over the depth slider and turns the mouse wheel. The panel's own scroll bar takes over and moves the slider out from under the cursor. With Kriging the wheel works flawlessly.

**W2 (checks E1, E2).** The preview and refining status sits at the bottom of the panel, often below the screen, so the user has to scroll to see it at the same time as the slider. The status also changes between one and two lines as it moves through preview, refining and normal. The user says this makes "the panel feel like it's jumping up and down".

**W3 (check E4).** "Refining with minimum curvature (0 of 9)…" — the user asked what the 9 are. The count mixes the current slice with the stretch windows.

## Cause, measured by the controller

The scratchpad script `label_heights.py` measured the word-wrapped `status_label` (slices_dock.py:565-567, at the bottom of the dock's scroll area). Its height changes as the refine state cycles:

| Dock width | normal | preview | refining |
|---|---|---|---|
| 260 px | 47 px | 70 px | 47 px |
| 400 px | 47 px | 47 px | 24 px |

Each change re-lays out the scrolled dock. When the user has scrolled down to see the status, the scroll position is clamped, the content shifts, and the slider moves from under the cursor. The next wheel event then lands on the scroll area. Kriging never changes the status text, so it never shows the problem.

## Required change: a short fixed-height indicator beside the readout

1. **A new one-line indicator label in the Position group, directly under the depth readout** (`self.readout`, slices_dock.py:354-355). Call it something like `self.refine_label`.
   - **Never changes height.** No word wrap. Its height is fixed to one line (e.g. `setFixedHeight` from the font metrics), and it keeps that height when empty, so it never appears, disappears or wraps.
   - **Never widens the dock.** A QLabel's text width is its minimum width, and a wider dock forces the QGIS main window to grow; see the existing test `test_the_dock_minimum_does_not_force_the_main_window_to_grow`. Give it a horizontal size policy that ignores the text width (`QSizePolicy.Policy.Ignored`) and elide long text, or otherwise guarantee this.
   - **Shared by both scopes.** It shows This grid's state in This grid and the site's state in Whole site, driven by each scope's `RefineFlow`.
2. **Indicator texts.** These replace `PREVIEW_STATUS` and `REFINING_STATUS` in slices_plan.py; rename the constants to fit.
   - While a preview stands and nothing is solving for it yet: `Kriging preview`
   - While the slice on screen is being solved: `Refining this slice…`. In Whole site, where several grids are solved for one slice: `Refining this slice ({done} of {total} grids)…`
   - While only stretch windows are being solved: `Measuring the colour stretch ({done} of {total})…`, counting stretch windows only. In Whole site, count the (grid, window) jobs.
   - Otherwise empty.
3. **The bottom `status_label` goes back to memory and redraw information only**: `_grid_status_text()` and the site's `status_text()`. It never shows refine states. Remove its use for refine state, and the `RefineFlow.status(normal)` composition, wherever it exists.
4. **Tests,** in both scopes where it applies:
   - The scroll area's content height and the slider's position inside the scroll area do not change when a slice goes normal → preview → refining the slice → measuring the stretch → final. Check at a narrow dock width (260 px) and a wide one (400 px).
   - The indicator shows each of the texts above at the right moment, including the grid and stretch counts. The bottom status label never shows a refine text.
   - The existing dock minimum-size test still passes. Add an assertion that the indicator does not raise the dock's minimum width even with the longest indicator text.
   - Update every existing test that asserts on `PREVIEW_STATUS`, `REFINING_STATUS` or the status label during a refine.
5. **The guide** (docs/guide/getting-started.md) must not mention the old status wording. If it says where to see the preview or refining state, say it shows under the depth readout.
6. **The walkthrough wording in the plan** may be left as it is; it is a record.

## Out of scope for this round

- The faster solver (#111).
- The Surfer comparison. The user waived it for B; it will be filed as a follow-up.
