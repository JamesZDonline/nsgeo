# M7 final review — fix wave report

Verdict going in: no Critical findings, "ready to merge." This closes the four
polish items (Finding 5 is explicitly out of scope, per the brief).

## Finding 1 — a preview sticks when the pointer leaves the canvas

**Fix.** `MapLink.__init__` now installs `self` as an event filter on
`canvas.viewport()`. The new `eventFilter()` method (in `map_link.py`, next to
`_on_dwell`) clears the preview and stops the dwell on `QEvent.Type.Leave`,
guards its own body in a `try`/`except` reporting through `_log` (like every
other slot in the module), and always returns `False` so the event still
reaches its normal handler. `dispose()` removes the filter with the exact same
`sip.isdeleted`/`contextlib.suppress(TypeError, RuntimeError)` treatment
already used for the `xyCoordinates` disconnect, inserted as one more
statement in the same `if not canvas_gone:` block — nothing above the
scene-removal loop was restructured.

**Experiment 1 — which object receives `Leave`.** Built two standalone
reproductions (offscreen Qt, no pytest) rather than assuming:
- A bare `QgsMapCanvas` inside a plain host widget, moving the mouse in with
  `QTest.mouseMove` then out past the host's own bounds.
- A `QMainWindow` with the canvas as central widget and a `QDockWidget` as a
  sibling (mirroring "hover a line, then move to the processing dock"
  exactly), moving the mouse from the canvas center into the dock's label via
  `QTest.mouseMove` + `mapToGlobal`.

Both experiments agree: **both `canvas` and `canvas.viewport()` receive a
real `Enter`/`Leave` pair**, in `Enter: canvas → viewport`, `Leave: viewport →
canvas` order — Qt's `dispatchEnterLeave` walks the whole ancestor chain
between the old and new "under the pointer" leaf, not just the leaf, so the
container is not skipped. The filter is still installed on `canvas.viewport()`
specifically, not because `canvas` misses the event, but because
`canvas.viewport()` is inset from `canvas`'s own rect by a 1px frame
(measured directly: canvas `511×400`, viewport at `(1,1)` sized `509×398`) and
is the object whose own mouse tracking backs `xyCoordinates` — watching it
means "left" fires in the same instant `xyCoordinates` stops producing
positions, with no gap where the pointer sits in that 1px frame margin.

**Experiment 2 — the queued dwell.** Confirmed via the new
`test_the_pointer_leaving_the_canvas_stops_the_pending_dwell`: arm the dwell,
send `Leave`, assert `not link._dwell.isActive()`, then manually fire
`link._dwell.timeout.emit()` (simulating an emission already queued before
the leave landed) and assert the preview stays cleared. `eventFilter` calls
`self._dwell.stop()` before `clear_preview()`, which is sufficient — `QTimer.stop()`
in this codebase is already relied on elsewhere (`dispose()`) to guarantee no
further `timeout` fires from the same timer instance.

Added to `test_plugin_map_link.py`: `test_the_pointer_leaving_the_canvas_clears_an_active_preview`,
`test_the_pointer_leaving_the_canvas_stops_the_pending_dwell`,
`test_leaving_the_canvas_with_no_preview_up_is_a_silent_no_op`,
`test_a_disposed_link_no_longer_clears_the_preview_on_leave`,
`test_a_disposed_link_still_removes_the_leave_filter_when_the_canvas_is_gone`.

## Finding 2 — `remove_line` of the current line while previewing another

**Read both sides first, as asked.** `session.py`'s `remove_line` resets only
the dropped key's own `_current_key`/`_preview_key` fields, and always emits
`line_opened("")` before `preview_changed` when the current line is dropped.
`profile_dock.py`'s `_open("")` (the slot `line_opened` drives) dropped
`self._preview_key` unconditionally.

**Choice: narrow fix, not a mirroring refactor.** I did not remove the dock's
own `_preview_key`/`_working_key` mirror. Doing that properly would mean
`ProfileDock._key` reading `self.session.preview_key`/`current_key` directly
everywhere, and re-auditing every one of the (many) preview-state guards in
this file that currently compare against the dock's own copies —
substantially more than a final-review polish item, and the brief explicitly
says not to attempt that here. Instead, `_open` now computes
`still_previewing = not key and self.session.is_open and self.session.preview_key is not None`
and, when true, skips clearing `_preview_key`/`preview_label`/`channel_combo`
and returns without calling `_clear_view_only()` — the view is already
showing exactly the surviving preview, untouched. This is safe because every
*other* caller of `line_opened` (`open_line`, and `remove_line` itself when
the removed line IS the preview) has already reset `session.preview_key` to
`None` before emitting, so `still_previewing` is only ever true in the one
case Finding 2 describes.

Added `test_removing_the_current_line_while_previewing_another_keeps_the_dock_in_sync`
to `test_plugin_profile_dock.py`: preview line B, `remove_line(A)`, assert
`session.display_key == dock._key == keys[1]` and the banner is still showing.

## Finding 3 — a false comment

Corrected the comment in `map_link.py`'s `_refresh()` (previously claiming
`MapLink` and `ProfileDock` "must agree" on `preview_key == current_key`).
No behaviour change. The new comment states the two deliberately diverge
here — `_refresh()` draws the marker at `preview_trace`, `ProfileDock._exit_preview()`
leaves the cursor at `current_trace` — and that the divergence is unreachable
from the hover path (`_on_dwell` never calls `set_preview(current_key, ...)`;
it always routes that case through `clear_preview()` + `set_trace()`), so it
can only be triggered by a caller invoking `session.set_preview(current_key, ...)`
directly, which nothing in the plugin does today.

