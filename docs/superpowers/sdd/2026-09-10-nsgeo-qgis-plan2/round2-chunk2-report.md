# Round-2 chunk 2 — I4, I5, I6: report

Base: `e02aa7f` (tree clean, C2 already landed at `f8a0c92`). Worktree
`/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-qgis`. No push, no merge, no
rebase. `PYTHONDONTWRITEBYTECODE=1` exported for every test run below.

## Baseline measured at the tip I started from

The brief quotes a controller baseline at `5cc5a12` (**before** C2): qgis **336**. Measured at my
actual base `e02aa7f`:

```
$ QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
339 passed in 68.08s (0:01:08)

$ .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests -q -p no:xonsh
363 passed, 3 skipped in 1.59s

$ .venv/bin/python -m pytest packages/nsgeo-core/tests/test_boundary.py \
    packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q -p no:xonsh
6 passed in 0.20s

$ .venv/bin/ruff check . && .venv/bin/ruff format --check .
All checks passed!
92 files already formatted

$ .venv/bin/mypy ...
Success: no issues found in 24 source files
```

336 → 339 is exactly C2's three tests, so the brief's figure is consistent, not wrong; it is simply
one commit older than my base. Everything below is measured against **339**.

---

## I4 — every "Digitise on map" click permanently leaks a canvas item

Commit **`396d711`** — `fix: give the digitise tool's rubber band back to the canvas`

### Before-fix failure output

Four new tests in `packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py`, all red on `e02aa7f`:

```
>       assert len(_scene_bands(canvas)) == baseline
E       assert 3 == 0
E        +  where 3 = len([<qgis._gui.QgsRubberBand object at 0x7403bcdc97f0>,
                           <qgis._gui.QgsRubberBand object at 0x7403bcdc9760>,
                           <qgis._gui.QgsRubberBand object at 0x7403bcde7920>])

>       assert len(_scene_bands(canvas)) == baseline
E       assert 1 == 0                       # the right-click abort path

>       assert len(_scene_bands(canvas)) == baseline
E       assert 1 == 0                       # the dialog-finished-mid-pick path

>       tool.dispose()
E       AttributeError: 'DigitiseGridTool' object has no attribute 'dispose'

FAILED ...::test_completed_digitise_picks_do_not_pile_rubber_bands_into_the_scene
FAILED ...::test_an_aborted_digitise_pick_gives_its_rubber_band_back
FAILED ...::test_a_dialog_closed_mid_pick_gives_the_rubber_band_back
FAILED ...::test_a_disposed_digitise_tool_is_disposable_again_and_still_usable
4 failed, 45 deselected in 1.27s
```

`3 == 0` after three digitise cycles with the tool's Python reference dropped and `gc.collect()`
between each — the brief's reproduction, reproduced.

### Design, and what was rejected

- `DigitiseGridTool.dispose()` removes the band from `band.scene()` and drops the reference.
  `band.scene()` rather than the brief's `self.canvas().scene()`: it removes the band from whatever
  scene actually holds it and does not assume the canvas outlives the tool. Same effect on the
  reported path, strictly fewer assumptions.
- **Rejected: disposal in `deactivate()`.** It fires on every map-tool switch and the tool can
  legitimately be set on the canvas again afterwards. Since the band can therefore be gone while the
  tool is still live, every `self._band` access in `reset()` and `_on_click` is now guarded — an
  `AttributeError` out of a `canvasClicked` slot is swallowed by Qt, so the tool would just stop
  responding with no message.
- All three finalisers call `_finish_with_digitise_tool(tool)`, which also `deleteLater()`s the tool
  (`QgsMapTool` parents it to the canvas, so it leaked too). The helper deliberately does **not**
  touch the canvas: `cancelled` is emitted from inside `deactivate()`, while the canvas is part-way
  through switching tools, so `unsetMapTool()` from there would re-enter it. `done()` unsets the tool
  itself; `finished()`'s teardown already does. Idempotent: `dispose()` is on its own, and the
  `sip.isdeleted` guard makes a second `deleteLater()` on a destroyed C++ object a no-op rather than a
  RuntimeError out of a slot.
- The brief's "all three places" is confirmed correct, and the third one is confirmed not to be
  reachable via the second: `finished()` calls `blockSignals(True)` precisely so `cancelled` does not
  fire (round 3, Finding 3), so it cannot lean on the cancelled path's disposal.

### Mutation results

