# Lines in bulk and at import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bulk preset/steps/velocity on a selection of lines, a map selection that is the Survey
panel's selection, a Remove prompt that names what goes, a Processing preset box at import, and
two `import_dialog.py` tidy-ups.

**Architecture:** New one-change `SiteSession` methods carry every bulk write. The Survey panel
gains menu items, prompts and two signals; `MapLink` gains one signal and one method; `plugin.py`
only wires them and hosts the bulk velocity dialog. A self-contained `PresetBox` widget goes into
both import dialogs, backed by a new optional `import_presets` field in the site file; the Slices
panel gains one slot that follows a preset written from outside.

**Tech Stack:** Python 3.12, PyQt5 (QGIS 3.44 locally) / PyQt6 (QGIS 4.2 in CI), pytest.

**Spec:** `docs/superpowers/specs/2026-11-19-nsgeo-lines-in-bulk-design.md` (read it first; this
plan cites its sections as §N).

## Global Constraints

- Paths are under `packages/nsgeo-qgis/nsgeo_qgis/` unless they start with `packages/`.
- User-facing strings are copied verbatim from the spec (§2.1, §4.1, §4.2, §5); the tests quote
  them through module constants, as `survey_dock.py` already does for its cut prompts.
- Every slot (menu action, signal handler, `itemSelectionChanged`, `selectionChanged`) guards its
  own body and logs through `QgsMessageLog` (`_log`), per each module's docstring: an exception in
  a slot never reaches the emitter, and in CI's container it aborts the run.
- New re-entrancy guards are depth counters (`+= 1` / `-= 1` in `try/finally`, read as truthy),
  never set/clear booleans.
- No modal runs in a test without `answer_modal` / `drive_dialog`; never `QMenu.exec()` in a
  test (build the menu, then find and trigger its action, as `test_plugin_survey_dock.py` does).
- Other sessions' files: no edit to `ui/processing_dock.py`. In `ui/slices_dock.py` only the one
  new slot and its `connect` line (Task 3). In `map_link.py` new methods plus a few lines in
  `_on_selection` (Task 2). In `survey_dock.py` and `plugin.py`, new functions; existing
  functions get one-line calls into them.
- Magnetometer files (M19a, unmerged) are not lines: nothing here may assume a selected key is a
  line without checking it is a "line" row (`SurveyDock.key_of`).
- Real data first: real-data tests use `tests.real_data.GRID2_LINES` and `GPS_LINES` and skip with
  a reason naming `tests/data/local` (that names them `real_data`; an unmarked data skip fails).
  Never put a survey or site name in code, tests, commits or the PR.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; push the branch
  after each task.
- **Local test recipe** (do not run the whole QGIS tier locally; CI does, on 3.44 and 4.2):
  - core + pure: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh`
  - touched QGIS files: `packages/nsgeo-qgis/scripts/qgis_tests.sh <files> -q`
  - real data: `packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis -m real_data -q`
  - then `gh run list --branch nsgeo-lines-in-bulk` until the pushed commit's run passes,
    **including the `qgis/qgis:4.2` job** (Qt 6: enums are not ints).

## Setup (controller, before Task 1)

- [ ] Build the worktree's own core venv and check it imports the worktree:
  `python3 -m venv .venv && ./.venv/bin/python -m pip install -e "packages/nsgeo-core[dev]"`, then
  `./.venv/bin/python -c "import nsgeo; print(nsgeo.__file__)"` must name `.worktrees/nsgeo-lines-in-bulk`.
  (`qgis_tests.sh` uses the main checkout's `.venv-qgis`; the plugin's path shim finds this
  worktree's core.)
- [ ] Link the real data: every entry of the main checkout's `packages/nsgeo-core/tests/data/local/`
  except the tracked `README.md`, symlinked into the worktree's same folder.
- [ ] Baseline: run the recipe's first two commands on the untouched branch and record the counts.

## Review Focus

1. **A `lines_changed` while lines are selected** (any bulk velocity, an Edit lines OK, an import):
   the selection must survive in the panel and on the map. The refill replaces every feature
   (provider `truncate` + `addFeatures`), so stale ids or an empty `selectionChanged` must not be
   read as the user clearing it. Task 2 pins it through the real plugin wiring.
2. **A selection of mixed kinds** (tape + GPS, several grids, an unplaced line, the open line
   inside the selection, a cut open): each menu item's count and greying must follow §4.1. Task 1
   pins the open-line and cut cases; Task 2 the unplaced line.
3. **Presets changing while an import dialog is open** (saved, deleted, the site closed): the box
   refills, keeps or drops its choice with the note, and Import never applies a preset that no
   longer exists. Task 3 pins it.
4. **The Slices panel already on the empty target grid at Import**: it must prepare the new lines
   with the import's preset, and its next own choice must not write the first preset back.
   Task 3 pins it with the panel and the dialog together.
5. **Enter on the Remove prompt when a fit would go** defaults to No; with no fits, Yes as today.
   Task 1 pins both through the default-button argument.

---

### Task 1: Bulk preset, steps and velocity on a selection (#58), and Remove names what goes (#221)

**Files:**
- Modify: `session.py` (three new methods, after `apply_stack_to_grid` / `set_line_velocity`)
- Modify: `ui/survey_dock.py` (selection branch of `_on_context_menu`: one call into a new
  function; new action functions; `_removal_text`: one call; `_remove`: default button)
- Modify: `plugin.py` (two `connect` lines beside the Survey panel's; `open_bulk_velocity_dialog`)
- Create: `ui/preset_box.py` with only `migration_note` for now (Task 3 adds the widget)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_session_bulk.py` (new),
  `packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py`

