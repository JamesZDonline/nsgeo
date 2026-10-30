# Grid-Aligned Profiles Implementation Plan (#67)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every code task is written test-first with superpowers:test-driven-development: the failing test is run and seen to fail before any production code is written.

**Goal:** Every line on a grid is drawn against one shared ruler of metres along the grid. Reversed lines are mirrored, and zoom and pan carry over in metres from line to line, so a reflection stays in place as you sweep across a zigzag survey.

**Architecture:** `ViewTransform` stays in trace units and gains two things. A `mirrored` flag draws trace 0 on the right. Window `bounds` let the window run past the data. A new pure module, `ui/ruler.py`, owns the metres ↔ trace-unit maths and the per-grid `Ruler`. `ProfileView` draws through the transform: it mirrors the image, hatches blank space and puts ticks in grid metres, and every gesture resolves to the trace under the pointer or to nothing. `ProfileDock` works out each line's ruler from its grid and the grid's other lines, and carries the metre window across lines on the same ruler, previews included.

**Tech Stack:** Python 3, numpy; PyQt via `qgis.PyQt`; pytest on two tiers (core+pure in `.venv`, QGIS in `.venv-qgis`).

**Spec:** No separate spec file. The design was approved in chat on 2026-10-30 and is restated in full under "Design" below. Executors read that section as the spec. Issue #67 holds the original request. Where the two differ, this plan wins.

## Design (approved in chat, 2026-10-30)

What the user said:
- The user had found a reflection and swept the mouse across neighbouring lines on the map to follow it. On a zigzag survey the reflection jumped from the left of the profile to the right and back, because every other line was walked the other way.
- Every line should read the same way, so the reflection stays put during the sweep.
- When zoomed in on a reflection and sweeping across lines, the Profile should stay on the same stretch of ground on every line ("Yes").
- "I don't think there's any reason to see a reversed line drawn the way I walked it." So there is no toggle. The behaviour is always on.
- Approved the description below with "That all sounds good to me" and then "go for it".

Calls made by Claude and played back to the user without objection:
- Only the picture flips. Trace index stays the join between data and geometry (`nsgeo/geometry/placement.py`). Picks, selections, the map link, slices, velocity fits and saved sites keep counting traces in recorded order. Nothing in `SiteSession`, the core or the saved file changes.
- The low end of the grid goes on the left, the way a forward line already reads.
- The distance axis already shows metres along the grid on main (`GridPlacement.distance_along` is `start_along + direction × i / traces_per_metre`), so the issue's "label the axis in grid metres" bullet is already true. What changes is that the numbers now rise left to right on every line and carry on across blank space.
- **One ruler per grid and axis:** `[0, the grid's size along the lines]`, widened to take in any line on that grid and axis that runs past the edge. A line shorter than the ruler leaves blank space at its end instead of being stretched to fill the panel. At full view, a given metre sits at the same pixel on every line.
- **The window is held in metres along the grid,** and the time window is held too, when the Profile moves to another line on the same grid running the same way. This applies to opening a line and to the map hover preview alike. Moving to a line on another grid, or to a cross-line on the other axis, starts at Fit.
- **Fit shows the whole ruler.** Pan and zoom can go anywhere along it, including past the end of a short line.
- **Blank space does nothing.** Hover, a pick click and a velocity click there produce nothing, with no snapping onto the last trace. A drag-select that runs off the end of a line stops at the last trace.
- The arrow next to the distance axis shows which way the line was walked, so a mirrored line shows ←.
- A line with no distance axis keeps today's view: its own length, counted in traces, never mirrored.
- Every gesture is covered on a mirrored line: hover and the map cursor, drag-select, pick clicks, velocity-fit clicks and right-click discards, wheel zoom, middle-drag pan, Fit, 1:1 and the cutoff drag.

Calls made while writing this plan. Check these:
- **Each trace is drawn centred on its own ground position.** Trace `i`'s column spans `distance[i] ± half a trace spacing`, in both directions. Today the tick for `distance[i]` sits on the column's left edge. That half-trace offset is harmless on one line, but it would put a forward and a reversed line a whole trace apart. So ticks move by half a trace (about 8 mm at 60 traces/m). The cursor, picks and fit curves are already drawn at `trace + 0.5`, so they now sit exactly on their metre.
- **Blank space is a light diagonal hatch** (`NO_DATA_HATCH`, grey 200, `BDiagPattern`) over the panel background, so it can't be read as data in any colour table. This is a walkthrough check.
- **Caption:** a line on a ruler reads `m along grid · walked ←` (or `→`). A line without one keeps today's `m along line →` / `trace along line →`.
- **A drag-select that covers only blank space clears the selection,** the same as a plain click: `selection_cleared` fires and `range_selected` doesn't.
- **The hold reads the window off the line being left.** No separate window is remembered. Every line on a ruler has the same bounds in metres, so the horizontal window never clamps. The time window is clamped into each line's record, so a line with a shorter record narrows the time window for the lines after it.
- **Re-rendering the same line** (a stack, display or channel change with the same shape) keeps the exact transform object, as today. When the same line's sample count changes, for example after adding `time_zero`, today's code refits. On a ruled line the hold applies instead: the horizontal zoom stays and the time window is clamped into the new record. This is a small change from today.
- **The ruler follows edits.** On `grids_changed` and `lines_changed`, a displayed line whose ruler has changed is shown again with the window held, so Fit follows a grid resize or an import without reopening the line.
- `_trace_to_metres` and `_metres_to_trace` move out of `profile_dock.py` into the new pure module as `trace_to_metres` and `metres_to_trace`, unchanged, so the view and the pure tier can use them.

## Global Constraints

