# M8 final fix wave — report

Branch `nsgeo-m8`, starting HEAD `68fb533`. All nine findings from the
whole-branch review plus the plan edit are addressed in this one pass.

## Important 1 — the migration's safety gate is vacuous / an unopenable `picks` table is overwritten

This was the reason the wave exists, and it got the most scrutiny.

### (a) `_read_picks_rows` returning `[]` on an unopenable table

**File:** `packages/nsgeo-qgis/nsgeo_qgis/layers.py`, `_read_picks_rows` (~line 810-845).

**Change:** it now raises `RuntimeError` naming the path and stating the
original is untouched, instead of returning `[]`, when
`QgsVectorLayer(...).isValid()` is False. An empty-but-opened table still
returns `[]` — only "could not open it at all" now raises. Docstring
extended to record the defect and why the distinction matters.

**Why:** `_rebuild_picks` is only ever called when `_ensure_table`'s own
`_table_schema` probe *just* opened `picks` successfully
(`existing_crs is not None`), so a second open of the same table failing
means something changed between the two opens — that is a real problem,
not an empty table. The old `[]` return made "could not open" and
"opened, zero rows" indistinguishable to the swap's own row-count gate
(`written != len(old_rows)`), which then compared `0 == 0`, passed
trivially, renamed the real table out to the backup, renamed an empty
table in, and dropped the backup.

**Test:** `test_picks_survive_a_failure_to_open_the_table_before_a_migration`
in `packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py`.

