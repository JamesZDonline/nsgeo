# Slices Panel Cleaning Round Implementation Plan (#74, #70, #72, #71, part of #75 and #54)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every code task is written test-first with superpowers:test-driven-development: the failing test is run and seen to fail before any production code is written.

**Goal:** Fix the papercuts in the Slices panel that the M12 walkthrough left behind. Both scopes read a grid's line choice the same way. *This grid* opens the grid selected in the site list. *This grid*'s fill radius is set in line spacings. Each grid, and the site view, remembers its resolution settings. A short list of test and docstring tidy-ups closes the round.

**Architecture:** Nearly all of the change is in the plugin's Slices dock (`ui/slices_dock.py`) and its Whole-site controller (`ui/site_scope.py`), plus the line chooser. The resolution memory adds one optional key, `resolution`, to the records M12 already persists: `Site.slice_sources[grid_id]` and `Site.site_view`. The core's tolerant loader cleans that key, and `SiteSession` gains accessors for it. The saved-survey schema version does not change, because an older build drops the unknown key on load.

**Tech Stack:** Python 3, numpy (core); PyQt via `qgis.PyQt` (plugin); pytest on two tiers (core+pure in `.venv`, QGIS in `.venv-qgis`).

**Spec:** No spec file. The user approved the behaviour in chat on 2026-10-30. The issues are the requirements, so read each one in full before its task: `gh issue view 74` (and 70, 72, 71, 75, 54). The behaviour the user approved, with the coordinator's calls marked, is copied under **Approved behaviour** below. Where this plan and an issue disagree, the plan wins: it records the decisions.

## Approved behaviour

1. **#74, one reading of the line record.** The line chooser, which both scopes share, greys out OK while no line is ticked *(call: greyed out, with the tooltip "Tick at least one line.")*. A remembered line choice that filters to nothing on the grid means *every line*, in both scopes. *Whole site* never shows such a grid as `no lines`. Only the site list's tick boxes take a grid out of the site. An old cube record with no `lines` key restores every line.
2. **#70 and #75 F-9.** If a row is selected in the site list and it names a grid other than *This grid*'s, switching to *This grid* opens that grid at the same window time, with that grid's remembered preset, lines and (after Task 4) resolution. With no such selection, *This grid* comes back exactly as it was left, as it does today. *(Call: the switch is not a source choice, so nothing is remembered and the survey is not marked dirty by it.)* The hand-back of This grid's grid-move hook runs from a `finally`.
3. **#72.** *This grid*'s Fill radius is set as `× line spacing`, like *Whole site*: range 0–10, 2 decimals, step 0.25, seeded at 0.5. The radius in metres is shown in a label beside the box *(call: beside it, not in a tooltip, since there is one grid)*. Saved cube records keep `radius_m` in metres. Opening an old record converts it to spacings, so the picture comes back the same. The GeoTIFF still records the radius in cells.
4. **#71.** Each grid remembers its cell size, dz, z0, z1 and fill radius (in spacings), saved in the survey. *Whole site* remembers its own set. A value is remembered only when the user changes it, so seeds, restores and clamps never write anything, and opening a survey never marks it dirty. Each field is remembered on its own *(call)*: changing the cell does not freeze a z range that was only seeded. Opening a saved cube counts as a choice: its settings become that grid's remembered ones *(call, matching how a cube's preset and lines are already remembered)*. A remembered z range is still clamped to what the prepared lines cover, and a remembered cell still respects the grid's size floor. Slice thickness and step are not included.
5. **Tidy-ups.** From #75: the unguarded `_note_z_edit` slot (removed in Task 5), the stale `_remember_source` docstring, the missing "opening a survey that has saved cubes stays clean" test, the import pick-up test that dodges the save → reopen → import path, the self-comparing velocity assertion, the `ds = None` pattern in M11's export tests, and the untested site seeding rules (pinned in Task 5). From #54's slice-preview section: the two wrong docstrings and the persistent-failure test that fakes its failure.

Out of scope: #73 (slider lag; the user deferred it), #47, #50, and every other #75 item.

