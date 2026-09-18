# Scoped re-review — `5cc5a12..b2ed89c` (C2, C3, C4, I4, I5, I6, I8 + docs)

Reviewer: Opus 5, merge-gate re-review. Scope: this range only. C1/C5/C6/I1/I2/I3/I7 landed
before `5cc5a12` and were not looked at. Mutation testing was **not** re-run as a primary method
(already done twice); this review went after what mutation testing cannot see: untested
neighbouring paths, tests that pass for the wrong reason, interactions between the three chunks,
resource lifetime, and anything that can lose or corrupt survey data.

Every claim below is reproduced. Probe scripts are in the session scratchpad; their exact output
is quoted. No code was changed; the tree is clean.

## Verdict

**Merge-able, with three Importants that should be adjudicated first — two of them in I5, and one
of those defeats I5's own stated goal for the population it was written for.** No Criticals. The
C2 / C3 / C4 / I4 / I6 / I8 work is sound and the tests are, with one small exception, honest.

Independently re-verified at `b2ed89c`, `PYTHONDONTWRITEBYTECODE=1`, pycache cleared:

| check | result |
|---|---|
| `QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q` | 368 passed, **exit 0** |
| `.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests -q` | 363 passed, 3 skipped |
| boundary (both files) | 6 passed |
| `test_plugin_layers.py` alone (teardown-segfault check) | 30 passed, exit 0 |
| `.venv/bin/ruff check .` / `ruff format --check .` | clean / 92 files |
| `.venv/bin/mypy` (CI invocation) | no issues, 24 files |

No drift into the brief's "out of scope — do not touch" list. All seven production files map to
C2 (`gain_strip.py`, `profile_dock.py`, `plugin.py`), I4 (`digitise_tool.py`, `plugin.py`),
I5/I6 (`session.py`, `layers.py`), I8 (`survey_dock.py`). Nothing touches `close_site`'s teardown
ordering, `import_dialog`, the loader keep-alive, or the slot-guard policy sweep.

---

## Important 1 — I5's sidecar refusal is not recoverable in the real plugin, and the message it prints is false

`packages/nsgeo-qgis/nsgeo_qgis/session.py:255-277` (the `hot` branch) together with
`packages/nsgeo-qgis/nsgeo_qgis/layers.py:328` (`ensure_tables` → `gpkg_path`).

The refusal tells the user:

> Open `Site1.nsgeo.gpkg` once in QGIS (or any SQLite client) and close it cleanly, then reopen
> this site and it will be adopted.

It will not be. `_adopt_legacy_package()` declines to create `GPKG_FILE`, and then `site_opened`
→ `SiteLayers.refresh()` → `ensure_tables()` creates an **empty** `site.nsgeo.gpkg` in the same
directory, seconds later, on the same open. From that moment `target.exists()` is permanently
true, so every later open takes the "`GPKG_FILE` already exists" branch and the legacy package is
never adopted — the site comes up with an empty picks layer, which is exactly the I5 symptom.

Reproduced end to end with a real `SiteLayers` attached (`probe_refusal_recovery.py`):

```
1. directory: ['Site1.nsgeo.gpkg', 'Site1.nsgeo.gpkg-shm', 'Site1.nsgeo.gpkg-wal', 'survey.nsgeo.json']
2. refusal logged?  True
2. directory now:   ['Site1.nsgeo.gpkg', 'Site1.nsgeo.gpkg-shm', 'Site1.nsgeo.gpkg-wal',
                     'site.nsgeo.gpkg', 'site.nsgeo.gpkg-shm', 'site.nsgeo.gpkg-wal',
                     'survey.nsgeo.json']
3. after the user closes the legacy package cleanly:
                    ['Site1.nsgeo.gpkg', 'site.nsgeo.gpkg', 'survey.nsgeo.json']
4. adopted? legacy gone? -> False
4. log: ['<root> also holds Site1.nsgeo.gpkg, which this site does not use; its data is only
         reachable by renaming it to site.nsgeo.gpkg by hand']
4. picks the site now shows: []
VERDICT: REFUSAL IS NOT RECOVERABLE
```

**Why the suite is green on it.** `test_a_legacy_package_with_a_hot_wal_is_not_renamed_out_from_under_it`
(`test_plugin_layers.py:1112`) drives `SiteSession()` **with no `SiteLayers` attached** for both
`session2` and `session3`, so nothing ever creates `GPKG_FILE` and the "next open adopts"
assertion holds in the test and only in the test. It is in the layers-tier file, next to tests
that do attach layers, which makes the omission easy to miss. This is the round's one test that
passes for the wrong reason relative to the production claim it is standing in for.

This is not a re-litigation of ruling "refuse rather than move the sidecars" — refusing is fine.
What does not hold is the recorded "and the refusal is recoverable by design". Not data loss
(the legacy package is intact and the second message does name it), but I5's goal —
"a renamed folder no longer orphans its picks" — fails for exactly the population I5's own
sidecar guard was added for: users whose QGIS was killed. Smallest fix shapes: defer creating
`GPKG_FILE` while an un-adopted legacy package is present, or re-attempt adoption when the target
exists but is an empty package this code created.

