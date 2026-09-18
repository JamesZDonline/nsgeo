# Task 18 Report: Gain-curve strip beside the profile

## What was implemented

Exactly the brief's structure, plus one design decision (the axis question)
and two defects the brief's own verbatim test/fixture code did not survive
running for real.

- **`packages/nsgeo-qgis/nsgeo_qgis/ui/gain_strip.py`** (new): `GainStrip`,
  a custom-painted `QWidget` sharing the profile viewer's `ViewTransform`.
  Vertical axis = two-way time (via `y_of_time`/`time_of_y`, offset by
  `MARGIN_TOP`); horizontal axis = dB, auto-ranged to fit the current
  points with headroom. Drag a handle to move it, double-click empty space
  to add a point, right-click a handle to remove it (never below two).
  Every mutation emits `points_changed(list)`. Implemented essentially
  verbatim from the brief, with one deliberate change: `paintEvent` uses
  `try/finally: p.end()` (the brief's own code called `p.end()` before each
  early `return` instead) -- this repo's documented hazard ("a second
  repaint after an escaped exception segfaults") applies directly to any
  custom-painted widget, and `try/finally` is the only form that guarantees
  `end()` runs regardless of what happens in between.

- **`packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`**: `GainStrip` added
  beside `ProfileView` in an `QHBoxLayout` (`viewer_row`), both parented to
  `body` (the dock's owned central widget) -- not appended to `body`'s
  layout and left otherwise parentless, which is the "widget destroyed by
  the layout that was supposed to hold it" class of defect the brief warns
  about; `GainStrip(body)` is parented before `viewer_row.addWidget(...)`
  ever runs, same as `self.view`. Added `gain_points_changed` signal,
  `_sync_strip_mapping()` (keeps the strip's time axis following
  `self.view.transform`, called at the end of `_render()` and whenever
  `view_changed` fires), and `show_gain_strip(points | None)`.

- **`packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py`**: `time_axis()`
  changed to prefer `stack.result()` over `stack.source` (see axis decision
  below), with a `ValueError` fallback.

- **`packages/nsgeo-qgis/nsgeo_qgis/plugin.py`**: `_curve_param_name(step)`
  (schema-kind-driven, not name-driven), `_sync_gain_strip(row)` (routes
  `ProcessingDock.step_selected` to `ProfileDock.show_gain_strip`), and
  `_on_gain_points(points)` (routes `ProfileDock.gain_points_changed` to
  `session.replace_step` via `build_step`). Also added an echo-guard
  (`_gain_echo_pos`/`_gain_echo_step`) not in the brief's own pseudocode --
  see "A defect I found and fixed" below.

- **`packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py`** (new): the
  brief's four tests plus three more (the axis-decision fallback test lives
  in `test_plugin_param_form.py` instead, next to `time_axis()`'s existing
  tests): a public-signal defensive-guard test and a drag-past-a-neighbour
  regression test (see below). Two of the brief's given test bodies needed
  fixing, not just transcribing -- both are argued in detail below.

## TDD evidence

**RED** (Step 1/2 of the brief, run verbatim):
```
QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py -q
```
```
ModuleNotFoundError: No module named 'nsgeo_qgis.ui.gain_strip'
1 error in 0.15s
```
Expected failure: the module didn't exist yet.

**GREEN** (after implementing `gain_strip.py`, `profile_dock.py`, `plugin.py`):
```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py -q -p no:xonsh
```
```
.......                                                                  [100%]
7 passed in 2.85s
```
(7, not the brief's 4, because two of the brief's own tests needed a real
fix rather than a literal transcription -- see below -- and I added two more
regression tests for defects found along the way.)

## The axis decision: `stack.source` vs `stack.result()`

**Decision: `time_axis()` now prefers `stack.result()`, falling back to
`stack.source` on `ValueError`, falling back to the line's header when
nothing has loaded. The strip's own drawn axis was never the problem --
it already comes from `ProfileDock.view.transform`, which `_render()`
derives from `current_radargram()` (`stack.result()`/`stack.difference()`),
already the correct, post-any-preceding-step axis.**

Tracing the brief's own hint carefully: the strip's *pixel* mapping
(`GainStrip.set_time_mapping`, called from `ProfileDock._sync_strip_mapping`)
is always `self.view.transform`, and that transform's `t0_ns`/`n_samples`
come from `current_radargram()`, which already calls `stack.result()` (or
`stack.difference()`), not `stack.source`. So a `time_zero` ahead of a
`gain_curve` in the stack does *not* desync the strip's drawn axis from
`GainCurve.apply`'s own interpolation axis -- both already agree, because
both ultimately derive from the same post-crop radargram.

The place `stack.source` (the pre-crop axis) actually leaked in was
`ProcessingDock.time_axis()`, used *only* to seed a brand-new curve step's
identity default in `add_step_with_dialog` (`identity_curve(t0, dt, n)`).
When a `time_zero` step already precedes the point where a new `gain_curve`
is appended, the *input that step's own `apply()` will actually receive* is
`stack.result()` (the post-crop radargram), not `stack.source` (the raw
one) -- appending is always at the end of the stack, so `result()` before
the append *is* the new step's input. Seeding with the wrong (pre-crop) axis
doesn't corrupt the interpolated *values* here (both identity points are
0 dB, so `np.interp` returns flat 0 dB regardless of where the two knots
sit), but it is still wrong: the seeded points land at the wrong times, and
the strip (which draws them via the *correct* transform) would show them
off the visible time range instead of spanning it -- a real, if currently
cosmetic, bug, and one that stops being cosmetic the moment `identity_curve`
or a future curve seed ever needs anything other than "flat 0 dB everywhere".

