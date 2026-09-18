# Task 9 report: Survey dock and the plugin's file actions

## Fix round 1 (review response)

Committed on top of `d5e719d`. All five findings addressed.

### Finding 1 — `unload()` discarded the user's Cancel

**Shape chosen: Save | Discard only, no Cancel, from `unload()`.** `save_with_prompt()`
gained an `allow_cancel: bool = True` keyword. `unload()` now calls
`save_with_prompt(ask_first=True, allow_cancel=False)`, which drops
`QMessageBox.StandardButton.Cancel` from the button set entirely rather than
showing it and then ignoring the answer — the reviewer's framing ("stop
offering a button that cannot do what it says") is exactly right, and a
removed button is a clearer signal to the user than a present-but-inert one.
`new_site()`/`open_site()` keep the default (`allow_cancel=True`): both of
those genuinely can abort their own action, so Cancel there does what it says.

If the user picks Save and the save then fails, `unload()` now logs an
explicit follow-up at `Critical` — `"could not save changes before
unloading; unsaved changes will be lost"` — through `message()` (so it hits
both `QgsMessageLog` and the message bar), since `save_with_prompt()`'s own
failure message ("could not save the site: …") doesn't say the data is
about to be gone. `unload()` then proceeds regardless, because it has no
other option: QGIS does not offer a way to veto its own unload.

New tests (using the Finding 3 fixture, see below):
`test_unload_does_not_offer_a_cancel_that_would_be_ignored` (asserts the
actual button bitmask passed to `QMessageBox.question` has Save and Discard
set and Cancel *not* set), `test_unload_saves_a_dirty_site_when_the_user_chooses_save`
(Save path succeeds, session ends up clean), `test_unload_warns_explicitly_when_the_chosen_save_then_fails`
(Save path fails, unload still proceeds, message bar carries "unsaved
changes will be lost").

### Finding 2 — `line_velocity_requested` was permanently unconnected

Added `open_velocity_dialog(self, key: str) -> None` to `NsgeoPlugin`, in the
same message-bar-stub shape as `open_grid_dialog`/`open_import_dialog`, and
wired `self.survey_dock.line_velocity_requested.connect(self.open_velocity_dialog)`
in `initGui()`. New test: `test_line_velocity_requested_reports_that_no_dialog_exists_yet`.

### Finding 3 — no guard against a modal hanging the suite

Added to `packages/nsgeo-qgis/tests/qgis/conftest.py`:

- `_no_unhandled_modals` (autouse, function-scoped): monkeypatches
  `QMessageBox.question`/`warning`/`information` and
  `QFileDialog.getOpenFileName`/`getExistingDirectory` to raise
  `AssertionError(f"unexpected modal: {cls}.{name}{args!r}")` — for every
  test in the `qgis` tier, by default. Raises rather than returning a
  default answer, per the instruction: a default would silently pass
  through exactly the class of bug this exists to catch (nothing before
  this asserted a prompt appeared at all, or with which buttons).
- `answer_modal` (opt-in): `calls = answer_modal(QMessageBox, "question", <answer>)`
  re-monkeypatches one specific `(class, method)` pair to return `<answer>`
  instead of raising, and records each call's `(args, kwargs)` into the
  returned list, so a test can supply an answer *and* assert on what was
  actually shown. Because the actual patching happens when the test body
  calls `answer_modal(...)`, not at fixture-setup time, it always overrides
  the autouse guard's patch regardless of fixture instantiation order — no
  explicit dependency between the two fixtures was needed.

Verified the raise-by-default behavior is real, not decorative, with a
throwaway probe test (written, run under `timeout 20`, and deleted — not
part of the committed test suite): `plugin.unload()` on a dirty session,
with no `answer_modal` in play. Result: fails in 1.27s with
`AssertionError: unexpected modal: QMessageBox.question(<QMainWindow ...>,
'Unsaved changes', 'Save the site before continuing?', <StandardButtons ...>)`
— the same call that, before this round's fix, blocked indefinitely (the
original `do_poll`/never-returns hang this whole finding is about).

