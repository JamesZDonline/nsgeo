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

