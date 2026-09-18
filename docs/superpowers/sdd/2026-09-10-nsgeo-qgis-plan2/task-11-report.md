# Task 11: Import dialog -- report

## What was implemented

- `packages/nsgeo-qgis/nsgeo_qgis/ui/import_dialog.py` (new): `ImportDialog(session, grid_id=None, parent=None)`.
  Widgets: `grid_combo`, `axis_combo`, `spacing`, `first_offset`, `start_along`, `direction_alternate`/`direction_forward`/`direction_reverse`,
  `label_stem`/`label_number`, `add_button`, `remove_button`, `up_button`/`down_button`, `table` (10 columns,
  `COL_INCLUDE..COL_NOTE`), `status`, `import_button`. Public methods: `add_files(paths)`, `remove_selected()`,
  `move_selected(delta)`, `set_include(row, flag)`, `set_offset(row, value)`, `options() -> ImportOptions`,
  `rows: list[ImportRow]`, `imported_keys: list[str]` (set on `accept()`).
- `packages/nsgeo-qgis/nsgeo_qgis/lookup.py`: added `ImportRow.label_edited: bool = False`; `recompute_offsets`
  now skips rewriting `row.label` when `label_edited` is set (the brief's called-out wrinkle).
- `packages/nsgeo-qgis/tests/pure/test_pure_lookup.py`: `test_hand_edited_labels_survive_recompute`, verbatim
  from the brief.
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`: `open_import_dialog` implemented (modeless, not the brief's
  `exec()` -- see Deviations); `_import_dialog` tracking slot added to `__init__`/`unload()`; module docstring's
  stale "no reason to expect Task 11's import dialog will [need modeless]" paragraph rewritten to match what was
  actually built, for the benefit of Tasks 15/16/18/19 which touch this file next.
- `packages/nsgeo-qgis/tests/qgis/conftest.py`: added `(QFileDialog, "getOpenFileNames")` to the modal guard
  (the new modal this dialog introduces via "Add files...").
- `packages/nsgeo-qgis/tests/qgis/test_plugin_import_dialog.py` (new): 22 tests -- the brief's 6 Step-1 tests
  verbatim, plus 16 more (see TDD Evidence and the audits below).

## Test results

- `.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q`
  -> **314 passed, 2 skipped** (was 313/2; +1 for `test_hand_edited_labels_survive_recompute`).
- `.venv/bin/ruff check .` -> **All checks passed.**
- `.venv/bin/ruff format --check .` -> **72 files already formatted.**
- `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py`
  -> **Success: no issues found in 23 source files.**
- `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh`
  -> **158 passed** (136 pre-existing in this worktree + 22 new in `test_plugin_import_dialog.py`; the task's
  stated baseline of 135 was off by one against this worktree's actual state -- verified directly by running the
  suite with the new file excluded).
- Ran the qgis tier three times across the session (after `import_dialog.py`, after adding two more audit-driven
  tests, and as the final gate) and the new file alone twice -- stable, no flakiness, no test-order sensitivity.

## TDD Evidence

**RED 1 (lookup.py wrinkle):** with `lookup.py` stashed back to its pre-Task-11 state (via a tagged, non-bare
`git stash push -u -m ... -- .../lookup.py` + `stash apply <sha>` + `stash drop`, per the worktree's stash-safety
rule), `test_hand_edited_labels_survive_recompute` failed:
```
AssertionError: assert 'FILE__002' == 'line 6a'
```
**GREEN:** re-applying the `label_edited` field + `recompute_offsets` guard, `pytest packages/nsgeo-qgis/tests/pure/test_pure_lookup.py -q` -> 20 passed.

**RED 2 (the dialog itself):** with `import_dialog.py` stashed away (same tagged-stash procedure, applied to the
untracked file), the qgis-tier test file failed exactly as the brief predicts:
```
ModuleNotFoundError: No module named 'nsgeo_qgis.ui.import_dialog'
```
**GREEN:** restoring the file, the full qgis tier passes (158/158), including `test_real_files_import_into_the_grid`
run in isolation.

Both stash operations followed the environment's safety rule for this shared-stash worktree: tagged message,
SHA captured immediately from `git stash list --format='%H %gs'`, restored with `stash apply <sha>` (never a bare
`pop`), dropped only after confirming the restore.

## Real-file validation

Ten real single-channel SIR-4000 `.DZT` files are symlinked into `packages/nsgeo-core/tests/data/local/` in this
worktree (verified present: `FILE__001.DZT` .. `FILE__010.DZT` + nine `.DZX` sidecars, `FILE__010` without one, as
stated). `test_real_files_import_into_the_grid` runs against them directly (not a stand-in): imports all 10 into
an 11 m grid (default axis "y", so `grid_size_along = size_y = 11.0`), asserts `FILE__008`'s row (666 traces, the
one that overruns) carries "exceeds" in its note, asserts row 0's Include checkbox is checked, then calls
`accept()` and confirms all 10 lines landed in the session. Ran both as part of the full suite and in isolation
(`-k real_files`) -- passes both ways, and is not skipped (`needs_real_data` only skips when the symlinks are
absent, which they are not here).

## Both audits

### Failure-path pass (every slot, every new line)

- **`_grid()`**: the one general-purpose fix that makes every caller safe by construction. `session.grid(gid)`
  raises `KeyError` if the grid was removed from the *same* still-open site while this modeless dialog stayed
  open (e.g. the survey dock's "Remove grid", which has no guard against an import in flight against the grid it
  is removing -- verified this is real and reachable, not hypothetical: `remove_grid_action` only refuses when
  lines already reference the grid, and an import not yet accepted never does). `_grid()` catches it and returns
  `None`, which every caller (`_grid_changed`, `options()`, `add_files` via `options()`, `_replan`) already treats
  as "no grid chosen" -- so this one fix, not a guard at each call site, is what keeps every slot in the dialog
  safe against the grid vanishing mid-session.

  **Correction (fix round 1, Finding 1): the claim above was false as originally shipped.** `_grid()` caught
  `KeyError` only. `SiteSession.grid()` also raises `ProjectError` (via `_require_site()`) when the *site itself*
  closes under the dialog, not just when the grid is removed from a still-open one -- and that exception was not
  caught at all. The reviewer probed it directly with the site closed under an open dialog holding rows:
  `set_include()` and every spin-box/radio-triggered replan raised `ProjectError` uncaught (silently, through the
  signal/slot hazard), `remove_selected()` raised after already deleting from `self.rows` but before
  `_refresh_table()` ran, desyncing `self.rows` from the table, and `add_files()` reported the wrong diagnosis
  ("could not read a file: no site is open") because the exception propagated up through its own broad
  `except Exception`. Fixed in this round: `except (KeyError, ProjectError)`. See "Fix round 1" below for the
  demonstrated-failing mutation and the new regression test
  (`test_dialog_methods_stay_safe_when_the_site_closes_under_it`).
- **`add_files` / `_choose_files`**: `plan_import` is wrapped in a broad `except Exception`, reported through
  `status`. `_choose_files` is a `QPushButton.clicked` slot; an uncaught exception there would print to stderr and
  leave the dialog looking like nothing happened (the standing signal/slot hazard). Confirmed empirically that
  testing the guard must call `d._choose_files()` directly, not `d.add_button.click()` -- `.click()` emits
  `clicked` synchronously, and an `AssertionError` raised inside a signal-connected slot does not propagate out of
  `.click()` either (same hazard, one level up); `pytest.raises` around `.click()` would never see it. Mirrors
  `test_fit_corners_reports_bad_numeric_entry_without_crashing`'s choice to call `fit_corners()` directly rather
  than `.click()` the button, for the identical reason -- I added
  `test_add_files_button_is_guarded_by_default` to prove this rather than assume it by analogy.
- **`_on_item_changed`**: COL_OFFSET's `float()` parse is guarded (`ValueError` -> status message + revert via
  `_refresh_table()`, tested by `test_bad_offset_entry_is_reported_and_reverted_not_crashed`). COL_LABEL sets
  `label_edited = True` (the brief's snippet set the label but never this flag, which would have silently
  defeated the whole fix on the very next unrelated edit -- see Deviations). COL_INCLUDE delegates to
  `set_include`.
- **`accept()`** (the one method that both writes to the session and is reachable as a signal slot via
  `buttons.accepted`): ordered guards, each reported through `status`, none raising:
  1. `session.is_open` -- refuses if the site closed under the dialog.
  2. `session.json_path != self._opened_against` -- refuses if a *different* site opened under the dialog
     (captured at `__init__` time, same mechanism as `GridDialog`/`open_grid_dialog`'s `opened_against`).
  3. target grid vanished (via `_grid()` returning `None` for a still-set `grid_combo.currentData()`) -- a
     message distinct from "never chose a grid".
  4. `recompute_offsets(self.rows, opts)` re-run immediately before writing, against freshly-read `options()` --
     closes a real staleness gap I found while auditing: a `GridDialog` open at the same time, editing the same
     grid's size, changes `grid_size_along` since the table was last refreshed, and without this re-run the
     *stale* `start_along`/note (not the live grid geometry) is what would have been written -- exactly the
     mis-mirroring hazard Task 7's own contract review is about.
  5. `rows_to_lines(...)` (which re-reads each file's header via `Line.open`) wrapped in a broad
     `except Exception` -- **a real gap in the brief's own reference `accept()`**, which caught only
     `(ValueError, OSError)` around this call. `DztError` (raised by `read_header` for a file that became
     malformed/truncated between planning and clicking Import) is a plain `Exception`, not an `OSError`
     subclass -- so the brief's code would have let a `DztError` here escape uncaught, out of a signal-connected
     slot, silently. See Deviations.
  6. empty `lines` (no included/placeable rows) -- refuses with a message rather than calling
     `session.add_lines([])`, which would have set `dirty=True` and emitted `lines_changed` for a no-op import.
  7. `add_lines` raises `ValueError` for a duplicate key -- caught, reported (`test_duplicate_import_is_reported_not_raised`).
- **`plugin.open_import_dialog`'s `finished`/`clear_if_current` closures**: copied `open_grid_dialog`'s pattern
  exactly, including the `is` (not `==`) identity check in `clear_if_current` (a dialog destroyed some other way
  must not clear a *newer* dialog's tracker) and `deleteLater()` inside `finished`'s `finally`. Proved this
  actually works for `ImportDialog`, not just by analogy to `GridDialog`, with
  `test_open_import_dialog_recovers_from_a_dialog_destroyed_outside_finished` (setParent(None) + deleteLater(),
  bypassing `finished()` entirely).
- **`unload()`**: `self._import_dialog.reject()`, not `.close()` (a hidden dialog's `closeEvent` never calls
  `reject()`, so `.close()` would emit `finished` zero times) -- though unlike `GridDialog`, nothing in
  `ImportDialog`'s own flow ever hides itself, so "hidden mid-something" is not a state this dialog reaches on its
  own; `reject()` was still the right call for consistency and because a future task could add a flow that hides
  it.

### Second pass: this dialog's own states, and whether each fix holds in them

Enumerated the states this dialog's own features (not just external races) can put it into, beyond the six
external races above:
- Empty dialog (no files, or a grid with zero files ever added) -- `accept()`'s "nothing to import" guard.
- Every row excluded by hand -- same guard.
- A row whose header can't be read at all, or whose acquisition rate is 0 (time-triggered) -- `recompute_offsets`
  already forces `include=False`; the checkbox item's flags are stripped of `ItemIsUserCheckable` so a user
  cannot even attempt to check it, and `set_include(row, True)` on such a row is self-correcting (the very
  `_replan()` it triggers forces `include` back to `False`) -- verified this by reasoning through
  `recompute_offsets`, not by adding a redundant test for a self-correcting no-op.
- Reorder/remove interacting with hand-edited offsets and labels -- covered by the brief's own
  `test_remove_and_reorder` plus my `test_hand_edited_label_survives_a_later_replan`.
- The same file added twice via two separate "Add files..." picks -- `add_files`'s dedup is by resolved path
  against the table's current rows; added `test_add_files_ignores_a_file_already_in_the_table` since this was
  previously unexercised.
- Two independent dialogs open at once (`GridDialog` editing the very grid `ImportDialog` targets) -- this is
  exactly the staleness case guard 4 above closes; not a hypothetical, since both dialogs are modeless and
  independently tracked.
- Dialog closed via the window's own X button rather than either button -- routes through `QDialog::closeEvent`
  -> `reject()` when visible, same as Cancel; `finished`'s handler already treats anything but `Accepted` as a
  no-op beyond cleanup, so this needed no special case.

## Decision: the direction-flip question

**Superseded in fix round 1 -- see that section below for the current state (`Dir` is now editable, `Start (m)`
stays read-only).** Original round-1 reasoning, kept for the record:

`Dir` and `Start (m)` were shown but not editable (`EDITABLE = {COL_LABEL, COL_OFFSET}`; the brief's reference had
them editable). Reasoning at the time: `ImportRow` had `offset_edited` and `label_edited`, but no
`direction_edited` -- read as Task 7's own contract rather than an oversight to patch around in a UI-only task.
`recompute_offsets` unconditionally re-derived `direction` from `direction_mode` and the row's slot position on
every replan, and every edit this dialog makes triggers one, so a hand-typed `Dir` would be silently discarded by
the very next replan. The reviewer's fix round 1 response: this reasoning about the *symptom* (an edit at risk of
being discarded is worse than no edit) was judged correct, but the conclusion (no fix exists) was wrong -- the
working fix is exactly the same shape as `offset_edited`/`label_edited`, and the reviewer also showed the
read-only workaround (exclude, then re-import the one line alone) actually mis-directs every later line in the
batch, which my original report did not check. See "Fix round 1, Finding 2" below for what was built instead.

## What was added to the modal guard

`(QFileDialog, "getOpenFileNames")` (plural -- multi-file selection, the "Add files..." button), added to
`tests/qgis/conftest.py`'s `_no_unhandled_modals` forbidden list and its docstring. `getOpenFileName` (singular)
was already covered from an earlier task; `getOpenFileNames` was not. Verified the guard actually fires
(`test_add_files_button_is_guarded_by_default`, calling `_choose_files()` directly -- see the failure-path audit
above for why not `.click()`) and that `answer_modal` correctly drives it
(`test_add_files_button_adds_the_chosen_files`).

## Files changed

- `packages/nsgeo-qgis/nsgeo_qgis/ui/import_dialog.py` (new)
- `packages/nsgeo-qgis/nsgeo_qgis/lookup.py` (modified: `label_edited`)
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (modified: `open_import_dialog`, `_import_dialog` tracking,
  `unload()`, module docstring)
- `packages/nsgeo-qgis/tests/pure/test_pure_lookup.py` (modified: `test_hand_edited_labels_survive_recompute`)
- `packages/nsgeo-qgis/tests/qgis/conftest.py` (modified: modal guard)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_import_dialog.py` (new)

## Self-review findings

- Confirmed no signal-processing imports and no direct `PyQt5`/`PyQt6` imports in the new file (Qt only via
  `qgis.PyQt`); `test_plugin_boundary.py` passes.
- `EDITABLE`'s narrowing to `{COL_LABEL, COL_OFFSET}` removed the brief's now-dead `_on_item_changed` branches for
  `COL_DIR`/`COL_START` entirely, rather than leaving unreachable code behind.
- `_on_item_changed`'s COL_INCLUDE/COL_OFFSET branches delegate to `set_include`/`set_offset` (each already calls
  `_replan()`) instead of duplicating that logic inline and then replanning a second time, which the brief's
  reference code would have done for every edit.
