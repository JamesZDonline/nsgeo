# 3-D follow-ups (session S) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surfaces stop reading stale when nothing changed. The 3-D view reads each line's file
once at most, and on channel 0. Plan D's five tidy-ups are done.

**Architecture:** Five small changes to existing modules, mostly `surface_plan.py`,
`surfaces.py` and `paraview_export.py`:
- one rounding for the 3-D cell (#204);
- a fallback to the newest built surface's choice when the grid's record is empty (#203);
- a remembered time-zero failure (#219);
- channel 0 for time zero (#218);
- #228's tidy-ups, the last two after session F merges.

**Tech Stack:** Python 3, PyQGIS (QGIS 3.44 locally), pytest, the `nsgeo` core.

**Spec:** `docs/superpowers/specs/2026-11-20-nsgeo-3d-follow-ups-design.md`. Read it first.
Background: `docs/superpowers/sdd/2026-11-13-nsgeo-m16-b-surfaces-from-picks` (rulings R10,
R11 and R15).

Paths below are under `packages/nsgeo-qgis/` unless they start with `docs/`.

## Global Constraints

- **The test recipe for each task** (run from the worktree root):
  - core and pure:
    `PYTHONDONTWRITEBYTECODE=1 /home/jameszd/Documents/Github/archaeo_geophysics/.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh`;
  - the QGIS files the task touches:
    `PYTHONDONTWRITEBYTECODE=1 packages/nsgeo-qgis/scripts/qgis_tests.sh <files> -q`;
  - the real-data tests:
    `PYTHONDONTWRITEBYTECODE=1 packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis -m real_data -q`.
  - Never run `qgis_tests.sh full`. CI runs the whole tier on every push.
- **Lint and types:** `ruff check .` and `ruff format --check .` are clean. `surface_plan.py`
  is checked by mypy in CI, so give it full annotations.
- **Each new test fails on main before its fix.** Run it before you implement, and put the
  failure line in your report.
- **Push every commit:** `git push`. The branch already tracks `origin/nsgeo-3d-follow-ups`.
- **The repo is public.** No survey or site names go into code, tests, comments, docs or commit
  messages. Call the real site "the M16 walkthrough site".
- **Real-data tests:**
  - Their skip reason names `tests/data/local`, so the `real_data` mark is applied
    automatically.
  - They copy the site file into `tmp_path` and never write to the original.
- **Commits** end with `Co-Authored-By:` and your own model's name.
- **Messages and log lines are plain:** no em dashes in new user-facing text, as in the
  surrounding code.

## Review Focus

1. **A cell whose 3-decimal rounding falls below the grid's smallest safe cell.** The
   remembered cell must round up, never produce a cell the export refuses. *Task 1, pure test
   rows `(0.0504, 0.051)`.*
2. **Two builds within one second.** `built_utc` is to the second, so ties go to the newer
   json's modification time. *Task 2, `test_the_newest_built_surface_is_the_fallback`.*
3. **A grid holding both old surfaces (no `"choice"` in the json) and new ones.** Old ones are
   skipped. With none left, the panel's values are used as today. *Task 2, same test.*
4. **A new 3-D view (a new `ParaViewExport`) after a failure.** It tries the line again. A plain
   refresh does not. *Task 3, `test_a_line_whose_zero_cannot_be_read_is_read_and_logged_once`.*
5. **A cut pick clicked while its section is already shown, or a different line opened before
   the section loads.** The first moves the cursor at once. The second drops the target, so the
   cursor never jumps later. *Task 5's item 4 tests.*

---

### Task 1: One rounding for the 3-D cell (#204)

**Files:**
- Modify: `nsgeo_qgis/surface_plan.py` (beside `remembered_step`, ~line 311)
- Modify: `nsgeo_qgis/paraview_export.py`: `defaults()` (~line 294), plus a new `cell_floor`
- Modify: `nsgeo_qgis/surfaces.py`: `_compute` (~line 577) and `inputs` (the `resolution`
  input, ~line 385)
- Modify: `tests/plugin_testing.py`: the walkthrough site helpers
- Test: `tests/pure/test_pure_surface_plan.py`, `tests/qgis/test_plugin_surface_build.py`
- Create: `tests/qgis/test_plugin_surfaces_walk_site.py`

**Interfaces:**
- Produces:
  - `surface_plan.remembered_cell(cell: float, floor: float) -> float`;
  - `ParaViewExport.cell_floor(grid_id: str) -> float`;
  - in `plugin_testing.py`:
    - `WALK_SITE: Path`, which is `LOCAL_DATA / "hand-fits" / "site-2.nsgeo.json"`;
    - `needs_walk_site`, a `skipif` whose reason is
      `"no M16 walkthrough site in tests/data/local"`;
    - `open_walk_site(tmp_path, *, edit=None) -> SiteSession`, which copies the json into
      `tmp_path / "walk site" / "survey.nsgeo.json"`, applies `edit(doc)` when given, and opens
      the copy.
  - `defaults()` now returns a remembered cell. Task 2 builds on `defaults()`.

- [ ] **Step 1: Write the failing pure tests.** In `test_pure_surface_plan.py`:

```python
@pytest.mark.parametrize(
    "cell, floor, want",
    [
        (0.05000000000000002, 0.0, 0.05),  # the M16 walkthrough site's Grid1 panel cell
        (0.15 - 0.1, 0.0, 0.05),
        (0.1234, 0.0, 0.123),
        (0.25, 0.0, 0.25),
        (0.0504, 0.051, 0.051),  # rounding down would pass the floor: round up
        (0.0506, 0.051, 0.051),
        (0.051, 0.051000000000000004, 0.051),  # a floor's own float tail is no reason to move
        (0.0004, 0.0, 0.001),  # never below the dialog's minimum
    ],
)
def test_remembered_cell(cell, floor, want):
    assert remembered_cell(cell, floor) == want


@pytest.mark.parametrize("cell", [0.05000000000000002, 0.1234, 0.0504, 0.0004, 1.0])
def test_remembered_cell_is_its_own_fixed_point(cell):
    once = remembered_cell(cell, 0.051)
    assert remembered_cell(once, 0.051) == once
```

- [ ] **Step 2: Write the failing QGIS test.** In `test_plugin_surface_build.py`, next to the
  R11 test `test_building_then_exporting_at_the_dialogs_defaults_keeps_surfaces_fresh`:

```python
@pytest.mark.parametrize("cell", [0.15 - 0.1, 0.1234, 0.05000000000000002])
@pytest.mark.parametrize("where", ["panel", "record"])
def test_an_untouched_export_keeps_a_surface_fresh_at_any_cell(built_site, cell, where):
    """#204: the dialog's Cell box has 3 decimals, so an untouched export writes back the
    rounded cell. The build must have used that same cell."""
```

  - Set the cell:
    - `"panel"`: `session.remember_slice_resolution(GRID, cell=cell)`;
    - `"record"`: `session.remember_volume(GRID, cell=cell)`.
  - Build one surface (`_surface`, then `surfaces.build`).
  - `built = surfaces.state(fid).report["resolution"]["cell"]`.
  - `assert built == round(cell, 3)`.
  - Open `ParaViewExportDialog` exactly as the R11 test does, take `dialog.choice()`, and call
    `session.remember_volume(GRID, **choice.to_record())`.
  - Then assert:
    - `session.volume_record(GRID)["cell"] == built`;
    - `surfaces.state(fid).stale == ()`.

- [ ] **Step 3: Write the failing real-data test.** In the new
  `tests/qgis/test_plugin_surfaces_walk_site.py`, marked `@needs_walk_site`:
  - The fixture `walk(qgis_app, tmp_path)`:
    - opens `open_walk_site(tmp_path)`, with a `Dock` (from `plugin_testing`), `SiteLayers` and
      `Surfaces`;
    - wires the export as the plugin does: `export.surfaces = surfaces`, and `Surfaces` gets
      `export_for=lambda: export`;
    - yields `(session, dock, export, layers, surfaces)`.
  - `test_the_walk_sites_float_tail_cell_survives_an_untouched_export(walk)`:
    - Precondition: `session.slice_resolution("Grid1")["cell"] == 0.05000000000000002`.
    - Write four picks on four different lines of `source_keys(session, "Grid1")`, at traces
      inside each line and times between 10 and 20 ns. Create a surface from them and build it.
    - Assert it's fresh.
    - Do the untouched dialog round trip from Step 2, then assert:
      - the record's cell is `0.05`;
      - the surface is still fresh.
  - Time the build. If it takes more than 3 minutes, set the copy's Grid1 fill method to IDW
    through `edit=`, and say so in the docstring: the fill method is not what this test is
    about.
  - Task 2 extends this same test, so the build happens once.

- [ ] **Step 4: Run all three and confirm they fail on main.**
  - The pure test fails with an ImportError for `remembered_cell`.
  - The QGIS test fails on its last `stale == ()`, which reads `('resolution',)`.
  - So does the real-data test.

- [ ] **Step 5: Implement.**
  - **`remembered_cell`:**
    - `r = round(cell, 3)`;
    - if `r < floor - 1e-9`, round `cell` up to 3 decimals instead, as
      `round(math.ceil(cell * 1000 - 1e-6) / 1000, 3)`;
    - return `max(r, 0.001)`.
    - Its docstring cites #204 and the dialog's 3 decimals.
  - **`ParaViewExport.cell_floor(grid_id)`:** `smallest_safe_cell(grid.size_x, grid.size_y)`.
  - **`defaults()`:** return the choice with
    `cell=remembered_cell(choice.cell, self.cell_floor(grid_id))`, using `dataclasses.replace`.
  - **`Surfaces._compute`:** apply the same next to the `remembered_step` line.
  - **`Surfaces.inputs`:** apply it to the `resolution` input's `"cell"`.
  - The last two make the rule explicit where R11's is, even though `defaults()` already
    applies it.

- [ ] **Step 6: Run the recipe.**
  - The touched QGIS files are `test_plugin_surface_build.py`,
    `test_plugin_paraview_export.py`, `test_plugin_paraview_dialog.py` and
    `test_plugin_surfaces_walk_site.py`. Expect all green.
  - If any existing test pinned an unrounded cell, name it in the report before you change it.

- [ ] **Step 7: Commit and push.**
  `fix(3d): one rounding for the 3-D cell, so an untouched export keeps surfaces fresh (#204)`

---

### Task 2: An empty grid record falls back to the newest built surface (#203)

**Files:**
- Modify: `nsgeo_qgis/surfaces.py`: `__init__`, `_write` (the report dict, ~line 740),
  `build`, and a new `built_choice`
- Modify: `nsgeo_qgis/paraview_export.py`: `defaults()`
- Modify: `docs/guide/getting-started.md`: the paragraph at ~1016–1019 ("One thing is saved
  with **Save site** after all …")
- Test: `tests/qgis/test_plugin_surface_build.py`, `tests/qgis/test_plugin_surfaces_walk_site.py`

**Interfaces:**
- Consumes: Task 1's `defaults()`, with its cell remembered.
- Produces:
  - `Surfaces.built_choice(grid_id: str) -> dict[str, float | str] | None`;
  - `Surfaces.forget_built_choices() -> None`;
  - each surface json gains a `"choice"` key holding `choice.to_record()`.

- [ ] **Step 1: Write the failing tests** in `test_plugin_surface_build.py`.
  - **A shared helper.** Factor R15's reopen (in
    `test_reopening_without_save_site_keeps_built_surfaces_fresh`) into a context manager
    `_reopened(session)`:
    - it yields `(again, dock2, export2, reopened)`;
    - it wires `export2.surfaces = reopened`, as the plugin does;
    - R15's test keeps passing through it.
  - **The parametrized test:**

```python
@pytest.mark.parametrize("what", ["transform", "volume", "cell"])
def test_a_reopen_without_save_site_keeps_the_built_choice(built_site, what):
    """#203: after a reopen without Save site the grid's record is empty, so the 3-D choice
    falls back to the newest built surface's, not the Slices panel's."""
```

  - Setup: `export.surfaces = surfaces` and `session.save(allow_absolute=True)`. Then, per
    case:
    - `"transform"`: `dock.transform_combo = types.SimpleNamespace(value=lambda: "amp_abs")`;
    - `"volume"`: `session.remember_volume(GRID, period_ns=<twice the default period>)`;
    - `"cell"`: `session.remember_slice_resolution(GRID, cell=0.2)`, after the save, so it is
      not saved.
  - Build one surface. Keep `first = surfaces.state(fid).report["choice"]`.
  - Reopen with `_reopened` and assert:
    - `again.volume_record(GRID) == {}`;
    - `reopened.state(fid).stale == ()`.
  - Then change the panel and check again:
    - `"transform"`: `dock2` reports `"amp_envelope"`;
    - `"cell"`: `again.remember_slice_resolution(GRID, cell=0.3)`;
    - `"volume"`: nothing (the panel holds no wave period).
    - Assert `stale == ()` again.
  - Rebuild with `reopened.build([fid], progress=_noop)`, then assert both:
    - `reopened.state(fid).report["choice"] == first`;
    - `again.volume_record(GRID) == first`.

```python
def test_the_newest_built_surface_is_the_fallback(built_site):
```

  - Setup: `export.surfaces = surfaces`, then save the site.
  - Build two surfaces, one at a time:
    - surface A with `remember_volume(GRID, cell=0.2)` before its build;
    - surface B with `remember_volume(GRID, cell=0.25)` before its build, straight after A, in
      the same second, which is fine.
  - Reopen, then assert:
    - `export2.defaults(GRID).cell == 0.25`;
    - `reopened.state(A).stale == ("resolution",)` (A was built at 0.2);
    - `reopened.state(B).stale == ()`.
  - Rewrite B's json without `"choice"`, as a build from before this change. Call
    `reopened.forget_built_choices()`, then assert `export2.defaults(GRID).cell == 0.2`.
  - Delete A with `reopened.delete(A)`. Its `features_changed` clears the memo. Then assert
    `export2.defaults(GRID).cell` equals what `defaults()` gave before any build (the panel's
    cell).

- [ ] **Step 2: Extend the real-data test.** In
  `test_the_walk_sites_float_tail_cell_survives_an_untouched_export`:
  - Before the build, set the dock's transform to `"amp_abs"`.
  - After the untouched-export round trip, reopen the copy in a new `SiteSession` without Save
    site, with a dock reporting `"amp_square"`, and assert the surface is fresh. The round
    trip's `remember_volume` was never saved, so it does not reach the reopen.
  - Rename the test to `test_the_walk_site_keeps_a_built_surface_fresh` and give it a docstring
    naming both issues.

- [ ] **Step 3: Run them and confirm they fail on main.**
  - Expect a `KeyError: 'choice'`, or `stale == ('source',)`, `('volume',)` or
    `('resolution',)`.

- [ ] **Step 4: Implement.**
  - **`_write`:** add `"choice": choice.to_record()` to the report.
  - **`Surfaces.built_choice(grid_id)`:**
    - Look only at the records on `grid_id` whose `_read_report` is whole and whose
      `report["choice"]` is a dict.
    - Return the newest one's `"choice"`, by `(report["built_utc"], the json's st_mtime_ns)`,
      or None when there is none.
    - Keep the answer in `self._built_choices: dict[str, dict | None]`.
  - **`forget_built_choices()`:**
    - It clears the memo.
    - `__init__` connects it to `session.site_opened`, `session.site_closed` and
      `session.features_changed`.
    - `build` calls it in its `finally`.
  - **`defaults()`:** take `record = self.session.volume_record(grid_id)`. When it is empty and
    `self.surfaces is not None`, use `self.surfaces.built_choice(grid_id) or {}`. Pass that
    record to `volume_choice`. Nothing else in `defaults()` changes.
  - **The guide's paragraph:** say that a build remembers the grid's 3-D settings in
    `survey.nsgeo.json`, which Save site writes. If you close without saving, the grid takes
    them from its newest built surface the next time, so its surfaces reopen fresh. Deleting
    the `surfaces` folder then loses only those unsaved settings.

- [ ] **Step 5: Run the recipe.**
  - The touched QGIS files are `test_plugin_surface_build.py`,
    `test_plugin_surfaces_walk_site.py`, `test_plugin_paraview_export.py`,
    `test_plugin_scene3d.py` and `test_plugin_surfaces_dock.py`.
  - Expect all green.

- [ ] **Step 6: Commit and push.**
  `fix(3d): a reopen without Save site takes the 3-D choice from the newest built surface (#203)`

---

### Task 3: Time zero is read once, from channel 0 (#219, #218)

**Files:**
- Modify: `nsgeo_qgis/paraview_export.py`: `__init__`, `_zero_of` (~line 502), a new
  `_zero_or_none`, and `pick_depths` (~line 512)
- Modify: `docs/guide/getting-started.md`, "Step 9: Export for ParaView" (~line 835)
- Test: `tests/qgis/test_plugin_paraview_export.py`, `tests/qgis/test_plugin_surfaces_walk_site.py`

**Interfaces:**
- Produces: `ParaViewExport._zero_or_none(key: str, steps: Sequence[dict[str, Any]]) -> float | None`.
  `_zero_of` keeps its signature.

- [ ] **Step 1: Write the failing tests** in `test_plugin_paraview_export.py`.

```python
def test_a_line_whose_zero_cannot_be_read_is_read_and_logged_once(synth_site, monkeypatch):
    """#219: the 3-D view calls pick_depths on every refresh."""
```

  - Rows: one pick on each of the two lines (preset `p` sets time zero).
  - Delete line 0's DZT file. It is synthetic, in `tmp_path`.
  - Count reads by wrapping `Line.load` on the class with `monkeypatch`, and collect
    `paraview_export._log` messages.
  - Call `export.pick_depths(GRID, rows)` twice, then assert:
    - line 0 was read once;
    - one log line names line 0's key;
    - line 0's pick is None both times and line 1's pick is a number.
  - Change the preset: `session.site.presets["p"] = [*STEPS_ZERO, {"step": "dewow", "params": {}, "enabled": False}]`.
    Call `pick_depths` again: read twice, logged twice.
  - Make a new `ParaViewExport(session, dock)` on the changed preset and call it: read three
    times.

```python
def test_on_a_two_channel_line_the_3d_work_reads_channel_0(qgis_app, tmp_path):
    """#218. Synthetic on purpose: every real file so far has one channel."""
```

  - **The site:** its own, on `GRID`.
    - Line 0 is a two-channel DZT written with `tests.synthetic.write_dzt(..., n_channels=2)`.
      The data has shape `(2, n_samples, n_traces)`, with a strong first arrival at a different
      sample on each channel, at least 20 samples apart.
    - Line 1 is an ordinary `synthetic_dzt`.
    - The preset is `p = STEPS_ZERO`.
  - **Setup:**
    - Open line 0 so its profiles load, then `session.set_channel(key0, 1)`.
    - Assert that the two channels' `StepStack.zero_ns()` differ.
  - **The pick:** a `Pick` on line 0 made on channel 1, so its `zero_ns` is channel 1's zero.
  - **First assertion:** `export.pick_depths(GRID, rows)[0] == pytest.approx(placed.depth_m, abs=1e-9)`.
    - `placed` is `place_picks(rows, got.lines, got.prov, got.frame, got.velocity)[0]`.
    - `got` is `export.fill(GRID, export.defaults(GRID), progress=_noop)`.
  - **Second assertion:** with the dock's engine not prepared, `export._record_range(source)`
    equals `dock.engine.prepared_z_bounds()` once a second `Dock` is prepared on the same
    source (see `_prepare_panel`), to `abs=1e-9`.

- [ ] **Step 2: Write the failing real-data test** in `test_plugin_surfaces_walk_site.py`:
  `test_a_moved_line_file_is_read_once_on_the_walk_site(qgis_app, tmp_path, monkeypatch)`.
  - Through `open_walk_site(tmp_path, edit=...)`, point one Grid1 line's `path` at a symlink in
    `tmp_path` to the real file. Then unlink the symlink after the site opens: the file has
    moved away.
  - Call `ParaViewExport(session, Dock(session)).pick_depths("Grid1", rows)` twice. `rows` has
    one pick on that line and one on another line.
  - Assert one log line names the moved line, and the other line's pick is placed.
  - This test needs no build.

- [ ] **Step 3: Run them and confirm they fail on main.**
  - The #219 tests fail on the read and log counts: 2, not 1.
  - The #218 test fails on the depth, off by the difference between the two channels' zeros.

- [ ] **Step 4: Implement.**
  - **`_zero_of`:**
    - It reads `profiles[0]`, and its docstring says that is the volume's channel (#218).
    - A failure is kept in `self._zero_failures[memo]`.
    - A later call with that `memo` re-raises the kept exception without reading.
  - **`_zero_or_none`:**
    - It returns `_zero_of`'s value, or None on any exception.
    - It logs `3-D view: no time zero for line {key}, its picks are left out: {exc}` only when
      the memo was not already a kept failure.
  - **`pick_depths`:** uses `_zero_or_none` in place of its own `try`.
  - **The guide:** add after Step 9's first paragraph: "On a line recorded with more than one
    channel, the 3-D work reads the first channel, whichever channel the Profile panel shows:
    the slices, surfaces, the 3D view and this export."

- [ ] **Step 5: Run the recipe.** The touched QGIS files are `test_plugin_paraview_export.py`,
  `test_plugin_scene3d.py` and `test_plugin_surfaces_walk_site.py`. Expect all green.

- [ ] **Step 6: Commit and push.**
  `fix(3d): time zero is read once per line and preset, from channel 0 as the volume is (#219, #218)`

---

### Task 4: Plan D's tidy-ups that stay out of the Profile panel (#228 items 1, 3, 5)

**Files:**
- Modify: `nsgeo_qgis/surfaces.py`: the skip reasons in `_compute` (~line 628)
- Modify: `nsgeo_qgis/surface_plan.py`: `selection_refusal`'s docstring (~line 127)
- Test: `tests/qgis/test_plugin_surface_build.py`, `tests/qgis/test_plugin_surfaces_membership.py`

**Interfaces:** none new.

- [ ] **Step 1: Write the failing test for item 1** in `test_plugin_surface_build.py`:
  `test_a_cut_pick_with_no_distance_is_reported_as_having_no_depth(built_site)`.
  - Use the existing helpers `_cut_along_line_0` and `_write_cut_picks`, on the time-zero
    clock that preset `p` uses. Write enough line and cut picks that the surface still builds.
  - Null one cut pick's `distance_m` in the picks layer, as a hand edit would.
  - Build, then assert the report's `skipped` holds
    `{"line_key": cut_key, "why": WHY_NO_DEPTH}` and no `WHY_OTHER_CLOCK`.

- [ ] **Step 2: Put back item 3's two assertions** in `test_plugin_surfaces_membership.py`.
  They were dropped in commit 82d34d8; see its diff.
  - **In `test_picks_on_a_cut_that_is_gone_cannot_be_placed`:**
    - `surfaces.create("Cut", [*fids, on_cut])` raises `ValueError`, matching the refusal's
      first words;
    - afterwards `surfaces.records()` is unchanged, and no pick names a feature.
  - **A new `test_line_and_cut_picks_on_one_grid_make_one_selection(site)`:**
    - make line picks plus picks on a real cut on the same grid;
    - `check` returns `refusal == ""` and `grid_id == GRID`.
  - These pin existing behaviour, so they may pass on main. Say so in the report, and break the
    code briefly by hand to show each one can fail.

- [ ] **Step 3: Run item 1's test and confirm it fails on main.** It reports `WHY_OTHER_CLOCK`.

- [ ] **Step 4: Implement.**
  - **Item 1.** In `_compute`, the cut-pick branch checks in this order:
    1. `key not in cuts` gives `WHY_NO_CUT`;
    2. `pick.distance_m is None` gives `WHY_NO_DEPTH`;
    3. `not cut_pick_on_clock(...)` gives `WHY_OTHER_CLOCK`;
    4. anything else gives `WHY_NO_DEPTH`.
  - **Item 5.** `selection_refusal`'s docstring lists every check in the order the body makes
    them, including the deleted-cut refusal. Read the body and copy its order.

- [ ] **Step 5: Run the recipe.** The touched QGIS files are `test_plugin_surface_build.py`,
  `test_plugin_surfaces_membership.py` and `test_plugin_new_surface_dialog.py`.

- [ ] **Step 6: Commit and push.**
  `fix(surfaces): a cut pick with no distance has no depth; membership test assertions back; refusal order documented (#228)`

---

### Task 5: One time-base reader, and the cut-pick cursor (#228 items 2, 4). After F merges.

**Gate: before anything else.**
- Run `git fetch origin`.
- Check whether `origin/main` holds session F's merge (branch `nsgeo-profile-view`, PR "profile
  axes, zoom and time zero by eye"): `git log origin/main --merges --oneline | grep -i profile`.
- If it doesn't, **stop and report BLOCKED**. The coordinator will ask the user whether to wait
  or to hand these two items to session G.
- If it does, run `git merge origin/main`, resolve any conflicts, run the recipe, then push.

**Files:**
- Modify: `nsgeo_qgis/surface_plan.py`: a new `time_base_of_provenance`, and `cut_pick_base`
  (~line 253)
- Modify: `nsgeo_qgis/ui/profile_dock.py`:
  - remove `_time_base_of_provenance` and use the shared reader;
  - add `aim_at_cut_distance` and the pending target.
- Modify: `nsgeo_qgis/ui/surfaces_dock.py`: `_open_outlier` (~line 512) and a new signal
- Modify: `nsgeo_qgis/plugin.py`: connect the signal next to the Surfaces dock's other
  connections
- Test: `tests/pure/test_pure_surface_plan.py`, `tests/qgis/test_plugin_surfaces_dock.py`, and
  whichever Profile panel cut test F's code makes natural (likely `test_plugin_profile_cut.py`)

**Interfaces:**
- Produces:
  - `surface_plan.time_base_of_provenance(text: str | None) -> str`;
  - `SurfacesDock.cut_pick_requested = pyqtSignal(str, float)`, carrying `(cut key, distance_m)`;
  - `ProfileDock.aim_at_cut_distance(key: str, distance_m: float) -> None`.

- [ ] **Step 1: Write the failing pure test for item 2.**

```python
@pytest.mark.parametrize(
    "text, want",
    [
        ('{"time_base": "time_zero"}', "time_zero"),
        ('{"time_base": "radar"}', "radar"),
        ('{"time_base": ""}', "radar"),  # the case the two readers disagreed on
        ('{"time_base": 3}', "radar"),
        ("{}", "radar"),
        ("[]", "radar"),
        ("not json", "radar"),
        ("", "radar"),
        (None, "radar"),
    ],
)
def test_time_base_of_provenance(text, want):
    assert time_base_of_provenance(text) == want
```

  Also add a test that the Profile panel's reader is the shared one:
  `"_time_base_of_provenance" not in vars(profile_dock)`, and the panel's cut-pick filter gives
  the same answer as `cut_pick_base` for `stack_json=""`. Put that in the QGIS test file that
  already covers the panel's other-clock count.

- [ ] **Step 2: Write the failing QGIS tests for item 4.** Use the existing cut-outlier test in
  `test_plugin_surfaces_dock.py` (added in 9e2fac8) as the base.
  - **Clicking a cut pick's outlier:** once the cut's section has loaded (wait for it as F's
    cut tests do), the profile's cursor is on the column whose
    `section.columns.distance_m` is nearest the pick's `distance_m`.
  - **The section is already shown when the outlier is clicked:** the cursor moves at once.
  - **Another line is opened before the cut's section loads:** when the cut is later shown, the
    cursor is not moved by the old target.

- [ ] **Step 3: Run them and confirm they fail.** Expect an ImportError for the reader, and the
  cursor where it was for item 4.

- [ ] **Step 4: Implement item 2.**
  - **`time_base_of_provenance`:**
    - It parses the text as JSON.
    - It returns `"time_base"` when that is a non-empty string, else `TIME_BASE_RADAR`.
    - It catches `TypeError`, `ValueError`, `AttributeError` and `KeyError`.
  - **`cut_pick_base(pick)`:** returns `time_base_of_provenance(pick.stack_json)`.
  - **`profile_dock`:** calls the shared reader wherever it called its own.

- [ ] **Step 5: Implement item 4.**
  - **`_open_outlier`:** for a cut pick whose `distance_m` is not None, it calls
    `session.open_line(key)` as now, then emits `cut_pick_requested(key, distance_m)`.
  - **`plugin.py`:** connects the signal to `profile_dock.aim_at_cut_distance`.
  - **`aim_at_cut_distance`:**
    - if the cut `key`'s section is shown now, it moves the cursor at once;
    - otherwise it keeps `(key, distance_m)` and applies it the next time `_show_cut` shows
      that key's section, then drops it.
    - Showing any other key drops it too.
  - The column is the nearest of `section.columns.distance_m`. The cursor moves through the
    same call a click on the section makes. Find it in F's code.
  - The guide's "at that pick" (`docs/guide/getting-started.md`, Making a surface from picks,
    step 4) now holds for cut picks too, so leave it as it is.

- [ ] **Step 6: Run the recipe.** The touched QGIS files are `test_plugin_surfaces_dock.py`,
  `test_plugin_profile_cut.py`, `test_plugin_profile_dock.py` and `test_plugin_surface_build.py`.

- [ ] **Step 7: Commit and push.**
  `fix(profile): one time-base reader; a cut pick's outlier puts the cursor on it once its section loads (#228)`

---

## After the tasks (coordinator)

- A whole-branch review on opus.
- Check branch CI.
- Deploy to a QGIS profile of its own, `ns_geo_3d_follow_ups`.
- A walkthrough artifact covering:
  - Grid1 on a copy of the M16 walkthrough site: an untouched export keeps a surface fresh;
  - a build on `amp_abs`, then quit without Save site and reopen: still fresh;
  - with the 3D view open, move one line's file away: the log names it once;
  - clicking a cut pick's outlier moves the cursor to it.
- The PR body notes the one-time "resolution" stale on surfaces already built at a float-tail
  cell (see the spec).
- Merging asks the user first.
