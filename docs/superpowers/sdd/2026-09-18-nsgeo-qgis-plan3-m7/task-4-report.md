# Task 4 report: ambient hover previews the line under the pointer

Worktree: `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m7`
Branch: `nsgeo-m7`
Base commit: `638a531`
Result commit: `8c40d68` (pushed to `origin/nsgeo-m7`)

## What was implemented

Followed the brief exactly, in the order given.

1. **Test file** (`packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py`):
   restored the `REAL_DZT` / `needs_real_data` imports from `plugin_testing`
   and appended the full "ambient hover (spec §3.2)" test block verbatim
   from the brief (12 new tests, including the real-data test and the
   loader-integration test).

2. **`packages/nsgeo-qgis/nsgeo_qgis/map_link.py`**:
   - Extended the `QtCore` import to include `QTimer`.
   - Added module constants `HOVER_DWELL_MS = 100` and
     `HOVER_TOLERANCE_PX = 12` beside `MARKER_COLOUR`, and mirrored them as
     class attributes on `MapLink` (`MapLink.HOVER_DWELL_MS`,
     `MapLink.HOVER_TOLERANCE_PX`).
   - In `__init__`, after the geometry-cache comment: added
     `self._last_point`, built the single-shot `self._dwell` `QTimer`
     wired to `self._on_dwell`, and connected `canvas.xyCoordinates` to
     `self._on_xy`.
   - Added a new `# ---- ambient hover ----` section (placed after
     `_transform`, before `# ---- drawing ----`) with `_on_xy`, `_on_dwell`,
     and `_hit_test`, exactly as given in the brief — including the
     squared-tolerance comparison in `_hit_test` and the branch in
     `_on_dwell` that routes a hover over the working line through
     `clear_preview()` + `set_trace()` rather than `set_preview()`.
   - Added `self._dwell.stop()` as the first line of `dispose()`.

3. **`packages/nsgeo-qgis/nsgeo_qgis/loader.py`**:
   - Connected `session.preview_changed` to a new `_on_preview_changed`
     slot in `LineLoader.__init__`, placed next to the existing
     `session.line_opened.connect(...)`.
   - Added `_on_preview_changed(self, key: str, _trace: int) -> None`
     next to `_on_line_opened`, delegating to `_on_line_opened(key)` as
     specified.

