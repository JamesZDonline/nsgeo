# M19a Plan B: Destagger, Change Setup and Export for Mag — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every code task is written test-first with superpowers:test-driven-development: the failing test is run and seen to fail before any production code is written.

**Goal:** Finish M19a. The author types a destagger and stretch for mag traverses in Edit lines, changes a mag file's setup after import, and exports the mag map as a GeoTIFF.

**Architecture:**
- **Edit lines.** `EditLinesDialog` learns a mag mode. Its rows are the grid's traverses, keeping Plan A's `LineEdit` and placement maths, and only Scale and Destagger can be edited. A new session method writes the result back into the `MagFile`'s per-traverse `scales` and `shifts`.
- **Setup form.** The import dialog's setup form and picture become a shared `MagSetupForm`, used by import and by a new Change setup dialog.
- **Export.** It reuses the slice export's one GeoTIFF writer and style writer, gaining a `centre` keyword, and places exported layers above the mag map (Plan A's parked finding).

**Tech Stack:** Python ≥ 3.9 and numpy (core); PyQt via `qgis.PyQt`; GDAL through the existing `slice_export.write_north_up`; pytest on two tiers.

**Spec:** `docs/superpowers/specs/2026-11-12-nsgeo-magnetometer-design.md`, approved 2026-11-13: §4 calls C4 and C20, decision D13 (the Mag panel's Change setup… and Export GeoTIFF…), §6.2 (Export), §6.4 (destagger as placement), §9 (docs). Builds on Plan A, `docs/superpowers/plans/2026-11-13-nsgeo-m19a-plan-a-mag-on-the-map.md`, as built on `nsgeo-m19-mag` at 32b477f. Plan A's ledger, `.superpowers/sdd/2026-11-13-nsgeo-m19a-plan-a-mag-on-the-map/progress.md` in that worktree, records every ruling made during its build. This plan's calls are Q1–Q12, cited as `(mag plan B, Q<n>)`.

## Plan calls (Claude's; check while reading)

- **Q1 — When this is built.**
  - Plan A's walkthrough comes first. Its results are folded into this plan before Task 1 is dispatched, and any Plan A fixes land on `nsgeo-m19-mag` first.
  - The walkthrough can change the setup form, the import dialog, and the Mag panel's defaults and colours. Those changes reach Tasks 2 and 3 here.
  - Plan B is built on `nsgeo-m19-mag`, so M19a merges as one.
  - Task 1 depends least on the walkthrough. If the author wants it early, it can be built on a stacked branch `nsgeo-m19-mag-b` in its own worktree, since the `ns_geo_mag` profile runs the Plan A worktree, then merged back.
- **Q2 — Edit lines decides mag itself.** It checks `session.grid(grid_id).instrument == "mag"`. The plugin's `open_edit_lines_dialog` and the Survey panel's `edit_lines_requested` stay as they are; the Survey panel only gains the menu entries.
- **Q3 — A mag row is a traverse.**
  - Its key is `f"{session.mag_key(mag)}#{row + 1}"` (`traverse_key`). It is parsed back only by `traverse_row(key) -> int`.
  - It is `LineEdit(key, seen=traverse.placement)`.
  - Traces = `mag.n_readings`, per metre = `mag.setup.readings_per_metre`, picks = 0.
  - The label is the placement's own `traverse {n}`.
- **Q4 — In mag mode only Scale and Destagger can be edited**, by typing in the cell or through the bulk Set buttons.
  - Hidden: the start row (spin, Set, Snap), the offset row, Flip, the Grid combo and Move, ↑/↓, **Fit to grid edges**, and **Measure**.
  - Measure on mag is M19b. Fit to grid edges is left out because a return traverse's start sits at the far end, so fitting would also move its start (C4 asks only for a typed stretch).
  - The Grid column shows the grid id as read-only text.
- **Q5 — A typed destagger keeps GPR's meaning.** `travel_shift` moves a traverse along its own walk, so one grid value moves outbound and return traverses opposite ways (spec §6.4).
  - The real-data check: on example1, a typed ±0.25 m (one sign or the other) removes most of the ±0.5 m lag between neighbours (Task 1). Which sign is reported, not asserted.
- **Q6 — `session.edit_traverses(grid_id, edits) -> EditOutcome`** sits beside `set_mag_file`. It skips an edit whose `seen` no longer matches the traverse with `CHANGED_ELSEWHERE`, and an edit for a file no longer on the grid with `REMOVED`, both as `line_edit` words them. It swaps the file once, through `set_mag_file`, only when a value changed. `EditOutcome.message()` is reused, so it still says "line(s)".
- **Q7 — The setup form is shared.** `MagSetupForm(QGroupBox)` in `ui/mag_setup_form.py` holds the setup widgets and `MagSetupPicture`, moved from `MagImportDialog` without behaviour change. The import dialog keeps `setup()` and `set_setup()` as thin delegates. Tests that touch its widgets move to `dialog.setup_form.<widget>`.
- **Q8 — Change setup… is per file, with an every-file option.**
  - It changes one file's setup and keeps each traverse's scale and shift (C20).
  - A checkbox applies the same setup to every mag file on the site, each keeping its own corrections, and makes it the setup the next import starts from. The usual reason to change the setup is a wrong start corner or axis, which is wrong for every grid of a morning.
  - Without the checkbox, the remembered import setup is untouched.
- **Q9 — Where Change setup… is reached:** the Mag panel's Source group, as a button beside File (D13), and the Survey panel's mag file row menu. Both call `Plugin.open_mag_setup_dialog(grid_id)`. The dialog is modal: a short, single decision.
- **Q10 — What Export GeoTIFF… writes.**
  - It writes what the Mag panel shows: the This grid or Whole site mosaic at the panel's cell. The mosaic comes from `MagEngine.mosaic(..., max_pixels=MAG_EXPORT_MAX_PIXELS, max_covered=MAG_EXPORT_MAX_PIXELS)` with `MAG_EXPORT_MAX_PIXELS = 100_000_000`. If the lattice still comes back coarser than the cell, the export is refused.
  - It is one float32 band, NaN nodata, in the mosaic's CRS, written through `slice_export.write_north_up`.
  - The style file uses the user's own colours when they are on, otherwise the panel's palette, centre and limit.
  - It is written on the GUI thread under the busy cursor: one band of at most a few million pixels.
- **Q11 — Exported layers go directly above the Mag (live preview) layer** when it is in the site group, otherwise at the bottom as before.
  - This covers GPR exports too, fixing Plan A's parked finding.
  - The placement is one helper, `insert_above(group, layer, anchor)` in `slice_layer.py`. `SliceLayer`'s own anchoring uses it as well, so the rule is written once.
- **Q12 — Replacing an export.**
  - If a project layer already reads the chosen file, Export asks once.
  - On yes, that layer is removed before the file is written, because Windows refuses to overwrite a file a layer holds open, and the new layer takes its place.
  - On no, nothing is written.

## Global Constraints

- **Core:** numpy only; Python 3.9 runtime rules; `from __future__ import annotations` in new files.
- **Plugin:**
  - Qt only through `qgis.PyQt`. `tests/pure/test_plugin_boundary.py` and `test_no_orphan_signals.py` stay green.
  - Every Qt slot guards its own body: `except Exception as exc:  # noqa: BLE001 -- a slot …`. It reports through the dialog's status line, the dock's `error` signal or `plugin.message`, and never raises.
  - `nsgeo_qgis/mag_engine.py` stays Qt-free.
- **GPR is unchanged.**
  - Edit lines on a GPR grid behaves exactly as before; its existing tests pass untouched.
  - A site without mag saves exactly as before.
  - The slice export's files and styles are byte-for-byte what they were, because `centre` defaults to 0.0.
- **Raw files are never written** (C18). Change setup… and Edit lines change only the survey file.
- **Never commit site data.** `tests/data/local/` is gitignored; never `git add -f`; no coordinates or pictures of real data.
- **Shared-worktree safety.** Reviewers never edit the worktree. Use `PYTHONDONTWRITEBYTECODE=1` for every run, and never a bare `git stash`.
- **Commits.** End each with a `Co-Authored-By:` line naming the model. Push each to the branch as it is made.

### Copy (exact)

- **Survey panel.**
  - The mag grid menu becomes `Edit grid…`, `Edit lines…` (enabled when the grid holds a file), `Import magnetometer file…`, a separator, then `Remove grid`.
  - The mag file row menu becomes `Edit lines…`, `Change setup…`, then `Remove file from site`.
- **Edit lines, mag mode.**
  - The title is `f"Edit lines · {grid_id} · magnetometer"`.
  - The Destagger tooltip adds this sentence after GPR's: `"On a magnetometer grid each traverse moves along the way it was walked, so outbound and return traverses move opposite ways."`
- **Mag panel.** The Source group gains a `Change setup…` button on the File row, disabled when no file is shown, and the dock gains `Export GeoTIFF…` below Display, disabled when nothing is drawn.
- **Change setup dialog.**
  - Window title `f"Change setup · {file name}"`. The form group is `Setup`.
  - The checkbox reads `Use this setup for every magnetometer file on the site`. The buttons are `Apply` and `Cancel`.
  - Live status: the file's `missing_summary` under the form's setup, then any `fit_problems`, one per line.
  - Prompt `File does not fit its grid`: `"{name} does not fit grid {id} with this setup:\n{problems}\nApply anyway? Nothing is cropped or stretched."`
  - Site gone or replaced: `"The site changed; nothing was changed."`
  - The plugin's message after Apply is `"{name}: setup changed."`, or `"Setup changed for {n} magnetometer files."` with the checkbox on.
- **Export.**
  - Save dialog title `Export the mag map`, filter `"GeoTIFF (*.tif)"`.
  - Default file: `mag-{grid_id}.tif` for This grid, `mag-site.tif` for Whole site, in the site folder.
  - The band description is `Magnetic gradient (nT)`.
  - Dataset metadata: `NSGEO_INSTRUMENT=mag`, `NSGEO_UNITS=nT`, `NSGEO_GRIDS` (grid ids joined with `,`), `NSGEO_CELL_M`, `NSGEO_INTERPOLATION`, `NSGEO_MAX_DISTANCE_M`, `NSGEO_SMOOTH_X_M`, `NSGEO_SMOOTH_Y_M`.
  - Prompt `Replace export`: `"{name} is shown in the project. Replace it and its layer?"`
  - Too big: `"The mag map is too large to export at {cell:g} m. Choose a coarser cell."`
  - Done: `"Exported {name}."` Failure: `"Could not export the mag map: {message}"`.
- **README.** The "Not built yet" line (README.md:68) becomes `"Not built yet: instruments other than GPR and the Bartington Grad601 magnetometer."`. The "Ready to use" list gains a short **Magnetometer grids** item in its style.

## Verification commands (exactly these, from the worktree root)

These are as in Plan A: the same virtualenvs, `.venv-tools`, and real data linked under `packages/nsgeo-core/tests/data/local/`. A real-data test that skips has validated nothing.

- **core + pure:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider`
- **qgis:** `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:cacheprovider -p no:xonsh`. It takes 20+ minutes, so implementers run the named files and the coordinator runs the full tier.
- **lint:** `.venv-tools/bin/ruff check . && .venv-tools/bin/ruff format --check .`
- **types:** the Plan A command, unchanged, including `mag_engine.py`.

## Review Focus

1. **The file is replaced or removed while Edit lines is open on its grid.** The edits are skipped with `REMOVED` or `CHANGED_ELSEWHERE`, nothing raises, and the outcome says so. Pinned by Task 1, `test_a_file_replaced_while_editing_skips_its_traverses`.
2. **Change setup… keeps the typed corrections** (C20). A traverse's scale and shift survive a corner or axis change. Pinned by Task 2, `test_changing_the_setup_keeps_each_traverses_corrections`.
3. **A setup that no longer fits.** For example a doubled spacing: Apply asks, and No changes nothing. Pinned by Task 2, `test_a_setup_that_does_not_fit_asks_and_no_changes_nothing`.
4. **Exporting over a file a layer already shows.** It asks; yes swaps the layer and writes; no writes nothing. Pinned by Task 3, `test_exporting_over_a_shown_file_asks_then_replaces_the_layer`.
5. **A GPR export on a site with mag.** It lands above the mag map, not under it. Pinned by Task 3, `test_an_export_lands_above_the_mag_layer`.

---

## Pre-flight (coordinator, before Task 1)

- [ ] Fold Plan A's walkthrough results into this plan (Q1), and land Plan A fixes first.
- [ ] Update the roadmap's M19a entry to "Plan B building", committing straight to main.
- [ ] Record the baselines (four commands) in a new ledger `.superpowers/sdd/2026-11-13-nsgeo-m19a-plan-b-mag-finish/`. Check that the `mag-data/` link and the other real-data links are still in place.

---

### Task 1: Destagger and stretch for mag traverses in Edit lines

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py`:
  - add `edit_traverses`;
  - add `traverse_key` and `traverse_row` as module functions beside it, or in `line_edit.py` if that keeps them Qt-free (preferred).
- Modify: `nsgeo_qgis/ui/edit_lines_dialog.py` (mag mode, Q2–Q4).
- Modify: `nsgeo_qgis/ui/survey_dock.py` (the menus per the Copy).
- Modify: `docs/guide/getting-started.md` (Step 10: typing a destagger and stretch for a mag grid; that Measure on mag is not built yet).
- Test:
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_edit_lines_mag.py` (new);
  - `tests/qgis/test_plugin_survey_dock.py`;
  - `packages/nsgeo-core/tests/test_mag_real_files.py`.

**Interfaces:**
- Consumes (Plan A):
  - `MagFile` (`scales`, `shifts`, `traverses(grid)`, `setup.readings_per_metre`, `n_readings`);
  - `SiteSession.mag_file_on`, `mag_key`, `set_mag_file`, `mag_changed`;
  - `LineEdit`, `EditOutcome`, `Skipped`, `REMOVED`, `CHANGED_ELSEWHERE`, `same_placement` (`line_edit.py`).
- Produces:

```python
# nsgeo_qgis/line_edit.py (Qt-free)
def traverse_key(mag_key: str, row: int) -> str: ...      # f"{mag_key}#{row + 1}"
def traverse_row(key: str) -> int: ...                    # inverse; ValueError for a key that is not a traverse key

# nsgeo_qgis/session.py
def edit_traverses(self, grid_id: str, edits: Sequence[LineEdit]) -> EditOutcome: ...
    # KeyError for an unknown grid; each edit's placed() scale and travel_shift go into the
    # file's scales/shifts at traverse_row(edit.key); one set_mag_file swap when anything
    # changed; Skipped(REMOVED) when the grid holds no file or a different one (key prefix
    # differs), Skipped(CHANGED_ELSEWHERE) when edit.seen differs from the traverse now
```

- [ ] **Step 1: Write the failing tests.**
  - `test_plugin_edit_lines_mag.py`, on `mag_site`, opening `EditLinesDialog(session, "M1")`:
    - `test_a_mag_grid_lists_its_traverses`:
      - 8 rows labelled `traverse 1` to `traverse 8`;
      - the title is `"Edit lines · M1 · magnetometer"`;
      - Traces 32 and Length `4.00` for each row (the dialog's `traces / per_metre`, 32 readings at 8 per metre);
      - the Grid column reads `M1` and is not editable.
    - `test_only_scale_and_destagger_can_be_edited_on_mag`:
      - the start, offset, Flip, Move, ↑/↓, Fit and Measure controls are hidden;
      - typing in Offset, Start or Dir changes nothing.
    - `test_a_typed_destagger_and_scale_reach_the_file`:
      - set Destagger 0.25 on rows 1–2 and type Scale 0.98 on row 3, then press OK;
      - `session.mag_file_on("M1").shifts == (0.25, 0.25, 0, 0, 0, 0, 0, 0)` and `.scales[2] == 0.98`;
      - `mag_changed` is emitted once and the site is dirty.
    - `test_ok_with_nothing_changed_writes_nothing`: the same file object stays on the grid, and the site is not dirty.
    - `test_a_file_replaced_while_editing_skips_its_traverses`:
      - replace M1's file through `set_mag_file`, then type and press OK;
      - the outcome has `skipped` with `CHANGED_ELSEWHERE` or `REMOVED`;
      - nothing raises and the new file is unchanged.
    - `test_gpr_edit_lines_is_unchanged`: G1's dialog still shows Measure, Fit and the Grid combo. Run the existing `test_plugin_edit_lines_dialog.py` unchanged as the full check.
  - `test_plugin_survey_dock.py`:
    - `test_a_mag_grid_and_its_file_offer_edit_lines`: the menus match the Copy, and choosing it emits `edit_lines_requested("M1", [])`.
    - Edit lines… is disabled on the empty M2.
  - `test_mag_real_files.py`:
    - `test_a_quarter_metre_destagger_lines_up_real_neighbours` (Q5).
    - For example1 under `MagSetup()` on a 30 × 30 m grid:
      - take every pair of neighbouring traverses' placed along positions;
      - interpolate both onto a common 0.0625 m axis (`np.interp`);
      - find the lag in ±1 m that maximises their correlation;
      - take the median |lag| over pairs.
    - Assertions:
      - with all shifts 0, the median |lag| is ≥ 0.375 m;
      - with all shifts set to +0.25 or to −0.25, the smaller of the two medians is ≤ 0.125 m.
    - Report which sign won in the task report. A failure is reported, never loosened.
- [ ] **Step 2: Run the new files and watch them fail.**
- [ ] **Step 3: Implement** `traverse_key`/`traverse_row`, then `edit_traverses`, then the dialog's mag mode, then the Survey menus, then the guide.
- [ ] **Step 4: Run** the new and touched QGIS files plus `test_plugin_edit_lines_dialog.py` unchanged, the core + pure tier, lint and types. All green; the real-data test ran.
- [ ] **Step 5: Commit and push.** `feat(mag): type a destagger and stretch for mag traverses in Edit lines (M19a)`.

---

### Task 2: Change setup…

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/mag_setup_form.py` (`MagSetupForm`, moved from `MagImportDialog`, Q7).
- Create: `nsgeo_qgis/ui/mag_setup_dialog.py` (`MagSetupDialog`).
- Modify:
  - `nsgeo_qgis/ui/mag_import_dialog.py` (use the form);
  - `nsgeo_qgis/session.py` (`change_mag_setup`);
  - `nsgeo_qgis/ui/mag_dock.py` (the Change setup… button, the `setup_requested(str)` signal);
  - `nsgeo_qgis/ui/survey_dock.py` (file row menu `Change setup…`, the `mag_setup_requested(str)` signal);
  - `nsgeo_qgis/plugin.py` (`open_mag_setup_dialog`, both signals);
  - `docs/guide/getting-started.md` (Step 10: changing a file's setup, and the every-file checkbox).
- Test:
  - `tests/qgis/test_plugin_mag_setup_dialog.py` (new);
  - `tests/qgis/test_plugin_mag_import_dialog.py` (moved widget paths only);
  - `tests/qgis/test_plugin_mag_dock.py`;
  - `tests/qgis/test_plugin_survey_dock.py`.

**Interfaces:**
- Consumes: `MagSetup`, `fit_problems`, `missing_summary`, `mark_missing`, `MagFile` (Plan A); `MagSetupPicture` (Plan A Task 5).
- Produces:

```python
# nsgeo_qgis/ui/mag_setup_form.py
class MagSetupForm(QGroupBox):
    changed = pyqtSignal()
    def __init__(self, title: str, parent: QWidget | None = None): ...
    def setup(self) -> MagSetup: ...                  # ValueError carries MagSetup's message
    def set_setup(self, setup: MagSetup) -> None: ... # emits nothing
    picture: MagSetupPicture

# nsgeo_qgis/session.py
def change_mag_setup(self, grid_id: str, setup: MagSetup, *, every_file: bool = False) -> list[str]: ...
    # the grid ids whose file changed; each file is dataclasses.replace(mag, setup=setup)
    # (scales and shifts kept); every_file also remember_mag_setup(setup); one mag_changed,
    # dirty, only when something changed; KeyError for a grid with no file

# nsgeo_qgis/ui/mag_setup_dialog.py
class MagSetupDialog(QDialog):
    def __init__(self, session: SiteSession, grid_id: str, parent: QWidget | None = None): ...
    changed_grids: list[str]   # filled on a successful Apply

# nsgeo_qgis/plugin.py
def open_mag_setup_dialog(self, grid_id: str) -> None: ...   # guarded; posts the Copy's message
```

- [ ] **Step 1: Write the failing tests.**
  - `test_plugin_mag_setup_dialog.py`, on `mag_site`:
    - `test_the_dialog_opens_on_the_files_setup`.
    - `test_changing_the_corner_moves_the_traverses`. Switch `far_x`: after Apply, traverse 1's offset is `4 - 0.25`.
    - `test_changing_the_setup_keeps_each_traverses_corrections` (Review Focus 2). Give M1 shifts and scales first; after Apply they are equal to before.
    - `test_a_setup_that_does_not_fit_asks_and_no_changes_nothing` (Review Focus 3). Use spacing 1.0 with `answer_modal` No: the file and site are unchanged. Yes applies it.
    - `test_every_file_changes_each_and_is_remembered`. Give M2 a file too and tick the checkbox: both setups change, each keeps its own corrections, and `session.mag_setup()` equals the new setup. Without the checkbox, `mag_setup()` is unchanged.
    - `test_apply_after_the_site_was_replaced_changes_nothing`.
    - `test_the_status_shows_missing_and_fit_live`.
  - `test_plugin_mag_dock.py`: `test_change_setup_is_offered_for_the_shown_file`. The button is enabled with M1 shown, disabled with M2 shown, and emits `setup_requested("M1")`.
  - `test_plugin_survey_dock.py`: the file row menu matches the Copy, and `Change setup…` emits `mag_setup_requested("M1")`.
  - Plugin level: `test_change_setup_from_the_mag_panel_opens_the_dialog`, using `answer_modal`/`drive_dialog` as the existing plugin tests do.
- [ ] **Step 2: Run them and watch them fail.**
- [ ] **Step 3: Implement.** Move the form first and keep the import dialog's tests green with only the widget paths changed. Then add the session method, the dialog, the signals and wiring, and the guide.
- [ ] **Step 4: Run** the touched QGIS files, the pure tier (orphan signals), lint and types. All green.
- [ ] **Step 5: Commit and push.** `feat(mag): change a mag file's setup after import, one file or every file (M19a)`.

---

### Task 3: Export GeoTIFF… and exports above the mag map

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/mag_export.py`. It holds `write_mag_geotiff`, which calls `slice_export.write_north_up`.
- Modify:
  - `nsgeo_qgis/export_style.py`: `write_style(..., centre: float = 0.0)` passed to `apply_renderer`.
  - `nsgeo_qgis/slice_layer.py`: `insert_above(group, layer, anchor)`, used by `SliceLayer`'s anchoring (Q11).
  - `nsgeo_qgis/mag_engine.py`: `MAG_EXPORT_MAX_PIXELS`, and keyword `max_pixels`/`max_covered` on `mosaic`, defaulting to today's values.
  - `nsgeo_qgis/ui/mag_dock.py`: the `Export GeoTIFF…` button, the `export_requested` signal, and `export_map() -> MagMosaic | None`.
  - `nsgeo_qgis/plugin.py`:
    - `_export_mag`;
    - `_add_export_layer(..., centre: float = 0.0)`;
    - `_add_exported_layer` uses `insert_above(group, layer, self.mag_layer.layer)` (Q11).
  - `README.md`: the Copy's two edits.
  - `docs/guide/getting-started.md` (Step 10: exporting the mag map; drop "not built yet" for export and destagger).
- Test:
  - `tests/qgis/test_plugin_mag_export.py` (new);
  - `tests/qgis/test_plugin_export_style.py`;
  - `tests/qgis/test_plugin_slice_layer.py`;
  - `tests/pure/test_pure_mag_engine.py`;
  - `tests/pure/test_release_docs.py` only if it pins the README line.

**Interfaces:**
- Consumes: `MagEngine.mosaic`, `MagMosaic` (`array`, `lattice`, `grids`, `centre()`, `limit()`), `MagSettings`, `MAG_STRETCH_PERCENTILE` (Plan A); `slice_export.write_north_up`, `ExportBand`; `Plugin._add_export_layer`, `_add_exported_layer`; `SliceLayer.above`.
- Produces:

```python
# nsgeo_qgis/mag_engine.py
MAG_EXPORT_MAX_PIXELS: int = 100_000_000
def mosaic(self, items, settings, *, max_pixels: int = SITE_MAX_PIXELS,
           max_covered: int = SITE_MAX_COVERED_PIXELS) -> MagMosaic | None: ...

# nsgeo_qgis/mag_export.py
def write_mag_geotiff(path: Path, mosaic: MagMosaic, settings: MagSettings) -> None: ...
    # one float32 band "Magnetic gradient (nT)", NaN nodata, the Copy's metadata;
    # ValueError("too large") is the caller's job (export_map refuses first)

# nsgeo_qgis/slice_layer.py
def insert_above(group: Any, layer: Any, anchor: Any | None) -> None: ...
    # directly above anchor's node when it is in group, else at the bottom

# nsgeo_qgis/ui/mag_dock.py
export_requested = pyqtSignal()
def export_map(self) -> MagMosaic | None: ...   # the shown scope at the panel's cell with the
                                                # export limits; None when nothing is shown;
                                                # ValueError with the Copy's "too large" text
```

- [ ] **Step 1: Write the failing tests.**
  - `test_plugin_mag_export.py`, on `mag_site` through the plugin. Stub the save dialog the way existing export tests do; read bands with `plugin_testing.read_bands`.
    - `test_exporting_this_grid_writes_one_band_in_nt`:
      - one float32 band described `Magnetic gradient (nT)`;
      - the values equal `dock.export_map().array` with NaN preserved;
      - the geotransform equals the lattice's;
      - the metadata has `NSGEO_INSTRUMENT=mag` and `NSGEO_GRIDS=M1`;
      - a layer named after the file is added with a `.qml` beside it;
      - the message is `"Exported mag-M1.tif."`.
    - `test_the_style_follows_the_panel` checks two cases:
      - with nsgeo colours, the renderer's min and max are centre ± limit;
      - with own colours, the user's style is written.
    - `test_exporting_over_a_shown_file_asks_then_replaces_the_layer` (Review Focus 4): with `answer_modal`, No leaves the old file's bytes and layer; Yes leaves exactly one layer reading the path, holding the new values.
    - `test_an_export_lands_above_the_mag_layer` (Review Focus 5): a GPR slice export (the existing `_add_export_layer` path) and a mag export both sit above `Mag (live preview)` in the site group.
    - `test_a_map_too_large_is_refused`: monkeypatch `MAG_EXPORT_MAX_PIXELS` small; the message is exact and nothing is written.
    - `test_export_is_disabled_with_nothing_drawn`.
  - `test_plugin_export_style.py`: `test_a_centre_shifts_the_exported_ramp`. Without `centre`, the existing style tests pass unchanged.
  - `test_plugin_slice_layer.py`: `test_insert_above_places_directly_above_or_at_the_bottom`. The existing anchoring tests pass unchanged.
  - `test_pure_mag_engine.py`: `test_mosaic_takes_export_limits`.
- [ ] **Step 2: Run them and watch them fail.**
- [ ] **Step 3: Implement.** Do the engine limits and `insert_above` first, then `write_style` centre and `write_mag_geotiff`, then the dock and plugin wiring, then README and the guide.
- [ ] **Step 4: Run** the touched QGIS files plus `test_plugin_slice_export.py` and `test_plugin_site_export.py` (GPR exports unchanged), the core + pure tier, lint and types. All green.
- [ ] **Step 5: Commit and push.** `feat(mag): export the mag map as a GeoTIFF; exports sit above the mag map (M19a)`.

---

### Task 4: Review, deploy and walkthrough (coordinator and author; a human gate)

- [ ] Run the full QGIS tier, then a whole-branch review (opus) over Plan A and Plan B together, then a fix wave if needed.
- [ ] Deploy: refresh the `ns_geo_mag` profile, or make `ns_geo_mag_b` if the stacked branch was used (Q1).
- [ ] Publish a walkthrough Artifact with a `db` capability for results. It covers:
  - a typed destagger on example1 to example6, judged against TerraSurveyor's destaggered plots;
  - which sign the real-data test found (Q5);
  - a typed stretch;
  - Change setup… on one file, then on every file;
  - an export of This grid and of Whole site, opened in QGIS and in other GIS software;
  - a GPR export on a mag site, landing above the mag map;
  - replacing an export;
  - the README and guide wording.
- [ ] Stop and wait for the author's results. Update the README roadmap and the memory. Merging M19a asks first.
- [ ] After the merge: retire both plans' ledgers into committed decision records before removing the worktree. File the Plan A follow-ups recorded in its ledger:
  - the GPR boundary-split hazard at fine cells on rotated grids;
  - the order-dependent `test_the_feature_list_follows_the_layer_list_not_its_signal`;
  - moving the Mag panel's work off the GUI thread, if the walkthrough asks for it.
