# Profile view, Plan A: band, Fit, 1:1, axes, read-out, held zoom (#131 #5 #14 #11 #163)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Profile panel's toolbar and axes do what session F's design says: a Slice band button, a Fit split button with Fit width and Fit height, 1:1 as true scale, per-axis units, a cursor read-out, a depth axis that clears when its velocity fails, and a time zoom that survives a change of clock on the same line.

**Architecture:** Window arithmetic stays in the Qt-free `ui/view_transform.py`. That covers Fit width, Fit height, true scale and carrying a window across a clock change, and it is unit-tested in the pure tier. `ui/profile_view.py` paints, hit-tests and owns the one pair of trace↔metre helpers. `ui/profile_dock.py` owns the toolbar, the settings and the `_set_axes_holding` rules. `plugin.py` is not touched.

**Tech Stack:** Python 3, PyQt via `qgis.PyQt` (QGIS 3.44 / Qt 5 and QGIS 4.2 / Qt 6), numpy, pytest.

**Spec:** `docs/superpowers/specs/2026-11-20-nsgeo-profile-view-design.md` (§4.1–§4.8 and §5 for this plan; §4.9–§4.13 are Plan B).

## Global Constraints

- **The user's Profile panel floats at about 1361 × 448.** Every toolbar and layout check is made at that size.
- **`plugin.py` is not edited in Plan A.** H, M19a and #227 edit it.
- **`slices_dock.py` is not edited.**
  - Take `ElidedLabel` from it with a deferred import inside `ProfileDock.__init__`. A module-level import is circular, because `slices_dock` imports `grid_velocity_label` from `profile_dock`.
  - Say so in a comment.
- **Settings go through one door,** `profile_settings()` in `ui/profile_dock.py`, which returns `QgsSettings()`. The test conftest swaps it, as `folds.fold_settings` is swapped. The keys are:
  - `nsgeo/profile/sliceBand` (bool, default true);
  - `nsgeo/profile/leftAxis` and `nsgeo/profile/rightAxis` (one of `ns`, `sample`, `m`; defaults `ns` and `m`).
- **No modal `exec()` for menus.** The axis menu opens with `QMenu.popup()` and is kept on `ProfileDock.axis_menu` so tests can trigger its actions.
- **Qt-invoked slots and virtual methods.** Every new slot, and every new Qt override (`leaveEvent`), wraps its body in `try/except Exception` and logs, following the module docstrings of `profile_dock.py` and `profile_view.py`. The autouse `_no_swallowed_slot_exceptions` fixture catches a slot that raises.
- **Enums and events:** use the `qtcompat` helpers (`event_pos`) and fully qualified enums (`Qt.MouseButton.LeftButton`) so both Qt versions work.
- **Tooltips are plain language,** like the panel's existing ones.
- **Every new test must fail before its fix.** Each task's report quotes the failing run.
- **Tests to run before each task's commit,** from the worktree root `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-profile-view`:
  - pure: `/home/jameszd/Documents/Github/archaeo_geophysics/.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q`;
  - QGIS, the touched files: `packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis/<file> -q`;
  - real data, at the end of Tasks 3, 5 and 6: `packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis -m real_data -q`.
  - **Never** run `qgis_tests.sh full`; CI runs the whole tier on push.
- **Commit and push after each task:** `git push` on branch `nsgeo-profile-view`.

## Review Focus

These are the inputs most likely to bite that no single feature test covers. Each has a test in the task named.

1. **Mirrored (reversed) lines on a ruler.** Fit width, Fit height, true scale and the read-out must behave as on a forward line, with the right metres. Tests in Tasks 2, 3 and 5.
2. **A line with no metres along it** (no distance, or one trace). The helpers return None without raising, 1:1 greys out, and the read-out says `trace N`. Tests in Tasks 3 and 5.
3. **A cut section** (a cut key, drawn by `_draw_cut`). The units menu and the read-out work on it, nothing raises, and 1:1 greys out without a velocity. Test in Task 5, using the cut fixture of `tests/qgis/test_plugin_profile_cut.py`.
4. **A remembered setting that is no longer valid** (`leftAxis = "feet"`, `sliceBand = "maybe"`). The default is used, nothing raises, and the bad value is overwritten on the next choice. Test in Task 4 for the axes and Task 1 for the band.
5. **True scale pushed to the clamps** (a very short window, or a very slow velocity). `with_window`'s minimum spans win, and nothing raises. Pure test in Task 3.

