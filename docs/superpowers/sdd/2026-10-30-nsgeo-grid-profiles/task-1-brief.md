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

