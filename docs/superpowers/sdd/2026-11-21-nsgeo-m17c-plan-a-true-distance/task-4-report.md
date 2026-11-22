# Task 4 report: the profile draws a GPS line at true distance

Status: DONE.

## Implemented
- profile_view.py: `set_axes(..., *, axis=None)` (wrong-length axis logged and dropped; axis reaches both `ViewTransform.fit` calls); `fit()` carries `t.axis`; `paintEvent` branches on `t.axis` into new `_paint_spans` (one drawImage per `paint_spans()` entry, flipped about its own target when mirrored), the no-axis path is untouched; `readout_text` over a gap gives `{m:.2f} m along (gap)` (blank space past the line's ends still reads "").
- profile_dock.py: `_trace_axis_for(line, distance)` (TrackPlacement with a distance only; ValueError logged -> None); `_set_axes_holding` (the only place axes are set, so R4 holds for every path incl. `_on_geometry_changed`, `_render`, `_show_cut`, take-down) builds it and passes it; rule 1 and the last same-transform rule also require `_same_axis` (else a Gap over change would restore the old transform); `_curve_traces` makes `velocity_curve_points` even in metres for a TrackPlacement line only (R5), ascending, tape/cut unchanged (`linspace` in traces, pinned by a test). The `_render` `n_traces == line.n_traces` guard covers the axis too (distance None -> no axis).

## Tests
- view: gap hatched / traces at distance; readout over a gap; click in a gap picks nothing + positive control on a drawn trace (R6); pick on a left-out trace drawn at its walked metre + right-click discard of a velocity point there (the view has no right-click pick removal; velocity points are what a right click removes).
- dock: GPS axis with gap_m (auto and typed); Gap over change reaches an open profile (R4, via `_replace_line` + `lines_changed`); tape no axis (x_of_trace == axis-less fit at 10 positions); difference view keeps axis; curve even in metres (std/mean < 0.01); tape curve unchanged; Fit width/height/all, zoom, 1:1 keep the axis. cut: no axis (in test_plugin_profile_cut.py, where cut fixtures live).
- true_distance (real_data): FILE__016 lift one gap (355-362 zero width, 354/363 drawn, gap at middle); FILE__028 lift (841->842 is a gap; traces 830-849 drawn). FILE__028 does have left-out traces elsewhere (1268-1275), so the assertion is local to the lift. Tape FILE__007 no axis; R9 FILE__016 migration at true spacing (time_zero first_break then MigrateFk(0.1): finite, same shape, edges 354/363 RMS within 2x of five-trace neighbours).
- Results: four files 363 passed; `-m real_data` 11 passed; core+pure 2230 passed, 9 skipped, 19 xfailed; ruff check and format clean.

## TDD
RED (11 failed, 25 passed on the new tests): `TypeError: ProfileView.set_axes() got an unexpected keyword argument 'axis'` (view x4), dock `assert (None is not None)` / `'NoneType' has no attribute 'gap_m'`, curve `std/mean = 0.067 > 0.01`, real `'NoneType' has no attribute 'drawn'`. Two real-data tests were red for test errors (migration needs time zero first; FILE__028 left-outs elsewhere), fixed in the test. GREEN: commands above.

## Files
packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py, profile_dock.py; tests test_plugin_profile_view.py, test_plugin_profile_dock.py, test_plugin_profile_cut.py (appended), test_plugin_profile_true_distance.py (new). No existing test changed.

## Self-review / concerns
- Selection band and cursor still use trace-unit edges through `x_of_trace` (selection edges `x_of_trace(a)`..`x_of_trace(b+1)` lie mid-gap-width for a trace next to a gap); not in the brief, not changed.
- `_distance_ticks` and pick/cursor go through the same road, unchanged.
- Not run: time-zero drag on a GPS line by hand (covered only through the transform paths above).