- `add_files`'s dedup was widened to update its `known` set as it iterates, so two copies of the same path
  arriving in a single `add_files([...])` call are also caught, not only a second, separate call.
- Ran `ruff format`/`ruff check --fix` and re-read the result; the only auto-changes were import ordering
  (`plugin_testing` sorts as third-party here, alongside `nsgeo`/`qgis`/`pytest`, matching
  `test_pure_lookup.py`'s existing layout) and line wrapping.
- Every new/changed line was covered by the failure-path pass above; nothing was left as a silent `except: pass`
  beyond the one pre-existing, documented "last resort" pattern this codebase already uses for `message()` itself
  (untouched by this task).

## Concerns

- None blocking. The only design judgment call with real weight is the direction-flip decision above (COL_DIR/
  COL_START read-only); I'm confident in the reasoning but flagging it explicitly since it's a user-facing
  capability the brief's reference code implied would exist and I removed.

## Deviations from the brief, with reasoning

1. **`plugin.py`'s `open_import_dialog` uses the modeless `show()`/`finished` pattern, not the brief's
   `dialog.exec()`.** The orchestrating task's "Carry-forward from Task 10" instructions state this is
   non-optional ("never `exec()`... Read `plugin.py`'s `open_grid_dialog` and copy its shape"), which overrides
   the brief's snippet and also `plugin.py`'s own pre-existing module-docstring comment speculating Task 11
   wouldn't need it (which I rewrote to match what was actually built, since Tasks 15/16/18/19 read this file
   next). Consequence: the toolbar/dock stay clickable while Import is open, which makes the site-closed/
   different-site/grid-removed races in the audit above real and reachable rather than something an
   application-modal `exec()` would have accidentally prevented -- `accept()` guards all three explicitly instead
   of relying on modality to make them unreachable.
