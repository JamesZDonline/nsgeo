# Task 5 report: selecting a pick or a mark jumps to it; marks confirmed; the milestone closes

## Status: DONE

## What I implemented

`packages/nsgeo-qgis/nsgeo_qgis/map_link.py`:

- Added `NULL` to the `qgis.core` import.
- Added `MapLink.SELECTABLE = ("lines", "picks", "marks")` beside `HOVER_DWELL_MS`,
  with the brief's comment verbatim.
- `__init__`: replaced the single `_lines_layer_bound: QgsVectorLayer | None`
  attribute with `self._bound: dict[str, QgsVectorLayer | None] =
  dict.fromkeys(self.SELECTABLE)` and `self._selection_slots`, a dict mapping
  each of the three layer names to its own bound-method slot
  (`_on_selection`, `_on_pick_selection`, `_on_mark_selection`) — one NAMED
  slot per layer, per the brief, so `disconnect()` can reliably take each
  back off.
- `_lines_layer()` is kept as a thin wrapper over a new general
  `_selectable_layer(name)` lookup (same `sip.isdeleted` guard as before);
  `_geometries()` and `_hit_test`/`_on_selection` still call `_lines_layer()`
  unchanged.
- `_rebind_layer()`: docstring's first line changed to "Follow the
  selectable layers across rebuilds."; every existing paragraph left
  untouched; the brief's one new paragraph appended at the end explaining
  why `picks`/`marks` are rebound on the same signals. The body was
  replaced with a loop over `SELECTABLE` that disconnects the old bound
  layer's slot (same `TypeError`/`RuntimeError` suppression as before) and
  reconnects the current layer's slot, per layer.
- Added `_on_pick_selection` / `_on_mark_selection` (each a try/except slot
  that calls `_jump_to_feature` and logs via `_log(..., Critical)` on
  failure) and the shared `_jump_to_feature(name, trace_field)`: resolves
  the one selected feature, opens its `line_key` via `session.open_line`
  (guarding "not exactly one selected" and "key not in session.keys()"),
  then sets the trace via `session.set_trace(key, int(trace))` — guarded
  against `trace == NULL` (the hand-digitised-pick case) so `int(NULL)`
  never raises inside the slot. `open_line` strictly before `set_trace`,
  per the brief's ordering requirement.
- `dispose()`: docstring paragraph wording changed in place from "The
  `lines` layer's `selectionChanged` connection" to "Each selectable
  layer's `selectionChanged` connection" — no other docstring text moved
  or reworded. Body: the single-layer unbind block replaced with a loop
  over `SELECTABLE` that pops each bound layer from `self._bound`, sets it
  to `None`, and disconnects its slot under the same `sip.isdeleted` /
  `contextlib.suppress(TypeError, RuntimeError)` guard as before.
- `_on_lines_changed`'s disposal sentinel (`if self._marker is None or
  self._band is None: return`) was left untouched, per the brief — it
  already covers the rebind for all three layers since `_rebind_layer` now
  iterates `SELECTABLE`.

`packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py`:
- Added `QgsFeature`, `QgsGeometry` to the `qgis.core` import.
- Appended the brief's nine tests verbatim, unchanged: the two "jumps to it"
  tests (pick, mark), the read-only confirmation, the multi-selection
  no-op, the NULL-trace pick, two disposal tests, the site-reopen test, and
  the `@needs_real_data` mark test. No test needed adjustment — every one
  ran and asserted the state its name claims (see TDD Evidence below for
  the one case I checked particularly closely: the real-data test's skip
  path).

`packages/nsgeo-qgis/README.md`: added the `### Picking` section verbatim,
directly after `### The map ↔ profile link` (confirmed by `git log` that
this, not the top-level `README.md`, is where M7's map-link section
actually went — `eb2e2a5` touched only this file).

`packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py`: fixed the stale
`SHADOWED_CONNECT_COUNTS` → `SHADOWED` in the comment above `KNOWN_UNCONSUMED`
(line 23–24). No other change to this file.

## What I tested and the results

### TDD Evidence