- `nsgeo_qgis/ui/ruler.py` and `nsgeo_qgis/ui/view_transform.py` import no Qt and no `qgis`. The pure tier imports both. `ui/__init__.py` stays empty for that reason.
- Nothing outside the Profile panel's drawing changes meaning. A trace index stays a trace index everywhere: signals, `SiteSession`, picks, selections, slices, saved files.
- The plugin imports Qt only through `qgis.PyQt`. `packages/nsgeo-core/tests/test_boundary.py` and `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py` must stay green.
- Every slot connected to a signal, and every Qt-invoked override, guards its own body and reports through `_log`. It never raises. `paintEvent` keeps its `try/finally` around `painter.end()`. Read the module docstrings of `profile_view.py` and `profile_dock.py` before touching either file.
- Pan and zoom never rebuild the image. Mirroring is a painter transform at draw time, not a mirrored copy made per frame.
- ruff 0.17.1 and mypy 2.4.0, as pinned in CI. `ui/ruler.py` joins the CI mypy file list in `.github/workflows/ci.yml`.

## Verification commands (exactly these)

- core + pure: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q`. Baseline at `7069959`: 808 passed, 3 skipped.
- qgis: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:xonsh`. Baseline at `7069959`: still running when this plan was committed. The count is filled in before Task 1 starts.
- lint: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- types: `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`

The worktree is `.worktrees/nsgeo-grid-profiles` on branch `nsgeo-grid-profiles`, off main `7069959`. Its own `.venv` and `.venv-qgis` are built, and the real DZT files are symlinked into `packages/nsgeo-core/tests/data/local/`. A real-data test that skips has validated nothing, so check the skip count.

## Review Focus

These are the input classes most likely to hurt a user that the main tests don't cover on their own. Each is pinned by a test in the task named.

1. **A zoom window lying entirely in blank space** (zoomed past the end of a long line, then sweeping onto a short one). The panel must show hatch and axes, paint nothing from the image, and raise nothing. Hover and clicks do nothing (Task 1: `test_a_window_in_blank_space_has_an_empty_source`; Task 2: `test_a_window_entirely_in_blank_space_paints_without_error`).
2. **Two lines on one grid with different traces per metre** (a second instrument, or a recalibrated wheel). The held window must stay the same in metres, not in traces (Task 3: `test_the_hold_is_in_metres_across_different_trace_spacings`).
3. **Moving from a ruled line to a line with no distance axis, and back** (a time-triggered file). The Profile must not mirror it, must not carry a window onto it and must not raise. Coming back starts at Fit (Task 3: `test_a_line_without_distance_neither_mirrors_nor_holds`).
4. **The difference view on a mirrored line.** The Profile must stay mirrored and keep its metre window when the difference toggles on and off (Task 3: `test_the_difference_view_keeps_the_mirror_and_the_window`).
5. **A preview of a line whose samples are not loaded yet.** This is the first hover over each line in a sweep. The header-only axes must already be ruled and held, and the load that follows must not jump the window (Task 3: `test_a_header_only_preview_is_ruled_and_held_through_its_load`).

---

### Task 1: The pure mapping (mirror, bounds, ruler)

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (delete `_trace_to_metres`/`_metres_to_trace`, import the moved functions from `ruler`, and update their three call sites)
- Modify: `.github/workflows/ci.yml` (add `packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py` to the mypy list)
- Test: modify `packages/nsgeo-qgis/tests/pure/test_pure_view_transform.py`
- Test: create `packages/nsgeo-qgis/tests/pure/test_pure_ruler.py`

**Interfaces:**
- Produces, in `ui/ruler.py`:
  - `trace_to_metres(distance, traces)` and `metres_to_trace(distance, x_m)`: `profile_dock._trace_to_metres`/`_metres_to_trace` moved verbatim, with docstrings, renamed public. Both extrapolate past either end.
  - `trace_units_at(distance, metres)`: the `ViewTransform` horizontal coordinate of a ground position. Trace `i`'s column is `[i, i + 1)` and its centre `i + 0.5` lies on `distance[i]`, so this returns `metres_to_trace(distance, metres) + 0.5`. It extrapolates.
  - `metres_at(distance, trace_units)`: the inverse, `trace_to_metres(distance, trace_units - 0.5)`.
  - `is_reversed(distance) -> bool`: `True` when the distance falls as traces rise (`distance[-1] < distance[0]`).
  - `@dataclass(frozen=True) class Ruler` with `grid_id: str`, `axis: str`, `lo_m: float`, `hi_m: float`, and a property `key -> tuple[str, str]` returning `(grid_id, axis)`.
  - `ruler_for(grid: Grid, axis: str, distances: Iterable[np.ndarray]) -> Ruler`: starts from `(0.0, grid.size_x if axis == "x" else grid.size_y)` and widens to cover each array's columns, `[min(d) - h, max(d) + h]` with `h = abs(d[1] - d[0]) / 2`. Arrays shorter than two are ignored.
  - `bounds_on(ruler: Ruler, distance) -> tuple[float, float]`: the ruler's ends in this line's trace units, sorted ascending.
