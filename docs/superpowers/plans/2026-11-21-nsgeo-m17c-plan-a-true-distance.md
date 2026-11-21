# M17c Plan A: true-distance profiles — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A GPS line's profile draws each trace at its true distance along the walked path, with one hatched gap where the cart was lifted, and its migration runs at true spacing; the gap rule is a per-line **Gap over (m)** in Edit lines.

**Architecture:** One gap rule in the core (`nsgeo.geometry.spacing`) serves the profile and migration. The profile keeps its trace-unit coordinates and its one road between traces and metres (`ruler.metres_at` / `trace_units_at`); a new Qt-free `TraceAxis` makes screen x linear in metres for GPS lines only, caps each column at a gap and leaves lifted traces out. Tape lines and cuts get no `TraceAxis`, so their code path is today's. Migration re-samples a GPS line onto an even grid at its usual step and reads each trace back.

**Tech Stack:** Python 3.9+ numpy core (`packages/nsgeo-core`); QGIS plugin on QGIS 3.44 / PyQt5 and 4.2 / PyQt6 (`packages/nsgeo-qgis`); pytest.

**Spec:** `docs/superpowers/specs/2026-11-06-nsgeo-gps-lines-design.md`: decision 11, **decision 16** (lifts left out; Gap over in Edit lines), §9 (M17c), §11 (M17c walkthrough) and **§17** (the calls this plan makes). The profile view's spec `docs/superpowers/specs/2026-11-20-nsgeo-profile-view-design.md` §3.1 and §4.7 (the one trace↔metres road M17c swaps).

## Global Constraints

- **Privacy:** "I'm fine with it as long as there are no coordinates and the site name isn't added." No real coordinate (from a DZG or a DZT header) and no site name in any committed file, test, docstring, commit message or report. Synthetic GPS data uses the existing made-up place (lat 45.2, lon 10.5, EPSG:32632). Real-data tests read `tests/data/local/` (gitignored, symlinked) and assert only on trace indices, steps, counts and metres along a line.
- **Tape lines and cuts are unchanged by construction:** they never get a `TraceAxis`; `ViewTransform` with `axis=None` runs exactly today's code. Existing tests pass unmodified; any change to an existing test is named and justified in the report.
- **Exact values:** `GAP_FACTOR = 6.0`. A step is a gap when it is **longer than** the threshold (`>`, not `>=`). A trace is left out when the steps on **both** sides are gaps; the first and last traces never are. A drawn trace reaches at most **half a usual step** into a gap.
- **Copy, verbatim:** column header `Gap over (m)`; automatic cell `auto {v:.2f}` (e.g. `auto 0.10`); typed cell `{v:.2f}`; read-out over a gap `{m:.2f} m along (gap)`; bulk buttons `Set` and `Automatic`; `GAP_TIP` = "On a GPS line, a step between two traces longer than this is drawn as a gap, and traces with a gap on both sides (lifted over an obstacle) are left out of the profile. Empty means automatic: 6× the line's usual step."; `TAPE_SKIP` = "Left {n} tape line(s) alone: Gap over applies to GPS lines only."; a bad typed value: `{text!r} is not a length above 0; unchanged`.
- **Platforms:** the plugin runs on QGIS 3.44 (PyQt5) and 4.2 (PyQt6); use `nsgeo_qgis.qtcompat` and the enum spellings already used in the touched files. Core stays numpy-only.
- **Tools:** lint with the worktree's `.venv-tools/bin/ruff` (0.17.1) only, never the main `.venv` ruff (it reformats `docs/superpowers`). Commands from the worktree root:
  - core + pure: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider -p no:xonsh`
  - QGIS files: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src packages/nsgeo-qgis/scripts/qgis_tests.sh <files> -q -p no:cacheprovider` (add `-m real_data` for the real-data tier)
  - lint: `.venv-tools/bin/ruff check . && .venv-tools/bin/ruff format --check .`; types: `.venv-tools/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo`
- **Schema:** `gap_m` is an optional key on the saved track placement, written only when typed. Schema 4 is unreleased; no new schema number.

