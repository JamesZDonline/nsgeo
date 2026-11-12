# Measure the Destagger Implementation Plan (#159)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every code task is written test-first with superpowers:test-driven-development: the failing test is run and seen to fail before any production code is written.

**Goal:** A **Measure** button in Edit lines that works out, from the grid's own data, the destagger every line shares and the lines that need their own value, and fills them in as pending edits.

**Architecture:**
- A new public core package, `nsgeo.destagger`, uses numpy only, with no Qt.
  - It prepares each line once: dewow, background removal, envelope, 8-sample time bins.
  - From the prepared lines and their current placements, it measures a grid value per axis (the spike's method) and per-line values with a status for each line.
- In the plugin, a Qt-free `nsgeo_qgis/destagger_job.py` reads the files and runs the measurement on the existing `Refiner` worker thread. It also words the status line.
- `EditLinesDialog` gains the button, a snapshot check, a cache of prepared lines, and cancel on close.

**Tech Stack:** Python ≥ 3.9 and numpy (core); PyQt via `qgis.PyQt` (plugin); pytest on two tiers (core+pure, QGIS).

**Spec:** `docs/superpowers/specs/2026-11-11-nsgeo-auto-destagger-design.md` (approved 2026-11-11). Read it first, then the spike note `docs/superpowers/notes/2026-11-11-destagger-measure-spike.md`, including its **Per-line prototype** section. The spec's calls are cited as C1–C14. This plan's own calls are numbered P1–P12 and cited as `(destagger plan, P<n>)`.

## Plan calls (Claude's; check while reading)

- **P1 — module and names.** The core code lives in the package `nsgeo/destagger/`. `__init__.py` re-exports the public names, and the code is in `prepare.py`, `profiles.py`, `measure.py` and `per_line.py`. `destagger` joins `EXPECTED_PUBLIC` in `test_public_api.py`, and the core README names every public name.
- **P2 — time settings.** Every line on an axis must share the most common bin `dt_ns` and `t0_ns` (within 1e-6). A line that differs is *not measured*, with the reason `recorded with different time settings from the rest of the grid`. Lines with different record lengths are cut to the shortest common bin count.
- **P3 — too short.** A line whose placed length, less the two 2 m end trims, is under 2 m is *not measured*, with the reason `too short to measure`.
- **P4 — multi-channel files** are measured on their first channel (`read_samples(...)[0]`), as the spike did.
- **P5 — per-line values round to 0.001 m** when they land in the table, the precision of the Destagger box.
- **P6 — the rows filled** are the rows selected when Measure was pressed. They exclude rows whose Grid cell now names another grid. The status line describes only those rows, plus the grid value.
- **P7 — the worker** is the existing `nsgeo_qgis.refine.Refiner` (one thread, generation-checked, results drained on the GUI thread), one per dialog. It is not a `QgsTask`. The job does no Qt and no session work, and the Refiner already handles its traps (C9).
- **P8 — the panel stays reachable.** While a measure runs, the bulk panel stays enabled even with no selection, so **Stop** can always be pressed. With no selection, the other bulk buttons do nothing.
- **P9 — the skew test** (spec §10, "an injected skew is ignored") cannot hold literally: real Grid 1 already has a few own values without any skew. It is tested as "the skew creates and removes no own value 0.20 m or more from the grid value, own values present in both runs differ by at most 0.03 m, and the grid value moves by less than 0.01 m".
- **P10 — two adjacent injected errors** use +0.30 m on two neighbouring lines, as when two lines were both started off the baseline. Each must be within 0.05 m. Large opposite moves on neighbours (−0.50 beside +0.30) are a known weak case of the prototype. They are reported at the C14 checkpoint, not pinned.
- **P11 — tolerances the spec did not give** are pinned by the Task 2 builder from the data:
  - the Grid 2 own values' size;
  - the share of lines keeping the grid value (spec: about 80% or more on Grid 1; at least 70% on Grid 2);
  - the thresholds.

  A spec tolerance that cannot be met (the −0.50 single-line case is the likeliest) is never loosened in a test. The task reports `DONE_WITH_CONCERNS`, and the coordinator takes it to the author at C14.
- **P12 — the summary names at most 6 lines per group**, then `and {n} more`.

## Global Constraints

- **Core:** numpy only (no scipy), runtime Python 3.9: no `zip(strict=)`, no `match`, no PEP 604 unions outside annotations. `from __future__ import annotations` heads every new file.
- **Plugin:**
  - `nsgeo_qgis/destagger_job.py` and `nsgeo_qgis/line_edit.py` import no Qt and no `qgis`. Add `destagger_job.py` to the mypy list in `.github/workflows/ci.yml` and in the types command below.
  - Qt only through `qgis.PyQt`. `tests/pure/test_plugin_boundary.py` and `test_no_orphan_signals.py` stay green.
  - Every Qt slot guards its own body and ends in `except Exception as exc: self._failed(exc)`, the pattern `EditLinesDialog` already uses.
- **Determinism:** the same lines and placements give identical results. The bootstrap uses `np.random.default_rng(0)`. Pressing Measure twice on an unchanged table gives the same numbers (spec anti-goal).
- **Stopping:** `measure_destagger` calls `should_stop()` at least once per line in every per-line loop, and raises `MeasureStopped` when it returns True. A stop then takes effect within about half a second.
- **Numbers (core, exact):**
  - `DEWOW_NS = 4.0` and `BIN_SAMPLES = 8`.
  - `STEP_M = 0.02`, `LOWPASS_M = 0.15`, `HIGHPASS_M = 3.0` and `END_TRIM_M = 2.0`.
  - `T_START_NS = 4.0` (header clock; bins whose centre is at or before it are skipped).
  - The search range is ±max(`MIN_SEARCH_M = 1.0`, `SEARCH_FRACTION = 0.03` × the longest placed line on the axis) of neighbour lag.
  - `BOOTSTRAP = 300`; `MIN_USABLE_M = 2.0` (P3).
  - The time window's end is not hard-coded. The builder chooses a rule (spec §11) that keeps the §10 values.
- **Copy (exact). Core reasons, as module constants in `nsgeo.destagger.measure`:**
  - `NO_DISTANCE = "no distance axis (recorded on a timer)"`
  - `TOO_SHORT = "too short to measure"`
  - `TIME_SETTINGS = "recorded with different time settings from the rest of the grid"`
  - `NO_NEIGHBOUR = "no line walked the other way beside it"`
  - `ONE_WAY = "every line was walked the same way, so there is no stagger to measure"`
  - `TOO_FEW = "too few lines walked in opposite directions to measure"` (fewer than `MIN_LINES = 4` lines with a neighbour)
  - `UNCLEAR = "no clear match between lines walked in opposite directions"`
  - `AXIS_FAILED = "its grid's value could not be measured"`
- **Copy (exact), plugin:**
  - Button: `Measure`; while running, `Stop`.
  - `MEASURE_TIP = "Works out the destagger from the grid's own data: each line is compared with its neighbours walked the other way, over the whole record. Fills the Destagger box with the grid's value and each selected row with its line's value. Nothing changes until OK."`
  - Progress: `Measuring… read {i} of {n} lines`, then `Measuring… comparing lines`.
  - Stopped: `Measure stopped. Nothing was changed.`
  - Discarded: `The table changed while measuring, so the results were not used. Press Measure again.`
  - Site gone or replaced: `The site changed while measuring, so the results were not used.`
  - Error: `Could not measure: {message}. Nothing was changed.`
  - Nothing selected to fill: `Select the lines to fill, then press Measure.`
  - Summary (built by `measure_summary`, parts joined with one space, empty parts left out):
    - One axis: `Measured {g:+.3f} m from {n} lines (±{s:.3f} m).`
    - Two axes: `Along {axis}: measured {g:+.3f} m from {n} lines (±{s:.3f} m).` per axis, then the groups below.
    - One axis that failed: `Could not measure: {reason}. Nothing was changed.`; with two axes, `Along {axis}: could not measure ({reason}); nothing changed there.`
    - `Own values: {label} {v:+.3f}, {label} {v:+.3f}.`
    - `Left at the grid value: {label} changes partway along; {label} has no clear match.`
    - `Not measured, left as they were: {label} ({reason}); {label} ({reason}).`
    - An unreadable file's reason: `could not be read: {error}`.
    - When every axis failed, the summary is only the failure sentence or sentences. The groups describe only the `filled` rows (P6).
- **Never commit site data:** never commit pictures of the site or coordinates. `tests/data/local/` is git-ignored; never `git add -f` from it.
- **Shared-worktree safety:** reviewers and any mutation probes work on a scratch copy, never this worktree. Set `PYTHONDONTWRITEBYTECODE=1` for every run.
- **Commits:** end each message with a `Co-Authored-By:` line naming the model that wrote it. Push each commit to `origin nsgeo-auto-destagger` as it is made. Touch no other worktree.

## Verification commands (exactly these, from the worktree root)

The worktree uses the main checkout's virtualenvs, with the worktree's core on `PYTHONPATH`, plus a local `.venv-tools` (git-excluded) holding the CI-pinned ruff 0.17.1 and mypy 2.4.0. Real data is linked under `packages/nsgeo-core/tests/data/local/`:
- the campus lines at the top level;
- `with-dzg/` (Nashville 2023 Grid 1);
- `grid2/` (Nashville 2023 Grid 2).

A real-data test that skips has validated nothing, so the skip count must not rise.

- **core + pure:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider`
- **qgis:** `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:cacheprovider -p no:xonsh`
  - This takes 10+ minutes. Run single files while iterating; the coordinator runs the full tier.
- **lint:** `.venv-tools/bin/ruff check . && .venv-tools/bin/ruff format --check .`
- **types:** `.venv-tools/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py packages/nsgeo-qgis/nsgeo_qgis/line_edit.py packages/nsgeo-qgis/nsgeo_qgis/destagger_job.py` (check `ci.yml` for any file added since; this list must match it).

The baselines are recorded in the ledger at pre-flight.

## Review Focus

1. **The selection is cleared while a measure runs.** **Stop** must stay pressable, and the results land in the rows selected at the start (P6, P8). Pinned by Task 3, `test_stop_stays_reachable_when_the_selection_is_cleared`.
2. **The site is closed or replaced while a measure runs.** The results are not used, the status says so, and nothing raises. Pinned by Task 3, `test_a_site_closed_while_measuring_is_not_written_to`.
3. **A line's file cannot be read** (moved or deleted after the site opened). That line is named as not measured with its reason, and the rest are measured. Pinned by Task 3, `test_an_unreadable_line_is_named_and_the_rest_are_measured`.
4. **A row moved to another grid in the table before Measure.** It is left out of the measurement and not filled. Its old neighbours are measured against each other. Pinned by Task 3, `test_a_row_moved_to_another_grid_is_left_out`.
5. **A timer-recorded line (`traces_per_metre <= 0`) among wheel lines.** It is *not measured* with `NO_DISTANCE`, and the others still give the grid value. Pinned by Task 1, `test_a_line_without_a_distance_axis_is_not_measured`.

---

## Pre-flight (coordinator, before Task 1)

- [ ] Create `.venv-tools`: `../../.venv/bin/python -m venv .venv-tools && .venv-tools/bin/pip install ruff==0.17.1 mypy==2.4.0 numpy`.
- [ ] Link the real data into the worktree. Use `ln -s` for each file, plus the folders `with-dzg/` and `grid2/`, from the main checkout's `packages/nsgeo-core/tests/data/local/`.
- [ ] Check that `git status --short` shows nothing new.
- [ ] Run the four verification commands. Record the pass and skip counts in the ledger as the baselines.

---

### Task 1: The grid value in nsgeo-core

Builds the package, the preparation step, the grid value per axis (the spike's method), *not measured* lines, C10 and C11. Every measured line gets `LineStatus.GRID` with the grid value. Task 2 adds per-line values.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/destagger/__init__.py`, `prepare.py`, `profiles.py`, `measure.py`
- Create: `packages/nsgeo-core/tests/destagger_data.py` (real-data helpers), `packages/nsgeo-core/tests/test_destagger_grid.py`
- Modify: `packages/nsgeo-core/tests/real_data.py` (add `GRID2_LINES`), `packages/nsgeo-core/tests/data/local/README.md` (layout gains `grid2/`), `packages/nsgeo-core/tests/test_public_api.py` (`EXPECTED_PUBLIC` gains `"destagger"`), `packages/nsgeo-core/README.md` (a short `nsgeo.destagger` section naming each public name in backticks)

**Interfaces (produced; Tasks 2 and 3 rely on these exactly):**

```python
# nsgeo/destagger/prepare.py
@dataclass(frozen=True, eq=False)
class EnvelopeBins:
    data: np.ndarray     # (n_bins, n_traces) float32
    t0_ns: float         # centre time of bin 0, header clock
    dt_ns: float         # time between bin centres (BIN_SAMPLES x sample interval)
    @property
    def t_ns(self) -> np.ndarray: ...

def envelope_bins(samples: np.ndarray, dt_ns: float, t0_ns: float) -> EnvelopeBins:
    """One channel's raw samples (n_samples, n_traces): dewow DEWOW_NS, background_mean,
    analytic envelope (nsgeo.processing), then the mean of each BIN_SAMPLES rows (a partial
    last bin is dropped)."""

# nsgeo/destagger/measure.py
class LineStatus(Enum):
    GRID = "grid value"
    OWN = "own value"
    CHANGES = "changes partway along"
    NO_MATCH = "no clear match"
    NOT_MEASURED = "not measured"

@dataclass(frozen=True)
class MeasureLine:
    key: str
    bins: EnvelopeBins
    placement: GridPlacement   # as the table shows it now; travel_shift is ignored (C1)
    header: DztHeader          # positions: replace(placement, travel_shift=0.0).distance_along(bins.data.shape[1], header)

# nsgeo/destagger/profiles.py (internal, but Task 2 imports it)
def search_range_m(longest_m: float) -> float:
    """Neighbour-lag search half-width: max(MIN_SEARCH_M, SEARCH_FRACTION * longest_m) (C12)."""

@dataclass(frozen=True)
class LineResult:
    key: str
    axis: str
    status: LineStatus
    destagger: float | None    # the value for its Destagger cell; None exactly when NOT_MEASURED
    reason: str = ""           # set for NOT_MEASURED (one of the reason constants)

@dataclass(frozen=True)
class AxisResult:
    axis: str
    destagger: float | None    # None when the grid value could not be measured (C10)
    spread_m: float            # half the width of the 95% bootstrap interval; nan when destagger is None
    lines_used: int            # lines with an opposite-direction neighbour that were measured
    reason: str = ""           # ONE_WAY, TOO_FEW or UNCLEAR when destagger is None

@dataclass(frozen=True)
class DestaggerResult:
    axes: dict[str, AxisResult]    # one per axis present among the lines
    lines: dict[str, LineResult]   # one per input line

class MeasureStopped(Exception): ...

def measure_destagger(
    lines: Sequence[MeasureLine], should_stop: Callable[[], bool] = lambda: False
) -> DestaggerResult: ...
```

`__init__.__all__` is `["AxisResult", "DestaggerResult", "EnvelopeBins", "LineResult", "LineStatus", "MeasureLine", "MeasureStopped", "envelope_bins", "measure_destagger"]`.

**The method** is spec §7.2, as the spike's `destagger_spike.py` (`prepare`, `Measure.profiles`, `Measure.curves`, `peak`, `report`) does it. Read that code; it is the reference. In order, per axis:
1. Exclude *not measured* lines: no distance axis, then P2 and P3.
2. Find neighbours by offset order among the rest, opposite direction only.
3. Build the common along axis, at `STEP_M` from the smallest to the largest along value.
4. Gain each bin by its median over all lines. Low-pass with a moving average of `LOWPASS_M`, high-pass by subtracting a moving average of `HIGHPASS_M`, and zero `END_TRIM_M` at each line's own ends. Normalise each line jointly over its bins.
5. Correlate each line with the mean of its neighbours by FFT, over the search range. Reverse the lag axis for direction −1, so the lag reads in the line's own travel direction. Sum over bins, then average over lines.
6. Take the peak with a parabola. Grid destagger = −peak / 2.
7. Check that the peak is clear: the argmax is not at either end of the range, and it beats the highest other local maximum more than 0.12 m away by a margin the builder tunes. Otherwise use `UNCLEAR`.
8. Bootstrap over lines with `np.random.default_rng(0)` to get `spread_m`.

`profiles.py` holds steps 3–5 as functions Task 2 reuses on half-windows: a time range, or an along range. Vectorising is welcome; the spike's loops are the reference for the results, not for speed.

- [ ] **Step 1: Write the failing tests** in `test_destagger_grid.py`. They use `destagger_data.py`, which provides:
  - `lines_for(paths, length, *, axis="y", fitted=False, mirrored=False, travel_shift=0.0, moved=None, skew=0.0) -> list[MeasureLine]`, placing zigzag lines at 0.5 m with line 1 forward, on grid `"G"`. Grid 1 uses `length=30.0` and Grid 2 `29.96`. Fitted means scale = length / recorded span and both ends on the edges. `moved` maps a 0-based index to metres added along that line's travel. `skew` adds `skew × rank` to every start. The function caches `envelope_bins` per path for the session, so the 60 files are read once.
  - `needs_grid1` (skip unless `len(GPS_LINES) == 60`) and `needs_grid2` (skip unless `len(GRID2_LINES) == 60`).

  The tests:
  - `test_grid1_unfitted_gives_the_value_found_by_eye`: axis `y` destagger within 0.02 of +0.15; `spread_m < 0.02`; `lines_used == 60`.
  - `test_grid1_fitted_gives_the_whole_grid_value`: within 0.02 of −0.065.
  - `test_grid2_unfitted_and_fitted`: within 0.02 of +0.165 (unfitted) and −0.059 (fitted), on a 29.96 m grid.
  - `test_the_current_destagger_is_ignored`: `travel_shift=0.3` on every line, and a different shift per line, both give results equal to `travel_shift=0` (`==` on `DestaggerResult`).
  - `test_mirrored_lines_give_the_same_values`: the grid value equals the unmirrored one within 0.005.
  - `test_measuring_twice_gives_identical_results`.
  - `test_every_measured_line_gets_the_grid_value` (Task 1 only; Task 2 replaces it): every `LineResult` has status GRID and `destagger == axes["y"].destagger`.
  - `test_a_line_without_a_distance_axis_is_not_measured`: one mid-grid line's header has `traces_per_metre=0.0` (`dataclasses.replace`). It is NOT_MEASURED with `NO_DISTANCE` and `destagger is None`; the grid value stays within 0.02 of +0.15.
  - `test_a_short_line_is_not_measured`: one line's bins are cut to its first 300 traces. It is NOT_MEASURED with `TOO_SHORT`.
  - `test_a_line_with_other_time_settings_is_not_measured`: one line's `EnvelopeBins` is rebuilt with `t0_ns + 1.0`. It is NOT_MEASURED with `TIME_SETTINGS`.
  - `test_lines_all_walked_one_way_measure_nothing`: every line direction +1. `axes["y"].destagger is None`, the reason is `ONE_WAY`, and every line is NOT_MEASURED with `AXIS_FAILED`.
  - `test_a_line_with_no_opposite_neighbour_is_not_measured`: line 0 is flipped to walk the same way as line 1, its only neighbour. It is NOT_MEASURED with `NO_NEIGHBOUR`.
  - `test_unrelated_lines_have_no_clear_match`: alternate Grid 1 and Grid 2 lines (real lines from different grids, so nothing matches). The destagger is None with reason `UNCLEAR`. If that pairing happens to give a clear peak, use Grid 1 lines with every odd line's bins reversed along the line instead. Say which in the test's docstring.
  - `test_the_search_range_grows_with_the_lines`: `search_range_m(30.0) == 1.0` and `search_range_m(60.0) == pytest.approx(1.8)`.
  - `test_too_few_lines_measure_nothing`: 3 lines. Reason `TOO_FEW`.
  - `test_each_axis_is_measured_on_its_own`: Grid 1 lines on axis `y` and Grid 2 lines on axis `x`, all with `grid_id` `"G"`. Both axes are present, each within 0.02 of its own unfitted value.
  - `test_should_stop_raises_measure_stopped`: `should_stop` returns True on its 5th call, and `MeasureStopped` is raised.
  - `test_envelope_bins_shape_and_clock`: on one real line, `data.shape == (n_samples // 8, n_traces)`; `t0_ns == position_ns + 3.5 * dt`; `dt_ns == 8 * header.dt_ns`.
  - Also extend `test_real_files.py`: a `GRID2_LINES` test mirroring the `GPS_LINES` one (60 names, all in `DATA / "grid2"`, a DZG beside each).
- [ ] **Step 2: Run them and see them fail** (`ModuleNotFoundError: nsgeo.destagger`).
- [ ] **Step 3: Implement** the interfaces above. Add `GRID2_LINES = dzt_files(DATA / "grid2")` with a docstring naming the survey. Update the README layout block and the core README section.
- [ ] **Step 4: Run** `test_destagger_grid.py`, `test_public_api.py` and `test_real_files.py`, then the full core+pure, lint and types. All green, no new skips.
- [ ] **Step 5: Commit and push:** `feat(core): measure a grid's destagger from its lines (#159)`.

---

### Task 2: Per-line values in nsgeo-core

Adds C4 and C13 (spec §7.4): own values, *changes partway along* and *no clear match*. This is the research-heavy task, so it gets an opus implementer.

**Start from the prototype.** `docs/superpowers/notes/2026-11-11-destagger-measure-spike/per_line_block.py`, and the note's **Per-line prototype** section, say what it gets right and wrong. The caches it needs can be rebuilt by `destagger_spike.py` (spike note, "Running the scripts"). The method is the builder's (spec §11), but the behaviour is fixed:
- **A line gets its own value only if it is clear and repeatable.** At least one pair of independent halves (shallow/deep bins, or first/second half along) has clear peaks that agree.
- **A half without a clear peak neither confirms nor counts against the line** (C13).
- **Changes partway along:** both along halves are clear and disagree by much more than noise. The line keeps the grid value.
- **No clear match:** the whole-record peak is not clear. The line keeps the grid value.
- **A bad line does not drag its neighbours.** A run of adjacent off lines is solved jointly. A skew (a shift that grows steadily across the lines) produces no own values.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/destagger/per_line.py`, `packages/nsgeo-core/tests/test_destagger_lines.py`
- Modify: `measure.py` (calls the per-line solve after the grid value; per-line results replace Task 1's all-GRID statuses), `test_destagger_grid.py` (remove `test_every_measured_line_gets_the_grid_value`)

**Interfaces:**
- Consumes: Task 1's types and `profiles.py`.
- Produces: no new public names. `LineResult.status` may now be OWN (with `destagger` = grid value + its own correction), CHANGES or NO_MATCH (with `destagger` = the grid value). Sign: a line whose features sit `r` metres ahead along its travel, relative to its corrected neighbours, gets `grid − r`.

- [ ] **Step 1: Write the failing tests** in `test_destagger_lines.py`. They are real data only, and `moved` is 0-based. `FILE__031` is index 30.
  - Module-scoped fixtures share the base results (Grid 1 unfitted and fitted, Grid 2 unfitted and fitted), so each 60-line measurement runs once.
  - `test_a_line_moved_forward_is_recovered`: Grid 1 unfitted, `moved={30: 0.30}`. `FILE__031`'s value is within 0.05 of (its base value − 0.30). `FILE__030` and `FILE__032` keep their base status, and their values stay within 0.02.
  - `test_a_line_moved_back_is_recovered`: the same with `moved={30: -0.50}`, so the target is the base value + 0.50, within 0.05. The prototype is 7 cm off here (P11).
  - `test_two_adjacent_moved_lines_are_both_recovered`: `moved={30: 0.30, 31: 0.30}`. Both are within 0.05 of base − 0.30 (P10).
  - `test_a_skew_creates_no_own_values` (P9): `skew=0.02`, on Grid 1 unfitted and fitted.
  - `test_most_grid1_lines_keep_the_grid_value`: unfitted and fitted, at least 80% of lines are not OWN, or the builder's pinned share, never lower than 75%.
  - `test_unfitted_file_011_gets_no_own_value`: status in {CHANGES, NO_MATCH}.
  - `test_grid2_clearly_off_lines_get_own_values`:
    - Unfitted: `FILE__045`, `FILE__027` and `FILE__028` are OWN with `destagger > grid + 0.25`.
    - Fitted: `FILE__051` is OWN with `destagger > grid + 0.10`, and `FILE__059` is OWN with `destagger < grid − 0.10`.
    - Size tolerances are pinned around the measured values. The prototype gave +0.881, +0.665 and +0.687 unfitted, and +0.147 and −0.287 fitted.
  - `test_grid2_fitted_file_050_gets_no_own_value`: status in {CHANGES, NO_MATCH}.
  - `test_most_grid2_lines_keep_the_grid_value`: at least 70%, or the builder's pinned share if higher.
  - `test_per_line_results_are_deterministic`: Grid 2 fitted, measured twice, gives equal results.
- [ ] **Step 2: Run them and see them fail.** Every line is GRID, so the own-value and status tests fail.
- [ ] **Step 3: Implement `per_line.py`.** Tune the thresholds on Grids 1 and 2, then name each one as a module constant with a comment saying what it was tuned on.
- [ ] **Step 4: Run** the two destagger test files, then the full core+pure, lint and types. All green. If a spec tolerance cannot be met, leave that test failing with a short comment, and report `DONE_WITH_CONCERNS` with the numbers. Do not loosen the test (P11).
- [ ] **Step 5: Write a results table** into the spike note, as a new section **Per-line results (built)**. For each grid and placement, give: the grid value; how many lines are OWN, CHANGES, NO_MATCH and NOT_MEASURED; each OWN line's value; and the injected-error results. Use file names and metres only.
- [ ] **Step 6: Commit and push:** `feat(core): per-line destagger values where a line is clearly off (#159)`.

---

### Checkpoint C14 (coordinator and author; a human gate)

Stop here and ask the author. Dialog work does not start until they answer.

- [ ] Write the line-strip pictures to the session scratchpad, never to the repository: Grids 1 and 2, unfitted and fitted, at 14.9–19.7 ns. Adapt the spike's `destagger_panels.py` to call `nsgeo.destagger` and draw three panels per case: no destagger; the grid value on every line; the grid value plus per-line values.
- [ ] Send the author the pictures and Task 2's results table. Include anything Task 2 reported as a concern (the −0.50 case, the Grid 2 own-value share), and ask:
  - whether the per-line values look better than the grid value alone;
  - whether any own value looks wrong;
  - whether the tolerances are acceptable.
- [ ] Record the answer in the ledger. "Worse overall" sends the plan back to Task 2 (spec C14). Agreed tolerance changes go into the tests, with the author's words cited in a comment.

---

### Task 3: Measure in Edit lines

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/destagger_job.py`, `packages/nsgeo-qgis/tests/pure/test_pure_destagger_job.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_edit_lines_measure.py`
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/edit_lines_dialog.py`
  - `.github/workflows/ci.yml` (mypy list)
  - `docs/guide/getting-started.md` (a paragraph after the destagger paragraphs: what Measure does, that it fills the selected rows and the box, that nothing changes until OK, and that it is a starting point to adjust)
  - `README.md` (the features bullet: "…and destaggered along its direction of travel, by an amount typed or measured from the data.")

**Interfaces:**
- Consumes: Task 1's `envelope_bins`, `MeasureLine`, `measure_destagger`, `DestaggerResult`, `LineStatus` and `MeasureStopped`; `nsgeo_qgis.refine.Refiner`.
- Produces, in `destagger_job.py`:

```python
@dataclass(frozen=True)
class JobLine:
    key: str
    label: str
    path: Path
    header: DztHeader
    placement: GridPlacement     # LineEdit.placed(frames) at press time

class MeasureJob:                # a RefineJob
    def __init__(self, lines: Sequence[JobLine], cached: Mapping[str, EnvelopeBins]) -> None: ...
    prepared: dict[str, EnvelopeBins]    # cached plus newly read
    unreadable: dict[str, str]           # key -> str(error)
    result: DestaggerResult | None
    stopped: bool
    progress: tuple[int, int]            # (lines read, lines to read); written by the worker
    def run(self, should_stop: Callable[[], bool]) -> None: ...

def box_value(result: DestaggerResult) -> float | None: ...   # the axis with more lines_used (C11); None if it failed
def measure_summary(result: DestaggerResult, filled: Sequence[str],
                    unreadable: Mapping[str, str], labels: Mapping[str, str]) -> str: ...
```

`run`:
- Reads only the lines missing from `prepared`, with `read_samples(path, header)[0]` then `envelope_bins` (P4).
- Catches `OSError`, `DztError` and `ValueError` per line into `unreadable`.
- Checks `should_stop()` before each read.
- Then calls `measure_destagger` on the prepared lines. On `MeasureStopped`, or on a stop between reads, it sets `stopped = True` and returns normally.

**Dialog changes:**
- `measure_button` sits after `set_destagger_button`, with tooltip `MEASURE_TIP`.
- `self._measurer = Refiner(self)`; a `QTimer` at `MEASURE_PROGRESS_MS = 200` shows progress.
- `self._bins: dict[str, EnvelopeBins]` caches prepared lines for the dialog's life (C8).
- `measure()` starts or stops a run.
- On land, check in this order: the session's `site` is still the object captured at press; then the snapshot. The snapshot is every on-grid row's `dataclasses.replace(placed, travel_shift=0.0, label=None)`, keyed by row key; the run's must equal the current one. Only then fill the targets (P5, P6) and the box, and `_refresh(summary)`.
- `_update_panel` enables the bulk panel when there is a selection or `self._measurer.busy` (P8).
- `done(r)` is overridden to `self._measurer.shutdown()` before `super().done(r)`. Every slot added is guarded.

- [ ] **Step 1: Write the failing pure tests** in `test_pure_destagger_job.py`, with synthetic DZTs from `plugin_testing.synthetic_dzt` and constructed `DestaggerResult`s:
  - `test_the_job_reads_only_lines_it_has_not_prepared`: one key cached, so one file is read. Check by monkeypatching `read_samples` with a counting wrapper.
  - `test_an_unreadable_file_is_recorded_not_raised`: a deleted path appears in `unreadable`, and the rest are measured.
  - `test_a_stop_between_reads_ends_the_job_quietly`: `stopped` is True, `result` is None, and nothing raises.
  - `test_a_multi_channel_file_is_measured_on_its_first_channel`: written with `n_channels=2`. The job's prepared bins equal `envelope_bins` of channel 0.
  - `test_box_value_takes_the_axis_with_more_lines`, and None when that axis failed.
  - `test_summary_words`: the exact strings from Global Constraints for one axis OK; two axes; one failed axis; own, changes, no-match and not-measured groups; an unreadable file; and more than 6 names (P12).
- [ ] **Step 2: Write the failing QGIS tests** in `test_plugin_edit_lines_measure.py`.
  - The fixture site is built like `test_plugin_edit_lines_dialog.py`'s `_site`, with 6 synthetic lines.
  - UI-plumbing tests monkeypatch `nsgeo_qgis.destagger_job.measure_destagger` with a canned function. It can block on a `threading.Event` the test sets, and it records the `MeasureLine`s it was given.
  - Tests wait with `spin_until(lambda: not dialog._measurer.busy)`.

  The tests:
  - `test_measure_fills_the_selected_rows_and_the_box`: rows 0–3 are selected. They get their canned values (one OWN), shaded `CHANGED`. Rows 4–5 are untouched. The box shows the grid value, and the status equals `measure_summary(...)`.
  - `test_measure_uses_the_tables_pending_placement`: with Fit to grid edges pending on the selection, the `MeasureLine` placements carry the fitted scale.
  - `test_an_edit_while_measuring_discards_the_results`: while the canned function blocks, change one row's Start. Then release it. No Destagger cell changes, and the status is the Discarded copy.
  - `test_a_destagger_edit_while_measuring_does_not_discard`: change a Destagger cell during the run. The results land.
  - `test_stop_changes_nothing`: press Measure, then press it again (it reads `Stop`). Nothing changes, the status is the Stopped copy, and the button reads `Measure` again.
  - `test_closing_the_dialog_stops_the_measure`: `reject()` during the run. Afterwards no result lands, and no `nsgeo-refine` thread is left alive.
  - `test_stop_stays_reachable_when_the_selection_is_cleared` (Review Focus 1).
  - `test_a_site_closed_while_measuring_is_not_written_to` (Review Focus 2): call `session.close_site()` during the run. The status is the Site-changed copy, and nothing raises.
  - `test_an_unreadable_line_is_named_and_the_rest_are_measured` (Review Focus 3): uses the real `measure_destagger`. Delete one synthetic file after opening; the summary names it with `could not be read:`.
  - `test_a_row_moved_to_another_grid_is_left_out` (Review Focus 4): the canned function did not receive that key, and the row is not filled.
  - `test_measuring_twice_reads_each_file_once_and_gives_the_same_values` (C8; count reads as in the pure test).
  - `test_a_one_way_grid_says_there_is_nothing_to_measure`: the real `measure_destagger` on all-forward synthetic lines. The status is `Could not measure: every line was walked the same way, so there is no stagger to measure. Nothing was changed.`
  - `test_two_axes_fill_each_row_from_its_own_axis` (C11, canned).
  - `test_measure_on_the_real_survey` (real data, skip without `GPS_LINES`): 60 lines unfitted on a 30 m grid. Ctrl+A, then Measure. The box is within 0.02 of +0.15, and every row's Destagger cell is filled. Allow 120 s.
- [ ] **Step 3: Run both files and see them fail.**
- [ ] **Step 4: Implement** `destagger_job.py` and the dialog changes. Update `ci.yml`, the guide and the README.
- [ ] **Step 5: Run** the two new files, `test_plugin_edit_lines_dialog.py` and the pure tier, then lint and types. Leave the full QGIS tier to the coordinator.
- [ ] **Step 6: Commit and push:** `feat(plugin): Measure the destagger in Edit lines (#159)`.

---

### Task 4: Review, deploy and walkthrough (coordinator and author; a human gate)

- [ ] Run the full QGIS tier, then a whole-branch review (opus). Then do a fix wave if needed.
- [ ] Deploy to a new profile `ns_geo_destagger`. Copy `ns_geo` with `cp -a`, then run `packages/nsgeo-qgis/scripts/dev_link.py` pointed at this worktree.
- [ ] Publish a walkthrough Artifact with a `db` capability for results, covering spec §10's walkthrough list:
  - Grids 1 and 2, unfitted and fitted;
  - judging the wiggle at 14.9–19.7 ns;
  - cancel mid-measure;
  - editing during a measure;
  - pressing Measure twice;
  - a one-direction grid.
- [ ] Stop and wait for the author's results. Update the README roadmap ("In progress": built, walkthrough pending). Merging asks first.