**Interfaces:**
- Produces (session, each one change, all keys checked first: an unknown key raises `KeyError`
  with the site untouched):
  - `SiteSession.apply_preset_to(name: str, keys: Iterable[str]) -> list[str]`: `apply_preset`'s
    body per key, one dirty mark, `stack_changed` per key; `KeyError` for an unknown preset too.
    Returns the keys changed (all of them; a stack is always replaced).
  - `SiteSession.apply_stack_to(source_key: str, keys: Iterable[str]) -> list[str]`: the source's
    stack copied to every key but the source; returns those keys.
  - `SiteSession.set_lines_velocity(keys: Iterable[str], model: VelocityModel | None) -> list[str]`:
    velocity set, `velocity_source` dropped, fits kept; one `lines_changed`; lines already at
    `model` with no record are skipped; nothing emitted when none changes. Returns keys changed.
- Produces (`ui/preset_box.py`): `migration_note(dicts: Sequence[dict], *, saved: bool) -> str | None`
  — the first enabled `migrate_fk` step's `velocity_m_ns`, as
  `"Its Migration (Stolt f-k) step uses {v:.3f} m/ns, the velocity it was saved with."` when
  `saved`, else `"Its Migration (Stolt f-k) step uses {v:.3f} m/ns."`; None with no such step.
- Produces (survey dock): `SurveyDock.bulk_velocity_requested = pyqtSignal(list)`,
  `SurveyDock.report = pyqtSignal(str)` (one message-bar line; the plugin connects it to
  `self.message`), and
  `apply_preset_action(keys: list[str], name: str, *, confirm: bool = True) -> list[str]`,
  `apply_steps_action(keys: list[str], *, confirm: bool = True) -> list[str]`,
  `clear_velocity_action(keys: list[str], *, confirm: bool = True) -> list[str]`,
  `selected_line_keys() -> list[str]` (line rows only, tree order; Task 2 reuses it).
- Produces (plugin): `NsgeoPlugin.open_bulk_velocity_dialog(keys: list[str]) -> None`.

- [ ] **Step 1: Write the failing session tests** in `test_plugin_session_bulk.py` (a site with
  grid A holding three synthetic lines and grid B holding one, two presets, one of them with an
  enabled `migrate_fk` step at 0.1):
  - `test_apply_preset_to_replaces_only_the_named_lines`: the named keys' `stack_for(k).to_dicts()`
    equal the preset; the other lines' stacks are unchanged objects; one `dirty_changed`.
  - `test_apply_preset_to_checks_every_key_first`: an unknown key or preset raises `KeyError` and
    no stack changed.
  - `test_apply_stack_to_skips_the_source_and_copies_to_the_rest`: returns the keys minus the
    source; the source's stack object is the same object as before.
  - `test_set_lines_velocity_is_one_change_and_keeps_fits`: a `lines_changed` counter goes up by
    exactly 1 for three keys; each line's `velocity == model` and `velocity_source is None`;
    `velocity_fits` unchanged; a line already at `model` with no record is not in the return.
  - `test_set_lines_velocity_none_clears_and_is_silent_when_nothing_changes`: clearing lines with
    no override emits nothing and returns `[]`.
  - `test_migration_note_reads_the_first_enabled_migration_step`: saved and unsaved wordings;
    a disabled `migrate_fk` step gives None.