## Important 2 — `_adopt_legacy_package` checks SQLite sidecars on the source name only, never on the destination

`packages/nsgeo-qgis/nsgeo_qgis/session.py:255` —
`hot = [sfx for sfx in _SQLITE_SIDECARS if found.with_name(found.name + sfx).exists()]`.

The guard asks "does the file I am renaming *from* have a journal?" and never "does the name I am
renaming *to* already have one?". If `site.nsgeo.gpkg-wal`/`-shm` are lying in the directory with
no `site.nsgeo.gpkg`, adoption renames the legacy package into that name and SQLite replays a
**foreign** database's WAL over it on the next open. Reproduced, deterministic over two runs
(`probe_target_sidecar.py`):

```
directory before the open: ['Site1.nsgeo.gpkg', 'site.nsgeo.gpkg-shm', 'site.nsgeo.gpkg-wal',
                            'survey.nsgeo.json']
adopted? True   legacy still there? False
log: ['adopted Site1.nsgeo.gpkg as site.nsgeo.gpkg: ...']
adopted package opens? False
tables visible: ['unrelated']       <- the rescued package's entire content is gone
```

The adopted package will not open as a layer and its GeoPackage tables are replaced by the
unrelated database's. Note the log line still reports a successful adoption.

**Reachability.** The plugin cannot create the precondition alone; a user has to remove or move
`site.nsgeo.gpkg` without its sidecars. Important 1 is what puts them in that position: after a
refusal the directory holds an empty `site.nsgeo.gpkg` (hot sidecars too, if QGIS is killed
again) plus the message "its data is only reachable by renaming it to site.nsgeo.gpkg by hand".
A user following that instruction does `rm site.nsgeo.gpkg; mv Site1.nsgeo.gpkg site.nsgeo.gpkg`
— neither step touches `-wal`/`-shm`. I walked that exact chain
(`probe_user_follows_instructions.py`) and in that staging the rescued package survived, so the
destruction is conditional on which database the orphan journal came from, not guaranteed. The
missing symmetry in the guard is certain; the blast radius varies.

Fix is one line, in the same shape as the existing check: refuse when `target.name + sfx` exists
for any `_SQLITE_SIDECARS` entry.

## Important 3 — I6 fixed `detach()`; the neighbouring `_drop_loaded_layer` path still destroys buffered pick edits silently

`packages/nsgeo-qgis/nsgeo_qgis/layers.py:612-615` (`_drop_loaded_layer`), reached from
`_rebuild_picks` at `layers.py:530` and from `_ensure_table` at `layers.py:404`.

I6 put `_commit_pending_edits()` into `detach()`. `_drop_loaded_layer("picks")` reaches the same
`project.removeMapLayer(...)` with no such guard, and `_rebuild_picks` then migrates from what is
**on disk** — so an open edit buffer is destroyed, not migrated. Pre-existing, and the brief did
scope I6 to `detach()`; but it is the same defect class the round exists to remove, sitting one
call away from the fix, and nothing in the round's tests covers it.

Reproduced (`probe_rebuild_edits.py`): one committed pick and one buffered pick, then
`session.replace_grid(...)` with a different CRS — i.e. the user opens "Edit grid…" and corrects
the CRS while `picks` is in edit mode:

```
before: editable=True modified=True buffered=1
picks on disk after the CRS change: ['committed pick']
any log line mentioning the lost edit? []
VERDICT: LOST SILENTLY
```

No prompt, no log, no exception — the exact wording of I6's own finding. The fix is to call
`_commit_pending_edits()` (or a single-layer form of it) from `_drop_loaded_layer`, which also
covers any future writable table.

---

## Minor

1. `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py:481-483` — the docstring claims "A `None`
   owner alongside real points would still be honoured, and ends any gesture in progress". False
   when `GainStrip._owner` is still the constructor's `None`: `owner != self._owner` is then
   `False` and the payload falls into the refuse-while-dragging branch. Unreachable today
   (production always passes a tuple, and `_points` starts empty so no drag can exist before the
   first `set_points`), but it is a doc statement a future caller would rely on.

2. "Discard" on the Unsaved-changes prompt (`plugin.py:498`, "Save the site before continuing?")
   no longer discards everything: `detach()` now commits buffered `picks` edits regardless of the
   answer. Deliberate per the recorded ruling, and the recoverable direction — but the one prompt
   now covers two stores that answer it differently. Worth a sentence in the docstring or a
   tracker item, not a code change.

3. `plugin._gain_owner` / `_gain_step` are never cleared — not on `show_gain_strip(None)`, not in
   `unload()`. Harmless for correctness (a write also requires the current row to still hold that
   exact object), but the plugin keeps a core `Step` alive past teardown.

