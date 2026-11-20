### Task 3: 1:1 as true scale, and one pair of trace↔metre helpers (#5, spec §4.4 and §4.7)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`:
  - add the module function `true_scale_window`;
  - **remove** `ViewTransform.one_to_one`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py`:
  - add the helper pair;
  - route `_distance_ticks`, `window_m` and `set_window_m` through it;
  - replace `one_to_one()` with `true_scale()` and add `can_true_scale()`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`:
  - wire `one_to_one_button` to `view.true_scale`;
  - keep its enabled state.
- Test: the pure, view and dock test files.

**Interfaces:**
- Consumes: Task 2's `one_to_one_button`.
- Produces:
  - `true_scale_window(t: ViewTransform, metres_per_trace_unit: float, ns_per_metre: float) -> ViewTransform`, a pure module function in `view_transform.py`;
  - `ProfileView.metres_at_trace_units(u: float | np.ndarray) -> float | np.ndarray | None`, which is `ruler.metres_at(self._distance, u)` and None without a distance of at least 2 traces;
  - `ProfileView.trace_units_at_metres(m: float | np.ndarray) -> float | np.ndarray | None`, which is `ruler.trace_units_at(self._distance, m)` and None likewise;
  - `ProfileView.can_true_scale() -> bool`, true iff there is a transform, a velocity and metres;
  - `ProfileView.true_scale() -> None`;
  - `ProfileDock._sync_true_scale_button() -> None`.

**The algorithm** for `true_scale_window`. The spec fixes the rule, but not its arithmetic:

```python
across = t.width / ((t.trace_hi - t.trace_lo) * metres_per_trace_unit)       # px per metre along
span = t.height / across * ns_per_metre                                        # ns that make px/m equal
record = t.n_samples * t.dt_ns
if span <= record:
    mid = (t.time_lo + t.time_hi) / 2
    return t.with_window(t.trace_lo, t.trace_hi, mid - span / 2, mid + span / 2)
down = t.height / (record / ns_per_metre)                                      # px per metre down, whole record
traces = t.width / down / metres_per_trace_unit
mid = (t.trace_lo + t.trace_hi) / 2
return t.with_window(mid - traces / 2, mid + traces / 2, t.t0_ns, t.t_end)
```

**`ProfileView.true_scale()` works out the two inputs:**
- `metres_per_trace_unit` is `abs(m(hi) − m(lo)) / (hi − lo)`, with `m = metres_at_trace_units`, over the current window;
- `ns_per_metre` is `1 / slope`, where `slope = (z(tm + h) − z(tm − h)) / (2h)`, with `z = self._velocity.depth_at`, `tm` the window's middle time clamped to at least `h`, and `h = t.dt_ns`.

It does nothing when `can_true_scale()` is false.

- [ ] **Step 1: Write the failing pure tests**

```python
def test_true_scale_sets_the_time_span_to_match_metres_across():
    t = ViewTransform.fit(200, 512, 0.0, 0.2, 696, 264).with_window(50.0, 100.0, 20.0, 60.0)
    s = true_scale_window(t, 1 / 60, 20.0)          # 60 traces/m; 0.1 m/ns -> 20 ns per metre of depth
    across = 696 / (50 / 60)
    assert s.time_hi - s.time_lo == pytest.approx(264 / across * 20.0)
    assert (s.time_lo + s.time_hi) / 2 == pytest.approx(40.0)
    assert (s.trace_lo, s.trace_hi) == pytest.approx((50.0, 100.0))

def test_true_scale_keeps_the_record_and_narrows_along_a_long_line():
    t = ViewTransform.fit(1800, 512, 0.0, 0.2, 696, 264)   # 30 m at 60 traces/m, 102.4 ns
    s = true_scale_window(t, 1 / 60, 20.0)
    assert (s.time_lo, s.time_hi) == pytest.approx((0.0, 102.4))
    assert s.trace_hi - s.trace_lo == pytest.approx(696 / (264 / (102.4 / 20.0)) * 60)
    assert (s.trace_lo + s.trace_hi) / 2 == pytest.approx(900.0)

def test_true_scale_on_a_mirrored_ruler_keeps_the_mirror():
    ...bounds=(-20.0, 260.0), mirrored=True, then the first test's assertions, plus s.mirrored...

def test_true_scale_at_the_clamps_does_not_raise():          # Review Focus 5
    t = ViewTransform.fit(200, 512, 0.0, 0.2, 696, 264).with_window(0.0, 4.0, 0.0, 0.8)
    s = true_scale_window(t, 1 / 60, 2000.0)                 # absurdly slow ground
    assert s.time_hi - s.time_lo >= 4 * 0.2 - 1e-9
    assert s.trace_hi - s.trace_lo >= 4.0 - 1e-9
```

