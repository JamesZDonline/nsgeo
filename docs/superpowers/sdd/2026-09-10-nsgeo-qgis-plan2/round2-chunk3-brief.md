# Round-2 chunk 3 — C3, C4, I8: three untested paths that destroy survey data

BASE: the branch tip of `nsgeo-qgis` when you start (C2 and chunk 2's I4/I5/I6 have landed).
Worktree `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-qgis`. Work only
there; never `cd` to the main checkout. Confirm the tree is clean before you touch anything.

## Scope — exactly three items

Read `.superpowers/sdd/2026-09-10-nsgeo-qgis-plan2/final-fix-brief.md` and implement, in full:

- **C3** — "The picks migration's verification step is untested"
- **C4** — "'New site' and 'Open site' do not protect unsaved work"
- **I8** — "The survey dock context menu is dead to the suite, and its destructive confirmations
  survive"

These are mostly **test** items: the production code is believed correct and the gap is that
nothing pins it. That does not make them small. Each one names a mutation that currently survives
the whole suite, and the deliverable is a test that kills it. C4 additionally tells you to verify
the production code while you are there and fix it if the Cancel path has a real defect — if you
find one, fix it and say so plainly.

Nothing else is yours. The "Out of scope — do not touch" list at the end of the final-fix brief
binds you.

## What the controller already knows, so you do not re-derive it

**I8 — the guard you need already exists, and there is a trap.** `tests/qgis/conftest.py` already
forbids `QMenu.exec` and `QMenu.exec_` (that half of I8 landed with C6 in `6d5f22f`), and the
controller has verified hands-on that both spellings raise. **But** `SurveyDock._on_context_menu`
wraps its whole body in `except Exception ... _log(...)` — so the guard's `AssertionError` is
caught and written to the message log instead of propagating to your test. A test that merely
calls `_on_context_menu` and expects a raise will pass for the wrong reason, or silently do
nothing. Design around that: expose the built menu the way `ProcessingDock` exposes
`presets_menu` (`processing_dock.py:162`, asserted on in `test_plugin_difference_presets.py:95`
via a `_menu_action` helper), so the action set can be asserted and each action `.trigger()`ed
without ever reaching `exec`. The `message_log` fixture in `conftest.py` is available if you want
to assert nothing was logged.

**I8 — the confirmations.** `remove_line_action` and `remove_grid_action`
(`survey_dock.py:309, 325`) both take `confirm: bool = True`, and **every existing test passes
`confirm=False`**, which bypasses the gate entirely. The two new tests must exercise the
`confirm=True` path with `answer_modal(QMessageBox, "question", StandardButton.No)` and assert
nothing was removed — and for the line, assert its **processing stack survives too**, because
`session.remove_line` drops the stack with the line.

**C3 — read it back off disk.** `layers.py:435-441` is the gate (`written != len(old_rows)`).
`test_picks_survive_a_failure_while_building_the_temporary_table` is the shape to copy: it opens
the original `picks` with a **fresh `QgsVectorLayer`** rather than going through `layers`,
deliberately, in case a failed rebuild left the registry stale. Do the same. Note the gate reads
`temp_layer.featureCount()` with a `-1` sentinel fallback, so there are two ways to make it
under-report — pick whichever gives the more honest test and say which.

**C4 — three tests each for `new_site` and `open_site`, plus the session guard.** The existing
unload trio (`test_unload_does_not_offer_a_cancel_that_would_be_ignored`,
`test_unload_saves_a_dirty_site_when_the_user_chooses_save`,
`test_unload_warns_explicitly_when_the_chosen_save_then_fails`, all in
`test_plugin_survey_dock.py`) is the standard to mirror. Cancel must assert **both** that the site
is unchanged **and** that `QFileDialog` was never reached — the default `_no_unhandled_modals`
guard makes the second assertion free, since an unexpected `getExistingDirectory` /
`getOpenFileName` raises. The mutations to kill: deleting the
`if self.session.dirty and not self.save_with_prompt(ask_first=True): return` line from each of
`plugin.py:349` and `:368`, and deleting `allow_cancel and answer == Cancel → return False` at
`:417`. Also add the missing test for `session.py:123`'s guard — `new_site` on a folder that
already holds a `survey.nsgeo.json` must raise rather than overwrite it.

## How to work

1. One item at a time. For each, run the mutation FIRST to see it survive the existing suite, then
   write the test, watch it fail, restore the mutation, watch it pass. Keep the output.
2. Three commits, one per item. Conventional-commit subject, a body explaining what the test pins
   and which mutation it kills (see `git log` for the standard), ending with exactly:
   `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
3. Do not weaken or delete existing assertions to make room for yours.

## Verification — after each commit, and again at the end

Export `PYTHONDONTWRITEBYTECODE=1` for every test run; stale `.pyc` files on this repo have faked
passing mutants before. From the worktree root:

```
QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests -q -p no:xonsh
.venv/bin/python -m pytest packages/nsgeo-core/tests/test_boundary.py \
  packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q -p no:xonsh
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
```

Controller-measured baseline at `5cc5a12`: qgis tier **336 passed**; pure+core **363 passed,
3 skipped**; boundary **6 passed** (BOTH boundary files -- the core one alone is 2); ruff clean; mypy clean. Your final run must be green with
strictly more tests than the tip you started from, quoting real counts from real output.

`-p no:xonsh` is a this-machine-only workaround and does not go into any config file.

Do NOT push, merge or rebase.

## Report

Write `.superpowers/sdd/2026-09-10-nsgeo-qgis-plan2/round2-chunk3-report.md`: per item, proof the
mutation survived before your test and died after, the test's failure output, the commit SHA, and
for C4 whether the production code had a real defect; then the final verification output with
real counts; then deviations and out-of-scope observations (name them, do not fix them).