- Produces, in `ViewTransform`:
  - New trailing fields `mirrored: bool = False` and `bounds: tuple[float, float] | None = None`. `None` means `(0.0, float(n_traces))`.
  - `fit(cls, n_traces, n_samples, t0_ns, dt_ns, width, height, *, bounds=None, mirrored=False)`. The window starts at the bounds.
  - Property `trace_bounds -> tuple[float, float]`.
  - `trace_at(x: float) -> int | None`: the trace whose column holds local pixel `x`, or `None` past the data.
  - `traces_between(x0: float, x1: float) -> tuple[int, int] | None`: the data traces whose columns the span touches, as an ascending `(a, b)` clamped into the data, or `None` when the span misses the data. Argument order doesn't matter.
  - `target_span() -> tuple[float, float]`: the ascending local x range that `source_rect()` lands on.
  - `one_to_one() -> ViewTransform`: one trace per pixel column, keeping the trace at the screen's left edge where it is.
  - Changed:
    - `x_of_trace`/`trace_of_x` honour `mirrored`.
    - `trace_index_at` stays clamped into the data and is mirror-aware.
    - `source_rect()` returns only the visible part of the data. Its width is 0 when the window is all blank.
    - `with_window` clamps to `trace_bounds`, not `[0, n_traces]`.
    - `zoomed` and `panned` are mirror-aware.
    - `resized` keeps both new fields.

- [ ] **Step 1: Write the failing ruler tests** in `test_pure_ruler.py`. Use `Grid("A", (0.0, 0.0), 0.0, 5.0, 11.0, "EPSG:32616", 0.5)`, `H = 1 / 120` (half a trace at 60/m), `FWD = np.arange(666) / 60.0` and `REV = 11.0 - np.arange(606) / 60.0`. Those are the longest forward and shortest reversed local lines placed the way the import places a zigzag.

```python
def test_a_trace_sits_at_its_column_centre_in_either_direction():
    assert trace_units_at(FWD, 0.0) == pytest.approx(0.5)
    assert trace_units_at(FWD, FWD[3]) == pytest.approx(3.5)
    assert trace_units_at(REV, 11.0) == pytest.approx(0.5)
    assert trace_units_at(REV, REV[3]) == pytest.approx(3.5)
    assert metres_at(REV, 0.0) == pytest.approx(11.0 + H)  # trace 0's column edge, beyond the start

def test_the_unit_maps_extrapolate_and_round_trip():
    for d in (FWD, REV):
        for m in (-2.0, 0.3, 5.0, 12.5):
            assert metres_at(d, trace_units_at(d, m)) == pytest.approx(m)
    assert trace_units_at(REV, 12.0) == pytest.approx(0.5 - 60.0)

def test_is_reversed_reads_the_distance_not_a_flag():
    assert not is_reversed(FWD) and is_reversed(REV)

def test_the_ruler_is_the_grid_widened_to_every_line():
    r = ruler_for(GRID, "y", [FWD, REV])
    assert (r.grid_id, r.axis, r.key) == ("A", "y", ("A", "y"))
    assert r.lo_m == pytest.approx(-H)
    assert r.hi_m == pytest.approx(665 / 60.0 + H)

def test_a_ruler_with_no_lines_is_the_grid_along_that_axis():
    assert (ruler_for(GRID, "y", []).lo_m, ruler_for(GRID, "y", []).hi_m) == (0.0, 11.0)
    assert ruler_for(GRID, "x", [np.array([1.0])]).hi_m == 5.0  # a one-trace line has no spacing

def test_bounds_put_both_lines_on_the_same_metres():
    r = ruler_for(GRID, "y", [FWD, REV])
    assert bounds_on(r, FWD) == pytest.approx((0.0, 666.0))
    assert bounds_on(r, REV) == pytest.approx((-5.0, 661.0))
```

- [ ] **Step 2: Run them and see them fail.** Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_ruler.py -q`. Expected: FAIL with `ModuleNotFoundError: No module named 'nsgeo_qgis.ui.ruler'`.

- [ ] **Step 3: Write `ui/ruler.py`** to the interface above. Move the two functions out of `profile_dock.py` and point its three call sites at the new names. Write a module docstring stating the column-centre convention and why: it is what lines up a forward line and a reversed line.

- [ ] **Step 4: Run them and see them pass.** Same command. Expected: 6 passed.

- [ ] **Step 5: Write the failing `ViewTransform` tests** in `test_pure_view_transform.py`. Every existing test there must keep passing unchanged, because the defaults reproduce today's behaviour. Add these, with `MIR = ViewTransform.fit(n_traces=608, n_samples=512, t0_ns=-11.09, dt_ns=0.2165, width=800, height=300, mirrored=True)` and `B = ViewTransform.fit(608, 512, -11.09, 0.2165, 800, 300, bounds=(-100.0, 668.0))`:

```python
def test_a_mirrored_fit_puts_the_last_trace_on_the_left():
    assert MIR.x_of_trace(608) == 0.0 and MIR.x_of_trace(0) == 800.0
    assert MIR.trace_index_at(0.0) == 607 and MIR.trace_index_at(799.9) == 0
    for x in (0.0, 123.4, 799.0):
        assert MIR.x_of_trace(MIR.trace_of_x(x)) == pytest.approx(x)

def test_mirrored_index_lookups_use_the_screen_left_edge():
    z = MIR.with_window(100.0, 110.0, 0.0, 20.0)  # 80 px per trace, trace 109 leftmost
    assert [z.trace_index_at(x) for x in (0.0, 41.0, 79.9, 80.0, 80.1)] == [109, 109, 109, 108, 108]
    assert z.trace_index_at(z.x_of_trace(106) + 0.1) == 105  # trace 105 spans x_of_trace(106)..x_of_trace(105)

def test_mirrored_zoom_keeps_the_point_under_the_anchor_fixed():
    before = MIR.trace_of_x(600.0)
    z = MIR.zoomed(2.0, anchor_x=600.0, anchor_y=100.0)
    assert z.trace_of_x(600.0) == pytest.approx(before)
    assert z.trace_hi - z.trace_lo == pytest.approx(304.0)

def test_mirrored_pan_moves_the_data_with_the_pointer():
    z = MIR.with_window(100.0, 300.0, 0.0, 20.0)
    p = z.panned(-100.0, 0.0)  # drag left 100 px = 25 traces at 4 px/trace
    assert (p.trace_lo, p.trace_hi) == pytest.approx((75.0, 275.0))
    assert p.x_of_trace(150.0) == pytest.approx(z.x_of_trace(150.0) - 100.0)

