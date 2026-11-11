### Task 4: The Edit lines table and its bulk panel

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/edit_lines_dialog.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`:
  - add `open_edit_lines_dialog` and `self._edit_lines_dialogs: dict[str, EditLinesDialog] = {}`;
  - `unload()` calls `reject()` on each open one, the way it does for `_import_dialog`, with the same comment shape.
- Test: create `packages/nsgeo-qgis/tests/qgis/test_plugin_edit_lines_dialog.py`

**Interfaces:**
- Consumes: `LineEdit`, `Inset`, `EditOutcome`, `placement_note`, `same_placement`, `length_along` and `width_across` from `line_edit.py`, and `SiteSession.edit_lines` (Task 2).
- Produces, in `ui/edit_lines_dialog.py`:
  - Column constants `COL_LABEL, COL_OFFSET, COL_DIR, COL_START, COL_GRID, COL_ALONG, COL_TRACES, COL_LENGTH, COL_PICKS, COL_NOTE = range(10)`.
  - `HEADERS = ["Label", "Offset (m)", "Dir", "Start (m)", "Grid", "Along", "Traces", "Length (m)", "Picks", "Note"]`.
  - `EDITABLE = {COL_LABEL, COL_OFFSET, COL_DIR, COL_START}`. Grid is a `QComboBox` cell widget listing every grid id.
  - `CHANGED = QColor(255, 236, 179)`, the background of every cell whose field differs from the line's `seen` placement.
  - `class EditLinesDialog(QDialog)`:
    - `__init__(self, session: SiteSession, grid_id: str, *, select: Sequence[str] = (), parent: QWidget | None = None)`. It reads the grid's keys, their placements as `seen` and their pick counts (`len(session.picks_for(key))`) once, and records `session.json_path`.
    - Attributes:
      - `grid_id`, `outcome: EditOutcome | None = None`;
      - `table`, `header_label`, `up_button` ("↑"), `down_button` ("↓");
      - `bulk: QGroupBox`;
      - `start_spin`, `set_start_button` ("Set"), `snap_button` ("Snap to grid edge");
      - `offset_spin`, `shift_button` ("Shift");
      - `flip_button` ("Flip");
      - `grid_combo`, `move_button` ("Move");
      - `status: QLabel`, `buttons` (OK | Cancel).
    - Methods:
      - `keys(self) -> list[str]` gives the table's row order;
      - `edit_for(self, key: str) -> LineEdit`;
      - `select_keys(self, keys: Iterable[str]) -> None` and `selected_keys(self) -> list[str]`;
      - `set_start(self, value: float) -> None`, `snap_to_edge(self) -> None`, `shift_offset(self, delta: float) -> None`, `flip(self) -> None` and `move_to(self, grid_id: str) -> None` each act on the selected rows;
      - `move_selected(self, delta: int) -> None` moves every selected row one place up (`-1`) or down (`+1`), keeping their order. It does nothing when one would leave the table;
      - `accept(self) -> None`.
- Produces, in the plugin: `open_edit_lines_dialog(self, grid_id: str, keys: Sequence[str] = ()) -> None`.
  - At most one dialog per grid. Opening it again calls `select_keys(keys)`, `show()`, `raise_()` and `activateWindow()`.
  - On `finished` with Accepted and an outcome: `self.message(f"Edit lines · {grid_id}: {dialog.outcome.message()}", Warning if dialog.outcome.skipped else Info)`.
  - It then calls `deleteLater()` and removes the dialog from the dict. A `destroyed` guard clears the entry only if it still names this dialog (the `open_import_dialog` pattern).

What the table shows and does:
- **Title and header.**
  - The title is `f"Edit lines · {grid_id}"`.
  - When every line runs along one axis `a`, the header reads `f"{grid_id} · {length_along(g, a):.2f} m along {a} × {width_across(g, a):.2f} m across · {n} lines"`. Otherwise it reads `f"{grid_id} · {g.size_x:.2f} m × {g.size_y:.2f} m · {n} lines"`.
- **Rows.** Each row shows `edit_for(key).placed(session.site.frames)`. Start and Offset show 2 decimals. Dir shows `"+1"` or `"−1"`. Along is the axis. Traces is `n_traces`. Length is `n_traces / traces_per_metre` to 2 decimals, blank when that is not positive. Picks is the count. Note is `placement_note(placed, frames[placed.grid_id])`.
- **Cell edits** (`itemChanged`, guarded by `_updating`):
  - Label: the text, or the file stem when the cell is empty.
  - Offset and Start: a float, with a comma accepted as the decimal mark. Anything else sets the status to `f"{text!r} is not a number; unchanged"` and refreshes the row.
  - Dir: parsed like `ImportDialog`. A leading minus means −1, and a positive number means +1. Anything else sets the status to `f"{text!r} is not recognised as a direction; unchanged"`. A direction that differs from the shown one is `flipped`.
  - The Grid combo calls `moved_to`.
  - Every edit refreshes the table and the status line.
- **Bulk panel.**
  - It is titled `f"Change the {n} selected lines"`, and greyed when no row is selected.
  - Set gives `start_along=start_spin.value()`. Snap gives `snapped()`. Shift gives `shifted(offset_spin.value(), frames)`. Flip gives `flipped`. Move gives `moved_to(grid_combo.currentText(), frames)`.
  - ↑ and ↓ are greyed when they could not move the selection.
- **Status line.** `n` counts the rows whose edit `changes(frames)`. `m` sums the pick counts of those rows whose label-free placement changed. The line is:
  - `""` when `n == 0`;
  - otherwise `f"{n} line{'s' if n != 1 else ''} changed · {m} pick{'s' if m != 1 else ''} will move with {'them' if n != 1 else 'it'}"`.
- **Guards.** Every method that reads the grid or the frames catches `KeyError` and `ProjectError`, then puts `f"grid {grid_id!r} no longer exists"` or `"no site is open"` on the status line instead of raising.
- **`accept()`:**
  1. With no site open, the status reads `"no site is open; nothing was changed"`.
  2. When `json_path` changed, it reads `"a different site was opened while the table was open; nothing was changed"`.
  3. When the grid is gone, it reads `f"grid {grid_id!r} no longer exists; nothing was changed"`.
  4. Otherwise `self.outcome = session.edit_lines([e for e in edits if e.changes(frames)], grid_id=self.grid_id, order=self.keys())` and `super().accept()`. A `KeyError`, `ValueError` or `ProjectError` from it goes to the status line and the dialog stays open.

- [ ] **Step 1: Write the failing tests.** The fixture `table(qgis_app, tmp_path)` builds:
  - `Grid("Grid5", (500.0, 700.0), 0.0, 15.0, 15.0, "EPSG:32616", 0.5)` with six 60-trace lines along y, labelled `line 1`–`line 6`, at offsets `0.25 + 0.5 * i`:
    - rows 0, 2 and 4 forward at 0.0;
    - rows 1 and 3 reversed at 16.0, the stale case;
    - row 5 reversed at 15.0;
  - `Grid("B", (600.0, 700.0), 0.0, 10.0, 9.0, "EPSG:32616", 0.5)`;
  - and yields `(session, EditLinesDialog(session, "Grid5"))`, hiding and `deleteLater()`-ing the dialog afterwards.

```python
def _cell(dialog, row, col):
    return dialog.table.item(row, col).text()


