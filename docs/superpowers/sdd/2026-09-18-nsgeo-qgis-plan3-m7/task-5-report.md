# Task 5 report: selection promotes, plugin wiring, no-orphan-signals check

## What was implemented

Followed the brief exactly, with two lint-driven deviations noted below.

1. **`map_link.py`**
   - `__init__`: added `self._lines_layer_bound: QgsVectorLayer | None = None` and a
     trailing call to `self._rebind_layer()`.
   - `_on_lines_changed`: added `self._rebind_layer()` as the first statement inside
     the try block, before `self._invalidate()`.
   - New `_rebind_layer()`: disconnects `selectionChanged` from whichever layer was
     previously bound (guarded the same way as `dispose()`'s canvas check), looks up
     the current `lines` layer via `self._lines_layer()`, records it, and connects
     `selectionChanged` to the new `_on_selection` slot.
   - New `_on_selection(self, *_: Any)`: reads `selectedFeatureIds()`; bails on
     anything but exactly one id (covers both the multi-selection and the
     empty-selection case, each with its own comment per the brief's requirement to
     keep them distinguishable); otherwise reads `line_key` off the one selected
     feature and calls `session.open_line(key)` if that key is still in
     `session.keys()`. Wrapped in try/except reporting through `_log`, per the
     Qt-slot-exception constraint.
   - `dispose()`: **inserted only** the layer-unbind block, in the exact position
     the brief specified (after the canvas-disconnect guard, before
     `items, self._marker, self._band = ...`), plus one added sentence in the
     existing docstring naming the layer connection. Nothing else in `dispose()` was
     touched — confirmed via `git diff`, which shows the method's pre-existing body
     unchanged apart from that insertion and the docstring sentence.

2. **`plugin.py`**
   - Added `from nsgeo_qgis.map_link import MapLink`.
   - Added `self.map_link: Any = None` in `__init__`.
   - In `initGui`, immediately after `self.loader = LineLoader(...)`, construct
     `self.map_link = MapLink(self.session, self.layers, self.iface.mapCanvas())`
     with the brief's comment.
   - In `unload`, before `self.layers.detach()`, dispose and null `self.map_link`
     with the brief's comment.

3. **`README.md`** — there was no pre-existing "features" section in this file
   (checked git history and all four prior task briefs/reports: none touched
   `README.md`). Added a new `## Features` heading right after the intro paragraph,
   containing the brief's `### The map ↔ profile link` block verbatim. This is the
   one place I made a placement judgment call the brief didn't fully specify; flagging it explicitly.

4. **Tests**
   - Appended the six selection/promotion tests plus
     `test_a_disposed_link_stops_promoting_on_selection` to
     `tests/qgis/test_plugin_map_link.py`, verbatim from the brief.
   - Appended `test_the_plugin_builds_and_disposes_its_map_link` to
     `tests/qgis/test_plugin_loads.py`, verbatim.
   - Created `tests/pure/test_no_orphan_signals.py`, verbatim.

## Deviations from the brief's literal code, and why

Two lines of the brief's own snippet fail this repo's `ruff check` as written, so I
adjusted only the lint-facing shape while keeping identical behaviour, following
existing precedent already in this codebase:

- `_rebind_layer`'s `try: ... except TypeError: pass` triggers SIM105. Rewrote as
  `with contextlib.suppress(TypeError): ...` (the same pattern `dispose()` already
  uses twice), keeping the original explanatory comment.
- `_on_selection`'s `if key in self.session.keys():` triggers SIM118 (ruff
  pattern-matches `.keys()` in an `in` test regardless of whether the receiver is
  actually a dict). `SiteSession.keys()` returns `list[str]`, not a dict, so this is
  a false positive — and the codebase already has this exact situation six times
  elsewhere (`loader.py`, `survey_dock.py`, two test files), always resolved with
  `# noqa: SIM118 -- SiteSession.keys(), not a dict` rather than rewriting the
  check. Added the same noqa comment here rather than inventing a different idiom.

