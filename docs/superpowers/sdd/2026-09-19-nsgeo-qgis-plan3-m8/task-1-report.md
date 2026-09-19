# Task 1: The pick schema and the pick store — Report

## Status: DONE (fix round 1 of 5 applied)

## What I implemented

Exactly the brief's Steps 3–5, in `packages/nsgeo-qgis/nsgeo_qgis/session.py` and
`packages/nsgeo-qgis/nsgeo_qgis/layers.py`:

- `nsgeo_qgis.session.Pick` — the frozen dataclass, fields in the exact order specified.
- `SiteSession._pick_store` (set in `__init__`, after `self._preview_trace = -1`), the
  `pick_store` read-only property, and `set_pick_store()`, placed in a new
  `# ---- picks (spec §4) ----` section immediately before `# ---- preview (spec §3.3) ----`.
- `TABLES["picks"]` gains `("feature_id", "str")` and `("seq", "int")`, appended after
  `("created", "str")`, with the migration-rationale comment from the brief kept verbatim.
- `SiteLayers.__init__` calls `session.set_pick_store(self)` right after the
  `layersWillBeRemoved` connection.
- `SiteLayers._picks_layer`, `_pick_point`, `write_pick`, `picks_for`, `_row_to_pick`, added
  after `feature_count` and before `# ---- derived tables ----`, verbatim from the brief.
- Module-level converters `_as_float`, `_as_str`, `_as_opt_str` added immediately after `_log`.
- `NULL` added to `layers.py`'s `qgis.core` import list (alphabetized ahead of `Qgis`); `Pick`
  added to the `nsgeo_qgis.session` runtime import at line 59.
- Ten new tests appended to `packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py`, verbatim
  from the brief, with the two import edits (`NULL` into the `qgis.core` list, `Pick` into the
  `nsgeo_qgis.session` import).

