### Task 1: Plan A follow-ups (rulings R17/R18), and a toolbar width pin that survives CI's fonts

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (`_take_down_picture`, the Fit button construction).
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py` (`set_axes` guard, and `_true_scale_inputs` / `true_scale_window_is_flat`).
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py` (remove `bounds_on`).
- Test: `tests/qgis/test_plugin_profile_dock.py`, `tests/qgis/test_plugin_profile_view.py` and `tests/pure/test_pure_ruler.py`.

**Interfaces:**
- Produces `ProfileView._window_metres_per_trace_unit() -> float | None`. It is the one place that works out metres per trace unit across the current window, and both `_true_scale_inputs` and `true_scale_window_is_flat` use it.

**The five changes:**
- **The header flag on a same-line take-down that went through rule 1.**
  - Today `_take_down_picture` sets `_axes_from_header = not self._clock_carried`.
  - Change the condition, checked **before** its `_set_axes_holding` call: set the flag only when `not (self._axes_key == key and not self._axes_from_header)`. That is, only when the header axes did not come from the same line's processed picture.
  - `test_a_held_zoom_does_not_move_when_an_unloaded_lines_samples_arrive` and `test_a_same_line_take_down_then_render_keeps_the_radar_window` must stay green, unchanged.
- **The Fit button's minimum width follows font and style changes.**
  - Recompute it (the widest of the three action labels) on `QEvent.Type.FontChange` and `QEvent.Type.StyleChange`. Use a small `QToolButton` subclass in `profile_dock.py`, or an event filter.
- **`set_axes` is guarded against non-finite clocks.**
  - Extend its first guard to `math.isfinite(t0_ns) and math.isfinite(dt_ns) and dt_ns > 0`.
  - On refusal it leaves `transform`, `_distance` and `_ruler` all unchanged.
- **`bounds_on` is removed from `ruler.py`,** and so are its tests in `tests/pure/test_pure_ruler.py`. It is unused in production since Plan A's I2, and it is a second road from metres to trace units (spec §3.1). Its conversion is covered by the helper-pair tests.
- **The toolbar minimum-width pin survives other fonts.**
  - `test_the_toolbar_minimum_width_is_back_to_pre_m7` failed on CI's QGIS 3.44 at 87198d9: 723 against a local 684. Pixel bounds measured on one machine break on another.
  - Replace the absolute pin with two checks that hold in any font:
    1. Long Difference and velocity texts do not raise the row's minimum width beyond the Difference label's own growth. The velocity label (`ElidedLabel`, `Ignored`) contributes nothing.
    2. The minimum is at most 900 px, the docked width the M7 walkthrough used.
  - Update the docstring.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_same_line_take_down_through_rule_1_does_not_set_the_header_flag(opened):
    # The re-review's probe: a line with no steps, zoom mid-record, _show_steps_refused,
    # then append time_zero(mode="sample", sample=20) -> the radar window is unchanged
    # (today it moves by the new zero: (39.35, 49.35) -> (41.25, 51.25)).
    ...

def test_the_fit_button_keeps_its_widest_width_after_a_font_change(opened):
    session, dock, key, line = opened
    f = dock.fit_button.font(); f.setPointSizeF(f.pointSizeF() * 1.25); dock.fit_button.setFont(f)
    QTest.qWait(50)
    xs = set()
    for action in (dock.fit_all_action, dock.fit_width_action, dock.fit_height_action):
        action.trigger(); QTest.qWait(50); xs.add(dock.one_to_one_button.x())
    assert len(xs) == 1

def test_set_axes_refuses_a_non_finite_clock_and_changes_nothing(view):
    v, rg = view
    before = (v.transform, v._distance, v.ruler)
    v.set_axes(rg.n_traces, rg.n_samples, float("nan"), rg.dt_ns, distance_along=np.arange(rg.n_traces) / 30.0)
    assert (v.transform, v._distance, v.ruler) == before
    v.set_axes(rg.n_traces, rg.n_samples, rg.t0_ns, float("inf"))
    assert (v.transform, v._distance, v.ruler) == before
```

  The width pin's replacement is written as the two checks described above.

- [ ] **Step 2: Run them and check they fail.**
  - Expected: the first moves by the zero, the second gives two or three x values, and the third replaces `_distance` or raises.
  - The width checks pass on today's code; say so.
- [ ] **Step 3: Implement the five changes.**
- [ ] **Step 4: Run** `test_plugin_profile_dock.py`, `test_plugin_profile_view.py`, `test_plugin_profile_cut.py`, pure and real data. Expected: PASS.
- [ ] **Step 5: Commit and push**

```bash
git commit -am "fix(profile): Plan A follow-ups -- header flag on rule 1, Fit width on font change, finite set_axes, one metre road, a font-proof width pin"
git push
```

---