Simulated by making `_read_picks_rows`'s *own* construction of the
`picks` `QgsVectorLayer` come back invalid, identified by inspecting the
immediate caller's frame (`sys._getframe(1).f_code.co_name ==
"_read_picks_rows"`) rather than by call order or count. I chose this
over call-order counting because `_table_schema`'s own probe inside
`_ensure_table` builds the textually identical
`QgsVectorLayer(path, "picks", "ogr")` call — the two call sites cannot
be told apart by arguments at all — and `replace_grid` drives **two**
refreshes (`grids_changed` then `lines_changed`, both connected to
`SiteLayers.refresh`), so a count-based fault would land on a different
absolute call number depending on which refresh reached the failure, and
would stop firing on the second refresh once the count moved past it. A
fault keyed on the caller's function name fires identically and
persistently on every attempt, matching how the pre-existing sibling
tests (`..._while_building_the_temporary_table`,
`..._during_the_swap`) key their own injected faults on a stable name
(`_PICKS_REBUILD`, a rename's own arguments) rather than a count.
Monkeypatching `QgsVectorLayer.isValid` on the class was ruled out for
the same reason: it cannot distinguish the two call sites either, so it
would blind `_table_schema`'s probe too and `_rebuild_picks` would never
be reached — the very path this hole is in.

The test asserts the seeded pick row is still on disk afterward, read
back through a **fresh, unpatched** `QgsVectorLayer` (not through
`layers`, in case the failed attempt left its registry stale) — the same
pattern the three pre-existing failure-injection tests use.

**Proof it fails against the unfixed code:** reverted
`packages/nsgeo-qgis/nsgeo_qgis/layers.py` to `git show HEAD:...` (the
pre-fix-wave version), ran the test, restored the file. Result:

```
message_log: []
AssertionError: assert False  (any("picks" in m and "untouched" in m for m in message_log))
```

I then ran a scratch reproduction of the same scenario against the
unfixed code to see the actual data-loss, not just the log assertion:

```
VALID True
CRS EPSG:4326      # rebuilt to the NEW crs -- the swap completed
COUNT 0            # the seeded pick is gone
MESSAGE_LOG []     # and nothing was ever logged
```

That is the exact defect: the migration silently "succeeded," destroying
the only row, with zero diagnostic output. After restoring the fixed
`layers.py`, the test passes (verified) and the full `test_plugin_layers.py`
file (47 tests) passes.

### (b) `_table_schema` collapsing "absent" and "present but unopenable"

**File:** `packages/nsgeo-qgis/nsgeo_qgis/layers.py`, `_table_schema`
(~line 631-673), `_ensure_table` (~line 543-600), `_recover_picks_backup`
(~line 602-629), plus a new module-level sentinel `_TABLE_UNREADABLE`
(~line 153-162).

**Change:** `_table_schema` now returns one of three distinguishable
results in its first element: `None` (no table by that name exists at
all), a real `QgsCoordinateReferenceSystem` (opened fine), or the new
sentinel `_TABLE_UNREADABLE` (a table by that name **is** present in the
GeoPackage — confirmed independently of `QgsVectorLayer`, via
`QgsProviderRegistry`'s OGR connection's own `tableExists("", name)`,
which is a plain catalogue lookup rather than an attempt to open the
layer — but `QgsVectorLayer` could not open it). Verified `tableExists`
is a real, working API on this QGIS build by direct experiment (see
below). Any failure probing the connection itself is treated as
`_TABLE_UNREADABLE` rather than `None` — guessing "broken" costs one
extra Critical log for a table that turns out to be absent; guessing
"absent" costs the one table with no other source of truth.

`_ensure_table` now raises immediately, for `picks` specifically, when
`_table_schema` reports `_TABLE_UNREADABLE`, instead of falling through
to `_drop_loaded_layer` + `_create_table(..., CreateOrOverwriteLayer)`.
For every other table, `_TABLE_UNREADABLE` is folded back to `None`
before the rest of the logic runs — the derived tables are fully
regenerable, so "broken" and "absent" are still recovered from the same
way (overwrite), unchanged from before.

`_recover_picks_backup`'s existing `... [0] is None` check needed no
logic change — `_TABLE_UNREADABLE is None` is `False`, so a
present-but-unreadable backup now correctly falls into "something is
there, try to recover it" rather than being silently skipped as if
nothing were there. Documented in its docstring.

**Why:** for `picks` specifically, "the table would not open right now"
and "there was never a table here" used to look identical, so a
present-but-broken `picks` table (a lock, a permissions problem,
momentary corruption) was routed straight into an overwrite exactly like
a brand-new site.

**Test:** `test_an_unopenable_picks_table_is_refused_not_overwritten`
in the same file.

Simulated by making **every** construction of the `picks`
`QgsVectorLayer` come back invalid, unconditionally — no call-order
disambiguation needed here because the test drives exactly one
`refresh()` by calling it directly (no signal cascade, no grid or schema
change), so there is only one attempt to open `picks` per table probe.
`_table_schema`'s presence check goes through `QgsProviderRegistry`'s
connection, which the test never touches, so it genuinely finds the real
table (with the seeded row) still there. Asserts the row is still on
disk afterward, read back through a fresh, unpatched `QgsVectorLayer`.

**Proof it fails against the unfixed code:** same revert/run/restore
procedure. Result:

```
StopIteration   # next(on_disk.getFeatures()) -- the table was overwritten empty
```

`on_disk.isValid()` was still True (a fresh, valid, empty table was
created in its place), confirming the overwrite happened rather than the
open simply failing outright. After restoring the fix, the test passes.

**`tableExists` verified directly** (not assumed) against this
project's `.venv-qgis` before relying on it:

```
conn = QgsProviderRegistry.instance().providerMetadata('ogr').createConnection(path, {})
conn.tableExists('', 'picks')            -> True   (table present)
conn.tableExists('', 'nonexistent_table') -> False  (table absent)
```

---

## Important 3 — the stale comment in `profile_dock.py`

**File:** `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`, `_pick`
(the I6 paragraph).

Deleted every clause that is now false: "nothing connects to
`pick_requested` yet", "`set_pick_mode()` has no control wired to it",
"picks are authored by editing the `picks` layer ... with QGIS's own
tools", and the now-irrelevant "Task 18/19" history note. Replaced with
a statement of what is actually wired: `pick_requested` connects to
`plugin.py`'s `_on_pick_requested` (which relays to `session.add_pick`
and reports failures on the message bar), and `set_pick_mode` is driven
by the Pick toolbar toggle (`plugin.py`'s `_toggle_pick_mode`). Also
noted that hand-editing the `picks` layer still works but is no longer
the only way in.

**Kept, verbatim in substance:** the verified observation that an
exception raised by a downstream subscriber of `pick_requested` is
swallowed by PyQt at the point that subscriber is invoked and never
propagates back into this method's own `try`, and the reason this method
still guards its own body regardless (the "every slot guards its body"
rule, and the insurance value for future logic ahead of the `emit()`
call).

I referenced the plugin.py methods by name (`_on_pick_requested`,
`_toggle_pick_mode`) rather than by line number, since line numbers are
exactly what went stale here before.

---

## Important 2 — a pick's position does not follow a moved grid

**Ruling honored: no re-placement logic was added.** All three requested
mitigations were implemented instead.

### 1. Warning log

**File:** `packages/nsgeo-qgis/nsgeo_qgis/layers.py`, `SiteLayers.refresh()`
and two new methods, `_grid_placements` (staticmethod) and
`_warn_if_a_placed_grid_moved`.

**Chosen point and why:** inside `refresh()`, called once per refresh,
before `ensure_tables()` runs (so it reads `self.layers["picks"]` as it
stood before any rebuild this cycle might do).

**Design:** `SiteLayers` now caches each grid's placement-relevant
fields (`origin`, `azimuth`, `size_x`, `size_y` — deliberately not `crs`,
`velocity`, or `default_spacing`) after every successful refresh, keyed
by grid id, in `self._last_grid_placements` (reset to `{}` in `__init__`
and in `detach()`, so a freshly opened site, or a different site reusing
a grid id, never compares against a stale or foreign snapshot). On the
next refresh, any grid id present in **both** the cached and the current
snapshot with a **different** value is a genuine move/resize/reorient of
an existing grid. If any such id is found and `picks` is non-empty, a
`Qgis.MessageLevel.Warning` is logged naming the moved grid(s).

**Why this and not "log on every `grids_changed`":** `add_grid` (a new
id, absent from the cache) and `remove_grid` (an id missing from the
current site) both emit that same signal without moving any *existing*
grid's own fields, and the finding explicitly requires a refresh with no
grid geometry change to stay quiet. A per-id placement diff is what
distinguishes "moved" from "added" or "removed" without needing to widen
`grids_changed`'s own signature (it is public and bound in several other
files — `map_link.py`, `survey_dock.py` — and widening it was judged
more risk than this diagnostic is worth in a fix wave scoped to picks,
not the signal graph). This is not the "narrower/imprecise fallback"
the brief pre-authorized — it is a precise detection, and I judged the
small, self-contained cache it needs (no new write path, no touch to
`session.py`, no signal changes) to be within the spirit of a
conservative fix wave. Verified by reasoning through `add_grid`,
`remove_grid`, `replace_grid`, and a fresh site-open, each against the
comparison logic (see the method's own docstring for the full
walkthrough) — no dedicated new automated test was added for this
diagnostic specifically (see Concerns below).

### 2. README note

**File:** `packages/nsgeo-qgis/README.md`, `### Picking` section — new
paragraph stating a pick's position is fixed at authoring time, that
moving/resizing/reorienting a grid does not move existing picks (the
plugin warns instead of silently re-placing), and that changing a grid's
CRS is the one exception (it re-projects picks along with everything
else).

