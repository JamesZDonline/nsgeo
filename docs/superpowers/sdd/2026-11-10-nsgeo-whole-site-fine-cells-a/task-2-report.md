# Task 2 report

Commit a93c527 `feat(slices): This grid draws and exports bilinear at the cell size` (pushed).

## Implemented
- display.py: `to_north_up(values, frame, *, counts=False)`; pixel = frame.cell at every azimuth, same box/eps logic; plan = (Taps, shape, geotransform) cached per frame (lru 2); `sample` or `sample_counts`. No longer imports lattice_pixel/snap_azimuth. Docstring rewritten (bilinear reason, counts, timing).
- slice_layer.py `update(..., counts=False)`; plugin.py This-grid branch passes `counts=dock.coverage_check.isChecked()`; slice_export.py writer passes `counts=plan.finish is None`, module docstring updated.
- core README row for `to_north_up` updated.

## TDD
RED (new tests vs old display.py): 2 failed, 28 passed: `test_a_rotated_frame_is_resampled_at_the_cell` (gt[1] was cell/2) and `test_coverage_counts_are_never_blended` (no `counts` kwarg). The axis-aligned exact test passed on old code too (nearest is exact there); expected. GREEN after implementing.

## Tests changed/deleted
- test_slices_display.py: `..._at_half_the_cell` -> `..._at_the_cell` (also covers 1e-7 hair-off-axis, so `test_a_hair_off_axis_frame_keeps_the_full_pitch` deleted/folded); `test_no_cell_is_dropped_on_a_rotated_frame` now single-bright-cell probe (12x9 frame); added exact axis-aligned reproduction and counts-never-blended; `test_north_up_of_a_rotated_frame_fills_a_larger_box...` assertion "only real cell values" -> "within [min,max]" (it pinned nearest; failed under bilinear, as expected).
- test_plugin_slice_export.py: half-pitch test renamed `..._at_the_cell_and_keeps_every_cell` (pixel==cell, all-ones band finite >=90% of cell count and only 1.0, per-cell probe via to_north_up; unique-id check dropped since bilinear blends ids); added `test_a_coverage_export_holds_whole_counts`; docstring cross-reference updated.
- test_plugin_slice_export_dialogs.py: docstring only.
- test_plugin_slice_layer.py / test_plugin_slices_dock.py: no assertion needed changing.

## Step 5 timing (1000x800 cells at 0.05 m, plan cached, median of 20)
- azimuth 0: 5.6 ms (first call 238 ms)
- azimuth 10.497: 139 ms (first call 441 ms)  -- OVER the 50 ms threshold; reported, not optimised. Recorded in the docstring.

## Results
Core tier: 788 passed, 28 skipped. QGIS: slice_export + dialogs 71 passed; slice_layer + slices_dock 166 passed, 1 skipped. ruff check/format clean; CI mypy clean.

## Concerns
- Rotated tick at 139 ms at 0.05 m on a 50x40 m grid (the same area at 0.1 m would be ~4x cheaper). Likely the 4-corner gather + float conversion in `sample`; Task 1/follow-up optimisation candidate.
- `to_north_up` still does `np.asarray(values, dtype=float)` (float64 copy) per tick; part of that cost.