---

### Task 1: Slice band button (#131) and a depth axis that clears (#14)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`:
  - the toolbar (about lines 385–397);
  - the signal wiring (about line 443);
  - `set_slice_band`, `_push_slice_band` and `clear_slice_band` (about lines 1773–1817);
  - `_refresh_velocity` (about line 2186).
- Modify: `packages/nsgeo-qgis/tests/qgis/conftest.py`: add an autouse `_profile_settings` fixture beside `_fold_settings` (about line 811).
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py`

**Interfaces:**
- Produces:
  - `profile_settings() -> QSettings` (module level, in `profile_dock.py`);
  - constants `SLICE_BAND_KEY = "nsgeo/profile/sliceBand"`, `LEFT_AXIS_KEY = "nsgeo/profile/leftAxis"` and `RIGHT_AXIS_KEY = "nsgeo/profile/rightAxis"`, all defined here (Task 4 uses the last two);
  - `ProfileDock.slice_band_button: QToolButton`, checkable, text `"Slice band"`, placed right after `one_to_one_button`;
  - `ProfileDock._sync_slice_band_button() -> None`.

- [ ] **Step 1: Add the conftest fixture**

  `_profile_settings(tmp_path, monkeypatch)`, autouse. It makes a `QSettings(str(tmp_path / "profile.ini"), QSettings.Format.IniFormat)` and monkeypatches `nsgeo_qgis.ui.profile_dock.profile_settings` to return it. It fails to import until Step 4; that is expected.

- [ ] **Step 2: Write the failing tests**

```python
def test_the_slice_band_button_hides_and_shows_the_band_keeping_its_window(opened):
    session, dock, key, line = opened
    dock.set_slice_band(18.0, 22.0)
    shown = dock.view._slice_band
    assert shown is not None
    dock.slice_band_button.setChecked(False)
    assert dock.view._slice_band is None
    assert dock._slice_band == (18.0, 22.0)          # the window is kept
    dock.slice_band_button.setChecked(True)
    assert dock.view._slice_band == pytest.approx(shown)

def test_a_window_change_while_hidden_is_drawn_when_shown_again(opened):
    session, dock, key, line = opened
    dock.set_slice_band(18.0, 22.0)
    dock.slice_band_button.setChecked(False)
    dock.set_slice_band(30.0, 34.0)
    assert dock.view._slice_band is None
    dock.slice_band_button.setChecked(True)
    lo, hi = dock.view._slice_band
    assert hi - lo == pytest.approx(4.0)              # the new window, on the shown clock

def test_the_slice_band_choice_survives_a_new_dock(opened):
    session, dock, key, line = opened
    dock.slice_band_button.setChecked(False)
    other = ProfileDock(session)
    try:
        assert not other.slice_band_button.isChecked()
    finally:
        other.deleteLater()

def test_the_slice_band_button_is_greyed_until_there_is_a_window(opened):
    session, dock, key, line = opened
    assert not dock.slice_band_button.isEnabled()
    dock.set_slice_band(18.0, 22.0)
    assert dock.slice_band_button.isEnabled()
    dock.slice_band_button.setChecked(False)
    dock.clear_slice_band()
    assert not dock.slice_band_button.isEnabled()
    assert not dock.slice_band_button.isChecked()     # greying keeps the choice

def test_a_bad_remembered_band_choice_falls_back_to_shown(opened):
    session, dock, key, line = opened
    profile_dock.profile_settings().setValue(SLICE_BAND_KEY, "maybe")
    other = ProfileDock(session)
    try:
        assert other.slice_band_button.isChecked()
    finally:
        other.deleteLater()

