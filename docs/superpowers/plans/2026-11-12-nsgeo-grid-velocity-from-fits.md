# A Grid Velocity From Its Fits Implementation Plan (#127, #86)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every code task is written test-first with superpowers:test-driven-development: the failing test is run and seen to fail before any production code is written.

**Goal:** A grid's **Set velocity…** opens a velocity dialog over every saved fit on the grid's
lines. It averages the ticked fits, and the grid remembers which fits made its velocity. A line's
dialog gains the same ticks and average. Slices take their depths from the grid's velocity.

**Architecture:**
- A new core module, `nsgeo/velocity_source.py`, holds the record of where a velocity came from
  and the weighted mean. `Line` and `Grid` each carry an optional record. The project file saves
  as version 3 when any record exists.
- `SiteSession` gains fit ids that never repeat, record-keeping setters, and a member-state
  lookup.
- `VelocityDialog` is generalised to two scopes, one line or one grid, so both dialogs share one
  table, one average group and one Apply rule.
- The slice code reads the grid rule cuts already use, renamed `grid_depth_velocity`.

**Tech Stack:** Python ≥ 3.9 and numpy (core); PyQt via `qgis.PyQt` (plugin, QGIS 3.44 and 4.2);
pytest on two tiers (core+pure, QGIS).

**Spec:** `docs/superpowers/specs/2026-11-12-nsgeo-grid-velocity-from-fits-design.md` (approved
2026-11-12). Read it first. Its sections are cited as §n. This plan's calls are P1–P9.

## Order and branch state