**RED** — before implementation:
```
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest \
  packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py -q -p no:xonsh
```
```
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py::test_selecting_a_pick_opens_its_line_and_moves_the_trace
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py::test_selecting_a_mark_opens_its_line_and_moves_the_trace
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py::test_a_pick_with_no_trace_jumps_to_the_line_and_stops_there
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py::test_jumping_from_a_pick_still_works_after_the_site_is_reopened
4 failed, 49 passed, 1 skipped in 61.34s (0:01:01)
```
Expected and exactly matched: the four tests that assert `current_key`/
`current_trace` actually change on selection failed (`assert 'raw/FILE__001.DZT'
== 'raw/FILE__002.DZT'`-shaped failures — nothing currently binds `picks`/
`marks`, so selection did nothing). The negative-shaped tests (multi-select
jumps nowhere, both disposal tests, read-only) already passed with no code,
exactly as the brief predicted — they assert "nothing happened," which was
already true before any of Task 5's code existed.

**GREEN** — after implementation:
```
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest \
  packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py -q -p no:xonsh
```
```
53 passed, 1 skipped in 62.99s (0:01:02)
```
The 1 skip is `test_selecting_a_real_files_mark_jumps_to_its_own_scan`
(`@needs_real_data`), which took its own `pytest.skip("the real DZX
sidecars carry no marks")` branch — see "Real-data note" below.

### Both tiers, full run

Pure:
```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
```
```
367 passed, 2 skipped in 1.60s
```
Matches baseline exactly (baseline was `367 passed, 2 skipped`).

QGIS:
```
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
```
```
517 passed, 1 skipped in 192.72s (0:03:12)
```
Baseline was `509 passed` (0 skipped). Net: +8 passing (9 new tests, 1 of
which skips), 1 skip overall — matches the file-level run above.

Lint/types:
```
.venv/bin/ruff check .                     -> All checks passed!
.venv/bin/ruff format --check .            -> 95 files already formatted
.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
                                            -> Success: no issues found in 24 source files
```

### Real-data note (not a defect)

`test_selecting_a_real_files_mark_jumps_to_its_own_scan` skips on this
machine's local data with "the real DZX sidecars carry no marks". I checked
why: of the nine real `FILE__00N.DZX` sidecars under
`packages/nsgeo-core/tests/data/local/`, only `FILE__007.DZX` actually
contains a `<WayPt>` mark; the test's `marked[:2]` (sorted `REAL_DZT`,
filtered to those with a `.DZX`, first two) picks `FILE__001`/`FILE__002`,
neither of which has one. This is exactly the case the brief's own
`pytest.skip(...)` branch exists for, so the test is running and reaching
the state it claims (it correctly finds 0 marks and skips rather than
false-passing) — it just doesn't get to exercise the real-mark assertion on
*this* local dataset. Not something I changed; flagging per "be
specifically suspicious of whether each test's setup actually reaches the
state its name claims" — here it does reach the right state, that state
just isn't the happy path on this machine.

### Disposal evidence (Step 5)

Used `receivers()` directly — it is available for these Python-side
`pyqtSignal`s on this build, so no behavioural fallback was needed. One fix
to the brief's script: it did not put `packages/nsgeo-core` on `sys.path`,
so `plugin_testing.synthetic_dzt`'s `from tests.synthetic import
write_dzt` raised `ModuleNotFoundError: No module named 'tests.synthetic'`
(the pytest tier gets this path from `tests/conftest.py`'s own
`sys.path` setup, which a bare script run outside pytest does not). Added
`sys.path.insert(0, "packages/nsgeo-core")` before running; no other
change. The four printed rows:

```
no link:                 {'lines': 1, 'picks': 1, 'marks': 1}
link constructed:        {'lines': 2, 'picks': 2, 'marks': 2}
after dispose:           {'lines': 1, 'picks': 1, 'marks': 1}
after a second dispose:  {'lines': 1, 'picks': 1, 'marks': 1}
OK: all three bound on construction, all three released on dispose, idempotent
```
Baseline is 1 receiver per layer, not 0 — `SiteLayers` itself already has a
connection to each layer's `selectionChanged` (unrelated to `MapLink`). The
delta is what the brief's assertions check, and it holds exactly: +1 on
construction, back to baseline on first dispose, unchanged on the second
(idempotent).

### No-orphans evidence (Step 7)

```
for name in add_pick picks_for set_pick_store pick_store write_pick set_pick_mode; do
  echo "== $name =="
  grep -rn "\.$name" packages/nsgeo-qgis/nsgeo_qgis/ | grep -v "def $name"
