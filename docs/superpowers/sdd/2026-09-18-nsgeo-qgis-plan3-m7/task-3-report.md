# Task 3 report: `MapLink`

## What was implemented

Created `packages/nsgeo-qgis/nsgeo_qgis/map_link.py` and
`packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py`, following the
brief's steps in order (write tests → confirm red → write module → confirm
green → boundary test → full tiers + lint → commit).

`MapLink` owns a `QgsVertexMarker` (the trace cursor) and a `QgsRubberBand`
(the selection band), redrawing both from `SiteSession` on every relevant
signal (`trace_changed`, `selection_changed`, `preview_changed`,
`line_opened`, `lines_changed`, `grids_changed`, `site_opened`,
`site_closed`, plus the canvas's `destinationCrsChanged`). A lazily-built,
canvas-CRS geometry cache (`_geometries()`/`_invalidate()`) reads vertex
positions straight off the `lines` layer's own geometry — no coordinate
maths, per the brief's §3.1 deviation note (vertex index == trace index,
because `SiteLayers.refill_lines` built it that way). `dispose()` removes
both canvas items via `item.scene()` (not `self.canvas.scene()`) and is
idempotent, addressing Plan 2's item I4 defect.

I transcribed both the module and the test file byte-for-byte from the
brief before running anything (verified with a `diff` against the brief's
own code blocks — see "Verifying no transcription error" below), then ran
TDD as instructed. Two of the eleven given tests failed against the
verbatim code, for reasons that turned out to be genuine logic conflicts
in the brief itself, not something I misread. Both are described in detail
below, with the fix I applied to each and why.

## Red state (Step 2)

Command:
```
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py -q -p no:xonsh
```

Output:
```
==================================== ERRORS ====================================
___ ERROR collecting packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py ____
ImportError while importing test module '.../test_plugin_map_link.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py:10: in <module>
    from nsgeo_qgis.map_link import MapLink
E   ModuleNotFoundError: No module named 'nsgeo_qgis.map_link'
=========================== short test summary info ============================
ERROR packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.19s
```

Exactly as the brief predicted.

## Verifying no transcription error, before trusting the failures

Before treating the two later failures as anything other than my own
mistake, I extracted the brief's `map_link.py` and test-file code blocks
into scratch files with a small script and ran `diff` against what I had
written. Both came back `IDENTICAL` — byte-for-byte. That ruled out a
copy error and told me the two failures below were real conflicts between
the brief's given code and given tests against the actual `session.py`/
`layers.py` in this worktree, not a misreading on my part.

## Deviation 1 (production code): the marker went invisible on the working line's own hover

After writing `map_link.py` verbatim and running the 11 new tests, this
failed:

```
FAILED test_plugin_map_link.py::test_hovering_the_working_line_keeps_its_own_selection_band
    session.set_selection(keys[0], 4, 9)
    session.set_preview(keys[0], 3)
    assert link._band.numberOfVertices() == 6   # passed
    assert link._marker.isVisible()             # FAILED: assert False
```

Root cause: `session.open_line()` resets `current_trace` to `-1` and never
sets it again — a fresh `SiteSession` has no "current trace" until
something explicitly calls `set_trace()`. This test never calls
`set_trace()`; it only hovers (`set_preview`) the line already open. In
the verbatim `_refresh()`, the branch for "not actually previewing"
(`preview_key == current_key`, i.e. hovering your own working line) draws
the marker from `self.session.current_trace` — which is still `-1` here —
so `_set_marker` correctly hides it (`trace < 0`). The test's own
docstring says this case "means the pointer is over the line already
being worked on -- not a preview," but only argues that point for the
*band* (matching context note 3 in my brief). It says nothing about the
marker, yet the assertion demands the marker be visible too — impossible
while it reads `current_trace`, given `current_trace` is unset in this
scenario.

I checked whether this was actually consistent with the feature's intent
rather than a test bug: `ProfileDock._on_preview_changed` (Task 2) treats
this exact case (`key and key != self._working_key` false) as "not a
preview," and its `_exit_preview()` also falls back to
`self.session.current_trace` for the profile view's own cursor — so
Task 2's own precedent test (`test_previewing_the_working_line_is_not_a_preview`)
never asserts anything about the cursor's position or visibility in this
state, only the banner and `_key`. That told me the marker-visibility
assertion here is new territory the brief introduced without also fixing
the code for it, not an established, already-verified behaviour I'd be
overriding by mistake.

