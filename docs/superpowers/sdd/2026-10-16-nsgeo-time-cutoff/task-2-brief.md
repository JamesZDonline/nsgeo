### Task 2: The draggable cutoff line in `ProfileView`

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`: add `ViewTransform.snap_cutoff`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py`
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_view_transform.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py`

**Interfaces:**
- Produces: `ViewTransform.snap_cutoff(time_ns: float) -> float`. It returns `t0_ns + m * dt_ns` with `m = round((time_ns - t0_ns) / dt_ns)`, clamped to `[1, n_samples]`. So the line always sits on a sample boundary, keeps at least one sample, and never passes `t_end`.
- Produces in `profile_view.py`: the constants `CUTOFF_COLOUR = QColor(214, 39, 140)`, `CUTOFF_DIM = QColor(250, 250, 250, 170)` and `CUTOFF_GRAB_PX = 5`, and the module function `cutoff_label(end_ns: float, velocity: VelocityModel | None) -> str`. It returns `f"{end_ns:.1f} ns"`, and appends `f" · {depth:.2f} m"` when a velocity is given, with `depth = float(velocity.depth_at(np.array([end_ns]))[0])`.
- Produces on `ProfileView`:
  - `cutoff_dragged = pyqtSignal(float)`. It is emitted once, on the left-button release that ends a drag of the line, carrying the snapped end time in ns.
  - `set_cutoff(end_ns: float | None) -> None`. `None` hides the line. A non-finite value is logged and treated as `None`, the same as `set_slice_band`. If a drag is in progress, it is abandoned: no emit, and the new value is taken.
  - `cutoff_ns -> float | None`, a read-only property. It is the value drawn now, live during a drag.
  - `_cutoff_y(t: ViewTransform) -> float | None`, the line's local y, factored out like `_slice_band_bounds` so tests can assert on it without pixels. The time is clamped into `[t.t0_ns, t.t_end]` before `t.y_of_time`.

- [ ] **Step 1: Write the failing pure tests** in `test_pure_view_transform.py`:

```python
def test_snap_cutoff_rounds_to_the_nearest_sample_boundary():
    t = ViewTransform.fit(100, 200, -4.0, 0.5, 400, 300)
    assert t.snap_cutoff(20.3) == pytest.approx(20.5)  # (20.3 + 4) / 0.5 = 48.6 -> 49
    assert t.snap_cutoff(20.2) == pytest.approx(20.0)

def test_snap_cutoff_clamps_into_the_record():
    t = ViewTransform.fit(100, 200, -4.0, 0.5, 400, 300)
    assert t.snap_cutoff(-100.0) == pytest.approx(-3.5)  # one sample kept
    assert t.snap_cutoff(1e6) == pytest.approx(t.t_end)
```

- [ ] **Step 2: See them fail, implement `snap_cutoff`, see them pass.** Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_view_transform.py -q`.

