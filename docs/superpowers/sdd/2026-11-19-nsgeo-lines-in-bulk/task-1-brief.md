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