No deviation from the brief's code. One deliberate deviation from the
brief's **commit message**: the brief's final step ends the commit message
with `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`,
but the live system reminder for this session specifies
`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` for all commits
made "from here on," and states it takes precedence over any other
attribution guidance unless overridden by the user's own CLAUDE.md/memory
rules (which it isn't, here). I used the session's attribution line
instead of the brief's. Every other line of the specified commit message
was used verbatim.

## Red-state output (Step 2)

Command:

```
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py -q -p no:xonsh -k "hover or dwell or tolerance or loader or sweep or working or real"
```

Result: `12 failed, 3 passed, 9 deselected in 17.21s`

All 12 new tests failed. The representative failure (repeated for every
test that touches `link._dwell`):

```
>       canvas.xyCoordinates.emit(target)
        _fire_dwell(link)
E       AttributeError: 'MapLink' object has no attribute '_dwell'
```

(`test_hovering_a_real_line_previews_its_real_trace` failed the same way,
at `link._dwell.timeout.emit()` — meaning this environment does have real
DZT data under `packages/nsgeo-core/tests/data/local`, so that test
actually ran rather than being skipped, both in red and in the final
green run.)

`test_a_previewed_line_is_requested_from_the_loader` failed differently,
as expected since it does not touch `_dwell` at all:

```
>       assert asked == [keys[1]]
E       AssertionError: assert [] == ['raw/FILE__002.DZT']
```

This matches the brief's predicted failure mode exactly.

## Green-state / full verification (Steps 5 and 6)

1. Targeted file pair:

```
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py packages/nsgeo-qgis/tests/qgis/test_plugin_loader.py -q -p no:xonsh
```
→ `39 passed in 28.34s`

2. Pure tier:

```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
```
→ `363 passed, 2 skipped in 1.44s` (matches the base-commit count exactly)

3. QGIS tier (full suite):

```
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
```
→ `428 passed in 117.17s` (base was 416; +12 matches the 12 new tests, all
passing, none skipped)

4. Lint:

```
.venv/bin/ruff check .
```
→ `All checks passed!`

```
.venv/bin/ruff format --check .
```
→ `94 files already formatted`

5. Confirmed `map_link.py` is not present in any mypy file-list
   configuration (`grep -rn "map_link"` across `*.cfg/*.ini/*.toml/Makefile/*.yml/*.yaml`
   outside the test file returned nothing).

## Commit and push

```
commit 8c40d68
feat: preview the line under the pointer, without a map tool
```

3 files changed: `packages/nsgeo-qgis/nsgeo_qgis/map_link.py`,
`packages/nsgeo-qgis/nsgeo_qgis/loader.py`,
`packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py`.

Pushed: `96e4ba0..8c40d68  nsgeo-m7 -> nsgeo-m7`.

## Things I'm unsure about

- The commit-message attribution-line substitution described above
  (Claude Sonnet 5 vs. the brief's Claude Opus 5 line). I judged the
  live session's attribution reminder to be authoritative over a line
  embedded in a pre-written brief, since the brief is not the user's own
  CLAUDE.md/memory instruction. Flagging in case the reviewer wants the
  brief's literal line instead — trivial to amend if so, though per the
  house git rules I'd create a new commit rather than amend the existing
  one, so I'm leaving it as pushed pending guidance.
- No other open questions. `_hit_test`'s squared-tolerance comparison,
  the working-line-vs-preview branch in `_on_dwell`, and the
  `_geometries()` empty-cache-on-invalid-transform behavior all matched
  the "five things" notes and required no interpretation beyond what the
  brief and those notes already specified.

## Fix report (post-review)

Coordinator review confirmed everything called out as needing verification
(squared-distance comparison, `index < 0`/`isEmpty()` guards, empty-cache
handling, the `""` sentinel, a pointer sweep leaving `dirty` and every
`StepStack` identity untouched) was correct, and returned one Important
finding and one Minor (comment) finding.

### Finding 1 (Important): a disposed `MapLink` still wrote to the session

Root cause: `dispose()` stopped `self._dwell` but never disconnected
`canvas.xyCoordinates` from `_on_xy`, and `_on_dwell` had no disposal
guard the way `_refresh` does (`if self._marker is None or self._band is
None: return`). After `dispose()`, a mouse move still reached `_on_xy`,
which restarted the timer, and a subsequent timeout ran `_on_dwell` to
completion against a live session — repointing `current_trace` and
issuing loader requests after the plugin considered itself torn down.

Fix, in `packages/nsgeo-qgis/nsgeo_qgis/map_link.py`:

- `dispose()` now disconnects `canvas.xyCoordinates` from `self._on_xy`
  right after `self._dwell.stop()`, wrapped in
  `contextlib.suppress(TypeError)` — `disconnect()` raises rather than
  no-ops on a connection already gone, and `dispose()` must stay
  idempotent (a second call, or one made after the canvas tore its own
  signals down).
  - Ruff's `SIM105` flagged the first draft (`try`/`except TypeError:
    pass`) and asked for `contextlib.suppress` — matched the existing
    precedent in `layers.py:472` and switched to it.
- `_on_dwell` now opens with `if self._marker is None: return  #
  disposed`, mirroring `_refresh`'s own sentinel, to cover a timeout
  already queued on the Qt event loop before `dispose()` ran (the
  disconnect only stops *new* emissions from reaching `_on_xy`; it does
  not un-queue one already in flight).

Added the reviewer's test verbatim in spirit, adapted to capture the
target vertex *before* `dispose()` (per the reviewer's own note that
`_geometries()` is unusable afterwards) —
`test_a_disposed_link_stops_tracking_the_pointer` in
`test_plugin_map_link.py`, placed next to
`test_hover_with_no_site_open_does_nothing`. It asserts both halves of
the fix: emitting `xyCoordinates` after disposal does not restart the
timer (`not link._dwell.isActive()`), and manually firing a timeout that
"got in under the wire" does not mutate `current_trace`.

Reasoned through why the bug reproduces without the fix (not re-verified
by literally reverting, since the reviewer had already verified it
directly): `current_trace` starts at `-1` in the `linked` fixture (no
`set_trace` call before disposal); pre-fix, `canvas.xyCoordinates.emit`
still reaches `_on_xy` (no disconnect), which calls `self._dwell.start()`
on the still-live `QTimer`; the manual `link._dwell.timeout.emit()` then
runs `_on_dwell` with no guard, hits the working line's own vertex 11,
and (since `key == session.current_key`) calls `clear_preview()` +
`set_trace(key, 11)`, leaving `current_trace == 11 != before`.

### Finding 2 (Minor): a comment describing a now-dead hover path

`_refresh()`'s comment explaining why `previewing` excludes
`preview_key == current_key` used to describe that state as "the pointer
is over the line already being worked on" — true before this task, but
after `_on_dwell` routes a hover over the working line through
`clear_preview()` + `set_trace()` instead, hovering can no longer produce
`preview_key == current_key`. Left the branch itself untouched (it is
still correct: `set_preview` is public, and any other caller — present
or future — can still set that state), and rewrote the comment to say so
explicitly: the branch is defensive against a call the hover path no
longer takes, not a description of live hover behaviour. Did not touch
the second, similarly-worded comment a few lines further down (the
`preview_trace < 0` fallback) since the reviewer's finding named only
this one location and asked for a targeted fix, not a broader sweep.

### Explicitly out of scope, not touched

Per the coordinator's instructions, left both of the following exactly
as designed and did not change any code for them:

- Hovering the working line now permanently moves `current_trace` with
  no snap-back on pan/zoom (consistent with the profile dock's own hover
  behavior; a fix would need a canvas event filter, which spec §3.2
  rules out). Recorded on M7's manual acceptance checklist per the
  coordinator, not in this code.
- `clear_preview()` followed by `set_trace()` causes two refreshes, so
  crossing from a preview onto the working line shows the old cursor for
  one frame.

### Re-verification after the fix

```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
```
→ `363 passed, 2 skipped in 1.36s` (unchanged from before the fix)

```
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
```
→ `429 passed in 119.79s` (428 + the 1 new disposal test, all passing)

```
.venv/bin/ruff check .
```
→ `All checks passed!` (after switching to `contextlib.suppress`)

```
.venv/bin/ruff format --check .
```
→ `94 files already formatted`

### Commit and push

```
commit 1a21862
fix: stop a disposed MapLink from still tracking the pointer
```

2 files changed: `packages/nsgeo-qgis/nsgeo_qgis/map_link.py`,
`packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py`.

Pushed: `8c40d68..1a21862  nsgeo-m7 -> nsgeo-m7`.

## Second fix report (re-review)

Re-review confirmed both prior findings addressed (probed independently:
the post-dispose leak closed end to end, and the rewritten comment's
claims both checked out — hover cannot reach `preview_key == current_key`
any more, a direct `set_preview` call still can). It also confirmed
`contextlib.suppress(TypeError)` was safe for the disconnect itself. Two
new problems were found in the fix's own edges, plus one drift risk.

### Finding 3 (Important): `dispose()` aborted before removing the items when the canvas itself was gone

`self.canvas.xyCoordinates` in the disconnect line assumes `self.canvas`
is reachable at all. With the wrapper deleted, touching any attribute on
it raises `RuntimeError: wrapped C/C++ object ... has been deleted`,
which `suppress(TypeError)` never covered — the exception propagated out
of `dispose()` before the scene-removal loop ran, so `_marker`/`_band`
were never cleared or removed: the exact Item I4 leak this method exists
to prevent, and a direct contradiction of the method's own "does not
assume the canvas is still alive" docstring claim.

Fixed by checking `sip.isdeleted(self.canvas)` before attempting the
disconnect at all, and suppressing `RuntimeError` alongside `TypeError`
around the disconnect call itself (for a wrapper that reports as
not-deleted but whose C++ object is gone regardless). Either branch, the
scene-removal loop below always runs.

One wrinkle the reviewer flagged as open (with instructions to resolve
and report which way): `sip.isdeleted()` itself raises `TypeError` — not
`False` — when handed an object that is not sip-wrapped at all, which is
exactly the shape of the `_Dead` stub the reviewer's own Finding-3 test
uses (`link.canvas = _Dead()`, a plain Python object). Verified directly:

```
>>> sip.isdeleted(_Dead())
TypeError: isdeleted() argument 1 must be sip.simplewrapper, not _Dead
```

Resolved by reordering the guard (not adjusting the stub, since the
reviewer's stub is the realistic double for "canvas unreachable" and the
production code must tolerate whatever shape `self.canvas` degrades to):
`sip.isdeleted(self.canvas)` is itself wrapped in `try/except TypeError`,
treating that outcome the same as "gone" — skip the disconnect, but still
run the scene-removal loop.

### Finding 4 (Important, tests): the disposal test pinned only the disconnect half, not the `_on_dwell` guard

`test_a_disposed_link_stops_tracking_the_pointer` (added in the previous
round) emits `xyCoordinates` after `dispose()` — but since the disconnect
already stops that from reaching `_on_xy`, `_last_point` is never set,
so `_on_dwell`'s own `point is None` check would return early even with
its disposal guard deleted entirely. The guard was unpinned.

Added `test_a_disposed_link_ignores_a_dwell_that_was_already_queued`,
which arms the dwell (`canvas.xyCoordinates.emit(target)`, setting
`_last_point` and starting the timer) *before* calling `dispose()`, then
fires `link._dwell.timeout.emit()` afterward — the real case the guard
exists for: a timeout already queued on the Qt event loop when disposal
happened. Also added `test_dispose_still_removes_the_items_when_the_canvas_is_gone`
for Finding 3, using the reviewer's `_Dead` stub verbatim.

**Verified both new tests fail with their own fix reverted, before
committing:**

- With the `_on_dwell` disposal guard removed (temporarily deleted the
  `if self._marker is None or self._band is None: return` line),
  `test_a_disposed_link_ignores_a_dwell_that_was_already_queued` failed:
  `assert 11 == -1` (current_trace was written despite disposal).
- With `dispose()`'s canvas guard reverted to the previous round's
  unconditional `with contextlib.suppress(TypeError):
  self.canvas.xyCoordinates.disconnect(self._on_xy)`,
  `test_dispose_still_removes_the_items_when_the_canvas_is_gone` failed
  with an unhandled `RuntimeError: wrapped C/C++ object has been
  deleted` propagating out of `dispose()`.

Both fixes were then restored and the same two tests re-run to confirm
they pass again, before running the full suites below.

### Finding 5 (Minor): `_on_dwell`'s disposal check now matches `_refresh`'s

Changed `if self._marker is None:` to `if self._marker is None or
self._band is None:` in `_on_dwell`, so the two disposal checks in this
module are the same spelling of one sentinel rather than two that could
drift apart.

### Re-verification after this round's fixes

```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
```
→ `363 passed, 2 skipped in 1.33s`

```
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
```
→ `431 passed in 122.42s` (429 + the 2 new tests)

```
.venv/bin/ruff check .
```
→ `All checks passed!`

```
.venv/bin/ruff format --check .
```
→ `94 files already formatted`

### Commit and push

```
commit cf0d901
fix: keep dispose() working when the canvas itself is already gone
```

2 files changed: `packages/nsgeo-qgis/nsgeo_qgis/map_link.py`,
`packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py`.

Pushed: `1a21862..cf0d901  nsgeo-m7 -> nsgeo-m7`.
