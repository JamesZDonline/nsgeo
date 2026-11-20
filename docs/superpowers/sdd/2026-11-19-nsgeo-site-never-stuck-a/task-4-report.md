# Task 4 report: #75 Whole site UI (push pending)

## Already gone (confirmed against the code)
- Unguarded `_note_z_edit`: no definition or caller anywhere (`grep -rn _note_z_edit packages` finds one docstring mention). Replacement: `SlicesDock._on_resolution_edited` (slices_dock.py:2622) and `_edited_fields` (:2654); the docstring at :2633 says it replaces `SiteScope._note_z_edit`.
- dz "seeded from the first ready grid": gone. `site_scope.py` `site_dt_floor` (min of `first_headers(...).dt_ns` over the included grids) sets the dz floor and the single step; the default dz in `seed_z` is the COARSEST included header interval (`max(dts)`, #177), from headers, not the first ready grid. Nuance: the brief says "finest"; that is the floor and step, not the seeded dz value.
- Self-compared velocity assertion: `test_plugin_site_scope.py:~1007` asserts `dock.site_velocities() == {"A": v_a, "B": v_b, "C": v_c}` with `v_c = session.resolved_velocity(c_key)` worked out apart from the dock; and :1020-1023 compares against `session.grid_depth_velocity`.

## New tests
- `test_snap_inside_never_escapes_its_bound` (+ `test_snap_inside_lands_on_the_legal_side_at_the_boundary`), `test_window_levels_rounds_and_floors_at_one` (pure): `ImportError: cannot import name 'snap_inside' from 'nsgeo_qgis.slices_plan'` before the move. The dock's old parametrized `_snap_inside` test moved here (cases kept) and was removed from test_plugin_slices_dock.py; two QGIS helpers that imported `_snap_inside` now import `snap_inside`.
- `test_site_export_refuses_while_a_grid_prepares` (QGIS): B is moved while `Line.load` is held behind an Event (A and C stay ready; asserted, so the busy check is what refuses). Before the fix: `AssertionError: []` on `any("wait until the site's grids finish preparing" in m for m in message_log)`. Passes now; also asserts the bar text and that no export dialog opened (`drive_export_dialog(..., accept=False)` list stays empty).
- Seeding rules: existing coverage found, none written for two of them. `test_the_site_cell_seeds_from_the_finest_spaced_grid` (cell from finest-spaced grid), `test_the_site_includes_every_grid_with_lines_by_default` (default inclusion), `test_the_site_cell_is_reseeded_only_when_the_included_grids_change` (a change reseeds). Gap: a re-sent same set and a tick never seed. Added `test_a_re_sent_included_set_never_seeds_the_resolution_again`: was untested, now pinned (passed at once).

## SlicesDockView (site_scope.py)
Attributes: cell_spin, dz_spin, z0_spin, z1_spin, thickness_spin, step_spin (QDoubleSpinBox), slice_slider (QSlider), coverage_check, resident_check (QCheckBox), stretch_combo, palette_combo, grid_combo (QComboBox), transform_combo (TransformCombo), readout, velocity_label, site_depths_label, status_label (QLabel), legend_label (ElidedLabel), export_button, save_button, grid_scope_button, site_scope_button (QPushButton), source_group (QGroupBox), site_panel (SiteSourcePanel), normalisation_panel (NormalisationPanel), grid_finish, site_finish (FinishPanel), refiner (Refiner), site_engine (SiteEngine), session (SiteSession), error/slice_changed/window_changed/window_cleared (pyqtBoundSignal); methods scope() -> str, show_refine(), show_warnings(), own_colours_on() -> bool; property finish_debounce_ms -> int.
Imports for the types are under `TYPE_CHECKING` (the dock imports this module). Imprecise: `dz_spin` is really `_DzSpinBox` (typed as its base QDoubleSpinBox); the signals are bare `pyqtBoundSignal` (no argument types); the dock is also a QObject (`QTimer(dock)`, `RefineFlow(dock, ...)`), which a Protocol cannot express. site_scope.py is not on CI's mypy list, so the Protocol is not type-checked in CI, only documented/usable.
`SiteScope.engine`/`session` properties still return `Any` (left as is).

`grep -n "dock\._" packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py`: no output (rc 1); no comments mention it either.

## Other changes
`SlicesDock.finish_debounce_ms` (public property); `site_scope.levels` and the dock's `_step_levels` / `thickness_step_levels` call `window_levels`; lazy `_snap_inside` import removed; `_export_site` refuses first (before the ready-grids check) while `site.is_running`, `self.message(..., Warning)`, text exactly as briefed.

## Results
- Pure: 396 passed, 4 skipped. Core untouched (not run).
- test_plugin_site_scope.py: 176 passed (one earlier run had 11 failures from two tests still importing `_snap_inside`; fixed, rerun clean).
- test_plugin_slices_dock.py: 236 passed.
- `-m real_data`: 46 passed, 2835 deselected.
- ruff check and format --check clean. CI mypy command (slices_plan.py is on it): Success, no issues in 65 source files.
- No flakes (#196 etc.) hit.

## Deviations
Busy check placed before the "prepare the site's grids" check (when grids prepare, ready_grids can be empty and the wait message is the useful one). Pure test split so the two brief assertions form their own test. Push pending.