Given the module exists specifically so the map cursor visibly follows
the pointer, and the pointer literally has just reported a fresher
position (`preview_trace`) than whatever trace navigation last set, I
changed the marker's trace source: prefer `preview_trace` whenever
`preview_key == key` (which covers both "hovering the working line" and
"no hover, preview_key is None" falls through to `current_trace` as
before), leaving the "is it actually a different-line preview" boolean
(`previewing`) and its band behaviour completely untouched, since context
note 3 says explicitly not to simplify that condition:

```python
trace = (
    self.session.preview_trace
    if self.session.preview_key == key
    else self.session.current_trace
)
self._set_marker(key, trace)
self._set_band(key, *self.session.selection)
```

Re-ran the full 11-test file: this test and all others pass. I re-checked
every other test against the new logic by hand (marker-follows-preview,
snap-back, closing-the-site, own-band-preserved) — none of them depend on
`preview_key == current_key` with a non-null preview, so none of them are
affected by this change.

## Deviation 2 (test file): an assertion on `_geoms` that the working code can never satisfy

Second failure, same run:

```
FAILED test_plugin_map_link.py::test_the_geometry_cache_is_rebuilt_after_the_lines_change
    link._geometries()          # populate
    session.remove_line(keys[1])
    assert link._geoms is None  # FAILED: assert {...} is None
```

Root cause: `remove_line()` emits `lines_changed`, which `MapLink` connects
to `_on_lines_changed`, whose body is `self._invalidate(); self._refresh()`
— both calls happen inside the *same* slot invocation, synchronously.
`keys[0]` is still the open line in this fixture, so `_refresh()` doesn't
return early; it calls `_set_marker`/`_set_band`, both of which call
`self._geometries()`, which — finding `self._geoms is None` — rebuilds the
whole cache and unconditionally assigns it back to `self._geoms` before
returning. So by the time `remove_line()` returns to the test, `_geoms` is
already a freshly rebuilt (correct, `keys[1]`-free) dict, not `None`. This
isn't dependent on construction order or `SiteLayers` timing (context note
5) — it is a two-line consequence of `_on_lines_changed` always following
`_invalidate()` with a `_refresh()` that (given an open line) always
touches `_geometries()` again in the same call. There is no code path
through the brief's own `_refresh()`/`_geometries()` that can leave
`_geoms` as `None` while a line is open — asserting so is asserting
something the given implementation structurally cannot do without
*breaking* the actual feature (the marker needing fresh geometry any time
a line moves under it, e.g. after a grid edit).

I did not change the module for this one — doing so would mean either
skipping the redraw on a structural change (leaving the marker stale after
`lines_changed`/`grids_changed`, the exact case invalidation exists to
handle) or duplicating the cache lookup in a way divorced from the "None
means not built" invariant context note 5 describes. Instead I loosened
the test's middle assertion to check what's actually externally
observable and meaningful — that a rebuild happened (new dict object, not
the old one merely edited in place) — rather than an intermediate `None`
state that's synchronously overwritten before control returns to the
caller:

```python
def test_the_geometry_cache_is_rebuilt_after_the_lines_change(linked):
    link, session, _layers, _canvas, keys = linked
    first = link._geometries()  # populate
    assert link._geoms is not None

    session.remove_line(keys[1])

    assert link._geoms is not None
    assert link._geoms is not first
    assert keys[1] not in link._geometries()
```

The externally-meaningful half of the original assertion —
`keys[1] not in link._geometries()` — already passed unmodified; the
failure output before my fix showed the rebuilt dict correctly contained
only `keys[0]`'s geometry.

## A third, unrelated fix: two dead imports in the test file