This fixture also converts the round-1 workaround into something no longer
structurally necessary: `test_save_with_prompt_reports_unexpected_errors_and_keeps_the_site_dirty`
still doesn't call `plugin.unload()` (still not its job — see updated
comment), but `unload()`'s dirty-session path is no longer "untested and
untestable as written" per the finding: it's now covered directly by the
three new tests above, driven through `answer_modal` rather than avoided.

Followed the "use `timeout` around anything that might open a modal"
instruction literally while iterating — every run of the new tests during
this round went through `timeout 90 ... pytest ...`, never a bare
`run_in_background` invitation to hang unnoticed.

### Finding 4 — the unload test pinned bookkeeping, not `deleteLater()`

Rewrote `test_unload_releases_every_toolbar_and_menu_action`: holds a
reference to one toolbar action and one menu action from before `unload()`,
calls `unload()`, then forces the deferred delete through and asserts
`sip.isdeleted()` on both.

One implementation wrinkle worth recording: `qgis_app.processEvents()` alone
does **not** dispatch a `QEvent::DeferredDelete` event — I verified this
empirically with a throwaway script (`deleteLater()` + `processEvents()` x2
left `sip.isdeleted()` still `False`). What actually forces it is
`qgis_app.sendPostedEvents(None, QEvent.Type.DeferredDelete)`, which is what
the test now calls. Recorded here since the reviewer's suggested shape
mentioned `processEvents()` specifically and I want to flag the deviation:
I used `sendPostedEvents(None, QEvent.Type.DeferredDelete)` instead, because
`processEvents()` alone did not make the assertion pass.

### Finding 5 — the dock recomputed line keys and read `site.lines` directly

`_rebuild()` now builds `(key, line)` pairs by iterating `self.session.keys()`
and calling `self.session.line_for_key(key)` for each — the same pattern
`SiteLayers.refill_lines()` already uses (Task 8) — instead of iterating
`site.lines` and recomputing each line's key via `self.session.line_key(line)`.
`_line_item()` now takes `key` as an explicit parameter instead of
recomputing it. `ROLE_ID` for a line item is therefore always exactly the
string `session.keys()`/`open_line()` use for that same line — they cannot
diverge even if `line.path` or `root` were ever to change under an open site.

**Scoped deviation, stated explicitly:** I left `site.grids` read directly
(`site = self.session.site; ... for grid in site.grids`). `SiteSession` has
no per-grid equivalent of `_lines_by_key`/`keys()`/`line_for_key()` — no
`session.grids` property, no `grid_ids()`, nothing — and `SiteLayers.refill_grids()`
(Task 8, already reviewed and accepted) reads `site.grids` directly for the
same reason. Unlike a line's key, a `Grid.id` is not derived from anything
that can drift out from under it (it's stored on the `Grid` object itself,
not recomputed from a path against a `root` that can change), so there is no
equivalent "authoritative index vs. recomputed value" risk for grids that
the finding's stated failure mode ("the day line.path or root can change …
the tree's keys and open_line's keys diverge silently") describes. I did
change how the *null-site* check works: it now goes through
`self.session.is_open` rather than `self.session.site is None`, so at least
that one read goes through the session's own accessor rather than around it.
If a future task adds a `SiteSession` grid accessor, `_rebuild()` should
switch to it, but adding one now would be outside this task's declared file
list (`session.py` isn't in Task 9's Files section).

## Verification after all five fixes

```
$ timeout 90 env QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest \
    packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py -q -p no:xonsh
18 passed in 3.21s

$ timeout 120 env QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest \
    packages/nsgeo-qgis/tests -q -p no:xonsh
91 passed in 44.36s          (was 87 before this round: +4 new tests)

$ .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q
313 passed, 2 skipped in 1.31s   (unchanged)

$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
66 files already formatted

$ .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
    packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py
Success: no issues found in 23 source files
```