2. **`COL_DIR`/`COL_START` are not user-editable** (brief had them in `EDITABLE`). See the "Decision" section
   above -- `recompute_offsets` would silently discard a per-row direction edit on the very next replan (every
   edit in this dialog triggers one), and Task 7's `ImportRow` deliberately has no `direction_edited` to protect
   it, unlike `offset_edited`/`label_edited`.
3. **`_on_item_changed`'s COL_LABEL branch sets `row.label_edited = True`.** The brief's own snippet for the fix
   it asked for set `row.label` but never the flag meant to protect it -- which would have made the fix a no-op
   the moment any other cell was edited (every edit calls `recompute_offsets` over every row). Fixed rather than
   copied verbatim, and covered by both the pure test the brief specified
   (`test_hand_edited_labels_survive_recompute`, exercising the `ImportRow` field directly) and a dialog-level one
   through the table (`test_hand_edited_label_survives_a_later_replan`).
4. **`accept()`'s exception handling around `rows_to_lines(...)` is `except Exception`, not the brief's
   `except (ValueError, OSError)`.** `DztError` (a plain `Exception`, not an `OSError` subclass) is what
   `read_header` raises for a malformed/truncated file, and `Line.open` (which `rows_to_lines` calls per row) can
   hit this for a file that changed on disk between planning and clicking Import -- a real TOCTOU gap the brief's
   narrower catch would have let escape uncaught out of a signal-connected slot.