**One deviation from the brief, made deliberately:** I did not add `import datetime as _dt` to
`session.py`. I grepped the whole brief for `_dt` and it appears exactly once — at the import
line itself; nothing in Task 1's actual code (the `Pick` dataclass, `set_pick_store`, or any
`layers.py` method) references it. Adding an unused import would fail `ruff check .` (F401 is
in this repo's selected rule set, confirmed in `ruff.toml`), which is one of this task's hard
gates. This is almost certainly prep for Task 2's `session.add_pick`, which will stamp
`created` from a real clock and will need the import then — placed one task early in the
brief. I left it out rather than silently keeping a dead import or fighting the linter, since
the brief itself says a broken instruction should be fixed and reported, not silently
worked around. Task 2 should add `import datetime as _dt` itself when it writes the code that
uses it.

**One other deviation, not code:** the working tree had a pre-existing uncommitted change to
`docs/superpowers/plans/2026-09-19-nsgeo-qgis-plan3-m8.md` (present before I started — visible
in the very first `git status` I ran) that has nothing to do with Task 1's files. I staged and
committed only the three files the brief names (`session.py`, `layers.py`,
`test_plugin_layers.py`) rather than running the brief's literal `git add -A`, so that
unrelated, not-mine-to-commit edit stays out of this commit. It is still sitting unstaged in
the working tree, untouched, for whoever owns it.

## What I tested and the results

### Focused file (during iteration)

```
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest \
  packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py -q -p no:xonsh
```
Before implementation: collection error (see RED below).
After implementation: `41 passed in 66.66s` (31 pre-existing + 10 new).

### Both tiers (once, before committing)

Pure:
```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
```
Result: `367 passed, 2 skipped in 1.60s` — matches the stated baseline exactly (this task adds
no pure tests).

QGIS:
```
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
```
Result: `479 passed in 150.35s (0:02:30)` — baseline 469 + the 10 new tests, no failures, no
warnings, no skips.

### Lint / types

```
.venv/bin/ruff check .          -> All checks passed!
.venv/bin/ruff format --check . -> 95 files already formatted
.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
                                 -> Success: no issues found in 24 source files
```

Two lines copied verbatim from the brief exceeded this repo's 100-char line length
(`ruff.toml`: `line-length = 100`) — the `RuntimeError` message in `write_pick`, and the
`old_spec`/`kinds` lines in the migration test. I ran `.venv/bin/ruff format` on just the two
affected files to rewrap them; the rewrap is purely cosmetic (same strings, same logic), and
`ruff check .` / `ruff format --check .` are both clean afterward. Diffs of the two spots are
in the "Files changed" section below.

## TDD Evidence

**RED** — before writing any implementation code, ran the focused file with only the tests
appended:

```
$ QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest \
    packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py -q -p no:xonsh
==================================== ERRORS ====================================
____ ERROR collecting packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py _____
ImportError while importing test module '.../test_plugin_layers.py'.
Traceback:
packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py:14: in <module>
    from nsgeo_qgis.session import GPKG_FILE, SURVEY_FILE, Pick, SiteSession
E   ImportError: cannot import name 'Pick' from 'nsgeo_qgis.session' (.../session.py)
=========================== short test summary info ============================
ERROR packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.33s
```

This is exactly the failure the brief predicted (`ImportError: cannot import name 'Pick'`),
confirming the test file was correctly wired to the not-yet-existing implementation before any
production code was touched.

**GREEN** — after implementing Steps 3–5:

```
$ QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest \
    packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py -q -p no:xonsh
.........................................                                [100%]
41 passed in 66.66s (0:01:06)
```

## Files changed

- `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m8/packages/nsgeo-qgis/nsgeo_qgis/session.py`
  — `Pick` dataclass, `_pick_store` field, `pick_store` property, `set_pick_store()`.
- `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m8/packages/nsgeo-qgis/nsgeo_qgis/layers.py`
  — `NULL`/`Pick` imports, `TABLES["picks"]` schema, `session.set_pick_store(self)` in
  `__init__`, `_as_float`/`_as_str`/`_as_opt_str` module functions, and
  `_picks_layer`/`_pick_point`/`write_pick`/`picks_for`/`_row_to_pick` methods.
- `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m8/packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py`
  — `NULL`/`Pick` imports, ten new tests appended verbatim from the brief.

Reformatted-only spots (ruff format, no logic change):

```python
# layers.py, write_pick
raise RuntimeError(
    f"could not write the pick: {layer.dataProvider().error().message()}"
)
```

```python
# test_plugin_layers.py, the migration test
old_spec = [
    (name, kind) for name, kind in TABLES["picks"][1] if name not in ("feature_id", "seq")
]
...
kinds = {
    "str": QMetaType.Type.QString,
    "int": QMetaType.Type.Int,
    "float": QMetaType.Type.Double,
}
```

## Self-review findings

- Verified `_ensure_table`/`_rebuild_picks` (read in full before implementing) really do
  migrate by field name with no code change, matching the brief's Fact 2 — confirmed both by
  reading the code and by `test_a_package_with_the_pre_m8_picks_schema_migrates_with_its_rows_intact`
  passing.
- Verified `line_for_key`, `grid_for_line`, `_line_points`, `feature_count`, and the
  `populated` fixture all match the shapes the brief assumes (no fixture/import drift to fix
  this time, unlike the note in the task instructions anticipating that possibility).
- Checked for naming collisions before adding `_as_float`/`_as_str`/`_as_opt_str` and
  `_PICKS_BACKUP`/`_PICKS_REBUILD` (pre-existing) — none.
- One latent (untested, out-of-scope-for-this-task) observation: `_pick_point` calls
  `self.session.line_for_key(pick.line_key)`, which raises `KeyError` (not caught) if the key
  names no line. `write_pick`'s contract is "raises `RuntimeError` on any failure to write";
  a `KeyError` escaping instead would violate that if ever reached. In practice this can't
  happen yet: nothing in Task 1 calls `write_pick` with an unvalidated key, and the brief's own
  `set_pick_store` docstring says the invariant "a pick targets the WORKING line" is enforced
  by `session.add_pick` (Task 2) before `write_pick` is ever called. Flagging it here so
  whoever writes Task 2's `add_pick` is aware the guard needs to hold before calling into
  `write_pick`, not as something I changed — the brief's code is verbatim and Task 1's own
  tests don't exercise this path.
- No stray warnings anywhere in either tier's output; both runs are pristine passes.

## Issues or concerns

- The `import datetime as _dt` omission (above) — flagging again here per the report
  requirements. I'm confident in this call (grep confirms zero uses in the brief's Task 1
  code), but noting it as a concern in case Task 2's author expected it pre-staged.
- The pre-existing unstaged change to `docs/superpowers/plans/2026-09-19-nsgeo-qgis-plan3-m8.md`
  is still sitting in the working tree (not committed by me, not touched by me). Someone should
  account for it before the branch is finished.

---

## Fix round 1 of 5 (review findings)

Reviewer confirmed the migration logic itself (Fact 2, the two-column append, the row-count
gate) is correct and the migration test is strong and non-vacuous. Four findings, all in
`packages/nsgeo-qgis/nsgeo_qgis/layers.py`, all about a state the rest of the module already
codes for and the new pick methods did not: a failed `_rebuild_picks` (`ensure_tables` catches
and Critical-logs it, then *continues*) can leave a stale `picks` layer — either missing fields
or a stale CRS — open in `self.layers["picks"]`.

### What I changed

1. **Important 1 — `_row_to_pick` read fields unguarded.** Added a module-level `_attr(feature,
   name)` helper mirroring `write_pick`'s existing `if name in names` guard: returns `NULL` when
   `feature.fields().indexOf(name) < 0` instead of letting `feature[name]` raise `KeyError`.
   Rewired all ten field reads in `_row_to_pick` (`trace`, `time_ns`, `distance_m`, `depth_m`,
   `velocity_m_ns`, `stack_json`, `note`, `created`, `feature_id`, `seq`) through it.