## Finding 4 — a preview leaves a trace in saved state

**Read `stack_for` first, as asked**, then verified the actual insertion
point empirically rather than trusting the finding's literal attribution.
Two standalone reproductions:

1. Reproduced the `previewing` test fixture's own setup (both lines loaded
   via `set_profiles` up front) and printed `site.stacks` after each step:
   `set_profiles` — not `current_radargram`/`stack_for(preview_key)` — is
   what inserts the entry, immediately, for *either* line, regardless of
   preview.
2. Reproduced the realistic production sequence instead (only line A loaded;
   line B previewed *before* its data ever loads, matching a genuine
   hover-triggered `LineLoader` background load): hovering B alone inserts
   nothing (`_show_line` takes its axes-only branch while `profiles_for(B)`
   is still `None`, so `_render()`/`current_radargram()` never runs); the
   entry appears at the exact moment `session.set_profiles(B, ...)` is
   called — i.e. `SiteSession.set_profiles`'s own `stack_for(key)` call, not
   `ProfileDock.current_radargram`'s.

**Judgement: the fix has to cover both call sites, or it does nothing.**
The finding named `current_radargram → stack_for(preview_key)`, but by the
time that call ever runs, `set_profiles` has already run for the same key
(every path into `_render()` requires `profiles_for(key)` to be truthy,
which only `set_profiles` sets, and `set_profiles` always calls `stack_for`
first) — so a fix scoped only to `current_radargram` would be provably inert
against the actual reported symptom. Extending it to `set_profiles` was a
straightforward addition, not a contract complication: `stack_for` gained a
keyword-only `insert: bool = True` parameter (zero behaviour change for every
other caller — `append_step` and siblings never pass it), and `set_profiles`
computes `insert = key == self._current_key or key != self._preview_key`
using state `SiteSession` already owns. `ProfileDock.current_radargram` uses
`insert=self._preview_key is None`. Both together mean a bare preview (not
also the current line) never plants an entry in `site.stacks`, and the very
next real `stack_for()` call once the line is promoted or edited creates it
normally — spec §3.3's claim is now literally true, not just documented as
close enough.

Added to `test_plugin_session.py`: `test_stack_for_with_insert_false_builds_without_storing`,
`test_set_profiles_on_a_preview_only_key_does_not_persist_an_empty_stack`,
`test_set_profiles_on_the_current_line_still_persists_its_stack` (regression
guard for the unchanged ordinary case). Added to `test_plugin_profile_dock.py`:
`test_a_preview_that_triggers_a_load_does_not_persist_an_empty_stack`
(end-to-end, via the real `_show_line`/`_on_line_loaded` path, not just the
session API).

## Not in scope

Finding 5 (`-p no:xonsh` in the plan document) — untouched, per the brief:
already closed by the Global Constraints section of the plan document.

## Red-before-green evidence

Isolated the three source files' diff into a patch
(`git diff -- map_link.py session.py profile_dock.py`), applied `git apply -R`
to revert just the source (keeping the new tests), ran the new tests, saw
them fail, then reapplied the patch (`git apply`, confirmed byte-identical to
the reverted patch via `diff`) and reran to green:

```
$ QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest \
    packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py -k "leaving_the_canvas or leave" -q -p no:xonsh
FF...
2 failed, 3 passed, 34 deselected in 6.30s
# (the 2 failures: test_the_pointer_leaving_the_canvas_clears_an_active_preview,
#  test_the_pointer_leaving_the_canvas_stops_the_pending_dwell — the other 3 pass
#  either way, as expected for a no-op-with-no-preview / dispose-robustness check)

$ QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest \
    packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py \
    -k "removing_the_current_line_while_previewing or preview_that_triggers_a_load" -q -p no:xonsh
FF
2 failed, 42 deselected in 0.98s

$ QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest \
    packages/nsgeo-qgis/tests/qgis/test_plugin_session.py \
    -k "insert_false or preview_only_key or current_line_still_persists" -q -p no:xonsh
FF.
2 failed, 1 passed, 49 deselected in 0.89s
# (test_set_profiles_on_the_current_line_still_persists_its_stack passes either
#  way — it pins pre-existing behaviour, not the fix)
```

Also isolated Finding 1's `dispose()` sub-guard specifically: removed just the
`self.canvas.viewport().removeEventFilter(self)` line, reran
`test_a_disposed_link_no_longer_clears_the_preview_on_leave` alone — it failed
(`assert None == 'raw/FILE__002.DZT'`) — then restored the line and confirmed
the full source diff was byte-identical to before via `diff` against the saved
patch.

## Final verification (full suite, both tiers, lint, types)

```
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
367 passed, 2 skipped in 1.64s

$ QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
453 passed in 130.99s (0:02:10)
# baseline 443 + 10 new tests (5 map_link, 2 profile_dock, 3 session) = 453

$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
95 files already formatted

$ .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
    packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
    packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
Success: no issues found in 24 source files
```

## Files touched

- `packages/nsgeo-qgis/nsgeo_qgis/map_link.py` (Findings 1, 3)
- `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (Findings 2, 4)
- `packages/nsgeo-qgis/nsgeo_qgis/session.py` (Finding 4)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py`
