### Task 2: The profile draws on the radargram's own clock

**Files:**
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`: `_set_axes_holding`, `_render`,
    `_show_line`, `_refresh_picks`, `_show_cutoff`, `_on_cutoff_dragged`, plus new helpers.
  - `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`: `_sync_gain_strip` and `_on_gain_points`.
- Test:
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_time_cutoff.py`
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py`
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py`
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py:346-372`

**Interfaces:**
- Consumes: `Radargram.zero_ns` and `retime_ns` from Task 1.
- Produces, on `ProfileDock`:
  - `_shown_radargram: Radargram | None`. Set in `_render` to the radargram it drew. Set to
    `None` in `_show_line`'s header-only branch and in `_clear`.
  - `shown_zero_ns() -> float`: `_shown_radargram.zero_ns`, or `0.0` when it is None.
  - `step_input_zero_ns(row: int) -> float`: the `zero_ns` of what the working stack's step at
    `row` receives. That is `intermediate(row - 1)`, or the source when `row == 0`. It returns
    `0.0` when there is no source, or when the stack raises `ValueError`.

- [ ] **Step 1: Write the failing tests**

In `test_plugin_time_cutoff.py`, use its `_plugin_with_line` and `_unload`. The synthetic header
puts row 0 at −11.0864 ns with `dt = 0.216531`, so `time_zero(sample=51)` makes
`zero = -0.0433` ns.

```python
def test_a_cutoff_ahead_of_time_zero_is_drawn_and_dragged_on_its_own_clock(fake_iface, tmp_path, answer_modal):
    plugin, s, key = _plugin_with_line(fake_iface, tmp_path)
    try:
        s.append_step(key, build_step("time_cutoff", end_ns=60.0))
        s.append_step(key, build_step("time_zero", mode="sample", sample=51))
        plugin.processing_dock.list.setCurrentRow(0)
        dock = plugin.profile_dock
        zero = dock.shown_zero_ns()
        assert zero == pytest.approx(-0.0433, abs=1e-3)
        assert dock.view.cutoff_ns == pytest.approx(60.0 - zero)
        dock.view.cutoff_dragged.emit(40.0)
        assert s.stack_for(key).entries[0][0].params["end_ns"] == pytest.approx(40.0 + zero)
    finally:
        _unload(plugin, answer_modal)


def test_an_unmoved_handle_across_clocks_writes_nothing(fake_iface, tmp_path, answer_modal):
    # Review Focus 3: the same stack, but emit the line's own drawn value back.
    # The dirty flag stays as it was before the emit, and the step object is unchanged (`is`).
    ...
```

In `test_plugin_gain_strip.py`, use its plugin fixture:

```python
def test_a_gain_curve_ahead_of_time_zero_is_shown_and_written_on_its_own_clock(...):
    # Stack: gain_curve(points=[[0.0, 0.0], [40.0, 12.0]]), then time_zero(sample=51); select row 0.
    zero = plugin.profile_dock.shown_zero_ns()
    assert plugin.profile_dock.gain_strip.points() == pytest.approx([[0.0 - zero, 0.0], [40.0 - zero, 12.0]])
    plugin.profile_dock.gain_strip.points_changed.emit([[0.0 - zero, 0.0], [30.0 - zero, 12.0]])
    assert step_points(s, key, 0) == pytest.approx([[0.0, 0.0], [30.0, 12.0]])
```

Also add a no-movement case to this file: emitting the strip's own `points()` back writes
nothing.

In `test_plugin_profile_dock.py`, use the existing opened-line fixture:

```python
def test_a_time_zero_that_crops_nothing_still_moves_the_axis(...):
    # Synthetic line, then append time_zero(mode="sample", sample=0).
    assert dock.view.transform.t0_ns == 0.0     # was -11.086; spec §4.4's Rule 1 trap


def test_picks_stay_on_their_sample_when_time_zero_is_added(...):
    session.add_pick(key, 30, 20.0)               # radar clock: no step yet
    session.append_step(key, build_step("time_zero", mode="sample", sample=51))
    zero = dock.shown_zero_ns()
    assert dock.view._picks == [(30, pytest.approx(20.0 - zero))]
```

In `test_plugin_param_form.py:346-372`, change the ground truth.
`time_zero(sample=5)` now gives `t0 == 0.0` and `n == source.n_samples - 5`. Keep
`t0 != approx(source.t0_ns)`, and update the docstring.

- [ ] **Step 2: Run the four files to make sure the new tests fail**

Run the QGIS command on those files.
Expected: the new tests FAIL. The cutoff line, the strip points and the picks are still on the
step's clock, and the axis stays at −11.086.

- [ ] **Step 3: Implement**

- **`_set_axes_holding`:** add `t0_ns` and `dt_ns` to both comparisons that put back the old
  transform: Rule 1's tuple and the `ruler is None` branch.
- **`_render`:** set `_shown_radargram = rg` before the axes. Call `_refresh_picks()` after
  `_update_velocity_fit()`, because a stack change can now move every pick on screen.
- **`_refresh_picks`:** draw each pick at `retime_ns(p.time_ns, 0.0, self.shown_zero_ns())`.
  Today's stored `time_ns` is on the radar clock. Task 4 replaces the `0.0` with the pick's own
  zero.
- **`_show_cutoff`:** draw at
  `retime_ns(value, self.step_input_zero_ns(row), self.shown_zero_ns())`.
- **`_on_cutoff_dragged(end_ns)`:**
  1. Return without writing when `end_ns` equals the value as drawn (the line above).
  2. Otherwise write `retime_ns(end_ns, self.shown_zero_ns(), self.step_input_zero_ns(row))`.
- **`plugin._sync_gain_strip`:** hand the strip points converted with the same
  `retime_ns(t, input, shown)`.
- **`plugin._on_gain_points`:**
  1. Compare the emitted points with the step's own points converted to the shown clock. If they
     are equal, return without writing.
  2. Otherwise convert the emitted points to the input clock and write them.

  Comparing in the shown clock is what keeps an unmoved handle from writing.

- [ ] **Step 4: Run the four files, then every QGIS file that mentions `time_zero`, cutoff or gain**

Run the QGIS command on `test_plugin_time_cutoff.py test_plugin_gain_strip.py test_plugin_profile_dock.py test_plugin_param_form.py test_plugin_processing_dock.py test_plugin_profile_view.py`.
Expected: all pass.

- [ ] **Step 5: Lint, then commit and push**

```bash
git commit -am "feat(profile): draw picks, cutoff and gain curve on the radargram's own clock (#97)"
git push
```

---