## Global Constraints

- Every slot connected to a Qt signal or timer guards its own body and reports through `_log` or `dock.error`, never raises (an exception escaping a slot aborts the CI container). Read the module docstrings of `slices_dock.py` and `site_scope.py` before touching either.
- R-P5 stands: This grid's engine never starts a preparation while a site task is live. Every This-grid preparation goes through `SlicesDock.prepare()` or `_run_pending_grid_prepare()`, never `engine.set_source` directly.
- Opening a survey, switching scope, seeding, restoring and clamping never mark the survey dirty and never write a remembered value. Only a user's edit, a line choice, or picking a saved cube writes one.
- Old surveys and old cube records keep loading. `SCHEMA_VERSION` does not change. The loader stays tolerant: a remembered value of the wrong type or out of range reads as unset and never blocks opening.
- Core stays numpy-only, with no Qt imports. `packages/nsgeo-core/tests/test_boundary.py` and `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py` stay green. The plugin imports Qt only through `qgis.PyQt`.
- Remembered resolution keys are exactly `cell`, `dz_ns`, `t0_ns`, `t1_ns`, `radius_spacings`. The first four are the names a cube record and `Resolution` already use.
- Comments and docstrings follow the file they are in: they say why, and cite the issue (`#74`) the way the existing ones cite rulings.
- ruff 0.17.1 and mypy 2.4.0, as pinned in CI.
- End every commit message with the `Co-Authored-By` trailer the coordinator gives you. Push each commit to `origin nsgeo-slices-cleanup` as it is made.

## Verification commands (exactly these, from the worktree root)

- core + pure: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider`
- qgis: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:cacheprovider -p no:xonsh` (about 11 minutes; run single files while iterating)
- lint: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- types: `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`

Baseline at `7069959`, with the real DZT files copied into `packages/nsgeo-core/tests/data/local/`: core+pure **808 passed, 3 skipped**; qgis **1320 passed**. A real-data test that skips has validated nothing, so check the skip count stays at 3.

## Review Focus

These are the inputs most likely to hurt a user that the issues don't name. Each is pinned by a test in the task named.

