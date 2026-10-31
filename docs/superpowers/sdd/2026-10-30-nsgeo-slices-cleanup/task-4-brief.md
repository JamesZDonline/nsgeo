### Task 4: Remember each grid's resolution (#71: core, session, This grid)

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/project.py` (`_clean_slice_source`, `_clean_site_view`, new `_clean_resolution`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py` (four accessors)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` (`_seeding`, `_on_resolution_edited`, `_restore_remembered_resolution`, `_seed_resolution_defaults`, `_seed_dz_z_defaults`, `_clamp_z_to_prepared`, `restore_cube`)
- Modify: `docs/guide/getting-started.md` (Step 7, item 3)
- Test: `packages/nsgeo-core/tests/test_project.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py`, `tests/qgis/test_plugin_slices_dock.py`

**Interfaces:**
- Produces (core): `_clean_resolution(value: object) -> dict[str, float]`. Anything but a dict gives `{}`. It keeps only `cell`, `dz_ns`, `t0_ns`, `t1_ns` and `radius_spacings`, each an `int` or `float` (never `bool`) that is finite. It also requires `cell > 0`, `dz_ns > 0` and `radius_spacings >= 0`. When both `t0_ns` and `t1_ns` survive and `t1_ns <= t0_ns`, both are dropped. `_clean_slice_source` and `_clean_site_view` store the result under `"resolution"` only when it is non-empty.
- Produces (session):
  - `SiteSession.slice_resolution(self, grid_id: str) -> dict[str, float]`: a copy of the grid's remembered resolution, or `{}`.
  - `SiteSession.remember_slice_resolution(self, grid_id: str, *, cell: float | None = None, dz_ns: float | None = None, t0_ns: float | None = None, t1_ns: float | None = None, radius_spacings: float | None = None) -> None`: merges the given fields into `slice_sources[grid_id]["resolution"]` through `_update_source`. `None` leaves a field as it is. The survey is marked dirty only when something changed. It keeps the entry's preset, lines and gain.
  - `SiteSession.site_resolution(self) -> dict[str, float]` and `SiteSession.remember_site_resolution(self, *, cell=None, dz_ns=None, t0_ns=None, t1_ns=None, radius_spacings=None) -> None`: the same, for `site_view["resolution"]`. Task 5 uses them.
- Produces (dock):
  - `SlicesDock._seeding: int`, a depth counter like `_updating`. It is raised around the whole bodies of `_seed_resolution_defaults`, `_seed_dz_z_defaults` and `_restore_remembered_resolution`.
  - `SlicesDock._on_resolution_edited(self, field: str, value: float) -> None`, a guarded slot connected through `functools.partial` to the five spins' `valueChanged`: `cell_spin` → `"cell"`, `dz_spin` → `"dz_ns"`, `z0_spin` → `"t0_ns"`, `z1_spin` → `"t1_ns"`, and `grid_radius_spin` → `"radius_spacings"`. It returns while `_updating` or `_seeding` is raised. In This grid scope with a grid selected and a survey open, it calls `session.remember_slice_resolution(grid_id, **{field: value})`. In site scope it does nothing yet; Task 5 fills that branch.
  - `SlicesDock._restore_remembered_resolution(self, grid_id: str | None) -> None`. It sets each remembered field onto its spin and remembers nothing. A remembered cell below the spin's minimum is clamped up by the spin itself, which `_seed_resolution_defaults` has already floored at `smallest_safe_cell`. It is called at the end of `_seed_resolution_defaults`, and at the end of `_seed_dz_z_defaults` whenever that method actually seeded. Remembered values therefore always land after the seed and are never overwritten by a later seed.
  - `_clamp_z_to_prepared` keeps its contract, plus one rule (Review Focus 1). If clamping would leave `z1 <= z0`, both ends are set to the prepared bounds instead. The remembered values are not touched, so a later crop that frees the range brings them back on the next grid change or reopen.
  - `restore_cube` remembers the cube's resolution: `cell`, `dz_ns`, `t0_ns` and `t1_ns` from `recipe.resolution` when present, and `radius_spacings` from the spin after `apply_view`, when `recipe.view` is present. It does this next to its existing `_remember_source` call.

- [ ] **Step 1: Write the failing core tests** in `test_project.py`, next to `test_slice_sources_and_site_view_round_trip`:
  - `test_a_remembered_resolution_round_trips`. A `slice_sources["A"]["resolution"]` with all five keys, plus a `site_view["resolution"]` with two, survive `save_site`/`load_site` unchanged.
  - `@pytest.mark.parametrize` `test_a_bad_remembered_resolution_value_reads_as_unset` (Review Focus 2). The cases are: `[]` for the whole `resolution`; `{"cell": "0.2"}`; `{"cell": 0}`; `{"cell": -1.0}`; `{"dz_ns": 0}`; `{"cell": True}`; `{"radius_spacings": -0.5}`; `{"t0_ns": 5.0, "t1_ns": 5.0}`; `{"t0_ns": 9.0, "t1_ns": 2.0}`; and `{"colour": 1}`. Each loads with no `"resolution"` key in the entry, for both the grid entry and the site view. Write the file with `json.dumps(..., allow_nan=True)` and add a NaN case, `{"dz_ns": float("nan")}`.
  - `test_a_partly_bad_resolution_keeps_its_good_values`: `{"cell": 0.1, "dz_ns": -1}` loads as `{"cell": 0.1}`.
- [ ] **Step 2: Run** `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_project.py -q -p no:cacheprovider` **and see them fail.** Then implement `_clean_resolution` and see them pass.
- [ ] **Step 3: Write the failing session tests** in `test_plugin_session.py`:
  - `test_remember_slice_resolution_merges_fields_and_keeps_the_source`. First `remember_slice_source("A", preset="p", lines=None)`, then `remember_slice_resolution("A", cell=0.1)`, then `(dz_ns=0.2)`. Assert `slice_source("A") == {"preset": "p", "lines": None, "resolution": {"cell": 0.1, "dz_ns": 0.2}}`.
  - `test_remembering_an_unchanged_resolution_does_not_dirty`.
  - `test_site_resolution_is_remembered_apart_from_each_grid`.
  - `test_removing_a_grid_drops_its_remembered_resolution`. This extends the existing prune tests' pattern.
- [ ] **Step 4: Run them, see them fail, implement the four accessors, and see them pass.**
- [ ] **Step 5: Write the failing dock tests** in `test_plugin_slices_dock.py`, with `docked_two_grids` and `_grid_keys`. After every spin change, call `dock.flush_debounce()` and `dock.engine.wait_for_preparation(20_000)` as the neighbouring tests do.
  - `test_a_resolution_edit_is_remembered_for_that_grid_only`. Set `cell_spin` to 0.1 and assert `session.slice_resolution("A") == {"cell": 0.1}`, `session.slice_resolution("B") == {}` and `session.dirty`.
  - `test_switching_grid_away_and_back_restores_that_grids_resolution`. On A set the cell to 0.1, dz to twice its seed, and the radius to 1.5. Switch to B and assert B shows its own seeds. Switch back and assert all three come back.
  - `test_seeding_never_remembers_a_resolution`. Switch A → B → A with no edit. Assert both `slice_resolution` are `{}` and `not session.dirty`.
  - `test_reopening_a_survey_restores_a_remembered_resolution_without_dirtying_it`. Copy the pattern of `test_reopening_a_survey_restores_a_remembered_source_without_dirtying_or_rewriting_it`. The new dock's spins show the remembered values, `not reopened.dirty`, and the record is unchanged.
  - `test_a_remembered_z_range_is_clamped_to_the_prepared_lines_but_kept`. With This grid on B, `session.remember_slice_resolution("A", ...)` a `t0_ns`/`t1_ns` wider than the data on both ends, then `session.save()`, then switch to A. After preparation, `z0_spin`/`z1_spin` sit at `engine.prepared_z_bounds()` (snapped as `_snap_inside` snaps), the record still holds the wide values, and the clamp has not marked the survey dirty.
  - `test_a_remembered_z_range_wholly_outside_the_data_falls_back_to_the_prepared_range` (Review Focus 1). Remember `t0_ns` beyond the data's end and `t1_ns` beyond that. After preparation, the spins equal the prepared bounds, no `error` was emitted, and a slice is drawn (`dock.current_values() is not None`).
  - `test_a_remembered_cell_below_the_grids_floor_is_clamped_to_it`. Remember `cell=0.001` and assert `cell_spin.value() == cell_spin.minimum()`.
  - `test_picking_a_saved_cube_remembers_its_resolution`. Save a cube at cell 0.1, change the cell, pick the cube, switch to B and back, and assert the cell is 0.1.
- [ ] **Step 6: Run them and see them fail. Implement the dock half, and see `test_plugin_slices_dock.py`, `test_plugin_site_scope.py` and `test_plugin_session.py` pass.** If a test that existed before this task now fails because an edit is remembered, that is a finding. Report it; don't loosen the guard.
- [ ] **Step 7: Update the guide.** Add one sentence to item 3: each grid remembers the resolution you set for it, and the survey saves it.
- [ ] **Step 8: Run all four verification commands and see them pass.**
- [ ] **Step 9: Commit.** `git commit -m "Slices: remember each grid's resolution settings (#71)"` and push.

---