- Tasks 1–3 can be built now, on `nsgeo-grid-velocity` from main 15dea4c. None of them touches
  a file that piece 1 (`nsgeo-fit-marks`) or the fine-cell export (PR #175) changes.
- **Before Task 4:** piece 1 must have merged to main. Merge main into this branch and run the
  Task 1–3 tests again. Task 4 edits the profile strip and the Survey grid row, both of which
  piece 1 changed.
- **Before Task 5:** PR #175 must have merged. Merge main again. Task 5 edits `slices_dock.py`,
  `site_scope.py` and `slices_engine.py`, which #175 touches.
- If a merge has not happened when its task comes up, stop and report. Do not build on a guess
  of the other branch's code.

## Plan calls (Claude's; check while reading)

- **P1 — names.**
  - The record is `VelocitySource` and a member is `SourceFit`, both in `nsgeo.velocity_source`.
  - `Line.velocity_source` and `Grid.velocity_source` hold them.
  - `Line.fit_serial: int` is the id counter (§8).
  - Both new names join `EXPECTED_PUBLIC` in `test_public_api.py` and the core README.
- **P2 — `velocity_from_fit` becomes a read-only property** on `Line`. It returns the fit id when
  the line's record is a single `fit` member that is still in `velocity_fits` with the same
  `fitted_at`, and `None` otherwise. Existing readers keep working (the profile label, the dialog's
  initial selection). Writers move to the new setters.
- **P3 — setters.**
  - `set_line_velocity(key, model)` and `set_grid_velocity(grid_id, model)` keep their
    signatures, and now **drop** the record: a bare number has no source (§7.2 rule 4, and
    §11's anti-goal).
  - `apply_line_velocity(key, model, source)` and `apply_grid_velocity(grid_id, model, source)`
    set both, with one emit.
  - `set_velocity_from_fit` is removed in Task 4, when its last caller moves.
- **P4 — one dialog class.** `VelocityDialog(session, key=None, *, grid_id=None, parent=None)`,
  with exactly one of `key` / `grid_id`.
  - Rows are keyed internally by `(line_key, fit_id)` in both scopes.
  - The line-scope accessors that tests use today keep their `str` fit-id signatures:
    `fit_id_at_row`, `select_fit`, `selected_fit_id`, `highlighted_fit_id`, `flagged_fit_ids`.
  - The grid scope uses `row_ref(row) -> tuple[str, str]` and `select_row(row)`.
- **P5 — the header tick box** (§4.3) is a tri-state `QCheckBox` labelled **All**, placed on the
  row above the table. A checkable header section is fragile across PyQt5/6, and this does the
  same job.
- **P6 — "applied" date.**
  - `applied_at` is ISO-8601 UTC to the second.
  - A record made from an old file's `velocity_from_fit` has `applied_at=None`, and the note then
    omits "(applied …)".
- **P7 — the fit counter** saves as `"fit_serial"` on a line entry whenever it is above 0. It
  never on its own lifts the file to version 3 (§9). On load, it is the larger of the saved value
  and the highest `fit-N` already on the line. Ids not of the form `fit-N` count as 0.
- **P8 — the line label** in a member is `placement.label or path.stem`, the Survey panel's
  rule.
- **P9 — dialog zeros are found once per dialog**, through one `fits_at_line_zero(session, key)`
  per line that has fits. Task 4 pins this with a call count, not a timing. Timing tests have
  flaked here before (#165).

## Global Constraints

- **Core:** numpy only, runtime Python 3.9 (CI's pure tier): no `zip(strict=)`, no `match`, no PEP
  604 unions outside annotations. Every new file starts with `from __future__ import annotations`.
  mypy runs on core exactly as CI does:
  `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`.
- **Plugin:** works on QGIS 3.44 (PyQt5) and 4.2 (PyQt6). Use fully qualified enums
  (`Qt.ItemFlag.ItemIsUserCheckable`, `Qt.CheckState.Checked`). Every slot catches `Exception`
  and logs through `QgsMessageLog`, as the existing dialog does. Every slot-driven test asserts
  `message_log == []`.
- **Numbers on screen:**
  - t0 to 1 dp; v and σ to 4 dp (`0.0896 ± 0.0014 m/ns`).
  - The box is compared to 4 dp.
  - The Survey row's `v` is 3 dp, as now.
- **Wording:** take it from spec §4–§7 and §10. These strings are pinned by tests:
  - `Slices and cuts on this grid use this velocity.`
  - `Saved hyperbola fits on this grid's lines. Tick fits to average them; pick one to use its velocity.`
  - `No fits ticked`
  - `No fits on this grid's lines yet`
  - `Some ticked fits disagree with each other. The ground may be layered, and one number may not suit every depth.`
  - `Weighted by each fit's ±: tighter fits count for more.`
  - `This velocity is the average of {n} fits`
- **Tests:** run them exactly as below, from the worktree root. Never run the whole QGIS tier
  locally; CI does.
  - QGIS, one file: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/<file> -q -p no:xonsh`
  - Core + pure: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q`
  - Lint: `.venv/bin/ruff check packages && .venv/bin/ruff format --check packages`
- **Real data** is linked at `packages/nsgeo-core/tests/data/local/`. Use
  `tests/real_data.py`'s lists (`CAMPUS_LINES`, `GRID2_LINES`) and skip when they are empty, as
  the existing real-data tests do.
- **Commits:** one or more per task, pushed as made. End each message with a `Co-Authored-By:`
  line naming your own model.

## Review Focus

These are inputs the spec implies but no task's main path exercises. Each has its test in the
task named.

1. **Two lines each with a `fit-1`, in one grid dialog.** Delete, pick and tick must act on the
   right line's fit (Task 4: `test_grid_dialog_deletes_the_fit_of_the_row_picked_not_another_lines_fit_1`).
2. **A fit with σ of zero.** Three clicks exactly on a hyperbola give that. It must not be
   weighted as infinitely precise, and the dialog must still open (Task 1: `test_weighted_mean_refuses_a_zero_sigma_and_names_it`;
   Task 3: `test_a_zero_sigma_fit_ticked_shows_why_and_disables_use_average`).
3. **An old project file, version 1 or 2, with `velocity_from_fit`.** It loads, keeps the
   velocity's provenance, and saves as 3. One naming a missing fit loads with no record (Task 1:
   `test_an_old_velocity_from_fit_loads_as_a_one_fit_record`,
   `test_an_old_velocity_from_fit_naming_a_missing_fit_loads_no_record`).
4. **A grid with many fitted lines whose zero needs the line read.** The dialog must read each
   line once, not once per repaint or tick (Task 4:
   `test_grid_dialog_reads_each_fitted_lines_zero_once`).
5. **Signals while the dialog fills its own tick boxes.** Setting a check state emits
   `itemChanged`. The average must not recompute per row, and must not loop (Task 3:
   `test_opening_the_dialog_computes_the_average_once`).

---

### Task 1: The velocity source record, the weighted mean, and the project file

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/velocity_source.py`
- Modify:
  - `packages/nsgeo-core/src/nsgeo/model/survey.py` (`Line`)
  - `packages/nsgeo-core/src/nsgeo/geometry/grid.py` (`Grid`)
  - `packages/nsgeo-core/src/nsgeo/project.py` (versions, save, load)
  - `packages/nsgeo-core/src/nsgeo/__init__.py` and the core `README.md` (public names)
- Test:
  - Create `packages/nsgeo-core/tests/test_velocity_source.py`.
  - Modify `packages/nsgeo-core/tests/test_project.py`. `test_rejects_future_schema_version`
    writes 3 today; change it to 4. Change the existing `velocity_from_fit` tests to the record.
  - Modify `packages/nsgeo-core/tests/test_public_api.py`.

**Interfaces:**
- Produces, in `nsgeo.velocity_source`:
  - `METHOD_FIT = "fit"`, `METHOD_WEIGHTED_MEAN = "weighted mean"`
  - `@dataclass(frozen=True) class SourceFit`:
    - fields `line_key: str`, `fit_id: str`, `fitted_at: str`, `line_label: str`, `t0_ns: float`,
      `v_m_ns: float`, `v_stderr_m_ns: float`, `zero_ns: float`
    - `classmethod of(line_key, fit_id, line_label, fit: StoredFit) -> SourceFit`. It copies
      `fit`'s numbers. The caller passes the fit already measured at the zero it used.
    - `names(fit_id: str, fit: StoredFit) -> bool`: the id and `fitted_at` both match.
    - `to_dict()` / `from_dict()`
  - `@dataclass(frozen=True) class VelocitySource`:
    - fields `method: str`, `members: tuple[SourceFit, ...]`, `v_m_ns: float`,
      `v_stderr_m_ns: float`, `applied_at: str | None`
    - `classmethod from_fits(members: Sequence[SourceFit], applied_at: str | None) -> VelocitySource`.
      One member gives `METHOD_FIT` with that member's v and σ. More than one gives
      `METHOD_WEIGHTED_MEAN` via `weighted_mean`.
    - `summary() -> str`: `"average of 6 fits"`, or `"fit on FILE__003"` for `METHOD_FIT`.
    - `to_dict()` / `from_dict()`. `from_dict` raises `ValueError` on:
      - an unknown method;
      - no members;
      - a non-finite number.
  - `weighted_mean(values: Sequence[tuple[float, float]]) -> tuple[float, float]`, for
    `(v, σ)` pairs: `(Σ v/σ² / Σ 1/σ², 1/√Σ 1/σ²)`.
    - It raises `ValueError("fit {i} has σ {s}; it cannot be weighted")` (i is 1-based) for
      σ ≤ 0 or a non-finite σ.
    - It raises `ValueError("no fits")` when `values` is empty.
- Produces on the models:
  - `Line.velocity_source: VelocitySource | None = None`, `Line.fit_serial: int = 0`
  - a read-only `Line.velocity_from_fit -> str | None` property (P2)
  - `Grid.velocity_source: VelocitySource | None = None`
- Produces in `nsgeo.project`: `VELOCITY_SOURCE_SCHEMA_VERSION = 3`,
  `READABLE_SCHEMA_VERSIONS = (1, 2, 3)`.

- [ ] **Step 1: Write the failing tests for the arithmetic and the record**

```python
def test_weighted_mean_matches_hand_values():
    v, s = weighted_mean([(0.0921, 0.0041), (0.0874, 0.0028), (0.0898, 0.0033)])
    w = [1 / 0.0041**2, 1 / 0.0028**2, 1 / 0.0033**2]
    assert v == pytest.approx((0.0921 * w[0] + 0.0874 * w[1] + 0.0898 * w[2]) / sum(w), rel=1e-12)
    assert s == pytest.approx(1 / math.sqrt(sum(w)), rel=1e-12)
    assert s < 0.0028  # tighter than any single fit

def test_weighted_mean_of_one_fit_is_that_fit():
    assert weighted_mean([(0.09, 0.003)]) == (0.09, 0.003)

def test_weighted_mean_refuses_a_zero_sigma_and_names_it():
    with pytest.raises(ValueError, match="fit 2 has σ 0.0"):
        weighted_mean([(0.09, 0.003), (0.088, 0.0)])
    # also: σ < 0, σ = nan, σ = inf, and an empty list ("no fits")

def test_one_member_is_a_fit_record_and_several_an_average():
    # from_fits([m]).method == METHOD_FIT, with m's v and σ
    # from_fits([m1, m2]).method == METHOD_WEIGHTED_MEAN, with weighted_mean's v and σ
    # summary(): "fit on FILE__003" and "average of 2 fits"

def test_a_record_round_trips_through_its_dict_bit_for_bit():
    # VelocitySource.from_dict(src.to_dict()) == src, members included; applied_at None too

def test_a_member_names_a_fit_only_with_the_same_fitted_at():
    # m.names("fit-1", fit) True; the same id with another fitted_at is False
```

- [ ] **Step 2: Run them and see them fail** (`ModuleNotFoundError: nsgeo.velocity_source`).

- [ ] **Step 3: Implement `nsgeo/velocity_source.py`** to the Interfaces above.

- [ ] **Step 4: Write the failing tests for the models and the file**, in `test_project.py`:

```python
def test_a_site_without_records_saves_as_today(tmp_path, site):
    # schema_version 1 without cuts (2 with cuts), as before; no "velocity_source" keys

def test_a_line_record_lifts_the_file_to_version_3_and_round_trips(tmp_path, site):
    # line.velocity_source set -> schema_version 3; load gives an equal record

def test_a_grid_record_lifts_the_file_to_version_3_and_round_trips(tmp_path, site): ...

def test_version_3_loads_and_4_is_refused(tmp_path, site): ...

def test_an_old_velocity_from_fit_loads_as_a_one_fit_record(tmp_path, site):
    # a version-1 file: velocity_fits {"fit-2": fit}, velocity_from_fit "fit-2"
    # -> velocity_source.method == METHOD_FIT, members[0] == SourceFit.of(key, "fit-2", label, fit)
    #    applied_at None; line.velocity_from_fit == "fit-2"; saving it writes version 3

def test_an_old_velocity_from_fit_naming_a_missing_fit_loads_no_record(tmp_path, site): ...

def test_a_record_naming_a_line_or_fit_the_file_lacks_still_loads(tmp_path, site):
    # members point at "raw/GONE.DZT" fit-9; load keeps the record unchanged (§9)

def test_fit_serial_saves_and_loads_without_lifting_the_version(tmp_path, site):
    # fit_serial 5, no records -> version 1, "fit_serial": 5 in the entry, loads as 5

def test_fit_serial_on_an_old_file_is_its_highest_fit_number(tmp_path, site):
    # fits {"fit-1", "fit-4", "f7"} and no fit_serial key -> fit_serial 4 (P7)

def test_velocity_from_fit_reads_none_when_the_record_is_an_average_or_its_fit_is_gone(): ...
```

- [ ] **Step 5: Run them and see them fail.**

- [ ] **Step 6: Implement the fields, the property and save/load.**
  - The version is 3 if any line or grid has a record; else 2 with cuts; else 1.
  - Write `"velocity_source"` on line entries and grid dicts. Stop writing `"velocity_from_fit"`.
  - Read either key. A `"velocity_source"` that fails `from_dict` is a `ProjectError` naming the
    line or grid.
  - Update the core README and `EXPECTED_PUBLIC`.

- [ ] **Step 7: Run core + pure, and mypy (Global Constraints).** All pass.

- [ ] **Step 8: Commit and push.**

---

### Task 2: The session keeps the records

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py`. Update
  `test_plugin_velocity_fit.py` and `test_plugin_velocity_dialog.py` only where a test constructed
  or replaced `velocity_from_fit` directly.

**Interfaces:**
- Consumes: Task 1's types and fields.
- Produces on `SiteSession`:
  - `add_velocity_fit(key, fit) -> str`: the id is `f"fit-{n}"`, where n is one more than the
    larger of `fit_serial` and the highest existing number. It stores `fit_serial = n`.
  - `remove_velocity_fit(key, fit_id) -> None`: it no longer touches any record (§7.3).
  - `set_line_velocity(key, model)` and `set_grid_velocity(grid_id, model)`: they now also set
    the record to `None` (P3).
  - `apply_line_velocity(key, model: VelocityModel | None, source: VelocitySource | None) -> None`,
    one `lines_changed`.
  - `apply_grid_velocity(grid_id, model, source) -> None`, one `grids_changed`.
  - `set_velocity_from_fit(key, fit_id)`, kept until Task 4. It builds a one-member record from
    the stored fit as stored. `None` clears the record and keeps the velocity.
  - `member_state(member: SourceFit, grid_id: str | None = None) -> str` returns one of:
    - `"present"`;
    - `"deleted"`: the line exists, but no fit there `names()` the member;
    - `"line removed"`;
    - `f"line moved to grid {gid}"`: only when `grid_id` is given and the line is now on
      another grid; a loose line gives `"line moved off this grid"`.
  - `member_fit(member) -> StoredFit | None`: the stored fit when the state is `"present"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_fit_ids_are_never_reused_after_a_delete(session_with_line):
    # add fit-1, fit-2; remove fit-2; add -> "fit-3"; remove all; add -> "fit-4"

def test_fit_ids_survive_save_and_load(tmp_path, ...):
    # add fit-1, fit-2, remove fit-2, save, load, add -> "fit-3"

def test_deleting_a_member_keeps_the_record_and_the_velocity(...):
    # apply_line_velocity(key, model, VelocitySource.from_fits([m], ts)); remove_velocity_fit
    # -> velocity unchanged, velocity_source unchanged, member_state(m) == "deleted"

def test_a_bare_velocity_drops_the_record(...):
    # line and grid: set_*_velocity(..., VelocityModel.constant(0.1)) -> velocity_source None

def test_apply_sets_velocity_and_record_with_one_signal(...):
    # count lines_changed / grids_changed emissions == 1

def test_member_state_names_each_way_a_member_goes(...):
    # present; deleted; line removed (remove_line); moved to grid B (move_lines);
    # removed and imported again with a new fit-1 -> "deleted" (fitted_at differs)
```

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** to the Interfaces.
- [ ] **Step 4: Run `test_plugin_session.py`, `test_plugin_velocity_fit.py` and
  `test_plugin_velocity_dialog.py`.** Existing tests that expected deleting a fit to clear
  `velocity_from_fit` still pass, because the property reads `None` once the fit is gone (P2).
  Any that break show a behaviour change. Report it rather than editing the expectation away.
- [ ] **Step 5: Commit and push.**

---

### Task 3: The line dialog: ticks, the average, and the Apply rule

**Files:**
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/velocity_dialog.py`
  - `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (`open_velocity_dialog`)
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (`velocity_source` label, line branch
    only)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_velocity_dialog.py`

**Interfaces:**
- Consumes: Task 1's `weighted_mean`, `VelocitySource`, `SourceFit`; Task 2's
  `apply_line_velocity` and `member_state`.
- Produces in `velocity_dialog.py`:
  - module-level
    `fits_at_line_zero(session, key) -> tuple[dict[str, StoredFit], dict[str, str]]`, moved out
    of the method of the same job. Task 4 calls it per line.
  - `VelocityDialog` methods:
    - `ticked_refs() -> list[tuple[str, str]]`
    - `set_ticked(refs: Iterable[tuple[str, str]]) -> None`
    - `average_text() -> str`, `average_meta_text() -> str`, `average_warning_text() -> str`
    - `use_average_button: QPushButton`, `all_check: QCheckBox` (P5)
    - `source_note_text() -> str`
    - `chosen_source() -> VelocitySource | None`
    - `velocity() -> VelocityModel | None`, extended to rule 2 (the unrounded average)
- Produces in `profile_dock.py`: the `velocity_source(session, key)` line branch reads
  `line override, average of 3 fits` when the line's record is an average. A single fit keeps
  `line override (fit at 15.6 ns)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_every_usable_fit_is_ticked_when_there_is_no_record(plugin): ...
def test_an_unusable_fit_cannot_be_ticked(plugin):
    # a fit unmeasurable at the line's zero (as the existing unusable-fit test builds one):
    # its row's check flag is off, and the All box cannot tick it
def test_the_average_reads_weighted_mean_count_and_depth_range(plugin):
    # three fits -> average_text() == f"{v:.4f} ± {s:.4f} m/ns" from weighted_mean;
    # average_meta_text() == "3 fits · t0 from 9.8 to 22.4 ns"
def test_unticking_all_reads_no_fits_ticked_and_disables_use_average(plugin): ...
def test_disagreeing_ticked_fits_show_the_warning_and_agreeing_ones_do_not(plugin): ...
def test_a_zero_sigma_fit_ticked_shows_why_and_disables_use_average(plugin): ...
def test_opening_the_dialog_computes_the_average_once(plugin, monkeypatch):
    # patch velocity_dialog.weighted_mean with a counter; construct -> exactly 1 call
def test_use_average_then_apply_records_the_ticked_fits_unrounded(plugin):
    # 3 ticked, Use average, Apply -> line.velocity.surface_velocity == weighted mean (rel 1e-12);
    # velocity_source.method == METHOD_WEIGHTED_MEAN, members == the 3 at the line's zero
def test_use_average_with_one_tick_records_a_fit(plugin): ...
def test_a_picked_row_then_apply_records_that_fit(plugin): ...
def test_an_untouched_apply_keeps_the_record_as_it_was(plugin):
    # record exists (applied_at "2026-11-01T00:00:00Z"); open, Apply -> identical record
def test_a_number_typed_over_the_average_drops_the_record(plugin): ...
def test_ticks_changed_after_use_average_without_a_second_press_drop_the_record(plugin): ...
def test_reopening_ticks_the_records_members(plugin): ...
def test_the_note_names_a_deleted_member_and_a_time_zero_change(plugin):
    # record of 2 fits; delete one; add a time_zero step -> source_note_text() contains
    # "This velocity is the average of 2 fits", "deleted", and "now gives" with the refit v
def test_clear_override_drops_velocity_and_record(plugin): ...
def test_deleting_a_member_says_so_in_the_confirmation_and_keeps_the_velocity(plugin, answer_modal):
    # the QMessageBox.question text names the line's average; after Yes, velocity and record stay
def test_the_profile_label_names_an_average_on_the_line(plugin): ...
```

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
  - The tick column is column 0. Every other column moves right by one, including
    `_FLAG_COLUMN`. Fill check states with the table's signals blocked, then compute the
    average once.
  - Track what last filled the box: `"none"`, `"average"` (with the refs ticked at the press) or
    `"pick"` (with the ref), plus the value it put there. §7.2's rules then read off that and the
    box. `plugin.open_velocity_dialog` calls
    `session.apply_line_velocity(key, dialog.velocity(), dialog.chosen_source())`.
  - Members are built with `SourceFit.of(key, fit_id, label, fit_at_zero_fit)`, using the
    numbers the table shows.
- [ ] **Step 4: Run `test_plugin_velocity_dialog.py`, `test_plugin_velocity_fit.py` and
  `test_plugin_profile_dock.py`.** All pass.
- [ ] **Step 5: Commit and push.**

---

### Task 4: The grid scope, its wiring, the labels, the strip and Edit grid

**Prerequisite:** piece 1 has merged to main and main is merged into this branch (see Order).

**Files:**
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/velocity_dialog.py` (grid scope)
  - `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`: new `open_grid_velocity_dialog(grid_id)`.
    `survey_dock.grid_velocity_requested` connects to it instead of `open_grid_dialog`. The
    Edit grid finish path changes too.
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/survey_dock.py` (grid row)
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`: the `velocity_source` grid branch, and
    both strip Apply slots.
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py`: remember the box's opening value.
  - `packages/nsgeo-qgis/nsgeo_qgis/session.py`: remove `set_velocity_from_fit`.
- Test:
  - Create `packages/nsgeo-qgis/tests/qgis/test_plugin_grid_velocity_dialog.py`.
  - Modify `test_plugin_survey_dock.py`, `test_plugin_velocity_fit.py` and
    `test_plugin_grid_dialog.py`.

**Interfaces:**
- Consumes: Tasks 1–3, and piece 1's `_just_saved` / `_saved_fit_now()` in `profile_dock.py`.
  `_saved_fit_now()` returns the saved fit measured at the line's current zero.
- Produces:
  - `VelocityDialog(session, grid_id=...)`, with `row_ref(row) -> tuple[str, str]`,
    `select_row(row)` and `starred_note_text() -> str`.
  - `NsgeoPlugin.open_grid_velocity_dialog(grid_id: str) -> None`.
  - `GridDialog.velocity_unchanged() -> bool`: the box still shows its opening value, to 4 dp.

- [ ] **Step 1: Write the failing tests** in `test_plugin_grid_velocity_dialog.py`, on a fixture
  of three lines on grid A and one on grid B. The lines have fits with deliberately repeated ids.

```python
def test_grid_dialog_lists_every_fit_on_the_grids_lines_only(plugin):
    # rows for A's lines' fits only, sorted by line (survey order) then t0; the Line column text
    # is the line label; the title is "Velocity · A" and the box's hint is the pinned sentence
def test_grid_dialog_lights_the_picked_fits_curve_when_its_line_is_open(plugin):
    # pick a row of the open line -> the profile highlights that fit; another line's row -> none
def test_grid_dialog_stars_lines_with_their_own_velocity_and_names_them(plugin):
    # starred_note_text() == "* FILE__002 has its own velocity (0.0889). Apply doesn't change it."
def test_grid_dialog_deletes_the_fit_of_the_row_picked_not_another_lines_fit_1(plugin, answer_modal): ...
def test_grid_dialog_flags_disagreement_across_lines(plugin): ...
def test_grid_dialog_apply_of_an_average_sets_grid_velocity_and_record_not_line_overrides(plugin): ...
def test_grid_dialog_reopens_with_the_records_members_ticked(plugin): ...
def test_grid_dialog_note_names_a_member_moved_to_another_grid_and_a_removed_line(plugin): ...
def test_grid_dialog_with_no_fits_says_so_and_still_applies_a_typed_velocity(plugin): ...
def test_grid_dialog_clear_drops_velocity_and_record(plugin): ...
def test_grid_dialog_reads_each_fitted_lines_zero_once(plugin, monkeypatch):
    # count velocity_dialog.fits_at_line_zero calls: one per line with fits, then none on
    # tick, untick, pick, Use average
def test_set_velocity_on_a_grid_row_opens_the_grid_velocity_dialog(plugin, answer_modal):
    # survey_dock.grid_velocity_requested.emit("A") opens VelocityDialog in grid scope, not
    # GridDialog
def test_real_grid2_lines_list_and_average_their_fits(tmp_path, ...):
    # skip if GRID2_LINES is empty; four real lines with a Time zero preset and stored fits ->
    # the dialog lists them at each line's zero, and Apply records them
```

  In the other test files:

```python
# test_plugin_survey_dock.py
def test_grid_row_names_where_its_velocity_came_from(dock):
    # "v 0.090 (average of 6 fits)", "v 0.090 (fit on FILE__003)", plain "v 0.090"; piece 1's
    # " · N fits on M lines" still ends the row
# test_plugin_velocity_fit.py
def test_strip_apply_to_grid_after_save_records_the_saved_fit(plugin, message_log): ...
def test_strip_apply_to_grid_of_an_unsaved_fit_records_nothing(plugin, message_log): ...
def test_strip_apply_to_line_after_save_records_the_fit_at_the_lines_zero(plugin, message_log): ...
def test_profile_label_names_the_grids_source(plugin): ...
# test_plugin_grid_dialog.py
def test_edit_grid_ok_with_the_velocity_untouched_keeps_a_velocity_set_meanwhile(...):
    # open Edit grid; apply_grid_velocity(A, v2, record); OK in Edit grid -> v2 and the record stay
def test_edit_grid_ok_with_a_changed_velocity_writes_it_and_drops_the_record(...): ...
```

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
  - Grid scope rows come from `session.keys_on_grid(grid_id)`. Each line with fits goes through
    `fits_at_line_zero` once (P9).
  - Delete in grid scope uses the row's own line key.
  - The confirmation adds the member sentence when the fit is a member of the grid's record or
    of its line's record (§4.4).
  - The strip's Apply slots call `apply_line_velocity` / `apply_grid_velocity`:
    - a saved fit gets a one-member record built from `_saved_fit_now()`;
    - an unsaved working fit gets `source=None` on the grid. On the line it keeps today's rule:
      a stored fit with the same points becomes the record, measured at the line's zero.
  - Edit grid's finish: when `velocity_unchanged()`, take `velocity` and `velocity_source` from
    the session's grid at OK time. Otherwise use the box's number with `velocity_source=None`.
  - Remove `set_velocity_from_fit` once nothing calls it.
- [ ] **Step 4: Run the five touched QGIS test files and core + pure.** All pass.
- [ ] **Step 5: Commit and push.**

---

### Task 5: Slices take their depths from the grid's velocity

**Prerequisite:** PR #175 has merged to main and main is merged into this branch (see Order).

**Files:**
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/session.py`: rename `cut_velocity` to `grid_depth_velocity`,
    and update both callers in the file.
  - `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py` (`provenance()`)
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` (`_resolved_velocity`,
    `_update_velocity_label`)
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py` (`grid_velocity`)
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`: new `grid_velocity_label` next to
    `velocity_source`.
- Test: `test_plugin_slices_engine.py`, `test_plugin_slices_dock.py`,
  `test_plugin_site_scope.py`, `test_plugin_session_cuts.py`.

**Interfaces:**
- Consumes: Task 1's `VelocitySource.summary()`.
- Produces:
  - `SiteSession.grid_depth_velocity(grid_id: str) -> VelocityModel`. This is
    `cut_velocity`'s rule and its `KeyError`, under the new name.
  - `grid_velocity_label(session, grid_id) -> str`, giving `Grid G2, average of 6 fits` /
    `Grid G2, fit on FILE__003` / `Grid G2` / `header ε 9, FILE__001`.
  - `SlicesDock._resolved_velocity() -> tuple[str | None, VelocityModel | None]`, which now
    returns `(grid_id, model)` from `engine.choice.grid_id`.

- [ ] **Step 1: Write the failing tests.** Each one gives the grid's first line in survey order,
  and the first prepared line, an override different from the grid's velocity. This is the
  hazard input; a test without it proves nothing (spec §12).

```python
def test_slice_provenance_velocity_is_the_grids_not_the_first_lines_override(...):
    # grid A v 0.09; FILE__001 override 0.12 -> engine.provenance().velocity ==
    # VelocityModel.constant(0.09).to_dict()
def test_slice_label_and_readout_use_the_grids_velocity(...):
    # velocity_label text == "v = 0.090 m/ns (Grid A)"; the readout's metres use 0.09
def test_slice_label_names_the_grids_record(...):
    # grid record of 2 fits -> "(Grid A, average of 2 fits)"
def test_slice_label_without_a_grid_velocity_names_the_header_and_line(...):
    # "(header ε 9, FILE__001)"
def test_whole_site_uses_each_grids_velocity(...):
    # site_scope.grid_velocity == session.grid_depth_velocity(grid)
def test_removing_the_first_line_still_leaves_a_valid_slice_label(...):
    # the existing KeyError guard, kept
def test_real_grid2_slice_depth_follows_the_grid_with_an_override_on_the_first_line(...):
    # skip if GRID2_LINES is empty
```

- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** to the Interfaces. Keep the `KeyError` / `RuntimeError` guards the
  three places already have.
- [ ] **Step 4: Run the four slice/cut QGIS test files and core + pure.** All pass. `grep -rn
  cut_velocity packages` finds nothing.
- [ ] **Step 5: Commit, push, and update the README roadmap.** The In progress entry for velocity
  from fits now reads: built, walkthrough next.

---

## After the tasks

A whole-branch review (opus). Then deploy to QGIS profile `ns_geo_grid_velocity` (a copy of
`ns_geo`) and write the walkthrough from spec §13 as an Artifact with the `db` capability. The
0.4.0 refusal check is marked data-loss relevant. Merge only after the author's walkthrough.
