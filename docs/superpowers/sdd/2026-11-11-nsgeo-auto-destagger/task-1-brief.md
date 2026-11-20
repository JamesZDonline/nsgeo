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