def test_the_window_may_cover_the_bounds_not_just_the_data():
    assert (B.trace_lo, B.trace_hi) == (-100.0, 668.0) and B.trace_bounds == (-100.0, 668.0)
    assert (B.zoomed(0.5, 400.0, 150.0).trace_lo, B.zoomed(0.5, 400.0, 150.0).trace_hi) == (-100.0, 668.0)
    far = B.with_window(200.0, 400.0, 0.0, 20.0).panned(100_000.0, 0.0)
    assert (far.trace_lo, far.trace_hi) == (-100.0, 100.0)
    assert FIT.trace_bounds == (0.0, 608.0)

def test_trace_at_is_none_past_the_data_in_either_direction():
    for t in (B, dataclasses.replace(B, mirrored=True)):
        assert t.trace_at(t.x_of_trace(-30.0)) is None
        assert t.trace_at(t.x_of_trace(0.5)) == 0
        assert t.trace_at(t.x_of_trace(607.5)) == 607
        assert t.trace_at(t.x_of_trace(608.5)) is None

def test_traces_between_clamps_into_the_data_and_misses_blank_space():
    for t in (B, dataclasses.replace(B, mirrored=True)):
        x = t.x_of_trace
        assert t.traces_between(x(-30.0), x(10.5)) == (0, 10)
        assert t.traces_between(x(10.5), x(-30.0)) == (0, 10)
        assert t.traces_between(x(600.5), x(650.0)) == (600, 607)
        assert t.traces_between(x(-50.0), x(-10.0)) is None

def test_source_rect_and_target_span_cover_only_the_data():
    assert B.source_rect()[0] == 0.0 and B.source_rect()[2] == 608.0
    assert B.target_span() == pytest.approx((100 / 768 * 800, 708 / 768 * 800))
    m = dataclasses.replace(B, mirrored=True)
    assert m.target_span() == pytest.approx((60 / 768 * 800, 668 / 768 * 800))
    assert FIT.target_span() == (0.0, 800.0)

def test_a_window_in_blank_space_has_an_empty_source():
    z = B.with_window(-100.0, -50.0, 0.0, 20.0)
    assert z.source_rect()[2] == 0.0
    assert z.trace_at(400.0) is None and z.traces_between(0.0, 799.0) is None

def test_one_to_one_keeps_the_screen_left_edge():
    w = ViewTransform.fit(2000, 512, -11.09, 0.2165, 800, 300)
    plain = w.with_window(500.0, 700.0, 0.0, 20.0).one_to_one()
    assert (plain.trace_lo, plain.trace_hi) == (500.0, 1300.0)
    m = dataclasses.replace(w, mirrored=True).with_window(1000.0, 1200.0, 0.0, 20.0).one_to_one()
    assert (m.trace_lo, m.trace_hi) == (400.0, 1200.0)

def test_resized_keeps_the_mirror_and_the_bounds():
    r = dataclasses.replace(B, mirrored=True).resized(400, 150)
    assert r.mirrored and r.bounds == (-100.0, 668.0)

def test_bounds_must_be_finite_and_ordered():
    for bad in ((5.0, 5.0), (10.0, 0.0), (float("nan"), 10.0), (0.0, float("inf"))):
        with pytest.raises(ValueError, match="bounds"):
            ViewTransform.fit(608, 512, -11.09, 0.2165, 800, 300, bounds=bad)
```

- [ ] **Step 6: Run them and see them fail.** Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_view_transform.py -q`. Expected: FAIL with `TypeError: ... unexpected keyword argument 'mirrored'`.

- [ ] **Step 7: Implement the `ViewTransform` changes.** All three lookups (`trace_index_at` clamped, `trace_at` → `None`, `traces_between`) share one private, unclamped column lookup. That lookup is `floor(trace_of_x(x))` normally and `ceil(trace_of_x(x)) - 1` when mirrored, which keeps the screen-left-edge convention. `__post_init__` rejects non-finite or unordered `bounds` with a `ValueError` naming `bounds`. Mirrored maps:

```python
# x_of_trace, mirrored:  (self.trace_hi - i) / span * self.width
# trace_of_x, mirrored:  self.trace_hi - x / self.width * span
# zoomed, mirrored:      hi' = at + fx * t_span; lo' = hi' - t_span   (at = trace_of_x(anchor_x))
# panned, mirrored:      the window moves by +dx/width*span, not -dx/width*span
```

  Update the module docstring: the window is `[trace_lo, trace_hi)` within `trace_bounds`, and a mirrored transform draws `trace_hi` at x = 0.

- [ ] **Step 8: Run both test files and see them pass.** Then run the full core+pure tier, lint and types. The core+pure count rises by 18. Also run `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_velocity_fit.py -q -p no:xonsh`, because the moved helpers are used there. Expected: all pass.

- [ ] **Step 9: Commit and push.**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py \
  packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py packages/nsgeo-qgis/tests/pure .github/workflows/ci.yml
git commit -m "feat(plugin): a mirrored, ruler-bounded ViewTransform and the grid ruler (#67)"
git push -u origin nsgeo-grid-profiles
```

---

### Task 2: `ProfileView` draws and handles gestures on the ruler

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py`
- Test: modify `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py`