## Review Focus

1. **Zero-length steps** (the cart standing still while the wheel turned; repeated distances): no division by zero, no NaN or inf in a transform, the inverse lands on a drawn trace. → Task 1 `test_a_line_with_no_spacing_has_no_gaps`, Task 3 `test_repeated_distances_do_not_break_the_inverse`.
2. **A lift at the very first or last step, and a line that is nearly all gaps:** ends drawn, runs and paint spans sane. → Task 1 `test_a_lift_at_either_end_leaves_the_end_trace_drawn`, Task 3 `test_a_lift_at_the_first_step_draws_trace_0_half_a_step_wide`.
3. **A window edge inside a gap:** zoom, pan, Fit width and 1:1 from there neither raise nor jump. → Task 3 `test_a_window_edge_inside_a_gap_survives_zoom_and_pan`.
4. **A pick or velocity dot on a left-out trace** (made before M17c): still drawn at its walked position and still removable. → Task 4 `test_a_pick_on_a_left_out_trace_is_still_drawn`.
5. **Gap over at the extremes** (typed 0.01 m, so nearly every step is a gap; typed 100 m, so none is; a saved site with no `gap_m`): nothing raises; the profile and migration follow. → Task 1 `test_a_tiny_gap_over_leaves_out_everything_but_the_ends`, Task 5 `test_gap_over_extremes_reach_the_profile`.

---

### Task 1: The gap rule and Gap over, in the core

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/geometry/spacing.py`
- Modify: `packages/nsgeo-core/src/nsgeo/geometry/track.py` (`TrackPlacement`), `packages/nsgeo-core/src/nsgeo/project.py` (track placement save/load, ~lines 164-172 and the track branch of the loader)
- Test: `packages/nsgeo-core/tests/test_spacing.py` (new), `packages/nsgeo-core/tests/test_spacing_real_files.py` (new), `packages/nsgeo-core/tests/test_project.py`

**Interfaces:**
- Produces, in `nsgeo.geometry.spacing`:
  - `GAP_FACTOR: float = 6.0`
  - `usual_step(distance: np.ndarray) -> float` — median of `abs(diff(distance))`; `0.0` for fewer than 2 traces.
  - `gap_threshold(distance: np.ndarray, gap_m: float | None = None) -> float` — `gap_m` when given, else `GAP_FACTOR * usual_step`; `math.inf` when the usual step is 0. `ValueError` for a `gap_m` that is not finite and above 0.
  - `gap_steps(distance: np.ndarray, gap_m: float | None = None) -> np.ndarray` — bool, length `n - 1` (empty below 2 traces): `abs(step) > threshold`.
  - `left_out(distance: np.ndarray, gap_m: float | None = None) -> np.ndarray` — bool, length `n`: True where the steps on both sides are gaps; never the first or last trace.
- Produces: `TrackPlacement.gap_m: float | None = None` (last field). `__post_init__` raises `ValueError` unless it is None or finite and > 0. Saved as `"gap_m"` only when not None; loaded with `doc.get("gap_m")`.

- [ ] **Step 1: Write the failing tests** in `test_spacing.py`:

```python
def test_the_usual_step_is_the_median_step():
    assert usual_step(np.array([0.0, 0.02, 0.04, 0.06, 1.0, 1.02])) == pytest.approx(0.02)

def test_a_step_over_six_usual_steps_is_a_gap():
    d = np.concatenate([np.arange(10) * 0.02, 0.18 + 0.5 + np.arange(10) * 0.02])
    assert gap_steps(d).tolist() == [False] * 9 + [True] + [False] * 9

def test_the_threshold_is_strictly_longer_than_six_usual_steps():
    base = np.arange(20) * 0.02
    assert not gap_steps(np.append(base, base[-1] + 0.119)).any()
    assert gap_steps(np.append(base, base[-1] + 0.121))[-1]

