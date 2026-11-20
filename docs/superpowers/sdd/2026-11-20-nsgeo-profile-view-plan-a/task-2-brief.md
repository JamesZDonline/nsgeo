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