**Delete** the pure tests that pin the removed method, naming them in the commit message:
- `test_one_to_one_keeps_the_screen_left_edge`;
- the `one_to_one` loop in the test at about line 344 of `test_pure_view_transform.py`. Keep that test's other assertions.

- [ ] **Step 2: Run and check that they fail.** Expected: `ImportError` for `true_scale_window`.

- [ ] **Step 3: Implement `true_scale_window`, and remove `ViewTransform.one_to_one`.**

- [ ] **Step 4: Write the failing view and dock tests**

  **Rewrite** these three tests for the new meaning:
  - `test_one_to_one_sets_a_trace_per_pixel_column_and_emits_view_changed` (`test_plugin_profile_view.py`, about line 1302) becomes `test_true_scale_matches_metres_across_and_down_and_emits_view_changed`:
    - use the `view` fixture plus `v.set_velocity(VelocityModel.constant(0.1))`;
    - after `v.true_scale()`, check that px/m across and px/m down agree within 1%;
    - check that `view_changed` was emitted once.
  - `test_fit_and_one_to_one_keep_the_ruler_and_the_mirror` (about line 2010) becomes `test_fit_and_true_scale_keep_the_ruler_and_the_mirror`. It gives the view a velocity and keeps the same ruler and mirror assertions.
  - `test_one_to_one_button_sets_a_trace_per_pixel_window` (`test_plugin_profile_dock.py`, about line 563) becomes `test_the_one_to_one_button_shows_true_scale`. `GRID`'s 0.08 m/ns gives `ns_per_metre` = 25. Assert the time span equals `height / across * 25` within 1%.

  **Add:**

```python
def test_true_scale_is_greyed_without_a_velocity(opened, monkeypatch):
    session, dock, key, line = opened
    assert dock.one_to_one_button.isEnabled()
    monkeypatch.setattr(session, "resolved_velocity", lambda k: (_ for _ in ()).throw(KeyError("none")))
    dock._refresh_velocity()
    assert not dock.one_to_one_button.isEnabled()

def test_true_scale_is_greyed_on_a_line_with_no_metres(opened):     # Review Focus 2
    session, dock, key, line = opened
    k2, _ = _add_line(session, "U1", GridPlacement("A", "y", 0.0, 0.0, 1, "U1"), traces_per_metre=0.0)
    session.open_line(k2)
    assert not dock.one_to_one_button.isEnabled()
    assert dock.view.metres_at_trace_units(10.0) is None

def test_the_metre_helpers_are_the_only_road(view, monkeypatch):    # spec §4.7, for M17c
    v, rg = view
    calls = []
    real = ProfileView.metres_at_trace_units
    monkeypatch.setattr(ProfileView, "metres_at_trace_units", lambda self, u: (calls.append(u), real(self, u))[1])
    v.grab_image()
    assert calls                                    # the distance ticks went through it

def test_the_metre_helpers_carry_the_held_window(ruled, monkeypatch):
    v = ruled
    fwd, back = [], []
    real_m, real_t = ProfileView.metres_at_trace_units, ProfileView.trace_units_at_metres
    monkeypatch.setattr(ProfileView, "metres_at_trace_units", lambda self, u: (fwd.append(u), real_m(self, u))[1])
    monkeypatch.setattr(ProfileView, "trace_units_at_metres", lambda self, m: (back.append(m), real_t(self, m))[1])
    lo, hi = v.window_m()
    v.set_window_m(lo + 0.5, hi - 0.5, v.transform.time_lo, v.transform.time_hi)
    assert fwd and back                             # window_m and set_window_m both went through the pair
```

- [ ] **Step 5: Run and check that they fail.** Expected: FAIL (no `true_scale`, button enabled, no helpers).

- [ ] **Step 6: Implement**

  **In the view:**
  - Add the helper pair.
  - `_distance_ticks`, `window_m` and `set_window_m` call the pair instead of `metres_at`/`trace_units_at`.
  - Add `can_true_scale()` and `true_scale()`, which emits `view_changed`.
  - Delete `one_to_one()`.

  **In the dock:**
  - `one_to_one_button.clicked` → `view.true_scale`.
  - Its tooltip when enabled: "True scale: a metre down is as long as a metre along the line, at the line's velocity". When greyed: "True scale needs metres along the line and a velocity".
  - Call `_sync_true_scale_button()` at the end of `_render`, of `_refresh_velocity` (every path), of `_take_down_picture` and of the cut path in `_draw_cut`.

- [ ] **Step 7: Run the touched files, pure and real data.** Expected: PASS.

- [ ] **Step 8: Commit and push**

```bash
git commit -am "feat(profile): 1:1 is true scale; one pair of trace-metre helpers for M17c (#5)

Removes ViewTransform.one_to_one and test_one_to_one_keeps_the_screen_left_edge; the view and dock 1:1 tests are rewritten for true scale."
git push
```

---