**How I handled a raising `result()`:** `result()` raises `ValueError` when
*any* step already in the stack is misconfigured (a `bandpass` whose high
cut exceeds Nyquist, the same example `ProfileDock`'s own docstring uses).
That is a problem with that other step, not a reason `time_axis()` -- whose
only job is to seed a sensible default for a *new* step being added -- should
raise and block the user from adding anything at all. `time_axis()` catches
`ValueError` from `stack.result()` and falls back to `stack.source` (the
pre-fix behaviour), which is always available whenever profiles are loaded.

Tested in `test_plugin_param_form.py`:
- `test_time_axis_follows_a_preceding_step_that_changes_the_sample_axis`:
  appends `time_zero(mode="sample", sample=5)` (deterministic: crops
  exactly 5 rows regardless of data content) and asserts `time_axis()`
  returns `(source.t0_ns + 5*dt, dt, n_samples - 5)` -- computed
  independently of `time_axis()` itself, from `stack.source` directly, and
  explicitly asserts `t0 != source.t0_ns` so a reversion to the old,
  wrong behaviour is caught, not just "some axis, don't care which".
- `test_time_axis_falls_back_to_source_when_evaluating_the_stack_would_raise`:
  appends a `bandpass` with `high_mhz` above Nyquist, confirms
  `stack.result()` really does raise, then asserts `time_axis()` returns
  the raw source's axis without raising, and that `add_step_with_dialog`
  can still add a `gain_curve` afterwards.

**Reversion checks (both run, not just named):**
```
# lines 331-336 (verified by eye) reverted to:
#   if stack.source is not None:
#       return stack.source.t0_ns, stack.source.dt_ns, stack.source.n_samples
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py -q -p no:xonsh
```
```
FAILED test_time_axis_follows_a_preceding_step_that_changes_the_sample_axis
  assert 512 == (512 - 5)
1 failed, 23 passed
```
Only the intended test failed.

```
# lines 332-334 (verified by eye) reverted to a bare `rg = stack.result()`
# (no try/except)
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py -q -p no:xonsh
```
```
FAILED test_time_axis_falls_back_to_source_when_evaluating_the_stack_would_raise
  ValueError: high_mhz (5000.0) exceeds the Nyquist frequency (2309.1 MHz) ...
1 failed, 23 passed
```
Only the intended test failed. Both reverted from the same backed-up copy
(`cp` aside, restored from the copy -- never `git checkout --`).

## Two defects found in the brief's own verbatim test code

**1. `QTest.mouseMove` is not delivered while a button is logically held**
(already documented in this codebase, but not listed among this task's
hazards, and the brief's own `test_dragging_a_handle_moves_its_point_and_emits`
uses exactly the pattern that hazard warns against). Run as given, it fails:
`got[-1][1][1] == 20.0`, not `30.0` -- the drag never happened. Fixed by
reusing the exact bypass pattern `test_plugin_profile_view.py` already
established for the identical hazard (`_send_move_while_pressed`, sending a
real `QMouseEvent` via `QApplication.sendEvent` instead of `QTest.mouseMove`).

**2. `QTest.mouseDClick` corrupts offscreen-platform mouse state that
outlives the test.** Not previously documented anywhere in this codebase.
Isolated with a *minimal* `QWidget` completely outside `GainStrip`: a bare
`QTest.mouseDClick` on one widget in one test reliably blocks a plain,
buttonless `QTest.mouseMove` on a *different* widget in the *next* test --
`mouseMoveEvent` silently never fires. Neither `hide()`/`deleteLater()` on
the first widget nor an explicit forced `QMouseEvent(MouseButtonRelease,
Qt.NoButton)` afterwards cleared it. Concretely, running
`test_double_click_adds_and_right_click_removes` (as originally written,
using `QTest.mouseDClick`) before `test_plugin_profile_view.py` in the same
session made that file's
`test_mouse_move_emits_the_trace_under_the_cursor` fail every time,
regardless of the two tests' order relative to each other, purely because
my new test file collects alphabetically before it. Fixed the same way as
(1): a `_send_double_click` helper sends the same four events a real
double-click delivers (press, release, dblclick, release -- Qt turns the
*second* physical press into `MouseButtonDblClick`, not a second
`MouseButtonPress`) directly via `QApplication.sendEvent`, confirmed in the
same minimal reproduction to leave no trace. I also gave the `strip`
fixture proper `hide()`/`deleteLater()` teardown (it had none in the
brief), matching `test_plugin_profile_view.py`'s own documented
segfault-avoidance pattern for a parentless, shown top-level widget -- this
did *not* fix the `mouseDClick` interference (confirmed by testing it
separately) but is still the right thing to do for the segfault hazard
it's independently listed for.

Verified after the fix: `test_plugin_gain_strip.py` +
`test_plugin_profile_view.py` together, in both orders, and the full qgis
suite run twice back to back -- all green, exit code 0 both times (264,
then 266 once the two extra regression tests below were added).

## A third, more serious defect found (not in the brief's given code at all)

The brief's own constraints section warned: "your drag handler will be the
first external caller of `session.replace_step` on the current key+row...
verify your changes don't defeat [`ProcessingDock`'s identity guard], and
that a drag doesn't fight the form for the same step." Tracing this
carefully turned up a real bug the brief's pseudocode for `plugin.py` does
not guard against, between the strip and *itself*, not the form:

Every `points_changed` emitted mid-drag runs `_on_gain_points` ->
`session.replace_step` -> `stack_changed` -> `ProcessingDock.rebuild()` ->
`step_selected` -> `_sync_gain_strip` -> `show_gain_strip()` ->
`GainStrip.set_points()`. `set_points()` *re-sorts* the point list by time.
`GainStrip.mouseMoveEvent` tracks the dragged point by a fixed integer index
(`self._drag`) and deliberately does *not* re-sort mid-drag (only
`mouseReleaseEvent`/`mouseDoubleClickEvent` do) -- but the echo from my own
`_on_gain_points` call *does* resort, on every single mouse-move event. The
instant a dragged point's time crosses a neighbouring point's time, that
echoed resort silently remaps `self._drag`'s index onto the *neighbour*
instead of the point actually under the cursor; the next move then
overwrites the neighbour's (time, dB) instead of continuing to drag the
original point -- the neighbour's value is gone, not merely reordered.
Verified directly with a synthetic multi-step drag (points
`[[0,0],[50,10],[100,20]]`, dragging the middle point through
`t = 60, 80, 100, 120, 150`): without a guard, the final stored points were
`[[0,0],[119.6,10],[149.9,10]]` -- `(100, 20)` gone entirely, replaced by a
second copy of the dragged point.

**Fix:** `NsgeoPlugin` now tracks `(_gain_echo_pos, _gain_echo_step)` --
mirroring `ProcessingDock`'s own `_shown`/`_shown_step` pattern exactly
(set *before* `replace_step`, compared by `(key, row) ==` plus step
identity `is`, so only the *exact* object just written is recognised, never
a merely-similar one). `_sync_gain_strip` skips the resync when the step it
would show is that same echoed object. This does not "fight the form,"
because `gain_curve`'s only schema field is `points` (kind `curve`), so
`ParamForm` never calls `commit()` for it (its curve-kind editor is a
static `QLabel`, wired to no signal) -- the strip is the only writer for
this step, and the guard only ever suppresses its own echo.

While restructuring `_on_gain_points` to set the echo markers before
`replace_step`, I initially left `build_step(...)` *outside* the `try`
block (the brief's own version had it inside, as the direct argument to
`replace_step`) -- a real regression of my own, caught by adding
`test_plugin_reports_a_bad_curve_edit_instead_of_raising` (emits a
one-point payload directly through the public `points_changed` signal) and
confirmed by seeing the exact escaping-`ValueError` traceback the module's
own hazard note warns about, before moving `build_step` back inside the
`try`.

**Reversion checks (both run):**
```
# lines 289-290 (verified by eye) reverted to `if False: return`
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py -q -p no:xonsh
```
```
FAILED test_dragging_a_point_past_its_neighbour_does_not_corrupt_it
  AssertionError: the (100, 20) neighbour was corrupted:
  [[0.0, 0.0], [119.5751405443464, 10.0], [149.93075915745325, 10.0]]
1 failed, 5 passed
```
```
# build_step moved back outside the try (verified by eye)
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py -q -p no:xonsh
```
```
FAILED test_plugin_reports_a_bad_curve_edit_instead_of_raising
  assert (None is not None)
  [stderr] ValueError: gain_curve needs at least two control points
1 failed, 6 passed
```
Both reverted from a backed-up copy afterwards; both times only the
intended test failed.

## Every new test's kill-condition, run

| Test | Kill mutation | Run result |
|---|---|---|
| `test_mappings_round_trip` | `y_of_time` drops the `self._top` offset | 4 of 5 gain_strip tests failed (this is a foundational mapping method) |
| `test_dragging_a_handle_moves_its_point_and_emits` | `mouseMoveEvent`'s point-assignment line replaced with `pass` | only this test failed |
| `test_double_click_adds_and_right_click_removes` | right-click guard `len(self._points) > 2` dropped | only this test failed |
| `test_profile_dock_shows_the_strip_only_when_asked` + `test_plugin_routes_strip_edits_through_replace_step` | `show_gain_strip`'s `self.gain_strip.show()` replaced with `pass` | both failed (both exercise `show_gain_strip`) |
| `test_plugin_routes_strip_edits_through_replace_step` | `_on_gain_points`'s `session.replace_step(...)` replaced with `pass` | only this test failed |
| `test_time_axis_follows_a_preceding_step_that_changes_the_sample_axis` | `time_axis()` reverted to plain `stack.source` | only this test failed |
| `test_time_axis_falls_back_to_source_when_evaluating_the_stack_would_raise` | `try/except` around `stack.result()` removed | only this test failed |
| `test_dragging_a_point_past_its_neighbour_does_not_corrupt_it` | echo-guard condition replaced with `if False` | only this test failed |
| `test_plugin_reports_a_bad_curve_edit_instead_of_raising` | `build_step(...)` moved outside the `try` | only this test failed |

(The first mutation above -- `y_of_time` -- was checked once against the
whole gain_strip file rather than per-test, since it is exercised directly
or indirectly by nearly every test in that file; all other mutations were
checked individually.)

## Files changed

- `packages/nsgeo-qgis/nsgeo_qgis/ui/gain_strip.py` (new)
- `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`
- `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py`
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py` (new)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py`

No changes to `packages/nsgeo-core` (numpy-only constraint untouched). No
widening of `ALLOWED_FROM_PROCESSING` -- `build_step` was already allowed.

## Full verification (final run)

```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:xonsh
266 passed in 58.17s          # baseline 257 + 9 new tests; exit code 0, run twice, identical both times

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
334 passed, 2 skipped in 0.95s   # unchanged from baseline (no pure/core files touched)

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_boundary.py packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q
6 passed in 0.19s               # unchanged from baseline

.venv/bin/python -m ruff check .
All checks passed!

.venv/bin/python -m ruff format --check .
90 files already formatted      # baseline 88 + 2 new files, all clean

.venv/bin/python -m mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
Success: no issues found in 24 source files
```

## Self-review