done
echo "== Pick (the record) =="
grep -rn "\bPick\b" packages/nsgeo-qgis/nsgeo_qgis/ | grep -v "pyqtSignal"
```

Results:
- `add_pick` — called at `plugin.py:480` (`self.session.add_pick(key, trace, time_ns)`). Has a caller.
- `picks_for` — called at `session.py:897` (`self._pick_store.picks_for(key)`, i.e. `SiteLayers.picks_for`) and `profile_dock.py:457` (`self.session.picks_for(key)`, i.e. `SiteSession.picks_for`). Both declarations have a caller.
- `set_pick_store` — called at `layers.py:222` (`session.set_pick_store(self)`). Has a caller.
- `pick_store` — **zero production hits.** Only reference anywhere in the plugin is `packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py:1469` (`assert session.pick_store is layers`). `SiteSession.pick_store` (the public read-property counterpart to `set_pick_store`) has no production caller. Pre-existing from Task 1 (the property and its setter), not introduced by this task, not a `pyqtSignal` so outside the automated no-orphan-signals check's scope, and not a file Task 5's brief authorizes me to touch — flagged as a concern below rather than acted on.
- `write_pick` — called at `session.py:867` (`self._pick_store.write_pick(pick)`). Has a caller.
- `set_pick_mode` — called at `plugin.py:461` (`self.profile_dock.set_pick_mode(bool(checked))`) and `profile_dock.py:601` (`self.view.set_pick_mode(bool(flag))`, i.e. `ProfileView.set_pick_mode`). Both declarations have a caller.
- `Pick` (the record) — constructed/used throughout `session.py` and `layers.py` (e.g. `session.py:852` `pick = Pick(...)`, `layers.py:946` `return Pick(...)`) — not an orphan, it's the dataclass every pick-handling call above passes around.

Ledger status, confirmed against the code as it stands:
- `picks_changed` — **adopted**: not in `KNOWN_UNCONSUMED` (confirmed by reading the set, which holds only `new_site_requested`, `open_site_requested`, `save_requested`); connected at `profile_dock.py:217` (`session.picks_changed.connect(self._on_picks_changed)`).
- `ProfileDock.pick_requested` — **adopted**: `SHADOWED["pick_requested"] == {"declared": 2, "connects": 2}` (confirmed by reading `SHADOWED`).
- `ProfileView.set_pick_mode` — **adopted**: called by `ProfileDock.set_pick_mode` at `profile_dock.py:601` (confirmed above).
- `ParamForm.error` — **still an orphan**, still pinned: `SHADOWED["error"] == {"declared": 2, "connects": 1}`.
- `SurveyDock.new_site_requested` / `open_site_requested` / `save_requested` — **still dead**, still in `KNOWN_UNCONSUMED`, all three present, unchanged.

**Did M8 add any new orphan?** No new *signal* orphan — `test_every_declared_signal_has_a_connect` (part of the full pure-tier run above, 367 passed) confirms this mechanically; Task 5 added no new `pyqtSignal` at all. The one thing this manual sweep turned up, `SiteSession.pick_store` having no production caller, is a pre-existing method-level (non-signal) gap from Task 1, not something Task 5 introduced — see the concern below.

## Files changed

- `packages/nsgeo-qgis/nsgeo_qgis/map_link.py`
- `packages/nsgeo-qgis/README.md`
- `packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py`

## Self-review findings

- Diffed `map_link.py` against the brief's exact snippets line by line
  after writing them — no drift. In particular double-checked the
  `dispose()` docstring edit: my first attempt at that edit accidentally
  duplicated the "lines layer's selectionChanged connection" sentence
  instead of reword-in-place; caught it before running any tests and
  corrected it to a single in-place wording change, leaving the paragraph
  order and every other sentence exactly as it was.
- Confirmed `_lines_layer_bound` has zero remaining references anywhere in
  the file after the rewrite (`grep` came back empty).
- Confirmed every new slot (`_on_pick_selection`, `_on_mark_selection`)
  catches its own exceptions and logs via `_log(..., Critical)`, matching
  every other slot in the module.
- Confirmed the `test_jumping_from_a_pick_still_works_after_the_site_is_reopened`
  test's `session.save()` / `close_site()` / `open_site()` sequence needs no
  `answer_modal`: neither `session.py` nor `layers.py` calls any
  `QMessageBox`/`QDialog`/etc., and the pre-existing, structurally identical
  `test_promotion_still_works_after_the_lines_layer_is_rebuilt` (same
  save/close/reopen shape, already in this file before Task 5) needs none
  either.
- Verified the diff stat for the test file is exactly the import-line
  change plus the appended block (`202 insertions, 1 deletion`) — nothing
  else in that file was touched.

## Issues or concerns

- **`SiteSession.pick_store` (the public property) has no production
  caller anywhere in the plugin** — only a test touches it (see Step 7
  above). This predates Task 5 (added in Task 1 alongside `set_pick_store`)
  and is a property, not a `pyqtSignal`, so it's invisible to the automated
  `test_no_orphan_signals.py` check, which only tracks signal declarations.
  I did not modify or remove it — it's outside this task's file list and
  outside its "no new orphan" scope (M8 didn't introduce it) — but it's
  worth someone deciding whether it should gain a caller, be documented as
  intentionally test-only, or be removed.
- **Manual QGIS walkthrough not performed by me.** The brief's "M8
  acceptance" section (14 numbered steps plus "open a pre-M8 site package")
  is an explicit human-in-QGIS gate that has to happen before any merge
  proposal, per this repo's own "deploy + walkthrough before merge" rule. I
  have not run `dev_link.py --profile ns_geo` or exercised the plugin
  interactively — that checkpoint is still outstanding and belongs to
  whoever does the manual walkthrough next, not to automated test evidence.
- No other concerns. Both tiers exceed baseline, ruff/mypy are clean, and
  the diff matches the brief's snippets exactly except for the one
  self-caught docstring-duplication slip (fixed before any test run) and
  the one sys.path fix needed to run the Step 5 script outside pytest.

## Commits

`47d4e69` — `feat: selecting a pick or a mark jumps to its line and trace`,
pushed to `origin/nsgeo-m8`.

---

## Fix round 1

Three items: one Important (the real-data mark test can never run), two
folded Minors (a `KeyError` reachability gap in `dispose()`/`_rebind_layer`,
and the `pick_store` orphan gate left open with no comment).

### What I changed

**Important 1 — `test_selecting_a_real_files_mark_jumps_to_its_own_scan`**
(`packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py`): rewrote the
test per the reviewer's exact prescription. It now:
- Looks up `FILE__007.DZT` explicitly (the one real sidecar in this
  dataset with a `<WayPt>`, per the reviewer's own inspection: scan 634,
  635 traces, so the mark is the file's last trace) instead of `sorted(...)
  [:2]`, which always picked the two guaranteed-unmarked files.
- Picks a second, distinct real file (`other_path`) to be the unmarked
  line, and orders `lines = [other_path_line, marked_path_line]` so
  `keys[0]` (opened first) is the unmarked one and `keys[1]` is the marked
  one — guaranteed by construction, not by hoping `session.keys()`
  preserves insertion order by luck (confirmed it does:
  `SiteSession.keys()` returns `list(self._lines_by_key)`, and
  `add_lines` inserts in the given list's order).
- Drops the `next((...), marks[0])` fallback entirely. `marked_key =
  keys[1]` is asserted `!= session.current_key` right after opening
  `keys[0]`, so the test cannot pass without the selection actually moving
  `current_key`.
- Skip condition narrowed to "no `FILE__007.DZT` and a second real file
  present" — the only case the data genuinely cannot support this test,
  as the reviewer specified.

**Minor 2 — `dispose()` / `_rebind_layer` `KeyError` gap**
(`packages/nsgeo-qgis/nsgeo_qgis/map_link.py`): both loops now iterate
`self._selection_slots.items()` directly instead of `self.SELECTABLE`
with a separate `self._selection_slots[name]` lookup, per the reviewer's
"make the slot table the single source of truth" instruction. A name
present in `SELECTABLE` but absent from `_selection_slots` can no longer
raise inside either method — the loop simply wouldn't visit it. Added a
short comment at each loop site naming the failure this closes (a
`KeyError` aborting `dispose()` before its scene-removal loop runs is
Item I4's leak reached a different way). Left `sip.isdeleted(layer)`
exactly as it was in both loops, per the reviewer's explicit "leave that
asymmetry alone" instruction — untouched.

**Minor 3 — `SiteSession.pick_store`**
(`packages/nsgeo-qgis/nsgeo_qgis/session.py`): added the reviewer's
comment (lightly extended) directly on the property, explaining it is the
read half of `set_pick_store`, has no production caller, and is kept
deliberately for the symmetry and the test-visible assertion it enables.
Did not delete or otherwise change the property.

**Report correction (no code change):** the "Real-data note" and
"Disposal evidence" sections above previously attributed the
`receivers()` baseline of 1 to `SiteLayers` holding its own
`selectionChanged` connection. Per the reviewer, that's wrong — `SiteLayers`
has no such connection; the extra receiver is QGIS's own (most likely
`QgsProject`'s aggregated signal). The delta-based assertions in Step 5
are unaffected either way. Correcting the record here rather than editing
the sentence in place above, so the fix-round trail stays visible: **the
baseline-1 receiver per layer is QGIS's own connection, not `SiteLayers`'s.**

### Covering tests

- `test_selecting_a_real_files_mark_jumps_to_its_own_scan` (rewritten) —
  the only test covering Important 1.
- Every test in `test_plugin_map_link.py` — none of Minor 2's change is
  behavior-visible under correct data (`SELECTABLE` and
  `_selection_slots` agree today), so the full file re-run is what
  demonstrates no regression; there is no reachable-today failure mode to
  add a test for (the reviewer confirmed this is "not reachable today,"
  which is exactly why it's Minor).
- Minor 3 is a comment-only change; no test applies or is needed.

### Commands and output

**1. Focused file, `-rs`, to prove zero skips:**
```
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest \
  packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py -q -p no:xonsh -rs