| mutation | killed by |
|---|---|
| drop `_finish_with_digitise_tool(tool)` from `done()`'s `finally` | `test_completed_digitise_picks_do_not_pile_rubber_bands_into_the_scene` (1 failed, 48 passed) |
| revert `tool.cancelled.connect(cancelled)` to `connect(show_dialog)` | `test_an_aborted_digitise_pick_gives_its_rubber_band_back` (1 failed, 48 passed) |
| drop the disposal from `finished()`'s teardown | `test_a_dialog_closed_mid_pick_gives_the_rubber_band_back` (1 failed, 48 passed) |
| make `dispose()` remove nothing (`return` before `scene.removeItem`) | all four (4 failed, 45 passed) |

Each of the first three is killed by exactly one test, so the three finalisers are pinned
independently rather than by one over-broad test.

---

## I5 — renaming the site folder orphans every authored pick

Commit **`512c51a`** — `fix: stop naming the site package after the folder it sits in`

### Before-fix failure output

Session tier (`test_plugin_session.py`) — the `GPKG_FILE` constant was added first as a bare name so
the failures would be behavioural rather than a collection-time `ImportError`:

```
E  AssertionError: assert PosixPath('.../test_new_site_writes_the_surve0.nsgeo.gpkg')
                      == (PosixPath('...') / 'site.nsgeo.gpkg')
E  AssertionError: assert PosixPath('.../Kavusan2026/Kavusan2026.nsgeo.gpkg')
                      == (PosixPath('.../Kavusan2026') / 'Site1.nsgeo.gpkg')
E  AssertionError: assert not True
E   +  where True = PosixPath('.../Kavusan2026/Site1.nsgeo.gpkg').exists   # never adopted
E  FileNotFoundError: [Errno 2] .../Kavusan2026/Kavusan2026.nsgeo.gpkg
E  AssertionError: []                                                      # nothing logged at all
5 failed, 21 passed in 0.91s
```

Layers tier (`test_plugin_layers.py`), the one that matters — a real pick, a real GeoPackage:

```
        on_disk = QgsVectorLayer(f"{session2.gpkg_path}|layername=picks", "picks", "ogr")
        assert on_disk.isValid()
        rows = list(on_disk.getFeatures())
>       assert len(rows) == 1
E       assert 0 == 1
E        +  where 0 = len([])
FAILED ...::test_renaming_the_site_folder_does_not_orphan_authored_picks
```

and the migration test the brief explicitly requires (a directory holding only
`Site1.nsgeo.gpkg`):

```
E       AssertionError: assert not True
E        +  where True = (PosixPath('.../Kavusan2026') / 'Site1.nsgeo.gpkg').exists
FAILED ...::test_a_package_written_under_the_old_name_is_adopted_with_its_picks
```

### Design, and what was rejected