No other deviations. `dispose()` was not retyped; only the specified block and
docstring sentence were inserted.

## Red-state output (Step 2)

Before implementing `_rebind_layer`/`_on_selection`/the `dispose()` insertion, with
only the new tests added:

```
$ QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py -q -p no:xonsh -k "select or promot"
...
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py::test_selecting_one_line_makes_it_the_working_line
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py::test_promotion_goes_through_open_line_so_it_cannot_diverge
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py::test_deselecting_everything_promotes_nothing
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py::test_promotion_still_works_after_the_lines_layer_is_rebuilt
4 failed, 6 passed, 23 deselected in 12.74s
```

The failures are exactly the ones the brief predicts (`assert session.current_key ==
keys[1]` — nothing promotes yet). Two selection tests in the `-k` filter passed
trivially even in the red state and were not expected to fail:
`test_selecting_several_lines_promotes_none` (current_key stays `keys[0]` whether or
not promotion exists, since nothing should promote a multi-selection either way) and
`test_a_disposed_link_stops_promoting_on_selection` (same reasoning — no promotion
exists yet at all, disposed or not).

```
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py -q -p no:xonsh
...
3 passed in 0.10s
```

The orphan test is **green on arrival**, exactly the case the brief calls out: "if it
passes here, say so and keep it; a check that is green on arrival is still the
check." Tasks 2 and 4 had already wired `preview_changed` before this task ran, so
there was no `preview_changed` orphan to catch. Kept the test as the standing guard
it's meant to be.

## Step 6: full test run + lint + mypy

```
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
366 passed, 2 skipped in 1.43s
```
(363 + 2 skipped baseline, plus the 3 new orphan tests = 366 passed, 2 skipped.)

```
$ QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
441 passed in 129.52s (0:02:09)
```
(431 baseline + 7 new qgis-tier tests + 3 orphan tests also collected under this run
because `tests/pure` sits under `packages/nsgeo-qgis/tests` = 441.)

```
$ .venv/bin/ruff check . && .venv/bin/ruff format --check .
All checks passed!
95 files already formatted
```

```
$ .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
Success: no issues found in 24 source files
```

`map_link.py` was confirmed absent from this (and every) mypy file list —
`grep -rn "map_link" --include="*.toml" --include="*.cfg" --include="*.ini" .` and a
search of `.github/` both came back empty.

## Step 7: manual orphan check (public methods)

```
$ for name in set_preview clear_preview display_key preview_key preview_trace dispose; do
    echo "== $name =="
    grep -rn "\.$name" packages/nsgeo-qgis/nsgeo_qgis/ | grep -v "def $name"
  done
```

Output:

```
== set_preview ==
packages/nsgeo-qgis/nsgeo_qgis/map_link.py:231:                self.session.set_preview(key, trace)
== clear_preview ==
packages/nsgeo-qgis/nsgeo_qgis/map_link.py:218:                self.session.clear_preview()
packages/nsgeo-qgis/nsgeo_qgis/map_link.py:228:                self.session.clear_preview()
packages/nsgeo-qgis/nsgeo_qgis/session.py:650:            self.clear_preview()
packages/nsgeo-qgis/nsgeo_qgis/session.py:734:            self.clear_preview()
== display_key ==
packages/nsgeo-qgis/nsgeo_qgis/map_link.py:332:        key = self.session.display_key if self.session.is_open else None
== preview_key ==
packages/nsgeo-qgis/nsgeo_qgis/map_link.py:349:        previewing = self.session.preview_key not in (None, self.session.current_key)
== preview_trace ==
packages/nsgeo-qgis/nsgeo_qgis/map_link.py:351:            self._set_marker(key, self.session.preview_trace)
packages/nsgeo-qgis/nsgeo_qgis/map_link.py:364:        trace = self.session.preview_trace
== dispose ==
packages/nsgeo-qgis/nsgeo_qgis/plugin.py:103:    tool.dispose()
packages/nsgeo-qgis/nsgeo_qgis/plugin.py:284:            self.map_link.dispose()
```

