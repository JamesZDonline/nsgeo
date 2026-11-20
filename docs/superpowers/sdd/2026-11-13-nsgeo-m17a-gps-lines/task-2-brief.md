### Task 2: `TrackPlacement` (nsgeo-core)

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/geometry/track.py`
- Modify: `packages/nsgeo-core/src/nsgeo/geometry/__init__.py` (export `Bridge`, `TrackFix`, `TrackPlacement`, `track_from_log`, sorted)
- Create: `packages/nsgeo-core/tests/test_track.py`, `test_track_real_files.py`
- Modify: `packages/nsgeo-core/README.md` (a short `TrackPlacement` paragraph)

**Interfaces:**
- Consumes: Task 1's `DzgLog`, `DzgFix` and `RTK_FIXED`.
- Produces:

```python
# nsgeo/geometry/track.py
ToXY = Callable[
    [np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]
]  # (lon, lat) degrees -> (x, y) metres
END_LIMIT_M: float = 2.0
HEADING_BASE_M: float = 1.0


@dataclass(frozen=True)
class TrackFix:
    trace: int
    x: float  # metres in the placement's crs; NaN for a fix with no position
    y: float
    lat: float
    lon: float
    alt_m: float | None = None
    geoid_m: float | None = None
    quality: int = 4


@dataclass(frozen=True)
class Bridge:
    first_trace: int  # the anchor before the dropout
    last_trace: int  # the anchor after it
    metres: float  # straight distance between the two anchors


@dataclass(frozen=True)
class TrackPlacement:
    fixes: tuple[TrackFix, ...]
    crs: str
    grid_id: str | None = None
    label: str | None = None
    travel_shift: float = 0.0

    # __post_init__: P3 + the Copy's ValueErrors (traces strictly rising, >= 2 anchors, not all at one point, finite shift)
    def anchors(self) -> tuple[TrackFix, ...]: ...
    def bridges(self) -> tuple[Bridge, ...]: ...  # P4, in trace order
    def positions(
        self, n_traces: int, header: DztHeader
    ) -> np.ndarray: ...  # (n, 2) unshifted, P4/P5
    def end_runs(
        self, n_traces: int, header: DztHeader
    ) -> tuple[float, float]: ...  # metres placed before the first / after the last anchor
    def distance_along(self, n_traces: int, header: DztHeader) -> np.ndarray: ...  # P6: c + s
    def trace_coords(
        self, n_traces: int, header: DztHeader, frames: Mapping[str, Grid]
    ) -> np.ndarray: ...  # P6; frames ignored


def track_from_log(
    log: DzgLog, to_xy: ToXY, crs: str, *, label: str | None = None
) -> TrackPlacement: ...


# Projects every fix with a position. Raises ValueError("no RTK-fixed position") or ValueError("only one RTK-fixed position")
# before building, so the import can show those words as they are.
```

**The shift** (P6). Let `P` be `positions(...)` and `c` its cumulative path length, with `c[0] = 0`. Trace `i` goes to the point at arc length `c[i] + s` along `P`. Beyond `c[-1]` it continues along `P[-1] − P[-2]`, and before 0 along `P[0] − P[1]`, both normalised. Repeated arc lengths, from coincident positions, must not divide by zero.

- [ ] **Step 1: Write the failing tests** (`test_track.py`). Headers come from `tests.synthetic.write_dzt` + `read_header`, at `traces_per_metre=10.0` unless stated.
  - `test_traces_between_fixes_are_spaced_evenly_by_trace`: anchors `(trace, x, y)` = (10, 0, 0), (40, 3, 0), (70, 3, 4). Trace 25 is at (1.5, 0) and trace 55 at (3, 2).
  - `test_distance_along_is_the_walked_path`: with the same anchors and 81 traces, `d[70] − d[10] == 7.0` (3 + 4 m), and `d` never falls.
  - `test_the_start_runs_on_by_wheel_along_the_heading`: anchors at (5, 0, 0) and (25, 2, 0). Trace 0 is at (−0.5, 0), five traces of 0.1 m back along +x.
  - `test_the_heading_uses_an_anchor_at_least_a_metre_away`: anchors (5, 0, 0), (7, 0.1, 0.15) and (25, 2, 0). Trace 0's y is 0 to 1e-9, because the jittery near anchor is skipped.
  - `test_a_time_triggered_line_runs_on_at_its_end_segments_spacing`: at `traces_per_metre=0.0`, with anchors (5, 0, 0) and (25, 2, 0), trace 0 is at (−0.5, 0), because the segment's 0.1 m per trace is used.
  - `test_float_and_plain_fixes_are_bridged_not_used`: anchors at traces 10 (0, 0) and 50 (4, 0), with a quality-5 fix at trace 30 placed at (2, 0.5). Trace 30 is at (2, 0), and `bridges() == (Bridge(10, 50, 4.0),)`.
  - `test_a_fix_with_no_position_still_marks_a_bridge`: the same, with a quality-0 fix (NaN x/y) at trace 30.
  - `test_travel_shift_moves_every_trace_forward_along_the_path`:
    - On a straight track along +x with `travel_shift=0.24`, every x grows by 0.24 and y is unchanged.
    - On the L-shaped track of the first test, the trace 0.24 m before the corner lands 0.24 m past it, on the +y leg.
    - `distance_along` grows by exactly 0.24 everywhere.
  - `test_a_negative_shift_runs_back_past_the_start_in_a_straight_line`.
  - `test_fewer_than_two_anchors_or_one_point_is_refused`: each of the Copy's `ValueError` messages, by `pytest.raises(match=…)`.
  - `test_end_runs_are_the_metres_beyond_the_first_and_last_anchor`: anchors at traces 5 and 25 on a 31-trace line give `(0.5, 0.5)`.
  - `test_track_from_log_projects_with_the_given_function_and_keeps_lat_lon`: `to_xy = lambda lon, lat: (lon * 100.0, lat * 100.0)`. Each `TrackFix` has those x/y and the lat/lon as read. A log with one quality-4 fix raises `ValueError("only one RTK-fixed position")`.
  - `test_frames_are_not_needed`: `trace_coords(n, header, {})` works.
- [ ] **Step 2: Write the failing real-data tests** (`test_track_real_files.py`), building each line with `track_from_log(read_dzg(...), local_xy(first fix), "LOCAL")`:
  - `test_file_011_is_placed_along_its_whole_walk`: `GPS_LINES`' `FILE__011.DZT` has 1,560 traces (26.0 m by wheel). Its walked length, `d[-1] − d[0]`, lies between 29.5 and 30.6 m.
  - `test_the_second_surveys_dropouts_are_bridged`:
    - in `GRID2_LINES`, `FILE__039` has exactly one bridge, traces 149 to 246, with `metres` 1.83 ± 0.02;
    - `FILE__042` has exactly one, 1739 to 1755, 0.39 ± 0.02;
    - every other `GRID2_LINES` line has none.
  - `test_every_first_survey_line_starts_close_to_its_first_fix_and_ends_at_its_last`: over `GPS_LINES`, every start run is ≤ 0.70 m and every end run ≤ 0.05 m.
- [ ] **Step 3: Run them and see each fail.**
- [ ] **Step 4: Implement `nsgeo/geometry/track.py`** to P3–P7.
- [ ] **Step 5: Run core + pure, lint and types.** All pass, and the skip count is unchanged.
- [ ] **Step 6: Commit** (`feat(core): TrackPlacement — place traces along an RTK track (#134)`) and push.

---

