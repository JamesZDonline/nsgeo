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

