### Task 3: `ProfileDock` rules each line and holds the window across lines

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`
- Modify: `docs/guide/getting-started.md` (the **nsgeo Profile** bullet)
- Test: modify `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py`
- Test: modify whichever existing QGIS tests fail only because their fixture lines now sit on a ruler (see Step 6)

**Interfaces:**
- Consumes: `Ruler`, `ruler_for`, and `ProfileView.set_axes(..., ruler)`, `.ruler`, `.window_m()`, `.set_window_m(...)` from Tasks 1–2.
- Produces:
  - `ProfileDock._ruler_for(line, distance) -> Ruler | None`. Returns `None` when `distance` is `None` or shorter than two, when the line has no grid (`session.grid_for_line` returns `None`), or when its placement has no `axis`. Otherwise it returns `ruler_for(grid, axis, ...)` over the `_safe_distance` of every line in `session.keys_on_grid(grid.id)` that has the same `axis`.
  - `ProfileDock._set_axes_holding(key: str, n_traces: int, n_samples: int, t0_ns: float, dt_ns: float, distance) -> None`. This is the only place the dock sets the view's axes. Both `_show_line`'s header-only branch and `_render` call it.
  - `ProfileDock._axes_key: str | None`: the key the view's axes were last set for. `_clear_view_only` resets it to `None`.
  - `ProfileDock._on_geometry_changed() -> None`, connected to `session.grids_changed` and `session.lines_changed`.
- Behaviour contract for `_set_axes_holding`. Before calling `set_axes`, capture `old = view.transform`, `old_ruler = view.ruler`, `old_m = view.window_m()` and `old_key = self._axes_key`. Then work through these rules in order:
  1. Same key, and the new transform's `(n_traces, n_samples, bounds, mirrored)` equals the old one's → put `old` back (the exact object, as `test_rerender_with_the_same_shape_keeps_the_current_zoom` pins).
  2. The new ruler and the old ruler are both not `None`, with equal `key`, and `old_m` is not `None` → `view.set_window_m(*old_m, old.time_lo, old.time_hi)`.
  3. No ruler now, and `old` has the same `(n_traces, n_samples)` → put `old` back. This is today's rule, kept for lines without a ruler.
  4. Otherwise leave the fresh fit.

  Then set `_axes_key = key`. `_render` drops its own `keep_window` logic. `_on_geometry_changed` returns early when no line is displayed or the site is closed. When `_ruler_for` on the displayed line differs from `view.ruler`, it calls `_show_line(self._key, is_preview=self._preview_key is not None)`. It swallows `KeyError` for a line removed in the same change, and guards its body like every slot here.

- [ ] **Step 1: Write the failing dock tests** in `test_plugin_profile_dock.py`. The `opened` fixture's line is reversed (`GridPlacement("A", "y", 0.0, 0.0, -1, ...)`, 240 traces, so it runs from 0 m down to −3.98 m) on `GRID` (size_y 11).

```python
def test_a_reversed_line_is_mirrored_against_its_grid_ruler(opened):
    session, dock, key, line = opened
    v = dock.view
    assert (v.ruler.grid_id, v.ruler.axis, v.ruler.hi_m) == ("A", "y", 11.0)
    assert v.ruler.lo_m == pytest.approx(-239 / 60 - 1 / 120)  # the line runs past the grid's 0 edge
    assert v.transform.mirrored

def test_the_same_metre_is_at_the_same_pixel_on_neighbouring_lines(opened):
    # add a forward 300-trace line on A at offset 0.5; record x of metre 2.0 on the opened line
    # (view.transform.x_of_trace(trace_units_at(distance, 2.0))), open the forward line, compare: abs diff < 0.5 px.

def test_zoom_is_held_in_metres_when_the_next_line_opens(opened):
    # zoom_at(4.0, ...) on the opened line; m = view.window_m(); t = (time_lo, time_hi);
    # open the forward line: view.window_m() == approx(m), time window == approx(t), not mirrored.

def test_the_hold_survives_a_preview_and_its_end(opened):
    # zoom; m = window_m(); session.set_preview(forward_key, 5): window_m() == approx(m);
    # session.set_preview("", -1): window_m() == approx(m) and mirrored again.

def test_a_header_only_preview_is_ruled_and_held_through_its_load(opened):
    # forward line with NO set_profiles; zoom on the opened line; preview it: view.ruler is not None,
    # window_m() == approx(m); then session.set_profiles(fwd_key, fwd.load()): window_m() still approx(m).