4. `test_detach_saves_buffered_pick_edits_rather_than_destroying_them`
   (`test_plugin_layers.py:994`) ends with `assert any("picks" in m for m in message_log)` —
   satisfied by any picks-related log line, not specifically the commit report. The row read back
   off disk is the real assertion, and the sibling Critical-level test pins level and count, so
   the gap is small.

---

## Checked and fine

**C2 (gain strip owner token).** Walked every `_sync_gain_strip` exit: the three
`show_gain_strip(None)` paths leave `_gain_step` stale but cannot produce a wrong write, because
`_on_gain_points` also requires the current row to hold that exact object. The echo path is
correct — `_gain_step = new` is recorded *before* `replace_step`, so the synchronous
`stack_changed → rebuild() → step_selected → _sync_gain_strip` round trip does not bump the
generation and does not end a live drag; `test_dragging_a_point_past_its_neighbour_does_not_corrupt_it`
is a real multi-move plugin drag that pins it. Curve→non-curve is covered by `hideEvent`,
curve→curve by the owner token, same-row step swaps by the generation. `!=` (not `is not`) on the
token is right for tuples. The two new C2 tests drive real `QTest` press/`Key_Down`/move/release
through the real plugin and assert on B's stored params *and* that A is unchanged — they cannot
pass by the gesture simply doing nothing.

**I4 (rubber band).** `dispose()` is idempotent and every `self._band` access is `None`-guarded,
so a disposed tool still `reset()`s and still takes clicks. `deactivate()` deliberately does not
dispose. All three finalisers are covered and none double-fires: `done()`'s
`canvas.unsetMapTool(tool)` cannot re-enter `cancelled()` because `_on_click` sets `_finished =
True` before emitting `points_picked`, so `show_dialog()` runs once. `deleteLater()` is deferred,
so nothing is freed while a C++ frame is live; `sip.isdeleted` makes a second call a no-op.
Counting bands off `canvas.scene().items()` rather than off the tool is the right measurement.

**I5 (fixed package name), apart from Importants 1 and 2.** `_install()` calls `close_site()` —
hence `site_closed` → `detach()` → layers removed — *before* `_adopt_legacy_package()`, so no
rename ever happens under open layers, including when the same site directory is re-opened. The
glob excludes the target name and directories (`is_file()`); the multi-legacy and target-exists
branches never rename. `site_name` correctly stays the folder name for display while `gpkg_path`
stops following it.

**I6 (commit on close).** Iterates before `removeMapLayers`; per-layer `try/except` so one
failure cannot abort the rest or the teardown; `sip.isdeleted` guarded; `_pending_edit_count`
cannot raise. `unload()` reaches it too, via its direct `self.layers.detach()`. The deliberately
abandoned edit buffer in `test_pick_edits_that_cannot_be_saved_are_reported_at_critical` does not
reintroduce the teardown crash: `test_plugin_layers.py` alone exits 0.

**C3 (picks migration verification).** The test reaches the real row-count gate — it asserts on
`"picks migration wrote 1 of 2 rows"`, so it cannot be passing via the `if not ok` branch above
it — wraps only the `_PICKS_REBUILD` layer (leaving `_table_schema`/`ensure_tables` untouched),
and reads the original back with a fresh `QgsVectorLayer` plus an explicit "no backup table"
assertion. The implementer was right to reject the brief's prescribed
`QgsVectorDataProvider.addFeatures` class patch: that is the unbound-method trap.

**C4 (New/Open protect unsaved work).** `QFileDialog.getExistingDirectory` / `getOpenFileName`
are called *outside* both slots' `try/except`, so "the chooser was never reached" really is
asserted by the call not raising. `calls[0][0][3]` is genuinely the button-set argument.
Production code re-checked: Cancel returns `False`, both callers stop, Cancel is also Qt's escape
button for that set, and a failed Save (including the `allow_absolute` sub-prompt answered No)
also returns `False`. No defect.

**I8 (context menu).** The known swallow trap is handled: `_on_context_menu` wraps its body in
`except Exception -> _log`, and every new context-menu test asserts `message_log == []`, so a
forbidden-modal `AssertionError` in there fails the test instead of vanishing. `answer_modal`
installs a `staticmethod`, so `QMenu.exec`'s recorded `args` really is `(global_pos,)` as
asserted. conftest now forbids `QMenu.exec`/`exec_` alongside `QDialog.exec`/`exec_`. The shared
`self.context_menu` cannot be re-entered mid-`exec()` (QMenu holds a popup grab, and the
destructive lambdas open app-modal message boxes), so `clear()`-ing a menu whose action is
executing is not reachable; the change also ends a real per-right-click `QMenu` leak.

**Interactions between the three chunks.** I5 × I6 ordering (commit strictly before any rename,
above). I5 × `_rebuild_picks` (an adopted package with a mismatched picks CRS migrates normally).
C2 × I8 and I4 × anything: no shared state. The only cross-fix coupling that bites is
Important 1, which is I5's own refusal meeting `SiteLayers.ensure_tables` — two chunks that were
never exercised together, which is precisely the gap this re-review was asked to look for.
