# M19a Plan A: Magnetometer Grids on the Map — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every code task is written test-first with superpowers:test-driven-development: the failing test is run and seen to fail before any production code is written.

**Goal:** Import Bartington Grad601 grid files onto magnetometer grids, and draw them from a new Mag panel as one live layer on the QGIS map, in the site's coordinates beside the GPR.

**Architecture:**
- **New core package `nsgeo.mag`** (numpy only). It:
  - reads Grad601 files and marks missing data;
  - turns each row into a traverse placed by `GridPlacement`, whose maths it shares;
  - holds `MagFile`;
  - makes a map for each grid: bin, then `plan_fill`, then `finish_slice`;
  - composes the maps into one mosaic: `SiteLattice`, then `compose_footprints`.
- **Grids and the survey file.** `Grid` gains an instrument. `Site` holds the mag files, and the survey file saves as schema 3 once the site has mag.
- **Plugin.** It gains:
  - a mag API in the session;
  - GPR panels filtered to GPR grids;
  - mag rows in the Survey panel;
  - an Import mag dialog;
  - a Qt-free `mag_engine.py`;
  - a `MagDock`;
  - a second `SliceLayer`, named `Mag (live preview)`.

**Tech Stack:** Python ≥ 3.9 and numpy (core); PyQt via `qgis.PyQt` (plugin); pytest on two tiers (core+pure, QGIS).

**Spec:** `docs/superpowers/specs/2026-11-12-nsgeo-magnetometer-design.md` (approved 2026-11-13). Read §2, §3, §4, §6.1, §6.2 and §10 first. The spec's author decisions are cited as D1–D14 and its calls as C1–C21. This plan's own calls are P1–P16, cited as `(mag plan A, P<n>)`.

## Plan calls (Claude's; check while reading)