def test_closing_the_slices_panel_leaves_the_band(...):
    ...
```

The last test is plugin-level. Build the plugin as `tests/qgis/test_plugin_band_times_on_add.py`'s `plugin` fixture does, then open a site with one synthetic line. Then:
- `plugin.slices_dock.window_changed.emit(18.0, 22.0)`;
- `plugin.slices_dock.close()`;
- `plugin.slices_dock.window_changed.emit(19.0, 23.0)`;
- assert that `plugin.profile_dock.view._slice_band` is not None, with a span of `pytest.approx(4.0)`.

**#14** has two more tests in the same file:

```python
def test_a_failed_velocity_refresh_clears_the_depth_axis(opened, monkeypatch):
    session, dock, key, line = opened
    assert dock.view.depth_tick_labels()                       # GRID's velocity is shown
    monkeypatch.setattr(session, "resolved_velocity", lambda k: (_ for _ in ()).throw(RuntimeError("boom")))
    dock._refresh_velocity()
    assert dock.view.depth_tick_labels() == []
    assert dock.velocity_label.text() == ""

def test_a_missing_velocity_on_a_line_clears_the_depth_axis(opened, monkeypatch):
    # KeyError on an ordinary line (not a cut) used to leave the old axis too.
    ...same shape, raising KeyError("no velocity")...
```

- [ ] **Step 3: Run them and check that they fail**

  Run: `packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py -q -k "slice_band or slices_panel or velocity_refresh or missing_velocity"`

  Expected: FAIL. The cause is `AttributeError: ... 'slice_band_button'` or `profile_settings`, and for #14 the stale labels.

- [ ] **Step 4: Implement**

  **The settings door.** Add `profile_settings()` and the three key constants.

  **The button:**
  - It is a checkable `QToolButton` after `one_to_one_button`.
  - Its initial checked state is read from `SLICE_BAND_KEY`. A value that isn't a bool, or `"true"`/`"false"`, means checked.
  - `toggled` → `_on_slice_band_toggled(checked)`:
    - write the key;
    - if checked, `_push_slice_band()`;
    - otherwise `view.clear_slice_band()`.

  **The band methods:**
  - `_push_slice_band` returns right after its `None` check when the button is unchecked. `set_slice_band` still stores `_slice_band` first.
  - `set_slice_band` and `clear_slice_band` call `_sync_slice_band_button()`, which enables the button iff `self._slice_band is not None` and sets the matching tooltip:
    - enabled: "Show or hide the slice's depth window on the profile. The window is kept while it's hidden."
    - greyed: "No slice depth window yet: the band appears once the Slices panel shows a slice."
  - Call it once at the end of `__init__`.

  **`_refresh_velocity`:** every failure path, meaning `KeyError` on any key and the generic `Exception`, does `self.view.set_velocity(None)` and `self.velocity_label.setText("")`. The generic path still logs as now.

- [ ] **Step 5: Run the touched file, then pure**

  Run: `packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py -q`, then the pure tier.

  Expected: all PASS.

- [ ] **Step 6: Commit and push**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py packages/nsgeo-qgis/tests/qgis/conftest.py packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py
git commit -m "feat(profile): a Slice band button that hides the band and keeps its window (#131); a failed velocity refresh clears the depth axis (#14)"
git push
```

---

### Task 2: The Fit split button, Fit width and Fit height, and the elided velocity label (#5)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`: add two methods after `with_window`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py`: add `fit_width()` and `fit_height()` beside `fit()` (about line 403).
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`: the toolbar.
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_view_transform.py`, `tests/qgis/test_plugin_profile_view.py` and `tests/qgis/test_plugin_profile_dock.py`