5. **`accept()` re-runs `recompute_offsets` against fresh `options()` immediately before building lines**, and
   also refuses when the target grid has been removed or the site has changed identity. None of these appear in
   the brief's reference `accept()` at all; found during the failure-path audit (see above) as real races made
   reachable specifically *because* of deviation 1 (modeless).

---

# Fix round 1

Reviewer verdict on the original submission: **Approved**, with five findings to fix before the branch moves on.
All five addressed below; nothing deferred except the two items the reviewer explicitly placed out of scope
(`label_edited` being one-way, and `test_import_dialog_exec_is_guarded_by_default` testing the conftest fixture
rather than the dialog).

## Finding 1 (Important) -- `_grid()` didn't catch `ProjectError`

**Fixed.** `_grid()`'s except clause is now `except (KeyError, ProjectError):`, with `ProjectError` imported from
`nsgeo.project` (already an established import elsewhere in this package -- `plugin.py`, `session.py` -- and
outside the processing boundary guard's scope, so nothing there changes). The module docstring's paragraph about
this was rewritten to state what `_grid()` actually now catches and why (it previously overclaimed
completeness -- see the correction in "Both audits" above).

**Demonstrated failing:** reverted `except (KeyError, ProjectError):` to `except KeyError:` and reran
`test_dialog_methods_stay_safe_when_the_site_closes_under_it` (new this round). It failed with `ProjectError: no
site is open` escaping `remove_selected()` -> `_replan()` -> `options()` -> `_grid()` -> `session.grid()` ->
`_require_site()`, i.e. exactly the reviewer's own probe reproduced as an uncaught exception, not merely a wrong
assertion. Restored the fix; full suite green again (verified: 26/26 in this test file).

New test: `test_dialog_methods_stay_safe_when_the_site_closes_under_it`
(`packages/nsgeo-qgis/tests/qgis/test_plugin_import_dialog.py`) -- closes the site under an open dialog holding
three rows, then drives `remove_selected()`, `set_include()`, `spacing.setValue()` (a signal-connected replan),
and `add_files()`, asserting none raise and `remove_selected()` does not desync `self.rows` from `self.table`.

## Finding 2 (Important) -- `direction_edited` added, `Dir` is editable again

**Fixed**, in `lookup.py` as required, not as a UI-only patch:
- `ImportRow.direction_edited: bool = False` (mirrors `offset_edited`/`label_edited`).
- `recompute_offsets` wraps its `direction_mode` cascade in `if not row.direction_edited:` -- one guard, same
  shape as the existing `offset_edited`/`label_edited` guards immediately above and below it.
- `EDITABLE` gained `COL_DIR` back; `_on_item_changed` gained a `COL_DIR` branch parsing "+1"/"-1"/"−1" (accepting
  either hyphen or the true minus sign `_refresh_table` writes) and delegating to a new `set_direction(row, value)`
  method (mirrors `set_offset`), which sets `direction_edited = True` and replans.

**Composes with the `start_along` contract for free, as the reviewer predicted:** the mirroring block in
`recompute_offsets` (`if row.direction == -1: row.start_along = options.start_along + grid_size_along ... else:
row.start_along = options.start_along`) keys off `row.direction`, which is now whatever `direction_edited` left it
at -- not off `options.direction_mode`. No change to that block was needed.

**Shown surviving two replans, band inside the grid** (pure test
`test_hand_edited_direction_survives_recompute_and_start_along_follows_it` in `test_pure_lookup.py`, using the
module's existing `OPTS`/`three` fixtures): with `direction_mode="alternate"` (the default), `rows[1]` starts at
`direction == -1` (alternate's default for slot 1). Flipped to `direction = 1`, `direction_edited = True`, then
`recompute_offsets` is called *twice* in a row (simulating two further, unrelated replans). Asserts hold after
both calls: `rows[1].direction == 1`, `rows[1].start_along == 0.0` (forward: starts at `options.start_along`, not
mirrored to the far edge), and `"reversed direction" not in rows[1].note` (no stray warning from the mirroring
branch's `else` clause, which only fires when `grid_size_along` is `None` -- not this case). Demonstrated RED
first: reverted the `if not row.direction_edited:` guard, reran the test, got
`AssertionError: assert -1 == 1` (the second `recompute_offsets` call re-derived `direction` from the still-active
`alternate` mode, exactly the "provable no-op" the reviewer described for the brief's unguarded branches);
restored the fix, reran the full pure/core tier (315/2, +1 over the previous round).

A parallel dialog-level test, `test_hand_edited_direction_survives_a_later_replan`, drives the same scenario
through the table (`d.table.item(1, COL_DIR).setText("+1")`, then an unrelated edit elsewhere) rather than the
`ImportRow` field directly, and additionally checks the rendered cell text (`COL_DIR` shows "+1",
`COL_START` shows "0.00") after the second replan.

`Start (m)` stays read-only -- no `start_along_edited` was added, since (per the original decision, still valid)
`start_along` is mechanically derived from `direction` with no independent per-row meaning of its own to protect;
now explained to the user via a header tooltip (Finding 4).

## Finding 3 -- `unload()`'s `reject()` was undefended

**Fixed** (test-only; `unload()`'s own code was already correct, per the reviewer's framing -- `.reject()`, not
`.close()`). Added `test_unload_closes_a_hidden_import_dialog`, which `hide()`s the dialog before calling
`plugin.unload()`, alongside the existing `test_unload_closes_a_visible_import_dialog`.

**Demonstrated failing:** swapped `unload()`'s `self._import_dialog.reject()` for `.close()` and reran both
unload tests. `test_unload_closes_a_visible_import_dialog` stayed green (confirming the reviewer's diagnosis: a
*visible* dialog's own `closeEvent` calls `reject()` regardless of which one `unload()` calls, so that test alone
never exercised the fix). `test_unload_closes_a_hidden_import_dialog` failed: `plugin._import_dialog` was still
the (now C++-hidden-but-not-destroyed) dialog object, not `None`, because `close()` on a hidden `QDialog` accepts
the close event without ever calling `reject()`, so `finished` never fired. Restored `.reject()`; both tests green
again.

## Finding 4 -- `Start (m)` header tooltip

**Fixed.** `self.table.horizontalHeaderItem(COL_START).setToolTip(...)` set right after
`setHorizontalHeaderLabels(...)`, reading "Derived from Direction (mode, or a per-row edit) and row order; not
directly editable." Covered by `test_start_along_is_derived_not_hand_editable` (renamed from
`test_direction_and_start_along_are_derived_not_hand_editable`, now scoped to `Start` alone since `Dir` is
editable again), which asserts the tooltip is non-empty in addition to the cell staying non-editable.

## Finding 5 -- label edit was clearing `status` unconditionally

**Fixed.** Removed the unconditional `self.status.setText("")` from `_on_item_changed`'s `COL_LABEL` branch (it
never had anything of its own to report, so it had nothing to legitimately clear). Also did **not** add an
equivalent clear to the new `COL_DIR` branch (Finding 2), for the identical reason -- direction parsing from the
table always succeeds, so a `COL_DIR` edit clearing status would just be a second instance of the same defect
introduced in the very round meant to fix it. `COL_OFFSET`'s existing `self.status.setText("")` on a *successful*
parse was left alone: unlike label/direction, it is clearing a status that was, in the ordinary case, about that
same cell's own prior failed parse.

New test: `test_status_is_not_cleared_by_a_label_or_direction_edit` -- sets a standing `status` message directly,
edits both a label cell and a direction cell in turn, and asserts the message survives both.

## Not in scope (per reviewer)

Left untouched, as instructed: `label_edited` remains one-way (clearing a hand-edited label pins the row to the
file stem with no release back to automatic renumbering); `test_import_dialog_exec_is_guarded_by_default` still
tests the `conftest.py` fixture rather than anything specific to `ImportDialog`.

## Test results after fix round 1

- `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh` ->
  **163 passed** (26 in `test_plugin_import_dialog.py`, up from 22; 137 elsewhere, unchanged).
- `.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q` ->
  **315 passed, 2 skipped** (up from 314; +1 for the new `direction_edited` pure test).
- `.venv/bin/ruff check .` -> **All checks passed.**
- `.venv/bin/ruff format --check .` -> **72 files already formatted.**
- `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py`
  -> **Success: no issues found in 23 source files.**
- `test_real_files_import_into_the_grid` re-run in isolation: still passes, still not skipped.

## Files changed in this round

- `packages/nsgeo-qgis/nsgeo_qgis/lookup.py` (`direction_edited` field + `recompute_offsets` guard)
- `packages/nsgeo-qgis/nsgeo_qgis/ui/import_dialog.py` (`_grid()`'s except clause; `set_direction()`; `COL_DIR`
  back in `EDITABLE` with an `_on_item_changed` branch; `COL_START` header tooltip; `COL_LABEL`'s status-clearing
  removed; module docstring and the `EDITABLE`-adjacent comment rewritten)
- `packages/nsgeo-qgis/tests/pure/test_pure_lookup.py` (+1 test)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_import_dialog.py` (+4 tests, 1 renamed)
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`: touched only transiently, to demonstrate Finding 3's mutation
  failing, then restored -- no net diff (`git diff` against the previous commit is empty for this file).

---

# Fix round 2

Reviewer verdict on round 1: all five findings addressed and mutation-defended (including reverting
`direction_edited` and confirming `assert -1 == 1`), plus a set of interaction probes on the real ten files that
all came back correct (`offset_edited`/`direction_edited` together survive three replans; a reorder that moves a
flagged row into a slot alternate would give the opposite direction keeps the flagged direction while offset still
re-derives; a hand flip with `grid_size_along=None` produces exactly one note, cleared when the grid length
returns, so `_merge_note`'s delimiter contract holds). Two minor findings left, both in round-1 code, and both
were undefended fixes -- the same shape Finding 3 was promoted for one round earlier.

## Finding 1 (Minor) -- `COL_DIR ∈ EDITABLE` had no positive assertion

**Fixed.** Added `assert d.table.item(1, COL_DIR).flags() & Qt.ItemFlag.ItemIsEditable` to
`test_hand_edited_direction_survives_a_later_replan`, right before the `setText()` edit the rest of the test
already relies on being real.

**Demonstrated failing:** reverted `EDITABLE` to `{COL_LABEL, COL_OFFSET}` (dropping `COL_DIR`, exactly the
reviewer's suggested mutation) and reran the file. The new assertion failed
(`AssertionError: assert (<Qt.ItemFlags> & 2)` -- `COL_DIR`'s flags no longer includes `ItemIsEditable`); every
other assertion in that test, and all 26 other tests, stayed green, confirming the reviewer's diagnosis that
`item.setText()` bypasses the flag entirely and nothing else in the suite depended on it. Restored `EDITABLE`;
27/27 green again.

## Finding 2 (Minor) -- `COL_DIR` parsing silently read negative-looking text as forward

**Fixed**, choosing the reviewer's suggested split: a leading minus (either glyph, checked via
`text.startswith(("-", "−"))`) means reversed regardless of what follows, so `"-1.0"`, `"-2"`, and a bare `"-"` (or
`"−"`) all now correctly read as reversed instead of being silently pinned forward. Anything without a leading
minus is parsed as a float and must be strictly positive to count as forward; anything that fails to parse, or
parses to a non-positive number (`"0"` specifically -- not a valid direction, and previously one of the silently-
mispinned cases), is reported through `status` and reverted via `_refresh_table()` -- the same shape `COL_OFFSET`
already uses for its own unparseable text, rather than silently committing `direction_edited = True` against
whatever the user actually typed.

**Demonstrated failing:** reverted the branch to the previous exact-string match
(`text in ("-1", "−1") else 1`) and reran the new test. It failed immediately on the first case:
`AssertionError: -1.0 / assert 1 == -1` -- `"-1.0"` read as forward, direction pinned there, exactly the reviewer's
report. Restored the fix; 27/27 green again.

New test: `test_dir_edit_recognises_a_leading_minus_and_reports_unrecognised_text` -- drives `COL_DIR` through
four leading-minus variants (`"-1.0"`, `"-2"`, `"-"`, `"−"`), asserting each lands on `direction == -1` with
`direction_edited` set, then through three genuinely-unrecognised cases (`"0"`, `""`, `"reverse"`), asserting each
leaves `direction`/`direction_edited` untouched, sets a `"not recognised"` status message, and reverts the cell's
displayed text rather than leaving the typed garbage on screen.

## Not in scope (per reviewer)

Left untouched, as instructed: `direction_edited` remains one-way like `label_edited`; the `+1 -> -1` flip
direction was not added as a symmetric test (the reviewer had already verified it by direct probe and made it
conditional on being "free" -- it would have meant restructuring the existing survives-a-later-replan test's
fixture rather than a one-line addition, so left out); editing `Dir` on an excluded row, and a stale `status`
surviving a later successful `add_files`/`accept`, are both unchanged from round 1.

## Test results after fix round 2

- `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh` ->
  **164 passed** (27 in `test_plugin_import_dialog.py`, up from 26; 137 elsewhere, unchanged).
- `.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q` ->
  **315 passed, 2 skipped** (unchanged -- this round touched only the dialog and its qgis-tier tests, not
  `lookup.py`).
- `.venv/bin/ruff check .` -> **All checks passed.**
- `.venv/bin/ruff format --check .` -> **72 files already formatted.**
- `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py`
  -> **Success: no issues found in 23 source files.**

## Files changed in this round

- `packages/nsgeo-qgis/nsgeo_qgis/ui/import_dialog.py` (`COL_DIR` parsing branch of `_on_item_changed` rewritten)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_import_dialog.py` (+1 test; +1 assertion in an existing test)