- **P1 — M19a is two plans.** The spec sizes M19a as L, and plans here are 3–6 tasks.
  - **Plan A (this plan)** gets mag from the file onto the map: the core package, the survey file, grids apart by instrument, the Survey panel, import, and the Mag panel with its layer.
  - **Plan B** adds:
    - **Export GeoTIFF…** (§6.2);
    - Edit lines on a mag grid, with typed destagger and stretch (C4, §6.4's first bullet);
    - **Change setup…** (C20);
    - the README's *Not built yet* line (§9).

  Plan B is written once Plan A is built, against Plan A's real interfaces. Plan A gets its own walkthrough.
- **P2 — The placement maths is shared** (C2). `GridPlacement` gains `along(n, per_metre)` and `local(n, per_metre)`, and `distance_along` and `trace_coords` call them. Every traverse is a `GridPlacement`, so no stagger or stretch maths is written twice.
- **P3 — A reading sits in the middle of its interval.** Reading `j` of a traverse is `(j + 0.5) / readings_per_metre` from the edge where the traverse starts. Measured from the edge itself, the two walking directions would sit one reading interval (0.125 m) apart before any destagger, which would look like stagger.
- **P4 — Readings are kept in the order walked.** When the download has flipped a return traverse (`flipped`), its stored row is reversed (`Traverse.reversed`). Then `start_along + direction * (scale * j / rpm + travel_shift)` means for mag exactly what it means for GPR, so Plan B's destagger works unchanged.
- **P5 — The setup is grid-local.** Its fields and defaults, exactly, are the author's setup (D3):
  - `axis="y"`, the grid axis the traverses run along;
  - `far_x=False` and `far_y=False`: the first traverse starts at `x = size_x` when `far_x`, otherwise at `x = 0`, and likewise for y;
  - `spacing_m=0.5` and `first_offset_m=0.25`;
  - `readings_per_metre=8.0`;
  - `sensors=2` and `sensor_separation_m=1.0`;
  - `zigzag=True` and `flipped=True`;
  - `missing_run=4` (C6).

  The defaults for axis and corner are arbitrary. The setup is remembered after the first import (C5).
- **P6 — The walking pattern comes from the setup.** `k = sensor_separation_m / spacing_m` must be a whole number (one sensor: `k = 1`). One pass logs `sensors` rows that are `k` apart. Zigzag alternates direction from pass to pass. For the author's setup that gives rows `i` and `i + 2` for one pass, as §3 measured:

  ```python
  block = setup.sensors * k
  pass_index = (row // block) * k + (row % block) % k
  return 1 if (not setup.zigzag or pass_index % 2 == 0) else -1
  ```
- **P7 — `MagFile` lives in `nsgeo.mag`, not `nsgeo.model`,** so `nsgeo.mag` never imports `nsgeo.model`. It is `eq=False`, as `Line` is (#89).
  - Per-traverse `scales` and `shifts` are in the model and the survey file from now on, so the file's shape is settled once (C20). Only Plan B edits them.
- **P8 — The survey file.**
  - A site with any mag grid or mag file saves as `MAG_SCHEMA_VERSION = 3`. Otherwise it saves as before, and a site without mag gains no new keys (C17).
  - `mag_files` entries look like `{"path", "grid_id", "setup", "corrections"}`. `corrections` is keyed by the 0-based row as a string, and holds only rows with a non-default `scale` or `travel_shift`.
  - `mag_setup` (C5) and `mag_view` (C21) are remembered choices. They are read tolerantly: a damaged one reads as unset.
- **P9 — One colours scope, `"mag"`,** serves both the This grid and Whole site buttons. It is the same field in nT either way, unlike GPR's per-scope stretch. It goes through #180's `slice_colours`.
- **P10 — Maps are drawn on the GUI thread, under the busy cursor,** and cached per grid.
  - Measured on a 30 m grid at 0.125 m: kriging takes 0.15 s per grid and minimum curvature 0.7 s.
  - So Whole site with minimum curvature on six grids takes about 4 s. That is accepted for Plan A.
  - The walkthrough judges it. If it is too slow, a follow-up moves the solve onto the `Refiner` thread.
- **P11 — Whole site is every mag grid that holds a file,** with no checklist (D13), mosaicked in the CRS of the first such grid in site order. A grid in another CRS is left out, and the panel names it.
- **P12 — The default look.**
  - The palette is `grey_black_high`, so positive readings show black, a common convention for mag plots. The walkthrough checks it against what the author is used to.
  - The range is centred on the median of the readings shown (§6.2).
  - Its half-width is the 95th percentile of `|value − centre|` (`MAG_STRETCH_PERCENTILE = 95.0`). Measured on the six files, that is ±3.7 to ±7.8 nT.
  - #180's own colours replace all of this when the author chooses them.
- **P13 — A grid's instrument is fixed once the grid exists.**
  - In the grid dialog, a new mag grid starts at 30 × 30 m with a 0.5 m spacing (D3).
  - The Velocity row is hidden for a mag grid.
  - The session refuses to change an instrument.
- **P14 — When the Mag panel shows and draws.**
  - It is hidden at start-up.
  - An import shows it, on the grid just imported.
  - It draws only while it is visible. Closing it leaves the layer as last drawn, and closing the site clears the layer.
- **P15 — Finish defaults.**
  - Cell 0.125 m (`DEFAULT_CELL_M`).
  - Kriging, with a max distance of 0.75 × the file's traverse spacing and no smoothing.
  - The spacing is `setup.spacing_m`, not `grid.default_spacing`. `SliceFinish.in_metres(setup.spacing_m)` converts.
- **P16 — The import dialog.**
  - It takes several files at once.
  - Each row's grid defaults to the first mag grid in site order that has no file and is not chosen by another row.
  - Its layout is shown to the author as a lavish mockup before Task 5 (Checkpoint C1).

## Global Constraints

- **Core:** numpy only (no scipy). The runtime is Python 3.9, so: no `zip(strict=)`, no `match`, and no PEP 604 unions outside annotations. `from __future__ import annotations` heads every new file.
- **Plugin:**
  - `nsgeo_qgis/mag_engine.py` imports no Qt and no `qgis`. Add it to the mypy list in `.github/workflows/ci.yml` and to the types command below.
  - Qt is used only through `qgis.PyQt`. `tests/pure/test_plugin_boundary.py` and `test_no_orphan_signals.py` stay green.
  - Every Qt slot guards its own body: `except Exception as exc:  # noqa: BLE001 -- a slot …`. It reports through the dock's `error` signal or `plugin.message`, never by raising (the plugin module docstring's rule).
- **GPR is unchanged.**
  - A site without mag saves exactly as before: schema 1 or 2, with no `instrument` and no `mag_*` keys.
  - The GPR panels never list a mag grid, and the Mag panel never lists a GPR grid (spec §8 anti-goal).
- **Raw files are never written** (C18).
- **Never commit site data.**
  - `tests/data/local/` is gitignored, and nothing from it is ever added with `git add -f`.
  - The real `.dat` files reach the worktree only by symlink.
  - No coordinates, screenshots or mockups made from real data are committed.
- **Shared-worktree safety:** reviewers and any mutation probes work on a scratch copy, never on this worktree. Set `PYTHONDONTWRITEBYTECODE=1` for every run.
- **Commits:** end each message with a `Co-Authored-By:` line naming the model that wrote it. Push each commit to `origin nsgeo-m19-mag` as it is made. Touch no other worktree.

### Copy (exact)

**Core.** `MagFileError` messages, from `read_grad601`:
- `"{name} holds no readings"`
- `"{name}: row {i} has {n} readings but row 1 has {m}; this does not look like a Grad601 grid file"`
- `"{name}: row {i} holds {token!r}, which is not a number"`

Here `name` is the file name and rows are counted from 1.

**Core.** `missing_summary` lists at most 6 traverses, then `and {k} more`:
- `"No readings are missing data."`
- `"{n} readings are missing data, on traverse {a}."`
- `"{n} readings are missing data, on traverses {a} and {b}."`
- `"{n} readings are missing data, on traverses 1, 2, 3, 4, 5, 6 and {k} more."`

When `n == 1`, `readings are` becomes `reading is`.

**Core.** `fit_problems`. `{A}` and `{B}` are the axes in capitals, the traverse axis and the other one:
- `"{n} readings at {rpm:g} per metre make {length:g} m, but the grid is {size:g} m along {A}."`, when `|n / rpm − size| > 0.5 / rpm`.
- `"{rows} traverses {spacing:g} m apart make {width:g} m, but the grid is {size:g} m across {B}."`, when `|rows × spacing − size| > spacing / 2`.

**Core.** `MagSetup` validation (`ValueError`):
- `"the sensor separation ({sep:g} m) must be a whole number of traverse spacings ({spacing:g} m)"`
- the other fields: `"{field} must be …"`, worded as `GridPlacement.__post_init__` words its checks.

**Core.** `Site.validate` (`ValueError`):
- `"mag file {name} references unknown grid {id!r}"`
- `"mag file {name} is on grid {id!r}, which is a GPR grid"`
- `"grid {id!r} holds {n} mag files; a mag grid holds one"`
- `"line {name} is on grid {id!r}, which is a magnetometer grid"`
- `"cut {name!r} is on grid {id!r}, which is a magnetometer grid"`

**Plugin, toolbar.** `Import mag…`, placed after `Import DZT…`, with the tip `"Imports Bartington Grad601 grid files onto magnetometer grids."` It is greyed out until a site is open.

**Plugin, grid dialog.** The row is `Instrument` and its items are `GPR` and `Magnetometer`.

**Plugin, Survey panel.**
- A mag grid row is `"{id} · {size_x:g} × {size_y:g} m · magnetometer"`, plus `" · empty"` when it has no file.
- A file row is `"{file name} · {rows} traverses × {readings} readings"`, plus `" · {n} missing"` when `n > 0`.
- The mag grid menu is `Edit grid…`, `Import magnetometer file…`, a separator, then `Remove grid`. The file row menu is `Remove file from site`.
- Removing a mag grid that holds a file asks `"Remove grid {id} and its magnetometer file {name}?"`.

**Plugin, import dialog.**
- The title is `Import magnetometer files`.
- The buttons are `Add files…`, `New mag grid…`, `Import` and `Cancel`.
- The file filter is `"Grad601 grid (*.dat *.DAT)"`.
- The table columns are `File`, `Grid`, `Size` (`"{rows} × {readings}"`), `Missing` (the count), and `Fits` (`yes`, or the first problem, with all of them in the tooltip).
- The setup group is `Setup (remembered for this site)`. Its rows are:
  - `Traverses run along` (`X`, `Y`);
  - `First traverse starts` (`At the origin`, `At the far end of X`, `At the far end of Y`, `At the far corner`);
  - `Traverse spacing (m)`;
  - `First traverse offset (m)`;
  - `Readings per metre`;
  - `Sensors`;
  - `Sensor separation (m)`;
  - `Walked` (`Zigzag`, `Parallel`);
  - `Return traverses already flipped by the download`, a checkbox that is disabled when the pattern is Parallel;
  - `Missing data: runs of {spin} or more zeros`.
- Status lines and prompts:
  - Status: `"Choose a mag grid for {name}."`
  - Status: `"{a} and {b} are both on grid {id}; a mag grid holds one file."`
  - Status: `"Could not read {name}: {message}"`. The row is not added.
  - Status: `"The site changed; nothing was imported."`
  - Prompt `Files do not fit their grids`: `"{n} file(s) do not fit their grids:\n{name}: {problem}\n…\nImport anyway? Nothing is cropped or stretched."`
  - Prompt `Replace files`: `"Replace the files already on these grids?\n{id}: {old} → {new}\n…"`
- After an import, the plugin shows one message per file: `"{name}: {missing_summary}"`.

**Plugin, Mag panel.**
- The title is `nsgeo Mag` and the object name `nsgeoMagDock`.
- The buttons are `This grid` and `Whole site`.
- The groups are `Source` (rows `Grid`, `File` and `Missing`), `Resolution` (row `Cell (m)`), `Interpolation` (a `FinishPanel`) and `Display`. Display's rows are `Colours` (`nsgeo colours` / `my own colours`, plus `Symbology…`) and `Palette`.
- Status lines:
  - `"Import a magnetometer file to see it here."`
  - `"Grid {id} has no magnetometer file yet."`
  - `"Left out of the whole site, being in another CRS: {ids}."`
  - `"Could not draw the mag map: {message}"`
- The layer is `Mag (live preview)` (`MAG_LAYER_NAME` in `slice_layer.py`). Its subtitle is `"{grid id} · {file name}"` for This grid, and `"{n} mag grids"` for Whole site.

## Verification commands (exactly these, from the worktree root)

The worktree uses the main checkout's virtualenvs, with the worktree's core on `PYTHONPATH`. A local `.venv-tools` (git-excluded) holds the CI-pinned ruff 0.17.1 and mypy 2.4.0. The real mag files are linked as `packages/nsgeo-core/tests/data/local/mag-data/`. A real-data test that skips has validated nothing, so the skip count must not rise.

- **core + pure:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider`
- **qgis:** `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:cacheprovider -p no:xonsh`. This takes 10+ minutes. Run single files while iterating; the coordinator runs the full tier.
- **lint:** `.venv-tools/bin/ruff check . && .venv-tools/bin/ruff format --check .`
- **types:** `.venv-tools/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py packages/nsgeo-qgis/nsgeo_qgis/line_edit.py packages/nsgeo-qgis/nsgeo_qgis/export_pipeline.py packages/nsgeo-qgis/nsgeo_qgis/destagger_job.py packages/nsgeo-qgis/nsgeo_qgis/mag_engine.py`. This list must match `ci.yml`.

## Review Focus

These are the inputs a person will meet that the spec implies but does not spell out. Each is pinned by a test in its owning task.

1. **A damaged download:** rows of different lengths, a stray word, or an empty file. The file is named with its row and nothing is added. Pinned by Task 1, `test_a_ragged_file_is_refused_with_its_row`, and Task 5, `test_an_unreadable_file_is_named_and_not_added`.
2. **A mag grid moved, rotated or resized after import.** The map follows the grid: traverses are placed from the grid at draw time, and the layer redraws. Pinned by Task 6, `test_editing_a_mag_grid_moves_its_map`.
3. **A mag grid laid out in advance with no file yet,** shown with This grid, or a site with no mag at all. The panel says why and draws nothing, with no error. Pinned by Task 6, `test_an_empty_mag_grid_draws_nothing_and_says_why`.
4. **The site closed or replaced while the import dialog is open.** Import adds nothing and says so. Pinned by Task 5, `test_import_after_the_site_was_replaced_adds_nothing`.
5. **Removing a mag grid that holds a file.** The confirmation names the file, both go, and the save still validates. Pinned by Task 4, `test_removing_a_mag_grid_takes_its_file_after_asking`.

---

## Pre-flight (coordinator, before Task 1)

- [ ] Commit the roadmap's *In progress* entry straight to main from a throwaway worktree: "**M19a, mag on the map** — Plan A building." Push it. Keep site names out.
- [ ] Create `.venv-tools`: `../../.venv/bin/python -m venv .venv-tools && .venv-tools/bin/pip install ruff==0.17.1 mypy==2.4.0 numpy`.
- [ ] Link the real files: `mkdir -p packages/nsgeo-core/tests/data/local && ln -s /home/jameszd/Documents/Github/archaeo_geophysics/packages/nsgeo-core/tests/data/local/mag-data packages/nsgeo-core/tests/data/local/mag-data`. Then check that `git status --short` shows nothing new.
- [ ] Run the four verification commands and record the pass and skip counts in the ledger (`.superpowers/sdd/`) as baselines.

---

### Task 1: Grad601 files, the setup and traverses (nsgeo-core)

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/mag/__init__.py`, `grad601.py`, `setup.py`, `traverses.py`
- Modify: `packages/nsgeo-core/src/nsgeo/geometry/placement.py` (`GridPlacement.along`, `.local`; `distance_along` and `trace_coords` call them)
- Create: `packages/nsgeo-core/tests/mag_data.py`, `test_mag_grad601.py`, `test_mag_setup.py`, `test_mag_traverses.py`, `test_mag_real_files.py`
- Modify:
  - `packages/nsgeo-core/tests/test_placement.py`;
  - `tests/real_data.py`: add `MAG_FILES`, the `.dat` files directly in `DATA / "mag-data"`, sorted, or `[]`;
  - `tests/data/local/README.md`: the layout gains `mag-data/`;
  - `tests/test_public_api.py`: `EXPECTED_PUBLIC` gains `"mag"`;
  - `packages/nsgeo-core/README.md`: a short `nsgeo.mag` section naming each public name in backticks.

**Interfaces (produced; later tasks rely on these exactly):**

```python
# nsgeo/geometry/placement.py — GridPlacement gains
def along(self, n: int, per_metre: float) -> np.ndarray: ...   # (n,) start_along + direction*(scale*arange(n)/per_metre + travel_shift)
def local(self, n: int, per_metre: float) -> np.ndarray: ...   # (n, 2) grid-local metres; offset on the other axis

# nsgeo/mag/grad601.py
MISSING_RUN: int = 4
class MagFileError(ValueError): ...
def read_grad601(path: Path) -> np.ndarray: ...       # float64 (n_rows, n_readings) as written; zeros kept; values split on whitespace, LF or CRLF
def mark_missing(raw: np.ndarray, min_run: int = MISSING_RUN) -> np.ndarray: ...  # float64 copy; NaN for each run of >= min_run consecutive exact 0.0 along a row
def missing_summary(readings: np.ndarray) -> str: ... # traverses numbered from 1

# nsgeo/mag/setup.py
@dataclass(frozen=True)
class MagSetup:            # fields and defaults exactly as P5
    def passes_apart(self) -> int: ...                # k (P6); 1 for one sensor
    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_dict(cls, doc: Mapping[str, Any]) -> MagSetup: ...  # every key optional (default when absent); ValueError/TypeError for a bad value
def fit_problems(setup: MagSetup, n_rows: int, n_readings: int, grid: Grid) -> list[str]: ...

# nsgeo/mag/traverses.py
@dataclass(frozen=True)
class Traverse:
    row: int                    # 0-based row in the file
    placement: GridPlacement    # label f"traverse {row + 1}"
    reversed: bool              # readings in walked order are the stored row reversed (P4)
    def walked(self, stored_row: np.ndarray) -> np.ndarray: ...
def walked_direction(setup: MagSetup, row: int) -> int: ...   # +1 the first traverse's way, -1 the other (P6)
def traverses(setup: MagSetup, grid: Grid, n_rows: int, n_readings: int,
              scales: Sequence[float] | None = None, shifts: Sequence[float] | None = None
              ) -> tuple[Traverse, ...]: ...
```

**How a traverse is placed** (P3, P4, P5). Take `size_along` and `size_across` from the grid by `setup.axis`, and `far_along` and `far_across` from `far_x`/`far_y`. Then:
- `sign = -1 if far_along else 1`, and `edge = size_along if far_along else 0`. The same pair for across gives `sign_x` and `edge_x`.
- `offset = edge_x + sign_x * (first_offset_m + row * spacing_m)`.
- With `d = walked_direction(setup, row)`:
  - `direction = sign * d`;
  - `reversed = d < 0 and setup.flipped`;
  - `start_along = edge + sign * (0.5 if d > 0 else n_readings - 0.5) / readings_per_metre`.

- [ ] **Step 1: Write the failing tests.**
  - `tests/mag_data.py` is a helper. `write_grad601(path: Path, values: np.ndarray) -> Path` writes each row tab-separated with 2 decimals, and CRLF line ends.
  - `test_placement.py`:
    - `test_along_and_local_are_the_placement_maths_without_a_header`:

      ```python
      p = GridPlacement("G", "y", 1.5, start_along=2.0, direction=-1, scale=0.9, travel_shift=0.1)
      np.testing.assert_allclose(p.along(5, 10.0), 2.0 - (0.9 * np.arange(5) / 10.0 + 0.1))
      np.testing.assert_allclose(p.local(5, 10.0), np.column_stack([np.full(5, 1.5), p.along(5, 10.0)]))
      # and p.distance_along(5, header) equals p.along(5, header.traces_per_metre) for a 10-per-metre header
      ```
  - `test_mag_grad601.py`:
    - `test_reads_tabs_and_crlf_as_rows_of_readings`: `[[1.5, -2.25], [0.0, 99.0]]` round-trips as float64 of shape (2, 2).
    - `test_a_ragged_file_is_refused_with_its_row`: `b"1.00\t2.00\r\n3.00\r\n"` raises `MagFileError` matching `r"r\.dat: row 2 has 1 readings but row 1 has 2"`.
    - `test_a_non_number_is_refused_with_its_row`: `"1.00\tx\r\n"` matches `r"row 1 holds 'x', which is not a number"`.
    - `test_an_empty_file_is_refused`.
    - `test_runs_of_four_zeros_are_missing_and_shorter_runs_are_readings`:

      ```python
      raw = np.array([[1, 0, 0, 2, 0, 0, 0, 0, 3, 0, 0, 0]], float)
      np.testing.assert_array_equal(mark_missing(raw), [[1, 0, 0, 2, nan, nan, nan, nan, 3, 0, 0, 0]])
      assert np.isnan(mark_missing(raw, min_run=3)[0, 9:]).all()
      ```
    - `test_missing_summary_names_the_traverses`:
      - two runs on rows 1 and 4 give `"10 readings are missing data, on traverses 2 and 5."`;
      - no NaN gives `"No readings are missing data."`;
      - one NaN on each of 9 rows gives `"9 readings are missing data, on traverses 1, 2, 3, 4, 5, 6 and 3 more."`.
  - `test_mag_setup.py`:
    - `test_the_default_setup_is_the_authors`: every P5 default.
    - `test_a_sensor_separation_off_the_traverse_spacing_is_refused`: `MagSetup(sensor_separation_m=0.7)` matches `"whole number of traverse spacings"`.
    - `test_setup_round_trips_through_a_dict`, with `MagSetup.from_dict({}) == MagSetup()`.
    - `test_fit_problems_say_what_does_not_fit`:
      - a 30 × 30 grid gives `[]` for `(60, 240)`;
      - a grid 40 m along Y gives `["240 readings at 8 per metre make 30 m, but the grid is 40 m along Y."]`;
      - a grid 20 m across gives `["60 traverses 0.5 m apart make 30 m, but the grid is 20 m across X."]`.
  - `test_mag_traverses.py`. `GRID = Grid("M", (0.0, 0.0), 0.0, 2.0, 4.0, "EPSG:32616", 0.5)`; `S = MagSetup(readings_per_metre=4.0)`. The helper `stored_along(t, n, rpm)` is `t.placement.along(n, rpm)`, reversed when `t.reversed`.
    - `test_walked_direction_follows_the_passes`:
      - `MagSetup()` over rows 0..7 gives `[1, -1, 1, -1, 1, -1, 1, -1]`;
      - `MagSetup(sensor_separation_m=0.5)` gives `[1, 1, -1, -1, 1, 1, -1, -1]`;
      - `MagSetup(sensors=1)` over rows 0..3 gives `[1, -1, 1, -1]`;
      - `MagSetup(zigzag=False)` gives all `1`.
    - `test_each_reading_sits_mid_interval_whichever_way_it_was_walked`. For rows 0 and 1 of `traverses(S, GRID, 4, 16)`:
      - `stored_along` both equal `0.125 + 0.25 * arange(16)`;
      - the directions are `(1, -1)`;
      - `reversed` is `(False, True)`.
    - `test_an_unflipped_return_traverse_keeps_its_stored_order`: with `flipped=False`, row 1 has `reversed is False`, direction −1, and `along == 3.875 - 0.25 * arange(16)`.
    - `test_traverses_step_across_from_the_starting_corner`:
      - the offsets are `[0.25, 0.75, 1.25, 1.75]`;
      - with `far_x=True, far_y=True` they are `[1.75, 1.25, 0.75, 0.25]`, and row 0's along is `3.875 - 0.25 * arange(16)` with direction −1.
    - `test_destagger_moves_each_traverse_along_its_own_walk`: with `shifts=(0.1,) * 4`, row 0's along is +0.1 against the unshifted one, and row 1's is −0.1.
    - `test_traverses_along_x_put_the_offset_in_y`: `axis="x"` on a 4 × 2 grid gives `local[:, 1] == offset`.
  - `test_mag_real_files.py`. Every test skips when `MAG_FILES` is empty, and files are keyed by name.

    ```python
    MISSING = {"example1.dat": 0, "example2.dat": 0, "example3.dat": 7273,
               "example4.dat": 24, "example5.dat": 0, "example6.dat": 24}
    KEPT_ZEROS = {"example1.dat": 9, "example2.dat": 15, "example3.dat": 5,
                  "example4.dat": 10, "example5.dat": 3, "example6.dat": 7}
    ```

    - `test_real_grids_are_60_traverses_of_240_readings`.
    - `test_real_missing_data_counts`: the NaN counts equal `MISSING`, and the remaining `== 0.0` counts equal `KEPT_ZEROS`.
    - `test_real_missing_blocks_are_where_section_3_says`:
      - example4 rows `[49, 51]`, columns `29:41`, are all NaN;
      - example6 rows `[33, 35]`, columns `20:32`, are all NaN;
      - every row of example3 ends in NaN.
    - `test_real_missing_summaries`:
      - example4 gives `"24 readings are missing data, on traverses 50 and 52."`;
      - example6 gives `"… on traverses 34 and 36."`;
      - example3 gives `"7273 readings are missing data, on traverses 1, 2, 3, 4, 5, 6 and 54 more."`.
- [ ] **Step 2: Run the core tier and watch the new tests fail** (import errors, then assertion failures).
- [ ] **Step 3: Implement** `GridPlacement.along`/`.local`, then `grad601.py`, `setup.py` and `traverses.py`. `__init__.py` re-exports every public name in a sorted `__all__`.
- [ ] **Step 4: Run the core + pure tier, lint and types.** Everything is green. The real-data tests ran and did not skip.
- [ ] **Step 5: Commit and push.** `feat(mag): read Grad601 files, mark missing data, place traverses (M19a)`.

---

### Task 2: Mag files in the site and the survey file (nsgeo-core)

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/geometry/grid.py` (`INSTRUMENTS`, `Grid.instrument`, `__post_init__`)
- Create: `packages/nsgeo-core/src/nsgeo/mag/file.py` (re-exported from `nsgeo.mag`)
- Modify: `packages/nsgeo-core/src/nsgeo/model/survey.py` (`Site.mag_files`, `.mag_setup`, `.mag_view`, `validate`)
- Modify: `packages/nsgeo-core/src/nsgeo/project.py`:
  - `MAG_SCHEMA_VERSION`, `READABLE_SCHEMA_VERSIONS`;
  - grid `instrument`;
  - `mag_files`, `mag_setup` and `mag_view` save and load;
  - `_COLOUR_SCOPES` gains `"mag"`.
- Test:
  - `tests/test_grid.py`;
  - `tests/test_mag_file.py` (new);
  - `tests/test_survey.py`;
  - `tests/test_project.py`, where `test_loads_schema_1_and_2_and_refuses_3` becomes `test_loads_schema_1_2_and_3_and_refuses_4`;
  - `tests/test_mag_real_files.py`.

**Interfaces:**
- Consumes: Task 1's `MagSetup`, `traverses`, `read_grad601`, `mark_missing`.
- Produces:

```python
# nsgeo/geometry/grid.py
INSTRUMENTS: tuple[str, ...] = ("gpr", "mag")
Grid.instrument: str = "gpr"     # last field; ValueError "instrument must be one of ('gpr', 'mag'), got {x!r}"

# nsgeo/mag/file.py
@dataclass(frozen=True, eq=False)
class MagFile:
    path: Path
    grid_id: str
    setup: MagSetup
    n_rows: int
    n_readings: int
    scales: tuple[float, ...]     # one per traverse; each finite and > 0
    shifts: tuple[float, ...]     # one per traverse, metres; each finite
    @classmethod
    def open(cls, path: Path, grid_id: str, setup: MagSetup) -> MagFile: ...   # reads once; scales all 1.0, shifts all 0.0
    def raw(self) -> np.ndarray: ...        # read_grad601, read-only, cached by (path, size, mtime_ns)
    def readings(self) -> np.ndarray: ...   # mark_missing(raw, setup.missing_run), read-only, cached likewise
    def traverses(self, grid: Grid) -> tuple[Traverse, ...]: ...
    def points(self, grid: Grid) -> tuple[np.ndarray, np.ndarray]: ...  # (m, 2) world, (m,) values: every finite reading
def clear_mag_cache() -> None: ...

# nsgeo/model/survey.py — Site gains
mag_files: list[MagFile] = field(default_factory=list)
mag_setup: MagSetup | None = None          # the setup the next import starts from (C5)
mag_view: dict[str, Any] = field(default_factory=dict)
# {"scope": "grid"|"site", "grid": mag grid id, "cell": float > 0,
#  "finish": {"method", "max_distance_spacings", "smooth_x_m", "smooth_y_m"}, "palette": str}; every key optional

# nsgeo/project.py
MAG_SCHEMA_VERSION = 3
READABLE_SCHEMA_VERSIONS = (SCHEMA_VERSION, CUTS_SCHEMA_VERSION, MAG_SCHEMA_VERSION)
```

**Survey file rules** (P8):
- **Schema.** A site with any `instrument == "mag"` grid or any mag file is version 3. Otherwise it is 2 with cuts and 1 without.
- **Grids.** A grid writes `"instrument": "mag"` only when it is a mag grid. A missing instrument loads as `"gpr"`, and an unknown one is a `ProjectError`.
- **Mag file paths** go through `line_key(..., allow_absolute=allow_absolute)`, as line paths do.
- **Loading a mag file.**
  - A missing file is a `ProjectError` worded as for a line.
  - An invalid setup is `ProjectError("invalid setup for mag file {path!r}: {exc}")`.
  - A correction row that is outside the file, or not a finite number, is a `ProjectError`.
- **Remembered choices.** `mag_setup` and `mag_view` are written whenever they are set.
  - `mag_setup` loads through `MagSetup.from_dict`, and anything it refuses reads as `None`.
  - `mag_view` loads through `_clean_mag_view(value, known_mag_grids)`, which keeps each key only when usable. Its finish fields are vetted by the same rules as `_clean_resolution`.

- [ ] **Step 1: Write the failing tests.**
  - `test_grid.py`:
    - `test_a_grid_is_gpr_unless_told_otherwise`.
    - `test_an_unknown_instrument_is_refused`.
  - `test_mag_file.py`:
    - `test_open_reads_the_shape_and_starts_uncorrected`: a (4, 16) file gives `n_rows, n_readings == 4, 16`, `scales == (1.0,) * 4` and `shifts == (0.0,) * 4`.
    - `test_points_skip_missing_readings_and_follow_the_placement`:
      - The setup is `MagSetup(readings_per_metre=4.0)`, with a run of 4 zeros on row 2, on the grid `Grid("M", (100.0, 200.0), 30.0, 2.0, 4.0, "EPSG:32616", 0.5, instrument="mag")`.
      - That gives 60 points, all 5.0.
      - The first 16 world points equal `grid.to_world(traverses(grid)[0].placement.local(16, 4.0))`.
    - `test_readings_are_read_only_and_reread_when_the_file_changes`: rewrite the file, then `os.utime(..., ns=...)` forward. The new values are read.
    - `test_corrections_must_match_the_traverses`: `dataclasses.replace(mag, scales=(1.0,))` raises `ValueError`.
  - `test_survey.py`:
    - `test_a_line_on_a_mag_grid_fails_validate`.
    - `test_a_cut_on_a_mag_grid_fails_validate`.
    - `test_a_mag_file_on_a_gpr_grid_fails_validate`.
    - `test_two_mag_files_on_one_grid_fail_validate`.
    - `test_a_mag_file_on_an_unknown_grid_fails_validate`.
    - Each matches its copy line.
  - `test_project.py`:
    - `test_a_site_with_mag_saves_as_schema_3_and_round_trips`:
      - The site has mag grid `M` and the file `data/a.dat` (4 × 16), with `shifts=(0.0, 0.1, 0.0, 0.0)`, `scales=(1.0, 1.0, 0.98, 1.0)`, a non-default `mag_setup`, and `mag_view={"scope": "site", "cell": 0.25}`.
      - The saved doc has `schema_version == 3` and `grids[0]["instrument"] == "mag"`.
      - `mag_files == [{"path": "data/a.dat", "grid_id": "M", "setup": setup.to_dict(), "corrections": {"1": {"travel_shift": 0.1}, "2": {"scale": 0.98}}}]`.
      - Loading gives back equal setup, scales, shifts, instrument, `mag_setup` and `mag_view`.
    - `test_a_site_without_mag_writes_no_mag_keys`: there is no `instrument` and no `mag_*` key, and the version is unchanged.
    - `test_loads_schema_1_2_and_3_and_refuses_4`.
    - `test_a_missing_mag_file_is_a_project_error`.
    - `test_an_unknown_instrument_is_a_project_error`.
    - `test_a_correction_for_a_traverse_the_file_lacks_is_a_project_error`.
    - `test_a_damaged_remembered_setup_or_view_reads_as_unset`:
      - `mag_setup = {"spacing_m": "wide"}` loads as `None`;
      - `mag_view = {"cell": -1, "scope": "everywhere", "grid": "nope", "palette": 3}` loads as `{}`.
    - `test_mag_colours_round_trip`: `slice_colours["mag"] == {"own": True, "style": "<qgis/>"}` survives a round trip.
  - `test_mag_real_files.py`:
    - `test_real_points_fill_the_grid`: each file on a 30 × 30 mag grid at the origin, azimuth 0, with `MagSetup()`.
    - Every world point lies in `[0, 30]²`.
    - The point count is `14400 - MISSING[name]`.
- [ ] **Step 2: Run the core tier and watch the new tests fail.**
- [ ] **Step 3: Implement** `Grid.instrument`, then `MagFile`, then `Site` and `validate`, then `project.py`.
- [ ] **Step 4: Run the core + pure tier, lint and types.** Everything is green, and the real-data tests ran.
- [ ] **Step 5: Commit and push.** `feat(mag): mag files in the site, grids by instrument, survey file schema 3 (M19a)`.

---

### Task 3: The mag map (nsgeo-core)

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/mag/map.py` (re-exported)
- Test: `packages/nsgeo-core/tests/test_mag_map.py` (new), `tests/test_mag_real_files.py`

**Interfaces:**
- Consumes: `MagFile.points` (Task 2); `CubeFrame.for_grid`, `slice_extent`, `plan_fill`, `finish_slice`, `FinishSettings`, `SiteLattice`, `fitting_lattice`, `bilinear_taps`, `footprint` and `compose_footprints` (all in `nsgeo.slices`, unchanged).
- Produces:

```python
DEFAULT_CELL_M: float = 0.125
def bin_readings(frame: CubeFrame, world: np.ndarray, values: np.ndarray) -> np.ndarray: ...
    # float32 (ny, nx): the mean of the readings in each cell (frame.cell_index); NaN where none; outside the frame dropped
def grid_map(mag: MagFile, grid: Grid, cell: float, settings: FinishSettings) -> tuple[CubeFrame, np.ndarray]: ...
    # frame = CubeFrame.for_grid(grid, cell); bin; plan_fill(populated, cell, settings.method,
    # settings.max_distance_m, settings.search_radius_m); finish_slice
def mosaic(maps: Sequence[tuple[CubeFrame, np.ndarray]], cell: float, crs: str, *,
           max_pixels: int, max_covered: int) -> tuple[SiteLattice, np.ndarray]: ...
    # lattice = fitting_lattice([slice_extent(f) ...], cell, crs, max_pixels, max_covered);
    # each map sampled over the window of lattice pixels around its slice_extent (bilinear_taps,
    # footprint(taps, rows, cols, row0, col0)); compose_footprints. ValueError for no maps, or
    # a frame whose crs is not `crs`.
def display_centre(values: np.ndarray) -> float: ...   # median of the finite values; 0.0 when none
```

- [ ] **Step 1: Write the failing tests.**
  - `test_mag_map.py`:
    - `test_bin_readings_averages_each_cell_and_leaves_empty_cells_nan`: two readings, 2.0 and 4.0, in one cell give 3.0, and every other cell is NaN.
    - `test_readings_outside_the_frame_are_dropped`.
    - `test_grid_map_fills_between_traverses_within_the_max_distance`. Use a 4 × 2 m mag grid with 8 traverses along X at 0.25 m spacing, 8 readings per metre, and cell 0.125.
      - With `"none"`, only the rows the traverses cross hold data.
      - With `"kriging"` and max distance 0.1875 (0.75 × spacing), every cell is finite.
      - With max distance 0, `"kriging"` equals `"none"`.
    - `test_the_mosaic_of_two_touching_grids_holds_each_where_it_lies`. Two 2 × 2 m grids side by side are filled with constants 1.0 and 3.0.
      - The lattice's geotransform pixel is the cell.
      - Pixels inside the left grid are 1.0 and inside the right one 3.0, at least one pixel from the seam.
      - Pixels off both grids are NaN.
    - `test_a_mosaic_in_another_crs_is_refused`.
    - `test_display_centre_is_the_median_of_finite_values`: `[1, 2, nan, 10]` gives 2.0, and all-NaN gives 0.0.
  - `test_mag_real_files.py`. All grids are 30 × 30 m with `MagSetup()`, cell `DEFAULT_CELL_M`, kriging, max distance 0.375 and search radius 1.0:
    - `test_a_real_grid_map_covers_its_grid`: example1's map is at least 98% finite. example3's is between 45% and 55% finite (49.5% of its readings are real), with its far side blank. A value outside either band is reported, not loosened.
    - `test_the_six_real_grids_land_where_the_layout_puts_them`. This uses §3's inferred layout.
      - Every grid is set up with `axis="x"`, `far_y=True`, `far_x=False`.
      - The origins (azimuth 0, CRS `EPSG:32616`) are: ex5 (0, 30), ex2 (30, 30), ex3 (60, 30), ex4 (0, 60), ex1 (30, 60) and ex6 (60, 0).
      - The mosaic's pixels at least 0.5 m inside each grid equal that grid's own map sampled bilinearly at the same points, to 1e-4.
      - The block x 0–60, y 0–30 is NaN.
    - `test_real_neighbours_join_along_their_traverses`. In the same mosaic, take the pixel columns either side of the seams ex4|ex1, ex5|ex2 and ex2|ex3, where both are finite.
      - Each seam correlates with r ≥ 0.8 (§3 measured r ≈ 0.92 on the raw rows).
      - A failure here is reported as a possible layout, flip or direction error. It is never loosened to pass (spec §10).
- [ ] **Step 2: Run the core tier and watch the new tests fail.**
- [ ] **Step 3: Implement** `map.py`.
- [ ] **Step 4: Run the core + pure tier, lint and types.** Everything is green, the real-data tests ran, and nothing skipped.
- [ ] **Step 5: Commit and push.** `feat(mag): per-grid mag maps and the mosaic (M19a)`.

---

### Task 4: Mag grids apart from GPR grids: session, grid dialog, Survey panel (plugin)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py`:
  - the `mag_changed` signal;
  - the mag API below;
  - `remove_grid`, `replace_grid` and `add_lines`;
  - `COLOUR_SCOPES` gains `"mag"`.
- Modify: `nsgeo_qgis/ui/grid_dialog.py`:
  - the `instrument` constructor keyword;
  - an `Instrument` combo in `form_top` after Id;
  - `_FORM_LABELS`;
  - `result_grid`;
  - the Velocity row hidden for mag.
- Modify: `nsgeo_qgis/plugin.py`:
  - `open_grid_dialog(grid_id, *, instrument="gpr")`;
  - `open_import_dialog`'s precondition becomes "Add a GPR grid before importing lines." when there is no GPR grid;
  - `_cut_grid_and_vertices` uses GPR grids only.
- Modify, filtering to GPR grids:
  - `ui/import_dialog.py` (`_fill_grid_combo`);
  - `ui/edit_lines_dialog.py` (`_grid_ids`);
  - `ui/slices_dock.py` (the grid combo fill, ~line 868);
  - `ui/site_scope.py` (`included_grids`, `site_rows`, and the grid loops at ~299 and ~413);
  - `site_engine.py` (the site CRS at ~line 758 comes from the first GPR grid);
  - `ui/survey_dock.py` (`_add_move_menu`, `target_grid_id`).
- Modify: `nsgeo_qgis/ui/survey_dock.py`:
  - the mag grid row text, and a `"magfile"` row kind;
  - the menus;
  - the `mag_import_requested(str)` and `mag_grid_selected(str)` signals;
  - `target_mag_grid_id()`;
  - `_identity`, `_item_for_identity`, `_selected_targets` and `_removal_text` extended.
- Modify: `packages/nsgeo-qgis/tests/plugin_testing.py`: `synthetic_grad601(folder, name, rows=8, readings=32, value=5.0, missing=()) -> Path`. Each row ramps by `0.1` per reading, and `missing` holds `(row, col0, n)` zero runs.
- Modify: `tests/qgis/conftest.py`: the `mag_site` fixture, below.
- Test:
  - `tests/qgis/test_plugin_session_mag.py` (new);
  - `tests/qgis/test_plugin_mag_grids_apart.py` (new);
  - `tests/qgis/test_plugin_grid_dialog.py`;
  - `tests/qgis/test_plugin_survey_dock.py`.

**Interfaces:**
- Consumes: Task 2's `Grid.instrument`, `MagFile`, `Site.mag_files`, `.mag_setup` and `.mag_view`.
- Produces (SiteSession):

```python
mag_changed = pyqtSignal()
def gpr_grids(self) -> list[Grid]: ...
def mag_grids(self) -> list[Grid]: ...
def mag_key(self, mag: MagFile) -> str: ...                  # line_key(mag.path, root, allow_absolute=True)
def mag_files(self) -> list[MagFile]: ...
def mag_file_on(self, grid_id: str) -> MagFile | None: ...
def mag_for_key(self, key: str) -> MagFile: ...             # KeyError
def set_mag_file(self, mag: MagFile) -> MagFile | None: ... # grid must exist and be mag (ValueError); replaces
    # and returns the grid's file; ValueError when the same file is already on another grid; dirty; mag_changed
def remove_mag_file(self, key: str) -> None: ...            # dirty; mag_changed
def mag_setup(self) -> MagSetup | None: ...
def remember_mag_setup(self, setup: MagSetup) -> None: ...  # dirty only when changed
def mag_view(self) -> dict[str, Any]: ...                   # a copy
def set_mag_view(self, **fields: Any) -> None: ...          # merge; dirty only when changed
```

- `remove_grid` on a mag grid holding a file treats the file as its lines. It is refused unless `with_lines`, and it emits `mag_changed`. It also drops the grid from `mag_view["grid"]`.
- `replace_grid` raises `ValueError("a grid's instrument cannot change")` when the instrument differs.
- `add_lines` raises `ValueError("grid {id!r} is a magnetometer grid; DZT lines go on GPR grids")`.
- `SurveyDock`:
  - `mag_import_requested(str)` carries the grid id, from `Import magnetometer file…`.
  - `mag_grid_selected(str)` is emitted on a click on a mag grid row or its file row.
  - `target_mag_grid_id() -> str | None` returns the selected mag grid or file row's grid.
- `GridDialog.__init__(..., instrument: str = "gpr")`:
  - For a new grid, the combo starts at `instrument`. With `"mag"`, Size X/Y start at 30 and the spacing at 0.5 (P13).
  - For an existing grid, the combo shows the grid's instrument and is disabled.
- **The `mag_site` fixture** is built like `site3_factory` and opened in a `SiteSession`:
  - GPR grid `G1`, 20 × 20 m, holding two synthetic DZT lines;
  - mag grid `M1`, 4 × 4 m at (100, 100), azimuth 0, holding `synthetic_grad601(…, "m1.dat")` under `MagSetup()`;
  - an empty mag grid `M2`, 4 × 4 m at (104, 100).

  It yields `(session, root)`.

- [ ] **Step 1: Write the failing tests.**
  - `test_plugin_session_mag.py`:
    - `test_set_mag_file_replaces_the_grids_file_and_announces_it`: the old file is returned, `mag_changed` is emitted once, and the site is dirty.
    - `test_a_mag_file_cannot_go_on_a_gpr_grid`.
    - `test_dzt_lines_cannot_go_on_a_mag_grid`.
    - `test_removing_a_mag_grid_holding_a_file_needs_with_lines`.
    - `test_a_grids_instrument_cannot_change`.
    - `test_mag_view_and_setup_merge_and_dirty_only_on_change`.
    - `test_a_saved_mag_site_reopens_with_its_files`.
  - `test_plugin_mag_grids_apart.py`, on `mag_site`:
    - `test_the_dzt_import_dialog_lists_only_gpr_grids`.
    - `test_the_slices_panel_lists_only_gpr_grids`.
    - `test_whole_site_rows_are_only_gpr_grids`.
    - `test_edit_lines_offers_only_gpr_grids`.
    - `test_move_to_grid_offers_only_gpr_grids`.
    - `test_a_cut_cannot_start_on_a_mag_grid`.
  - `test_plugin_grid_dialog.py`:
    - `test_a_new_grid_can_be_a_magnetometer_grid`: `result_grid().instrument == "mag"`, and the Velocity row is hidden.
    - `test_a_new_mag_grid_starts_at_the_usual_setup`: 30, 30 and 0.5.
    - `test_an_existing_grids_instrument_is_shown_and_fixed`.
  - `test_plugin_survey_dock.py`:
    - `test_a_mag_grid_shows_its_file_as_one_row`, with the exact copy.
    - `test_a_mag_grid_menu_offers_mag_import_not_dzt`.
    - `test_clicking_a_mag_row_selects_its_grid`: `mag_grid_selected` is emitted with `"M1"`.
    - `test_removing_a_mag_grid_takes_its_file_after_asking`: `answer_modal` gives the exact prompt. After it, the site saves and validates.
- [ ] **Step 2: Run the new and modified test files and watch them fail.**
- [ ] **Step 3: Implement** the session first, then the grid dialog, the filters and the Survey panel.
- [ ] **Step 4: Run the touched QGIS test files, the core + pure tier, lint and types.** All green.
- [ ] **Step 5: Commit and push.** `feat(mag): magnetometer grids apart from GPR grids in the session, grid dialog and Survey panel (M19a)`.

---

### Checkpoint C1: the import dialog's layout (coordinator and author; a human gate)

- [ ] Build a lavish mockup of the Import magnetometer files dialog from this plan's copy:
  - the file table;
  - the setup group, with a small grid picture showing the origin and the chosen start corner;
  - the buttons.

  Use made-up file names only. Ask the author whether the corner choice and the setup rows read clearly.
- [ ] Fold any changes into this plan's copy before dispatching Task 5. Wait for the author.

---

### Task 5: Import mag… (plugin)

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/mag_import_dialog.py`
- Modify: `nsgeo_qgis/plugin.py`:
  - the `Import mag…` toolbar action, enabled like `Import DZT…`;
  - `_import_mag_from_toolbar`;
  - `open_mag_import_dialog(grid_id: str | None)`, which is modeless and single-instance, like `open_import_dialog`;
  - wiring for `SurveyDock.mag_import_requested`;
  - wiring for `MagImportDialog.new_grid_requested`, which calls `open_grid_dialog(None, instrument="mag")`;
  - the per-file summary messages after an import.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_mag_import_dialog.py` (new)

**Interfaces:**
- Consumes:
  - from Task 4: `SiteSession.mag_grids`, `mag_file_on`, `set_mag_file`, `mag_setup`, `remember_mag_setup`, `mag_key`, `mag_changed` and `grids_changed`;
  - from Tasks 1–2: `MagFile.open`, `fit_problems`, `missing_summary` and `MagSetup`.
- Produces:

```python
class MagImportDialog(QDialog):
    new_grid_requested = pyqtSignal()
    imported = pyqtSignal(list)                       # [(key, grid_id, summary)] after a successful import
    def __init__(self, session: SiteSession, grid_id: str | None = None, parent: QWidget | None = None): ...
    def add_files(self, paths: list[Path]) -> None: ...     # unreadable files go to the status line, not the table
    def setup(self) -> MagSetup: ...                        # from the form; ValueError carries MagSetup's message
    def set_setup(self, setup: MagSetup) -> None: ...
    def retarget(self, grid_id: str | None) -> None: ...
    def row_grid(self, row: int) -> str | None: ...
    def set_row_grid(self, row: int, grid_id: str | None) -> None: ...
```

**Behaviour:**
- **Start.** The form starts from `session.mag_setup()`, or `MagSetup()`.
- **Live updates.** The Missing and Fits columns update when the setup or a row's grid changes.
- **Grid combos.** On `grids_changed` they refill, keeping each choice, and any row without a grid takes the next free one (P16).
- **`accept()`, in order:**
  1. Is it the same site? (`ImportDialog`'s check.)
  2. Is the setup valid?
  3. Does every row have a grid?
  4. Is no grid chosen twice?
  5. The fit prompt, only when something does not fit.
  6. The replace prompt, only when a chosen grid already holds a file.
  7. `remember_mag_setup`.
  8. `set_mag_file(MagFile.open(...))` for each row.
  9. Emit `imported`, then close.
- **A No** at either prompt leaves the dialog open and changes nothing.
- **After import,** the plugin posts each file's summary, then shows the Mag panel on the first imported grid (Task 6 connects this; Task 5 emits `imported`).

- [ ] **Step 1: Write the failing tests.** All of them run on `mag_site` with synthetic files:
  - `test_importing_a_file_puts_it_on_its_grid_with_the_setup`.
  - `test_the_setup_is_remembered_for_the_next_import`: a new dialog's `setup()` equals the last one.
  - `test_each_row_takes_the_next_empty_mag_grid`.
  - `test_a_file_that_does_not_fit_asks_before_importing`. Use a 60 × 240 file on 4 × 4 m `M2`, with `answer_modal`:
    - No leaves nothing added;
    - Yes adds the file, and nothing is cropped (`n_readings == 240`).
  - `test_importing_onto_a_grid_with_a_file_asks_then_replaces`: the prompt text is exact.
  - `test_two_files_on_one_grid_are_refused`: the status copy is exact.
  - `test_a_bad_setup_is_reported_and_nothing_changes`: a separation of 0.7.
  - `test_an_unreadable_file_is_named_and_not_added`: a ragged file.
  - `test_import_after_the_site_was_replaced_adds_nothing`.
  - `test_the_summary_says_how_many_readings_are_missing_and_where`: `missing=((2, 3, 6),)` gives the message `"m3.dat: 6 readings are missing data, on traverse 3."`.
  - `test_new_mag_grid_opens_the_grid_dialog_as_magnetometer`, at plugin level: the grid dialog's instrument combo reads Magnetometer.
- [ ] **Step 2: Run the file and watch the tests fail.**
- [ ] **Step 3: Implement** the dialog, then the plugin wiring.
- [ ] **Step 4: Run the touched QGIS test files, the core + pure tier, lint and types.** All green.
- [ ] **Step 5: Commit and push.** `feat(mag): Import mag… with a remembered setup, a fit check and a missing-data summary (M19a)`.

---

### Task 6: The Mag panel and the Mag (live preview) layer (plugin)

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/mag_engine.py` (Qt-free; add it to the mypy list in `ci.yml`)
- Create: `nsgeo_qgis/ui/mag_dock.py`
- Modify: `nsgeo_qgis/slice_layer.py`:
  - `MAG_LAYER_NAME = "Mag (live preview)"`;
  - a `centre: float = 0.0` keyword on `build_shader`, `apply_renderer` and `SliceLayer.update_north_up`;
  - the renderer key gains the centre;
  - for a bipolar palette `lo, hi = centre - limit, centre + limit`. Unipolar ignores the centre.
- Modify: `nsgeo_qgis/own_colours.py`: `seed_style(..., centre: float = 0.0)`, with the same rule.
- Modify: `nsgeo_qgis/plugin.py`:
  - `self.mag_dock` and `self.mag_layer = SliceLayer(self.layers)`;
  - `addDockWidget(Right)`, `self.docks`, then hidden at start-up (P14);
  - `("Mag", self.mag_dock)` in `_build_panels_menu`'s `named` tuple;
  - `_on_mag_map_changed`;
  - mag symbology and own-style slots, modelled on `_open_slice_symbology` and `_on_own_style_changed`;
  - `SurveyDock.mag_grid_selected` connected to `mag_dock.show_grid`;
  - `MagImportDialog.imported` connected to show the dock on the first imported grid;
  - `site_closed` clears the mag layer;
  - `unload` disposes of the mag layer.
- Modify: `docs/guide/getting-started.md`:
  - the toolbar table gains `Import mag…`;
  - the panels section names the Mag panel. Grep for links to `#2-the-toolbar-and-the-four-panels` before renaming that heading;
  - a new `### Step 10: Magnetometer grids` after Step 9 covers the setup at import, missing data, the Mag panel and colours. It says that exporting the mag map and destaggering mag traverses are not built yet.
- Test:
  - `packages/nsgeo-qgis/tests/pure/test_pure_mag_engine.py` (new);
  - `tests/qgis/test_plugin_mag_dock.py` (new);
  - `tests/qgis/test_plugin_slice_layer.py`;
  - `tests/qgis/test_plugin_panels_menu.py`: `test_the_panels_button_drops_down_the_four_panels_then_the_layouts` becomes five panels, named accordingly.

**Interfaces:**
- Consumes:
  - from Task 3: `grid_map`, `mosaic`, `display_centre` and `DEFAULT_CELL_M`;
  - from Task 4: the session's mag API, `mag_changed`, `grids_changed`, `site_opened`, `site_closed`, `slice_colours("mag")` and `set_slice_colours("mag", …)`;
  - the existing `SliceFinish`, `FinishPanel`, `busy_cursor`, `SITE_MAX_PIXELS`, `SITE_MAX_COVERED_PIXELS`, `PercentileClip` and `limit_over_slices`.
- Produces:

```python
# nsgeo_qgis/mag_engine.py
MAG_STRETCH_PERCENTILE: float = 95.0
DEFAULT_MAG_FINISH = SliceFinish(method="kriging", max_distance_spacings=0.75)
@dataclass(frozen=True)
class MagSettings:
    cell: float = DEFAULT_CELL_M
    finish: SliceFinish = DEFAULT_MAG_FINISH
@dataclass(frozen=True, eq=False)
class MagMosaic:
    array: np.ndarray            # (H, W) float32, NaN nodata
    lattice: SiteLattice
    grids: tuple[str, ...]       # drawn, in site order
    left_out: tuple[str, ...]    # in another CRS (P11)
    def centre(self) -> float: ...   # display_centre(array)
    def limit(self) -> float: ...    # limit_over_slices((array - centre,), PercentileClip(MAG_STRETCH_PERCENTILE))
class MagEngine:
    def __init__(self, *, max_entries: int = 32) -> None: ...
    def grid_map(self, mag: MagFile, grid: Grid, settings: MagSettings) -> tuple[CubeFrame, np.ndarray]: ...
        # cached on (mag object, file size and mtime_ns, grid geometry and crs, settings);
        # finish = settings.finish.in_metres(mag.setup.spacing_m) (P15)
    def mosaic(self, items: Sequence[tuple[MagFile, Grid]], settings: MagSettings) -> MagMosaic | None: ...  # None for no items
    def clear(self) -> None: ...

# nsgeo_qgis/ui/mag_dock.py
class MagDock(QgsDockWidget):
    map_changed = pyqtSignal()
    symbology_requested = pyqtSignal()
    error = pyqtSignal(str)
    def __init__(self, session: SiteSession, parent: QWidget | None = None): ...
    def scope(self) -> str: ...                       # "grid" | "site"
    def set_scope(self, scope: str) -> None: ...
    def show_grid(self, grid_id: str) -> None: ...    # sets the Grid combo; the scope is unchanged
    def settings(self) -> MagSettings: ...
    def palette(self) -> str: ...                     # default "grey_black_high" (P12)
    def current_map(self) -> MagMosaic | None: ...
    def status(self) -> str: ...
    def subtitle(self) -> str: ...
    def refresh(self) -> None: ...                    # recompute under busy_cursor when visible, then emit map_changed
    def own_colours_on(self) -> bool: ...             # session.slice_colours("mag")
    def own_style(self) -> str | None: ...
    def set_own_style(self, text: str) -> None: ...
```

**Behaviour:**
- **What is drawn.**
  - This grid draws the Grid combo's grid, which lists mag grids only.
  - Whole site draws every mag grid holding a file (P11).
  - Changes to the cell and the finish are debounced by 120 ms, as in the Slices panel.
- **Remembering choices.**
  - Each user change writes `session.set_mag_view(...)`: scope, grid, cell, finish fields and palette.
  - `site_opened` restores them.
- **Redraws.** These all call `refresh`: `mag_changed`, `grids_changed`, the site opening or closing, and showing the dock.
- **Drawing the layer.** `_on_mag_map_changed` does one of two things:
  - It clears the layer when `current_map()` is None.
  - Otherwise it calls `mag_layer.update_north_up(m.array, m.lattice.geotransform, m.lattice.crs, limit=m.limit, centre=m.centre(), colormap_name=dock.palette(), unipolar=False, subtitle=dock.subtitle(), name=MAG_LAYER_NAME, own=dock.own_colours_on(), own_style=dock.own_style())`.

- [ ] **Step 1: Write the failing tests.**
  - `test_pure_mag_engine.py`, with synthetic files written by a local helper:
    - `test_a_grid_map_is_computed_once_per_settings`: the same array object comes back for the same inputs, and a new one after the cell changes.
    - `test_a_replaced_file_is_mapped_afresh`.
    - `test_a_grid_in_another_crs_is_left_out`.
    - `test_no_items_is_no_mosaic`.
    - `test_the_limit_is_the_95th_percentile_about_the_median`.
  - `test_plugin_slice_layer.py`:
    - `test_a_centre_shifts_the_palette_range`: the renderer's classification min and max are `4 - 3` and `4 + 3`.
    - `test_own_colours_seed_around_the_centre`.
  - `test_plugin_mag_dock.py`, on `mag_site`:
    - `test_this_grid_draws_the_chosen_grid_on_the_mag_layer`: the layer is named `Mag (live preview)`, its extent covers M1, and it is in the site's layer group.
    - `test_whole_site_draws_every_mag_grid_holding_a_file_and_no_gpr_grid`.
    - `test_the_default_colours_centre_on_the_median`.
    - `test_own_colours_are_kept_in_the_mag_scope`.
    - `test_cell_and_finish_changes_redraw_and_are_remembered`: save, reopen, and the dock restores them.
    - `test_editing_a_mag_grid_moves_its_map`: `replace_grid` with a new origin moves the layer's extent by the same amount.
    - `test_an_empty_mag_grid_draws_nothing_and_says_why`: `M2` with This grid. There is also a site with no mag at all. In both cases the exact statuses show and no layer is left drawn.
    - `test_a_grid_in_another_crs_is_left_out_and_named`.
    - `test_importing_shows_the_mag_panel_on_the_imported_grid`.
    - `test_a_real_grid_draws`: example1 on a 30 × 30 m mag grid. It skips when the files are absent; check that it ran.
  - `test_plugin_panels_menu.py`: the five-panel version of the existing test.
- [ ] **Step 2: Run the new and modified files and watch them fail.**
- [ ] **Step 3: Implement** `mag_engine.py`, then the centre in `slice_layer` and `own_colours`, then `MagDock`, then the plugin wiring, then the guide.
- [ ] **Step 4: Run the touched QGIS test files, the core + pure tier, lint and types.** All green.
- [ ] **Step 5: Commit and push.** `feat(mag): the Mag panel and the Mag (live preview) layer (M19a)`.

---

### Task 7: Review, deploy and walkthrough (coordinator and author; a human gate)

- [ ] Run the full QGIS tier and confirm the real-data tests ran. Then run a whole-branch review (opus) against the spec and this plan, followed by a fix wave if needed.
- [ ] Deploy to a new profile `ns_geo_mag`: copy `ns_geo` with `cp -a`, then run `packages/nsgeo-qgis/scripts/dev_link.py` pointed at this worktree.
- [ ] Publish a walkthrough Artifact with a `db` capability for results. It covers:
  - Import example1–6 onto six mag grids laid out as §3 infers, or as the author knows them. Check that the second import remembers the setup.
  - Missing data: example3's summary and its blank far side, and the holes in example4 and example6.
  - This grid and Whole site, judged against TerraSurveyor's output:
    - Is each grid the right way round?
    - Is the zigzag stagger visible, at about ±0.25 m per traverse? Fixing it is Plan B.
  - The default colours (P12, including that positive is black), then own colours through Symbology….
  - Each interpolation method, and how long Whole site with minimum curvature takes (P10).
  - The author's own site with GPR over mag: GPR panels list no mag grid, the Mag panel no GPR grid, and the mag layer sits under the GPR grids.
  - Save, reopen, and everything comes back.
- [ ] Stop and wait for the author's results. Update the README roadmap ("In progress": Plan A built, walkthrough pending) and the memory. Merging asks first. Then write Plan B.
