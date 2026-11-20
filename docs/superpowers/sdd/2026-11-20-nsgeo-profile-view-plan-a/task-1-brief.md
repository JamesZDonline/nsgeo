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