- Fixed basename `site.nsgeo.gpkg` (`GPKG_FILE` in `session.py`). `site_name` is left deriving from
  the folder, because it is a display label (the legend group, the survey tree's root) and is *meant*
  to follow a rename; a file path is not.
- **Rejected: recording the package filename in the survey JSON.** That file is `nsgeo.project`'s
  format — portable, human-readable, shared with anything else that ever reads a site — so it would
  push a QGIS-plugin-private detail into the core's contract, and a recorded name can itself go stale
  when the file is renamed by hand. A fixed basename cannot.
- Migration: `_adopt_legacy_package()`, called from `_install()`. It **globs** `*.nsgeo.gpkg` rather
  than looking for `f"{site_name}.nsgeo.gpkg"`. This is load-bearing and the brief's phrasing could
  mislead a reader here: in the reported scenario the folder has *already* been renamed, so the
  legacy package's name (`Site1.nsgeo.gpkg` in `Kavusan2026/`) is exactly the one thing no rule can
  re-derive. A name-derived probe would find nothing and the migration would be dead code.
- "What happens when BOTH names exist", as the brief asks — and a third case it does not:
  - one legacy package, no `site.nsgeo.gpkg` → **adopt** (rename), logged at Info;
  - `site.nsgeo.gpkg` already exists → **touch nothing**, name the stray at Warning (it may hold
    picks and nothing else in the UI would mention it). Adopting would have to overwrite the site's
    own package;
  - more than one legacy package → **do not guess**, name all of them at Critical. The adopted one is
    the file the site then writes into, so choosing wrong is worse than choosing none.
  It renames only; it never copies and never deletes, so no branch can destroy a package.
- Runs from `_install()`, so for `new_site()` too — one behaviour rather than two. `new_site()`
  refuses a folder that already holds a survey file, so a legacy package there belongs to a project
  whose JSON is gone, and adopting hands those picks back instead of stranding them beside a fresh
  empty package. An `OSError` from the `glob` or the `rename` is logged, never raised: opening a site
  must not fail because its directory could not be listed.

### Mutation results

| mutation | killed by |
|---|---|
| `gpkg_path` derived from `site_name` again | session tier: 4 failed, 22 passed (`..._names_the_gpkg_for_the_site`, `..._survives_renaming_the_site_folder`, `..._adopts_a_package_left_under_the_old_folder_name`, `..._named_not_adopted_when_the_fixed_name_exists`); layers tier: `test_renaming_the_site_folder_does_not_orphan_authored_picks` (`assert 0 == 1`) |
| drop `self._adopt_legacy_package()` from `_install()` | 4 failed, 47 passed — the three session adoption tests and `test_a_package_written_under_the_old_name_is_adopted_with_its_picks` |
| adopt even when `site.nsgeo.gpkg` exists (`if target.exists():` → `if False:`) | `test_an_old_style_package_is_named_not_adopted_when_the_fixed_name_exists` (1 failed, 50 passed) |
| guess between two legacy packages (`if len(legacy) > 1:` → `if False:`) | `test_two_old_style_packages_are_reported_rather_than_guessed_between` (1 failed, 50 passed) |

Note on the first mutation: running the session and layers tiers *together* under it exits 139
(segfault) rather than 1 — GDAL is being pointed at a package that does not exist. Run per tier it
gives the clean failures quoted above. That is a property of the mutant, not of the fix; the restored
tree runs both together green (51 passed).

---

## I6 — closing a site discards uncommitted pick edits with no prompt

Commit **`395d108`** — `fix: save buffered pick edits before closing the site destroys them`

### Before-fix failure output

```
>       assert len(rows) == 1
E       assert 0 == 1
E        +  where 0 = len([])            # detach(): the buffered feature is gone from disk
>       assert len(rows) == 1
E       assert 0 == 1
E        +  where 0 = len([])            # session.close_site(): same
>       assert any("picks" in msg and "1" in msg and level == critical for msg, level in seen), seen
E       AssertionError: []               # and the message log is EMPTY -- no prompt, no signal,
E       assert False                     # no exception, exactly as reported
FAILED ...::test_detach_saves_buffered_pick_edits_rather_than_destroying_them
FAILED ...::test_closing_the_site_saves_buffered_pick_edits
FAILED ...::test_pick_edits_that_cannot_be_saved_are_reported_at_critical
3 failed, 25 deselected in 4.68s
```

### Design, and what was rejected

Chose **commit**, not refuse-and-report.

- **Rejected: refuse and report.** Refusing means keeping a layer bound to a package the session no
  longer owns, inside a legend group `detach()` has already removed, while the next site opens on top
  of it — a silent inconsistency traded for a silent loss, and a stale-state class this branch has
  already been bitten by.
- There is no prompt available to offer instead: `detach()` is a signal slot with no user in it, and
  by the time it runs the decision to close has already been taken (the survey JSON's own save prompt
  runs earlier, in `new_site`/`open_site`/`unload`).
- Committing is the recoverable direction: a pick the user did not want is still visible and
  deletable; a discarded one is gone.
- Applied to every held layer, not just `picks`, so a future writable table gets it free; the derived
  three are `setReadOnly(True)` and can never be in this state.
- On a failed commit there is nothing further to do — the site is closing either way, the same "QGIS
  cannot be told no here" that `unload()`'s prompt already reasons from — so the requirement becomes
  that it is not silent: `Critical`, naming the layer and the number of edits being lost. The loop is
  inside its own `try/except` for the module's rule 4: `detach()` is a slot, and one layer's commit
  failing must stop neither the others nor the teardown.

### Mutation results

| mutation | killed by |
|---|---|
| drop `self._commit_pending_edits()` from `detach()` | all three (3 failed, 25 deselected) |
| delete the failed-commit `else:` branch (silent failure) | `test_pick_edits_that_cannot_be_saved_are_reported_at_critical` (1 failed, 27 passed) |
| report the failure at `Warning` instead of `Critical` | `test_pick_edits_that_cannot_be_saved_are_reported_at_critical` (1 failed, 27 passed) |

Worth recording: under the first mutation the **whole file** run reports `FFF` and then exits 139
(`Segmentation fault (core dumped)`) at session teardown. Destroying a `QgsVectorLayer` that is still
in edit mode with a buffered feature crashes the process — so the pre-fix behaviour was not only
losing the picks, it was a plausible route to the same shutdown-crash class the digitise flow's own
round-1 note describes. The fixed tree runs the same file green.

---

## Final verification (real output, from the fixed tree at `395d108`)

```
$ QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
352 passed in 81.34s (0:01:21)

$ .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests -q -p no:xonsh
363 passed, 3 skipped in 1.50s

$ .venv/bin/python -m pytest packages/nsgeo-core/tests/test_boundary.py \
    packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q -p no:xonsh
6 passed in 0.19s

$ .venv/bin/ruff check . && .venv/bin/ruff format --check .
All checks passed!
92 files already formatted

$ .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
    packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
    packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
Success: no issues found in 24 source files
```

qgis tier **339 → 352**, +13 tests (I4 4, I5 6, I6 3). The pure+core tier is unchanged at
**363 passed, 3 skipped** because every new test lives in `tests/qgis`, which that tier
`importorskip`s — the same reason C2's three tests did not move it either.

## Commits

| item | SHA | subject |
|---|---|---|
| I4 | `396d711` | fix: give the digitise tool's rubber band back to the canvas |
| I5 | `512c51a` | fix: stop naming the site package after the folder it sits in |
| I6 | `395d108` | fix: save buffered pick edits before closing the site destroys them |

Nothing pushed, merged or rebased. Branch `nsgeo-qgis` is at `395d108`, three commits ahead of
`e02aa7f`.

## Deviations

1. **`band.scene()` instead of `self.canvas().scene()` (I4).** The brief prescribes the latter
   verbatim. Same result on every reachable path, but it does not assume the canvas outlives the tool
   and it removes the band from whatever scene actually holds it.
2. **The I5 migration globs, it does not probe a derived name.** The chunk brief says "an existing
   old-style package be handled gracefully". A probe for `f"{site_name}.nsgeo.gpkg"` — the natural
   reading — would be dead code: in the reported scenario the folder has already been renamed, so the
   package's old name is precisely the thing that cannot be re-derived. Globbing `*.nsgeo.gpkg` is
   what actually finds it, which forced the "more than one candidate" case into the design.
3. **One existing test was renamed and its assertion changed.**
   `test_new_site_writes_the_survey_file_and_derives_the_gpkg_name` →
   `..._and_names_the_gpkg_for_the_site`: it asserted the exact behaviour I5 removes, so it could not
   survive unchanged. It still pins `site_name`, the survey file, the dirty flag, the `site_opened`
   emission and the "already holds a survey file" refusal.
4. **The `GPKG_FILE` constant was added before the red run for I5.** Importing a name that does not
   exist yet is a collection-time `ImportError`, which proves nothing; the constant alone changes no
   behaviour, and the five failures quoted above are all behavioural.

## Out-of-scope observations (named, not fixed)

1. **Stale design documentation after I5.**
   `docs/superpowers/specs/2026-09-10-nsgeo-qgis-plugin-design.md:252` still specifies
   `<name>.nsgeo.gpkg`, and `docs/superpowers/plans/2026-09-10-nsgeo-qgis-plan2.md` repeats the old
   rule at `:2051`, `:2296` and `:3036`. These are dated historical artefacts, so I did not rewrite
   them; the spec line is the one that arguably should be corrected.
2. **An abandoned edit buffer leaves the process in a state that crashes at teardown.**
   *(Corrected — my first wording overstated this, and the controller was right to catch it.)*
   `removeMapLayers` on a layer with `isEditable()`/`isModified()` true and one buffered feature does
   **not** crash: probed in isolation it survives cleanly and the row reads back as 0 on disk — a
   silent loss, no exception. The `Segmentation fault (core dumped)` / exit 139 I saw is real but
   happens at **teardown of a full-file run** (reproduced as `FFF` + 139 over the whole of
   `test_plugin_layers.py` under the I6-a mutant). So the honest claim is that abandoning an edit
   buffer leaves the process in a state that crashes later, not that `removeMapLayers` crashes — a
   GitHub issue with the stronger claim would send someone chasing a ghost. Fixed here as a side
   effect for `detach()`; nothing prevents it on another route that removes a writable layer mid-edit
   (e.g. a user removing `picks` from the legend by hand, which `_on_layers_removed` simply forgets),
   though QGIS's own removal *action* prompts there, so the exposure is small.
3. **`_grid_dialog`'s `finished()` teardown resolves the tool from `canvas.mapTool()`**, so it only
   ever reaches a tool that is still the *current* one. A `DigitiseGridTool` displaced by a third
   party without `cancelled` firing (its signals blocked by someone else) would be reached by no
   finaliser at all. Not reachable through any plugin path today; noting it because I4's disposal now
   depends on that same lookup.
4. **The legend group name still follows the folder** (`layers.py`:
   `f"nsgeo · {self.session.site_name}"`). Deliberate and left alone — it is a display label — but it
   now reads differently from the package name, so the two will visibly disagree after a folder
   rename until the group is rebuilt.
5. **`-p no:xonsh` remains necessary on this machine** (system-site-packages plugin conflict). Not
   written into any config file, as instructed.

---

# Addendum — controller review of I5: the migration renamed a hot SQLite database

Raised by the controller after the three commits above verified. Fixed in a fourth commit,
**`bb65f31`** — `fix: never rename a legacy site package away from its SQLite journal`. Worked from
`395d108`. Same standards: test-first, mutation-checked, no push.

**The controller is right, and this was my design's blind spot, not the brief's.** The brief said
"handle an existing old-style package gracefully"; an adoption that discards the user's most recent
picks is the opposite of graceful.

## What I reproduced myself

A GeoPackage is a SQLite database, and SQLite resolves `-wal` / `-shm` / `-journal` from the
database's **current** filename. `_adopt_legacy_package()` renamed the `.gpkg` alone, so the journal
was orphaned under the old name. Deterministic probe — a real GeoPackage with one checkpointed pick,
then a subprocess that writes a further commit in WAL mode and `os._exit(0)`s without closing
(exactly what `kill -9` leaves):

```
files                : ['Site1.nsgeo.gpkg', 'Site1.nsgeo.gpkg-shm', 'Site1.nsgeo.gpkg-wal']
sidecars intact      : layer=valid picks=['checkpointed pick'] wal-only=[('the last hour of picks',)]
after the rename     : ['Site1.nsgeo.gpkg-shm', 'Site1.nsgeo.gpkg-wal', 'site.nsgeo.gpkg']
orphaned sidecars    : layer=valid picks=['checkpointed pick'] wal-only=GONE -- no such table: uncheckpointed
```

**One honest correction to the controller's evidence.** I could not make the *unopenable* variant
("disk I/O error", "PACKAGE UNREADABLE") reproduce deterministically here — on this machine the
renamed package still opens and the checkpointed pick still reads. What reproduces every time is
that **everything committed since the last checkpoint is destroyed, silently**. The unopenable
variant is entirely consistent with a kill *during* a checkpoint, where the main file is left
mid-update and only the WAL holds the consistent pages; it is timing-dependent, which is why it is
not deterministic. The verdict, the severity class and the fix are identical either way, so nothing
here weakens the finding — I am recording it only so a future reader is not confused when a probe
shows loss rather than corruption.

The reason this is severe rather than an edge case stands exactly as the controller put it: a hot
journal persists whenever the last writer did not close cleanly — a QGIS crash or kill, not rare —
and the adoption runs automatically on the first open after upgrade.

## Before-fix failure output

The layers-tier test, with a real GeoPackage and a real hot WAL:

```
        used = session2.gpkg_path if session2.gpkg_path.exists() else legacy
        on_disk = QgsVectorLayer(f"{used}|layername=picks", "picks", "ogr")
        assert on_disk.isValid(), f"{used.name} will not open"
        assert [f["note"] for f in on_disk.getFeatures()] == ["checkpointed pick"]
        del on_disk
>       assert _wal_only_rows(used) == ["the last hour of picks"]
E       AssertionError: assert 'GONE -- no such table: uncheckpointed' == ['the last hour of picks']
E        +  where 'GONE -- no such table: uncheckpointed' = _wal_only_rows(
E                PosixPath('.../Site1/site.nsgeo.gpkg'))
FAILED ...::test_a_legacy_package_with_a_hot_wal_is_not_renamed_out_from_under_it
1 failed, 28 deselected in 2.05s
```

The three session-tier spelling tests:

```
E  FileNotFoundError: [Errno 2] No such file or directory: '.../Kavusan2026/Site1.nsgeo.gpkg'   (x3)
FAILED ...::test_a_legacy_package_with_a_sqlite_sidecar_is_refused[-wal]
FAILED ...::test_a_legacy_package_with_a_sqlite_sidecar_is_refused[-shm]
FAILED ...::test_a_legacy_package_with_a_sqlite_sidecar_is_refused[-journal]
3 failed, 26 deselected in 0.76s
```

## Design decision, and what was rejected

**Chose: refuse to adopt while a journal is present, and say how to clear it.** It is the rule the
rest of the function already follows — at worst leave a package where it is and say so — and it is
the only option that cannot corrupt anything.

- **Rejected: move the sidecars with the main file.** Getting SQLite recovery semantics right by hand
  is a much larger claim than this migration needs to make, a half-completed multi-file rename is
  worse than no rename, and a `-shm` is not movable even in principle — it is shared memory backing a
  live `-wal`, meaningless once detached.
- **Rejected: checkpoint it ourselves first** (`open` → `PRAGMA wal_checkpoint(TRUNCATE)` → `close`).
  This one is genuinely tempting: it is a small claim in SQLite terms, it is the documented remedy,
  and it would recover the user's data with no manual step. Rejected because it means writing,
  unattended and on the first open after an upgrade, to a database some process left in an unclean
  state — precisely the thing this round exists to stop doing. The manual step costs the user one
  action and risks nothing.

**The refusal is recoverable, not permanent**, which is what makes it acceptable: the message names
the package and each journal file it found, and says to open it once in QGIS (or any SQLite client)
and close it cleanly. That checkpoints and removes the sidecars, and the next open adopts. The test
proves that loop closes rather than assuming it. Logged at `Warning`, not the `Critical` the
unrecoverable branches use: there is a one-step remedy and nothing has been lost.

All three journal spellings are checked (`-wal`, `-shm`, `-journal`): each means the same thing, and
SQLite looks for every one of them.

## Tests added (4)

- `test_a_legacy_package_with_a_hot_wal_is_not_renamed_out_from_under_it` (layers tier) — real
  GeoPackage, real hot WAL from a subprocess that `os._exit`s. It asserts, **first**, that the
  package this site will use still opens and still holds everything committed to it — the assertion
  none of I5's six original tests made, and the one that fails on the old code — then that the
  package was not renamed, then that a clean close really does let the next open adopt.
- `test_a_legacy_package_with_a_sqlite_sidecar_is_refused[-wal|-shm|-journal]` (session tier) —
  cheap, plain files, pinning the level as well as the text.

## Mutation results

| mutation | killed by |
|---|---|
| adopt regardless of a hot journal (`if hot:` → `if False:`) | all four (4 failed, 54 passed) |
| narrow `_SQLITE_SIDECARS` to `("-wal",)` | the `-shm` and `-journal` cases (2 failed, 56 passed) |
| report at `Critical` instead of `Warning` | all three session cases (3 failed, 55 passed) |

## Final verification (real output, at `bb65f31`)

```
$ QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
356 passed in 82.89s (0:01:22)

$ .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests -q -p no:xonsh
363 passed, 3 skipped in 1.50s

$ .venv/bin/python -m pytest packages/nsgeo-core/tests/test_boundary.py \
    packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q -p no:xonsh
6 passed in 0.20s

$ .venv/bin/ruff check . && .venv/bin/ruff format --check .
All checks passed!
92 files already formatted

$ .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
    packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
    packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
Success: no issues found in 24 source files
```

qgis tier **352 → 356**, +4. Pure+core unchanged at **363 passed, 3 skipped** (all four new tests are
in `tests/qgis`). Net for the chunk: **339 → 356**, +17.

## Commits, final

| item | SHA | subject |
|---|---|---|
| I4 | `396d711` | fix: give the digitise tool's rubber band back to the canvas |
| I5 | `512c51a` | fix: stop naming the site package after the folder it sits in |
| I6 | `395d108` | fix: save buffered pick edits before closing the site destroys them |
| I5 follow-up | `bb65f31` | fix: never rename a legacy site package away from its SQLite journal |

Branch `nsgeo-qgis` at `bb65f31`, four commits ahead of `e02aa7f`. Nothing pushed, merged or rebased.
C3, C4 and I8 untouched.

## Further out-of-scope observations from this round

6. **Nothing else in the plugin considers SQLite journal files.** `layers.py` opens and rebuilds the
   package through QGIS providers, which handle their own journals, so there is no *known* second
   exposure — but `_rebuild_picks`'s `renameVectorTable`/`dropVectorTable` sequence and any future
   code that moves or copies the `.gpkg` as a file would have the identical hazard. Worth a note
   wherever the package is treated as a single file.

---

# Addendum 2 — controller re-review of I5: two Importants, plus the C4/I6 interaction

Worked from `b2ed89c`. Three commits, no push. The refuse-vs-move ruling from Addendum 1 is
untouched; Important 1 is about what "refuse" should then *do*.

## Important 1 — the refusal was not recoverable, and the message was false

**Confirmed independently, and it reproduces exactly as the controller described.** My probe, real
plugin, `SiteLayers` attached as in production:

```
1. before the open        : ['Site1.nsgeo.gpkg', 'Site1.nsgeo.gpkg-shm', 'Site1.nsgeo.gpkg-wal', 'survey.nsgeo.json']
2. after the open         : [..., 'Site1.nsgeo.gpkg', 'site.nsgeo.gpkg', 'site.nsgeo.gpkg-wal', ...]
   GPKG_FILE created?     : True
   session.gpkg_path      : site.nsgeo.gpkg
   picks the site shows   : 0
3. after detach/close     : ['Site1.nsgeo.gpkg', 'Site1.nsgeo.gpkg-shm', 'Site1.nsgeo.gpkg-wal', 'site.nsgeo.gpkg', 'survey.nsgeo.json']
4. user clears the journal: ['Site1.nsgeo.gpkg', 'site.nsgeo.gpkg', 'survey.nsgeo.json']
5. after reopening        : ADOPTED? False   picks the site shows: 0
```

`site_opened` → `SiteLayers.refresh()` → `ensure_tables()` creates an empty `site.nsgeo.gpkg` in the
same open, so the "a package by the right name already exists" branch fires forever afterwards. The
branch I wrote to protect the picks made losing them permanent and printed advice that could not
work — worse than the silent orphaning I5 exists to fix, exactly as the controller put it.

Step 3 also answers a question the fix turns on: **QGIS's own clean close does checkpoint its
journals away** (`site.nsgeo.gpkg-wal` is gone after `detach()`).

**Why my test missed it — the one test in this round that passed for the wrong reason.** It drove a
bare `SiteSession` with no `SiteLayers`, so nothing ever created `GPKG_FILE`. Accepted without
qualification; that is the whole reason this got through.

### Fix — `81e425f`: use the package where it is

Rather than declining, `_resolve_package()` now returns the **legacy package itself** when a journal
is present, under its old name, renaming nothing. This fixes the trap at the root because no
competing file is ever created — and it is simply more correct: *opening* a database with a hot
journal is what SQLite recovery is for; only *renaming* it was ever unsafe. The picks are on screen
on the first open, the ordinary clean close checkpoints the journal, and the next open adopts with
nothing asked of anyone. The remedy became automatic instead of manual-and-impossible.

`gpkg_path` becomes a value **resolved once at install time** rather than a property recomputed from
`root`, because the resolution can now legitimately land on a pre-I5 name. Recomputing would re-run
the decision after `ensure_tables()` had created files underneath it — which is how this got stuck in
the first place. The failed-rename branch now returns the legacy path too: still readable where it
is, so using it beats resolving to a name that does not exist.

**Rejected**, both of the controller's other two options:

- *Suppress `ensure_tables()`'s on-demand creation for that open* — the site comes up with no layers
  at all, a worse answer to "your package is fine, we just cannot rename it yet".
- *Treat an empty `GPKG_FILE` as adoptable* — needs a second handle on the package to decide what
  "empty" means (against `layers.py`'s rule 2), then a two-step rename that can half-complete.

Neither deletes nor overwrites anything; the journal branch performs no filesystem write at all. All
three pre-existing adoption outcomes still work (no legacy → `GPKG_FILE`; `GPKG_FILE` exists → use it
and name the stray; more than one legacy → refuse to guess at Critical).

### Before-fix output

```
>       assert session2.gpkg_path == legacy
E       AssertionError: assert PosixPath('.../Site1/site.nsgeo.gpkg') == PosixPath('.../Site1/Site1.nsgeo.gpkg')
FAILED ...::test_a_legacy_package_with_a_hot_journal_is_used_where_it_is_and_adopted_later
1 failed, 29 deselected in 2.56s
```
plus the three session-tier spellings, same shape (3 failed, 26 deselected).

### Mutations — 3 run, 3 killed (each by all four tests)

| mutation | result |
|---|---|
| journal branch declines again (`return target`) | 4 failed, 56 passed |
| `gpkg_path` recomputed instead of resolved | 4 failed, 56 passed |
| drop the journal check entirely | 4 failed, 56 passed |

The rewritten layers-tier test now attaches `SiteLayers` and pins the whole loop: picks visible on
the first open, **no competing package created**, journal cleared by the clean close, next open
adopts, pick intact.

## Important 2 — the guard never checked the destination

Confirmed: on the old code the destination tests fail with
`FileNotFoundError: ... '.../Kavusan2026/Site1.nsgeo.gpkg'` — the rename went ahead onto a name that
already had a foreign journal beside it.

### Fix — `a8da845`

`journals = self._sqlite_journals(found) + self._sqlite_journals(target)`. Same check, both names,
same outcome (use the legacy package where it is, so nothing ever meets that journal). The stray
journal is named in the message but never touched — not ours to remove.

### Mutations — 3 run, 3 killed

| mutation | killed by |
|---|---|
| check only the source | the three destination tests (3 failed, 60 passed) |
| check only the destination | the four source-side tests (4 failed, 59 passed) |
| narrow `_SQLITE_JOURNALS` to `("-wal",)` | the `-shm`/`-journal` cases on both sides (4 failed, 59 passed) |

## The C4 / I6 interaction — addressed, behaviour unchanged

**Addressed, not decided against.** Reproduced first: a buffered pick, `Discard` to "Save the site
before continuing?", and the pick is on disk afterwards, with the log saying only
`saved 1 unsaved edit(s) to 'picks' while closing the site`.

I6's commit-over-discard ruling stands, and nothing about it changed. The two stores fail in opposite
directions (an unwanted pick is visible and deletable, a discarded one is gone), and `detach()` is a
signal slot with no user in it, reached after the decision to close has been taken. `Discard` means
"do not write my grid and line changes to `survey.nsgeo.json`", not "throw away the layer I was
editing".

What was missing was that **nothing said so**, so I fixed that in both directions — for the user and
for the next maintainer:

- the success message now reads `... layer edits live in the GeoPackage, not the survey file, so the
  site's own save prompt does not cover them`;
- `_commit_pending_edits()`'s docstring records the interaction and why it is deliberate.

One test (`e023ada`) drives the real plugin down the Discard path and asserts both halves — the pick
is committed, and the log explains why. Mutation: reverting the message to its old wording fails it.

## Final verification (real output, at `e023ada`)

```
$ QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
372 passed in 89.38s (0:01:29)

$ .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests -q -p no:xonsh
363 passed, 3 skipped in 1.50s

$ .venv/bin/python -m pytest packages/nsgeo-core/tests/test_boundary.py \
    packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q -p no:xonsh
6 passed in 0.20s

$ .venv/bin/ruff check . && .venv/bin/ruff format --check .
All checks passed!
92 files already formatted

$ .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
    packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
    packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
Success: no issues found in 24 source files
```

qgis tier **368 → 372**. The +4 is net: three session-tier tests and one layers-tier test were
*rewritten* rather than added (the layers one because it passed for the wrong reason), and three
destination tests plus one C4/I6 test are new. Pure+core unchanged at **363 passed, 3 skipped** — all
of these live in `tests/qgis`.

## Commits

| item | SHA | subject |
|---|---|---|
| Important 1 | `81e425f` | fix: use a journalled legacy package where it is instead of declining |
| Important 2 | `a8da845` | fix: check the destination name for a journal too, not just the source |
| C4/I6 note | `e023ada` | docs: say that the site's save prompt does not cover layer edits |

Branch at `e023ada`, three commits ahead of `b2ed89c`. Nothing pushed, merged or rebased. C2, C3, C4,
I4 and I8 untouched.

## Out-of-scope observations from this round

7. **A site already in the wedged state is not rescued.** If a directory holds both
   `site.nsgeo.gpkg` (empty, created by the broken build) and a legacy package with the real picks,
   the "already exists" branch still wins and the picks stay unreachable except by hand. Reachable
   only from the unreleased `bb65f31`..`b2ed89c` range, so I judged an automatic rescue not worth a
   second handle on the package plus a two-step rename — but anyone who ran those commits against a
   real site should check their site directory for a stray `*.nsgeo.gpkg`.
8. **`_pending_edit_count()` counts the buffer, not what committed.** The success message says
   "saved N" using the pre-commit count. `commitChanges()` returning True means all of them landed,
   so it is accurate today; it would quietly become wrong if a partial-commit path were ever
   introduced.
