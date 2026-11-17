### Task 4: Sections that fold, and the coverage view explained (#157 item 6)

Spec §6.2 and §7.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/folds.py`
- Modify: `nsgeo_qgis/ui/slices_dock.py` (`resolution_group`, `display_group` become
  `QgsCollapsibleGroupBox`; wire folds after the panels exist; `coverage_check` tooltip)
- Modify: `nsgeo_qgis/ui/finish_panel.py` (`FinishPanel` base class)
- Modify: `nsgeo_qgis/ui/site_panel.py` (`NormalisationPanel`'s inner group, exposed as `self.group`)
- Modify: `packages/nsgeo-qgis/tests/qgis/conftest.py` (autouse settings fixture)
- Modify: `docs/guide/getting-started.md` (Show coverage, ~559-570; step 3, ~490)
- Test: `tests/qgis/test_plugin_slices_dock.py`, `tests/qgis/test_plugin_site_scope.py`

**Interfaces:**
- Produces, in `ui/folds.py`:
  - `FOLD_GROUP = "nsgeo/slices/folded"`;
  - `fold_settings() -> QSettings`, which returns `QgsSettings()`. It is the only way fold state
    is read or written.
  - `remember_folds(name: str, boxes: Sequence[QgsCollapsibleGroupBox]) -> None`, which:
    - turns off QGIS's own saving on each box (`setSaveCollapsedState(False)`,
      `setSaveCheckedState(False)`);
    - sets each box from `f"{FOLD_GROUP}/{name}"` (default unfolded);
    - on any box's `collapsedStateChanged`, writes the key and sets the others alike, guarded
      against re-entry.
- Calls in the dock:
  - `remember_folds("resolution", [resolution_group])`;
  - `remember_folds("interpolation", [grid_finish, site_finish])`;
  - `remember_folds("normalisation", [normalisation_panel.group])`;
  - `remember_folds("display", [display_group])`.
- Produces `slices_dock.COVERAGE_TIP` (exact copy, spec §7):
  `"Shows how many traces fell in each cell, instead of the amplitude.\nUse it to see where your lines ran and where there is no data: blank cells had no line through them.\nIn a Whole site preview each pixel shows the largest count among the cells under it, so lines look wider than they are."`
- Conftest: an autouse fixture patches `nsgeo_qgis.ui.folds.fold_settings` to return
  `QSettings(str(tmp_path / "folds.ini"), QSettings.Format.IniFormat)`.

- [ ] **Step 1: Check the preview's coverage draw.** Read how a Whole site preview reduces coverage
  counts to its coarser pixel (`site_engine.py`, the coverage branch of `slice_at`). If it doesn't
  take the largest count, change `COVERAGE_TIP`'s last sentence and the guide's to say what it does.
  Say so in the task report.

- [ ] **Step 2: Write the failing tests.**

```python
FOLDING = ("resolution_group", "grid_finish", "display_group")

def test_each_settings_section_folds_and_unfolds(docked):
    # float + show; for each name: box.setCollapsed(True); events; box.isCollapsed() and
    # box.height() < its unfolded height; setCollapsed(False) restores it.

def test_source_position_and_warnings_do_not_fold(docked):
    for name in ("source_group", "position_group", "warnings_panel"):
        assert not isinstance(getattr(dock, name), QgsCollapsibleGroupBox)

def test_every_section_starts_unfolded(docked):
    # every box in FOLDING plus site_finish and normalisation_panel.group: not isCollapsed()

def test_the_two_interpolation_panels_fold_together(docked):
    # shown; grid_finish.setCollapsed(True) -> site_finish.isCollapsed()
    # (site_finish is hidden in This grid: QGIS applies its fold when it shows)

def test_folds_are_remembered_across_a_restart(docked):
    # shown; display_group.setCollapsed(True)
    # -> folds.fold_settings().value("nsgeo/slices/folded/display", type=bool) is True;
    # a new SlicesDock(session).display_group.isCollapsed() is True

def test_fold_state_never_touches_a_real_settings_file(tmp_path):
    assert Path(folds.fold_settings().fileName()).parent == tmp_path

def test_the_coverage_tooltip_explains_what_and_how_a_preview_draws_it(docked):
    assert dock.coverage_check.toolTip() == COVERAGE_TIP
```

In `test_plugin_site_scope.py`, add
`test_the_normalisation_section_folds_and_is_remembered(plugin)`.

- [ ] **Step 3: Run them; expect failures** (no `folds` module; plain group boxes).

- [ ] **Step 4: Implement.**
  - `FinishPanel(QgsCollapsibleGroupBox)` keeps `super().__init__("Interpolation", parent)`.
  - `NormalisationPanel` builds `self.group = QgsCollapsibleGroupBox("Normalisation")`.
  - Folding is wired after all four panels exist.
  - The coverage tooltip becomes `COVERAGE_TIP`.

- [ ] **Step 5: Edit the guide** (`docs/guide/getting-started.md`).
  - **Show coverage:** add the preview sentence, as worded in `COVERAGE_TIP`.
  - **Step 3** (Resolution), *my call: the guide would otherwise go stale*, three sentences:
    - the mouse wheel changes **Cell size**, **dz**, **z0** and **z1** only once you have clicked
      into the box, so scrolling past them changes nothing;
    - **dz** can't go below the radar's own sample interval;
    - the **Resolution**, **Interpolation**, **Normalisation** and **Display** headers fold their
      sections away, and nsgeo remembers which are folded.
  - **Warnings:** one sentence where step 4 says a preview "says so in the panel": it now says so
    under **Warnings**, below **Position**.

- [ ] **Step 6: Run the dock, site scope, finish panel and site panel test files; all green.**

- [ ] **Step 7: Commit and push.** Message:
  `feat(slices): settings sections fold and remember it; explain the coverage view (#157)`.

---

