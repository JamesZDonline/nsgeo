### Task 5: Whole site through the panel; retire the disc fill; the guide

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/site_engine.py`:
  - `_shown(top_ns, thickness_ns, finish, method, manual, coverage)` computes `a * self._engines[g].finish(values, cov, finish) + b`;
  - `slice_at(..., *, finish: SliceFinish, method, manual, coverage=False)`;
  - `shared_limit(..., *, finish, method, manual)`;
  - add `weights_cached(finish) -> bool`, true when every ready engine's weights are cached.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`:
  - remove `radius_spacing_spin`;
  - add `self.site_finish = FinishPanel(metres_label=False)` beside `grid_finish`;
  - drop the `radius_spacings` branch in `_on_resolution_edited`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py`:
  - `show_scope_widgets` shows `site_finish` in Whole site and `grid_finish` in This grid;
  - `enter` restores the site's remembered finish quietly;
  - `site_finish.edited` leads to `remember_site_resolution(**{field: value})` (user edits only), `refresh_rows()` and `schedule_refresh()`;
  - `radius_tooltip` is replaced by `max_distance_tooltip`, set on `site_finish.max_distance_spin`;
  - the `limit_cache` key holds `site_finish.value()`;
  - every `slice_at` / `shared_limit` call passes `finish=`;
  - the tick wraps a refresh in `busy_cursor()` while `not engine.weights_cached(finish)`;
  - remove `set_radius_quietly` and `_on_radius_changed`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/site_export.py`:
  - `SiteExportPlan.radius_spacings` becomes `finish: SliceFinish | None`;
  - `plan_site_export` and `export_site` take `finish=`;
  - metadata;
  - `write_site_coverage` replaces with `finish=None`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`. `export_site_geotiff` passes `finish=dock.site_finish.value()`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`. Delete `DEFAULT_RADIUS_SPACINGS` and `radius_cells_for`. Rewrite the `Resolution` docstring line about the fill radius.
- Modify: `packages/nsgeo-core/src/nsgeo/project.py`. Remove `radius_spacings` from `_RESOLUTION_KEYS`, so an old one is dropped on load.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py`. Remove the `radius_spacings` keyword arguments.
- **Delete:**
  - `packages/nsgeo-core/src/nsgeo/slices/fill.py` and `packages/nsgeo-core/tests/test_slices_fill.py`;
  - `fill`, `disc_kernel` and `clear_kernel_cache` from `nsgeo.slices` and `__all__`;
  - the `clear_kernel_cache()` call and import in `slices_engine.py`.
- Modify: `packages/nsgeo-qgis/scripts/bench_site.py` to use `finish=SliceFinish()` in place of `radius_spacings`.
- Modify: `docs/guide/getting-started.md`.
  - Rewrite step 3 so it no longer mentions Fill radius.
  - Add an **Interpolation** step after it covering Method, Max distance to data, and Smoothing X and Y, in the guide's existing plain style for archaeologists, with one sentence on when to pick each method. Renumber the steps that follow.
- Test:
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_site_engine.py`
  - `test_plugin_site_scope.py`
  - `test_plugin_site_export.py`
  - `packages/nsgeo-core/tests/test_project.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces:
  ```python
  # site_scope.py
  def max_distance_tooltip(session: Any, included: Iterable[str], spacings: float) -> str: ...
  ```
  The tooltip returns the Max distance copy from Task 3, then `" (in each grid's own line spacings, so grids with different spacings are treated alike)"`, then a new line, then `"A 0.25 m · B 0.50 m"`-style metres per included grid.
- **Site metadata keys:**
  - `NSGEO_SITE_INTERPOLATION`;
  - `NSGEO_SITE_MAX_DISTANCE_SPACINGS`, `NSGEO_SITE_SMOOTH_X_M`, `NSGEO_SITE_SMOOTH_Y_M` (`str(float)`).
  - The coverage companion carries none of them. `NSGEO_SITE_FILL_RADIUS_SPACINGS` is gone.

- [ ] **Step 1: Write the failing tests.**

  Site engine:
  - `test_site_slices_are_each_grids_finished_slice_times_its_gain`.
  - `test_site_gains_commute_with_every_method`: for `none`, `idw` and `kriging`, `a * engine.finish(v) + b` is allclose to `engine.finish(a * v + b)`, with `a=1.7`, `b=-0.3`.
  - `test_site_shared_limit_measures_finished_slices`.

  Site scope:
  - `test_each_scope_shows_its_own_interpolation_panel`.
  - `test_a_site_finish_edit_is_remembered_for_the_site_not_the_grid`.
  - `test_entering_the_site_restores_its_remembered_finish_quietly`: not dirty.
  - `test_a_site_finish_edit_redraws`.
  - `test_the_max_distance_tooltip_gives_each_grids_metres`: exact text for `site3`.

  Site export:
  - `test_the_site_geotiff_carries_interpolation_metadata`.
  - `test_the_site_coverage_companion_has_no_interpolation_metadata`.

  Core: flip `test_an_old_radius_spacings_still_loads` to `test_an_old_radius_spacings_is_dropped_on_load`.

- [ ] **Step 2: Run them and see them fail.**

- [ ] **Step 3: Implement**, then make the deletions.

- [ ] **Step 4: Sweep for leftovers.**
  - Run `grep -rnE "radius_spacings|radius_cells|Fill radius|DEFAULT_RADIUS|disc_kernel|clear_kernel_cache|fill\(|FILL_RADIUS" packages docs/guide`.
  - Expected: no hits, apart from `map_link.py`'s unrelated hit radius. List anything else you kept, and why, in your report.

- [ ] **Step 5: Run every suite, ruff and mypy.** The skip count must equal the baseline.

- [ ] **Step 6: Commit.**

  ```bash
  git commit -m "feat(slices): Whole site through the Interpolation panel; retire the disc fill; guide (interpolation spec §8)"
  git push
  ```

---

## After Task 5 (coordinator)

These are the manual checkpoints from spec §10. Track them and report them; never pass them silently.

1. **Build and deploy.** Deploy to a fresh QGIS profile on ns-geo, then hold the §10.1 walkthrough on the user's real grids. Leave out the minimum-curvature item. Confirm:
   - no polka dots and no holes at defaults;
   - a skipped line shows as blank;
   - Smoothing X and Y each act along the expected axis;
   - depth scrubbing is live;
   - site scope, saved cubes and exports all carry the settings.
2. **Offer the early kriging read.** Offer the user an early look at kriging against their Surfer grids (spec §12). The formal comparison waits for milestone B.
