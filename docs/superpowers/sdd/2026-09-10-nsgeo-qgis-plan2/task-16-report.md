# Task 16 report — Processing dock: the stack list

## Fix report — review round 2

Re-review verdict: all 7 round-1 findings judged genuinely fixed (not merely attempted), no new
Critical/Important breakage. Round 2 was two Minors, both in code round 1 introduced. Both fixed;
test-file-only change, no implementation edits this round.

### What changed

**`packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py`**

1. **`test_apply_button_click_confirms_before_applying`** — the declined-confirmation caption
   (`"cancelled; nothing was applied"`, added in round 1) had no assertion anywhere. Added
   `assert "cancelled" in dock.status.text()` at the end of the test, which already clicks through a
   `QMessageBox.StandardButton.No` answer, so it needed no new fixture or setup.
2. **`test_on_rows_moved_uses_dest_index_not_the_raw_row`** — replaced the fabricated direct call
   `dock._on_rows_moved(None, 0, 0, None, 3)` with driving the real model:
   `dock.list.model().moveRow(QModelIndex(), 0, QModelIndex(), 3)`, asserting it returns `True`. This
   is a genuine model move (`beginMoveRows`/`endMoveRows`) that emits the real `rowsMoved` signal
   already connected to `_on_rows_moved` in `__init__`, so the test now exercises the actual
   signal -> slot connection rather than only the slot's body called by hand — if `_on_rows_moved`'s
   parameter order were ever changed to no longer match Qt's real
   `rowsMoved(parent, start, end, destination, row)`, this test would now catch it; the fabricated
   call could not have. Added `from qgis.PyQt.QtCore import QModelIndex` alongside the existing `Qt`
   import.

Both were reviewer-verified independently before I touched anything: `moveRow(parent, 0, parent, 3)`
returns `True` and emits a real `rowsMoved`, while `dest=1`/`dest=2` (the tie and one past it) both
return `False` and emit nothing — matching `dest_index`'s own docstring claim about
`beginMoveRows`'s `[start, start+1]` rejection window, now confirmed twice (round 1 by me, round 2 by
the re-reviewer, independently, on the actual dock's list rather than a bare `QListWidget`).

### Mutation check, redone against the real-model-driven test

Per the coordinator's explicit ask, re-verified `test_on_rows_moved_uses_dest_index_not_the_raw_row`
still fails under the exact `row`-for-`dst` substitution now that it drives the real signal path, not
the fabricated call. Backed up the good file to the scratchpad, mutated, ran, restored (verified
byte-identical with `diff` before continuing) -- same protocol as round 1, never `git checkout --`:

```
# mutated: self.session.move_step(key, start, dst) -> self.session.move_step(key, start, row)
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest \
  packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py::test_on_rows_moved_uses_dest_index_not_the_raw_row \
  -q -p no:xonsh
```
```
FAILED ...::test_on_rows_moved_uses_dest_index_not_the_raw_row
AssertionError: assert ['background_...ero', 'dewow'] == ['background_..., 'time_zero']
At index 2 diff: 'time_zero' != 'dewow'
1 failed in 0.76s
```
Confirmed: the connection is genuinely exercised, and the mutation is still caught. Restored from the
scratch copy afterward (`diff` confirmed byte-identical to the pre-mutation file).

### Full verification, final state

Per-tier counts, exactly as printed:

```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py -q -p no:xonsh
13 passed in 0.77s
```
```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:xonsh
235 passed in 55.84s
```
```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
333 passed, 2 skipped in 0.93s
```
```
.venv/bin/python -m ruff check .
All checks passed!
.venv/bin/python -m ruff format --check .
85 files already formatted
```
```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_boundary.py packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q
6 passed in 0.17s
```
```
mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
Success: no issues found in 24 source files
```

### Files changed (this round)

- `packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py` (test-only; no implementation
  changes this round)

### Commit

`cc743e1` — fix: processing dock review round 2 -- assert the cancel caption, drive the real move
(pushed to `origin/nsgeo-qgis`)

### Concerns