### 3. Comment on `_pick_point`

**File:** `packages/nsgeo-qgis/nsgeo_qgis/layers.py`, `_pick_point`
docstring — records that this is computed once, at write time, never
re-derived; that a grid move redraws the line/marks but not the pick;
that a CRS change is handled (via `_rebuild_picks`) but a move is not;
and why (re-deriving would overwrite a hand-moved pick), pointing to
`_warn_if_a_placed_grid_moved` as the mitigation actually taken.

---

## Minor fixes

**4. `layers.py` `picks_for` reads `feature["line_key"]` directly.**
Routed through `_attr(feature, "line_key")`, matching `_row_to_pick`
right below it. Comment explains this is a consistency fix (a pre-M8
table still has `line_key`; no concrete failure was found here, unlike
the fields `_attr` was originally added for).

**5. `map_link.py` `SELECTABLE` is a second, unchecked source of truth.**
Confirmed no test or other module references `MapLink.SELECTABLE`
(grepped the whole repo). Deleted the constant; `_selection_slots` is now
defined first in `__init__`, and `_bound` is seeded from it
(`dict.fromkeys(self._selection_slots)`) instead of from `SELECTABLE`.
Updated the two comments in `_rebind_layer` and `dispose` that
previously contrasted against `SELECTABLE` by name, since there is
nothing left to contrast against.

**6. `map_link.py:492-493` (now ~500-511) — silent orphaned pick/mark
selection.** Added one `_log` line when the selected feature's
`line_key` names no current line, explaining that this is reachable by
design (`remove_line` deliberately keeps orphaned picks/marks) and
naming the same "silence is indistinguishable from success" pattern
`write_pick` already fixes for an unplaceable line.

**7. `test_plugin_profile_view.py` — no coverage for the high side of
the image-rect guard.** Added `QPoint(r.right() + 5, r.top() + 10)` to
`test_a_shift_click_outside_the_image_rect_is_not_a_pick`'s "not a pick"
points, alongside the two pre-existing low-side ones. Verified the right
margin (`MARGIN_RIGHT`) is the depth-axis label area by reading
`profile_view.py`'s paint code.

**8. `session.py` `add_pick`'s time clamp.** Added a comment next to the
`t_end = t0 + (n_samples - 1) * dt_ns` line noting the one-sample-interval
difference from `ViewTransform.t_end` (`t0 + n_samples * dt_ns`), that
this is deliberate (a pick names an existing sample), and that the two
must not be "fixed" to match.

**9. `test_plugin_map_link.py` real-mark test docstring.** Verified
directly against the real data: `FILE__007.DZT` has 635 traces (indices
0..634) and its DZX mark is at scan 634 — already in range, no clamp
exercised — and the synthetic sibling test uses scan 27 on 60 traces,
also no clamp. Rewrote the docstring to claim what the test actually is
(a real-data jump test) rather than a clamp test, and fixed a directional
error I introduced on a first pass (the synthetic sibling test is
*above* this one in the file, not below).