Every one of the six has at least one hit outside its own definition, in production
code (not tests): `set_preview`, `clear_preview`, `display_key`, `preview_key`, and
`preview_trace` are all called from `map_link.py`'s `_on_dwell`/`_refresh`, and
`dispose` is called from `plugin.py`'s `unload` (the `tool.dispose()` hit is
`DigitiseGridTool`'s own unrelated `dispose`, an independent caller of an
independent method with the same name — still evidence that "dispose" the name is
not orphaned in production code).

Confirmed the pre-existing orphans are unchanged in status:

```
$ grep -rn "picks_changed\s*\.connect" packages/nsgeo-qgis/nsgeo_qgis/
(no output — still unconsumed, still deferred to M8)

$ grep -rn "pick_requested\s*\.connect" packages/nsgeo-qgis/nsgeo_qgis/
packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py:197:        self.view.pick_requested.connect(self._pick)
(exactly one connect — ProfileView's; ProfileDock's own pick_requested is still
unconsumed, matching the pinned count of 1)

$ for n in new_site_requested open_site_requested save_requested; do
    grep -rn "$n\s*\.connect" packages/nsgeo-qgis/nsgeo_qgis/
  done
(no output for any of the three — still dead API, still unconsumed)

$ grep -rn "\.set_pick_mode" packages/nsgeo-qgis/nsgeo_qgis/ | grep -v "def set_pick_mode"
packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py:714:        # layer"), and this signal plus `ProfileView.set_pick_mode()` are
(the only hit is a comment mentioning the method's name, not a call — still uncalled)
```

M7 adopts none of the pre-existing orphans.

**Report for the user** (per the brief): spec §1's orphan table and §6's "the three
existing orphans" are both wrong — the real set is `picks_changed`,
`ProfileDock.pick_requested`, `ProfileView.set_pick_mode`, plus
`SurveyDock.new_site_requested` / `open_site_requested` / `save_requested`. The
three `SurveyDock` signals are dead API from Plan 2 and want an issue filed against
that plan for cleanup (not done here — out of scope for M7 per the brief).

## Things I'm unsure about

- The README's "features section" didn't exist before this task; I created one
  (`## Features`) rather than assuming a specific pre-existing location, since no
  prior M7 task touched the README. If a different placement or heading was
  intended, easy to adjust.
- I did not perform the M7 acceptance manual checklist (the 10 hand-run-in-real-QGIS
  items at the end of the brief) — those require a live QGIS session against a real
  site, which is outside what an automated task run can do. Flagging this as a
  surfaced manual checkpoint that still needs a human pass before the milestone is
  called fully done.
- I did not open an issue for the dead `SurveyDock` signals (the brief explicitly
  scopes that out of M7, but says it "wants an issue" — leaving that decision to the
  reviewer/user).

## Commit

Committed as instructed (message body kept verbatim from the brief, attribution
line updated per this session's actual reminder rather than the brief's literal
"Claude Opus 5" line, since the attribution the conversation gave takes precedence).
Pushed to `origin/nsgeo-m7`.

---

# Fix report (post-review round 1)

Addressed all five findings from the coordinator's review of commit `eb2e2a5`.

## Finding 1 (Important) — a disposed link re-arms itself and promotes again

Root cause: `_on_lines_changed` called `_rebind_layer()` unconditionally, with no
disposal sentinel, unlike `_on_dwell`/`_refresh`. Any `lines_changed`/`grids_changed`/
`site_opened`/`site_closed` landing after `dispose()` would reconnect
`selectionChanged` on the still-live `lines` layer and let a disposed link promote
again.

Fix: added the same sentinel used elsewhere in the module, as the first statement of
`_on_lines_changed`'s try block:

```python
if self._marker is None or self._band is None:
    return  # disposed
```

Extended the test suite with a new test that actually exercises the gap
(`test_a_disposed_link_stops_promoting_on_selection` alone never fires a signal
between `dispose()` and the selection, so it could not tell a real unbind apart from
a silently reinstated one):