Two new ruff findings surfaced against my own round-1 code (not present
before, introduced by this round's edits) and were fixed before committing:
`SIM102` in `plugin.py`'s `unload()` (nested `if` collapsed into one
`and`-chained condition — semantically identical, since `and` short-circuits
left to right the same way the nested `if`s did) and `SIM118` in
`survey_dock.py`'s new `for key in self.session.keys():` (same false-positive
as the one already `noqa`'d in the test file: `SiteSession.keys()` returns
`list[str]`, not a dict, so ruff's `.keys()`-implies-dict heuristic doesn't
apply here either — `noqa`'d with the same one-line reason).

## Files changed, this round

- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (Findings 1, 2)
- `packages/nsgeo-qgis/nsgeo_qgis/ui/survey_dock.py` (Finding 5)
- `packages/nsgeo-qgis/tests/qgis/conftest.py` (Finding 3, new file additions only)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py` (Findings 1, 2, 4 — new/rewritten tests)

## What I implemented

- `packages/nsgeo-qgis/nsgeo_qgis/ui/__init__.py` — docstring-only package marker, no imports, per the brief (so the pure tier can later import `ui.view_transform` with no Qt present).
- `packages/nsgeo-qgis/nsgeo_qgis/ui/survey_dock.py` — `SurveyDock(QgsDockWidget)`: a `QTreeWidget` (`site -> grids -> lines`) and a `QLabel` status line, bound to `SiteSession` signals, plus `new_site_requested`/`open_site_requested`/`save_requested`/`add_grid_requested`/`edit_grid_requested(str)`/`import_requested(str)`/`grid_velocity_requested(str)`/`line_velocity_requested(str)`, `ROLE_KIND`/`ROLE_ID` item-data roles, `rebuild()`, `item_for_key`/`grid_id_of`/`key_of`, and `remove_line_action`/`remove_grid_action`.
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` — rewritten: `NsgeoPlugin` now owns a `SiteSession`, a `SiteLayers`, and the `SurveyDock`; toolbar actions `act_new`/`act_open`/`act_save`/`act_add_grid`/`act_import`; `new_site()`, `open_site()`, `save_with_prompt()`; stub `open_grid_dialog`/`open_import_dialog` for Tasks 10/11.
- `packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py` — the brief's 8 tests verbatim, plus 6 more covering explicit "Get these right" requirements and the failure-path hazard that the brief's own list doesn't exercise (see below).

## Testing

Both tiers, ruff, mypy, all green:

```
.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q
  313 passed, 2 skipped in 0.94s        (unchanged from baseline — no core/pure files touched)

QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
  87 passed in 41.40s                    (baseline 73 + 14 new in test_plugin_survey_dock.py)

.venv/bin/ruff check .        -> All checks passed!
.venv/bin/ruff format --check . -> 66 files already formatted

.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py
  -> Success: no issues found in 23 source files
```

## TDD evidence

**RED** — wrote the full test file (brief's 8 + my 6 additional tests) before any implementation existed:

```
$ QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py -q -p no:xonsh
ImportError while importing test module '.../test_plugin_survey_dock.py'.
...
    from nsgeo_qgis.ui.survey_dock import ROLE_ID, ROLE_KIND, SurveyDock
E   ModuleNotFoundError: No module named 'nsgeo_qgis.ui.survey_dock'
```
Expected and matched the brief exactly: the `ui` package and `survey_dock` module did not exist yet.

**GREEN** — after implementing `ui/__init__.py`, `ui/survey_dock.py`, and `plugin.py`:

```
$ QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py -q -p no:xonsh
..............                                                           [100%]
14 passed in 1.73s
```

### A real bug found and fixed mid-TDD (in my own test, not the plugin)

While driving the new failure-path tests to green, one of them —
`test_save_with_prompt_reports_unexpected_errors_and_keeps_the_site_dirty` — hung
indefinitely under `QT_QPA_PLATFORM=offscreen`. `ps`/`/proc/<pid>/wchan` showed the
process parked in `do_poll`, i.e. blocked in a Qt event loop with nothing to answer it.
Root cause: the test deliberately leaves the session dirty (that's the point of the
test) and then called `plugin.unload()`. `unload()` sees the dirty session and calls
`save_with_prompt(ask_first=True)`, which shows a real, blocking `QMessageBox.question`
("Unsaved changes — Save/Discard/Cancel") *before it ever attempts to save* — so
nothing about the monkeypatched `save()` failing was relevant; the modal blocks
unconditionally whenever `dirty` is true and `ask_first=True`, and under `offscreen`
nothing will ever click a button. Fixed by removing the trailing `plugin.unload()`
call from that one test (its job — verifying `save_with_prompt()`'s own failure
handling — was already complete at the preceding assertions; plugin/session teardown
was never part of what it needed to prove). Confirmed the isolated test now completes
in ~1.2s, and the full file completes in 1.73s.

## The failure-path audit

Per the task's standing hazard: an exception raised inside a slot connected via
PyQt's `connect()` never reaches whatever emitted the signal (stderr only,
`emit()` returns as if nothing happened). I went slot-by-slot:

