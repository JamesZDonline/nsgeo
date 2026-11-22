### Task 2: Migration at true spacing

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/processing/base.py` (`Radargram`), `packages/nsgeo-core/src/nsgeo/processing/migration.py` (`MigrateFk.apply`), `packages/nsgeo-core/src/nsgeo/geometry/spacing.py` (resample helpers)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py` (`_attach_source`; `edit_lines` re-attaches), `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py` (the `work` job's `Radargram.from_profile`)
- Test: `packages/nsgeo-core/tests/test_steps_migration.py`, `packages/nsgeo-core/tests/test_spacing.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_session_gps_grids.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py`

**Interfaces:**
- Consumes: Task 1's `usual_step`, `gap_steps`, `left_out`, `TrackPlacement.gap_m`.
- Produces:
  - `Radargram.trace_x_m: np.ndarray | None = None` and `Radargram.gap_m: float | None = None`, after the existing fields. `__post_init__` raises `ValueError` when `trace_x_m` is given with a length other than `n_traces`. `replace()` keeps both.
  - `Radargram.from_profile(profile, *, trace_x_m=None, gap_m=None)`.
  - `spacing.resample_even(data, x_m, gap_m=None) -> tuple[np.ndarray, float, float]` — `(even, x0, step)`: columns at `x0 + k*step`, `step = usual_step(x_m)`, over the walk direction; each column linearly interpolated from the two nearest drawn traces (left-out traces are not used); 0 where the column lies inside a gap more than half a step from both edge traces.
  - `spacing.sample_back(even, x0, step, x_m) -> np.ndarray` — each trace's column, linearly interpolated at its own distance.
  - `MigrateFk.apply`: with `trace_x_m` given and not evenly spaced (steps equal to within `1e-9` relative), resample → `migrate_fk(..., dx_m=step)` → sample back; otherwise exactly today's call with `rg.dx_m`.
  - Plugin: `nsgeo_qgis.session.source_radargram(line: Line, profile: Profile) -> Radargram` — `Radargram.from_profile(profile, trace_x_m=line.distance_along(), gap_m=line.placement.gap_m)` for a `TrackPlacement`, `Radargram.from_profile(profile)` otherwise. Used by `_attach_source` and the slices engine's job. `edit_lines` re-attaches the source of every GPS line whose placement changed and emits `stack_changed` for it.

- [ ] **Step 1: Write the failing tests.**
  - `test_steps_migration.py`:
    - `test_an_even_trace_axis_migrates_exactly_as_dx` — same record with `dx_m=0.02` and with `trace_x_m=np.arange(n)*0.02`: `np.testing.assert_allclose(a, b, atol=1e-9 * np.abs(a).max())`.
    - `test_an_uneven_line_focuses_a_diffraction_where_an_even_one_does` — a point diffractor (apex 2.0 m, 20 ns, v = 0.1 m/ns) sampled at steps alternating 0.015 and 0.025 m with one 0.6 m gap 1 m from the apex; after migration the strongest column is the trace nearest 2.0 m (within one usual step), and its peak is at least 0.8× the evenly sampled migration's peak.
    - `test_migration_keeps_the_trace_axis` — `result.trace_x_m is rg.trace_x_m` and `result.gap_m == rg.gap_m`.
    - `test_a_trace_axis_of_the_wrong_length_is_refused`.
  - `test_spacing.py`:
    - `test_nothing_is_invented_inside_a_gap` — data 1.0 either side of a 1.0 m gap: every even column more than half a step from both edge traces is 0.
    - `test_left_out_traces_do_not_feed_the_resample` — left-out traces hold 1e6, the rest 1.0: `even.max() <= 1.0`.
    - `test_sample_back_returns_each_trace_at_its_own_distance` — `sample_back(*resample_even(d, x), x)` equals `d` on drawn traces to 1e-9 for data linear in x.
  - `test_plugin_session_gps_grids.py`:
    - `test_a_gps_lines_source_carries_its_walked_distance_and_gap_over` — `stack_for(key).source.trace_x_m` equals `line.distance_along()` and `.gap_m` the placement's; a tape line's source has `trace_x_m is None`.
    - `test_a_destagger_edit_reattaches_a_gps_lines_source` — a `TrackEdit` with `travel_shift=0.2`: the source's `trace_x_m` moves by 0.2, and `stack_changed` is emitted for the key.
  - `test_plugin_slices_engine.py`: `test_slices_build_a_gps_lines_record_with_its_walked_distance` — monkeypatch `session.source_radargram` to record its calls; preparing a grid holding a GPS line calls it with that line.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.** The resample's extent runs from the first to the last drawn trace; the walk direction follows the sign of `x_m[-1] - x_m[0]` so a falling distance resamples the same as its reverse.
- [ ] **Step 4: Run core+pure in full and the two QGIS files.** Expected: all pass.
- [ ] **Step 5: Commit and push** (`feat(m17c): GPS lines migrate at their true spacing, with nothing invented in a gap (#134)`).

---