2. **Important 2 — `write_pick` had no CRS guard.** Added a check at the top of `write_pick`,
   right after the "layer not open" check and before `_pick_point` is called, mirroring
   `_refill`'s existing guard verbatim in spirit: `if target is not None and layer.crs() !=
   target: raise RuntimeError(...)`.
3. **Minor 6 — `write_pick` could leak `KeyError`.** Wrapped the `_pick_point(pick)` call in
   `try/except KeyError`, re-raising as `RuntimeError(f"could not write the pick: no line with
   key {pick.line_key!r}") from None` — a clean message naming the key, not a re-stringified
   `KeyError` (whose `__str__` would double-quote it).
4. **Minor 3 — untested NULL branches.** Added a test with a hand-edited row that has `trace`/
   `time_ns` set but `distance_m`/`note` left blank, asserting it comes back as a `Pick` with
   `distance_m is None` and `note == ""`. (This one is coverage-only: my existing `_as_float`/
   `_as_str` already compared with `== NULL`, not `is not None`, so this test happens to pass
   before and after — verified directly, see below — but the gap in coverage was real and is
   now closed.)

### Tests added (in `packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py`)

- `test_write_pick_reports_an_unknown_line_key_as_a_runtime_error` (Minor 6)
- `test_picks_for_reads_a_hand_edited_row_with_blank_optional_fields` (Minor 3)
- `test_picks_for_survives_a_failed_rebuild_leaving_pre_m8_fields_missing` (Important 1) —
  constructs the actual failed-rebuild state: writes a pre-M8 `picks` table to disk (same
  technique as the Task 1 migration test), monkeypatches `SiteLayers._rebuild_picks` to raise,
  reopens the site so `ensure_tables` genuinely hits and swallows that failure, then asserts
  `picks_for` returns the surviving row instead of raising `KeyError`, with `feature_id`/`seq`
  reading back as `None`.
- `test_write_pick_refuses_when_the_picks_layer_predates_a_grid_crs_change` (Important 2) —
  constructs the actual CRS-mismatch state: monkeypatches `_rebuild_picks` to raise, then calls
  `session.replace_grid` with a new CRS on the only (first) grid, confirms the live `picks`
  layer still reports the old CRS while `layers.crs()` reports the new one, then asserts
  `write_pick` raises `RuntimeError` (matching `"picks"`) and nothing gets written
  (`feature_count("picks") == 0`).

### Non-vacuousness check

Before committing, I copied the fixed `layers.py` aside, checked out the pre-fix (previous
commit's) `layers.py` over it via `git show HEAD:...`, and reran just the four new tests:

```
$ QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest \
    packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py -q -p no:xonsh \
    -k "reports_an_unknown_line_key or blank_optional_fields or survives_a_failed_rebuild or predates_a_grid_crs_change"
...
E       KeyError: 'feature_id'                          # survives_a_failed_rebuild
...
E       Failed: DID NOT RAISE RuntimeError               # predates_a_grid_crs_change
...
FAILED ...::test_write_pick_reports_an_unknown_line_key_as_a_runtime_error
FAILED ...::test_picks_for_survives_a_failed_rebuild_leaving_pre_m8_fields_missing
FAILED ...::test_write_pick_refuses_when_the_picks_layer_predates_a_grid_crs_change
3 failed, 1 passed, 41 deselected in 6.93s
```

Three of the four fail against the pre-fix code exactly as the review predicted (`KeyError:
'feature_id'` for Important 1, `DID NOT RAISE RuntimeError` for Important 2, and the unknown-key
case for Minor 6). The fourth (Minor 3's blank-optional-fields test) passes both before and
after, confirming it is a coverage addition locking in already-correct behaviour, not evidence
of a live bug — matching what I found reading `_as_float`/`_as_str` (both already use `==
NULL`, never `is None`). I then restored the fixed `layers.py` from the copy and reran the full
file to confirm all 45 pass with the real fix in place.

### Verification (with the fix in place)

Focused file:
```
$ QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest \
    packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py -q -p no:xonsh
.............................................                            [100%]
45 passed in 71.70s (0:01:11)
```
(41 from the original task + 4 new this round.)

Lint:
```
$ .venv/bin/ruff check .
All checks passed!
$ .venv/bin/ruff format --check .
95 files already formatted
```
(One line in the new `picks_for`-survival test exceeded 100 chars — `ruff format` rewrapped it;
no logic change.)

Per the coordinator's instructions, I did not re-run both full tiers for this round (the
focused file plus ruff is what was asked for).

### Files changed this round

- `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m8/packages/nsgeo-qgis/nsgeo_qgis/layers.py`
  — `_attr()` helper; `_row_to_pick` reads routed through it; CRS guard and `KeyError`→
  `RuntimeError` conversion added to `write_pick`.
- `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m8/packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py`
  — four new tests (above).

### Commit

`887467b` — "fix: guard picks reads/writes against a failed rebuild's stale table", pushed to
`origin/nsgeo-m8`. Staged only the two files above, per the coordinator's instruction not to
`git add -A` (the plan/ledger commit `f8f2baa` is the coordinator's own, already committed
separately, and correctly excluded from this commit).

### Deferred items — untouched, as instructed

`_set_by_name` duplication between `write_pick` and `_rebuild_picks`, `_pick_point`'s trace
clamp, the collection-level RED run, and `layers.py`'s line count were all left alone per the
coordinator's explicit "do NOT fix these" list.