**Interfaces:**
- Consumes: Task 1's `slice_band_button` position (after `one_to_one_button`).
- Produces:
  - `ViewTransform.fit_width() -> ViewTransform`: the trace window becomes `trace_bounds`, the time window is kept;
  - `ViewTransform.fit_height() -> ViewTransform`: the trace window is kept, the time window becomes `(t0_ns, t_end)`;
  - `ProfileView.fit_width() -> None` and `ProfileView.fit_height() -> None`, which emit `view_changed` and update, like `fit()`;
  - `ProfileDock.fit_button: QToolButton` in `MenuButtonPopup` mode;
  - `ProfileDock.fit_menu: QMenu`;
  - `ProfileDock.fit_all_action`, `fit_width_action` and `fit_height_action: QAction`, with texts `"Fit"`, `"Fit width"` and `"Fit height"`;
  - `ProfileDock.one_to_one_button` becomes a `QToolButton` with text `"1:1"`. Its behaviour changes in Task 3.

- [ ] **Step 1: Write the failing pure tests**

```python
def _w():
    return ViewTransform.fit(200, 128, 0.0, 0.25, 696, 264).with_window(50.0, 100.0, 4.0, 12.0)

def test_fit_width_shows_every_trace_and_keeps_the_time_window():
    t = _w().fit_width()
    assert (t.trace_lo, t.trace_hi) == (0.0, 200.0)
    assert (t.time_lo, t.time_hi) == pytest.approx((4.0, 12.0))

def test_fit_height_shows_the_whole_record_and_keeps_the_trace_window():
    t = _w().fit_height()
    assert (t.trace_lo, t.trace_hi) == pytest.approx((50.0, 100.0))
    assert (t.time_lo, t.time_hi) == pytest.approx((0.0, 32.0))

def test_fit_width_on_a_mirrored_ruler_shows_the_ruler():
    w = ViewTransform.fit(200, 128, 0.0, 0.25, 696, 264, bounds=(-20.0, 260.0), mirrored=True)
    t = w.with_window(40.0, 90.0, 4.0, 12.0).fit_width()
    assert (t.trace_lo, t.trace_hi) == (-20.0, 260.0) and t.mirrored
    assert (t.time_lo, t.time_hi) == pytest.approx((4.0, 12.0))
```

- [ ] **Step 2: Run and check that they fail**

  Run: `.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_view_transform.py -q -k fit_`

  Expected: FAIL, with `AttributeError: 'ViewTransform' object has no attribute 'fit_width'`.

- [ ] **Step 3: Implement both methods** with `with_window`, so the result is clamped.

- [ ] **Step 4: Write the failing dock tests**

```python
def test_fit_width_and_fit_height_from_the_menu(opened):
    session, dock, key, line = opened
    r = dock.view.image_rect()
    dock.view.zoom_at(4.0, r.width() / 2, r.height() / 2)
    z = dock.view.transform
    dock.fit_width_action.trigger()
    t = dock.view.transform
    assert (t.trace_lo, t.trace_hi) == pytest.approx(t.trace_bounds)
    assert (t.time_lo, t.time_hi) == pytest.approx((z.time_lo, z.time_hi))
    dock.view.zoom_at(4.0, r.width() / 2, r.height() / 2)
    z = dock.view.transform
    dock.fit_height_action.trigger()
    t = dock.view.transform
    assert (t.trace_lo, t.trace_hi) == pytest.approx((z.trace_lo, z.trace_hi))
    assert (t.time_lo, t.time_hi) == pytest.approx((t.t0_ns, t.t_end))

def test_the_fit_button_repeats_the_last_pick(opened):
    session, dock, key, line = opened
    dock.fit_width_action.trigger()
    assert dock.fit_button.text() == "Fit width"
    r = dock.view.image_rect()
    dock.view.zoom_at(4.0, r.width() / 2, r.height() / 2)
    z = dock.view.transform
    dock.fit_button.click()
    t = dock.view.transform
    assert (t.trace_lo, t.trace_hi) == pytest.approx(t.trace_bounds)
    assert (t.time_lo, t.time_hi) == pytest.approx((z.time_lo, z.time_hi))

def test_a_new_dock_starts_with_fit(opened):
    session, dock, key, line = opened
    dock.fit_height_action.trigger()
    other = ProfileDock(session)
    try:
        assert other.fit_button.text() == "Fit"
    finally:
        other.deleteLater()

def test_the_toolbar_fits_the_users_panel_in_the_worst_case(opened):
    # 1361 px wide, a long Difference label and a velocity label naming its fits.
    session, dock, key, line = opened
    dock.resize(1361, 448)
    dock.difference_label.setText("Difference: Background removal (sliding)")
    dock.velocity_label.setText("v = 0.100 m/ns (Grid A, average of 6 fits)")
    QTest.qWait(50)
    assert dock.widget().minimumSizeHint().width() <= 1361
    for b in (dock.fit_button, dock.one_to_one_button, dock.slice_band_button):
        assert b.geometry().right() < dock.widget().width()
    assert dock.velocity_label.text() == "v = 0.100 m/ns (Grid A, average of 6 fits)"   # full text kept
```