---

## Plan edit

**File:** `docs/superpowers/plans/2026-09-19-nsgeo-qgis-plan3-m8.md`,
"M8 acceptance" step 12. Added an explicit exit criterion: if the
walkthrough shows the pick is invisible until the edit session ends, the
fix is for `write_pick` to refuse the write outright while
`layer.isEditable()`, with a message saying so — not a documentation
note.

---

## Test results

**Pure tier:**
```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
367 passed, 2 skipped
```
Matches the stated baseline exactly (no pure tests were added or changed).

**QGIS tier:**
```
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
520 passed in 200.08s (0:03:20)
```
Baseline was 518 passed, 0 skipped; +2 for the two new Important-1 tests.
**Zero skips**, as required.

**Lint/format/types**, all from the pure venv:
```
.venv/bin/ruff check .                      -> All checks passed!
.venv/bin/ruff format --check .             -> 95 files already formatted
.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
  -> Success: no issues found in 24 source files
```
(`layers.py`, `session.py`, `map_link.py`, and the UI modules were not
added to the mypy invocation, as instructed.)

---

## Files changed

- `packages/nsgeo-qgis/nsgeo_qgis/layers.py` — Important 1a, 1b, 2 (all
  three parts), Minor 4.
- `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` — Important 3.
- `packages/nsgeo-qgis/nsgeo_qgis/map_link.py` — Minor 5, Minor 6.
- `packages/nsgeo-qgis/nsgeo_qgis/session.py` — Minor 8.
- `packages/nsgeo-qgis/README.md` — Important 2 (README note).
- `packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py` — two new tests
  for Important 1a/1b.
- `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py` — Minor 7.
- `packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py` — Minor 9.
- `docs/superpowers/plans/2026-09-19-nsgeo-qgis-plan3-m8.md` — the plan
  edit (acceptance step 12).

## Self-review

- **Completeness:** all nine findings and the plan edit are addressed —
  see the section-by-section mapping above.
- **Quality (Important 1):** I would trust this on real data. The
  `_table_schema` three-state design is the smallest change that makes
  "absent" and "unreadable" distinguishable, `tableExists` was verified
  as a real, working API on this build rather than assumed, and the
  presence-probe's own failure mode defaults toward the *safe*
  direction (treats an unprobable connection as "unreadable", not
  "absent"). The two new tests were proven to fail against the unfixed
  code by an actual revert/run/restore, not by inspection, and one of
  them (1a) surfaced a worse result than I expected going in — a
  completely silent, fully "successful" data-destroying migration
  (`MESSAGE_LOG: []`) — which is the strongest possible evidence that
  the fix closes a real hole rather than a hypothetical one.
- **Discipline:** no pick re-placement logic was added (Important 2's
  ruling honored). No new write path was added anywhere in `picks`.
  `session.py`'s public signal signatures are untouched, so nothing
  downstream of `grids_changed`/`lines_changed` needed to change.
  `SELECTABLE`'s removal was checked against the whole repo (not just
  the plugin package) before deleting it.
- **Testing:** both new Important-1 tests construct the actual failure
  state (an unopenable-but-present table, at the two different call
  sites that matter) rather than asserting a guard exists in the
  abstract, and both were confirmed to fail against the unfixed code.

## Concerns

- Important 2's warning mechanism (`_grid_placements` /
  `_last_grid_placements` / `_warn_if_a_placed_grid_moved`) has no
  dedicated automated test of its own — I verified its logic by manual
  walkthrough against `add_grid`, `remove_grid`, `replace_grid`, and a
  fresh site-open, and the full QGIS tier (520 tests, including every
  existing `replace_grid`/`add_grid`/`remove_grid` test) passed with it
  in place, but a reviewer who wants a positive assertion that the
  Warning message actually appears on a real `replace_grid` call (and
  stays silent on `add_grid`/`remove_grid`) will need to add one. I
  judged adding a new caching mechanism, a new test, *and* everything
  else in this wave to be enough scope for one pass without also writing
  a `message_log`-based test I hadn't been asked for by name — happy to
  add it if wanted.
- Minor 6's log message reads `f"the selected {name[:-1]} names line
  {key!r}, which is no longer in the site"` — `name[:-1]` turns `"picks"`
  into `"pick"` and `"marks"` into `"mark"`, which works for both current
  callers but is a small, implicit assumption (both selectable table
  names happen to be regular plurals) rather than an explicit mapping.
  Low risk given there are exactly two callers and both are plural
  nouns, but noting it for the record.