- [ ] **Step 3: Write the failing view tests** in `test_plugin_profile_view.py`. Use the existing `view` and `make_view` fixtures. The `view` fixture is 200 traces by 128 samples, dt 0.5, t0 -4.0, so the record runs from -4.0 to 60.0 ns. Use `_send_move_while_pressed` for any mid-drag move; plain `QTest.mouseMove` is never delivered while a button is down (see `test_drag_selects_a_trace_range`'s docstring).

  - `test_the_cutoff_line_sits_at_its_time`: `set_axes(100, 200, 0.0, 0.5)`, `set_cutoff(40.0)`, then `_cutoff_y(t) == approx(t.y_of_time(40.0))` and `cutoff_ns == 40.0`.
  - `test_a_cutoff_past_the_record_is_drawn_at_its_bottom_edge`: `set_cutoff(1e6)` puts the y at `t.y_of_time(t.t_end)`.
  - `test_set_cutoff_none_hides_it_and_a_non_finite_one_is_logged` (uses the `message_log` fixture): `None` gives `_cutoff_y(...) is None`; `float("nan")` gives `None` plus one log entry.
  - `test_the_cutoff_dims_the_samples_below_it`: paint a solid black `QImage` (`QImage(200, 128, QImage.Format.Format_RGB32)` filled with black) with `set_cutoff(30.0)`. In `grab_image()`, at `x = r.left() + 20` (clear of the right-aligned label), a pixel 10 px below the line is lighter than one 10 px above, and a pixel on the line row has a red channel of at least 150.
  - `test_the_label_names_the_time_and_the_depth`: `cutoff_label(40.0, None) == "40.0 ns"` and `cutoff_label(40.0, VelocityModel.constant(0.08)) == "40.0 ns · 1.60 m"`.
  - `test_dragging_the_cutoff_emits_the_snapped_time_once_on_release`: `set_cutoff(40.0)`. Press left at `(r.left() + 100, r.top() + round(_cutoff_y))`. Move to local y `y2 = round(t.y_of_time(20.3))`, then release there. `cutoff_dragged` fired exactly once with `approx(t.snap_cutoff(t.time_of_y(y2)))`. `range_selected` and `selection_cleared` never fired. `cutoff_ns` equals the emitted value.
  - `test_dragging_above_the_record_keeps_one_sample`: the same press, a move to local y `-50`, then release. The emitted value is `approx(-4.0 + 0.5)`.
  - `test_a_press_away_from_the_line_still_selects_a_range`: `set_cutoff(40.0)`, then repeat `test_drag_selects_a_trace_range`'s gesture at `r.top() + 50`, which is far from the line. `range_selected == [(28, 86)]` and `cutoff_dragged` never fired.
  - `test_pick_mode_wins_over_the_cutoff_grab`: `set_pick_mode(True)`, then press on the line. `pick_requested` fired once and `cutoff_dragged` never fired after the release.
  - `test_a_move_without_the_button_abandons_the_drag`: press on the line, move with the button held (`cutoff_ns` changes), then `send_hover` with no button held. `cutoff_ns` is back to `40.0`. A following release emits nothing.
  - `test_set_cutoff_during_a_drag_abandons_it`: press on the line, move, then `set_cutoff(30.0)`, then release. Nothing is emitted and `cutoff_ns == 30.0`.
  - `test_hovering_the_line_shows_a_resize_cursor`: `send_hover` on the line gives `cursor().shape() == Qt.CursorShape.SizeVerCursor`. Hovering away gives `ArrowCursor`, or `CrossCursor` in pick mode.
  - `test_clear_forgets_the_cutoff`: `clear()` gives `cutoff_ns is None`.

- [ ] **Step 4: Run them and see them fail.** Run: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py -q -p no:xonsh -k "cutoff or label"`.

- [ ] **Step 5: Implement the overlay and the gesture in `profile_view.py`.**
  - Painting: `_paint_cutoff(p, r, t)` is called in `paintEvent` right after `_paint_slice_band` and before `_paint_selection`, so the selection, picks and cursor stay on top. It fills `CUTOFF_DIM` from the line down to `r.bottom()`, draws a 2-px `CUTOFF_COLOUR` line across `r`, and draws `cutoff_label(self.cutoff_ns, self._velocity)` right-aligned just above the line, inside `r`.
  - Precedence on a left press: pick (pick mode or Shift), as today. Then the cutoff grab, when a cutoff is shown, the press is inside the image (`0 <= x < t.width` and `0 <= y < t.height`) and `abs(y - _cutoff_y) <= CUTOFF_GRAB_PX`. Then the existing range-select arming. A cutoff grab records the starting value and does not arm `_press`, so its release can neither commit nor clear a selection.
  - A move during a grab: if `event.buttons()` lacks the left button, abandon (the I3 pattern in `_handle_mouse_move`). Otherwise set the value to `t.snap_cutoff(t.time_of_y(y))` and `update()`.
  - A left release during a grab ends it and emits `cutoff_dragged(self.cutoff_ns)`. Always emit; the no-op guard lives in the dock (Task 3).
  - Hover with no grab: set `SizeVerCursor` near the line. Otherwise restore the cursor `set_pick_mode` would set.
  - `clear()` resets the cutoff and any grab.
  - Extend the module docstring's opening line to name the cutoff line among the overlays.

- [ ] **Step 6: Run them and see them pass.** Then run the whole `test_plugin_profile_view.py` file, and the pure tier for `test_no_orphan_signals.py`. `cutoff_dragged` has no consumer until Task 3, so if that test fails here, add a one-line `KNOWN_UNCONSUMED` entry naming Task 3, and remove it in Task 3.

- [ ] **Step 7: Lint, types, commit, push.**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/ui packages/nsgeo-qgis/tests
git commit -m "feat(plugin): a draggable cutoff line on the profile view"
git push
```

---