Add a view-level test as well: `ProfileView.fit_width()` emits `view_changed` once. Use the `view` fixture and connect a counter.

- [ ] **Step 5: Run and check that they fail**

  Run: `qgis_tests.sh` on `test_plugin_profile_dock.py -k "fit_width or fit_button or starts_with_fit or worst_case"` and on `test_plugin_profile_view.py -k fit_width`.

  Expected: FAIL.

- [ ] **Step 6: Implement**

  **`ProfileView.fit_width` and `fit_height`** wrap the transform methods, emit `view_changed` and call `update()`, as `fit()` does.

  **The toolbar:**
  - `fit_button` is a `QToolButton` in `MenuButtonPopup` mode, with `fit_menu` holding the three actions:
    - `fit_all_action` → `view.fit`, tooltip "The whole line across and the whole record down";
    - `fit_width_action` → `view.fit_width`, tooltip "The whole line across; keeps the time zoom";
    - `fit_height_action` → `view.fit_height`, tooltip "The whole record down; keeps the zoom along the line".
  - `fit_menu.triggered` → `fit_button.setDefaultAction(action)`.
  - `fit_button.setDefaultAction(fit_all_action)` is set in `__init__`. It is not persisted.
  - `one_to_one_button` is a `QToolButton("1:1")`, still connected to `view.one_to_one` until Task 3.
  - `velocity_label` is an `ElidedLabel`: a deferred import with a comment naming the cycle. It right-aligns, is added with stretch 1, and `bar.addStretch(1)` is removed.

  **Re-pin `test_a_preview_starting_does_not_shift_the_toolbar_buttons`.**
  - At 900 px the velocity label may now elide, so the two `velocity_label.width() >= velocity_text_width` asserts become `dock.velocity_label.text() == <its full text>`.
  - The button-position asserts stay.
  - Note the change in the test's docstring, citing spec §4.1.

- [ ] **Step 7: Run the touched files, then pure.** Expected: PASS.

- [ ] **Step 8: Commit and push**

```bash
git commit -am "feat(profile): Fit is a split button with Fit width and Fit height; the velocity label elides (#5)"
git push
```

---

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

### Task 5: The cursor read-out (#11, spec §4.7)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py`: hover tracking, `leaveEvent`, `readout_text`, and `_paint_readout`, called after `_paint_axes`.
- Test: `tests/qgis/test_plugin_profile_view.py`, plus one cut test in `tests/qgis/test_plugin_profile_cut.py`.

**Interfaces:**
- Consumes: Task 3's `metres_at_trace_units`, and Task 4's `axis_units` and `has_velocity`.
- Produces: `ProfileView.readout_text() -> str`, which is `""` when the pointer isn't over the image.