**Interfaces:**
- Consumes: everything Task 1 produces.
- Produces:
  - `ProfileView.set_axes(n_traces, n_samples, t0_ns, dt_ns, distance_along=None, ruler: Ruler | None = None) -> None`. A ruler takes effect only alongside a valid `distance_along` of length ≥ 2. The view then fits to `bounds_on(ruler, distance)` with `mirrored=is_reversed(distance)`. Otherwise the ruler is dropped (stored as `None`) and the view behaves exactly as today.
  - Property `ProfileView.ruler -> Ruler | None`.
  - `ProfileView.window_m() -> tuple[float, float] | None`: the window's ends in metres, ascending. `None` without a ruler.
  - `ProfileView.set_window_m(lo_m: float, hi_m: float, time_lo: float, time_hi: float) -> None`: sets the window from metres through `with_window`, which clamps it. Emits `view_changed`. Does nothing without a ruler.
  - `ProfileView._distance_caption() -> str`, factored out of `_paint_axes` the way `_time_ticks` was.
  - Module constant `NO_DATA_HATCH = QColor(200, 200, 200)`.
- Behaviour contract:
  - **Painting.** Hatch the image rect with `QBrush(NO_DATA_HATCH, Qt.BrushStyle.BDiagPattern)`, then draw `source_rect()` into `target_span()`. When `mirrored`, flip it with `painter.save()`/`translate`/`scale(-1, 1)`/`restore()`. Draw nothing from the image when the source width is 0.
  - **Selection.** `_selection_bounds` returns its two x values in ascending order.
  - **Ticks.** `_distance_ticks` takes the visible window in metres via `metres_at` at `trace_lo` and `trace_hi`, so ticks run on across blank space. It places each tick at `x_of_trace(trace_units_at(d, tick))`. The no-distance branch is unchanged.
  - **Gestures.**
    - Hover emits `trace_hovered` only when `trace_at(x)` is not `None`.
    - A pick click and a velocity click emit only when `trace_at(x)` is not `None`.
    - A drag-select uses `traces_between(press_x, x)`. If that is `None`, the band is cleared, and the release counts as a plain click: `clear_selection()` plus `selection_cleared`, never `range_selected`.
    - Wheel zoom, middle-drag pan and the cutoff drag need no change of their own beyond Task 1. The cutoff grabs anywhere across the image rect, blank space included.
  - **Buttons.** `fit()` keeps `bounds` and `mirrored`. `one_to_one()` calls `ViewTransform.one_to_one()`. `clear()` drops the ruler.

- [ ] **Step 1: Write the failing tests.** The file has no pixel-to-event helper yet, so add `_local(v, x, y)` returning `QPoint(round(r.left() + x), round(r.top() + y))` for `r = v.image_rect()`, as `test_plugin_velocity_fit.py` has. Also add `LEFT`, `RIGHT`, `NO_MOD` and `SHIFT` for the buttons and modifiers, and `import nsgeo_qgis.ui.profile_view as profile_view_module` for the `_log` patch. Add a fixture `ruled(make_view)` sized like `view`: 800 × (264 + MARGIN_TOP + 28), so the image rect is 696 × 264. Use `rg = _rg()` (200 traces) and `D = 4.0 - np.arange(200) / 60.0`, a reversed line walked from 4 m. Set `R = Ruler("A", "y", -1.0, 5.0)`, call `v.set_axes(..., distance_along=D, ruler=R)`, and give it an image whose columns 0–99 are white and 100–199 are black (a hand-built `QImage`). Its bounds are `(-59.5, 300.5)`, so the data spans local x ≈ 194–581, with blank space on both sides.

