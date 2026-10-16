# Task 3 report: Pick mode, and the click that becomes a pick

## What I implemented

Exactly the brief's five production changes plus its pin update, in TDD order:

1. **`profile_view.py` (`mousePressEvent`)** — a pick (shift-click or pick-mode click) is now
   refused unless the local coordinates land inside `image_rect()` (`0 <= x < transform.width`
   and `0 <= y < transform.height`). Before this, a shift-click on the axis margins reached
   `time_of_y`/`trace_index_at` with out-of-range coordinates and emitted a pick outside the
   record.

2. **`profile_dock.py`**:
   - New public `set_pick_mode(flag: bool) -> None`, a pure passthrough to
     `self.view.set_pick_mode(bool(flag))`, placed immediately before `set_difference_index` as
     specified. First consumer of `ProfileView.set_pick_mode`, which shipped in Plan 2 unused.
   - `_pick`'s preview guard now emits `self.error` ("picks are authored on the working
     line; this is a preview — select the line on the map to work on it") instead of returning
     silently. The guard logic is unchanged; only the silence is gone. The `I6` comment block and
     the `try/except` around the relay emit are untouched, as instructed.

3. **`plugin.py`**:
   - `self.act_pick: QAction | None = None` in `__init__`, alongside the other actions.
   - A checkable "Pick" toolbar action after `act_import`, with the specified tooltip, behind a
     new separator.
   - `self.profile_dock.pick_requested.connect(self._on_pick_requested)` after the existing
     `error` connection.
   - `self.session.line_opened.connect(self._update_enabled)` alongside the existing
     `site_opened`/`site_closed` connections.
   - `_update_enabled` extended: `act_pick` is enabled only when a working line is open
     (`session.current_key is not None`), and losing that (site closed, or the working line
     cleared) also turns off pick mode if it was on — `setChecked(False)` plus a direct
     `_toggle_pick_mode(False)` call, since an unchecked-but-still-in-pick-mode view would be
     silently stuck.
   - Two new slots: `_toggle_pick_mode(checked)` (drives `profile_dock.set_pick_mode`, guards
     `profile_dock is None`, reports failures via `self.message(..., Warning)`) and
     `_on_pick_requested(key, trace, time_ns)` (calls `session.add_pick`, reports failures via
     `self.message(..., Critical)`). `session.add_pick` is never connected to a signal directly —
     it is reached only through this slot's `try/except Exception`.
   - `unload()` already tears down toolbar actions generically via `self.toolbar_actions`, but it
     also nulls the `act_*` attributes by name; added `self.act_pick = None` there too, per the
     brief's Step 5 check.

4. **`test_no_orphan_signals.py`** — `SHADOWED["pick_requested"]` moved from
   `{"declared": 2, "connects": 1}` to `{"declared": 2, "connects": 2}`, with the comment the
   brief specified (both declarations now have a consumer).

## Two defects found in the brief's own tests (fixed, not worked around)

Per the task's standing instruction ("fix the test to match the real file... do not silently
drop the test or weaken its assertion"):

1. **`test_a_pick_while_previewing_is_refused_out_loud`** (`test_plugin_profile_dock.py`), as
   given in the brief, never actually entered a preview. The `previewing` fixture only loads two
   lines and opens the first as the *working* line — reaching a preview requires calling
   `session.set_preview(...)` yourself, exactly as the sibling test
   `test_preview_renders_the_previewed_line_not_the_working_one` does. Without that call,
   `dock._preview_key` stays `None`, and the emitted pick reaches the working-line relay instead
   of the guard. Confirmed directly: run as written, the test failed on
   `assert emitted == []` (one tuple was there), never reaching the guard assertion at all — a
   false pass waiting to happen if I'd loosened the assertion instead of fixing the fixture use.
   **Fix:** added `session.set_preview(keys[1], 5)` before emitting the pick, with a NOTE comment
   explaining why.