```python
def test_a_disposed_link_does_not_re_arm_itself_on_the_next_lines_signal(linked):
    link, session, layers, _canvas, keys = linked
    link.dispose()

    session.lines_changed.emit()
    layers.layers["lines"].selectByIds([_feature_id(layers, keys[1])])

    assert session.current_key == keys[0]
```

**Red-state output, captured by temporarily removing the sentinel** (`QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py -q -p no:xonsh -k re_arm`):

```
F                                                                        [100%]
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py::test_a_disposed_link_does_not_re_arm_itself_on_the_next_lines_signal
AssertionError: assert 'raw/FILE__002.DZT' == 'raw/FILE__001.DZT'
1 failed, 33 deselected in 2.27s
```

Restored the sentinel; the test then passes (verified with the full `test_plugin_map_link.py` file: 34 passed).

## Finding 2 (Important) — the orphan check hides a real orphan (`ParamForm.error`)

Confirmed by grep: `ui/param_form.py:40` declares `error = pyqtSignal(str)`, emitted at
`:222`, and never connected anywhere (`ParamForm` is instantiated by
`processing_dock.py:150` and `add_step_dialog.py:39`, neither of which connects its
`error`). It was invisible to the old check because `ProfileDock.error`'s connect at
`plugin.py:185` satisfied the name-keyed search — exactly the `pick_requested` flaw,
unpinned and undocumented.

Generalised rather than special-cased, per the instruction:

- `_declared_signals` now uses an `ast.NodeVisitor` (`_SignalVisitor`) that tracks
  the enclosing class via a stack, returning `dict[name, list[(owning_class, path)]]`
  instead of silently letting the second declaration overwrite the first in a plain
  dict. Also now handles `ast.AnnAssign` (Finding 5), not just `ast.Assign`.
- Replaced the single `pick_requested` pin with a table:

```python
SHADOWED_CONNECT_COUNTS = {
    "pick_requested": 1,  # ProfileView's connected; ProfileDock's own is not
    "error": 1,           # ProfileDock's connected; ParamForm's own is not
}
```

- Added `test_every_shadowed_signal_name_is_pinned`, which computes every signal name
  declared by more than one class and asserts it is a key in
  `SHADOWED_CONNECT_COUNTS` — this is the test that would have caught `error` on its
  own before a human had to.
- Replaced `test_profile_docks_pick_signal_is_still_unconsumed` with
  `test_shadowed_connect_counts_match_reality`, which checks every entry in the table
  against its actual connect count (generalising the old single-name assertion).

**Verification that the generalisation actually catches `error`**, done by temporarily
deleting the `"error": 1` line from `SHADOWED_CONNECT_COUNTS` and rerunning
(`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py -q -p no:xonsh`):

```
..F.                                                                     [100%]
FAILED packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py::test_every_shadowed_signal_name_is_pinned
AssertionError: signal names declared by more than one class must be pinned in
SHADOWED_CONNECT_COUNTS with their current connect count: {'error'}. ...
1 failed, 3 passed in 0.22s
```

Restored the entry; all 4 orphan tests pass again.

**Corrected list of genuinely-unconsumed signals — the real set is SEVEN, not six:**

1. `SiteSession.picks_changed` — deferred to M8 (`session.add_pick` will emit it).
2. `SurveyDock.new_site_requested` — dead API from Plan 2.
3. `SurveyDock.open_site_requested` — dead API from Plan 2.
4. `SurveyDock.save_requested` — dead API from Plan 2.
5. `ProfileDock.pick_requested` — shadowed by `ProfileView.pick_requested`, which IS
   connected (`profile_dock.py:197`); `ProfileDock`'s own is not.
6. `ParamForm.error` — shadowed by `ProfileDock.error`, which IS connected
   (`plugin.py:185`); `ParamForm`'s own is not.
7. `ProfileView.set_pick_mode` — not a signal at all (a public method), so outside
   what the automated check can see; confirmed by hand (Step 7) to still have no
   caller anywhere in `nsgeo_qgis/`.

