### Task 4: The profile draws a GPS line at true distance

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py` (`set_axes`, `paintEvent`, `readout_text`), `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (where `set_axes` is called for a line: `_set_axes_holding` / `_render`; `velocity_curve_points`)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_true_distance.py` (new; real-data tests marked as the other `real_data` tests are)

**Interfaces:**
- Consumes: Task 3's `TraceAxis`, `ViewTransform(axis=...)`, `paint_spans()`; Task 1's `TrackPlacement.gap_m`.
- Produces:
  - `ProfileView.set_axes(n_traces, n_samples, t0_ns, dt_ns, distance_along=None, ruler=None, *, axis: TraceAxis | None = None)`; the axis reaches `ViewTransform.fit`. An axis whose length is not `n_traces` is logged and dropped, as a wrong-length distance is today.
  - `paintEvent` with an axis: hatch the image rect as today, then one `drawImage` per `paint_spans()` entry (source columns `first*sx` to `(last+1)*sx`), each flipped about its own target when mirrored.
  - `readout_text()` over a gap: `{m:.2f} m along (gap)`.
  - `ProfileDock._trace_axis_for(line, distance) -> TraceAxis | None` — `TraceAxis.from_distance(distance, line.placement.gap_m)` for a `TrackPlacement` with a distance; None for tape lines, cuts and any failure (logged).
  - `velocity_curve_points` samples `_CURVE_SAMPLES` points evenly in metres between the line's ends (then converts to traces), not evenly in trace index.

- [ ] **Step 1: Write the failing tests.**
  - `test_plugin_profile_view.py`: `test_a_gap_is_hatched_and_the_traces_sit_at_their_distance` (a radargram of one strong value with a 1.0 m gap; `grab()` the widget: the pixel at the gap's middle is the background or hatch colour, the pixel at `x_of_trace(i + 0.5)` of a drawn trace is not); `test_the_readout_says_gap_over_a_gap`; `test_a_click_in_a_gap_picks_nothing` (pick mode: no `pick_requested`); `test_a_pick_on_a_left_out_trace_is_still_drawn` (`_pick_positions` holds it at its walked metre; right-click near it still offers removal as for any pick).
  - `test_plugin_profile_dock.py`: `test_a_gps_line_gets_a_trace_axis_with_its_gap_over`; `test_a_tape_line_gets_no_trace_axis` (and its transform's `x_of_trace` at 10 positions equals a `ViewTransform.fit` without an axis); `test_a_cut_gets_no_trace_axis`; `test_the_difference_view_keeps_the_trace_axis` (Difference on a GPS line: same axis, same gap); `test_the_fit_curve_is_sampled_evenly_in_metres` (metres between consecutive curve points: std / mean < 0.01 on a GPS line).
  - `test_plugin_profile_true_distance.py` (`real_data`): `test_file016s_lift_is_one_gap_in_its_profile` (open `with-dzg/FILE__016` as a GPS line the way the M17b real-data tests do: `trace_at` at the middle metre of the lift is None, traces 355–362 have zero drawn width, 354 and 363 are drawn); `test_file028s_lift_has_no_traces_left_out`; `test_a_tape_lines_profile_gets_no_axis` (a local tape line, e.g. `FILE__007`).
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `test_plugin_profile_view.py test_plugin_profile_dock.py test_plugin_profile_true_distance.py test_plugin_profile_cut.py`, then those with `-m real_data`, and core+pure. Expected: all pass; existing tests unmodified.
- [ ] **Step 5: Commit and push** (`feat(m17c): a GPS line's profile at true distance, a lift one hatched gap (#134)`).

---