```python
def test_a_ruled_reversed_line_is_mirrored_on_its_bounds(ruled):
    v = ruled
    assert v.ruler == R and v.transform.mirrored
    assert (v.transform.trace_lo, v.transform.trace_hi) == pytest.approx((-59.5, 300.5))

def test_the_mirrored_image_puts_the_last_trace_on_the_left(ruled):
    v = ruled; shot = v.grab_image(); r = v.image_rect(); t = v.transform; mid_y = r.top() + 130
    assert QColor(shot.pixel(int(r.left() + t.x_of_trace(190.5)), mid_y)).red() < 60   # trace 190: black
    assert QColor(shot.pixel(int(r.left() + t.x_of_trace(5.5)), mid_y)).red() > 200    # trace 5: white
    blank = QColor(shot.pixel(r.left() + 40, mid_y))
    assert blank in (BACKGROUND, NO_DATA_HATCH)

def test_cursor_picks_and_selection_sit_on_their_traces_when_mirrored(ruled):
    v = ruled; t = v.transform
    v.set_picks([(10, 0.0)])
    (px, _), = v._pick_positions(t)
    assert t.x_of_trace(11) < px < t.x_of_trace(10)
    v.set_selection(10, 20)
    assert v._selection_bounds(t) == pytest.approx((t.x_of_trace(21), t.x_of_trace(10)))

def test_hover_reports_the_trace_under_the_pointer_and_nothing_over_blank_space(ruled):
    v = ruled; heard = []; v.trace_hovered.connect(heard.append)
    send_hover(v, _local(v, v.transform.x_of_trace(150.5), 100))
    send_hover(v, _local(v, 40, 100))
    assert heard == [150]

def test_picks_and_velocity_clicks_in_blank_space_do_nothing(ruled):
    v = ruled; picks, points = [], []
    v.pick_requested.connect(lambda tr, ns: picks.append(tr))
    v.velocity_point_requested.connect(lambda tr, ns: points.append(tr))
    QTest.mouseClick(v, LEFT, SHIFT, _local(v, 40, 100))
    QTest.mouseClick(v, LEFT, SHIFT, _local(v, v.transform.x_of_trace(42.5), 100))
    v.set_velocity_fit_mode(True)
    QTest.mouseClick(v, LEFT, NO_MOD, _local(v, 40, 100))
    QTest.mouseClick(v, LEFT, NO_MOD, _local(v, v.transform.x_of_trace(42.5), 100))
    assert picks == [42] and points == [42]

def test_a_right_click_discards_the_fit_point_under_it_when_mirrored(ruled):
    v = ruled; gone = []; v.velocity_point_discarded.connect(gone.append)
    v.set_velocity_fit_mode(True)
    v.set_velocity_fit([(20, 10.0), (150, 10.0)], [])
    QTest.mouseClick(v, RIGHT, NO_MOD, _local(v, v.transform.x_of_trace(150.5), v.transform.y_of_time(10.0)))
    assert gone == [1]

def test_a_drag_off_the_end_stops_at_the_last_trace(ruled):
    v = ruled; got = []; v.range_selected.connect(lambda a, b: got.append((a, b)))
    QTest.mousePress(v, LEFT, NO_MOD, _local(v, v.transform.x_of_trace(150.5), 100))
    send_move_while_pressed(v, _local(v, 40, 100))   # left of the data = past trace 199
    QTest.mouseRelease(v, LEFT, NO_MOD, _local(v, 40, 100))
    assert got == [(150, 199)]

def test_a_drag_across_only_blank_space_clears_like_a_click(ruled):
    v = ruled; v.set_selection(10, 20); got, cleared = [], []
    v.range_selected.connect(lambda a, b: got.append((a, b))); v.selection_cleared.connect(lambda: cleared.append(1))
    QTest.mousePress(v, LEFT, NO_MOD, _local(v, 20, 100))
    send_move_while_pressed(v, _local(v, 120, 100))
    QTest.mouseRelease(v, LEFT, NO_MOD, _local(v, 120, 100))
    assert got == [] and cleared == [1] and v._selection == (-1, -1)

def test_wheel_and_middle_drag_follow_the_pointer_when_mirrored(ruled):
    # wheel one notch in at x_of_trace(100.0): trace_of_x at that x is unchanged.
    # middle-press at X, move to X - 50: the trace that was under X is now under X - 50.
    ...

def test_fit_and_one_to_one_keep_the_ruler_and_the_mirror(ruled):
    v = ruled; r = v.image_rect()
    v.zoom_at(4.0, r.width() / 2, r.height() / 2); v.fit()
    assert v.transform.mirrored and (v.transform.trace_lo, v.transform.trace_hi) == pytest.approx((-59.5, 300.5))
    left = v.transform.trace_hi
    v.one_to_one()
    assert v.transform.trace_hi == pytest.approx(left) and v.transform.mirrored

def test_distance_ticks_rise_left_to_right_across_blank_space(ruled):
    v = ruled; t = v.transform
    ticks = v._distance_ticks(t)
    values = [float(label) for label, _ in ticks]; xs = [x for _, x in ticks]
    assert values == sorted(values) and xs == sorted(xs)
    assert values[0] <= -0.5 and values[-1] >= 4.5        # ticks over the blank space at both ends
    label, x = next((l, x) for l, x in ticks if float(l) == 2.0)
    assert x == pytest.approx(t.x_of_trace(trace_units_at(D, 2.0)))

def test_window_m_round_trips_and_emits_view_changed(ruled):
    v = ruled; changed = []; v.view_changed.connect(lambda: changed.append(1))
    v.set_window_m(1.0, 2.0, v.transform.time_lo, v.transform.time_hi)
    assert v.window_m() == pytest.approx((1.0, 2.0)) and changed

def test_the_caption_names_grid_metres_and_the_walking_direction(ruled, view):
    ruled.set_direction(-1)
    assert ruled._distance_caption() == "m along grid · walked ←"
    plain, _ = view
    assert plain._distance_caption() == "m along line →"

def test_the_cutoff_can_be_dragged_from_blank_space(ruled):
    # set_cutoff mid-record; press on the line at local x = 40 (blank), drag 30 px up, release:
    # cutoff_dragged fires once with a time earlier than the start value.
    ...

def test_a_window_entirely_in_blank_space_paints_without_error(ruled, monkeypatch):
    v = ruled; logged = []
    monkeypatch.setattr(profile_view_module, "_log", lambda *a, **k: logged.append(a))
    v.set_window_m(-0.9, -0.5, v.transform.time_lo, v.transform.time_hi)
    v.grab_image()
    assert logged == [] and v.transform.source_rect()[2] == 0.0

def test_set_axes_drops_a_ruler_without_a_distance(make_view):
    v = make_view(); v.resize(800, 300)
    v.set_axes(200, 128, -4.0, 0.5, None, R)
    assert v.ruler is None and not v.transform.mirrored and v.transform.bounds is None
```

  Write the two `...` bodies as their comments say, with `send_move_while_pressed(..., held_button=Qt.MouseButton.MiddleButton)` for the pan. `_local`, `LEFT`, `NO_MOD` and `SHIFT` follow the helpers already in the file.

- [ ] **Step 2: Run them and see them fail.** Run: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py -q -p no:xonsh`. Expected: the new tests fail, with `TypeError: set_axes() takes ... positional arguments` or `ImportError: cannot import name 'NO_DATA_HATCH'`. Every existing test still passes.

- [ ] **Step 3: Implement the view half** to the behaviour contract. Add a paragraph to the module docstring covering mirroring, bounds, blank space, and the rule that the trace index never changes meaning.

- [ ] **Step 4: Run the file and see it all pass.** Then run the whole QGIS tier. Expected: full pass. The dock passes no ruler yet, so nothing outside this file changes behaviour. A failure elsewhere means a default changed.

- [ ] **Step 5: Commit and push.**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py
git commit -m "feat(plugin): the profile draws mirrored lines on the grid ruler, gestures included (#67)"
git push
```

---