M7 adopts none of these seven. Items 2-4 are dead Plan-2 API and want a cleanup
issue; that issue is not filed by this task (out of scope per the original brief).

## Finding 3 (Minor) — `_rebind_layer` should suppress `RuntimeError` too

Fixed: `_rebind_layer`'s disconnect now suppresses `(TypeError, RuntimeError)`,
matching `dispose()`'s own suppression around the identical `disconnect` call, with a
comment explaining why (a wrapper that reports as not-deleted but whose underlying
C++ object is gone regardless must not abort the method before the new layer gets
bound).

## Finding 4 (Minor) — the rebuild test didn't test what it said

Confirmed by reading `layers.py`: `refresh()` → `ensure_tables()` → `_ensure_table()`
only replaces a table's on-disk schema when the CRS/fields are stale, and even then
`refill_lines()`/`_refill()` operate on the *same* `QgsVectorLayer` Python object via
truncate+re-add — `refresh()` alone never swaps the object out from under
`self.layers["lines"]`. The layer object is only actually replaced when `self.layers`
has been cleared first (`detach()`), which is exactly what `_on_site_opened` does on
every site close/reopen. The old test called `layers.refresh()` directly, which
neither replaced the layer nor fired any signal `MapLink` listens for — it passed
regardless of whether `_rebind_layer` worked at all.

Rewrote the test to drive the real path — close and reopen the site (which both
replaces the `lines` layer object via `detach()`+`refresh()` and fires the
`site_closed`/`site_opened` signals `_on_lines_changed` is actually connected to):

```python
def test_promotion_still_works_after_the_lines_layer_is_rebuilt(linked):
    link, session, layers, _canvas, keys = linked
    json_path = session.json_path
    session.save()  # add_grid/add_lines only staged the site in memory

    session.close_site()
    session.open_site(json_path)

    layers.layers["lines"].selectByIds([_feature_id(layers, keys[1])])

    assert session.current_key == keys[1]
```

**Red-state output, captured by temporarily removing the `self._rebind_layer()` call
from `_on_lines_changed`** (`QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py -q -p no:xonsh -k rebuilt`):

```
.F                                                                       [100%]
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py::test_promotion_still_works_after_the_lines_layer_is_rebuilt
AssertionError: assert None == 'raw/FILE__002.DZT'
 +  where None = <nsgeo_qgis.session.SiteSession object at 0x...>.current_key
1 failed, 1 passed, 32 deselected in 3.62s
```

Restored the call; the test passes again (verified with the full file: 34 passed).