def test_a_cross_line_or_another_grid_starts_at_fit(opened):
    # zoom; add a line on axis "x" on grid A and open it: ruler key ("A", "x"), window == its bounds.
    # Same with a line on a second grid "B".

def test_the_hold_is_in_metres_across_different_trace_spacings(opened):
    # a forward line written with synthetic_dzt(..., traces_per_metre=50.0); zoom on the opened line, open it:
    # window_m() == approx(m) although trace_hi - trace_lo differs.

def test_a_line_without_distance_neither_mirrors_nor_holds(opened):
    # the time-triggered line the existing FILE__TIME test builds: open it after zooming:
    # ruler is None, not mirrored, window == (0, n_traces); open the reversed line again: at Fit, no error logged.

def test_the_difference_view_keeps_the_mirror_and_the_window(opened):
    # set_profiles, append dewow, zoom, set_difference_index(0): mirrored and window_m() == approx(m);
    # set_difference_index(-1): same.

def test_a_grid_resize_moves_fit_without_reopening_the_line(opened):
    session, dock, key, line = opened
    session.replace_grid(dataclasses.replace(GRID, size_y=20.0))
    assert dock.view.ruler.hi_m == pytest.approx(20.0)
    dock.fit_button.click()
    assert dock.view.window_m()[1] == pytest.approx(20.0)

@needs_real_data
def test_real_zigzag_lines_keep_a_metre_in_place_across_the_sweep(bare):
    # Ten REAL_DZT lines on Grid("R", (0, 0), 0, 20.0, 11.0, ...) along "y" at offsets 0.5*i, placed the way
    # lookup's zigzag does: even i GridPlacement(..., start_along=0.0, direction=1), odd i start_along=11.0, -1.
    # Open line 0; x0 = x of metre 5.0. Preview each other line in turn (set_profiles first): x of 5.0 within 0.5 px.
    # Then zoom so window_m() is about (4.5, 5.5) and sweep again: same check, and window_m() is unchanged.
```

  Write the commented bodies as described. Read the x of a metre with `ruler.trace_units_at(line.distance_along(), m)` through `dock.view.transform.x_of_trace`.

- [ ] **Step 2: Run them and see them fail.** Run: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py -q -p no:xonsh`. Expected: the new tests fail, for example with `assert None == Ruler(...)`.

- [ ] **Step 3: Implement the dock half** to the behaviour contract above. Add a paragraph to the module docstring explaining why the hold reads the window off the line being left, and why rule 1 keeps the exact object.

- [ ] **Step 4: Run the new tests and see them pass.**

- [ ] **Step 5: Update the guide.** Replace the **nsgeo Profile** bullet's "**Fit** fits the whole line in the panel" sentence. The new text says:
  - Every line on a grid is drawn against the grid's length, with the low end on the left, so a line walked the other way is shown mirrored.
  - A short line leaves hatched blank space.
  - Zoom and pan stay on the same stretch of ground when another line on the same grid, running the same way, opens or is hovered on the map.
  - **Fit** shows the whole grid length.
  - The arrow under the distance axis shows which way the line was walked.

  Write it plain but professional, in the voice of the paragraphs around it.

- [ ] **Step 6: Run the whole QGIS tier and repair fallout.** Some existing tests place short lines on large grids, or a reversed line starting at 0, and then assert the old trace-0-left full-extent window or click at fixed pixels. Known so far:
  - `test_fit_button_restores_the_full_extent_after_a_zoom` and `test_one_to_one_button_sets_a_trace_per_pixel_window` in this file.
  - `test_plugin_velocity_fit.py`: 60-trace (1 m) lines on an 11 m grid, clicked at x = 40.

  Rule for each one: keep the test's intent. Prefer making the fixture match what the import would produce, over loosening an assertion. That means a grid sized to its lines along the lines' axis, or a reversed line starting at the far edge. Where the assertion itself pinned trace-0-left behaviour, restate it against the new rule: the window equals `transform.trace_bounds` after Fit, and the screen-left trace holds after 1:1. List every changed test, and why, in the task report.

- [ ] **Step 7: Run both tiers in full, plus lint and types.** Record the counts. The real-data test must not be among the skips.

- [ ] **Step 8: Commit and push.**

```bash
git add packages/nsgeo-qgis docs/guide/getting-started.md
git commit -m "feat(plugin): one ruler per grid, and the view holds its metres from line to line (#67)"
git push
```

---

