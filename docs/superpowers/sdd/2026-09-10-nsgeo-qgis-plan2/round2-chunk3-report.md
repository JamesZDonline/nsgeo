# Round-2 chunk 3 report — C3, C4, I8

Worktree `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-qgis`, branch
`nsgeo-qgis`. Started clean at `bb65f31`. Three commits, nothing pushed, nothing merged or rebased.
`PYTHONDONTWRITEBYTECODE=1` was exported for every test run in this report.

Baseline measured at `bb65f31` before touching anything (not the brief's figures, which are stale):

```
$ QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
356 passed in 83.85s (0:01:23)
```

Final: **368 / 363 passed + 3 skipped / 6**, ruff clean, mypy clean. Full output at the end.

---

## C3 — the picks migration's verification step

**Commit `22ab7adf81dd5ba07f3f26c89cb574aa2fc4e52b`** — *test: pin the picks migration's own
row-count verification*

One test added to `packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py`
(`test_a_short_migration_refuses_the_swap_rather_than_losing_picks`, plus two small wrapper classes
it needs). No production change: the guard at `layers.py:523` is correct.

### The mutation survived before

`packages/nsgeo-qgis/nsgeo_qgis/layers.py:523`, `if written != len(old_rows):` →
`if False and written != len(old_rows):`

```
$ QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
356 passed in 82.80s (0:01:22)
```

### The test fails against the mutant

```
>       assert any("picks migration wrote 1 of 2 rows" in m for m in message_log), message_log
E       AssertionError: []
E       assert False
E        +  where False = any(<generator object ...>)

packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py:580: AssertionError
----------------------------- Captured stderr call -----------------------------
ERROR 1: In ExecuteSQL(): sqlite3_prepare_v2(UPDATE layer_styles SET f_table_name =
  'picks__before_rebuild' WHERE f_table_name = 'picks'): no such table: layer_styles
ERROR 1: In ExecuteSQL(): sqlite3_prepare_v2(UPDATE layer_styles SET f_table_name = 'picks'
  WHERE f_table_name = 'picks__rebuild'): no such table: layer_styles
1 failed, 29 deselected in 3.34s
```

The empty log is the whole finding: nothing was reported, and the stderr lines are the swap
proceeding — `picks` renamed to the backup, the short migrated table renamed into its place, one
authored pick gone.

### The mutation restored — green

```
$ QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest \
    packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py -q -p no:xonsh
30 passed in 53.87s
```

### Which way of making the count under-report, and why

The brief noted two ways and asked which is more honest. I made `addFeatures` **genuinely drop a
row and still report success**, rather than making `featureCount` lie. The count then under-reports
because the temporary table really is short — which is the failure the guard exists for and the one
that costs data. Faking the count would leave a complete migrated table on disk, so the swap the
guard prevents would have been harmless and the test would pin the check while proving nothing
about the consequence.

### One thing that does not work, recorded so nobody repeats it

Patching `QgsVectorDataProvider.addFeatures` at class level and calling the captured original does
**not** reach the OGR provider's override — it runs the base-class implementation, which returns
`False`. Measured directly:

```
direct:         (True,  [...])
unbound:        (False, [...])
unbound sliced: (False, [...])
```

The first attempt at this test did exactly that, and the rebuild then failed at the `if not ok`
branch *above* the gate:

```
E  AssertionError: ["could not prepare table 'picks': could not migrate picks into a temporary
   table: ; the original picks table is untouched", ...]
```

That version would have looked like it was killing the mutant while exercising a different guard
entirely. The committed test wraps the one temporary layer (the `FlakyRegistry` shape already used
in this file) instead.

### Why the assertion is on the log, not `pytest.raises`

`ensure_tables` deliberately contains a per-table failure so one table's setup cannot cancel the
other three, so the `RuntimeError` is logged rather than raised out of the signal. The test asserts
on the row count the message names (`picks migration wrote 1 of 2 rows`) and reads the original
table back off disk with a fresh `QgsVectorLayer`, not through `layers`, as the brief asked.

---

## C4 — "New site" and "Open site" do not protect unsaved work

**Commit `046f653193624dd11d59fbf9225ee97e432d60b2`** — *test: pin that New and Open protect unsaved
work*

Six tests in `test_plugin_survey_dock.py` (three per entry point, mirroring the unload trio) and one
in `test_plugin_session.py`. No production change — see "was there a real defect" below.

### The three mutations survived before

Each applied alone to `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`, full qgis tier each time
(baseline at that point was 357, C3 having landed):

| mutation | result |
|---|---|
| delete `if self.session.dirty and not self.save_with_prompt(ask_first=True): return` from `new_site` (:436) | `357 passed in 85.80s` |
| delete the same two lines from `open_site` (:455) | `357 passed in 85.68s` |
| delete `if allow_cancel and answer == QMessageBox.StandardButton.Cancel: return False` (:504) | `357 passed in 85.43s` |

### All three now die

```
########## MUTANT: new
E       AssertionError: unexpected modal: QFileDialog.getExistingDirectory(<PyQt5.QtWidgets.QMainWindow object at 0x7b0db4ff87a0>, 'Choose an empty folder for the site')
E       assert 0 == 1
E        +  where 0 = len([])
E       AssertionError: assert [] == ['A']
E         Right contains one more item: 'A'
FAILED ...::test_new_site_cancelled_leaves_the_dirty_site_exactly_as_it_was
FAILED ...::test_new_site_discarding_abandons_the_old_site_without_saving_it
FAILED ...::test_new_site_saves_the_old_site_first_when_the_user_chooses_save
3 failed, 21 passed in 6.38s

########## MUTANT: open
E       AssertionError: unexpected modal: QFileDialog.getOpenFileName(<PyQt5.QtWidgets.QMainWindow object at 0x720f11269760>, 'Open a survey file', '', 'nsgeo survey (survey.nsgeo.json);;All files (*)')
E       assert 0 == 1
E        +  where 0 = len([])
E       AssertionError: assert [] == ['A']
E         Right contains one more item: 'A'
FAILED ...::test_open_site_cancelled_leaves_the_dirty_site_exactly_as_it_was
FAILED ...::test_open_site_discarding_abandons_the_old_site_without_saving_it
FAILED ...::test_open_site_saves_the_old_site_first_when_the_user_chooses_save
3 failed, 21 passed in 6.63s

########## MUTANT: cancel
E       AssertionError: unexpected modal: QFileDialog.getExistingDirectory(...)
E       AssertionError: unexpected modal: QFileDialog.getOpenFileName(...)
FAILED ...::test_new_site_cancelled_leaves_the_dirty_site_exactly_as_it_was
FAILED ...::test_open_site_cancelled_leaves_the_dirty_site_exactly_as_it_was
2 failed, 22 passed in 6.29s
```

The `unexpected modal: QFileDialog...` lines are the brief's "free" assertion doing its job: the
default `_no_unhandled_modals` guard turns reaching the chooser into an AssertionError, and both
callers reach it *outside* their own `try/except`, so it comes straight back out of
`plugin.new_site()` / `plugin.open_site()` rather than being caught and reported as "could not
create the new site".

### Was there a real defect in the production code? No.

I checked `save_with_prompt` line by line against the Cancel path and found nothing to fix:

- Cancel returns `False`, and both callers treat `False` as "stop" — verified by the six tests
  passing against unmodified code.
- Cancel is also Qt's escape button for the `Save | Discard | Cancel` set, so dismissing the prompt
  with Esc or the window close button aborts rather than falling through to the save.
- Choosing Save and having the save fail returns `False` too (both the plain failure and the
  `allow_absolute` sub-prompt answered No), so New/Open abort rather than discarding.
- Discarding and then cancelling the *folder chooser* leaves the site open and still dirty, which is
  the safe outcome.

The `allow_cancel and ...` conjunct is redundant (with `allow_cancel=False` the button is not in the
set, so `answer` cannot be `Cancel`), but it is not wrong, and removing it would be a change the
brief did not ask for.

### The `session.py` guard — the brief is wrong here, and I implemented what is actually missing

The brief says `session.new_site`'s occupied-folder guard "has no test either … I grepped both test
trees … and found nothing". That is not true at this tip. `test_plugin_session.py:57-58`, the tail of
`test_new_site_writes_the_survey_file_and_names_the_gpkg_for_the_site`, is:

```python
    with pytest.raises(ProjectError, match="already"):
        s.new_site(tmp_path)
```

and deleting the guard fails it:

```
########## MUTANT: sessionguard   (delete `if json_path.exists(): raise ProjectError(...)`)
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_session.py::test_new_site_writes_the_survey_file_and_names_the_gpkg_for_the_site
1 failed, 356 passed in 85.02s (0:01:25)
```

So I did not add a duplicate. What genuinely is not pinned is the half the brief's own wording calls
out — "**rather than overwrite it**". The existing test only proves it raises, and it raises on a
folder whose survey file is empty anyway. `test_new_site_refuses_an_occupied_folder_without_touching_what_is_there`
pins the file on disk instead: a site with a real grid in it, byte-compared before and after, plus
"nothing was installed" and "the site that was there still opens, with its grid".

Mutation used to show it earns its place — a guard that raises only *after* `save_site` has already
written (the shape a reordering or an early write would really take):

```python
        json_path = folder / SURVEY_FILE
        occupied = json_path.exists()
        site = Site()
        save_site(site, json_path)
        if occupied:
            raise ProjectError(...)
```

```
>       assert (tmp_path / SURVEY_FILE).read_bytes() == before
E       assert b'{\n  "schem...nes": []\n}\n' == b'{\n  "schem...nes": []\n}\n'
E         At index 37 diff: b']' != b'\n'
FAILED ...::test_new_site_refuses_an_occupied_folder_without_touching_what_is_there
1 failed, 29 passed in 0.86s
```

The pre-existing test survives that mutant (29 passed); the new one kills it.

---

## I8 — the survey dock context menu

**Commit `b2ed89c36ed4872f17c057188e3b82c1238231d7`** — *test: open the survey tree's context menu to
the suite, gate and all*

Four tests in `test_plugin_survey_dock.py`, plus one small production change in
`packages/nsgeo-qgis/nsgeo_qgis/ui/survey_dock.py`.

The conftest half of I8 (forbidding `QMenu.exec` / `QMenu.exec_`) had already landed with C6 and was
left alone.

### The three mutations survived before

Full qgis tier each time, baseline 364 at that point:

| mutation (`ui/survey_dock.py`) | result |
|---|---|
| `menu.exec(self.tree.viewport().mapToGlobal(pos))` → `pass` | `364 passed in 88.88s` |
| delete `if answer != QMessageBox.StandardButton.Yes: return` from `remove_line_action` | `364 passed in 90.01s` |
| delete the same from `remove_grid_action` | `364 passed in 88.64s` |

### All three now die

```
########## MUTANT: exec
E       assert 0 == 4
E        +  where 0 = len([])
FAILED ...::test_the_context_menu_offers_the_right_actions_for_each_kind_of_item
1 failed, 27 passed in 6.41s

########## MUTANT: line
E       AssertionError: assert None == 'raw/FILE__001.DZT'
E        +  where None = <nsgeo_qgis.session.SiteSession object ...>.current_key
E       AssertionError: assert 'raw/FILE__001.DZT' in ['raw/FILE__002.DZT', 'raw/FILE__003.DZT']
E        +    where keys = <nsgeo_qgis.session.SiteSession object ...>.keys
FAILED ...::test_every_context_menu_action_is_wired_to_the_slot_it_names
FAILED ...::test_removing_a_line_from_the_menu_takes_no_for_an_answer
2 failed, 26 passed in 6.68s

########## MUTANT: grid
E       AssertionError: assert ['A'] == ['A', 'B']
E         Right contains one more item: 'B'
FAILED ...::test_removing_a_grid_from_the_menu_takes_no_for_an_answer
1 failed, 27 passed, 1 error in 6.45s
```

The extra `1 error` under the grid mutant is `_no_swallowed_slot_exceptions` catching what the
mutant lets through: with the gate gone, triggering "Remove grid" on grid A (which still holds three
lines) reaches `session.remove_grid`, which raises `ValueError`, which `remove_grid_action` reports
through `QMessageBox.warning` — forbidden in this tier — and that AssertionError escapes the lambda
into Qt. Exactly the hook C6 added, doing exactly its job.

### The production change, and why it is needed

`self.context_menu = QMenu(self)` is built once in `__init__` and `menu.clear()`-ed per right-click,
instead of a fresh local `QMenu(self)` — the shape `ProcessingDock.presets_menu` already uses. Two
reasons, both in the code comment:

1. It is what makes any of this testable. `QMenu.exec` runs a nested event loop and is forbidden in
   this tier (offscreen it blocks forever rather than failing), so without a handle on the built
   menu there is no way to read the action set or fire an action.
2. It ends a leak. The old local menu was parented to the dock and nothing ever deleted it, so one
   QMenu accumulated per right-click for the dock's whole life. `QMenu.clear()` deletes the actions
   it owns and there are no submenus here, so the reuse leaves nothing behind either.

### Designing around the swallowing trap the controller warned about

`_on_context_menu` wraps its whole body in `except Exception -> _log(...)`, so a test that merely
calls it and expects a raise passes for the wrong reason. Three things in the tests address that:

- They go through the real `customContextMenuRequested` signal rather than calling the slot, so the
  connection is pinned too.
- They install `answer_modal(QMenu, "exec", None)` and then **assert `QMenu.exec` was actually
  reached**, with the viewport-mapped global position, once per right-click. That is what kills the
  `pass` mutant: it leaves the menu built and correct but never shown.
- Every one of them asserts `message_log == []`, so anything the blanket `except` swallowed —
  including this tier's own forbidden-modal AssertionError — fails the test instead of disappearing
  into the log.

The two confirmation tests use `answer_modal(QMessageBox, "question", StandardButton.No)`, drive the
real menu action rather than calling `remove_*_action` directly, and assert nothing was removed —
for the line, that its processing stack survived too, since `session.remove_line` drops the stack
with the line. Each then re-answers **Yes** and asserts the removal does happen, so "nothing was
removed" is about the answer rather than about the action never doing anything. The grid test adds
an empty grid B for this, because `remove_grid` refuses a grid that still holds lines for an
unrelated reason, which would have made "nothing was removed" true whatever the answer was.

---

## Final verification

All from the worktree root, `PYTHONDONTWRITEBYTECODE=1` exported, run after the third commit with a
clean tree:

```
$ QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
368 passed in 88.13s (0:01:28)

$ .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests -q -p no:xonsh
363 passed, 3 skipped in 1.54s

$ .venv/bin/python -m pytest packages/nsgeo-core/tests/test_boundary.py \
    packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q -p no:xonsh
6 passed in 0.20s

$ .venv/bin/ruff check . && .venv/bin/ruff format --check .
All checks passed!
92 files already formatted

$ .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
    packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
    packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
Success: no issues found in 24 source files
```

qgis tier 356 → **368** (+1 C3, +7 C4, +4 I8). The pure+core and boundary tiers are unchanged at
363 passed / 3 skipped and 6 passed, as expected — every test added here is in the qgis tier.

---

## Deviations from the brief

1. **The brief's baseline figures were stale** (336 / 5cc5a12). The controller's corrected numbers
   were used: 356 / 363+3 / 6 at `bb65f31`.
2. **C4's "session.py:123 has no test" is wrong at this tip** — see the C4 section above. The
   existing assertion kills the deletion mutant. I added the test for the half that genuinely is not
   pinned (the file on disk is untouched) rather than a duplicate, and proved it with a mutation the
   existing test survives.
3. **C3's suggested `QgsVectorDataProvider.addFeatures` monkeypatch does not work** — it does not
   reach the OGR override. Recorded above with the measurement; the committed test wraps the layer.
4. **I8 needed a production change after all.** The brief frames C3/C4/I8 as "mostly test items", and
   for I8 says to "expose the built menu the way `ProcessingDock` exposes `presets_menu`" — which is
   a production change, so this is a deviation only from the framing, not from the instruction.

## Out-of-scope observations (named, not fixed)

- **A failed picks rebuild leaves the `picks__rebuild` table behind on disk.** The swap drops
  `_PICKS_BACKUP` but nothing drops `_PICKS_REBUILD` when the migration aborts before the renames.
  It is currently harmless — `_create_table` uses `CreateOrOverwriteLayer`, so the next rebuild
  overwrites it — but it is the same shape as the leftover-backup problem fix round 3 had to solve,
  and it is one `actionOnExistingFile` change away from wedging every future rebuild. Not touched:
  fixing it is a production change C3 does not call for.
- **`save_with_prompt`'s `allow_cancel` conjunct is redundant** (`allow_cancel and answer ==
  Cancel`): with `allow_cancel=False` the Cancel button is not in the set, so `answer` cannot be
  `Cancel`. Harmless and self-documenting; left alone.
- **`unload()`'s prompt has no escape button.** With `Save | Discard` and no Cancel, Qt's escape-
  button auto-detection finds nothing (Save is AcceptRole, Discard is DestructiveRole), so Esc and
  the window close button do nothing and the prompt can only be answered by choosing. That is
  arguably correct for a prompt that cannot be cancelled, and `unload` is not in this chunk's scope,
  but it is worth someone deciding deliberately.
- **The `drive_dialog` fixture's docstring claims it covers `QMenu.exec`**
  (`tests/qgis/conftest.py`, and `_no_unhandled_modals` says so too), but it cannot: it returns
  `self.result()`, which only `QDialog` has. `QMenu` would raise `AttributeError`. The I8 tests use
  `answer_modal(QMenu, "exec", None)` instead, which matches how `_no_unhandled_modals` forbids it
  (a `staticmethod`). Only the two docstrings are inaccurate; no code is wrong. Not touched —
  conftest edits beyond I8's own are outside this chunk.