def test_snap_on_every_row_fixes_the_stale_reversed_lines_and_nothing_else(table):
    session, dialog = table
    keys = dialog.keys()
    changed = Spy(session.lines_changed)
    dialog.select_keys(keys)
    dialog.snap_to_edge()
    assert [_cell(dialog, r, COL_START) for r in range(6)] == ["0.00", "15.00", "0.00", "15.00", "0.00", "15.00"]
    assert [dialog.table.item(r, COL_START).background().color() == CHANGED for r in range(6)] == [
        False, True, False, True, False, False]
    assert dialog.status.text() == "2 lines changed · 0 picks will move with them"
    assert session.line_for_key(keys[1]).placement.start_along == 16.0  # nothing before OK
    dialog.accept()
    assert [session.line_for_key(k).placement.start_along for k in keys] == [0.0, 15.0, 0.0, 15.0, 0.0, 15.0]
    assert set(dialog.outcome.changed) == {keys[1], keys[3]} and len(changed.calls) == 1
```

  - **Add** the rest by name, with these assertions (`Spy` as in `test_plugin_session.py`):
    - `test_the_table_lists_the_grids_lines_in_survey_order_with_their_placements`:
      - labels, Start, Dir, the Grid combo's text, Along `"y"`, Traces `"60"` and Length `"1.00"`;
      - Note `"starts 1.00 m past the far edge"` on rows 1 and 3 and `""` elsewhere;
      - the header reads `"Grid5 · 15.00 m along y × 15.00 m across · 6 lines"` and the title `"Edit lines · Grid5"`.
    - `test_cancel_applies_nothing`: snap and shift, then `reject()`. No placement changed and no `lines_changed`.
    - `test_flip_sends_start_to_the_other_edge_and_back`: on row 0, the first flip shows `"−1"`/`"15.00"` highlighted. The second shows `"+1"`/`"0.00"` with no highlight, and the status is `""`.
    - `test_typing_in_a_cell_edits_only_that_row`: Label, Offset (`"0,40"`), Start and Dir typed on row 2 change only row 2's edit.
    - `test_a_cell_that_is_not_a_number_is_reverted_and_says_so`:
      - `"abc"` in Offset sets the status to `"'abc' is not a number; unchanged"`, the cell back to `"1.25"` and row 2's edit to blank;
      - `"0"` in Dir gives `"'0' is not recognised as a direction; unchanged"`.
    - `test_shift_moves_each_selected_offset_by_the_amount`: rows 0 and 1, `shift_offset(0.1)`, give 0.35 and 0.85.
    - `test_moving_rows_to_another_grid_keeps_them_listed_until_ok`:
      - row 5 `move_to("B")` shows Grid `"B"` and Start `"9.00"`, and the row stays in the table;
      - after OK it is the last key of `session.keys_on_grid("B")`.
    - `test_up_and_down_set_the_survey_order`:
      - with rows 1 and 2 selected, `move_selected(-1)` gives order `[k1, k2, k0, k3, k4, k5]`;
      - `up_button` is disabled with row 0 selected;
      - after OK, `session.keys_on_grid("Grid5")` matches the table.
    - `test_the_status_counts_the_picks_that_will_move`: with a stub pick store whose `picks_for` returns two picks for `keys[0]`, built before the dialog:
      - flipping row 0 gives `"1 line changed · 2 picks will move with it"`;
      - a label edit on row 2 then gives `"2 lines changed · 2 picks will move with them"`.
    - `test_the_bulk_panel_is_greyed_until_rows_are_selected_and_counts_them`.
    - `test_ok_skips_a_line_changed_elsewhere_and_names_it`: flip row 2 in the table, then `session.edit_lines` its offset directly. After `accept()`, `outcome.skipped[0].label == "line 3"`, and the offset edit made elsewhere stands.
    - `test_a_concurrent_length_edit_is_not_undone_by_ok`:
      - flip row 0 in the table;
      - `session.replace_grid` with `size_y=14.0`, which moves rows 1, 3 and 5 by −1 m;
      - after `accept()`, row 0 starts at `14.0`, rows 1 and 3 at `15.0` and row 5 at `14.0`.
    - `test_the_dialog_survives_its_grid_being_removed`:
      - after `session.remove_grid("Grid5", with_lines=True)`, `flip()`, `snap_to_edge()` and `accept()` raise nothing;
      - the status reads `"grid 'Grid5' no longer exists; nothing was changed"` and `result()` is not Accepted.
    - `test_a_site_closed_under_the_dialog_changes_nothing`.
    - `test_a_line_with_no_distance_axis_is_listed_and_editable`:
      - add a `traces_per_metre=0.0` line to Grid5 before building a dialog;
      - its Length is `""`;
      - an Offset edit on it applies on OK.
    - `test_open_edit_lines_dialog_opens_one_table_per_grid_and_reports_on_ok` (`fake_iface`, `message_log`, `answer_modal`):
      - `plugin.open_edit_lines_dialog("A", [k0])` selects `k0`, and opening again with `[k1]` reuses the same dialog, now with `k1` selected;
      - a snap and `accept()` put `"Edit lines · A: changed"` in `message_log` and empty `plugin._edit_lines_dialogs`;
      - one left open is rejected by `plugin.unload()` (answer the save prompt with Discard, as the grid dialog test does).
- [ ] **Step 2: Run the file and see it fail.** Run `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_edit_lines_dialog.py -q -p no:cacheprovider -p no:xonsh`. Expected: FAIL with `ModuleNotFoundError`.
- [ ] **Step 3: Write the dialog and the plugin opener** to the interfaces above. Follow `ImportDialog`'s module docstring and table code for the modeless and `_updating` rules. Write a module docstring saying what the dialog edits, why Start is editable here when it isn't in Import, and that OK re-checks the site (spec call 14).
- [ ] **Step 4: Run the file, then the whole QGIS tier.** Expected: all pass.
- [ ] **Step 5: Lint, types, commit and push.**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/ui/edit_lines_dialog.py packages/nsgeo-qgis/nsgeo_qgis/plugin.py packages/nsgeo-qgis/tests/qgis/test_plugin_edit_lines_dialog.py
git commit -m "feat(ui): Edit lines — a grid's lines in one table, changed one at a time or together (#29)"
git push origin nsgeo-line-editing
```

---