### Task 3: `ProfileDock` rules each line and holds the window across lines

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`
- Modify: `docs/guide/getting-started.md` (the **nsgeo Profile** bullet)
- Test: modify `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py`
- Test: modify whichever existing QGIS tests fail only because their fixture lines now sit on a ruler (see Step 6)

**Interfaces:**
- Consumes: `Ruler`, `ruler_for`, and `ProfileView.set_axes(..., ruler)`, `.ruler`, `.window_m()`, `.set_window_m(...)` from Tasks 1–2.
- Produces:
  - `ProfileDock._ruler_for(line, distance) -> Ruler | None`. Returns `None` when `distance` is `None` or shorter than two, when the line has no grid (`session.grid_for_line` returns `None`), or when its placement has no `axis`. Otherwise it returns `ruler_for(grid, axis, ...)` over the `_safe_distance` of every line in `session.keys_on_grid(grid.id)` that has the same `axis`.
  - `ProfileDock._set_axes_holding(key: str, n_traces: int, n_samples: int, t0_ns: float, dt_ns: float, distance) -> None`. This is the only place the dock sets the view's axes. Both `_show_line`'s header-only branch and `_render` call it.
  - `ProfileDock._axes_key: str | None`: the key the view's axes were last set for. `_clear_view_only` resets it to `None`.
  - `ProfileDock._on_geometry_changed() -> None`, connected to `session.grids_changed` and `session.lines_changed`.
- Behaviour contract for `_set_axes_holding`. Before calling `set_axes`, capture `old = view.transform`, `old_ruler = view.ruler`, `old_m = view.window_m()` and `old_key = self._axes_key`. Then work through these rules in order:
  1. Same key, and the new transform's `(n_traces, n_samples, bounds, mirrored)` equals the old one's → put `old` back (the exact object, as `test_rerender_with_the_same_shape_keeps_the_current_zoom` pins).
  2. The new ruler and the old ruler are both not `None`, with equal `key`, and `old_m` is not `None` → `view.set_window_m(*old_m, old.time_lo, old.time_hi)`.
  3. No ruler now, and `old` has the same `(n_traces, n_samples)` → put `old` back. This is today's rule, kept for lines without a ruler.
  4. Otherwise leave the fresh fit.

  Then set `_axes_key = key`. `_render` drops its own `keep_window` logic. `_on_geometry_changed` returns early when no line is displayed or the site is closed. When `_ruler_for` on the displayed line differs from `view.ruler`, it calls `_show_line(self._key, is_preview=self._preview_key is not None)`. It swallows `KeyError` for a line removed in the same change, and guards its body like every slot here.

- [ ] **Step 1: Write the failing dock tests** in `test_plugin_profile_dock.py`. The `opened` fixture's line is reversed (`GridPlacement("A", "y", 0.0, 0.0, -1, ...)`, 240 traces, so it runs from 0 m down to −3.98 m) on `GRID` (size_y 11).

```python
def test_a_reversed_line_is_mirrored_against_its_grid_ruler(opened):
    session, dock, key, line = opened
    v = dock.view
    assert (v.ruler.grid_id, v.ruler.axis, v.ruler.hi_m) == ("A", "y", 11.0)
    assert v.ruler.lo_m == pytest.approx(-239 / 60 - 1 / 120)  # the line runs past the grid's 0 edge
    assert v.transform.mirrored

def test_the_same_metre_is_at_the_same_pixel_on_neighbouring_lines(opened):
    # add a forward 300-trace line on A at offset 0.5; record x of metre 2.0 on the opened line
    # (view.transform.x_of_trace(trace_units_at(distance, 2.0))), open the forward line, compare: abs diff < 0.5 px.

def test_zoom_is_held_in_metres_when_the_next_line_opens(opened):
    # zoom_at(4.0, ...) on the opened line; m = view.window_m(); t = (time_lo, time_hi);
    # open the forward line: view.window_m() == approx(m), time window == approx(t), not mirrored.

def test_the_hold_survives_a_preview_and_its_end(opened):
    # zoom; m = window_m(); session.set_preview(forward_key, 5): window_m() == approx(m);
    # session.set_preview("", -1): window_m() == approx(m) and mirrored again.

def test_a_header_only_preview_is_ruled_and_held_through_its_load(opened):
    # forward line with NO set_profiles; zoom on the opened line; preview it: view.ruler is not None,
    # window_m() == approx(m); then session.set_profiles(fwd_key, fwd.load()): window_m() still approx(m).

def test_a_cross_line_or_another_grid_starts_at_fit(opened):
    # zoom; add a line on axis "x" on grid A and open it: ruler key ("A", "x"), window == its bounds.
    # Same with a line on a second grid "B".

def test_the_hold_is_in_metres_across_different_trace_spacings(opened):
    # a forward line written with synthetic_dzt(..., traces_per_metre=50.0); zoom on the opened line, open it:
    # window_m() == approx(m) although trace_hi - trace_lo differs.

def test_a_line_without_distance_neither_mirrors_nor_holds(opened):
    # the time-triggered line the existing FILE__TIME test builds: open it after zooming:
    # ruler is None, not mirrored, window == (0, n_traces); open the reversed line again: at Fit, no error logged.

def test_the_difference_view_keeps_the_mirror_and_the_window(opened):
    # set_profiles, append dewow, zoom, set_difference_index(0): mirrored and window_m() == approx(m);
    # set_difference_index(-1): same.

def test_a_grid_resize_moves_fit_without_reopening_the_line(opened):
    session, dock, key, line = opened
    session.replace_grid(dataclasses.replace(GRID, size_y=20.0))
    assert dock.view.ruler.hi_m == pytest.approx(20.0)
    dock.fit_button.click()
    assert dock.view.window_m()[1] == pytest.approx(20.0)