2. **Three of the five new `test_plugin_loads.py` tests** (`test_the_pick_action_is_a_checkable
   _toggle_that_drives_the_view`, `test_a_pick_from_the_profile_reaches_the_picks_table`,
   `test_a_pick_that_cannot_be_written_is_reported_not_swallowed`) build a site via
   `_plugin_with_one_line`, which calls `add_grid`/`add_lines` — both of which dirty the session
   (`SiteSession._set_dirty(True)`) — and never close it before `plugin.unload()`. `unload()`
   dirty-and-open reaches `save_with_prompt(ask_first=True, allow_cancel=False)`, which
   unconditionally calls `QMessageBox.question` — forbidden by this tier's autouse
   `_no_unhandled_modals` fixture unless answered via `answer_modal`. Confirmed directly: run as
   the brief wrote them (no `answer_modal` fixture), each of these three failed inside its own
   `finally: plugin.unload()` with `AssertionError: unexpected modal: QMessageBox.question(...)`,
   which (via Python's exception-in-`finally`-replaces-the-original semantics) *masked* whatever
   the test body itself found. Every other test file in this tier that unloads a dirty plugin
   already answers `Discard` this way (`test_plugin_gain_strip.py`,
   `test_plugin_import_dialog.py`, `test_plugin_difference_presets.py`, `test_plugin_layers.py`).
   **Fix:** added the `answer_modal` fixture parameter and
   `answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)` to those three
   tests, with a comment on the first explaining why and cross-referencing it from the other two.
   The other two brief tests (`test_the_pick_action_is_disabled_until_a_line_is_open`,
   `test_disabling_the_pick_action_also_turns_the_crosshair_off`) each call
   `plugin.session.close_site()` before their own `finally`, so `unload()` finds `is_open` False
   and short-circuits before reaching the prompt — no fix needed there; confirmed empirically
   (see TDD evidence below: only the three needing the fix showed the modal failure once the
   *other* RED-phase noise — missing `act_pick`/`set_pick_mode` — was implemented away).

Both defects are the same shape as the ones flagged in Tasks 1 and 2's briefs: a fixture/test
wiring gap, not a requirements gap. I did not weaken any assertion — both fixes make the test
actually exercise what its own docstring says it exercises.

## What I tested and the results

**Pure tier** (`packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure`):
```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
367 passed, 2 skipped in 1.60s
```
Matches the stated baseline exactly.

**QGIS tier** (`packages/nsgeo-qgis/tests`), run twice (once before, once after the ruff-format
fix described below — both green):
```
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
504 passed in 172-174s
```
495 (baseline) + 9 new tests (2 in `test_plugin_profile_view.py`, 2 in
`test_plugin_profile_dock.py`, 5 in `test_plugin_loads.py`) = 504. Matches exactly.

**Lint/types:**
```
.venv/bin/ruff check .                 -> All checks passed!
.venv/bin/ruff format --check .        -> (after one auto-format, see below) 95 files already formatted
.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
  -> Success: no issues found in 24 source files
```
`ruff check` initially flagged two `E501` (line too long) in
`test_pick_mode_also_ignores_a_click_outside_the_radargram`, copied verbatim from the brief's own
snippet (105/104 chars). Ran `ruff format` on that one file to wrap the two `QTest.mouseClick`
calls across multiple lines (pure whitespace change, no semantic change); re-ran the focused
QGIS file and the full QGIS tier afterward, both still green (110 passed / 504 passed).

## TDD Evidence

**RED** — pure tier, after writing only the tests and the `SHADOWED` pin update (no production
code changed yet):
```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q -p no:xonsh
...
E       AssertionError: shadowed signals no longer match their pinned shape, as (expected, actual) pairs: {'pick_requested': {'declared': (2, 2), 'connects': (2, 1)}}. ...
1 failed, 49 passed in 0.83s
```
Expected: the pin now claims 2 connects but the plugin still only wires `ProfileView.pick_requested`
(1), not `ProfileDock.pick_requested` yet — exactly Step 2's predicted failure.

**RED** — QGIS tier, same point in time:
```
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest \
  packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py \
  packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py \
  packages/nsgeo-qgis/tests/qgis/test_plugin_loads.py -q -p no:xonsh
...
9 failed, 101 passed in 4.81s
```
Failure reasons (isolated via targeted reruns), all expected:
- `test_a_shift_click_outside_the_image_rect_is_not_a_pick` / `test_pick_mode_also_ignores_a_click_outside_the_radargram`:
  assertion failures — picks fired for out-of-rect clicks (no bound check yet).
- `test_set_pick_mode_reaches_the_view`: `AttributeError: 'ProfileDock' object has no attribute 'set_pick_mode'`.
- `test_a_pick_while_previewing_is_refused_out_loud`: `assert 0 == 1` (no `error` emitted — old silent `return`).
- The five `test_plugin_loads.py` tests: `AttributeError: 'NsgeoPlugin' object has no attribute 'act_pick'`
  (plus, in the RED phase only, the two brief-defect modal cascades described above, which resolved
  themselves once I fixed the test wiring — not a production-code symptom).

**GREEN** — focused files, after implementing Steps 3-5:
```
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest \
  packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py \
  packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py \
  packages/nsgeo-qgis/tests/qgis/test_plugin_loads.py -q -p no:xonsh
110 passed in 5.61s
```

**GREEN** — pure tier orphan check:
```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py -q -p no:xonsh
4 passed in 0.29s
```

**GREEN** — both full tiers (see "What I tested" above): pure 367/2, QGIS 504.

## Injection evidence (Step 7)

- **Scratch copy location:** `/tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/00c69e5a-8152-4498-8bba-9b3166a8043e/scratchpad/m8-task3-orphan-check/nsgeo-qgis`
  (a full copy of `packages/nsgeo-qgis`, made with `cp -r`, never touched inside the worktree).
- **Baseline check on the scratch copy** (before injection):
  ```
  .venv/bin/python -m pytest <scratch>/tests/pure/test_no_orphan_signals.py -q -p no:xonsh
  4 passed in 0.33s
  ```
- **Injection:** added an unconnected third declaration of the shadowed name, on a class
  unrelated to `ProfileView`/`ProfileDock`, in `<scratch>/nsgeo_qgis/loader.py`:
  ```python
  class LineLoader(QObject):
      ...
      loading_changed = pyqtSignal(str, bool)
      pick_requested = pyqtSignal()  # INJECTED for Step 7's orphan-check verification; unconnected
  ```
- **Command and observed failure:**
  ```
  .venv/bin/python -m pytest <scratch>/tests/pure/test_no_orphan_signals.py -q -p no:xonsh
  ...
  E       AssertionError: shadowed signals no longer match their pinned shape, as (expected, actual)
  pairs: {'pick_requested': {'declared': (2, 3), 'connects': (2, 2)}}. ...
  1 failed, 3 passed in 0.32s
  ```
  `test_shadowed_signals_match_their_pinned_shape` failed exactly on the `declared` count
  (pinned 2, actually 3) — precisely what Step 7 asks to confirm: a third, unconnected,
  same-named declaration is caught even though the `connects` count (2) didn't move.
- **Restore and re-run:** removed the injected line from the scratch copy, re-ran:
  ```
  .venv/bin/python -m pytest <scratch>/tests/pure/test_no_orphan_signals.py -q -p no:xonsh
  4 passed in 0.30s
  ```
  Back to green, confirming the scratch copy (and by extension the real check in the working
  tree, which was never touched by this step) round-trips cleanly.

## Files changed

- `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py` — bound check in `mousePressEvent`.
- `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` — `set_pick_mode`; `_pick`'s spoken refusal.
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` — `act_pick`, its toolbar wiring, `_update_enabled`
  extension, `_toggle_pick_mode`, `_on_pick_requested`, `unload()`'s `act_pick = None`.
- `packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py` — `SHADOWED["pick_requested"]` pin.
- `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py` — two new tests (plus a
  `ruff format` pass on the file to fix two brief-inherited long lines).
- `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py` — `Qt` import, two new tests (one
  amended to actually enter preview — see defect #1 above).
- `packages/nsgeo-qgis/tests/qgis/test_plugin_loads.py` — `pytest`/`Qt`/`QMessageBox` imports,
  `_plugin_with_one_line` helper, five new tests (three amended with `answer_modal` — see defect
  #2 above).

## Self-review findings

- Diff is scoped exactly to the files the brief named; no unrelated changes, no restructuring.
- `_pick`'s existing comment block was extended, not replaced or stripped, per instructions.
- The `I6` comment block and the `try/except` around `_pick`'s relay emit are byte-for-byte
  unchanged, as the brief required.
- `_toggle_pick_mode` and `_on_pick_requested` each catch their own exceptions and report via
  `self.message`, matching the module's stated slot-safety contract; `session.add_pick` is never
  connected to a signal directly, only reached through `_on_pick_requested`'s `try`.
- Both test-authoring defects I found and fixed are the same *shape* of gap the task brief
  explicitly warned to expect and fix rather than paper over (fixture-shape/wiring gaps, not
  requirements gaps) — I did not weaken any assertion to make either test pass.
- Confirmed the two "no-fix-needed" `test_plugin_loads.py` tests really don't need `answer_modal`
  by tracing `close_site()`'s effect on `is_open` before their own `unload()` — not just by
  observing the final green run.
- No dialogs added; no new `QMessageBox`/`QFileDialog`/`QInputDialog`/`QDialog.exec`/`QMenu.exec`
  calls introduced by production code (the one `QMessageBox` reference added is in test code,
  answering an existing, pre-M8 prompt via the sanctioned `answer_modal` fixture).
- Left `test_no_orphan_signals.py`'s top-of-file historical note (the "real set is SEVEN..."
  paragraph, referencing Plan 2's original orphan count and Task 5's brief) untouched — it is
  documenting Plan 2's original state for context, not asserting the current shape of `SHADOWED`,
  and the brief only asked to update the pin itself.

## Issues or concerns

None. Both tiers are green and above baseline, ruff and mypy are clean, and the two brief-test
defects were fixed rather than worked around, each confirmed by direct observation of the wrong
failure mode before the fix.
