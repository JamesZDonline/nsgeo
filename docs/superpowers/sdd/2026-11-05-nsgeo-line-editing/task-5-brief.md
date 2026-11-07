### Task 5: Survey panel entries, Move to grid, and the guide

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/survey_dock.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`:
  - connect `edit_lines_requested` to `open_edit_lines_dialog`;
  - connect `move_lines_requested` to a new `move_lines`.
- Modify: `docs/guide/getting-started.md`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py` for the menus, and `packages/nsgeo-qgis/tests/qgis/test_plugin_edit_lines_dialog.py` for the plugin's `move_lines`.

**Interfaces:**
- Consumes: `open_edit_lines_dialog` (Task 4) and `SiteSession.move_lines` (Task 2).
- Produces, in `SurveyDock`:
  - `edit_lines_requested = pyqtSignal(str, list)`, carrying the grid id and the keys to select;
  - `move_lines_requested = pyqtSignal(list, str)`, carrying the keys and the target grid id;
  - `self.move_menu = QMenu("Move to grid", self)`, made once in `__init__` and refilled on every right-click. It is added with `menu.addMenu(self.move_menu)`, so `context_menu.clear()` never leaves a submenu behind;
  - fix the `__init__` comment that says there are no submenus.
- Produces, in the plugin: `move_lines(self, keys: list[str], grid_id: str) -> None`.
  - It calls `session.move_lines(keys, grid_id)`.
  - `KeyError` or `ProjectError` go to the message bar at Critical.
  - Otherwise it sends `f"Move to {grid_id}: {outcome.message()}"`, at Warning when anything was skipped and Info otherwise.

The menus (texts exact; separators as today, before the destructive entry):
- **Grid:**
  - `["Edit grid…", "Edit lines…", "Import DZT files…", "Set velocity…", "Remove grid"]`;
  - "Edit lines…" is disabled when the grid has no lines, and emits `edit_lines_requested(gid, [])`.
- **One line:**
  - `["Open", "Edit line…", "Set velocity override…", "Move to grid", "Remove line from site"]`;
  - "Edit line…" emits `edit_lines_requested(<its grid>, [key])`.
- **A selection holding lines** (`_selected_targets` gives keys):
  - `"Edit {n} lines…"`, only when every key is on one grid, which emits `edit_lines_requested(grid, keys)`;
  - then `f"Move {n} lines to grid"` and `f"Remove {n} lines from site"`.
  - A selection of grids only keeps today's single Remove entry.
- **The submenu** lists every grid id in site order. Each entry emits `move_lines_requested(keys, gid)`. An entry is disabled when every selected line is already on that grid. The submenu's title is set on each refill, to "Move to grid" or `f"Move {n} lines to grid"`.

- [ ] **Step 1: Write the failing tests** in `test_plugin_survey_dock.py`, using `dock`, `answer_modal(QMenu, "exec", None)` and `_right_click`/`_texts`:
  - **Change** `test_the_context_menu_offers_the_right_actions_for_each_kind_of_item` to the grid and line lists above. Its separator checks stay.
  - `test_edit_lines_is_greyed_on_a_grid_with_no_lines`: add an empty grid B.
  - `test_edit_line_and_edit_n_lines_ask_for_the_table_with_those_rows`: one line gives `edit_lines_requested` `("A", [key])`. Two selected lines on A give `("A", [k0, k1])` from `"Edit 2 lines…"`.
  - `test_a_selection_spanning_grids_offers_move_but_no_edit`: add grid B with a line and select a line on each grid. The texts are `["Move 2 lines to grid", "Remove 2 lines from site"]`.
  - `test_the_move_submenu_lists_every_grid_and_greys_the_one_they_are_on`: entries `["A", "B"]`, with A disabled for a line on A. Triggering B emits `move_lines_requested([key], "B")`.
  - `test_the_move_submenu_leaves_nothing_behind`: `n = len(dock.findChildren(QMenu))`, then five right-clicks on a line, leave `len(dock.findChildren(QMenu)) == n` and `dock.context_menu.findChildren(QMenu) == []`.
  - `test_move_lines_moves_them_and_reports_on_the_bar`, in `test_plugin_edit_lines_dialog.py` (plugin, `fake_iface`):
    - `plugin.move_lines([k], "B")` puts the line on B, and `message_log` has `"Move to B: changed 1 line(s)"`;
    - an unknown grid logs at Critical without raising.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** the menus, the reused submenu, the two signals and their plugin connections. Every lambda's work is guarded, as `_on_context_menu`'s comment requires.
- [ ] **Step 4: Update the guide.**
  - **The nsgeo Survey bullet in *The panels*:**
    - a grid's menu gains **Edit lines…**;
    - a line's menu gains **Edit line…** and **Move to grid**;
    - a selection of lines on one grid offers **Edit N lines…**, and any selection of lines offers **Move N lines to grid**.
  - **A new short subsection, *Fixing lines after import*,** after Step 3's import text:
    - **Edit lines…** opens a table of every line on the grid, in survey order. Label, Offset, Dir, Start and Grid can be changed.
    - ↑ and ↓ set the order the Survey panel shows.
    - The panel under the table changes every selected line at once: Set a Start, **Snap to grid edge**, Shift the offset, Flip the direction, or Move to another grid.
    - Note flags a line that starts off its edge, or that lies outside the grid's width.
    - Nothing changes until **OK**, and then everything changes as one step. Picks move with their lines.
    - Changing a grid's length in **Edit grid…** moves its reversed lines with the far edge, and the message bar says so.
- [ ] **Step 5: Run the survey dock file, then both tiers, lint and types.** Expected: all pass, with no new skips.
- [ ] **Step 6: Commit and push.**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/ui/survey_dock.py packages/nsgeo-qgis/nsgeo_qgis/plugin.py docs/guide/getting-started.md packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py packages/nsgeo-qgis/tests/qgis/test_plugin_edit_lines_dialog.py
git commit -m "feat(ui): Edit lines and Move to grid from the Survey panel; the guide (#29, #64)"
git push origin nsgeo-line-editing
```

---

