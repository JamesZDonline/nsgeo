# M17b: Add data and GPS grids — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One **Add data ▾ ▸ GPR…** dialog with a Grid / GPS switch, in which GPS lines always go into a grid (an existing one, or a new one fitted around their tracks), and GPS lines that work in grids like tape lines do.

**Architecture:** The fitting is pure numpy in a new core module, `nsgeo.geometry.track_fit`. The plugin's two import dialogs become two pages (`GridImportPage`, `GpsImportPage`) in one `AddDataDialog` that owns the switch, the footer and the map preview. A GPS line joins a grid through its existing `TrackPlacement.grid_id`; the session, Survey panel, layers and Edit lines learn to carry that, through a `TrackEdit` beside `LineEdit`. Nothing about a GPS line's position changes when it joins or leaves a grid (C3).

**Tech Stack:** Python 3.9+ numpy core (`packages/nsgeo-core`); QGIS plugin on QGIS 3.44 / PyQt5 and 4.2 / PyQt6 (`packages/nsgeo-qgis`); pytest.

**Spec:** `docs/superpowers/specs/2026-11-06-nsgeo-gps-lines-design.md`: decision 14 and **decision 15** (the mock-up's answers), §6.3, §6.5, §9 (M17b), §11 (M17b walkthrough) and **§16** (the calls this plan makes). The approved mock-up is `.lavish/m17b-add-data.html` in the main checkout (git-ignored; read it, do not copy it).

## Global Constraints

- **Core:** numpy only (no scipy, no pyproj). Runtime Python 3.9: no `zip(strict=)`, no `match`, no PEP 604 unions outside annotations. `from __future__ import annotations` heads every new file.
- **Plugin:** Qt only through `qgis.PyQt`. `tests/pure/test_plugin_boundary.py` and `test_no_orphan_signals.py` stay green: every new signal is connected in `plugin.py`.
- **Every Qt slot guards its own body:** `except Exception as exc:  # noqa: BLE001 -- a slot …`, reporting through `plugin.message`, the dialog's status line or `_log`, never by raising.
- **Both QGIS versions:** code and tests run on QGIS 3.44 (PyQt5) and 4.2 (PyQt6). Compare Qt enums to enums, never to ints; clear QGIS flags with `qtcompat.without_layer_flag`. Local QGIS is 3.44 only, so CI's `plugin-qgis (qgis/qgis:4.2)` job is the Qt 6 check: read it after every push.
- **Tape lines and Grid mode are unchanged** in what they place and save. A site without GPS lines saves byte-for-byte as before.
- **A GPS line never moves when its grid changes** (C3, C13): only `TrackPlacement.grid_id` changes.
- **GPS lines never join a magnetometer grid.** main has no mag grids yet (M19a is unmerged); whichever of M17b and M19a merges second filters `Grid.instrument == "mag"` out of the Target grid list, Move to grid ▸ and Fit to these tracks, and folds M19a's `Import mag…` button into the Add data menu as `Magnetometer…`.
- **Privacy:** `tests/data/local/` is gitignored and reaches the worktree only by symlink; nothing from it is ever `git add -f`ed. No coordinate from a real DZG or DZT header appears in any committed file. Real-data tests assert relative quantities only (lengths, spacings, angles between lines and grid axes, counts, fractions). No site name in any committed file. Synthetic DZGs use made-up positions near lat 45.2, lon 10.5.
- **Shared-worktree safety:** reviewers and mutation probes work on a scratch copy, never on this worktree. `PYTHONDONTWRITEBYTECODE=1` for every run.
- **Commits:** end each message with a `Co-Authored-By:` line naming the model that wrote it. Push each commit to `origin nsgeo-m17b` as it is made. Touch no other worktree.

### Copy (exact)

Strings the user reads. `{n}`, `{gid}` and the like are filled in; `(s)` stays literal, as elsewhere in the plugin.

- **Toolbar:** a button `Add data` with an instant-popup menu holding one entry, `GPR…`. Tooltip: `"Add survey data to the site: GPR lines placed by a grid's tapes or by GPS."` It replaces `Import DZT…` and `Import GPS lines…`, at their place after `Add grid…`.
- **Dialog title:** `Add GPR data into {gid}`, `Add GPR data into new grid {name}`, `Add GPR data into a new grid` (no name yet), `Add GPR data` (no target).
- **Switch:** the label `Place lines by`, then two exclusive checkable buttons `Grid` and `GPS`.
- **GPS-available note (Grid mode only):** `"{n} of {m} files have a GPS log beside them."`, or `"This file has a GPS log beside it."` when one file was added and it has one. Hidden when no file has one.
- **Grid mode, a site with no grid:** status `"This site has no grid yet. Add one with Add grid…, or place the lines by GPS."`, Import disabled.
- **Import button:** `Import {n} line(s) into {gid}`, `Import {n} line(s) into new grid {name}`, `Import {n} line(s) into a new grid`.
- **GPS page form, in order:** `Target grid` (first entry `New grid`, then the site's grids by id); `Name` (New grid only); `Spacing (m)` (New grid only); `Fitted` (New grid only); `Destagger (m)`; `Processing preset`; `Coordinates:`.
  - Spacing note: `"measured from the tracks; type over it if it is wrong"` while measured; empty once typed; `"type one: one line gives nothing to measure it from"` or `"type one: these lines share no direction to measure it along"` while there is none.
  - Fitted: `"{w:.1f} × {l:.1f} m, azimuth {a:.1f}°, lined up with the lines, half a spacing outside the outer ones"`, or `"{w:.1f} × {l:.1f} m, azimuth {a:.1f}°, the smallest rectangle around them; these lines share no direction"`, or `"—"`.
  - Status: `"Name the new grid."`, `"A grid named {name} already exists."`.
- **Existing grid:** a column `Outside {gid}` before `Status`: `"—"` under 0.05 m, `"{m:.1f} m"` (amber), `"all {m:.1f} m"` (red) for a line wholly outside, whose refusal is `outside {gid}`.
- **After a GPS import:** `"imported {n} GPS line(s) into new grid {gid} ({w:.1f} × {l:.1f} m, spacing {s:.2f} m)"` or `"imported {n} GPS line(s) into {gid}"`; then M17a's warnings unchanged; then `"{file}: {m:.1f} m lies outside {gid} and is left out of its slices"` per line with 0.05 m or more outside; then M17a's `"not imported: {file} ({refusal})"` for refused files that are not handed on.
- **Hand-on banner** (Grid page, amber): `"{n} GPS line(s) are in {gid}. GPS could not place {k} file(s): place them by the tapes, or Cancel to leave them out."`, plus `" Offsets and directions are guessed from the GPS lines either side of each one."` when at least one row was guessed.
- **Guess notes:** `"between {a} and {b}"`, `"{k} spacing after {a}"` / `"{k} spacings after {a}"`, `"{k} spacing before {b}"` / `"{k} spacings before {b}"` (stems of the neighbouring files; `{k}` a whole number).
- **Survey panel:** a grid's `Import DZT files…` becomes `Add GPR data…`. A GPS line gains `Move to grid ▸` (after `Set destagger…`) and `Fit a grid to this track…`. A selection of only GPS lines gains `Move {phrase} to grid ▸` and `Fit a grid to these {n} tracks…`. A selection holding both kinds gets `Edit {phrase}…` (when all on one grid) and `Move {phrase} to grid ▸`, as a tape-only selection does.
- **After Fit to these tracks:** `"moved {n} GPS line(s) into {gid}"`.
- **Edit lines, a GPS row:** Offset, Dir, Start and Scale read `—`, read-only, tooltip `"A GPS line is placed by its track: Offset, Dir, Start and Scale do not apply."`; Along reads `GPS`. A bulk change or Measure that skips GPS rows says `"Left {n} GPS line(s) alone: {what} applies to tape lines only."` with `{what}` one of `Offset`, `Dir`, `Start`, `Scale`, `Fit to grid edges`, `Measure`.

### Verification commands (from the worktree root)

The worktree uses the main checkout's virtualenvs with the worktree's core on `PYTHONPATH`. `.venv-tools` (git-excluded, in this worktree) holds CI's ruff 0.17.1 and mypy 2.4.0. A real-data test that skips has validated nothing: the skip count must not rise.

- **core + pure:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider -p no:xonsh`
- **qgis, the files a task touches:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src packages/nsgeo-qgis/scripts/qgis_tests.sh <files> -q -p no:cacheprovider`
- **qgis, real data:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis -m real_data -q -p no:cacheprovider -rs`
- **The whole qgis tier** runs only as `qgis_tests.sh full`, and only by the coordinator; CI runs it on 3.44 and 4.2 on every push.
- **lint:** `.venv-tools/bin/ruff check . && .venv-tools/bin/ruff format --check .`
- **types:** the mypy line in `.github/workflows/ci.yml`, run with `.venv-tools/bin/mypy` (the core's `track_fit.py` is inside `packages/nsgeo-core/src/nsgeo`, already on it).

## Review Focus

Inputs the spec implies that are most likely to bite, each pinned by a test in the task that owns the code:

1. **The site changes under an open dialog:** the target grid is removed, a grid named like the typed Name appears, or the site closes, while Add data sits on New grid with its preview. Import must refuse with the status line and leave nothing behind; the preview must leave the map when the dialog closes, however it closes. (Task 5)
2. **Import half-succeeds:** `add_grid` succeeds and `add_lines` then refuses (a CRS mismatch, a key already in the site). The new grid must be removed again, and the slice preset put back. (Task 5)
3. **A site with no CRS and no grid, project CRS in degrees:** the new grid and the lines both land in the UTM zone the CRS rule picks, and the site's CRS is pinned to it. (Task 5)
4. **Switching mode with edits in flight:** Grid-mode hand edits (offset, direction, label) survive a switch to GPS and back while the file list is unchanged; the GPS page's destagger and target survive the reverse. (Task 4)
5. **Edit lines after a GPS line changed elsewhere:** a destagger set from the Survey panel while Edit lines is open makes that row skip as changed elsewhere on OK, and every other row still applies. (Task 3)

---

### Task 1: The fit, in the core

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/geometry/track_fit.py`
- Modify: `packages/nsgeo-core/src/nsgeo/geometry/__init__.py` (export the four names below and `TrackFrame`)
- Test: `packages/nsgeo-core/tests/test_track_fit.py`, `packages/nsgeo-core/tests/test_track_fit_real_files.py`

**Interfaces:**
- Produces, in `nsgeo.geometry.track_fit` (and re-exported from `nsgeo.geometry`):
  - `ALONG_DEG = 20.0`, `MIN_VOTE_M = 1.0`
  - `main_direction(tracks: Sequence[np.ndarray]) -> float | None` — the axial azimuth in degrees, `[0, 180)`, clockwise from CRS north; None when the lines share none (§16).
  - `measure_spacing(tracks: Sequence[np.ndarray]) -> float | None` — §16's median gap; None with fewer than two along lines or no main direction.
  - `fit_frame(tracks: Sequence[np.ndarray], spacing: float) -> TrackFrame` — `ValueError` for no tracks, a track with no finite point, or `spacing <= 0`.
  - `@dataclass(frozen=True) class TrackFrame: origin: tuple[float, float]; azimuth: float; size_x: float; size_y: float; lined_up: bool` with `def as_grid(self, grid_id: str, crs: str, spacing: float) -> Grid`.
  - `metres_outside(grid: Grid, xy: np.ndarray) -> tuple[float, bool]` — (metres of trace-to-trace steps whose midpoint lies outside the rectangle, whether any trace lies inside).
- Each track is an `(n, 2)` array of world positions in the site CRS, as `Line.trace_coords(frames)` returns.

- [ ] **Step 1: Write the failing synthetic tests** in `test_track_fit.py`. A helper `zigzag(n_lines, spacing, bearing_deg, length=30.0, wobble=0.03, seed=0)` builds tracks walked alternately up and down at `bearing_deg`, each line a column of points every 0.1 m with seeded cross-wobble of `wobble` m.

```python
def test_a_zigzag_survey_is_fitted_along_its_lines():
    tracks = zigzag(12, 0.5, 30.0)
    assert main_direction(tracks) == pytest.approx(30.0, abs=0.2)
    assert measure_spacing(tracks) == pytest.approx(0.5, abs=0.01)
    frame = fit_frame(tracks, 0.5)
    assert frame.lined_up and frame.azimuth == pytest.approx(30.0, abs=0.2)
    assert frame.size_x == pytest.approx(12 * 0.5, abs=0.05)  # outer means ± half a spacing
    assert frame.size_y == pytest.approx(30.0, abs=0.05)
    grid = frame.as_grid("G", "EPSG:32632", 0.5)
    local = np.vstack([grid.to_local(t) for t in tracks])
    assert local[:, 1].min() >= -1e-9 and local[:, 1].max() <= grid.size_y + 1e-9


def test_reversed_lines_and_a_bearing_past_90_fold_to_one_azimuth():
    assert main_direction(zigzag(6, 0.5, 170.0)) == pytest.approx(170.0, abs=0.2)
    assert fit_frame(zigzag(6, 0.5, 170.0), 0.5).azimuth == pytest.approx(350.0, abs=0.2)


def test_one_line_has_no_spacing_and_a_typed_one_makes_it_one_spacing_wide():
    tracks = zigzag(1, 0.5, 10.0)
    assert measure_spacing(tracks) is None
    assert fit_frame(tracks, 0.8).size_x == pytest.approx(0.8, abs=1e-6)


def test_lines_in_every_direction_get_the_smallest_rectangle():
    tracks = zigzag(6, 0.5, 0.0) + zigzag(6, 0.5, 90.0)  # equal lengths, crossing
    assert main_direction(tracks) is None and measure_spacing(tracks) is None
    frame = fit_frame(tracks, 0.5)
    assert not frame.lined_up
    # every trace inside, half a spacing in from each side at the tightest
    ...


def test_short_lines_do_not_vote_and_a_cross_line_is_held_inside(): ...  # 10 along lines + one 1.5 m line at 60°: direction unchanged; frame holds the cross line


def test_metres_outside_counts_only_the_steps_outside():
    grid = Grid("G", (0.0, 0.0), 0.0, 10.0, 10.0, "EPSG:32632", 0.5)
    inside_then_out = np.column_stack([np.full(201, 5.0), np.linspace(0.0, 20.0, 201)])
    metres, any_in = metres_outside(grid, inside_then_out)
    assert metres == pytest.approx(10.0, abs=0.1) and any_in
    assert metres_outside(grid, inside_then_out + [30.0, 0.0]) == (
        pytest.approx(20.0, abs=0.1),
        False,
    )
```

Fill in the two elided bodies with assertions that pin the stated behaviour (every trace inside; the azimuth of the along lines unchanged by the short and cross lines).

- [ ] **Step 2: Run them to see them fail** (`ModuleNotFoundError: nsgeo.geometry.track_fit`).
- [ ] **Step 3: Implement `track_fit.py`** to §16 of the spec.
  - Direction per track: last finite point minus first; tracks with a chord under `MIN_VOTE_M` do not vote. Axial mean: mean of `(cos 2θ, sin 2θ)` weighted by chord length, halved back; θ measured as azimuth (`atan2(dx, dy)`).
  - Along: within `ALONG_DEG` of the mean. A main direction exists when the along chords sum to more than half of all chords (one voting track always does; an even 50/50 cross-hatch has none).
  - Spacing: each along track's mean position across the main direction, sorted; the median of consecutive differences.
  - Frame, lined up: rotate into (cross, along); along extent = every trace; cross extent = outer along means ∓ `spacing / 2`, widened to hold every trace of a track that is not along. Fold the azimuth so +Y follows the main direction with azimuth in `(-90, 90]`, stored `% 360`. Origin = the world position of local (0, 0).
  - Frame, no main direction: convex hull (monotone chain) of every trace, the minimum-area rectangle over hull-edge angles, grown by `spacing / 2` on all sides, +Y along the longer side, azimuth folded the same way.
  - `metres_outside`: `grid.to_local`, step midpoints outside `[0, size_x] × [0, size_y]` summed by step length; `any_in` from the traces themselves.
- [ ] **Step 4: Run the synthetic tests to pass.**
- [ ] **Step 5: Write the real-data tests** in `test_track_fit_real_files.py`, skipping when `GPS_LINES` / `GRID2_LINES` is empty (reason naming `tests/data/local`, so the `real_data` mark applies). Project every line of a survey with one shared `tests.dzg_data.local_xy` about the first file's first RTK fix, read at run time.

```python
@pytest.mark.skipif(not GPS_LINES, reason="no real GPS survey in tests/data/local")
def test_the_first_survey_fits_along_its_sixty_lines():
    tracks = survey_tracks(GPS_LINES)
    assert len(tracks) == 60
    assert main_direction(tracks) == pytest.approx(3.8, abs=0.5)  # spec §2: bearing 3.8°
    s = measure_spacing(tracks)
    assert s == pytest.approx(0.496, abs=0.01)  # spec §2: 0.496 m by GPS
    frame = fit_frame(tracks, s)
    assert frame.lined_up and frame.size_x == pytest.approx(60 * s, abs=0.3)
    grid = frame.as_grid("G", "LOCAL", s)
    inside = np.mean(np.vstack([inside_mask(grid, t) for t in tracks]))
    assert inside >= 0.99
    cube = CubeFrame.for_grid(grid, s)
    assert covered_cells(cube, tracks) / cube_cell_count(cube) >= 0.9


@pytest.mark.skipif(not GRID2_LINES, reason="no real second survey in tests/data/local")
def test_the_second_survey_fits_too(): ...  # main direction exists, 0.45 < spacing < 0.55, lined up, ≥ 99 % of traces inside
```

`inside_mask` and `cube_cell_count` are small helpers in the test file (`cube_cell_count` reads the frame's cell grid size; see `nsgeo.slices.frame.CubeFrame`).
- [ ] **Step 6: Run the real-data tests locally; they must pass, not skip.** Then core + pure, lint and types.
- [ ] **Step 7: Commit and push** (`feat(core): fit a grid to GPS tracks (M17b, #134)`).

---

### Task 2: GPS lines in grids: the session, the map and the Survey panel

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/line_edit.py` (add `TrackEdit`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py` (`edit_lines`, `move_lines`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/layers.py` (GPS lines' `grid_id` field; `_hide_when_lines_crowd`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/survey_dock.py` (menus)
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_line_edit.py` (or the existing pure line-edit test file), `tests/qgis/test_plugin_session_gps_grids.py` (new), `tests/qgis/test_plugin_layers_gps.py`, `tests/qgis/test_plugin_survey_dock.py`

**Interfaces:**
- Consumes: `measure_spacing` (Task 1).
- Produces, in `line_edit.py`:

```python
@dataclass(frozen=True)
class TrackEdit:
    """A GPS line's requested change against the placement the table saw. None: unchanged.
    Only the grid, label and destagger can change; the track never moves (C3)."""

    key: str
    seen: TrackPlacement
    label: str | None = None
    grid_id: str | None = None
    travel_shift: float | None = None

    def placed(
        self, frames: Mapping[str, Grid]
    ) -> TrackPlacement: ...  # KeyError for a grid not in frames
    def moved_to(self, grid_id: str, frames: Mapping[str, Grid]) -> TrackEdit: ...
    def changes(self, frames: Mapping[str, Grid]) -> bool: ...
```

- `SiteSession.edit_lines(edits: Sequence[LineEdit | TrackEdit], *, grid_id=None, order=None) -> EditOutcome` — unchanged contract; a `TrackEdit` is checked against a `TrackPlacement` the same way (`REMOVED`, `CHANGED_ELSEWHERE`, a new grid gone). A GPS line that changes grid leaves the old grid's remembered slice lines and joins the end of the survey order, as a tape line does.
- `SiteSession.move_lines(keys, grid_id)` moves GPS lines too (a `TrackEdit` with only `grid_id`), including GPS lines in no grid.
- `SurveyDock.fit_tracks_requested = pyqtSignal(list)` (keys) — connected in Task 6; until then connect it in `plugin.py` to a stub that does nothing but log, so `test_no_orphan_signals` passes. Task 6 replaces the stub.

- [ ] **Step 1: Write the failing tests.**
  - Pure: `TrackEdit(key, seen).placed(frames) == seen`; `grid_id="B"` gives `seen` with `grid_id="B"` and identical fixes; a grid missing from `frames` raises `KeyError`; `travel_shift=0.3` and `label="x"` apply; `changes` is False for an empty edit.
  - Session (`test_plugin_session_gps_grids.py`, built with `plugin_testing.gps_line` / `open_gps(..., grid_id=…)`):
    - `move_lines([gps_key], "B")` moves a GPS line from grid A to B, and a GPS line in no grid into B: `grid_id` changes, `trace_coords` are byte-identical before and after, one `lines_changed`, dirty, and A's remembered slice `lines` no longer names it.
    - A mixed `move_lines` (one tape, one GPS) moves both in one change.
    - `edit_lines([TrackEdit(...)])` after the line's destagger changed elsewhere skips it as `CHANGED_ELSEWHERE`, and a tape edit in the same call still applies.
    - `replace_grid` with a moved and resized grid leaves a GPS line's `trace_coords` unchanged (C13).
    - `remove_grid(…, with_lines=True)` takes the grid's GPS lines with it.
    - A GPS line with `grid_id="A"` is in `keys_on_grid("A")`, sits under grid A in the Survey panel's tree, and is in the line keys of grid A's default slice source (`export.source_choice("A", export.defaults("A")).line_keys`, with `export` a `ParaViewExport` built as the existing ParaView export tests build it; the source the 3-D view and the export read).
    - Profiles stay in distance walked until M17d: `ProfileDock._ruler_for` returns None for a GPS line in grid A, and the ruler of a tape line on grid A is built without the GPS line.
  - Layers: a GPS line with `grid_id="A"` writes `grid_id = "A"` in the `lines` table (so it takes grid A's colour); one with none still writes `""`. Lines layer zoom-out hiding: a site with only GPS lines in no grid, walked 0.5 m apart, gets scale-based visibility at `HIDE_LINES_BEYOND_SCALE_PER_M * measure_spacing(...)` (#222); a GPS line in a grid uses the grid's `default_spacing`.
  - Survey panel: a GPS line's menu reads `Open`, `Set velocity override…`, `Set destagger…`, `Move to grid ▸`, `Fit a grid to this track…`, separator, `Remove line from site`; a GPS-only selection adds `Move {phrase} to grid ▸` and `Fit a grid to these {n} tracks…`; a mixed selection on one grid gets `Edit {phrase}…` and `Move {phrase} to grid ▸`; the grid menu reads `Add GPR data…` where `Import DZT files…` was. Choosing a grid in the GPS line's Move menu moves it (through `session.move_lines`).
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.** `TrackEdit` in `line_edit.py` (pure, on the mypy list already). In `session.edit_lines`, branch on the edit type; `applied` holds either placement kind; the "moved" bookkeeping reads `grid_id` from either (a GPS line may come from `None`). `move_lines` builds a `TrackEdit` for a `TrackPlacement` whose `grid_id` differs. In `layers.py`, `f["grid_id"] = p.grid_id or ""` for GPS lines; `_hide_when_lines_crowd` adds `measure_spacing` of the GPS lines in no grid (their `trace_coords({})`) when there are two or more, and ignores it when None. In `survey_dock.py`, follow the copy above; the GPS-only and mixed branches reuse `_add_move_menu`; `Fit a grid…` emits `fit_tracks_requested(keys)`. Move to grid ▸ for a GPS line in no grid enables every grid (none is "already on").
- [ ] **Step 4: Run the tests to pass**, plus `test_plugin_layers.py`, `test_plugin_layers_gps.py`, `test_plugin_survey_dock.py`, `test_plugin_line_selection.py`, `test_plugin_session*.py` and the pure tier.
- [ ] **Step 5: Commit and push** (`feat(m17b): GPS lines move between grids and take their grid's colour; Survey panel menus (#134, #222)`).

---

### Task 3: GPS rows in Edit lines

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/edit_lines_dialog.py`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_edit_lines_gps.py` (new); the existing Edit lines test files must still pass.

**Interfaces:**
- Consumes: `TrackEdit` and the `edit_lines` contract (Task 2).
- Produces: `EditLinesDialog.edit_for(key) -> LineEdit | TrackEdit`; `GPS_SKIP = "Left {n} GPS line(s) alone: {what} applies to tape lines only."` as a module constant.

- [ ] **Step 1: Write the failing tests** on a grid holding three tape lines and two GPS lines (`open_gps(..., grid_id="A")`):
  - The table lists all five in survey order. A GPS row's Offset, Dir, Start and Scale cells read `—`, are not editable and carry the copy's tooltip; Along reads `GPS`; Traces, Length (walked), Picks are filled.
  - Editing a GPS row's Label and Destagger, then OK, changes only those fields (`trace_coords` before/after differ only by the destagger's shift along the track).
  - Choosing another grid in a GPS row's Grid cell, then OK, moves it with its track unchanged.
  - Bulk Offset step, Flip, Start, Scale, Fit to grid edges on a selection of two tape and one GPS line: the tape rows change, the GPS row does not, and the status line reads `GPS_SKIP` with `n=1` and the right `{what}`. Bulk Destagger and Move to grid apply to all three.
  - Measure with GPS rows selected measures the tape rows only and says `GPS_SKIP` with `what="Measure"` (use the existing Measure test helpers; a GPS row is never handed to `destagger_job`).
  - Review Focus 5: with the dialog open, `session.set_travel_shift([gps_key], 0.2)`; OK skips that row as changed elsewhere (named on the status line, as for a tape row) and applies the rest.
  - Moving a GPS row up or down changes the survey order like a tape row's.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.** Rows for `TrackPlacement` lines hold a `TrackEdit`. Every method that reads `placed(frames).offset/direction/start_along/scale/axis` branches on the edit type: render (`—`, read-only, tooltip), `_item_changed` (only Label, Destagger, Grid reach a `TrackEdit`), `_apply` callers for Offset/Dir/Start/Scale/Fit/Snap (skip and count GPS rows, then `_say(GPS_SKIP…)`), `set_destagger` and `move_to` (apply to both), `_measure_snapshot` (tape rows only), `_counts` and the dirty-cell colouring (compare a `TrackEdit` with `changes`). `Along` reads `GPS` for a GPS row; the header's axis summary ignores GPS rows.
- [ ] **Step 4: Run the new file and every `test_plugin_edit_lines*.py` file to pass**; lint, types.
- [ ] **Step 5: Commit and push** (`feat(m17b): GPS rows in Edit lines: label, destagger and grid (#134)`).

---

### Task 4: The Add data dialog: one dialog, two pages, the switch

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/add_data_dialog.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/import_dialog.py` (`ImportDialog(QDialog)` becomes `GridImportPage(QWidget)`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/gps_import_dialog.py` (`GpsImportDialog(QDialog)` becomes `GpsImportPage(QWidget)`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/gps_import.py` (`count_with_gps`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (toolbar button, `open_add_data_dialog`, the Survey shortcut, messages; remove `open_import_dialog`, `open_gps_import_dialog`, `_import_from_toolbar`'s old target, `act_import`, `act_import_gps`)
- Modify: `docs/guide/getting-started.md` and any other doc that names `Import DZT…` or `Import GPS lines…` (grep `docs/` and both package READMEs)
- Test: migrate `tests/qgis/test_plugin_import_dialog.py` and `tests/qgis/test_plugin_gps_import_dialog.py` to the new classes; new `tests/qgis/test_plugin_add_data_dialog.py`; `tests/pure/test_pure_gps_import.py`; `tests/qgis/test_plugin_panels_menu.py` (its tuple of toolbar actions).

**Interfaces:**
- Produces, in `ui/add_data_dialog.py`:

```python
GRID, GPS = "grid", "gps"
MODE_KEY = "nsgeo/addDataMode"  # QgsSettings; absent means GRID (decision 15: Grid the first time)


class AddDataDialog(QDialog):
    imported = pyqtSignal(list)  # list[tuple[str, bool]]: (text, is_warning), one batch per Import

    def __init__(
        self,
        session: SiteSession,
        *,
        grid_id: str | None = None,
        mode: str | None = None,
        canvas: QgsMapCanvas | None = None,
        parent: QWidget | None = None,
    ) -> None: ...

    grid_page: GridImportPage
    gps_page: GpsImportPage
    grid_button: QPushButton
    gps_button: QPushButton
    gps_note: QLabel
    import_button: QPushButton

    def mode(self) -> str: ...
    def set_mode(self, mode: str) -> None: ...  # carries the file list across (below)
    def add_files(self, paths: list[Path]) -> None: ...  # to the current page
    def retarget(
        self, grid_id: str
    ) -> None: ...  # the current page's target, only while it has no files
    def accept(self) -> None: ...  # current page's import_lines(); closes when it returns True


def opening_mode(session: SiteSession, grid_id: str | None) -> str:
    ...
    # decision 15: a grid whose lines are all GPS → GPS, all tape → GRID; else (no grid, empty, mixed) the remembered mode
```

- Each page is a `QWidget` with: `changed = pyqtSignal()` (title, button text or enabled state may have moved); `title() -> str`; `import_text() -> str`; `can_import() -> bool`; `paths() -> list[Path]`; `set_files(paths: list[Path]) -> None` (keeps the rows of paths it already has, with their edits; drops the others; plans the new ones; no-op when equal); `import_lines() -> bool` (the old `accept` body; True once lines were added); `messages: list[tuple[str, bool]]` (what the last `import_lines` has to say); `status: QLabel`; `preset_box`. Every existing public attribute and method of the two dialogs keeps its name on its page (`grid_combo`, `rows`, `table`, `add_files`, `set_offset`, `shift`, `crs_label`, …).
- `gps_import.count_with_gps(paths: Sequence[Path]) -> int` — files whose DZG holds at least one RTK fix with a position (`first_fixed_lonlat(p) is not None`).
- `plugin.open_add_data_dialog(grid_id: str | None = None, mode: str | None = None) -> None` — single-instance and modeless, `open_grid_dialog`'s shape (`finished` cleans up, `destroyed` guard). The toolbar's `GPR…` opens it on the Survey panel's `target_grid_id()` in the remembered mode; the Survey shortcut opens it on that grid in `opening_mode(session, gid)`; an open dialog is raised, retargeted (only while its current page has no files) and switched to the asked mode. `imported` batches go to `self.message`, the first of each batch Info, the rest Warning when flagged.
- `AddDataDialog.accept` writes `MODE_KEY` = the mode Import succeeded in.

- [ ] **Step 1: Migrate the two dialog test files first** so they drive the pages through an `AddDataDialog` (helpers `grid_dialog(session, grid_id="A")` and `gps_dialog(session)` returning the dialog; tests reach `d.grid_page` / `d.gps_page` and call `d.accept()`). Their assertions stay as they are, except the window title and the button texts, which follow the copy. Run them to see them fail (the classes do not exist yet).
- [ ] **Step 2: Write the new tests** in `test_plugin_add_data_dialog.py` and `test_pure_gps_import.py`:
  - The switch: Grid checked first with no `MODE_KEY`; `set_mode(GPS)` shows the GPS page, hides `gps_note`, retitles; the `Grid` / `GPS` buttons are exclusive.
  - Carrying files: three files added in Grid mode with one offset typed and one direction flipped → switch to GPS → the GPS page lists the same three paths → switch back → the typed offset and flipped direction are still there (Review Focus 4). Removing one file in GPS mode and switching back drops it from the Grid page and keeps the other rows' edits.
  - The note: two of three files with a usable DZG → `"2 of 3 files have a GPS log beside them."`; a DZG with no RTK fix does not count; none → hidden; one file with one → `"This file has a GPS log beside it."`; never shown in GPS mode. `count_with_gps` pinned in the pure tier.
  - No grid: in Grid mode on a grid-free site the status reads the copy and Import is disabled; GPS mode is still offered.
  - Mode memory: a successful Grid import writes `grid`; a GPS import writes `gps`; Cancel writes nothing. `opening_mode` for an all-GPS grid, an all-tape grid, an empty grid and a mixed grid (the last two take the remembered mode). Restore `MODE_KEY` after each test.
  - Plugin: the toolbar has an `Add data` button whose menu holds `GPR…`, in the place of the two import actions, greyed until a site opens; `GPR…` opens one dialog and a second press raises it; the Survey panel's `Add GPR data…` opens it on that grid; `imported` batches reach the message bar; the dialog finishing clears `plugin._add_data_dialog`; a dialog destroyed without `finished` is cleared too (port the two lifecycle tests the old dialogs had).
- [ ] **Step 3: Run them to see them fail.**
- [ ] **Step 4: Implement.** Move each dialog's body into its page unchanged apart from: no title of its own (`title()`), no button box (`import_text()`, `can_import()`, `changed`), `accept` → `import_lines()`, and `messages` filled where the plugin used to read `imported_keys`/`preset_notice`/`messages`. The dialog stacks the pages in a `QStackedWidget` under the switch row, puts the shared footer (the current page's `status` stays inside the page; the dialog's button box at the bottom) and forwards `changed` to its title and button. `GpsImportPage` keeps M17a's behaviour exactly in this task (no grid yet; Task 5 adds it). The toolbar button copies the Panels ▾ pattern (`QToolButton`, `InstantPopup`, `toolbar.addWidget`) at the old actions' position; put its action into `_update_enabled`'s site-open tuple in their place. Update the guide's toolbar table and Step 3 / Step 3a.
- [ ] **Step 5: Run** the three dialog test files, `test_plugin_panels_menu.py`, `test_plugin_survey_dock.py`, the pure tier (boundary and orphan-signal tests included), lint and types.
- [ ] **Step 6: Commit and push** (`feat(m17b): Add data ▾ ▸ GPR…, one dialog with a Grid / GPS switch (#134)`).

---

### Task 5: GPS lines into a grid: existing or new, with the preview

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/gps_import_dialog.py` (`GpsImportPage`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/gps_import.py` (`with_grid`, `import_messages`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/preset_box.py` (`set_grid(..., new=True)`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/add_data_dialog.py` (the preview)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (pass the canvas; dispose the preview in `finished` and the `destroyed` guard, as `open_grid_dialog` does with its overlay)
- Modify: `docs/guide/getting-started.md` (Step 3a: into a grid, new or existing)
- Test: `tests/pure/test_pure_gps_import.py`, `tests/qgis/test_plugin_gps_import_dialog.py`, `tests/qgis/test_plugin_add_data_dialog.py`, `tests/qgis/test_plugin_preset_box.py`

**Interfaces:**
- Consumes: `fit_frame`, `measure_spacing`, `main_direction`, `metres_outside`, `TrackFrame.as_grid` (Task 1); the pages and `AddDataDialog` (Task 4).
- Produces:
  - `gps_import.OUTSIDE = "outside {gid}"`; `with_grid(rows: Sequence[GpsRow], grid: Grid) -> tuple[list[GpsRow], dict[Path, float]]` — rows whose ready line has no trace inside the grid become refused `OUTSIDE`; the dict holds metres outside per remaining ready row.
  - `import_messages(rows, imported, *, into: str, outside: Mapping[Path, float] = {}, handed_on: Collection[Path] = ()) -> list[str]` — `into` is `"new grid {gid} ({w:.1f} × {l:.1f} m, spacing {s:.2f} m)"` or `"{gid}"`; refused rows in `handed_on` are not listed as "not imported".
  - `GpsImportPage.target() -> str | None` (None for New grid); `GpsImportPage.proposal() -> Grid | None` (the grid Import would make, from the ready rows, or None while it cannot); `GpsImportPage.last_import: GpsImportResult | None` with `@dataclass(frozen=True) class GpsImportResult: grid_id: str; order: list[Path]; placed: dict[Path, np.ndarray]; leftovers: list[Path]` (`order`: every path the page held at Import, in its order; `placed`: each imported line's `trace_coords`; `leftovers`: refused paths whose refusal is neither `ALREADY_IN_SITE` nor `OUTSIDE`, in file order) — read by Task 6.
  - `PresetBox.set_grid(grid_id: str | None, *, new: bool = False)` — `new=True`: starts on the site's last choice, and the Slices note shows for any chosen preset with `{grid}` = `grid_id or "The new grid"`.

- [ ] **Step 1: Write the failing tests.** Synthetic surveys: `gps_file(folder, name, lon=LON0 + k * dlon)` with `dlon` putting lines 0.5 m apart, alternate files walked south (reverse the fix order).
  - Pure: `with_grid` refuses a line wholly outside and reports 3.0 m for one that runs 3 m past the grid's end; `import_messages` with `into` for both forms, an outside warning, and a handed-on refusal left out.
  - New grid: eight files → Target grid starts on `New grid` on a grid-free site; Name empty → Import disabled, status `"Name the new grid."`; Name `"G4"` → Spacing shows 0.500 with the measured note; Fitted reads the copy with `4.0 × 20.0 m` (or the synthetic survey's sizes); typing 0.6 sticks through adding a file; Import makes grid `G4` (`default_spacing` 0.6, `crs` the site's) and eight lines with `grid_id="G4"`; messages start with the new-grid copy.
  - A name already used → `"A grid named {name} already exists."`, Import disabled; a grid with the typed name added elsewhere after typing → Import refuses on the status line and adds nothing (Review Focus 1).
  - One file → Spacing `—` with the one-line note, Import disabled until a spacing is typed, then a grid one spacing wide.
  - Two crossing sets of four lines (north and east) → Spacing `—` with the no-direction note, and once typed, Fitted reads the smallest-rectangle copy.
  - Existing grid: the `Outside {gid}` column, amber metres, a wholly outside line red with `outside {gid}`; Import adds the ready lines with that `grid_id`; the grid itself is unchanged.
  - The preset: New grid with a preset chosen shows `"G4's first lines: this becomes its Slices preset too."`; after Import the grid's Slices preset is that preset and every new line carries it; the import preset is remembered for `G4`.
  - Review Focus 2: monkeypatch `session.add_lines` to raise `ValueError` → no grid `G4` remains, no slice source for it, the status shows the message.
  - Review Focus 3: grid-free site with no CRS, project in EPSG:4326 → the new grid's `crs` and the site's CRS are the picked UTM zone, and the lines are placed in it.
  - The preview (`AddDataDialog` with `iface.mapCanvas()`): while on New grid with ready rows its overlay's `grid` holds four corners equal to `proposal()`'s corners transformed to the canvas CRS; switching Target grid to an existing grid or to Grid mode clears it; the dialog finishing (accept, reject, close) disposes it; the target grid removed or the site closed under the dialog makes Import refuse with the status line (Review Focus 1).
  - Real data (skip on missing `GPS_LINES`, reason naming `tests/data/local`): the sixty lines into a new grid → 60 lines on it, its spacing within 0.01 of 0.496, every line's traces ≥ 99 % inside it.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.** The Target grid combo (`New grid`, data `""`, then the grids) with Name / Spacing / Fitted rows shown only for New grid (hide label and field together; `QFormLayout.setRowVisible` does not exist on Qt 5). Spacing is a `QDoubleSpinBox` (0.000–100.000, 3 decimals, `setSpecialValueText("—")` at 0) that follows the measurement until the user types (`_spacing_own`, like Grid mode's `_first_offset_own`). Replan on files, target and spacing changes: `with_grid` for an existing target; `measure_spacing` / `fit_frame` on the ready rows for New grid. Import, in this order, after M17a's re-checks: name checks; for a site with no CRS, `set_site_crs`; `add_grid(proposal)` for New grid; Slices preset rule (`import_sets_slice_preset` / `set_slice_preset`) for the target; lines with `grid_id` set (`dataclasses.replace` on each placement); `add_lines`; on its `ValueError`, put the slice preset back and `remove_grid` the new grid, then report. Then preset applied, remembered per grid, `last_import` filled, and `messages = [(text, i > 0) for i, text in enumerate(import_messages(...))]` (the count is news, the rest warnings, as M17a's plugin showed them). The preview: the dialog owns one `GridOverlay` when given a canvas, sets `set_grid(corners)` from `gps_page.proposal()` on every `changed` while in GPS mode on New grid, else `set_grid(None)`; corners in the canvas CRS through a `QgsCoordinateTransform` from the site CRS.
- [ ] **Step 4: Run the touched test files and the real-data tier to pass**; lint, types.
- [ ] **Step 5: Commit and push** (`feat(m17b): GPS lines into an existing grid or a new one fitted around them, with a map preview (#134)`).

---

### Task 6: Files GPS cannot place, and Fit to these tracks

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/gps_import.py` (`TapeGuess`, `guess_tape_rows`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/lookup.py` (`ImportRow.guess`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/import_dialog.py` (`GridImportPage.hand_on`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/add_data_dialog.py` (after a GPS import with leftovers)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/grid_dialog.py` (`proposed`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (`open_grid_dialog(..., proposed=, move_keys=)`; the `fit_tracks_requested` slot replacing Task 2's stub)
- Modify: `docs/guide/getting-started.md` (the hand-on; Fit to these tracks)
- Test: `tests/pure/test_pure_gps_import.py`, `tests/qgis/test_plugin_add_data_dialog.py`, `tests/qgis/test_plugin_grid_dialog.py` (or the existing grid dialog test file), `tests/qgis/test_plugin_survey_dock.py`

**Interfaces:**
- Consumes: `GpsImportResult` (Task 5), `fit_frame` / `measure_spacing` (Task 1), `fit_tracks_requested` (Task 2), `session.move_lines` for GPS lines (Task 2).
- Produces:
  - `@dataclass(frozen=True) class TapeGuess: axis: str; offset: float; direction: int; note: str`
  - `guess_tape_rows(order: Sequence[Path], placed: Mapping[Path, np.ndarray], grid: Grid) -> dict[Path, TapeGuess]` — §16's rule: for each path in `order` not in `placed`, interpolate the offset by file position between the nearest placed paths before and after it; at an end, `grid.default_spacing` per file further on, away from the placed line before it (or `+` when there is only one placed line); direction opposite the line before it in file order (placed or guessed), or opposite the line after it for the first file; omitted unless every neighbour used runs within `ALONG_DEG` of the same grid axis. A placed line's offset is its mean local cross coordinate (local x for axis `y`, local y for axis `x`); its direction is the sign of its local along change.
  - `ImportRow.guess: str = ""` — the guess note; non-empty means the row's offset and direction are a guess the user has not changed. `set_offset` / `set_direction` clear it.
  - `GridImportPage.hand_on(paths: Sequence[Path], grid_id: str, guesses: Mapping[Path, TapeGuess], *, n_placed: int) -> None` — replaces the rows with `paths` planned on `grid_id`, sets the axis to the guesses' (the most common, when they differ; rows of the other axis lose their guess), applies each guess as edited offset and direction with its `guess`, shows the hand-on banner (`n_placed` is the GPS line count for its first sentence), and hides the Direction and First line at rows until the page's next Import or the dialog closes.
  - `GridDialog(session, grid=None, parent=None, canvas=None, *, proposed: Grid | None = None)` — fills every field from `proposed` except Id, which stays empty and editable.
  - `plugin.open_grid_dialog(grid_id: str | None, *, proposed: Grid | None = None, move_keys: Sequence[str] = ()) -> None` — after OK on a new grid, `session.move_lines(move_keys, new_id)` and the copy's message (plus any skipped lines, as Edit lines names them).

- [ ] **Step 1: Write the failing tests.**
  - Pure `guess_tape_rows`, on a synthetic grid with azimuth 0 and lines along +Y at 0.25, 0.75, …: a gap between two placed lines gets the midpoint and `"between FILE__303 and FILE__305"`; two leftovers in a row interpolate by file position; a leftover after the last placed line gets one spacing on and `"1 spacing after FILE__309"`; the first file gets `"1 spacing before FILE__302"`; directions alternate from the neighbour before (zigzag); neighbours at 45° to both axes → no guess; lines along X → axis `x` with offsets in local y.
  - Hand-on (`AddDataDialog`, synthetic survey of ten files where files 4 and 7 have no DZG): GPS mode, New grid `G4`, Import → `G4` holds eight GPS lines, the dialog is still open, in Grid mode, on `G4`, with two rows whose offsets and directions match the guesses, amber Offset and Dir cells, the notes in the Note column, the banner's copy, Direction and First line at hidden; the `imported` signal carried the GPS summary without listing files 4 and 7 as not imported. Import → two tape lines on `G4`, the dialog closes. Cancel instead → nothing more added, and the GPS lines stay.
  - Editing a guessed row's offset clears its amber and its note.
  - A refused `already in the site` file is not handed on; when every refusal is of that kind the dialog closes after the GPS Import as before.
  - `GridDialog(proposed=…)`: the fields read the proposal's origin, azimuth, size and spacing, Id is empty and editable, OK is disabled until an Id is typed.
  - Fit to these tracks: three unattached GPS lines selected → `Fit a grid to these 3 tracks…` opens the grid dialog with the fitted proposal; typing an Id and OK adds the grid and moves the three lines into it (tracks unchanged), with the copy's message; Cancel adds and moves nothing. One line → the proposal's spacing is the grid dialog's default and its width one spacing.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** to the interfaces above. In `AddDataDialog.accept`, when the GPS page's `import_lines()` returns True and `last_import.leftovers` is non-empty: emit `imported`, call `grid_page.hand_on(last_import.leftovers, last_import.grid_id, guess_tape_rows(last_import.order, last_import.placed, session.grid(last_import.grid_id)), n_placed=len(last_import.placed))`, clear the GPS page's files, `set_mode(GRID)` without carrying files, and stay open. The Grid page's amber uses Add data's GPS colours (`FLAG_BG`, `FLAG_FG`). `GridDialog._prefill` gains the `proposed` path (Id left alone). The plugin's `fit_tracks_requested` slot builds the proposal from the lines' `trace_coords` (`measure_spacing`, else the grid dialog's default spacing) in the site CRS and calls `open_grid_dialog(None, proposed=…, move_keys=keys)`.
- [ ] **Step 4: Run the touched files, the pure tier and the real-data tier to pass**; lint, types.
- [ ] **Step 5: Commit and push** (`feat(m17b): files GPS cannot place are handed on to Grid mode with a guess; Fit a grid to these tracks (#134)`).

---

## After the tasks

- The coordinator runs `qgis_tests.sh full` once, reads CI on both QGIS versions, merges main if it moved, and builds the walkthrough (spec §11, M17b) on its own QGIS profile `ns_geo_m17b`, deployed with `scripts/dev_link.py`. The walkthrough's checks: Add data ▾ ▸ GPR… with GPS on the sixty lines into a new grid (the rectangle lined up with the lines, half a spacing outside the outer ones; slices of it); the second survey into an existing grid with a line partly outside named in the summary; a tape import through the same dialog with its GPS note and no marker anywhere after; a hand-on of files with their DZG hidden; M17a's unattached lines moved into a grid, and a grid fitted around others; Edit lines with GPS rows; editing the grid leaves its GPS lines in place; the toolbar and Survey panel copy.
- Merging waits for the user's go after the walkthrough.