**Completeness:** all six brief steps done; the axis decision explicitly
made and tested both ways (follows a preceding axis-changing step, falls
back cleanly when the stack can't evaluate). Edge cases covered: hiding on
row -1/out-of-range/non-curve step, never below two points, a degenerate
one-point payload arriving through the public signal without a UI path to
produce it.

**Quality:** the echo-guard and the `time_axis()` fallback both mirror an
already-reviewed pattern in this codebase (`ProcessingDock._shown`/
`_shown_step`, and `current_radargram()`'s own `ValueError` handling)
rather than inventing a new idiom. `gain_strip.py` otherwise matches the
brief verbatim except the documented `paintEvent` `try/finally` fix.

**Discipline:** no scope creep -- the drag-past-neighbour fix and its test
were necessary to satisfy the brief's own explicit warning about the drag
handler and the identity guard, not an invented enhancement. Did not touch
`nsgeo-core`. Did not widen the processing boundary allowlist.

**Testing:** every new test drives real Qt events (`QMouseEvent`s via
`QApplication.sendEvent`, or real signals via `.emit()`), not fabricated
calls into private slots. No test asserts an exact intermediate pixel
position that would reject a better implementation -- assertions are on
semantic outcomes (stored points, visibility, message text). Output is
clean: no stray Qt warnings observed in any of the runs above beyond the
pre-existing, benign `"This plugin does not support propagateSizeHints()"`
line QGIS itself prints for `QgsDockWidget`, which appears throughout the
existing suite already and is unrelated to this task.

## Concerns

- The `mouseDClick` offscreen-platform corruption (finding 2) is now worked
  around in this one file, but nothing stops a *future* test elsewhere in
  this suite from calling `QTest.mouseDClick` directly and reintroducing
  the same cross-file hazard. It might be worth a repo-wide note (or a
  lint/grep-based check) that `QTest.mouseDClick` is unsafe in this
  environment, the same way `QTest.mouseMove`-while-pressed already has one
  in `test_plugin_profile_view.py` -- I did not add one outside this file's
  own scope, since that felt like widening beyond what Task 18 asked for.
- `_on_gain_points` re-reads `entries[row][0]` fresh on every call rather
  than trusting any cached reference, so a same-row/different-step race is
  not possible by construction; I did not add a synthetic test for "select
  a different line mid-drag" since a drag is a single, uninterruptible
  mouse gesture and QGIS gives no way to switch lines without releasing
  the mouse first.

---

# Fix round 1

Review came back **1 Critical, 2 Important, 7 Minor**. Every item addressed
below. Two of the round-0 calls were independently re-verified by the
reviewer and held up: the neighbour-corruption numbers reproduced to the
digit, and the axis decision was judged correct (with the added detail that
`time_zero` preserves absolute time, so only the seed's *span* was ever
wrong).

## Critical 1 — echo guard hid the strip forever after one edit

**Root cause.** The round-0 fix (a plugin-level `_gain_echo_pos`/
`_gain_echo_step` marker, set in `_on_gain_points` before `replace_step`)
was compared unconditionally in `_sync_gain_strip`, not only while a drag
was actually live. After any edit, the marker kept pointing at that exact
step object; a genuine reselection of the *same, unchanged* step later
(e.g. select another row, then come back) still matched the stale marker
and was wrongly treated as an echo, so `show_gain_strip` was never called
again. Reproduced exactly as the reviewer's probe showed:
```
after selecting gain row, hidden = False
after edit, stored points: [[-11.0, 0.0], [50.0, 6.0], [99.0, 0.0]]
after selecting dewow row, hidden = True
BACK on the gain row, hidden = True    <-- expected False
```

**Fix taken: the better one, not the minimal one.** Per the review's
instruction, I did not patch the marker's write sites; I retired the whole
marker pair and moved the invariant onto the widget itself:
`GainStrip.set_points` (`gain_strip.py`) now returns immediately if
`self._drag is not None` — the *only* time an external resync was ever
unsafe, since that's the one window where `mouseMoveEvent` tracks the
dragged point by a fixed index that a re-sort (which `set_points` always
does) can silently remap onto a neighbour. `_sync_gain_strip` and
`_on_gain_points` in `plugin.py` are back to their simplest form: no
markers, resync unconditionally on every real `step_selected`. This also
directly fixes the original neighbour-corruption bug (mid-drag echoes now
simply can't touch `_points` at all, rather than being merely
"recognised" and skipped by an out-of-band marker) and covers resyncs a
plugin-level marker could never recognise (a line switch, an undo, any
future caller of `show_gain_strip`), exactly as the review argued.

New regression test: `test_reselecting_a_curve_row_after_an_edit_still_shows_the_strip`.

## Important 2 — unclamped drag, range derived from the point being dragged

Two related defects, both in `gain_strip.py`:

1. **Runaway gain.** `_db_range()` was `(min(-6, min(dbs)-6), max(24,
   max(dbs)+6))` — a function of the value the *previous* move just wrote.
   Qt's implicit mouse grab keeps delivering moves to the widget that
   started the drag even once the cursor leaves it (ordinary on a 96px
   strip), so every out-of-bounds move fed the growing `hi` straight back
   into the next move's range: a feedback loop. Reproduced directly with a
   widget-level test: parking the cursor ~100px right of the strip and
   repeating the same one-pixel move ran the gain from ~26 dB into the
   hundreds within a handful of moves before the fix (confirmed via the
   reversion below), matching the review's own account of an unbounded
   runaway into the millions given enough moves. `GainCurve.apply` computes
   `10 ** (db/20)`, which overflows to `inf` once `db` reaches the
   thousands, so an unlucky drag could write an all-`inf` radargram into
   the session and (on save) the project file.

   **Fix:** `_drag_db_range`, set to the current `_db_range()` on
   `mousePressEvent` (only when the press hit a handle) and cleared on
   `mouseReleaseEvent`; `_db_range()` returns it when set. The range is now
   frozen for the whole gesture, so every out-of-bounds move maps to the
   *same* bounded value (the frozen `hi`), not a growing one.

2. **Position never clamped.** Both the db-range feedback loop above and a
   dragged handle vanishing off-widget (unreachable to `handle_at`
   afterwards, hence neither re-draggable nor right-click-removable) share
   the same missing guard: the raw event position was used directly.
   Added `_clamped(pos)`, used in both `mouseMoveEvent` and
   `mouseDoubleClickEvent`, clamping `x` into `[PAD_X, width - PAD_X]` (the
   same domain `x_of_db`/`db_of_x` already use) and `y` into `[top, top +
   transform.height]`.

   **A real bug found while building this fix, not just the one the
   review named:** my first attempt clamped `y` into `[0, self.height()]`
   (the widget's own raw Qt pixel height) — which broke a *pre-existing*
   test (`test_dragging_a_point_past_its_neighbour_does_not_corrupt_it`,
   built through the full plugin with `fake_iface`'s unshown main window)
   because `GainStrip.height()` (30px, its unlaid-out default) and
   `self._transform.height` (84px, the real conceptual viewport) disagreed
   — `y_of_time`/`time_of_y` only ever reference the latter, never the
   widget's actual Qt size. Clamping against the wrong one silently mapped
   a legitimate drag position (t=150) down to a nonsense time (~18ns)
   instead of merely bounding it. Fixed by clamping against
   `self._transform.height` (what the coordinate functions actually use),
   not `self.height()`.

   That same height mismatch also forced two test adjustments, both
   argued in their own comments: the brief's original drag target (30.0
   dB against this fixture's frozen (-6, 26) range) is now correctly out
   of range and clamped to 26.0, so I moved it to 24.0; and the
   neighbour-corruption test's control points ([0, 50, 100]) had their top
   end sitting right at (very slightly past) the real line's own
   `time_hi` (~99.78ns), so a "drag past the neighbour" no longer meant
   anything once clamped to the axis — I moved the points to [0, 30, 60],
   comfortably inside the line's real time range.

New regression tests: `test_drag_overshoot_is_clamped_and_the_range_does_not_ratchet`,
`test_drag_above_the_strip_keeps_the_handle_reachable`.

## Important 3 — a drag is not an uninterruptible gesture

Qt's implicit mouse grab only constrains *mouse* events; keyboard, timers,
and `QgsTask` completions (`LineLoader.finished` → `set_profiles`/
`open_line`) still run during a drag. Per the review's own scoped remedy
("Critical 1's widget invariant plus a `self._drag < len(self._points)`
check... write [the test] at widget level"), I implemented exactly that,
no more:

- Critical 1's `set_points` guard already closes the "an external caller
  replaces `_points` mid-drag" route entirely (nothing but `set_points`
  changes `_points`, and it now refuses to while dragging).
- Added a defensive `self._drag >= len(self._points)` bounds check at the
  top of `mouseMoveEvent`: if the index a drag started with is no longer
  valid (a future caller reaching `_points` directly, bypassing
  `set_points`), the gesture aborts (`self._drag = None`) instead of
  raising `IndexError` inside a slot nothing would see fail.

New regression test: `test_a_shrunk_point_list_mid_drag_does_not_raise` —
built at the widget level as instructed (shrinks `strip._points` directly
to simulate the hypothetical external caller, no plugin needed).

## Minors

- **m1 — no-op guard.** `_on_gain_points` now compares the rebuilt
  `params` dict against `step.params` and returns early if unchanged,
  mirroring `ProcessingDock._on_form_committed`'s own `current.params ==
  params` guard. A plain click on a handle (press+release, no move) no
  longer dirties the session. New test:
  `test_clicking_a_handle_without_moving_it_does_not_edit_the_step`.
- **m2 — silent fallback logged.** `ProcessingDock.time_axis()`'s
  `ValueError` fallback now calls `_log(...)` (imported from
  `nsgeo_qgis.log`) naming the axis it fell back to. New test:
  `test_time_axis_logs_when_it_falls_back_to_source` (added a
  `message_log` fixture to `test_plugin_param_form.py`, mirroring the
  identical fixture already duplicated in three other test files).
- **m3 — deduplicated `_send_move_while_pressed`.** Moved to
  `packages/nsgeo-qgis/tests/plugin_testing.py` as
  `send_move_while_pressed`, with its Qt imports kept *local to the
  function* (not module-level) since `plugin_testing.py` is also imported
  by the pure tier's `test_pure_lookup.py`, which has no QGIS/PyQt
  installed. Both `test_plugin_profile_view.py` and
  `test_plugin_gain_strip.py` now import it aliased back to
  `_send_move_while_pressed` (zero call-site changes in the former, which
  has several). `_send_double_click` was *not* moved — the review named
  only the move-while-pressed duplicate; it isn't duplicated anywhere.
- **m4 — `QTest.mouseDClick` forbidden repo-wide.** Added to
  `conftest.py`'s `_no_unhandled_modals` fixture (the same
  make-it-unrepresentable idiom it already uses for a real modal): calling
  `QTest.mouseDClick` anywhere in this tier now raises `AssertionError`
  pointing at `_send_double_click`. New test:
  `test_qtest_mousedclick_is_forbidden_in_this_tier`.
- **m5 — `assert` replaced with `_update_enabled`'s None-guard pattern.**
  Both `_sync_gain_strip` and `_on_gain_points` now `return` quietly if
  `self.session`/the relevant dock is `None`, instead of asserting. New
  test: `test_gain_strip_slots_do_not_raise_after_unload` — calls the two
  slots directly after `unload()`, since unload() itself removes the only
  things (the docks) that could deliver a *real* signal here, leaving
  nothing to drive by the time the guard needs probing.
- **m6 — strip now re-syncs on `line_loaded`.** `NsgeoPlugin` connects
  `session.line_loaded` to a new `_resync_gain_strip(key)`, which re-runs
  `_sync_gain_strip(processing_dock.current_row())` when `key` matches the
  current line. This is the one render-triggering signal `ProcessingDock`
  never reacted to, so a strip `_sync_gain_strip` had hidden for want of a
  transform previously had no way to reappear once one arrived through
  *this* channel specifically.

  **Honesty about the test:** I could not reliably reproduce, through the
  full plugin, an end-to-end sequence where `view.transform` is actually
  `None` while a curve row is already selected. `ProfileDock._open`'s
  header-only branch (taken whenever profiles aren't loaded yet) sets a
  valid transform from the DZT header *unconditionally*, before any
  profile ever loads, and dock construction order in `plugin.py`
  (`ProfileDock` before `ProcessingDock`) guarantees `ProfileDock`'s own
  reaction to `line_opened` always runs before `ProcessingDock`'s
  `step_selected` re-emission reaches `_sync_gain_strip`. The one path I
  found that genuinely produces a null transform (a misconfigured step
  ahead of the curve step, evaluated on the very first render) turned out
  to *self-heal* regardless of this fix, because fixing that step also
  fires `stack_changed`, which `ProcessingDock` does react to. Rather than
  keep chasing a race that may not be reachable against today's code, the
  test constructs the documented failure condition directly
  (`ProfileDock.view.clear()` — the same public reset
  `_clear_view_only` itself uses) and drives the real recovery signal
  (`session.set_profiles`) to confirm the new wiring does what it's
  supposed to. This is flagged plainly in the test's own docstring, not
  hidden.

## Reversion checks (fix round 1) — all run, all killed only the intended test

Each mutation applied to a **backed-up copy**, restored from that copy
afterward (never `git checkout --`), targeting lines verified by eye
immediately before mutating.

| Fix | Mutation | Result |
|---|---|---|
| Critical 1 (`set_points` drag guard) | `if self._drag is not None: return` → no-op | `test_dragging_a_point_past_its_neighbour_does_not_corrupt_it` failed (neighbour corrupted again); `test_reselecting_a_curve_row_after_an_edit_still_shows_the_strip` still passed (that bug's root cause was the removed marker, not this guard) — both correct |
| Important 2a (frozen `_drag_db_range`) | never freeze (`_drag_db_range = None` always) | only `test_drag_overshoot_is_clamped_and_the_range_does_not_ratchet` failed (`26.0 == 140.0`) |
| Important 2b (`_clamped` position clamp) | `_clamped` returns raw `(pos.x(), pos.y())` | both `test_drag_overshoot_is_clamped_and_the_range_does_not_ratchet` (`103.9 == 26.0 ± 2.6e-05`) and `test_drag_above_the_strip_keeps_the_handle_reachable` failed; nothing else did |
| Important 3 (`self._drag >= len(self._points)`) | check disabled | only `test_a_shrunk_point_list_mid_drag_does_not_raise` failed, with the exact `IndexError: list assignment index out of range` the fix guards against visible in stderr |
| m1 (no-op guard) | `if step.params == params: return` → no-op | only `test_clicking_a_handle_without_moving_it_does_not_edit_the_step` failed (step object identity changed) |
| m2 (`_log` on fallback) | `except ValueError as exc: _log(...)` → bare `except ValueError:` | only `test_time_axis_logs_when_it_falls_back_to_source` failed |
| m4 (`mouseDClick` forbid) | `_forbid(QTest, "mouseDClick", ...)` call removed | only `test_qtest_mousedclick_is_forbidden_in_this_tier` failed (`DID NOT RAISE AssertionError`) |
| m5 (None-guard vs `assert`) | both guards reverted to `assert ... is not None` | only `test_gain_strip_slots_do_not_raise_after_unload` failed, with a real `AssertionError` at the reverted line |
| m6 (`line_loaded` connection) | `self.session.line_loaded.connect(...)` line removed | only `test_a_strip_hidden_for_want_of_a_transform_reappears_once_profiles_load` failed |

m3 (dedup) has no behavioural reversion — it's a pure refactor; both test
files' full suites passing identically before and after is the evidence.

## Full verification (fix round 1, final run)

```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:xonsh
275 passed in 62.02s      # baseline (round 0) 266 + 9 new tests; run twice, identical both times, exit 0

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
334 passed, 2 skipped in 1.06s   # unchanged from baseline

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_boundary.py packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q
6 passed in 0.19s                # unchanged from baseline

.venv/bin/python -m ruff check .
All checks passed!

.venv/bin/python -m ruff format --check .
90 files already formatted        # same count as round 0 (no new files this round)

.venv/bin/python -m mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
Success: no issues found in 24 source files
```

## Files changed (fix round 1)

- `packages/nsgeo-qgis/nsgeo_qgis/ui/gain_strip.py` — drag invariants
  (`set_points` guard, frozen `_drag_db_range`, `_clamped`, bounds check)
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` — echo markers retired,
  `_resync_gain_strip` added, None-guards, no-op guard
- `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py` — logs the
  `time_axis()` fallback
- `packages/nsgeo-qgis/tests/plugin_testing.py` — new shared
  `send_move_while_pressed`
- `packages/nsgeo-qgis/tests/qgis/conftest.py` — `QTest.mouseDClick`
  forbidden
- `packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py` — 9 new
  tests, 2 pre-existing tests adjusted for the new clamped/frozen
  behaviour (both changes argued in their own comments)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py` — new
  `message_log` fixture + 1 new test
- `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py` — local
  `_send_move_while_pressed` replaced with the shared import (no
  call-site changes)

No changes to `packages/nsgeo-core`. No further widening of
`ALLOWED_FROM_PROCESSING`.

## Self-review (fix round 1)

**Completeness:** all 1+2+7 = 10 findings addressed, each with its own
test and a run reversion.

**Quality:** Critical 1's fix follows the review's explicit instruction to
take the structural fix over the patch; Important 2's fix was itself
caught mid-implementation making a second, related mistake (clamping
against the wrong height), which I found and fixed the same way the task
asks me to find things — by running the test, not by inspection alone.

**Discipline:** m6's fix is exactly what the review asked for, not more;
I did not chase a wider "harden every render path" refactor. I was
explicit in the test's own docstring about not being able to reproduce
the underlying race end-to-end, rather than presenting a contrived setup
as if it were the real thing.

**Testing:** every new test drives a real signal or a real Qt event,
except `test_gain_strip_slots_do_not_raise_after_unload`, which calls two
slots directly — justified in its own docstring, since `unload()` removes
the only real emitters that could reach them.

## Concerns carried forward

- Same as round 0: nothing stops a *future* test elsewhere in this suite
  from reintroducing the `QTest.mouseDClick` hazard by accident — mitigated
  now by m4's repo-wide guard, so this concern is resolved, not just noted.
- m6's test constructs its precondition directly rather than through an
  organic race (see that section's "Honesty about the test" above) — flagged
  for the next reviewer's attention specifically, in case a cleaner
  end-to-end repro exists that I didn't find.

---

# Fix round 2

Re-review of round 1 came back **all 10 findings addressed, no new
Critical/Important breakage**, with two things independently re-verified
(the `y` clamp's use of `_transform.height`, `GainCurve.params`'s fresh
list-of-lists backing m1's comparison) and one limitation of my own m6 test
found and correctly credited as "the honest choice" rather than a shortcut
(it pins `ProfileDock`'s `line_loaded` connection ordering ahead of
`plugin.py:156`'s).

Round 2 itself: **one Important** (a silent data-modification path the
reviewer traced end-to-end and reproduced, chaining a round-1 finding with a
pre-existing, previously out-of-scope one) plus **five Minor** items. All
six addressed below; Task 18 closes with no further review after this round.

## Important — stranded `_drag` + a buttonless hover silently edits the gain curve

**The chain, reproduced exactly as the review described it.** Nothing
delivers `mouseReleaseEvent` to a widget hidden mid-drag (a line load
completing, or an arrow-key row change stealing focus — `GainStrip` sets no
focus policy, so the processing list keeps focus during a strip drag
regardless). This predates round 1; round 1's own `set_points` refusal
(Critical 1's fix) made the consequence *sticky*: once `_drag` is stranded,
every later external resync is refused forever, not merely skipped once.
Worse, `mouseMoveEvent` guarded only `_drag is None`, never whether a
button was actually held — so a plain, buttonless hover across the strip
afterwards silently rewrote the stranded index's point and emitted
`points_changed`, which `plugin.py` routes straight into
`session.replace_step`: a hover edits the user's gain curve and dirties the
project, with nothing on screen suggesting anything happened.

**Fix, exactly as specified, two independent barriers:**

1. `GainStrip.hideEvent` now clears `_drag` and `_drag_db_range` itself —
   the widget-local-invariant policy Critical 1 already established in this
   module, applied to a third gap in it.
2. `mouseMoveEvent` now returns immediately if `not event.buttons()`, before
   even checking `_drag`. Kept as a second barrier even though (1) alone
   would suffice for the reproduced chain, because the failure is silent:
   a loud bug is worth fixing once, a silent one is worth two independent
   barriers against (so a stranding path this file didn't anticipate still
   can't reach the silent edit).

New regression tests: `test_hiding_mid_drag_ends_the_gesture` (press, hide,
confirm `_drag`/`_drag_db_range` are `None` and a subsequent `set_points` is
honoured) and `test_a_buttonless_move_never_edits_a_stranded_drag` (forces
`_drag` to a stranded index directly, sends a buttonless move via
`plugin_testing.send_move_while_pressed(..., held_button=Qt.MouseButton.
NoButton)`, confirms neither the point nor `points_changed` fire).

**A test bug I found building the first of these, the same way this task
keeps finding them: by running it, not by inspecting it.** My first version
of `test_hiding_mid_drag_ends_the_gesture` pressed the handle, hid the
widget, asserted, and stopped — no matching release. That left Qt's own
mouse grab unbalanced exactly the way `QTest.mouseDClick` did in round 1
(same mechanism, different trigger): running the full qgis tier surfaced
`test_plugin_profile_view.py::test_mouse_move_emits_the_trace_under_the_
cursor` failing again, in a different file, for the identical reason.
Confirmed directly that `QTest.mouseRelease` sent to an already-hidden
widget still reaches Qt's own bookkeeping (the widget's own
`mouseReleaseEvent` finds `_drag` already `None` by then and does nothing
with it, which is fine — the release is there purely to balance Qt, not to
exercise the widget). Added it; the full-suite failure disappeared and
stayed gone.

## Minors

- **Item 3 — `mouseDoubleClickEvent` now clears `_drag_db_range` too**, not
  just `_drag`, matching `mouseMoveEvent`'s bounds-check branch and
  `mouseReleaseEvent`. Confirmed genuinely unreachable through real Qt
  sequencing, not just asserted: my first test routed a stale value through
  `plugin_testing.send_double_click`, whose own leading `MouseButtonPress`
  (hitting no handle at the test's `mid`) resets `_drag_db_range` to `None`
  itself before `mouseDoubleClickEvent` ever runs — a reversion of the fix
  still passed 18/18 with that version, silently pinning nothing (see the
  reversion table). Rewrote it to send a bare `MouseButtonDblClick` event
  directly, with no preceding press, isolating `mouseDoubleClickEvent`'s own
  clearing from that unrelated reset; the same reversion then correctly
  failed exactly that one test.
- **Item 4 — `test_drag_above_the_strip_keeps_the_handle_reachable`
  reworked.** It used to assert `handle_at(QPoint(x, 0))`, which passed only
  because this fixture's 8px `MARGIN_TOP` gap is smaller than `handle_at`'s
  own `HIT_RADIUS + 1.0` (9px) slack — coincidental, and would break if
  `MARGIN_TOP` ever changed, for a reason unrelated to clamping. Reworked to
  (a) drag handle 1 (`t=100`, this fixture's own `time_hi`) instead of
  handle 0 (already at `time_lo`, where "dragged past the top" and "left
  alone" look identical — not a real test of the fix) and (b) assert
  directly against the stored point (clamped to `time_lo`, db unchanged),
  with `handle_at` kept as a second, now-correctly-targeted check using the
  real clamped position rather than a magic `0`.
- **Item 5 — `_send_double_click` moved to `plugin_testing.py`** as
  `send_double_click`, Qt imports kept function-local (same reasoning as
  `send_move_while_pressed`: this module is also imported by the pure
  tier). `test_plugin_gain_strip.py` imports it aliased back to
  `_send_double_click` (no call-site changes). `conftest.py`'s forbid
  message and docstring now point at the importable name.
- **Item 6 — the fourth `message_log` fixture consolidated.** Moved into
  `tests/qgis/conftest.py` (the same place `fake_iface`/`answer_modal`
  already live, available to every test in the tier with no import), and
  removed from `test_plugin_layers.py`, `test_plugin_profile_view.py`,
  `test_plugin_profile_dock.py`, and `test_plugin_param_form.py`. Also
  removed the now-unused module-level `QgsApplication` import from
  `test_plugin_layers.py` (the other three imported it locally inside the
  fixture, so removing the fixture removed the import with it).

## Reversion checks (fix round 2) — all run, all killed only the intended test

| Fix | Mutation | Result |
|---|---|---|
| `hideEvent` clears drag state | body replaced with `pass` | only `test_hiding_mid_drag_ends_the_gesture` failed (`assert 1 is None`) |
| `mouseMoveEvent`'s buttons check | `if not event.buttons(): return` disabled | only `test_a_buttonless_move_never_edits_a_stranded_drag` failed, showing the exact silent rewrite (`[30.0, 4.95...]` in place of the untouched point) |
| Item 3 (`mouseDoubleClickEvent` clears `_drag_db_range`) | line removed | **first test version: 18/18 still passed — caught before this report, not by the reviewer** (see "Minors" above); rewritten test correctly failed alone once isolated from the unrelated press-triggered reset |
| Item 4 rework | (test-only change; re-ran the existing `_clamped`-disabled mutation from round 1 against the rewritten assertions) | both `test_drag_overshoot_is_clamped_and_the_range_does_not_ratchet` and `test_drag_above_the_strip_keeps_the_handle_reachable` failed, nothing else did |

Items 5 and 6 are pure refactors (moved code, no behaviour change); the
full suite passing identically before and after is the evidence, same as
round 1's m3.

## Full verification (fix round 2, final run)

```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:xonsh
278 passed in 62.22s      # round 1's 275 + 3 new tests; run twice, identical both times, exit 0

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
334 passed, 2 skipped in 0.96s   # unchanged from baseline

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_boundary.py packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q
6 passed in 0.18s                # unchanged from baseline

.venv/bin/python -m ruff check .
All checks passed!

.venv/bin/python -m ruff format --check .
90 files already formatted        # same count as round 1 (no new files this round)

.venv/bin/python -m mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
Success: no issues found in 24 source files
```

## Files changed (fix round 2)

- `packages/nsgeo-qgis/nsgeo_qgis/ui/gain_strip.py` — `hideEvent`, the
  buttonless-move guard, `mouseDoubleClickEvent`'s `_drag_db_range` clear
- `packages/nsgeo-qgis/tests/plugin_testing.py` — `send_double_click` added
  (moved from `test_plugin_gain_strip.py`)
- `packages/nsgeo-qgis/tests/qgis/conftest.py` — `message_log` fixture
  added (consolidated from four files); forbid message/docstring updated
- `packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py` — 3 new
  tests, one test rewritten (item 4), `_send_double_click` now imported
  rather than defined locally
- `packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py`,
  `test_plugin_profile_view.py`, `test_plugin_profile_dock.py`,
  `test_plugin_param_form.py` — duplicate `message_log` fixtures removed
  (plus the now-unused `QgsApplication` import in `test_plugin_layers.py`)

No changes to `packages/nsgeo-core`. No further widening of
`ALLOWED_FROM_PROCESSING`.

## Self-review (fix round 2)

**Completeness:** all 1 Important + 5 Minor addressed, each with a test
(where the review asked for one) and a run reversion.

**Quality:** found and fixed a genuine test-quality defect in my own work
this round (item 3's first version pinning nothing) before it could reach
review, by actually running the reversion rather than trusting the
mutation's plausibility — which is exactly the discipline this task's
brief asks for and exactly the mistake it warned a past round made ("a
named reversion is a hypothesis; only a run one is evidence").

**Discipline:** did not touch the parked item (the module docstring's
broad try/except policy for `_sync_gain_strip`/`_resync_gain_strip`/
`_on_gain_points`) — explicitly deferred by the reviewer for a proper sweep
later, not three point patches now.

**Testing:** every new/changed test drives a real Qt event or a real
widget state transition (`hide()`, a forced buttonless move via the shared
helper, a bare `MouseButtonDblClick` sent directly) — no test in this round
calls a private method with fabricated arguments to skip the real
mechanism.

## Concerns

None carried forward. The `QTest.mouseDClick` cross-test hazard (round 1)
and its cousin found this round (an unbalanced press-without-release doing
the same thing) are both now understood, fixed, and — for the `mouseDClick`
half — made structurally unrepresentable via `conftest.py`. m6's test
precondition limitation (flagged in round 1) stands as noted there; nothing
in round 2 changed it.