1. **A remembered z range wholly outside what the lines now cover.** For example, z0 = 80 ns is remembered, then a time cutoff crops the lines at 50 ns. Clamping each end on its own gives z1 < z0, and every slice then fails with a `Resolution` error. Expected: fall back to the prepared range and keep the remembered values (Task 4: `test_a_remembered_z_range_wholly_outside_the_data_falls_back_to_the_prepared_range`; Task 5: the site's twin).
2. **A hand-edited or damaged survey file.** Examples: `resolution` is a list, a cell given as a string, a zero or negative cell or dz, NaN, a negative radius, `t1_ns <= t0_ns`, a boolean. Expected: each bad value reads as unset, and the survey opens (Task 4: `test_a_bad_remembered_resolution_value_reads_as_unset`).
3. **A grid's line spacing edited after its radius was set.** The radius is in spacings, so the metres label and `radius_cells()` must follow the new spacing without a grid switch (Task 3: `test_the_radius_follows_a_line_spacing_edit`).
4. **The selected site row's grid removed while Whole site shows.** Expected: switching to *This grid* falls back to today's behaviour and never raises (Task 2: `test_a_selected_grid_removed_meanwhile_falls_back_to_this_grids_own`).
5. **A cube saved on a grid whose spacing has changed since.** The record's `radius_m` is metres and the box is spacings, so the conversion must use the grid's spacing at restore time, keeping the metres (Task 3: `test_a_cube_saved_before_a_spacing_edit_keeps_its_radius_in_metres`).

---

### Task 1: One reading of a grid's line choice (#74)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py` (`source_keys`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/line_choice_dialog.py` (`_refresh`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` (`restore_cube`, and its docstring paragraph about `recipe.choice.line_keys`)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_line_choice_dialog.py`, `tests/qgis/test_plugin_site_scope.py`, `tests/qgis/test_plugin_slices_dock.py`

**Interfaces:**
- Produces: `site_scope.source_keys(session, grid_id, by_grid=None) -> tuple[str, ...]`, with the same signature. The remembered lines still on the grid, in survey order. If none is remembered (`None`), or the remembered list filters to nothing, it returns every line on the grid. That is the rule `SlicesDock._restore_remembered_source` already applies.
- Produces: `LineChoiceDialog.buttons.button(QDialogButtonBox.StandardButton.Ok)` is disabled exactly while `included_keys()` is empty, with the tooltip `"Tick at least one line."` while disabled and no tooltip while enabled.

- [ ] **Step 1: Write the failing tests.**
  - `test_plugin_line_choice_dialog.py`: `test_ok_is_greyed_out_while_no_line_is_ticked`. Open the dialog on a grid with lines, all ticked, and assert OK is enabled. Call `select_none()` and assert OK is disabled with the tooltip `"Tick at least one line."`. Tick one row through `set_included(key, True)` and assert OK is enabled. Also `test_ok_is_greyed_out_on_a_grid_with_no_lines`.
  - `test_plugin_site_scope.py`, using `plugin`/`site3`:
    - `test_both_scopes_read_a_line_choice_that_left_the_grid_as_every_line`. Call `plugin.session.remember_slice_source("A", preset="p", lines=("raw/gone/X.DZT",))`. Assert `dock.line_choice_keys("A")` in This grid equals `site3.keys("A")` once `rebuild_source()` has run and This grid has left and come back to A. Then `whole_site(plugin)`. Assert `site_scope.source_keys(plugin.session, "A") == site3.keys("A")`, `dock.site_engine.engine_for("A").line_count == 4`, and that the A row's `lines` column reads `"4 / 4"` and its state is not `"no lines"`. Read the row through `site_scope.site_rows(...)`, or the panel's model, whichever the existing tests use.
    - `test_removing_every_remembered_line_reads_as_every_line_in_both_scopes`. Remember A's first two keys as its lines, then `plugin.session.remove_lines(those two keys)`. Assert both scopes now use A's remaining two lines.
    - `test_a_source_edit_after_emptying_does_not_change_what_the_site_prepares`. Remember lines that have all left A. In This grid, change the preset to `"raw"`, which rewrites the record as `lines: None`. Then `whole_site(plugin)` and assert A's line count is 4, the same as before the edit.
  - `test_plugin_slices_dock.py`, using `docked_two_grids` and `_save_cube`: `test_an_old_cube_record_without_lines_restores_every_line`. Save a cube from a two-line choice, delete the `"lines"` key from `session.site.cubes[cube_id]`, pick it in `cube_combo`, and assert `dock.included_keys() == _grid_keys(session, "A")` and `session.slice_source("A")["lines"] is None`.

- [ ] **Step 2: Run them and see them fail.**
  Run: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_line_choice_dialog.py packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py -q -p no:cacheprovider -p no:xonsh -k "greyed or every_line or emptying or without_lines"`
  Expected: FAIL. OK is never disabled, the site reads the choice as `()`, and the old cube restores no lines.

- [ ] **Step 3: Implement.** In `source_keys`, return every line when the filtered tuple is empty. Update its one-line docstring. In `LineChoiceDialog._refresh`, set the OK button's enabled state and tooltip from `self._included` after the table is rebuilt. Every path that changes the ticks (`set_included`, `select_all`, `select_none`, an item click) already ends in `_refresh`. In `restore_cube`, after `self._included = recipe.choice.line_keys`, set `self._included = self._default_included(recipe.choice.grid_id)` and `self._included_is_default = True` when `recipe.choice.line_keys` is empty. Rewrite the docstring paragraph that defended the empty set: say that an old record names no line list, the remembered record already says every line (D4), and #74 makes This grid show what the record says.

- [ ] **Step 4: Run the three files in full and see them pass.** Any existing test that pinned the old empty-set reading is wrong under #74. Correct it, and name it in the commit message.

- [ ] **Step 5: Commit.** `git commit -m "Slices: read an emptied line choice as every line in both scopes (#74)"` and push.

---

### Task 2: This grid opens the grid selected in the site list (#70, #75 F-9)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` (`_resume_grid`, two new private helpers)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py`

**Interfaces:**
- Consumes: `SiteSourcePanel.selected_grid() -> str | None` (`ui/site_panel.py`), and Task 1's `source_keys`.
- Produces: `SlicesDock._grid_to_resume(self) -> str | None`. The site panel's selected grid, when it is offered by `grid_combo` and differs from `grid_combo.currentText()`; otherwise `None`.
- Produces: `SlicesDock._switch_resumed_grid(self, grid_id: str) -> None`. Selects `grid_id` in `grid_combo` inside the `_updating` guard, so `_on_source_changed` does not fire. Then it runs `_sync_included()`, whose grid-changed branch re-seeds the resolution and restores the grid's remembered source, and calls `_mark_cube_unsaved()`, `_update_included_label()` and `_refresh_source_status()`. Finally it sets `_grid_prepared_away = False` and `_grid_prepare_pending = True`. It does not call `_remember_source` (Approved behaviour 2), and it does not restore `_grid_spins` or `_grid_palette`, which belong to the grid that was left.
- `_resume_grid(top)` keeps its signature. Its body is wrapped in `try`/`finally`, and the `finally` calls `self._run_pending_grid_prepare()` (#75 F-9). With a target grid it calls `_switch_resumed_grid`, then sets `_pending_top_ns = top` and `_sync_grid_slider()`. Without one it does exactly what it does today.

- [ ] **Step 1: Write the failing tests** in `test_plugin_site_scope.py`:
  - `test_this_grid_opens_the_grid_selected_in_the_site_list`. Enter `whole_site(plugin)`, `dock.site_panel.select_grid("B")`, note the site's top time, then `dock.grid_scope_button.click()`. Assert `dock.grid_combo.currentText() == "B"`, then `dock.engine.wait_for_preparation(20_000)`, `dock.engine.choice.grid_id == "B"`, and the slider's top time within `dz/2` of the site's, as `test_switching_scope_keeps_the_window_time` measures it. Also assert `not plugin.session.dirty`.
  - `test_this_grid_opens_the_selected_grid_with_its_remembered_source`. Before entering the site, `remember_slice_source("B", preset="raw", lines=site3.keys("B")[:2])`. Select B in the site and switch back. Assert the preset combo reads `"raw"` and `dock.included_keys() == site3.keys("B")[:2]`.
  - `test_with_this_grids_own_grid_selected_it_comes_back_as_it_was_left`. Leave the selection on A, which is the default on entering. Assert This grid's cell spin and palette are what they were before entering, and `dock.engine.choice.grid_id == "A"`.
  - `test_opening_the_selected_grid_waits_for_a_site_task_that_outlived_its_cancel`. Copy the set-up of `test_leaving_the_site_waits_out_a_task_that_outlived_its_cancel`: `_CANCEL_TIMEOUT_MS = 1`, a `LoadCounter` with `delay=0.15`. Select B, then click This grid. Assert `dock.site_engine.has_live_task` and `not dock.engine.is_running`, then that it settles prepared on B with `counter.max_concurrent == 1`.
  - `test_a_selected_grid_removed_meanwhile_falls_back_to_this_grids_own`. Select C in the site, then `plugin.session.remove_grid("C", with_lines=True)`. Read the call's exact signature in `session.py`. Click This grid. Assert the combo reads `"A"` and no error was emitted. Connect `dock.error` to a list.
  - `test_a_failure_inside_resume_still_hands_this_grids_moves_back`. Enter the site and let it settle. Monkeypatch `dock._refresh_source_status` to raise `RuntimeError` once. Call `dock.set_scope("grid")` inside `pytest.raises(RuntimeError)`. Assert `dock.engine.on_grid_moved is None`.

- [ ] **Step 2: Run them and see them fail.**
  Run: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py -q -p no:cacheprovider -p no:xonsh -k "selected or resume"`
  Expected: the B tests and the F-9 test fail. The "as it was left" and "removed meanwhile" tests may already pass. They pin today's path, so they stay.

- [ ] **Step 3: Implement** the two helpers and the new `_resume_grid`. Update `_resume_grid`'s docstring to the rule in Approved behaviour 2, and cite #70 and F-9.

- [ ] **Step 4: Run `test_plugin_site_scope.py` and `test_plugin_slices_dock.py` in full and see them pass.**

- [ ] **Step 5: Commit.** `git commit -m "Slices: This grid opens the grid selected in the site list (#70)"` and push.

---

### Task 3: This grid's fill radius in line spacings (#72)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` (the Fill radius row, `radius_cells`, `view_settings`, `apply_view`, `restore_cube`, `_seed_resolution_defaults`, `rebuild_source`, the debounce wiring)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py` (`show_scope_widgets`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py` (module docstring mentions of `radius_spin`)
- Modify: `docs/guide/getting-started.md` (Step 7, item 3)
- Test: `tests/qgis/test_plugin_slices_dock.py`, `tests/qgis/test_plugin_site_scope.py`, `tests/qgis/test_plugin_slice_export_dialogs.py`

**Interfaces:**
- Consumes: `slices_plan.radius_cells_for(spacing_m, radius_spacings, cell) -> int` and `slices_plan.DEFAULT_RADIUS_SPACINGS`.
- Produces: `SlicesDock.grid_radius_spin: QDoubleSpinBox`, which replaces `radius_spin`. The rename is deliberate: every test and caller that read metres has to be revisited, not silently reinterpreted. Range 0.0–10.0, 2 decimals, single step 0.25, suffix `" × line spacing"`, constructed at 0.0, seeded to `DEFAULT_RADIUS_SPACINGS` on a grid change.
- Produces: `SlicesDock.grid_radius_metres: QLabel`, reading `f"= {metres:.3g} m"` for the selected grid, or empty with no grid. It sits beside the spin in one form row whose field is `SlicesDock.grid_radius_row: QWidget`, with no margins. `site_scope.show_scope_widgets` toggles `dock.grid_radius_row` where it toggled `dock.radius_spin`.
- Produces: `SlicesDock._grid_spacing(self) -> float | None`, the selected grid's `default_spacing`, or `None`.
- Produces: `SlicesDock.radius_cells(self) -> int`, which is `radius_cells_for(spacing, grid_radius_spin.value(), cell_spin.value())`, or 0 with no grid.
- Produces: `SlicesDock.apply_view(self, view: ViewSettings, *, spacing_m: float) -> None`. It sets `grid_radius_spin` to `view.radius_m / spacing_m` (0.0 when `spacing_m <= 0`), still with signals blocked. `restore_cube` passes the record's grid's current `default_spacing`, which is why the grid must be known before `apply_view` runs. `view_settings()` records `radius_m = grid_radius_spin.value() * spacing` (0.0 with no grid). `ViewSettings` and the cube record format are unchanged.
- The metres label is refreshed by `_update_radius_metres(self) -> None` on the spin's `valueChanged`, at the end of `_seed_resolution_defaults`, and in `rebuild_source`. `rebuild_source` runs on `grids_changed`, which a spacing edit emits. The spin's `valueChanged` still starts the shared debounce, as `radius_spin`'s did.

- [ ] **Step 1: Write the failing tests** in `test_plugin_slices_dock.py`. `GRID.default_spacing` is 0.5.
  - `test_this_grid_sets_the_fill_radius_in_line_spacings`. After the grid is seeded: `grid_radius_spin.suffix() == " × line spacing"`, `value() == 0.5`, `singleStep() == 0.25`, `grid_radius_metres.text() == "= 0.25 m"`, and `radius_cells() == round(0.25 / dock.cell_spin.value())`.
  - `test_the_metres_beside_the_radius_follow_the_box`. Set the spin to 1.5 and assert the label reads `"= 0.75 m"` and `radius_cells()` follows.
  - `test_the_radius_follows_a_line_spacing_edit` (Review Focus 3). `session.replace_grid(dataclasses.replace(GRID, default_spacing=1.0))`. Assert the label reads `"= 0.5 m"` and `radius_cells()` doubled, with the spin still at 0.5.
  - `test_a_saved_cube_records_its_radius_in_metres`. Spin at 1.5 on spacing 0.5 gives `dock.view_settings().radius_m == pytest.approx(0.75)`.
  - `@pytest.mark.parametrize("radius_m", [0.0, 0.25, 0.5, 0.75])` `test_an_old_cubes_radius_reopens_with_the_same_radius_in_cells`. Save a cube whose view has `radius_m`, move the spin elsewhere, pick the cube, and assert `grid_radius_spin.value() == pytest.approx(radius_m / 0.5)` and `radius_cells() == max(0, round(radius_m / cell))`.
  - `test_a_cube_saved_before_a_spacing_edit_keeps_its_radius_in_metres` (Review Focus 5). Save with `radius_m=0.5`, change A's spacing to 1.0, pick the cube, and assert the spin reads 0.5 and the label `"= 0.5 m"`.
  - Rewrite the existing `radius_spin` tests (lines ~638–700, ~1503, ~1524) in spacings. Their intent stays: the seeded default, the step size, and a radius of 0 showing the unfilled truth.
  - `test_plugin_site_scope.py`: in `test_the_scope_switch_swaps_the_source_controls`, the three `radius_spin` visibility asserts become `grid_radius_row` asserts.
  - `test_plugin_slice_export_dialogs.py`: `radius_spin.setValue(0.5)` and `(0.0)` become `grid_radius_spin` values that give the same metres on that test's grid spacing.

- [ ] **Step 2: Run the three files and see the new tests fail** (`AttributeError: grid_radius_spin`).

- [ ] **Step 3: Implement.** Write the tooltip for a radius in spacings: it fills cells no line crossed, within this many line spacings; the default is half a spacing, which just closes the gap between lines; 0 shows the unfilled truth. Update `slice_export.py`'s module docstring to name `grid_radius_spin`. Its construction default of 0 still means "unfilled".

- [ ] **Step 4: Update the guide.** In Step 7, item 3 of `docs/guide/getting-started.md`, say the Fill radius is set in line spacings, starts at 0.5, and shows its metres beside the box.

- [ ] **Step 5: Run the core + pure, qgis and lint commands, and see them pass.**

- [ ] **Step 6: Commit.** `git commit -m "Slices: set This grid's fill radius in line spacings (#72)"` and push.

---

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

### Task 5: Whole site remembers its resolution (#71), and its seeding rules are pinned (#75)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py` (`SiteScope.__init__`, `enter`, `forget`, `seed_resolution`, `seed_z_from_ready`, `_on_radius_changed`; remove `_note_z_edit`; new `set_radius_quietly`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` (`_on_resolution_edited`'s site branch)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py`

**Interfaces:**
- Consumes: Task 4's `site_resolution()`, `remember_site_resolution(...)` and `_on_resolution_edited`.
- `_on_resolution_edited`, site branch: when `self._scope == "site"`, for `cell`, `dz_ns`, `t0_ns` and `t1_ns`, call `session.remember_site_resolution(**{field: value})`. For `dz_ns`, `t0_ns` and `t1_ns`, also set `self._site.z_custom = True`. This replaces `SiteScope._note_z_edit`, which is deleted with its three connections; it was the unguarded slot #75 names. `grid_radius_spin` is hidden in site scope, so its field never arrives here.
- `SiteScope._on_radius_changed`: still guarded. While `self.showing and not self.dock._updating`, it also calls `session.remember_site_resolution(radius_spacings=value)`. Every programmatic set of `radius_spacing_spin` goes through the new `set_radius_quietly(dock: Any, value: float) -> None` (signals blocked).
- `SiteScope.forget()` also resets the radius to `DEFAULT_RADIUS_SPACINGS` through `set_radius_quietly`. Today a second survey inherits the first one's radius.
- `SiteScope.enter()` applies a remembered `radius_spacings` through `set_radius_quietly` before `refresh_rows()`.
- `SiteScope.seed_resolution(included)`: the seed runs as today. Remembered values are then laid over it quietly: `cell` right after the cell seed, which the floor clamps. If any of `dz_ns`/`t0_ns`/`t1_ns` is remembered, those are set after the z seed and `z_custom` becomes True, so `seed_z_from_ready()` clamps them from then on and never re-seeds them.
- `seed_z_from_ready()`, when `z_custom` is set: if clamping would leave `z1 <= z0`, set both to the snapped bounds instead (the Task 4 rule, Review Focus 1).

- [ ] **Step 1: Pin the existing seeding rules first** (#75 "seeding rules are untested"). These are characterisation tests and should pass on the current code. If one fails, stop and report: it has found a bug, and fixing it is not this task's call.
  - `test_the_site_cell_seeds_from_the_finest_spaced_grid`. Use `site3_factory`, then before opening, `site.session.replace_grid(dataclasses.replace(site.session.grid("B"), default_spacing=0.3))` and `save()`. Assert the site's cell is `default_cell(0.3, floor)`.
  - `test_the_site_includes_every_grid_with_lines_by_default`. Remove all of C's lines before opening, and assert `dock._site.included() == ("A", "B")`.
  - `test_the_site_cell_is_reseeded_only_when_the_included_grids_change`. Change the cell by hand, leave the site and come back, and assert the hand value is kept. Untick a grid and assert the cell is re-seeded.
- [ ] **Step 2: Run them and see them pass on the unchanged code.** Commit them on their own: `git commit -m "Slices: pin the site's resolution seeding rules (#75)"`.
- [ ] **Step 3: Write the failing tests.**
  - `test_a_site_resolution_edit_is_remembered_in_the_site_view`. `whole_site(plugin)`, set the cell by hand, `dock.flush_debounce()`. Assert `plugin.session.site_resolution() == {"cell": <value>}` and `plugin.session.slice_resolution("A") == {}`.
  - `test_entering_the_site_never_remembers_its_seeded_resolution`. `whole_site(plugin)`. Assert `site_resolution() == {}` and not dirty.
  - `test_the_site_resolution_survives_save_and_reopen`. Follow `test_the_site_view_survives_save_and_reopen`: set the cell, `t0_ns` and a radius of 1.25, save, close, and reopen through `open_plugin`. Enter the site and assert all three come back and the survey is not dirty.
  - `test_a_remembered_site_z_range_is_clamped_not_reseeded`, and `test_a_remembered_site_z_range_wholly_outside_the_data_falls_back_to_the_ready_range` (Review Focus 1, site twin).
  - `test_a_different_survey_starts_the_site_radius_from_the_default`. Set the radius in one survey, then open a second one, built by `site3_factory`, in the same plugin. Assert the site radius reads `DEFAULT_RADIUS_SPACINGS`.
  - `test_a_hand_z_edit_in_the_site_is_clamped_from_then_on`. This replaces whatever pinned `_note_z_edit`, so check the file for such a test first and keep its intent.
- [ ] **Step 4: Run them, see them fail, and implement.**
- [ ] **Step 5: Run all four verification commands and see them pass.**
- [ ] **Step 6: Commit.** `git commit -m "Slices: Whole site remembers its resolution settings (#71)"` and push.

---

### Task 6: Tidy-ups from #75 and #54

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` (`_remember_source` docstring)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slice_layer.py` (module docstring, `_sweep` docstring)
- Test: `tests/qgis/test_plugin_slices_dock.py`, `tests/qgis/test_plugin_site_scope.py`, `tests/qgis/test_plugin_slice_export.py`, `tests/qgis/test_plugin_slice_layer.py`

Each item names its source, so the PR can tick the matching box.

- [ ] **Step 1: #75, Survey memory, "one case has no test".** Add `test_opening_a_survey_that_has_saved_cubes_stays_clean` to `test_plugin_slices_dock.py`. With `docked_two_grids`, save a cube (`_save_cube`) and save the survey. Reopen it in a new `SiteSession` and `SlicesDock`, wait for the preparation, and assert `not reopened.dirty` and that `cube_combo` lists the cube. Dispose of the second dock as the reopen test does. It should pass at once. If it fails, report it.
- [ ] **Step 2: #75, Survey memory, "the import pick-up test half-dodges its hazard".** Add two tests next to `test_a_default_line_choice_picks_up_a_line_imported_later`:
  - `test_a_default_line_choice_picks_up_an_import_after_save_and_reopen`. Leave A's lines as the default, `session.save()`, and reopen in a new session and dock. Import `_line(tmp_path, "A", "FILE__099", 9.0)` there, and assert the new key is in `dock2.included_keys()`.
  - `test_an_explicit_line_choice_does_not_pick_up_an_import_after_save_and_reopen`. Do the same after `dock.set_included(a_keys[:2])`, and assert the new key is not included and `dock2.included_keys() == a_keys[:2]`.
- [ ] **Step 3: #75, Whole site UI, "one assertion compares a value with itself".** In `test_the_readout_names_each_grids_depth_and_any_absent_grid`, replace `"C": dock.site_velocities()["C"]` with C's expected value, worked out independently: `plugin.session.resolved_velocity(<C's first line key>)`. Add an assert that it is neither `v_a` nor `v_b`.
- [ ] **Step 4: #75, Tooling and docs, "M11's export tests can crash on failure".** In `test_plugin_slice_export.py`, replace each of the seven `ds = None` closes with `try`/`finally: ds.Close()`, the way `_metadata` in `test_plugin_site_scope.py` does it, so a failing assert can't keep a GDAL dataset alive past `exitQgis()`.
- [ ] **Step 5: #54, Slice preview.**
  - Correct `_sweep`'s docstring: the code keeps both files, not either.
  - Correct the module docstring: stale files go at the end of the tick that supersedes them, not "on later ticks". Read `_sweep` and `update_north_up` before rewording either.
  - Add `test_a_persistently_failing_update_from_a_corrupt_file_keeps_the_scratch_folder_bounded` next to the faked one. Instead of replacing `_repoint`, make each tick's write produce a file GDAL cannot open: monkeypatch `SliceLayer._write` to write junk bytes to its path. Assert the folder holds at most the files the layer reads, and the layer still points at an existing file. Then confirm that removing either keep-guard in `_sweep` on its own makes one of the two tests fail. Try each removal by hand, revert it, and record what you saw in your report. Set `PYTHONDONTWRITEBYTECODE=1` while doing so: stale `.pyc` files fake survivors.
- [ ] **Step 6: #75, Survey memory, "a docstring is stale".** `_remember_source`'s docstring names two callers. `restore_cube` is a third. After Task 4, also say that it writes the source only, and that the resolution is remembered by `_on_resolution_edited` and `restore_cube`.
- [ ] **Step 7: Run all four verification commands and see them pass.**
- [ ] **Step 8: Commit.** `git commit -m "Slices: tidy-ups from the M12 and M9 reviews (#75, #54)"` and push.

---

### Task 7: Build and walkthrough (coordinator and user; a human gate)

Not a subagent task. The coordinator does this after the whole-branch review and its fix wave are clean.

- [ ] Deploy to a new QGIS profile, `ns_geo_slices`, a copy of `ns_geo`, with `.venv/bin/python packages/nsgeo-qgis/scripts/dev_link.py --profile ns_geo_slices` from this worktree. Smoke-load it headless.
- [ ] Publish a walkthrough page, an Artifact with a `results` db, with one check per approved behaviour above, on the user's real multi-grid data. It must include: emptying a grid's lines and checking both scopes; selecting a row and switching to This grid; the radius label across grids with different spacings; resolution memory across a grid switch, a scope switch and a save and reopen; and an old survey opening clean.
- [ ] Report the results to the user. Do not merge, or offer to, until the walkthrough has been run.