```
```
......................................................                   [100%]
54 passed in 63.48s (0:01:03)
```
54 passed, **zero skipped** (was `53 passed, 1 skipped` before this round;
+1 net because the real-data test now actually runs instead of skipping).

**2. Mutation proof** — commented out `self.session.set_trace(key,
int(trace))` in `_jump_to_feature` (the only line in the whole diff that
sets the trace), re-ran the file:
```
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest \
  packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py -q -p no:xonsh -k "jump or selecting"
```
```
E       assert -1 == 634
E        +  where -1 = <nsgeo_qgis.session.SiteSession object at 0x7577f8b43c80>.current_trace
...
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py::test_selecting_a_pick_opens_its_line_and_moves_the_trace
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py::test_selecting_a_mark_opens_its_line_and_moves_the_trace
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py::test_jumping_from_a_pick_still_works_after_the_site_is_reopened
FAILED packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py::test_selecting_a_real_files_mark_jumps_to_its_own_scan
4 failed, 6 passed, 44 deselected in 13.00s
```
`test_selecting_a_real_files_mark_jumps_to_its_own_scan` is in the failure
list (`assert -1 == 634`) — it genuinely exercises the trace jump and
fails when that code path is disabled. Reverted the mutation immediately
after (`diff` against the pre-mutation copy came back empty, confirming
an exact restore), then reran the file clean: `54 passed in 63.37s`, 0
skipped, before committing.

**3. Disposal proof, re-run because `dispose()` was touched:**
```
no link:                 {'lines': 1, 'picks': 1, 'marks': 1}
link constructed:        {'lines': 2, 'picks': 2, 'marks': 2}
after dispose:           {'lines': 1, 'picks': 1, 'marks': 1}
after a second dispose:  {'lines': 1, 'picks': 1, 'marks': 1}
OK: all three bound on construction, all three released on dispose, idempotent
```
Identical shape to the pre-fix-round run — the `_selection_slots.items()`
change is not behavior-visible here, as expected.

**4. Ruff:**
```
.venv/bin/ruff check .            -> All checks passed!
.venv/bin/ruff format --check .   -> 95 files already formatted
```

Full-tier reruns were not required for this round per the coordinator's
instructions and were not performed; the focused file plus ruff above are
the complete verification for this round.

### Files changed (this round)

- `packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py`
- `packages/nsgeo-qgis/nsgeo_qgis/map_link.py`
- `packages/nsgeo-qgis/nsgeo_qgis/session.py`

### Commit

`68fb533` — `fix: make the real-mark test actually jump, and close two
review gaps`, pushed to `origin/nsgeo-m8`.
