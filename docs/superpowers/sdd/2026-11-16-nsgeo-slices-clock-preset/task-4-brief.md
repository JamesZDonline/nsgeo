### Task 4: #163 items 3 and 6: a time field before the samples load, and the test gaps

Spec §6. Suggested implementer tier: sonnet.

**Files:**
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py`: `input_axis`, `time_axis`,
    `_show_form`, the new `_on_line_loaded`;
  - `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`: only the comment that says ProcessingDock never
    reacts to `line_loaded`;
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py`: `grid_time_bases`, and the
    `SiteScope.warnings` docstring;
  - `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`: `prepared_steps`.
- Test:
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py`;
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_velocity_fit.py`;
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py`.

**Interfaces:**
- Produces:
  - `ProcessingDock.input_axis(self, row: int) -> tuple[float, float, int] | None`. It returns
    `None` when the stack has no source and an enabled `time_zero` entry sits above `row`.
    Otherwise it is unchanged.
  - `ProcessingDock.time_axis(self) -> tuple[float, float, int]`. When `input_axis` is `None`, it
    returns `(0.0, header.dt_ns, header.n_samples)`: on the time-zero clock the record starts at 0
    and has at most that many samples, so a cutoff seeded at its end is a no-op.
  - `SliceEngine.prepared_steps -> tuple[dict[str, Any], ...]`, a property returning `self._steps`.
  - `site_scope.grid_time_bases(session, source, site_engine)`, with `site_engine` now required.

- [ ] **Step 1: Write the failing tests**
  - `test_a_time_field_behind_time_zero_is_unbounded_until_the_samples_load`: a session whose
    line is opened before `set_profiles` (so `stack.source is None`), with a `time_zero` step and
    then a `time_cutoff` step.
    1. Select the cutoff row. The `end_ns` editor's range is not the header's radar-clock range.
       `param_form`'s unbounded case is what a missing `time_range` gives; see
       `test_a_cutoff_without_a_range_is_effectively_unbounded`.
    2. `session.set_profiles(key, line.load())`. The editor's minimum and maximum are now
       `zeroed.t0_ns + zeroed.dt_ns` and `zeroed.t0_ns + zeroed.n_samples * zeroed.dt_ns`, with
       `zeroed = stack.intermediate(0)`.
  - `test_a_cutoff_added_behind_time_zero_before_the_samples_load_crops_nothing`: the same
    unloaded line with a `time_zero` step. `dock.add_step("time_cutoff")`, then load the profiles.
    `stack.result().n_samples == stack.intermediate(0).n_samples`.
  - `test_a_saved_curve_is_drawn_on_the_shown_clock` (`test_plugin_velocity_fit.py`): a line with a
    `time_zero` step and a saved fit.
    1. `before = dock.velocity_curve_points(fit, distance, zero=z)`.
    2. Monkeypatch `dock.shown_zero_ns` to `lambda: z + 1.0`, then take `after` the same way.
    3. Every `after` time is the matching `before` time minus 1.0 (abs 1e-9).

    In your report, show that it fails with the `retime_ns` call removed from
    `velocity_curve_points`.
  - In `test_plugin_site_scope.py`:
    - rewrite `test_grid_time_bases_reads_each_grids_preset` to pass `dock.site_engine` before
      Whole site is entered: no grid has been prepared, so each is read from its preset;
    - add `test_a_grid_with_no_lines_has_no_clock`. A grid with no lines is left out of
      `grid_time_bases`, as a failed one is.

- [ ] **Step 2: Run them; the two processing tests fail, and the velocity test passes (it pins
  today's code)**

- [ ] **Step 3: Implement**
  - `input_axis` and `time_axis`, as in Interfaces. `_show_form` passes neither `time_range` nor
    `time_step` when `input_axis` is `None`.
  - `ProcessingDock` connects `session.line_loaded` to `_on_line_loaded(key)`, a guarded slot. For
    the line it shows, it re-shows the current row's form: reset `self._shown`, then `_show_form`.
    Update `plugin.py`'s comment that says ProcessingDock never reacts to `line_loaded`.
  - `prepared_steps`, used by `grid_time_bases` in place of `provenance().steps`. `grid_time_bases`
    loses its preset-only mode.
  - The `SiteScope.warnings` docstring says that queued and preparing grids are counted from their
    presets.

- [ ] **Step 4: Run the task's tests, `test_plugin_processing_dock.py`, `test_plugin_param_form.py`,
  `test_plugin_time_cutoff.py`, `test_plugin_site_scope.py` and the pure tier
  (`test_no_orphan_signals.py` included); all pass**

- [ ] **Step 5: Commit**

---

## After the tasks (the coordinator)

1. The full QGIS tier, the pure and core tiers, ruff, and green CI on the pushed head.
2. A whole-branch review (opus), then any fix wave.
3. Deploy to its own profile, `ns_geo_clock`, with a sandbox copy of the campus and GPS surveys in
   `~/nsgeo-clock-walk/`. Make the pre-#97 cube there by stripping `time_base` from a copied
   record and its npz.
4. **Human gate:** the walkthrough artifact (spec §10). Stop for the author's results. Merging asks
   first.
