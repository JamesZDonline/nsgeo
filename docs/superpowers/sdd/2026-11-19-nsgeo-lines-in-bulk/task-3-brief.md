### Task 3: A Processing preset box at import (#129), and the Slices panel follows it

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/model/survey.py` (`Site.import_presets`)
- Modify: `packages/nsgeo-core/src/nsgeo/project.py` (save when non-empty; tolerant
  `_clean_import_presets(value, known_grid_ids)` in the loader)
- Modify: `session.py` (four new methods; `remove_grid` pops the grid's entry)
- Modify: `ui/preset_box.py` (the `PresetBox` widget)
- Modify: `ui/import_dialog.py` (last form row; `_grid_changed` calls `preset_box.set_grid`;
  `accept`)
- Modify: `ui/gps_import_dialog.py` (form row under Destagger; `_accept`)
- Modify: `ui/slices_dock.py` (one new slot `_follow_remembered_preset(grid_id: str)` and its
  `connect` to `session.slice_sources_changed`; nothing else)
- Test: `packages/nsgeo-core/tests/test_project.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_session_bulk.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_preset_box.py` (new),
  `packages/nsgeo-qgis/tests/qgis/test_plugin_import_dialog.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_gps_import_dialog.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`

**Interfaces:**
- Consumes: `SiteSession.apply_preset_to` and `migration_note` (Task 1).
- Produces (core): `Site.import_presets: dict[str, Any]`, shape
  `{"grids": {grid_id: str | None}, "site": str | None}`, both keys optional.
- Produces (session):
  - `import_preset(grid_id: str | None) -> str | None`: the grid's entry if present (None stays
    None), else `"site"`, else None; a name that is no longer a preset reads as None.
  - `remember_import_preset(grid_id: str | None, name: str | None) -> None`: sets `"site"` and,
    with a grid, that grid's entry; dirty only when something changed.
  - `import_sets_slice_preset(grid_id: str) -> bool`: the grid has no lines and its remembered
    slice source has no preset (§2.4's one rule, read by the box and by `accept`).
  - `set_slice_preset(grid_id: str, name: str | None) -> None`: through `_update_source`; None
    removes the `"preset"` key (and an entry left empty), for the undo in `accept`.
- Produces (widget): `PresetBox(session: SiteSession, parent: QWidget | None = None)` with
  `combo: QComboBox`, `note: QLabel`, `set_grid(grid_id: str | None) -> None` (moves to the
  starting value; the Slices line only for a grid), `chosen() -> str | None`, `is_choice() -> bool`
  (False while greyed).

- [ ] **Step 1: Write the failing core tests** in `test_project.py`:
  `test_import_presets_round_trip`, `test_import_presets_are_read_tolerantly` (a non-object,
  a non-string non-null value, an unknown grid id: each dropped, the site opens),
  `test_import_presets_do_not_change_the_schema_version`, `test_an_empty_import_presets_is_not_written`.
- [ ] **Step 2: Run (core venv); fail. Implement; run; pass.**
- [ ] **Step 3: Write the failing session tests** (in `test_plugin_session_bulk.py`):
  starting-value rule (grid's, site's, None; a remembered None stays None; a deleted preset reads
  None), `remember_import_preset` dirtiness, `import_sets_slice_preset` (true only for no lines and
  no remembered preset), `set_slice_preset` set and undo, `remove_grid` drops the entry.
- [ ] **Step 4: Run; fail. Implement; run; pass.**
- [ ] **Step 5: Write the failing widget tests** in `test_plugin_preset_box.py`:
  - `test_the_list_is_none_then_the_presets_by_name`.
  - `test_with_no_presets_the_box_is_greyed_on_none_with_its_tooltip` (tooltip
    `"Save a preset from the Processing panel first."`; `is_choice()` False).
  - `test_the_note_shows_the_migration_line_only_for_a_migration_preset`.
  - `test_the_note_shows_the_slices_line_only_when_the_rule_holds` (`"Grid3's first lines: this
    becomes its Slices preset too."` with the grid's id; never for None or `set_grid(None)`).
  - `test_a_deleted_choice_drops_to_none_and_says_so` (`"The preset {name} was deleted; these
    lines will import with none."`, until another choice is made).
  - `test_a_saved_preset_appears_and_the_choice_is_kept`.
  - `test_the_box_survives_the_site_closing_under_it` (no exception; `chosen()` is None).
- [ ] **Step 6: Run; fail. Implement `PresetBox`; run; pass.**
- [ ] **Step 7: Write the failing dialog tests.** In `test_plugin_import_dialog.py`:
  - `test_the_preset_box_is_the_last_form_row`.
  - `test_import_with_a_preset_changes_only_the_new_lines` (two lines imported first with no
    preset and a hand-added step; then two more with the preset: the first two keep their stacks,
    the new two equal the preset).
  - `test_the_box_starts_on_the_grid_choice_then_the_sites_and_cancel_remembers_nothing`.
  - `test_a_greyed_box_remembers_nothing`.
  - `test_the_first_import_into_an_empty_grid_sets_its_slices_preset_and_later_ones_do_not`
    (also: not for None, not when a Slices preset exists).
  - `test_a_refused_import_puts_the_slices_preset_back` (a key already in the site).
  - `test_real_grid2_lines_import_with_a_preset_only_the_new_ones_change` (real data:
    `GRID2_LINES[:3]` then `GRID2_LINES[3:6]` with a preset).
  In `test_plugin_gps_import_dialog.py`:
  - `test_the_preset_box_sits_under_the_destagger_row`.
  - `test_gps_import_with_a_preset_changes_only_the_new_lines_and_remembers_the_sites_choice`.
  - `test_real_gps_lines_import_with_a_preset` (real data: two of `GPS_LINES`).
- [ ] **Step 8: Run; fail. Implement both dialogs' rows and `accept` per spec §2.4–2.5**: check
  the preset still exists, check for keys already in the site, read `import_sets_slice_preset`,
  write the Slices preset before `add_lines` and put it back if `add_lines` refuses, then
  `apply_preset_to` the new keys, then `remember_import_preset` when `is_choice()`. Run; pass.
- [ ] **Step 9: Write the failing Slices panel tests** in `test_plugin_slices_dock.py`:
  - `test_the_panel_follows_a_preset_written_for_the_grid_it_shows` (`set_slice_preset` on the
    shown grid switches the combo).
  - `test_the_panel_ignores_its_own_writes_other_grids_and_other_fields` (gain/resolution change,
    another grid: combo unchanged, nothing re-prepared).
  - `test_an_import_into_the_shown_empty_grid_prepares_with_the_imports_preset_once`
    (Review Focus 4: the panel on the empty grid, an `ImportDialog` import with preset P; the
    panel shows P, the engine's last prepare used P, and the lines were prepared once; then a
    Choose-lines change keeps P in `slice_source`).
- [ ] **Step 10: Run; fail. Implement `_follow_remembered_preset` (acts only in This grid scope,
  for the grid it shows, when the remembered preset exists and differs from the combo; switches
  as a hand choice). Run; pass.**
- [ ] **Step 11: Run the touched files, `-m real_data`, and core+pure; all pass.**
- [ ] **Step 12: Commit and push.**
  `git commit -m "feat(import): choose a processing preset for the new lines; the Slices panel follows a grid's first (#129)"`