@needs_real_data
def test_real_zigzag_lines_keep_a_metre_in_place_across_the_sweep(bare):
    # Ten REAL_DZT lines on Grid("R", (0, 0), 0, 20.0, 11.0, ...) along "y" at offsets 0.5*i, placed the way
    # lookup's zigzag does: even i GridPlacement(..., start_along=0.0, direction=1), odd i start_along=11.0, -1.
    # Open line 0; x0 = x of metre 5.0. Preview each other line in turn (set_profiles first): x of 5.0 within 0.5 px.
    # Then zoom so window_m() is about (4.5, 5.5) and sweep again: same check, and window_m() is unchanged.
```

  Write the commented bodies as described. Read the x of a metre with `ruler.trace_units_at(line.distance_along(), m)` through `dock.view.transform.x_of_trace`.

- [ ] **Step 2: Run them and see them fail.** Run: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py -q -p no:xonsh`. Expected: the new tests fail, for example with `assert None == Ruler(...)`.

- [ ] **Step 3: Implement the dock half** to the behaviour contract above. Add a paragraph to the module docstring explaining why the hold reads the window off the line being left, and why rule 1 keeps the exact object.

- [ ] **Step 4: Run the new tests and see them pass.**

- [ ] **Step 5: Update the guide.** Replace the **nsgeo Profile** bullet's "**Fit** fits the whole line in the panel" sentence. The new text says:
  - Every line on a grid is drawn against the grid's length, with the low end on the left, so a line walked the other way is shown mirrored.
  - A short line leaves hatched blank space.
  - Zoom and pan stay on the same stretch of ground when another line on the same grid, running the same way, opens or is hovered on the map.
  - **Fit** shows the whole grid length.
  - The arrow under the distance axis shows which way the line was walked.

  Write it plain but professional, in the voice of the paragraphs around it.

- [ ] **Step 6: Run the whole QGIS tier and repair fallout.** Some existing tests place short lines on large grids, or a reversed line starting at 0, and then assert the old trace-0-left full-extent window or click at fixed pixels. Known so far:
  - `test_fit_button_restores_the_full_extent_after_a_zoom` and `test_one_to_one_button_sets_a_trace_per_pixel_window` in this file.
  - `test_plugin_velocity_fit.py`: 60-trace (1 m) lines on an 11 m grid, clicked at x = 40.

  Rule for each one: keep the test's intent. Prefer making the fixture match what the import would produce, over loosening an assertion. That means a grid sized to its lines along the lines' axis, or a reversed line starting at the far edge. Where the assertion itself pinned trace-0-left behaviour, restate it against the new rule: the window equals `transform.trace_bounds` after Fit, and the screen-left trace holds after 1:1. List every changed test, and why, in the task report.

- [ ] **Step 7: Run both tiers in full, plus lint and types.** Record the counts. The real-data test must not be among the skips.

- [ ] **Step 8: Commit and push.**

```bash
git add packages/nsgeo-qgis docs/guide/getting-started.md
git commit -m "feat(plugin): one ruler per grid, and the view holds its metres from line to line (#67)"
git push
```

---

### Task 4: Build and walkthrough (human gate, not a code task)

The user's rule: deploy and a manual walkthrough come before any merge decision. This task ends when the user reports back. It never ends by merging.

- [ ] **Step 1: Verify the branch head from clean.** Run both tiers, lint, types and the boundary tests, and record every count.
- [ ] **Step 2: Deploy to a new QGIS profile `ns_geo_zigzag`.** Make it a copy of `ns_geo`, then run `.venv/bin/python packages/nsgeo-qgis/scripts/dev_link.py --profile ns_geo_zigzag` from this worktree. `ns_geo` and the other profiles stay untouched. Check the symlink with `ls -la` on the profile's plugins directory, and do a headless smoke load.
- [ ] **Step 3: Publish a walkthrough page** as a claude.ai Artifact with the `db` capability, the same pattern as the earlier walkthrough pages. Each check has a pass/fail plus notes. Run each gesture on a reversed line from the user's real zigzag grid:
  - the user's own case: sweep the mouse across the zigzag lines on the map at full view, with a reflection in view. It stays in place;
  - the same sweep zoomed in on the reflection. The stretch of ground and the time window stay put;
  - Fit and 1:1 on a mirrored line;
  - wheel zoom and middle-drag pan on a mirrored line follow the pointer;
  - hovering the profile near each end of a mirrored line puts the map cursor at the right place;
  - drag-select on a mirrored line, including one dragged off the short end. The map highlight matches;
  - a Shift-click pick lands under the pointer, and existing picks show where they were made;
  - velocity-fit clicks and a right-click discard on a mirrored line. Saved fit curves show in the right place;
  - the cutoff drag, including grabbing it over blank space;
  - the blank space past a short line: does the hatch read as "no data", and does clicking there do nothing;
  - the distance numbers, and the caption `m along grid · walked ←`;
  - opening a cross-line or a line on another grid starts at full view;
  - the Difference view on a mirrored line;
  - editing the grid's size, after which Fit uses the new length;
  - after adding `time_zero` to a zoomed line, the horizontal zoom is kept (a change from today). Is that welcome?
- [ ] **Step 4: Report the walkthrough to the user and wait for their results.** Fix rounds go back through Tasks 1–3's test-first discipline. Merging is offered only afterwards, through superpowers:finishing-a-development-branch, and is asked, never assumed.

## Follow-ups (not in this plan)

- **#83 (profile figure/annotation panel):** an exported figure should use the mirrored, ruled view. That falls out if the figure is drawn through `ProfileView`. Note it on #83.
- **The help-pages branch** doesn't touch the Profile panel, so no conflict is expected.