## Addendum: sampler optimisation (controller ruling)
Commit: `perf(slices): precompute corner taps; float32 sampling`.
- resample.py: `Taps` now holds `nearest`, `ids` (4, n) intp flat corner ids (clipped safe) and `weights` (4, n) float32 (0 for out-of-frame corners and for every corner of an outside point); `ix0/iy0/tx/ty` are gone. `sample` is one gather, float32 einsum, in-place divide; no float64 copy. `to_north_up` no longer converts values to float64 (`sample` casts to float32 once). `sample_counts` uses `weights > 0` for the positive-weight rule. Exact fast path now maps non-finite nearest values (inf) to NaN; test `test_an_infinite_nearest_cell_is_blank_on_the_exact_path`.
- Test rewritten: the counts `hits` check in test_slices_resample.py read `ix0/iy0/tx/ty`; it now reads `ids` and `weights > 0` for flat cell 10*nx+10 (equivalent). No other test changed.
- Bytes per point (`Taps.nbytes`): 20 before (nearest + ix0 + iy0 + tx + ty), 52 after (4 + 32 ids + 16 weights). Deviation from the suggestion: ids are intp, not int32, because numpy converts int32 indices on every gather (measured 17 ms vs 8 ms per (4, n) gather at 1.1M points). int32 ids would be 36 B/pt at about 48-50 ms. Task 3/4 plan-memory budgets should use 52 B/pt (a 1.2M-pixel plan is about 57 MB).
- Timing (1000x800 cells at 0.05 m, plan cached, median of 20, several runs): azimuth 0: 5.2-5.7 ms (one 10.8 ms outlier under load); azimuth 10.497: 139 ms -> 29.5-31.7 ms in four runs (earlier intermediate variants 35-50 ms). Docstring updated.
- Verification: test_slices_resample + test_slices_display 45 passed; core tier 789 passed/28 skipped; QGIS test_plugin_slice_layer + test_plugin_slice_export 66 passed; ruff check/format and CI mypy clean.

## Addendum 2: fix round 1
Commit: `fix(slices): exact constants in the blend; pin counts= in export and the layer`.
1. resample.py `sample`: blends offsets from the nearest value (`v -= base`, blend, `+= base`). New tests: `test_a_constant_field_resamples_to_itself_exactly` (c in 7.3/0.1/1234.567 x azimuth 10.497/30/45, assert_array_equal) and `test_a_plateau_at_the_maximum_never_blends_above_it`. Against the previous resample.py (scratch copy of the tree, not committed): the 9 constant tests fail; the plateau test passes on both versions (it does not discriminate; the constant test is the real pin). Timing (Step 5, median of 20, three runs): azimuth 0 4.4-4.7 ms; azimuth 10.497 35.3-36.0 ms (was ~30); docstring updated.
2. counts= pins: the rotated export test now also exports a negative-valued random field and compares the band to `to_north_up(field, frame)` (assert_allclose); new `test_a_rotated_coverage_view_draws_only_whole_counts` in test_plugin_slice_layer.py (counts=True draws whole numbers, counts=False on the same input is blended). Mutants (edited, run, reverted with git checkout; PYTHONDONTWRITEBYTECODE=1): writer `counts=True` hard-coded -> rotated export test fails; `SliceLayer.update` ignoring counts (counts=False hard-coded) -> the new layer test fails. Not covered: plugin.py's `counts=dock.coverage_check.isChecked()` line itself (no plugin-level test; the reviewer accepted SliceLayer-level pinning).
Results: core tier 799 passed/28 skipped; QGIS export + export_dialogs + slice_layer 94 passed; ruff/format/CI mypy clean.

## Addendum 3: fix round 2
Commit: `test(slices): pin the plugin's coverage call; a real plateau at the maximum` (tests only).
- New `test_the_plugin_draws_a_rotated_coverage_view_as_whole_counts` (test_plugin_slice_export_dialogs.py): rotated grid, `dock.coverage_check` on, reads the drawn layer back, whole counts >= 1; off, non-integers present. Mutant: plugin.py:831 `counts=False` (temporary edit, reverted with git checkout) -> the test fails; unmutated it passes.
- Plateau test now uses 7.3 (above every random() value). Against the b445475 num/den sampler (scratch copy) it fails; on the current sampler it passes.
- Results: test_slices_resample 25 passed; test_plugin_slice_export_dialogs 28 passed; ruff/format/CI mypy clean.

## Addendum 4: fix round 3
Commit: `test(slices): the coverage-off view is pinned as a blend` (test only). The coverage-off check in the plugin test is now `not np.isin(amplitudes.float32, dock.current_values().float32).all()` (min-sampling only returns cell values; a blend does not); docstring updated.
Mutants at plugin.py:831 (temporary edits, reverted by git checkout): `counts=False` -> test fails; `counts=True` -> test fails; unmutated -> passes. test_plugin_slice_export_dialogs.py: 28 passed; ruff/format clean.