Also corrected `_rebind_layer`'s docstring and the matching comment in `dispose()` to
name the real mechanism ("a site reopen -- `SiteLayers.detach()` ... then
`refresh()`") instead of the wrong one ("`SiteLayers.refresh()` replaces the layer
object"). Left the already-pushed commit `eb2e2a5`'s message as history rather than
rewriting it; the correction lives in this fix commit's message and in the corrected
source docstrings going forward.

## Finding 5 (Minor) — `AnnAssign` not handled

`_SignalVisitor` now has a `visit_AnnAssign` alongside `visit_Assign`, both routing
through the same `_record` helper. Verified directly (no such declaration exists yet
in this codebase to exercise naturally) with a standalone AST smoke test against a
synthetic snippet containing both `plain = pyqtSignal(str)` and
`annotated: "pyqtSignal" = pyqtSignal(int)` inside one class — both were captured.

## Final verification (after all five fixes)

```
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
367 passed, 2 skipped in 1.54s
```

```
$ QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
443 passed in 128.64s (0:02:08)
```

```
$ .venv/bin/ruff check . && .venv/bin/ruff format --check .
All checks passed!
95 files already formatted
```

```
$ .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
Success: no issues found in 24 source files
```

Manual orphan re-check, all still correct:

```
== picks_changed connects ==          (none)
== new_site_requested/open_site_requested/save_requested connects ==   (none, all three)
== pick_requested total connects ==   packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py:197
== error total connects ==            packages/nsgeo-qgis/nsgeo_qgis/plugin.py:185
== set_pick_mode callers ==           (only a comment mentioning the name, no call)
```

## Remaining uncertainty

None new from this round. The M7 manual acceptance checklist (real-QGIS, 10 items)
still has not been run, as noted in the original report.

---

# Fix report (post-review round 2)

## Finding 6 (Important) — once a name is pinned, further classes declaring it are unguarded

Confirmed the gap by injection: added a throwaway third class declaring an
unconnected `error` signal, and the existing `SHADOWED_CONNECT_COUNTS` table (which
pinned only the connect count) left the suite green -- the connect count it already
expected (1) never moved, so a brand new orphan joining an already-pinned name was
invisible.

Fix: renamed the table to `SHADOWED` and pinned two numbers per name instead of one --
`declared` (how many classes declare the name) and `connects` (how many connects
exist):

```python
SHADOWED = {
    "pick_requested": {"declared": 2, "connects": 1},
    "error": {"declared": 2, "connects": 1},
}
```

`test_every_shadowed_signal_name_is_pinned` is unchanged in purpose (still catches a
brand-new shadowed name). The old `test_shadowed_connect_counts_match_reality` was
replaced with `test_shadowed_signals_match_their_pinned_shape`, which checks both
numbers for every pinned name and fails if either drifts in either direction.

**Injection evidence** (`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py -q -p no:xonsh`), captured before committing:

1. Baseline, before injection: `4 passed`.

2. Added `packages/nsgeo-qgis/nsgeo_qgis/_injection_probe.py`:
   ```python
   class ThirdClassSharingError(QObject):
       error = pyqtSignal(str)  # unconnected -- a third, new orphan on a new class
   ```
   Result:
   ```
   FAILED packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py::test_shadowed_signals_match_their_pinned_shape
   AssertionError: shadowed signals no longer match their pinned shape, as (expected, actual)
   pairs: {'error': {'declared': (2, 3), 'connects': (1, 1)}}. ...
   1 failed, 3 passed in 0.29s
   ```
   The third, unconnected declaration is caught by the `declared` count moving from 2
   to 3, exactly the case Finding 6 identified as invisible before this fix. Deleted
   the probe file afterward (never committed).

3. Flipping either pinned number in either direction, one mutation at a time, each
   reverted immediately after:
   - `"error": {"declared": 1, "connects": 1}` (declared, too low) → **FAILED**
     (`test_shadowed_signals_match_their_pinned_shape`)
   - `"error": {"declared": 3, "connects": 1}` (declared, too high) → **FAILED**
   - `"error": {"declared": 2, "connects": 0}` (connects, too low) → **FAILED**
   - `"error": {"declared": 2, "connects": 2}` (connects, too high) → **FAILED**

   All four mutations produced the same assertion failure at
   `test_shadowed_signals_match_their_pinned_shape`; the file was restored to the
   correct table after each and reverified green (`4 passed`) before moving to the
   next.

## Three observations from the review, left unchanged as instructed

- Shadow detection keys on class name only (a same-named class in another module
  would collide) -- safe today, not fixed.
- `dispose()` leaves `canvas.destinationCrsChanged` and the session signals
  connected -- harmless now that `_on_lines_changed`/`_refresh` carry disposal
  sentinels, not fixed.
- `eb2e2a5`'s commit message still names the wrong layer-replacement mechanism --
  history left as-is; the corrected docstrings are what people read going forward.

## Final verification (after Finding 6's fix)

```
$ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
367 passed, 2 skipped in 1.64s
```

```
$ QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
443 passed in 131.68s (0:02:11)
```

```
$ .venv/bin/ruff check . && .venv/bin/ruff format --check .
All checks passed!
95 files already formatted
```

```
$ .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
Success: no issues found in 24 source files
```

Test counts unchanged from the previous round (367 / 443): this round renamed and
restructured one test rather than adding a new one, by design -- the shape check
replaces the connect-only check outright rather than sitting alongside it.
