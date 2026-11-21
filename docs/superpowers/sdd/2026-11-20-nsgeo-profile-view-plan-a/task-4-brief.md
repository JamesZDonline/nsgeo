### Task 4: Each vertical axis in ns, samples or m, chosen by clicking the axis (#11)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py`:
  - `MARGIN_RIGHT` goes from 48 to 56 (spec §4.6);
  - `_paint_axes`;
  - tick helpers;
  - `_handle_mouse_press`;
  - a new signal.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`: the axis menu and the settings.
- Test: `tests/qgis/test_plugin_profile_view.py` and `tests/qgis/test_plugin_profile_dock.py`

**Interfaces:**
- Consumes: Task 1's `profile_settings`, `LEFT_AXIS_KEY` and `RIGHT_AXIS_KEY`.
- Produces:
  - `AXIS_UNITS = ("ns", "sample", "m")` in `profile_view.py`;
  - `ProfileView.set_axis_units(left: str, right: str) -> None`, which raises `ValueError` for a unit not in `AXIS_UNITS`;
  - `ProfileView.axis_units -> tuple[str, str]`, a property;
  - `ProfileView.has_velocity -> bool`, a property;
  - `ProfileView._axis_ticks(unit: str, t: ViewTransform) -> list[tuple[str, float]]`;
  - `ProfileView.axis_strip_at(x: float, y: float) -> str | None`, which takes image-local coordinates (as `_local` gives) and returns `"left"`, `"right"` or None;
  - signal `ProfileView.axis_menu_requested = pyqtSignal(str, QPoint)`, carrying the side and the global position;
  - `ProfileDock.axis_menu: QMenu | None`;
  - `ProfileDock._on_axis_menu_requested(side: str, pos: QPoint) -> None`;
  - `ProfileDock._set_axis_unit(side: str, unit: str) -> None`.

**The spec fixes these values:**
- The captions are `f"{unit} ▾"`.
- The menu items are `"Time (ns)"`, `"Samples"` and `"Depth (m)"`, carrying `"ns"`, `"sample"` and `"m"` as action data.
- Depth is disabled when `not view.has_velocity`, with the tooltip "Depth needs a velocity for this line".
- Sample ticks:
  - `s_lo = (time_lo - t0)/dt - 0.5` and `s_hi = (time_hi - t0)/dt - 0.5`;
  - integer `nice_ticks(s_lo, s_hi)` inside `[0, n_samples - 1]`;
  - each placed at `y_of_time(t0 + (s + 0.5)·dt)` and labelled `str(int(s))`.
- Depth ticks are drawn only for times ≥ 0 on the shown clock.
- **The strip hit-test.** It is the margin beside the image: left is `x < 0`, right is `x >= t.width`, and both need `-MARGIN_TOP <= y < t.height`. A left or right press there emits `axis_menu_requested` and returns before `_press`, a pick, a velocity gesture or a cutoff grab is armed.

- [ ] **Step 1: Re-pin the view tests for the wider right margin, first and separately**

  In `test_plugin_profile_view.py`:
  - define `VIEW_W = 696 + MARGIN_LEFT + MARGIN_RIGHT` and import `MARGIN_RIGHT`;
  - replace every `resize(800, ...)` with `resize(VIEW_W, ...)`;
  - in the resize test that expects 896, use `VIEW_W + 200`.

  The hard-coded numbers derived from a 696 px image then stand. Change `MARGIN_RIGHT` to 56 and run the file. Expected: PASS. Any failure here is a re-pin miss; fix it before going on.

- [ ] **Step 2: Write the failing tests**

```python
def _sampled(make_view):
    v = make_view(); v.resize(VIEW_W, 264 + MARGIN_TOP + 28); v.show()
    v.set_axes(200, 128, 0.0, 0.25, distance_along=np.arange(200) / 60.0)
    v.set_velocity(VelocityModel.constant(0.1))
    return v

def test_an_axis_in_samples_ticks_row_centres(make_view):
    v = _sampled(make_view)
    v.set_axis_units("sample", "m")
    ticks = v._axis_ticks("sample", v.transform)
    # nice_ticks(-0.5, 127.5) steps by 50 at the default target of 6
    assert [label for label, _ in ticks] == ["0", "50", "100"]
    assert ticks[1][1] == pytest.approx(v.transform.y_of_time(50.5 * 0.25))

def test_each_side_takes_each_unit(make_view):
    v = _sampled(make_view)
    for left in AXIS_UNITS:
        for right in AXIS_UNITS:
            v.set_axis_units(left, right)
            assert v.axis_units == (left, right)
            v.grab_image()                      # paints without raising

def test_depth_is_blank_without_a_velocity(make_view):
    v = _sampled(make_view); v.set_velocity(None)
    assert v._axis_ticks("m", v.transform) == []

def test_a_press_on_an_axis_strip_asks_for_its_menu_and_keeps_the_selection(make_view):
    v = _sampled(make_view)
    v.set_selection(10, 40)
    got = []
    v.axis_menu_requested.connect(lambda side, pos: got.append(side))
    QTest.mousePress(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(10, MARGIN_TOP + 50))
    QTest.mouseRelease(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(10, MARGIN_TOP + 50))
    QTest.mousePress(v, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, QPoint(v.width() - 10, MARGIN_TOP + 50))
    assert got == ["left", "right"]
    assert v._selection == (10, 40)

def test_a_press_on_the_bottom_axis_still_clears_the_selection(make_view):
    ...press and release at (MARGIN_LEFT + 100, v.height() - 10); assert v._selection == (-1, -1)...
```

In the dock file:

```python
def test_the_axis_menu_sets_a_unit_and_remembers_it(opened):
    session, dock, key, line = opened
    dock._on_axis_menu_requested("left", QPoint(0, 0))
    act = next(a for a in dock.axis_menu.actions() if a.data() == "sample")
    act.trigger()
    assert dock.view.axis_units == ("sample", "m")
    other = ProfileDock(session)
    try:
        assert other.view.axis_units == ("sample", "m")
    finally:
        other.deleteLater()
    dock.axis_menu.hide()

def test_depth_is_greyed_in_the_menu_without_a_velocity(opened, monkeypatch):
    ...make _refresh_velocity fail (as in Task 1), open the menu, assert the "m" action is disabled...

def test_a_bad_remembered_unit_falls_back(opened):             # Review Focus 4
    session, dock, key, line = opened
    profile_dock.profile_settings().setValue(LEFT_AXIS_KEY, "feet")
    other = ProfileDock(session)
    try:
        assert other.view.axis_units == ("ns", "m")
    finally:
        other.deleteLater()
```

- [ ] **Step 3: Run and check that they fail.** Expected: FAIL (no `set_axis_units`, no signal, no menu).

- [ ] **Step 4: Implement as the Interfaces and fixed values above say.** `_paint_axes` draws each side's ticks from `_axis_ticks(unit, t)` and its caption with the arrow.

- [ ] **Step 5: Run both touched files, `test_plugin_profile_cut.py`, `test_plugin_velocity_fit.py` (whose right-presses are in velocity mode) and pure.** Expected: PASS.

- [ ] **Step 6: Commit and push**

```bash
git commit -am "feat(profile): each vertical axis shows ns, samples or m, chosen by clicking the axis (#11)"
git push
```

---