def test_a_typed_gap_over_replaces_the_automatic_threshold():
    d = np.array([0.0, 0.02, 0.04, 0.10, 0.12, 0.62, 0.64])
    assert gap_steps(d, gap_m=0.05).tolist() == [False, False, True, False, True, False]
    assert not gap_steps(d, gap_m=1.0).any()

def test_traces_between_two_gap_steps_are_left_out():
    d = np.array([0.0, 0.02, 0.04, 0.5, 1.0, 1.5, 1.52, 1.54])
    assert left_out(d).tolist() == [False, False, False, True, True, False, False, False]

def test_a_single_gap_step_leaves_both_its_traces_drawn():
    d = np.array([0.0, 0.02, 0.04, 1.5, 1.52, 1.54])
    assert not left_out(d).any()

def test_a_falling_distance_has_the_same_gaps_as_its_reverse(): ...  # gap_steps(-d) == gap_steps(d); left_out likewise
def test_a_line_with_no_spacing_has_no_gaps(): ...  # constant d: usual_step 0, no gaps, nothing left out, no numpy warning (pytest -W error)
def test_fewer_than_two_traces(): ...  # n=1: gap_steps empty, left_out == [False]; n=0: both empty
def test_a_lift_at_either_end_leaves_the_end_trace_drawn(): ...  # gaps at step 0 and step n-2: left_out[0] and left_out[-1] False
def test_a_tiny_gap_over_leaves_out_everything_but_the_ends(): ...  # gap_m=0.001 on an even 0.02 line: left_out[1:-1] all True, ends False
def test_gap_over_must_be_finite_and_positive(): ...  # gap_steps(d, gap_m=v) and TrackPlacement(..., gap_m=v) raise ValueError for 0, -1, nan, inf
```

In `test_project.py`: `test_gap_over_round_trips_and_is_saved_only_when_typed` — a GPS line with `gap_m=0.25` saves `"gap_m": 0.25` and reloads as 0.25; with `gap_m=None` the saved track has no `"gap_m"` key and reloads None. Build the placement as the existing track round-trip test does.

In `test_spacing_real_files.py` (skips when `with-dzg/` or `grid2/` is absent, as `test_track_real_files.py` does, with its projector): `test_the_gps_surveys_lifts_are_gaps_and_their_slips_are_not`:
- `FILE__028` (with-dzg): the step from trace 841 to 842 is a gap;
- `FILE__016` (with-dzg): traces 355–362 are left out, 354 and 363 are not;
- the number of lines, over both surveys, with at least one gap: measure it and pin it with a comment (§17 measured 19 lines by fix-to-fix stretches; per-trace steps may differ slightly; report the measured value).

- [ ] **Step 2: Run them to see them fail.** core+pure command, `-k "spacing or gap_over"`. Expected: ImportError / AttributeError.
- [ ] **Step 3: Implement** `spacing.py`, `TrackPlacement.gap_m` and the save/load. Wrap the median and comparisons in `np.errstate` so a constant line raises no warning.
- [ ] **Step 4: Run core+pure in full.** Expected: all pass.
- [ ] **Step 5: Commit and push** (`feat(m17c): one gap rule for GPS lines, and Gap over on the track placement (#134)`).

---

### Task 2: Migration at true spacing

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/processing/base.py` (`Radargram`), `packages/nsgeo-core/src/nsgeo/processing/migration.py` (`MigrateFk.apply`), `packages/nsgeo-core/src/nsgeo/geometry/spacing.py` (resample helpers)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py` (`_attach_source`; `edit_lines` re-attaches), `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py` (the `work` job's `Radargram.from_profile`)
- Test: `packages/nsgeo-core/tests/test_steps_migration.py`, `packages/nsgeo-core/tests/test_spacing.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_session_gps_grids.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py`

**Interfaces:**
- Consumes: Task 1's `usual_step`, `gap_steps`, `left_out`, `TrackPlacement.gap_m`.
- Produces:
  - `Radargram.trace_x_m: np.ndarray | None = None` and `Radargram.gap_m: float | None = None`, after the existing fields. `__post_init__` raises `ValueError` when `trace_x_m` is given with a length other than `n_traces`. `replace()` keeps both.
  - `Radargram.from_profile(profile, *, trace_x_m=None, gap_m=None)`.
  - `spacing.resample_even(data, x_m, gap_m=None) -> tuple[np.ndarray, float, float]` — `(even, x0, step)`: columns at `x0 + k*step`, `step = usual_step(x_m)`, over the walk direction; each column linearly interpolated from the two nearest drawn traces (left-out traces are not used); 0 where the column lies inside a gap more than half a step from both edge traces.
  - `spacing.sample_back(even, x0, step, x_m) -> np.ndarray` — each trace's column, linearly interpolated at its own distance.
  - `MigrateFk.apply`: with `trace_x_m` given and not evenly spaced (steps equal to within `1e-9` relative), resample → `migrate_fk(..., dx_m=step)` → sample back; otherwise exactly today's call with `rg.dx_m`.
  - Plugin: `nsgeo_qgis.session.source_radargram(line: Line, profile: Profile) -> Radargram` — `Radargram.from_profile(profile, trace_x_m=line.distance_along(), gap_m=line.placement.gap_m)` for a `TrackPlacement`, `Radargram.from_profile(profile)` otherwise. Used by `_attach_source` and the slices engine's job. `edit_lines` re-attaches the source of every GPS line whose placement changed and emits `stack_changed` for it.

- [ ] **Step 1: Write the failing tests.**
  - `test_steps_migration.py`:
    - `test_an_even_trace_axis_migrates_exactly_as_dx` — same record with `dx_m=0.02` and with `trace_x_m=np.arange(n)*0.02`: `np.testing.assert_allclose(a, b, atol=1e-9 * np.abs(a).max())`.
    - `test_an_uneven_line_focuses_a_diffraction_where_an_even_one_does` — a point diffractor (apex 2.0 m, 20 ns, v = 0.1 m/ns) sampled at steps alternating 0.015 and 0.025 m with one 0.6 m gap 1 m from the apex; after migration the strongest column is the trace nearest 2.0 m (within one usual step), and its peak is at least 0.8× the evenly sampled migration's peak.
    - `test_migration_keeps_the_trace_axis` — `result.trace_x_m is rg.trace_x_m` and `result.gap_m == rg.gap_m`.
    - `test_a_trace_axis_of_the_wrong_length_is_refused`.
  - `test_spacing.py`:
    - `test_nothing_is_invented_inside_a_gap` — data 1.0 either side of a 1.0 m gap: every even column more than half a step from both edge traces is 0.
    - `test_left_out_traces_do_not_feed_the_resample` — left-out traces hold 1e6, the rest 1.0: `even.max() <= 1.0`.
    - `test_sample_back_returns_each_trace_at_its_own_distance` — `sample_back(*resample_even(d, x), x)` equals `d` on drawn traces to 1e-9 for data linear in x.
  - `test_plugin_session_gps_grids.py`:
    - `test_a_gps_lines_source_carries_its_walked_distance_and_gap_over` — `stack_for(key).source.trace_x_m` equals `line.distance_along()` and `.gap_m` the placement's; a tape line's source has `trace_x_m is None`.
    - `test_a_destagger_edit_reattaches_a_gps_lines_source` — a `TrackEdit` with `travel_shift=0.2`: the source's `trace_x_m` moves by 0.2, and `stack_changed` is emitted for the key.
  - `test_plugin_slices_engine.py`: `test_slices_build_a_gps_lines_record_with_its_walked_distance` — monkeypatch `session.source_radargram` to record its calls; preparing a grid holding a GPS line calls it with that line.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.** The resample's extent runs from the first to the last drawn trace; the walk direction follows the sign of `x_m[-1] - x_m[0]` so a falling distance resamples the same as its reverse.
- [ ] **Step 4: Run core+pure in full and the two QGIS files.** Expected: all pass.
- [ ] **Step 5: Commit and push** (`feat(m17c): GPS lines migrate at their true spacing, with nothing invented in a gap (#134)`).

---

### Task 3: The trace axis and the view transform in metres (Qt-free)

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/trace_axis.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_trace_axis.py` (new), `packages/nsgeo-qgis/tests/pure/test_pure_view_transform.py`

**Interfaces:**
- Consumes: Task 1's `gap_steps`, `left_out`, `usual_step`; `ui/ruler.py`'s `metres_at` / `trace_units_at` (the one road; do not write a second interpolation).
- Produces, in `trace_axis.py`:

```python
@dataclass(frozen=True, eq=False)
class TraceAxis:
    distance: np.ndarray            # metres along the line per trace, either direction
    gap_m: float | None = None
    @classmethod
    def from_distance(cls, distance: Any, gap_m: float | None = None) -> TraceAxis: ...
    #   ValueError for fewer than 2 traces, non-finite values, or a distance that turns back
    def walk_at(self, units: Any) -> Any: ...        # metres_at(distance, units) * sign: rises with units
    def units_at_walk(self, walk: Any) -> Any: ...   # the inverse, through trace_units_at
    def drawn(self) -> tuple[np.ndarray, np.ndarray]: ...  # per-trace [lo, hi) in walk metres; lo == hi when left out
    def trace_at_walk(self, w: float) -> int | None: ...   # the drawn trace holding w; None in a gap or past the ends
    def nearest_drawn(self, w: float) -> int: ...
    def runs(self) -> list[tuple[int, int, float, float]]: ...  # (first, last, lo, hi): adjoining drawn traces of equal width
```

  `sign` is +1 when `distance[-1] >= distance[0]`, else −1. A trace's `[lo, hi)` runs halfway to each neighbour, capped at half a usual step on a gap side; the end traces reach half their own step outward.
- Produces, in `view_transform.py`: `ViewTransform.axis: TraceAxis | None = None` (last field) and `fit(..., axis=None)`. With an axis:
  - `x_of_trace(u)` is linear in `axis.walk_at(u)` across the window `[walk_at(trace_lo), walk_at(trace_hi)]`, mirrored as today; `trace_of_x` is its inverse.
  - `_column_at` / `trace_at` use `trace_at_walk` (None in a gap); `trace_index_at` uses `nearest_drawn`; `traces_between` returns the drawn traces whose extents meet the span.
  - `zoomed`, `panned` and `true_scale_window` work in walk metres (the metre under the anchor stays put; a pan of `dx` pixels moves the window by `dx / width` of its metres; 1:1 narrows about the window's middle metre).
  - New `paint_spans() -> list[tuple[float, float, int, int]]` — `(x0, x1, first, last)` per visible run, clipped to the window, `x0 < x1` in local pixels; for a mirrored transform the caller flips each span's image.
  - With `axis=None` every method runs today's code, unchanged.

- [ ] **Step 1: Write the failing tests.**
  - `test_pure_trace_axis.py`: `test_an_even_axis_puts_trace_units_linearly`; `test_each_trace_reaches_halfway_to_its_neighbours` (steps 0.02 then 0.03: trace 1 drawn `[0.01, 0.035)` from distance `[0, 0.02, 0.05]`); `test_a_trace_reaches_half_a_usual_step_into_a_gap`; `test_left_out_traces_are_not_drawn` (`lo == hi`; `trace_at_walk` at the gap's middle is None); `test_runs_group_adjoining_equal_columns` (an even line is one run `(0, n-1, ...)`; one gap makes two; two spacings make three, the boundary trace its own run); `test_a_reversed_line_walks_the_same_way_as_its_forward_twin`; `test_repeated_distances_do_not_break_the_inverse` (finite results; `trace_at_walk` returns one of the repeated traces); `test_a_lift_at_the_first_step_draws_trace_0_half_a_step_wide`; `test_a_distance_that_turns_back_is_refused`.
  - `test_pure_view_transform.py`: `test_an_even_axis_matches_the_linear_transform` (20 positions, within 1e-9 px of `axis=None`); `test_x_is_linear_in_metres_along_the_line` (uneven axis: `x_of_trace(i + 0.5)` proportional to `distance[i] - walk_lo`); `test_hover_in_a_gap_finds_no_trace` (`trace_at` None, `trace_index_at` a neighbour); `test_zoom_keeps_the_metre_under_the_pointer`; `test_pan_moves_by_metres`; `test_a_window_edge_inside_a_gap_survives_zoom_and_pan` (no exception; panning 1 px moves the window's walk metres by `span / width` within 1e-9); `test_true_scale_is_exact_on_an_uneven_axis` (px per metre across equals px per metre down within 1 %); `test_paint_spans_cover_the_drawn_traces_and_skip_gaps` (no span overlaps a gap's middle; span widths sum to the drawn metres × px per metre within 1 px); `test_a_mirrored_axis_puts_the_last_trace_on_the_left`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** `TraceAxis` and the `ViewTransform` changes.
- [ ] **Step 4: Run core+pure in full.** Expected: all pass, including every existing view-transform and ruler test, unmodified.
- [ ] **Step 5: Commit and push** (`feat(m17c): a trace axis lays a GPS line out in metres, with its gaps (#134)`).

---

### Task 4: The profile draws a GPS line at true distance

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py` (`set_axes`, `paintEvent`, `readout_text`), `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (where `set_axes` is called for a line: `_set_axes_holding` / `_render`; `velocity_curve_points`)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_true_distance.py` (new; real-data tests marked as the other `real_data` tests are)

**Interfaces:**
- Consumes: Task 3's `TraceAxis`, `ViewTransform(axis=...)`, `paint_spans()`; Task 1's `TrackPlacement.gap_m`.
- Produces:
  - `ProfileView.set_axes(n_traces, n_samples, t0_ns, dt_ns, distance_along=None, ruler=None, *, axis: TraceAxis | None = None)`; the axis reaches `ViewTransform.fit`. An axis whose length is not `n_traces` is logged and dropped, as a wrong-length distance is today.
  - `paintEvent` with an axis: hatch the image rect as today, then one `drawImage` per `paint_spans()` entry (source columns `first*sx` to `(last+1)*sx`), each flipped about its own target when mirrored.
  - `readout_text()` over a gap: `{m:.2f} m along (gap)`.
  - `ProfileDock._trace_axis_for(line, distance) -> TraceAxis | None` — `TraceAxis.from_distance(distance, line.placement.gap_m)` for a `TrackPlacement` with a distance; None for tape lines, cuts and any failure (logged).
  - `velocity_curve_points` samples `_CURVE_SAMPLES` points evenly in metres between the line's ends (then converts to traces), not evenly in trace index.

- [ ] **Step 1: Write the failing tests.**
  - `test_plugin_profile_view.py`: `test_a_gap_is_hatched_and_the_traces_sit_at_their_distance` (a radargram of one strong value with a 1.0 m gap; `grab()` the widget: the pixel at the gap's middle is the background or hatch colour, the pixel at `x_of_trace(i + 0.5)` of a drawn trace is not); `test_the_readout_says_gap_over_a_gap`; `test_a_click_in_a_gap_picks_nothing` (pick mode: no `pick_requested`); `test_a_pick_on_a_left_out_trace_is_still_drawn` (`_pick_positions` holds it at its walked metre; right-click near it still offers removal as for any pick).
  - `test_plugin_profile_dock.py`: `test_a_gps_line_gets_a_trace_axis_with_its_gap_over`; `test_a_tape_line_gets_no_trace_axis` (and its transform's `x_of_trace` at 10 positions equals a `ViewTransform.fit` without an axis); `test_a_cut_gets_no_trace_axis`; `test_the_difference_view_keeps_the_trace_axis` (Difference on a GPS line: same axis, same gap); `test_the_fit_curve_is_sampled_evenly_in_metres` (metres between consecutive curve points: std / mean < 0.01 on a GPS line).
  - `test_plugin_profile_true_distance.py` (`real_data`): `test_file016s_lift_is_one_gap_in_its_profile` (open `with-dzg/FILE__016` as a GPS line the way the M17b real-data tests do: `trace_at` at the middle metre of the lift is None, traces 355–362 have zero drawn width, 354 and 363 are drawn); `test_file028s_lift_has_no_traces_left_out`; `test_a_tape_lines_profile_gets_no_axis` (a local tape line, e.g. `FILE__007`).
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `test_plugin_profile_view.py test_plugin_profile_dock.py test_plugin_profile_true_distance.py test_plugin_profile_cut.py`, then those with `-m real_data`, and core+pure. Expected: all pass; existing tests unmodified.
- [ ] **Step 5: Commit and push** (`feat(m17c): a GPS line's profile at true distance, a lift one hatched gap (#134)`).

---

### Task 5: Gap over in Edit lines, and the guide

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/line_edit.py` (`TrackEdit`), `packages/nsgeo-qgis/nsgeo_qgis/ui/edit_lines_dialog.py` (column, bulk row), `packages/nsgeo-qgis/nsgeo_qgis/session.py` (`edit_lines` applies it; Task 2's re-attach covers the source), `docs/guide/getting-started.md`
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_line_edit.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_edit_lines_gps.py`

**Interfaces:**
- Consumes: Task 1's `gap_threshold`, `TrackPlacement.gap_m`; Task 2's re-attach in `edit_lines`; Task 4's `_trace_axis_for`.
- Produces:
  - `TrackEdit.gap_m: float | None = None` (None leaves it unchanged) and `TrackEdit.gap_auto: bool = False` (True returns the line to automatic); `placed()` applies them (`gap_auto` wins).
  - Edit lines: a `COL_GAP` column headed `Gap over (m)`, right after `COL_DESTAGGER`, editable on GPS rows, "—" on tape rows (typing there is ignored, as GPS rows ignore Offset). The header tooltip is `GAP_TIP`. Automatic shows `auto {v:.2f}` with `v = gap_threshold(line.distance_along(), None)`; a typed value shows `{v:.2f}`. An empty cell returns the row to automatic; a value that is not finite and above 0 is refused with `{text!r} is not a length above 0; unchanged`.
  - A bulk row under Destagger: label `Gap over (m)`, a spin box (0.01–10.00, 2 decimals, step 0.01, default 0.10), `Set` and `Automatic` buttons acting on the selected GPS rows; selected tape rows are left alone and the status line says `TAPE_SKIP`.
  - The guide's GPS profile paragraph says: profiles draw each trace at its true distance; a lift is one hatched gap with the lifted traces left out; Gap over in Edit lines tunes it, automatic at 6× the line's usual step.

- [ ] **Step 1: Write the failing tests.**
  - `test_pure_line_edit.py`: `test_a_track_edit_sets_gap_over_and_returns_to_automatic`.
  - `test_plugin_edit_lines_gps.py`: `test_a_gps_row_shows_its_automatic_gap_over` (a synthetic GPS line at 60 traces/m: `auto 0.10`); `test_typing_gap_over_sets_it_and_clearing_returns_to_automatic`; `test_a_bad_gap_over_is_refused`; `test_a_tape_row_shows_a_dash_for_gap_over`; `test_bulk_set_and_automatic_act_on_gps_rows_and_skip_tape_rows` (status text is `TAPE_SKIP` with the count); `test_gap_over_extremes_reach_the_profile` (OK with 0.01 m, then 100 m: the open profile's `transform.axis.gap_m` follows, and the line's source `gap_m` likewise); `test_gap_over_survives_save_and_reopen`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement**, then update the guide.
- [ ] **Step 4: Run** the touched QGIS files (`test_plugin_edit_lines_gps.py test_plugin_edit_lines_dialog.py test_plugin_edit_lines_measure.py test_plugin_session_gps_grids.py`), `-m real_data`, core+pure and lint. Expected: all pass. Fix any existing Edit lines test that counted columns by index, naming each in the report.
- [ ] **Step 5: Commit and push** (`feat(m17c): Gap over in Edit lines tunes where a GPS profile shows a gap (#134)`).
