### Task 5: The panel fits Processing's minimum, and opens without sideways scroll (#121, #50)

Spec §8.

**Files:**
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_width.py`
- Modify: `tests/qgis/test_plugin_slices_dock.py:2103-2140`
  (`test_the_dock_minimum_does_not_force_the_main_window_to_grow`: drop only its
  `sizeHint().width() >= 280` line, now covered by the opening test)
- Modify, as the measurement shows: `nsgeo_qgis/ui/slices_dock.py` and the panels it holds
- Modify: `packages/nsgeo-qgis/README.md` (the stale "On Qt 6, the dock-width test is an expected
  failure until #50" sentence; the xfail went in 4e39772)

**Interfaces:**
- Consumes: Task 2's `warnings_panel` and Task 4's folding boxes, which are both in the panel being
  measured.
- Produces `width_fonts(points: float) -> context manager`, a test helper in the new file. It sets
  `QApplication.font()` with `setPointSizeF(points)` and restores the old font on exit. Build the
  docks inside it.

- [ ] **Step 1: Measure first** (spec §8.2, the builder check).
  - **What:** write a scratch script, not committed. At 9, 11 and 14 pt it prints:
    - `ProcessingDock(session).minimumSizeHint().width()`;
    - the Slices content's `minimumSizeHint().width()` in both scopes;
    - each top-level row's own minimum width.
  - **Session:** use one with three grids of synthetic lines (`site3`'s shape), a long cube name in
    `cube_combo`, the slider on its last slice (the longest readout), and every section unfolded.
    The memory label counts too, so set it to the GB form of its text.
  - **Report:** list the rows over the rule. Then, for each, apply one of these:
    - **wrap** `velocity_label` and `included_label`;
    - **cap the combo's content width** on `cube_combo` (`AdjustToMinimumContentsLengthWithIcon`,
      `setMinimumContentsLength(12)`);
    - **stack a label above its box.**

    The Interpolation row may be stacked only if the measurement puts it over.

- [ ] **Step 2: Write the guard tests** in `test_plugin_slices_width.py`:

```python
@pytest.mark.parametrize("points", [9.0, 14.0])
@pytest.mark.parametrize("scope", ["grid", "site"])
def test_the_slices_panel_fits_the_processing_panels_minimum(qgis_app, site3, points, scope):
    with width_fonts(points):
        session = _open_site(site3)            # three grids, lines, a preset
        limit = ProcessingDock(session).minimumSizeHint().width()
        dock = SlicesDock(session)
        dock.cube_combo.addItem("a cube name long enough to widen any combo box at all, 60 c")
        # every section unfolded; scope switched and settled
        dock.setFloating(True); dock.resize(limit, 500); dock.show(); settle
        scroll = dock.findChild(QScrollArea)
        assert scroll.verticalScrollBar().maximum() > 0       # the vertical bar is showing
        assert scroll.horizontalScrollBar().maximum() == 0    # nothing scrolls sideways

@needs_real_data
@pytest.mark.parametrize("points", [9.0, 14.0])
def test_a_real_site_fits_the_processing_panels_minimum(qgis_app, tmp_path, points):
    # the same on four REAL_DZT lines on one grid, both scopes; it skips cleanly in CI

@pytest.mark.parametrize("scope", ["grid", "site"])
def test_the_panel_opens_at_least_as_wide_as_its_contents(qgis_app, site3, scope):
    # dock.resize(dock.sizeHint()); show; settle -> horizontalScrollBar().maximum() == 0
```

- [ ] **Step 3: Run them; expect a failure.** Each failing row from Step 1 fails the guard. The
  opening test fails if `QScrollArea.sizeHint` leaves out the vertical bar.

- [ ] **Step 4: Make the rows give way, and make the dock open wide enough.** For the opening
  width, one option is a `QScrollArea` subclass whose `sizeHint` adds
  `verticalScrollBar().sizeHint().width()`.

- [ ] **Step 5: Run the width tests and the existing layout tests.** All must be green:
  - `test_the_dock_minimum_does_not_force_the_main_window_to_grow`;
  - `test_the_indicator_never_raises_the_dock_minimum_width`;
  - `test_the_refine_states_do_not_move_the_panel_under_the_wheel`;
  - `test_plugin_site_scope.py -k "layout or width or wheel"`.

- [ ] **Step 6: Run the whole local suite.** Both tiers must be green:
  - `QT_QPA_PLATFORM=offscreen ../../.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q`;
  - `../../.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q`.

- [ ] **Step 7: Run the Qt 6 image** (Review Focus 5). Expect green:

```bash
packages/nsgeo-qgis/scripts/in_qgis_docker.sh qgis/qgis:4.2 \
    python3 -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_slices_width.py \
    packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py \
    packages/nsgeo-qgis/tests/qgis/test_plugin_edit_lines_dialog.py \
    packages/nsgeo-qgis/tests/qgis/test_plugin_warnings_panel.py -q -p no:cacheprovider
```

- [ ] **Step 8: Fix the README sentence.** Replace it with one line: the Slices panel's width is
  pinned to the Processing panel's minimum by `test_plugin_slices_width.py`.

- [ ] **Step 9: Commit and push.** Message:
  `feat(slices): the panel fits the Processing panel's minimum and opens without sideways scroll (#121, #50)`.

---

## After the plan (controller, not tasks)

These are spec §11 and §14 and the session process:
1. **Whole-branch review.**
2. **Deploy** to a new QGIS profile `ns_geo_wheel` with `scripts/dev_link.py`.
3. **Walkthrough artifact** covering spec §11.
4. **Merge** only when the author says so.
5. **At merge:** the PR closes #177, #176, #105 and #121. Comment on #157 (items 4, 5 and 6),
   #163 (item 1) and #50, without closing them; #121's comment explains the change of target.
   Update the README roadmap.