**The spec fixes these values:**
- The hover position is set in `_handle_mouse_move` when `0 <= x < t.width` and `0 <= y < t.height`, and set to None otherwise. `leaveEvent` sets it to None and updates.
- **The format.** The parts are joined with `" · "`:
  - first, `f"{m:.2f} m along (trace {i})"`, with `m = metres_at_trace_units(i + 0.5)`, or `f"trace {i}"` when that is None;
  - then, for each side's unit in order (left, right), skipping a unit already shown:
    - `ns`: `f"{t0 + s*dt:.2f} ns"`;
    - `sample`: `f"sample {s}"`;
    - `m`: `f"{depth:.2f} m deep"`. Left out when there is no velocity, or when `t0 + s*dt < 0`.
  - `i = t.trace_at(x)` and `s = t.sample_index_at(y)`. When `i` is None (blank ruler space), there is no read-out.
- **How it is painted:** 9 pt, `AXIS_COLOUR`, in `QRectF(r.left(), 0, r.width(), MARGIN_TOP)`, aligned right and vertically centred.

- [ ] **Step 1: Write the failing tests.** These use Task 4's `_sampled` view: 200 traces at 60 per metre, 128 samples, dt 0.25, t0 0, and 0.1 m/ns.

```python
def _hover_at(v, trace, sample):
    t, r = v.transform, v.image_rect()
    send_hover(v, QPoint(int(r.left() + t.x_of_trace(trace + 0.5)), int(r.top() + t.y_of_time((sample + 0.5) * 0.25))))

def test_the_readout_reads_the_sample_under_the_pointer(make_view):
    v = _sampled(make_view)
    _hover_at(v, 100, 40)
    assert v.readout_text() == "1.67 m along (trace 100) · 10.00 ns · 0.50 m deep"

def test_the_readout_follows_the_axis_units(make_view):
    v = _sampled(make_view)
    v.set_axis_units("sample", "m"); _hover_at(v, 100, 40)
    assert v.readout_text() == "1.67 m along (trace 100) · sample 40 · 0.50 m deep"
    v.set_axis_units("ns", "ns"); _hover_at(v, 100, 40)
    assert v.readout_text() == "1.67 m along (trace 100) · 10.00 ns"

def test_the_readout_without_metres_or_velocity(make_view):          # Review Focus 2
    v = make_view(); v.resize(VIEW_W, 264 + MARGIN_TOP + 28); v.show()
    v.set_axes(200, 128, 0.0, 0.25)
    _hover_at(v, 100, 40)
    assert v.readout_text() == "trace 100 · 10.00 ns"

def test_the_readout_leaves_depth_out_above_zero(make_view):
    v = make_view(); v.resize(VIEW_W, 264 + MARGIN_TOP + 28); v.show()
    v.set_axes(200, 128, -2.0, 0.25, distance_along=np.arange(200) / 60.0)
    v.set_velocity(VelocityModel.constant(0.1))
    t, r = v.transform, v.image_rect()
    send_hover(v, QPoint(int(r.left() + t.x_of_trace(100.5)), int(r.top() + t.y_of_time(-2.0 + 4.5 * 0.25))))
    assert v.readout_text() == "1.67 m along (trace 100) · -1.00 ns"

def test_the_readout_clears_off_the_image(make_view):
    v = _sampled(make_view); _hover_at(v, 100, 40)
    send_hover(v, QPoint(5, MARGIN_TOP + 40))            # the left axis strip
    assert v.readout_text() == ""

def test_a_mirrored_line_reads_its_own_metres(ruled):                 # Review Focus 1
    ...hover the column of trace 10 on the `ruled` fixture; assert the metres equal D[10] to 2 dp...
```

In `test_plugin_profile_cut.py`, reuse its fixture that draws a cut section (Review Focus 3):
- hover the middle of the image and assert `readout_text()` is non-empty;
- open the axis menu with `_on_axis_menu_requested("left", QPoint(0, 0))`, trigger "Samples", and repaint without raising;
- `one_to_one_button` is disabled when the cut has no velocity.

- [ ] **Step 2: Run and check that they fail.** Expected: `AttributeError: readout_text`.

- [ ] **Step 3: Implement.**

- [ ] **Step 4: Run the touched files, the real-data marker and pure.** Expected: PASS.