`ruff check .` flagged the test file's given import line:
```python
from plugin_testing import REAL_DZT, needs_real_data, synthetic_dzt
from qgis.core import QgsGeometry, QgsPointXY, QgsProject
```
`REAL_DZT`, `needs_real_data`, and `QgsGeometry` are never used anywhere in
this test file (every fixture uses `synthetic_dzt`; nothing in this file
is gated behind real DZT data, unlike sibling files such as
`test_plugin_layers.py` that import the same names and do use them). I
removed the three unused names, changing nothing about test behaviour:
```python
from plugin_testing import synthetic_dzt
from qgis.core import QgsPointXY, QgsProject
```
`ruff check .` and `ruff format --check .` are both clean after this.

## Final verification (Step 6)

```
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
363 passed, 2 skipped in 1.37s
```
(Matches the stated baseline exactly — this task adds no pure-tier tests.)

```
$ QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
415 passed in 103.80s (0:01:43)
```
(Baseline 404 + 11 new tests = 415. No skips, no failures.)

```
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q -p no:xonsh
4 passed in 0.19s
```

```
$ .venv/bin/ruff check .
All checks passed!
$ .venv/bin/ruff format --check .
94 files already formatted
```

`map_link.py` was not added to `.github/workflows/ci.yml`'s mypy file list
(confirmed via `git diff .github/workflows/ci.yml` — empty). No files
other than the two new ones were touched (confirmed via `git status`).

## Things I'm not fully certain about