- [ ] **Step 2: Run them; they fail** (`AttributeError` on the new methods).
  `packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis/test_plugin_session_bulk.py -q`
- [ ] **Step 3: Implement the three session methods and `migration_note`.**
- [ ] **Step 4: Run them; they pass.**
- [ ] **Step 5: Write the failing Survey panel tests** in `test_plugin_survey_dock.py` (the
  module's `dock` fixture, plus helpers to add presets, a second grid, a GPS line where needed):
  - `test_a_selection_menu_offers_the_bulk_items_per_kind`: for the four §4.1 rows, the action
    texts in order, e.g. tape-on-one-grid gives `["Edit 3 lines…", "Move 3 lines to grid",
    "Apply preset to 3 lines", "Apply steps from FILE__001 to 2 lines…", "Set velocity for 3
    lines…", "Clear velocity override on 3 lines", "Remove 3 lines from site"]` with FILE__001
    open and selected; tape across grids keeps "Move N lines to grid".
  - `test_bulk_items_grey_out_as_the_spec_says`: no presets → "Apply preset to N lines" disabled;
    no open line, or a cut open → "Apply steps from the open line…" disabled; no override →
    "Clear velocity override on N lines" disabled.
  - `test_apply_preset_action_asks_with_the_count_and_reaches_exactly_the_selection`:
    `answer_modal(QMessageBox, "question", Yes)`; the prompt text is
    `"Replace the processing of 3 lines with preset {name}?"` followed by the migration note for
    the migration preset; only the three keys changed; `report` emitted
    `"preset {name} applied to 3 lines"`. With `No`, nothing changed.
  - `test_apply_steps_action_leaves_the_open_line_out`: prompt
    `"Replace the processing of 2 lines with the steps on FILE__001?"` + `"FILE__001 itself is left as it is."`;
    `report` emitted `"steps from FILE__001 applied to 2 lines"`.
  - `test_clear_velocity_action_names_how_many_and_the_fits`: two of three with overrides, one of
    them with a velocity source record; prompt
    `"Clear the velocity override on 2 of these 3 lines? They go back to their grid's velocity, or the one in the file's header."`
    + `"1 of them has a velocity from its saved fits; the fits stay saved."`; afterwards no
    override on any of them, one `lines_changed`; `report` emitted
    `"velocity override cleared on 2 lines"`.
  - `test_set_velocity_item_requests_the_plugin_dialog`: triggering it emits
    `bulk_velocity_requested` with the three keys.
  - `test_the_bulk_items_never_offer_a_mag_or_cut_key`: a selection holding a cut and no line
    shows today's menu only.
  - `test_removal_text_names_what_goes_with_one_line` /
    `..._with_several_lines` / `..._with_a_grid` / `..._and_nothing_when_nothing_goes`: the §5
    strings, with each part present only when true ("processing steps" = a stored stack with ≥ 1
    step).
  - `test_remove_defaults_to_no_only_when_a_fit_would_go`: `answer_modal(QMessageBox, "question",
    No)` returns its calls; the default-button argument is `No` when a selected line has a fit and
    `Yes` otherwise; same for Remove grid.
- [ ] **Step 6: Run them; they fail.**
- [ ] **Step 7: Implement the menu items, the three action functions, `report`, the removal
  line (one new function, `_lost_with_lines_text(keys: list[str]) -> str`, called once from
  `_removal_text`) and the default button in `_remove`.** The selection stays as it was (the
  rebuild's handling comes in Task 2).
- [ ] **Step 8: Write the failing plugin test** in `test_plugin_survey_dock.py`:
  `test_bulk_velocity_dialog_sets_the_number_and_warns_about_fits(fake_iface, tmp_path, answer_modal)`:
  three lines, one with a record; `calls = answer_modal(QInputDialog, "getDouble", (0.095, True))`;
  emit `bulk_velocity_requested`; the label holds `"Velocity for 3 lines (m/ns):"`,
  `"1 of these lines has a velocity from its saved fits; it will be replaced. The fits stay saved on the lines."`
  (for 2: `"2 of these lines have a velocity from their saved fits; it will be replaced. …"`) and `"Migration steps keep their own velocity."`;
  the start value is the shared override, else the first line's `resolved_velocity`; range 0–0.3,
  4 decimals; every line ends at 0.095 with no record; the message bar shows
  `"velocity 0.095 m/ns set on 3 lines"`. `(…, False)` changes nothing.
- [ ] **Step 9: Implement `open_bulk_velocity_dialog`** (shaped like `open_destagger_dialog`:
  `QInputDialog.getDouble`, the warnings in its label, guarded, reports on the message bar), and
  the two `connect` lines.
- [ ] **Step 10: Run the two test files and core+pure; all pass.**
- [ ] **Step 11: Commit and push.**
  `git commit -m "feat(survey): bulk preset, steps and velocity on a selection; Remove names what goes (#58, #221)"`

### Task 2: The map and the Survey panel share one line selection (#57)

**Files:**
- Modify: `map_link.py` (`lines_selected` signal, `select_lines`, a depth-counted guard; a few
  lines in `_on_selection`)
- Modify: `ui/survey_dock.py` (`line_selection_changed` signal, `select_lines`; `_capture_state`
  / `_restore_selection` / `_follow_current` each get a one-line call into new functions)
- Modify: `plugin.py` (two `connect` lines)
- Possibly modify: `layers.py`, only if Step 1 shows the refill needs bracketing (a depth counter
  `MapLink` can read; nothing else in `layers.py`)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_line_selection.py` (new: the wired plugin)

**Interfaces:**
- Consumes: `SurveyDock.selected_line_keys()` (Task 1), `SiteSession.set_lines_velocity` (Task 1).
- Produces: `MapLink.lines_selected = pyqtSignal(list)`, `MapLink.select_lines(keys: list[str]) -> None`;
  `SurveyDock.line_selection_changed = pyqtSignal(list)`, `SurveyDock.select_lines(keys: list[str]) -> None`.

- [ ] **Step 1: Find out what a refill does to the selection** (spec §3.4's hazard). Write
  `test_a_refill_keeps_or_clears_the_lines_selection_as_measured` in `test_plugin_map_link.py`
  (the `linked` fixture): select two features, count `selectionChanged` emissions and read
  `selectedFeatureIds()` across `session.set_line_velocity(...)` (a `lines_changed`). Record the
  measured behaviour in the test's docstring and in the task report; it decides Step 7's guard.
- [ ] **Step 2: Write the failing `MapLink` tests** in `test_plugin_map_link.py`:
  - `test_selecting_several_lines_announces_them_and_opens_nothing`: `lines_selected` carries the
    keys in any order; `current_key` unchanged. (Keep `test_selecting_several_lines_promotes_none`.)
  - `test_selecting_one_line_announces_it_and_opens_it`.
  - `test_deselecting_everything_announces_an_empty_selection_and_keeps_the_line_open`.
  - `test_select_lines_selects_those_features_and_neither_announces_nor_opens`: after
    `link.select_lines([k])`, the layer's selected feature is `k`'s, `lines_selected` did not
    fire and `current_key` did not change, also for exactly one key.
  - `test_select_lines_ignores_keys_with_no_feature` (an unplaced line's key).
- [ ] **Step 3: Implement them; run; pass.**
- [ ] **Step 4: Write the failing Survey panel tests** in `test_plugin_survey_dock.py`:
  - `test_select_lines_selects_exactly_those_rows_unfolds_their_grids_and_opens_nothing`.
  - `test_select_lines_does_not_announce_back`: `line_selection_changed` not emitted by it.
  - `test_a_ctrl_click_announces_the_new_line_selection`: `_click(dock, item, Ctrl)` emits the
    remaining keys in tree order; nothing opens, also when one line is left.
  - `test_a_grid_or_cut_selection_announces_no_lines`.
  - `test_the_line_selection_survives_a_rebuild`: select three lines, `set_lines_velocity` on
    them, still three selected; the open line stays the current item when among them.
  - `test_opening_a_line_makes_it_the_selection_and_announces_it` (`session.open_line` with three
    selected: one selected, announced).
  - `test_opening_a_cut_announces_an_empty_line_selection`.
- [ ] **Step 5: Implement them; run; pass.**
- [ ] **Step 6: Write the failing wired tests** in `test_plugin_line_selection.py`, through
  `NsgeoPlugin(fake_iface).initGui()` and a site with grid A's synthetic lines, one GPS line and
  one time-triggered (unplaced) line:
  - `test_a_rectangle_over_several_lines_selects_them_in_the_panel_and_opens_nothing`
    (`selectByIds` on the `lines` layer stands in for the rectangle).
  - `test_a_ctrl_click_in_the_panel_takes_the_line_off_the_map_and_opens_nothing` (down to one).
  - `test_clicking_empty_map_clears_both_and_the_open_line_stays_open`.
  - `test_gps_lines_select_like_tape_lines`.
  - `test_an_unplaced_line_stays_selected_in_the_panel_and_a_map_gesture_drops_it`.
  - `test_the_selection_survives_a_bulk_velocity_in_both_places` (Review Focus 1: six lines,
    `set_lines_velocity`, then the panel's and the layer's keys are both the six).
  - `test_delete_after_a_map_selection_removes_lines_only` (#31's rule, with the grid row swept
    into the selection).
  - `test_real_grid2_lines_select_from_the_map` (real data: `GRID2_LINES[:6]` imported into a grid
    sized for them; select four on the layer; the panel holds those four).
- [ ] **Step 7: Wire the two `connect` lines; add the refill guard Step 1 calls for; run; pass.**
- [ ] **Step 8: Run the three test files, `-m real_data`, and core+pure; all pass.**
- [ ] **Step 9: Commit and push.**
  `git commit -m "feat(map): the map and the Survey panel share one line selection (#57)"`

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

### Task 4: Tidy-ups in `import_dialog.py` (#16, #17)

**Files:**
- Create: `numbers.py` (`parse_decimal`)
- Modify: `ui/import_dialog.py` (`_updating`, `_following`, the Offset cell's parse)
- Modify: `ui/param_form.py` (the float branch of `_parse_number` calls `parse_decimal`;
  messages unchanged)
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_numbers.py` (new),
  `packages/nsgeo-qgis/tests/qgis/test_plugin_import_dialog.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py`

**Interfaces:**
- Produces: `parse_decimal(text: str) -> float` in `nsgeo_qgis/numbers.py` (no Qt import, so the
  pure tier can test it): `float(text.strip())`; `ValueError` for a comma anywhere, for anything
  `float` refuses, and for NaN or an infinity. Callers word their own messages.

- [ ] **Step 1: Write the failing tests:**
  - pure: `test_parse_decimal_reads_a_point_and_refuses_a_comma_nan_and_inf`
    (`"1.5"` → 1.5, `" 2 "` → 2.0; `"1,000"`, `"1,5"`, `"nan"`, `"inf"`, `"-inf"`, `""` raise).
  - qgis: `test_an_offset_typed_with_a_comma_is_refused_like_paramform`: typing `"1,000"` into the
    Offset cell leaves the offset unchanged and the status reads `"'1,000' is not a number;
    offset unchanged"`; `"nan"` the same.
  - qgis: `test_paramform_and_the_import_dialog_refuse_the_same_inputs`: for each of
    `["1,000", "1,5", "nan", "inf"]`, ParamForm's float field reports an error and the Offset cell
    is refused.
  - qgis: `test_a_reentrant_refresh_does_not_clear_the_guard_early`: from inside
    `_refresh_table`'s guarded block (patch a call it makes to run `_refresh_table` again), an
    `itemChanged` delivered after the inner call returns is still ignored; same shape for
    `_follow_spacing` / `_first_offset_changed`.
- [ ] **Step 2: Run; fail.**
- [ ] **Step 3: Implement `parse_decimal`; switch both callers; make `_updating` and
  `_following` depth counters.**
- [ ] **Step 4: Run the touched files and core+pure; all pass. Check `test_plugin_param_form.py`
  still passes unchanged.**
- [ ] **Step 5: Commit and push.**
  `git commit -m "fix(import): one rule for decimal input; guards as depth counters (#17, #16)"`

---

## After the tasks

- [ ] Whole-branch review (most capable model), then the local recipe and CI (3.44 and 4.2)
  green on the last pushed commit.
- [ ] Deploy to its own QGIS profile (`ns_geo_bulk`) and publish the walkthrough Artifact (db
  collection `checks`), covering spec §10: DZT import with a preset into a grid with lines; the
  first import into an empty grid with the Slices panel on it; GPS import with a preset; a
  rectangle selection on the map, trimmed in the panel, removed with Delete (the prompt names
  what goes, No is the default with fits); a preset, the open line's steps, a velocity and a
  cleared velocity on a selection, the selection staying through each. Wait for the author.
- [ ] PR body: closes #129 #16 #17 #57 #221, and #58 (presets and velocity; placement was #137);
  lists the set/clear flags left for other sessions' files (spec §6); notes the overlaps for
  M19a, H and G (spec §8). Merging asks first.
- [ ] README roadmap: session D's In progress entry updated at each stage (straight to main).