- [ ] **Step 5: Commit and push**

```bash
git commit -am "feat(profile): a cursor read-out in the axes' units, above the profile (#11)"
git push
```

---

### Task 6: A time zoom survives a clock change on the same line (#163 item 2, spec §4.8)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`: add `carry_time_window`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`: `_set_axes_holding` (about line 572) and its three callers (about lines 851, 944 and 1925), plus a new `self._axes_zero`.
- Test: `tests/pure/test_pure_view_transform.py` and `tests/qgis/test_plugin_profile_dock.py`

**Interfaces:**
- Produces:
  - `carry_time_window(old: ViewTransform, new: ViewTransform, old_zero: float, new_zero: float) -> ViewTransform`, a pure function;
  - `ProfileDock._set_axes_holding(key, n_traces, n_samples, t0_ns, dt_ns, distance, zero_ns: float = 0.0)`;
  - `ProfileDock._axes_zero: float`, set at the end of every `_set_axes_holding` and reset with `_axes_key`.
- Plan B uses both functions, unchanged.

**`carry_time_window`'s rule.** The spec's §4.8, in code terms:
- trace window: `old.trace_lo`, `old.trace_hi`;
- **whole** (`old.time_lo <= old.t0_ns + old.dt_ns/2` and `old.time_hi >= old.t_end - old.dt_ns/2`) → `(new.t0_ns, new.t_end)`;
- **top** (`old.time_lo <= old.t0_ns + old.dt_ns/2`) → `(new.t0_ns, new.t0_ns + span)`;
- **otherwise** → `(lo + old_zero - new_zero, hi + old_zero - new_zero)`, which is `retime_ns`;
- the result goes through `new.with_window(...)`.

**The new rule in `_set_axes_holding`.** It sits after rule 1 and before rule 2. It applies when:
- `old` and `new` exist;
- `key == old_key` and `not is_cut_key(key)`;
- `(n_traces, dt_ns, bounds, mirrored)` are equal;
- any of `t0_ns`, `n_samples` or the zero (`zero_ns` vs `self._axes_zero`) differ.

Then `view.transform = carry_time_window(old, new, self._axes_zero, zero_ns)`, and `view_changed` is emitted.

**What the callers pass as `zero_ns`:**
- `_render`: `rg.zero_ns`;
- `_take_down_picture`: `0.0`, since the header's axes are on the radar clock;
- the cut path: `0.0`, since the rule skips cuts.

- [ ] **Step 1: Write the failing pure tests**

```python
def _old():
    return ViewTransform.fit(200, 512, -11.0, 0.2, 696, 264)          # -11 .. 91.4 ns, radar clock

def test_a_whole_record_stays_whole():
    new = ViewTransform.fit(200, 460, 0.0, 0.2, 696, 264)
    c = carry_time_window(_old(), new, 0.0, -0.6)
    assert (c.time_lo, c.time_hi) == pytest.approx((0.0, 92.0))

def test_the_top_stays_the_top():
    old = _old().with_window(0.0, 200.0, -11.0, 4.0)
    new = ViewTransform.fit(200, 460, 0.0, 0.2, 696, 264)
    c = carry_time_window(old, new, 0.0, -0.6)
    assert (c.time_lo, c.time_hi) == pytest.approx((0.0, 15.0))

def test_a_window_in_the_middle_keeps_its_radar_times():
    old = _old().with_window(20.0, 120.0, 30.0, 45.0)
    new = ViewTransform.fit(200, 460, 0.0, 0.2, 696, 264)
    c = carry_time_window(old, new, 0.0, -0.6)
    assert (c.time_lo - 0.6, c.time_hi - 0.6) == pytest.approx((30.0, 45.0))   # radar = zero + t
    assert (c.trace_lo, c.trace_hi) == pytest.approx((20.0, 120.0))
```

- [ ] **Step 2: Run and check that they fail.** Expected: `ImportError`.

- [ ] **Step 3: Implement `carry_time_window`.**

