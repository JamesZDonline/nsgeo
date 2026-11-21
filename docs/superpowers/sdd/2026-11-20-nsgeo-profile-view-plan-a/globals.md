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