**`SurveyDock`**
- `rebuild()` (connected to `site_opened`/`site_closed`/`grids_changed`/`lines_changed`): wraps the real work (`_rebuild()`) in try/except. On any unexpected exception, logs via `QgsMessageLog` and **empties the tree** with a visible `"survey tree error — see the nsgeo log"` status, rather than leaving a half-built tree that would look complete and be silently wrong. Pinned by `test_rebuild_survives_an_unexpected_error_and_leaves_an_honest_empty_tree` (monkeypatches `_line_item` to raise mid-build; asserts the tree ends up empty with an error status, not a partial tree or a propagated exception).
- `_line_item()`: the one *expected* failure — `GridPlacement.distance_along()` raises `ValueError` for a time-triggered acquisition (`traces_per_metre <= 0`). Caught narrowly (matching `SiteLayers._line_points`'s own handling of the same condition) and the line is marked `"⚠ unplaced (time-triggered)"` rather than omitted or allowed to blow up the whole rebuild. Pinned by `test_time_triggered_lines_appear_in_the_tree_marked_not_omitted`.
- `_update_status()` (connected to `dirty_changed`): guarded; logs on failure rather than leaving a stale/wrong dirty indicator with no trace of why.
- `_follow_current()` (connected to `line_opened`): guarded.
- `_open_line()` (the shared body of the tree-click and context-menu "Open" handlers): guarded — a click on a tree item whose underlying line vanished between build and click (or a bug) is logged, not silently dropped mid-signal.
- `_on_context_menu()` (connected to `customContextMenuRequested`): guarded around menu *construction*. Note in the docstring/comment: `QMenu.exec()` runs its own nested event loop, and the action the user eventually picks fires through an ordinary `pyqtSignal` — so that guard does **not** protect the deferred lambdas; each of those (`remove_line_action`, `remove_grid_action`, `_open_line`) has to (and does) guard itself independently. This is the one place in the file where getting the swallowed-exception model wrong would have been easy, so I documented it explicitly rather than relying on the surrounding guard to look sufficient.
- `remove_grid_action()` (brief's code, unchanged): catches `ValueError`, warns interactively or re-raises for a programmatic caller (`confirm=False`) — already correct.
- `remove_line_action()`: brief's code didn't guard the `KeyError` `session.remove_line()` can raise. Added the same interactive-warn/programmatic-reraise split as `remove_grid_action`, for symmetry and because a stale tree item (theoretically reachable, e.g. two rapid removals) must not vanish into stderr. Pinned by `test_remove_line_action_reraises_rather_than_silently_dropping_a_missing_key`.
- `_capture_state`/`_identity`/`_item_for_identity`/`_restore_selection`: pure, exception-free by construction (attribute reads and dict lookups only); not separately guarded, and I don't think they need to be — called only from inside `_rebuild()`, which is already covered by `rebuild()`'s outer guard.

**`NsgeoPlugin`**
- `message()`: hardened to be the one deliberately silent catch in the file — logging *and reporting* a failure can't be allowed to itself throw, because there is nowhere further to report that failure to. Every other guard in this file routes through it.
- `new_site()` / `open_site()`: the brief's reference code caught only `ProjectError`. That's too narrow — `SiteSession.new_site()`/`open_site()` can just as easily raise a plain `OSError` (a read-only filesystem, per the session-tier test `test_new_site_does_not_install_when_the_initial_save_fails`) or, for `open_site()`, a `DztError`/`OSError` from a corrupt or unreadable referenced `.DZT` file (`load_site()` calls `Line.open()` with no wrapping try/except of its own). Either way it's an uncaught exception inside a `QAction.triggered` slot: silently swallowed, user sees nothing. Broadened both to `except Exception`. Pinned by `test_new_site_reports_unexpected_errors_without_crashing_or_losing_state` (monkeypatches `session.new_site` to raise `OSError`; asserts `new_site()` doesn't raise and the message bar shows the error).
- `save_with_prompt()`: same defect, same fix, for both the normal save and the `allow_absolute` retry path — every branch that can fail now returns `False` rather than raising, since callers (`new_site`/`open_site`/`unload`) treat `True` as "safe to discard the dirty site." A failed save must never look like a successful one. Pinned by `test_save_with_prompt_reports_unexpected_errors_and_keeps_the_site_dirty` (monkeypatches `session.save` to raise `OSError`; asserts `save_with_prompt()` returns `False`, `session.dirty` stays `True`, and the message bar shows the error).
- `_update_enabled()` (connected to `site_opened`/`site_closed`): guarded, defensively — its three actions are only ever `None` before `initGui()` finishes, and this slot is only ever connected after `initGui()` finishes, so it's safe by construction, but the cost of a guard here is negligible and it closes the loop the task asked for.
- `open_grid_dialog`/`open_import_dialog` (stubs): trivially safe now that `message()` can't raise.

## Deviations from the brief's reference code (with reasoning)

1. **Toolbar action leak, per the brief's own note.** The brief said Task 5's `initGui()`/`unload()` pattern (menu-only actions, `removePluginMenu` + `deleteLater()` for every entry in one `self.actions` list) needed fixing rather than copying, since this task adds real toolbar actions. I found the concrete defect: `QToolBar.addAction()` does **not** reparent the action (unlike `QToolBar.addSeparator()`, whose returned action *is* toolbar-owned) — the five toolbar `QAction`s stay parented to `iface.mainWindow()` forever unless explicitly `deleteLater()`'d, independent of the toolbar's own teardown. Worse, dumping them into the *same* list as the menu's "About" action and unconditionally calling `iface.removePluginMenu(MENU, action)` on all of them would raise (`FakeIface.removePluginMenu` does `list.remove(...)`, which throws for an action never added to that menu), aborting `unload()` partway through and leaking everything after it. Fixed by splitting into `menu_actions` (needs `removePluginMenu` + `deleteLater()`) and `toolbar_actions` (needs only `deleteLater()`). Pinned by `test_unload_releases_every_toolbar_and_menu_action`.
2. **`new_site()`/`open_site()`/`save_with_prompt()` caught only `ProjectError`.** Broadened to `except Exception` as described above in the failure-path audit — this is a correctness fix for the same swallowed-exception hazard the task brief calls out as the central risk of this task, not a style preference.
3. **`remove_line_action()` had no failure handling for `session.remove_line()`'s `KeyError`**, unlike `remove_grid_action()`'s already-correct handling of `remove_grid()`'s `ValueError`. Made symmetric.
4. **Time-triggered lines are not merely "not crashing" — they're now marked.** The brief's reference `_line_item()` doesn't call anything that could raise for such a line (so it technically doesn't crash), but it also never distinguishes an unplaceable line from a placeable one, which the brief's own "Get these right" section requires ("such a line must appear in the tree, marked"). Added the guarded `line.distance_along()` probe and the `"⚠ unplaced (time-triggered)"` marker.
5. **Expansion/selection preservation across `rebuild()`.** The brief's reference `rebuild()` does a full `tree.clear()` + rebuild + `expandAll()` on every signal, unconditionally re-expanding everything and dropping whatever the user had selected unless it happens to be the session's current line. Per the brief's own "Get these right" list ("preserve selection and expansion state ... where you reasonably can"), added `_capture_state()`/`_restore_selection()`: a grid's expand/collapse state survives an unrelated rebuild (new grids default to expanded), and a manually-selected grid or site node survives an unrelated rebuild too (the session's current line still always wins when one is open). Not separately unit-tested beyond the given tests' structural assertions (which don't exercise expand state at all) — this is a UX-quality improvement over the reference, not a new externally-observable contract the brief specified a test for; I judged it not worth inventing synthetic expand/collapse assertions for a rebuild path that's otherwise fully covered.
6. **SIM401/SIM118 ruff findings against otherwise-verbatim brief code.** `by_grid[grid_id] if grid_id in by_grid else loose` → `by_grid.get(grid_id, loose)` (ruff SIM401, semantics-preserving). The test file's `assert "..." not in session.keys()` (copied verbatim from the brief) trips SIM118, which assumes `.keys()` implies a dict — `SiteSession.keys()` is a plain method returning `list[str]`, so ruff's suggested fix (`not in session`) would be wrong (`SiteSession` has no `__contains__`/`__iter__`). Added a `# noqa: SIM118` with a one-line reason rather than either breaking the test or leaving lint dirty.

## Interface confirmations (no change needed)

- **Task 8 ordering requirement** ("construct `SiteLayers` before the first `site_opened` fires"): `self.layers = SiteLayers(self.session)` runs immediately after `self.session = SiteSession()` in `initGui()`, before any user-triggered `new_site()`/`open_site()` can exist — trivially satisfied, confirmed by reading `initGui()`'s body rather than assumed.
- **`ui/__init__.py`**: docstring only, no imports, matching the brief exactly (verified via the pure-tier boundary test, which parses every `.py` file under `nsgeo_qgis/` by AST and would fail on a forbidden import even without QGIS installed).

## Files changed

- `packages/nsgeo-qgis/nsgeo_qgis/ui/__init__.py` (new, 3 lines)
- `packages/nsgeo-qgis/nsgeo_qgis/ui/survey_dock.py` (new, 330 lines)
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (rewritten, 253 lines; was 58)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py` (new, 229 lines; 14 tests)

## Self-review findings

- Read the full diff of `plugin.py` and the full new content of `survey_dock.py` end to end after formatting; naming is consistent with the existing codebase (`_log`, `message()`, `_toolbar_action`, `ROLE_KIND`/`ROLE_ID` match the brief's/earlier tasks' conventions).
- Checked for YAGNI: didn't add anything beyond what the brief's interface list requires plus the explicitly-called-out "Get these right" items and the hazard-mitigation the task made a deliverable. Did not touch `open_grid_dialog`/`open_import_dialog` beyond making `message()` (which they call) safe — implementing anything more there would be scope creep into Tasks 10/11.
- Checked the new tests assert on *behaviour* (tree structure, status text, returned booleans, dirty flag, message-bar content, action list emptiness) rather than restating implementation details (no test inspects `_capture_state`'s internals directly, for instance).
- One noted, disclosed gap: `_on_context_menu()` itself (menu construction from a right-click position) is not exercised by any test, brief's or mine — matching the brief's own original scope (only `remove_line_action`/`remove_grid_action` are tested directly, bypassing menu construction). I judged adding synthetic mouse-position/menu-content tests disproportionate to this task's scope, since the underlying per-action calls are already independently tested.
- Observed (not fixed, not a regression): `initGui()` constructs `SiteLayers(self.session)` against the global `QgsProject.instance()` (no override), matching the brief's reference exactly — every plugin-level test that opens a site and adds a grid (the given `test_plugin_wires_the_dock_and_file_actions` plus two of mine) creates real GPKG-backed map layers in that shared, per-process singleton. This is pre-existing brief-level design (Task 8's own `test_plugin_layers.py` deliberately isolates via `project.clear()` for schema tests; plugin-level smoke tests don't), not something I introduced, and the full suite ran green and in reasonable time, so I left it alone and am only flagging it as a possible future cleanup if the QGIS-tier suite grows much larger.

## Concerns

- None blocking. The one open item is the disclosed `_on_context_menu` coverage gap above, and the `QgsProject` singleton observation, both carried forward from the brief's own design rather than introduced by me.

## Commit

Committed with the message the brief specified (attribution line per current session instructions, not the brief's since the brief predates that guidance).