- [ ] **Step 4: Write the failing dock tests**

  Give the line its samples synchronously with `session.set_profiles(key, line.load())`, as other tests in this file do, so stack changes render at once.

```python
def _radar_window(dock):
    t = dock.view.transform
    return (dock.shown_zero_ns() + t.time_lo, dock.shown_zero_ns() + t.time_hi)

def _zoom_middle(dock):
    t = dock.view.transform
    mid = (t.time_lo + t.time_hi) / 2
    dock.view.transform = t.with_window(t.trace_lo + 20, t.trace_hi - 20, mid - 5.0, mid + 5.0)

def test_a_time_zoom_survives_adding_time_zero_on_an_unruled_line(opened):
    session, dock, key, line = opened
    k2, l2 = _add_line(session, "U1", GridPlacement("A", "y", 0.0, 0.0, 1, "U1"), traces_per_metre=0.0)
    session.open_line(k2); session.set_profiles(k2, l2.load())
    _zoom_middle(dock)
    before = _radar_window(dock)
    session.append_step(k2, build_step("time_zero", mode="sample", sample=20))
    assert _radar_window(dock) == pytest.approx(before)          # today: reset to Fit
    session.replace_step(k2, 0, build_step("time_zero", mode="sample", sample=26))
    assert _radar_window(dock) == pytest.approx(before)

def test_a_time_zoom_survives_adding_time_zero_on_a_ruled_line(opened):
    ...the same on `opened`'s own ruled line...

def test_a_zoom_at_the_top_stays_at_the_top(opened):
    ...zoom to (t0, t0 + 10) first; after adding time_zero the window is (new t0, new t0 + 10)...

@needs_real_data
def test_a_time_zoom_survives_time_zero_on_the_campus_line(opened):
    # FILE__007 (next(p for p in CAMPUS_LINES if p.name == "FILE__007.DZT")) on GRID at
    # GridPlacement("A", "y", 0.0, 0.0, 1, "FILE__007"), samples set, _zoom_middle, then:
    #   append time_zero(mode="first_break")          -> _radar_window unchanged
    #   replace it with time_zero(mode="sample", sample=52) -> _radar_window unchanged
    ...

@pytest.mark.skipif(not GPS_LINES, reason="needs the with-dzg lines in tests/data/local")
def test_a_time_zoom_survives_time_zero_on_a_gps_line(qgis_app, tmp_path):
    # GPS_LINES[0] on Grid("G", (500.0, 700.0), 0.0, 30.0, 29.98, "EPSG:32616", 0.5) at
    # GridPlacement("G", "y", 0.25, 0.0, 1, "l0"), as test_plugin_edit_lines_measure.py places
    # them; the same two edits (sample=47 for the second) and the same two assertions.
    ...
```

- [ ] **Step 5: Run and check that they fail.** Expected: the unruled test fails (reset to Fit), and the ruled tests fail (window slid by the zero change).

- [ ] **Step 6: Implement** the new rule, `_axes_zero` and the callers' `zero_ns`.

- [ ] **Step 7: Run the touched files, then `test_plugin_time_cutoff.py`, `test_plugin_profile_cut.py`, `test_plugin_velocity_fit.py`, the real-data marker and pure**

  The broad trigger can change older expectations on unruled lines. A failure must be one of two things:
  - **the intended change:** the same line kept its zoom on a record or clock change. Re-pin that test with a comment citing spec §4.8, and list it in the task report;
  - **a bug:** anything else. Fix it.

- [ ] **Step 8: Commit and push**

```bash
git commit -am "feat(profile): a time zoom survives a change of clock or record on the same line (#163 item 2)"
git push
```

---

## After Plan A

- Plan B (#158) is written next, from spec §4.9–§4.13. It reuses `carry_time_window`, `_set_axes_holding(zero_ns=…)` and the `_axes_zero` bookkeeping unchanged.
- The walkthrough, deploy and merge wait for Plan B; one PR covers both plans.