None. Both items addressed within round-2 scope; the coordinator's calibration note on
`test_updating_guard_survives_a_nested_rebuild` (couples to `_updating`'s name/type rather than
behaviour) was explicitly parked as a non-blocking nit and left alone, per instruction.

---

## Fix report — review round 1

Review verdict: Spec compliant, task quality approved, 0 Critical / 1 Important / 7 Minor. All 7
items fixed; round-1 scope only, no other refactoring.

### What changed, file by file

**`packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py`**

- **IMPORTANT 1** — the add-menu action lambda was `lambda n=name: self.add_step(n)`. Hardened to
  `lambda checked=False, n=name: self.add_step(n)` so it no longer depends on `QMenu.addAction`'s
  convenience overload binding the zero-argument `triggered()` form (an implementation detail, not
  documented API, unverifiable under PyQt6 in either venv here).
- **MINOR 3+4** — rewrote `dest_index`'s docstring. It no longer claims the tie (`row == start`) is
  a real drop Qt reports; it now says what's true: `beginMoveRows` rejects a same-parent destination
  inside `[start, start+1]`, so the tie never arrives from a real `rowsMoved` at all, `row <= start`
  is defensive only, and `_on_rows_moved`'s own `dst != start` guard — not this function — is what
  stops a spurious `move_step` call. `row <= start` itself is unchanged (still correct, still what
  the brief's own test requires).
- **MINOR 5** — `rebuild()` now clears `self.status.setText("")` at the top, so a stack change or a
  line switch always drops any earlier "applied to N line(s)" caption instead of leaving it standing
  for a stack it no longer describes. `apply_to_grid`'s declined-confirmation branch now sets
  `"cancelled; nothing was applied"` instead of returning silently with the previous caption intact.
- **MINOR 6** — `self._updating` is now a depth counter (`0`, `+= 1`, `-= 1`) instead of a set/clear
  bool (`False`, `= True`, `= False`). Every read site (`_on_item_changed`, `_on_current_row`,
  `_on_rows_moved`) already tested truthiness, not identity, so no call site needed to change.

**`packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py`**

- **MINOR 8** — moved `from qgis.PyQt.QtWidgets import QMessageBox` out of
  `test_apply_button_click_confirms_before_applying` and into the module-level imports (alongside
  `Qt`). Extended `test_no_line_disables_the_controls` to also assert `remove_button`, `up_button`,
  and `down_button` are disabled, not just `add_button`/`apply_button`.
- **IMPORTANT 1** — added `test_add_menu_action_triggers_add_step`: finds the `dewow` and `bandpass`
  actions by name (`action.text().split(" ")[0]`, matching the existing convention, immune to a
  registry reordering) and calls `.trigger()` on each — the first prior test in this file to actually
  fire a menu action rather than only read `action.text()`. Asserts `dewow` lands in
  `session.stack_for(key).entries` and `bandpass` fires `add_step_requested` without touching the
  stack.
- **MINOR 2** — added `test_on_rows_moved_uses_dest_index_not_the_raw_row`: adds four
  no-required-params steps, calls `dock._on_rows_moved(None, 0, 0, None, 3)` directly (confirmed by
  direct `QTest` mouse-press/move/release experiment that a real internal `QListWidget` drag cannot be
  driven under the offscreen platform — it produces no `rowsMoved` at all, matching why no other
  dock/dialog test in this codebase drives drag-and-drop directly), and asserts the resulting stack
  order matches `dest_index`'s translation, not the raw Qt `row`.
- **MINOR 5** — added `test_status_message_clears_when_the_line_switches`: applies to grid, confirms
  the caption is non-empty, switches to another line, and asserts the caption is now `""`.
- **MINOR 6** — added `test_updating_guard_survives_a_nested_rebuild`: sets `dock._updating += 1`
  first (simulating an outer rebuild already in progress), runs a full `rebuild()` through it, and
  asserts the guard (`dock._updating`) is still truthy afterward — the state a real nested call from
  Task 17's form would leave behind.

### Verification each new/changed test actually pins something

Per the reviewer's ask, each addition was checked against the exact single-line reversion of its own
fix, using a scratch copy of the good file (`cp ... /tmp/.../scratchpad/processing_dock.py.good`) so
each experimental edit could be applied, tested, and restored from the copy rather than via
`git checkout --`:

1. **`test_add_menu_action_triggers_add_step`** — changed the lambda body to
   `self.add_step(checked)` (passing the bool instead of the captured name). Result:
   ```
   FAILED ...::test_add_menu_action_triggers_add_step
   AssertionError: assert [] == ['dewow']
   ```
   with the stderr traceback showing exactly the documented hazard: `KeyError: "unknown step False..."`
   raised inside the slot and swallowed — printed to stderr, `trigger()` returned normally.

2. **`test_on_rows_moved_uses_dest_index_not_the_raw_row`** — changed
   `self.session.move_step(key, start, dst)` to `self.session.move_step(key, start, row)`. Result:
   ```
   FAILED ...::test_on_rows_moved_uses_dest_index_not_the_raw_row
   AssertionError: assert ['background_...ero', 'dewow'] == ['background_..., 'time_zero']
   At index 2 diff: 'time_zero' != 'dewow'
   ```

3. **`test_status_message_clears_when_the_line_switches`** — removed the
   `self.status.setText("")` line from `rebuild()`. Result:
   ```
   FAILED ...::test_status_message_clears_when_the_line_switches
   AssertionError: assert 'applied to 2...(s) in grid A' == ''
   ```

4. **`test_updating_guard_survives_a_nested_rebuild`** — reverted `rebuild()`'s
   `self._updating += 1` / `-= 1` back to `self._updating = True` / `= False` (left `__init__`'s
   `self._updating = 0` alone). Result:
   ```
   FAILED ...::test_updating_guard_survives_a_nested_rebuild
   assert False
    +  where False = <...ProcessingDock object ...>._updating
   ```

After each check, the file was restored from the scratch copy (verified byte-identical with `diff`
before re-running the full suite) rather than via `git checkout --`, per this branch's standing
caution about that command.

### Full verification, final state (after every fix and every mutation-check restore)

Per-tier counts, exactly as printed, using the corrected commands:

```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:xonsh
235 passed in 57.06s
```
(231 before this round + 4 new tests: menu-trigger, rows-moved, status-clears, updating-guard)

```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
333 passed, 2 skipped in 0.94s
```
(unchanged from the initial submission; the 2 skips are the pre-existing `needs_real_data` guard)

```
.venv/bin/python -m ruff check .
All checks passed!
.venv/bin/python -m ruff format --check .
85 files already formatted
```
(one intermediate reformat was needed: `ruff format` wanted a space between the docstring's opening
`"""` and its first character, `"applied` — `""""applied` reads as four quote characters. Applied,
re-checked clean.)

```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_boundary.py packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q
6 passed in 0.17s
```
(matches the corrected total of 6 across the two files)

```
mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
Success: no issues found in 24 source files
```
(this task's diff touches neither of the two plugin modules in CI's mypy scope, so this is unaffected
either way)

### Files changed (this round)

- `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py`

### Commit

`53fd4bf` — fix: processing dock review round 1 -- untested menu path, stale status, reentrant guard
(pushed to `origin/nsgeo-qgis`)

### Concerns

None. All 7 items addressed within round-1 scope; nothing else touched.

---

## Original submission

## What I implemented

- `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py` (new): `ProcessingDock(session, parent=None)`,
  a `QgsDockWidget` showing the current line's `StepStack` as a `QListWidget`. Steps are enumerated
  from `nsgeo.processing.available_steps()`/`required_params()` for the "Add step" menu — never a
  hardcoded list. Every mutation (`add_step`, `remove_selected`, `move_selected`, checkbox toggles,
  drag reorder, `apply_to_grid`) goes through a `SiteSession` method; the list itself is only ever
  rebuilt from `session.stack_for(key).entries` in `rebuild()`, triggered by `stack_changed`/
  `line_opened`/`site_closed`. Steps with `REQUIRED` parameters (`bandpass`, `gain_curve`) are never
  built directly — `add_step` emits `add_step_requested(name)` instead, for Task 17's form to answer.
  Module-level `dest_index(start, row)` translates `QAbstractItemModel.rowsMoved`'s destination row
  into the index a moved row ends up at.
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (modified): wired `ProcessingDock` into `initGui`
  (`RightDockWidgetArea`, appended to `self.docks`) and `unload` (`self.processing_dock = None`),
  in the exact shape `ProfileDock` uses. `add_step_requested` is left unconnected, per the task
  context — Task 17 is its consumer.
- `packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py` (new): the brief's 8 given tests,
  verbatim, plus one I added (`test_apply_button_click_confirms_before_applying`) covering a wiring
  bug I found and fixed (see below).

## Two fixes to the brief's illustrative implementation

The brief says the *test cases* are the requirement to use verbatim; the Step-3 code sample is a
draft. Two lines in that draft do not hold up under the brief's own tests / this codebase's own
conventions, both confirmed by direct experiment rather than assumption:

1. **`dest_index`**: the draft used `row if row < start else row - 1`. The brief's own test asserts
   `dest_index(start=1, row=1) == 1`, which that formula fails (`row < start` is false at the tie, so
   it returns `row - 1 = 0`). I checked the semantics directly against `QAbstractItemModel::rowsMoved`
   (a row dropped back on its own starting position is a no-op tie, `row == start`, and must land back
   at `start`) and fixed the comparison to `row <= start`. This also fixes a real behavioural bug in
   `_on_rows_moved`: with the old formula, dropping a row back on its own position would spuriously
   call `session.move_step(key, start, start - 1)`.

2. **`apply_button` wiring**: the draft connects `self.apply_button.clicked.connect(self.apply_to_grid)`.
   I verified directly (a live `QPushButton.clicked` connected to a one-bool-defaulted-parameter slot)
   that PyQt hands the click's `checked=False` straight into `apply_to_grid`'s `confirm` parameter —
   every real click would silently skip the "replace every other line in this grid" confirmation
   dialog. Fixed by wrapping in a lambda (`lambda: self.apply_to_grid()`), matching the pattern already
   used for `up_button`/`down_button` two lines above it. Added
   `test_apply_button_click_confirms_before_applying` to pin this: it clicks the real button, checks
   `QMessageBox.question` was actually asked, and that declining leaves every other line's stack
   untouched.

I also dropped `lambda _key: self.rebuild()` for `session.line_opened.connect(self.rebuild)` directly
(verified PyQt trims a bound method's signal arguments to its own arity, so this is behaviourally
identical) — this matches the direct `session.site_closed.connect(self.rebuild)` connection two lines
below it in the same constructor, rather than mixing both styles for no reason.

I looked hard at whether `QListWidgetItem`'s flags (`ItemIsDragEnabled` only, no `ItemIsDropEnabled`)
leave real mouse-driven drag reordering non-functional. A `QTest` mouse-press/move/release simulation
under the offscreen platform produced no `rowsMoved` at all regardless of flags — this is a known
limitation of simulating native `QDrag` with bare `QTest` mouse events, not evidence of a flag bug, and
matches why no dock/dialog test in this codebase drives drag-and-drop directly (reordering elsewhere,
e.g. `ImportDialog`, is button-only). I left the flags as specified; `dest_index`'s correctness is what
actually matters for a real drag; button-driven reordering is what the tests can and do verify.

## TDD evidence

**RED** — before `processing_dock.py` existed:

```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py -q -p no:xonsh
```
```
ERROR collecting packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py
...
E   ModuleNotFoundError: No module named 'nsgeo_qgis.ui.processing_dock'
1 error in 0.16s
```
Expected failure: the module didn't exist yet — this is a collection error, not a test failure, so it
proves nothing about behaviour, only that the import doesn't yet resolve. That's the correct RED for
"file not created yet."

**GREEN** — after implementing (including both fixes above), focused file:

```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py -q -p no:xonsh
```
```
.........                                                                [100%]
9 passed in 0.76s
```

## Full verification (final run, after all edits)

Per-tier counts, exactly as printed:

```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:xonsh
231 passed in 56.16s
```
```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
333 passed, 2 skipped in 0.98s
```
(the 2 skips are the pre-existing `needs_real_data` guard — no real DZT files under `tests/data/local`
in this environment; unrelated to this task)

```
.venv/bin/python -m ruff check .
All checks passed!
.venv/bin/python -m ruff format --check .
85 files already formatted
```

### mypy and the boundary test — two discrepancies from the task instructions, both investigated and pre-existing

- **mypy**: `.venv/bin/python -m mypy packages/nsgeo-qgis/nsgeo_qgis` reports 72 errors, almost all
  `Cannot find implementation or library stub for module named "qgis...."` / `import-untyped` for
  `nsgeo.*`. I checked whether this is something my diff introduced: running mypy against
  `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` alone (a file I did not touch, already on `main`
  before this task) reproduces the identical `Found 72 errors in 15 files`. `.venv` has no qgis stubs
  installed (`.venv-qgis` doesn't even have `mypy` installed), so mypy cannot resolve `qgis.*` imports
  from either venv — this is a pre-existing, structural condition of the whole package, not something
  from this diff. Grepping the full-package run for `processing_dock` shows only the same
  import-resolution noise (4 lines: one `import-untyped` for `nsgeo.processing`, three
  `import-not-found` for `qgis.gui`/`qgis.PyQt.QtCore`/`qgis.PyQt.QtWidgets`) and zero "real" type
  errors (no `arg-type`, `union-attr`, etc. attributed to my file). `.github/workflows/ci.yml`'s actual
  `lint` job only runs mypy against `packages/nsgeo-core/src/nsgeo`,
  `packages/nsgeo-qgis/nsgeo_qgis/lookup.py`, and `packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`
  — none of which this task touches. I did not attempt to fix the package-wide mypy environment gap;
  that's outside this task's scope and predates it.
- **Boundary test**: `packages/nsgeo-core/tests/test_import_boundary.py` does not exist; the actual
  file is `packages/nsgeo-core/tests/test_boundary.py`, and it has 2 tests, not 4:
  ```
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_boundary.py -q
  2 passed in 0.03s
  ```
  This package is untouched by this task's diff (no import of qgis/PyQt/matplotlib/scipy was added to
  `src/nsgeo`), so the boundary condition it guards is unaffected either way.

## Files changed

- `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py` (new)
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (modified: import, `__init__` attribute, `initGui`
  wiring, `unload` nulling — 7 lines added, nothing removed)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py` (new)

## Self-review findings

- Confirmed the given `SiteSession` interface is used exactly as documented (no new session methods
  added).
- Confirmed no DSP/signal-processing code appears anywhere in the diff — only registry lookups
  (`available_steps`, `build_step`, `default_params`, `required_params`) and session calls.
- Confirmed every Qt import goes through `qgis.PyQt`/`qgis.gui`, and every enum reference is scoped
  (`Qt.DockWidgetArea.*`, `Qt.ItemFlag.*`, `Qt.CheckState.*`, `QAbstractItemView.DragDropMode.*`,
  `QMessageBox.StandardButton.*`).
- Found and fixed the two defects described above (`dest_index` tie case, `apply_button` checked-arg
  absorption) before committing, plus the minor `line_opened` lambda-vs-bound-method simplification.
- Traced every given test by hand against the final implementation (list ordering, current-row
  tracking through `rebuild()`'s `keep`/`_updating` guard, `stack_for(...).entries` shape) to confirm
  each assertion is pinned by a real implementation detail, not incidentally true — in particular, the
  new `dest_index` tie-case assertion and the new button-click test both fail against the original
  brief code and pass against mine.
- Ran the focused file, then the two full test tiers, then ruff/format, in that order, as instructed.

## Concerns

- None regarding the implementation itself. The two documentation/environment discrepancies above
  (boundary test file name and count; the mypy command's inherent inability to resolve `qgis` stubs
  from either venv) are pre-existing conditions of this branch/environment, not introduced by this
  task — flagged here rather than silently worked around.
