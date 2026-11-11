### Task 2: This grid draws and exports with the bilinear rule, at the cell size

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/slices/display.py`:
  - `to_north_up` (around line 192) and its docstring;
  - `_build_north_up_plan` (around line 265);
  - `_NORTH_UP_PLANS` and its comment.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slice_layer.py`: `SliceLayer.update` gains
  `counts: bool = False`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`: `_on_slice_changed`'s This grid branch passes
  `counts=dock.coverage_check.isChecked()`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py`: `GeoTiffSliceWriter.write` calls
  `to_north_up(values, plan.frame, counts=plan.finish is None)`. A coverage plan has
  `finish=None`.
- Test: in `packages/nsgeo-core/tests/test_slices_display.py`, the north-up tests only (lines
  ~224–370).
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export.py`:
  `test_a_rotated_export_is_at_half_pitch_and_keeps_every_cell` (~575).
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export_dialogs.py`: the docstring at
  ~262.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_layer.py`: run it, and update any
  assertion that pinned a half-pitch shape or a nearest-cell value. Name each one in the report.

**Interfaces:**
- Consumes: Task 1's `bilinear_taps`, `sample` and `sample_counts`.
- Produces: `to_north_up(values: np.ndarray, frame: CubeFrame, *, counts: bool = False) ->
  tuple[np.ndarray, tuple[float, ...]]`. Same return shapes as today. The pixel is `frame.cell` for
  every azimuth, anchored on the frame's own extent as today. The plan cached per frame is the
  frame's `Taps` plus the shape and geotransform.

- [ ] **Step 1: Rewrite the half-pitch tests in `test_slices_display.py`.**
  - `test_a_rotated_frame_is_resampled_at_half_the_cell` becomes
    `test_a_rotated_frame_is_resampled_at_the_cell`, asserting `gt[1] == frame.cell`.
  - `test_no_cell_is_dropped_on_a_rotated_frame` stays parametrised. It asserts that every cell
    feeds some finite pixel, by the single-bright-cell probe from Task 1.
  - Add `test_an_axis_aligned_frame_is_reproduced_exactly_at_the_cell`, with a random values array:
    `to_north_up(values, frame)[0]` equals `values[::-1]` as float32.
  - Add `test_coverage_counts_are_never_blended`: `to_north_up(counts, f30, counts=True)` holds
    only values present in `counts`.
  - Delete `test_a_hair_off_axis_frame_keeps_the_full_pitch` (the pitch no longer depends on the
    azimuth), or fold it into the at-the-cell test.
  - Keep the rest (row zero at the bottom, top-left anchor, masked corners, no invented values,
    plan once per frame). Update an expected number only where it came from half pitch.
- [ ] **Step 2: Rewrite the plugin pins.**
  - `test_a_rotated_export_is_at_half_pitch_and_keeps_every_cell` becomes
    `test_a_rotated_export_is_at_the_cell_and_keeps_every_cell`. Pixel == cell, and every frame
    cell with data reaches a finite pixel.
  - Add to `test_plugin_slice_export.py`: `test_a_coverage_export_holds_whole_counts`, where a
    rotated frame's coverage band holds only integers ≥ 1 or NaN.
- [ ] **Step 3: Run and see them fail.** Run the display tests (core command) and the two QGIS
  files.
- [ ] **Step 4: Implement.** `_build_north_up_plan` computes the box as today at
  `pixel = frame.cell`, then `bilinear_taps(frame, world)`. `to_north_up` applies `sample`, or
  `sample_counts` when `counts`. Remove the `lattice_pixel` and `snap_azimuth` import here.
  Update the docstring: the "Nearest neighbour, not bilinear" paragraph is replaced by the spec's
  reason, and "Ruling 2 / half the cell" goes.
- [ ] **Step 5: Measure one tick.** Time `to_north_up` on a 50 × 40 m frame at 0.05 m (1000 × 800
  cells) at azimuth 0 and 10.497, plan already cached, median of 20. Record both figures in the
  docstring next to the old ones (2 ms at 0.2 m, 8 ms at 0.1 m). If the rotated tick is over 50 ms,
  report it rather than optimising.
- [ ] **Step 6: Run** the display tests, `test_plugin_slice_export.py`,
  `test_plugin_slice_export_dialogs.py`, `test_plugin_slice_layer.py` and
  `test_plugin_slices_dock.py`, plus lint. All pass.
- [ ] **Step 7: Commit**: `feat(slices): This grid draws and exports bilinear at the cell size`.

---