- **Deviation 1's UX call.** I judged, from the module's own purpose and
  from `ProfileDock`'s (Task 2) treatment of the same "hovering your own
  working line" case, that the marker should visibly track the mouse even
  over the working line. That is a design opinion about what the *test*
  meant to check, not something I could verify against a spec passage
  that says so explicitly. It doesn't touch `ProfileDock` or the `band`
  logic the review-locked context note 3 covers, but a reviewer who
  intended `test_hovering_the_working_line_keeps_its_own_selection_band`'s
  marker assertion to mean something else (e.g. "marker should just stay
  wherever it already was, and the test itself has a spurious extra
  assertion") would want to weigh in.
- **Deviation 2's precedent.** I have not seen a similar "assert the
  cache is momentarily None mid-signal" pattern elsewhere in this codebase
  to compare against; my read is that it's simply unreachable given how
  `_refresh()` must work, but I'd welcome a second opinion given the
  brief was explicit that test wording is deliberate.
- Task 4 (hover/hit-testing) is not implemented here, per the brief's
  scope ("Marker and band only... Hover comes in Task 4").

## Commit

```
git add packages/nsgeo-qgis/nsgeo_qgis/map_link.py packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py
git commit -m "feat: draw the profile's cursor and selection on the map ..."
```
See the actual commit SHA reported back to the orchestrator.

---

## Fix round 1 (coordinator review)

Spec compliance was judged compliant; the three deviations above were all
assessed as sound (D1's diagnosis, D2's replacement, D3 matching an
independent ruling). Two Important findings and one Minor came back.
Fixed all three; details below.

### Finding 1 (Important): `_transform` never checked the transform was valid

`QgsCoordinateTransform(source, dest, ...)` does not raise when PROJ has
no path between the two CRSs — `isValid()` is `False`, and
`geom.transform(tr)` then reports success while leaving the geometry
untouched. The verbatim brief code returned this transform unchecked, so
an unreachable canvas CRS would silently cache raw layer-CRS coordinates
as if they were canvas-CRS ones.

Fixed by following `SiteLayers._require_transform`'s shape exactly:
`_transform` now raises `RuntimeError` when `transform.isValid()` is
`False`, with a message in the same form
(`f"no coordinate transform from {source.authid()...} to
{dest.authid()...}; refusing to draw untransformed geometry"`). It also
now builds the transform against `self.layers.project` (the project
`SiteLayers` was actually constructed with) instead of the global
`QgsProject.instance()` singleton, and the now-unused `QgsProject` import
was dropped.

`_geometries()` catches that `RuntimeError` around the transform lookup —
*before* the feature loop runs, not around it — logs a Critical message
via `_log`, and caches an **empty** dict rather than leaving `_geoms` as
`None` (which would retry, and re-log, on every subsequent signal) or
half-populating it partway through the loop. An empty cache reads as
"line not found" everywhere it's consulted, so `_set_marker`/`_set_band`
hide the marker and empty the band exactly as they already do for any
other missing key — no new code path needed there.

Added `test_a_canvas_crs_unreachable_from_the_layer_produces_no_untransformed_geometry`.
A genuinely invalid transform is constructible on this build: the grid's
own `EPSG:32616` (projected, Earth) against `ESRI:104905` (`GCS_Mars_2000`,
geographic, Mars) gives `QgsCoordinateTransform(...).isValid() == False`
— the same Earth/Mars pairing `SiteLayers._require_transform`'s own
docstring uses, so this is a real failure on this exact QGIS build, not a
stub. The test asserts only observable outcomes: the marker (previously
visible) goes invisible, the band empties, `_geometries()` returns `{}`,
and a message containing "no coordinate transform" reaches
`QgsMessageLog` (via the `message_log` fixture). I verified the test
actually catches the bug by reverting `_transform` to the brief's
verbatim (unchecked, global-`QgsProject`) form and confirming this new
test fails against it — the marker stayed visible, drawn from
untransformed coordinates — then restored the fix and confirmed all 12
tests in the file pass again.

### Finding 2 (Important): `destinationCrsChanged` was connected but never exercised by a signal

`test_geometries_are_transformed_into_canvas_crs` called
`canvas.setDestinationCrs(...)` and then `link._invalidate()` by hand,
so the `canvas.destinationCrsChanged.connect(self._on_lines_changed)`
line in `__init__` was never actually exercised — deleting it left all
11 tests green. Removed the manual `link._invalidate()` call so the test
now depends on the signal firing. Verified directly: temporarily
commenting out the `connect()` line in `map_link.py`, re-running just
this test, and watching it fail (`in_wgs84` came back at the untransformed
`(500, 700)`, tripping the `<= 180.0` bound); restored the connection and
confirmed the test (and the full file) pass again.

### Finding 3 (Minor, folded in): `set_preview(key)`'s default `trace=-1` hid a marker that had a valid position

D1's original fix used `preview_trace` whenever `preview_key == key`,
which also fires when something calls `set_preview(key)` with no trace
(defaulting to `-1`) on the working line — that would now hide a marker
whose `current_trace` is a perfectly good answer, purely because of how
that particular call happened to be shaped. No caller does this yet, but
the coordinator flagged it as a trap for Task 4, which will call
`set_preview` from real hover code.

Replaced the `preview_key == key` branch with a fallback on the trace
value itself, per the coordinator's suggested shape:

```python
trace = self.session.preview_trace
if trace < 0:
    # set_preview(key) defaults trace to -1. On the working line
    # current_trace is still a real answer, so fall back to it
    # rather than hiding a cursor we know the position of.
    trace = self.session.current_trace
self._set_marker(key, trace)
```

This is actually simpler than the original fix, not just safer:
`session.py` guarantees `preview_trace == -1` whenever `preview_key` is
`None` (every place that clears the preview resets both fields together),
so the single `trace < 0` fallback also covers the plain "no hover at
all" case that the old `preview_key == key` check needed as its `else`
branch. No test needed changing for this — it's a strict superset of the
old behaviour on every value the existing 12 tests exercise (all of which
use `set_preview(key, trace)` with an explicit non-negative trace or
`None`, never a bare `set_preview(key)`), and adding a caller that
reaches the new branch is explicitly the two Minors' territory (deferred
to Task 4), not this task's.

### The two deliberately-out-of-scope Minors

Left both exactly as the coordinator specified: `trace_changed` not
moving the marker while the pointer rests on the working line is Task 4's
design change (hover will call `set_trace` for the working line and
`set_preview` only for other lines); `MapLink.__init__` never calling
`_refresh()` is unreachable in production because Task 5 constructs
`MapLink` before any site can be open. No code touched for either.

### Re-verification after all fixes

```
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
363 passed, 2 skipped in 1.33s
```

```
$ QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
416 passed in 105.06s (0:01:45)
```
(415 after the original commit + 1 new test for Finding 1.)

```
$ .venv/bin/ruff check .
All checks passed!
$ .venv/bin/ruff format --check .
94 files already formatted
```

Commit SHA reported back to the orchestrator.
