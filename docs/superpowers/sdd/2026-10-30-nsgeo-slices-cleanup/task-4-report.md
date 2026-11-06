# Task 4 report: remember each grid's resolution (#71: core, session, This grid)

**Status:** DONE_WITH_CONCERNS (the concerns are minor and noted below; nothing is blocked)
**Commit:** `88ba267 Slices: remember each grid's resolution settings (#71)`, pushed to `origin nsgeo-slices-cleanup` (47e48ff..88ba267)

## What was implemented

### Core (`packages/nsgeo-core/src/nsgeo/project.py`)
- `_RESOLUTION_KEYS = ("cell", "dz_ns", "t0_ns", "t1_ns", "radius_spacings")`.
- `_clean_resolution(value: object) -> dict[str, float]`. Anything that is not a dict gives `{}`. It keeps only the five keys, and each value must be an `int` or `float` (never `bool`) and finite. It drops `cell <= 0`, `dz_ns <= 0` and `radius_spacings < 0`. When both `t0_ns` and `t1_ns` survive and `t1_ns <= t0_ns`, it drops both. Values are stored as `float`.
- `_clean_slice_source` and `_clean_site_view` store the result under `"resolution"` only when it is non-empty. `SCHEMA_VERSION` is unchanged.

### Session (`packages/nsgeo-qgis/nsgeo_qgis/session.py`)
- A module helper `_merge_resolution(old, **fields)`. It returns `old` with the non-None fields laid over it as floats, or None when nothing changed. None is the cue not to dirty.
- `slice_resolution(grid_id)` returns a copy, or `{}`.
- `remember_slice_resolution(grid_id, *, cell, dz_ns, t0_ns, t1_ns, radius_spacings)` merges through `_update_source(grid_id, resolution=merged)`. It keeps the preset, lines and gain, and dirties only on a real change. A call with no fields writes nothing.
- `site_resolution()` and `remember_site_resolution(...)` do the same for `site_view["resolution"]`, apart from every grid's record. `set_site_view` already copies the whole view, so it keeps `resolution`.
- `remove_grid` already pops `slice_sources[grid_id]`, so the grid's resolution goes with it. A test now pins this.

### Dock (`packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`)
- `self._seeding = 0` is a depth counter next to `_updating`.
- `_on_resolution_edited(field, value)` is connected through `functools.partial` to the five spins' `valueChanged`: cell→`cell`, dz→`dz_ns`, z0→`t0_ns`, z1→`t1_ns`, grid_radius→`radius_spacings`.
  - It returns while `_updating` or `_seeding` is raised.
  - In site scope it returns, leaving a `# Task 5` marker.
  - Otherwise, with a grid selected and a survey open, it calls `session.remember_slice_resolution(grid_id, **{field: value})`.
  - The whole body is guarded and logs through `_log`.
- `_restore_remembered_resolution(grid_id)` runs inside `_seeding`.
  - It sets the remembered cell, dz, z0 and z1 with signals live, so they reach the engine through the debounce, or through the owed apply on the #70 path.
  - It sets the radius signal-blocked, as its seed is, then calls `_update_radius_metres()`. `refresh_slice` reads the radius live, and `rebuild_source`'s #72 branch redraws if the radius in cells moved.
  - A remembered cell below the floor is clamped up by the spin itself, because `setMinimum` already ran in the seed.
- `_seed_resolution_defaults`: its whole body (after the early returns) is wrapped in `_seeding`, and it calls `_restore_remembered_resolution(grid_id)` last.
- `_seed_dz_z_defaults`: the seeding part (after its early returns, so only when it actually seeds) is wrapped in `_seeding`, and it calls `_restore_remembered_resolution(grid_id)` last.
  - When it runs from inside `_seed_resolution_defaults`, the restore runs twice. The second pass sets identical values, emits nothing and is harmless. I kept it because the brief prescribes both call sites.
- `_clamp_z_to_prepared` computes the clamped pair first. If the pair is empty (`z1 <= z0`), both ends take the snapped prepared bounds.
  - Otherwise it behaves exactly as before: each end is clamped only when it lies outside the prepared range, snapped with `_snap_inside`.
  - The sets are still signal-blocked and inside `_updating`, and it still returns whether anything moved. The docstring now states the rule.
- `restore_cube`, right after `_remember_source(...)`, remembers:
  - `cell`, `dz_ns`, `t0_ns` and `t1_ns` from `recipe.resolution` when it is present;
  - `radius_spacings` from `grid_radius_spin.value()` (after `apply_view`) when `recipe.view` is present.
  - It writes them for `recipe.choice.grid_id` in one call.

### Guide
`docs/guide/getting-started.md`, Step 7, item 3: "Each grid remembers the resolution you set for it, and saving the site saves it." I wrote "site" because the guide calls the survey a site ("Save site").

## Programmatic-set audit (the five spins: `cell_spin`, `dz_spin`, `z0_spin`, `z1_spin`, `grid_radius_spin`)

| Call site | Calls | Guard |
|---|---|---|
| `SlicesDock.__init__`, widget construction | `setRange`/`setDecimals`/`setValue` on all five | Run before any `valueChanged` connect, so no slot is listening |
| `_seed_resolution_defaults` | `cell_spin.setMinimum(floor)` (emits if it raises the value), `cell_spin.setValue(seed)` | `_seeding` (new) |
| `_seed_resolution_defaults` | `grid_radius_spin.setValue(0.5)` | signals blocked + `_seeding` |
| `_seed_dz_z_defaults` | `dz/z0/z1.setValue(header…)`; `setSingleStep` (never emits `valueChanged`) | `_seeding` (new) |
| `_restore_remembered_resolution` (new) | `cell/dz/z0/z1.setValue(remembered)` | `_seeding` |
| `_restore_remembered_resolution` (new) | `grid_radius_spin.setValue` | signals blocked + `_seeding` |
| `_clamp_z_to_prepared` | `z0/z1.setValue(...)` | signals blocked + `_updating` |
| `apply_view` (called only from `restore_cube`) | `grid_radius_spin.setValue(radius_m / spacing)` | signals blocked (+ `_updating` from `restore_cube`) |
| `restore_cube` | `cell/dz/z0/z1.setValue(recipe…)` | `_updating`. Signals are live (debounce and `_mark_cube_unsaved` see them); `_on_resolution_edited` returns. The cube's values are then remembered explicitly from the recipe |
| `site_scope.set_spins_quietly` (callers `restore_spins`, `seed_resolution`, `seed_z_from_ready`) | `cell/dz/z0/z1.setValue` | signals blocked |
| `site_scope.set_cell_floor` (callers `restore_spins`, `seed_resolution`) | `cell_spin.setMinimum` | signals blocked |
| `site_scope.restore_spins` / `seed_resolution` / `seed_z_from_ready` | `setSingleStep` on dz/z0/z1 | never emits `valueChanged` |
| z0/z1 coupling | none exists (no `setMinimum`/`setMaximum` linking z0 and z1) in either file | n/a |
| Elsewhere in the plugin (`plugin.py`, etc.) | grep found no programmatic set on these five spins | n/a |

`radius_spacing_spin` (the site's own radius) is not one of the five and is not wired to `_on_resolution_edited`.

## TDD evidence

### Core: RED
`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_project.py -q -p no:cacheprovider`
```
FAILED packages/nsgeo-core/tests/test_project.py::test_a_remembered_resolution_round_trips
FAILED packages/nsgeo-core/tests/test_project.py::test_a_partly_bad_resolution_keeps_its_good_values
2 failed, 57 passed in 1.09s
```
The 11 `test_a_bad_remembered_resolution_value_reads_as_unset` cases passed before the change, because the old cleaner dropped the unknown `resolution` key wholesale. They guard against a cleaner that is too permissive. To show they bite, I monkeypatched `nsgeo.project._clean_resolution` in-process with a naive one (`dict(v) if isinstance(v, dict) else {}`), which edited no file:
```
11 failed, 2 passed, 46 deselected   (every bad case except "list", plus the partly-bad test)
```

### Core: GREEN
Same command: `59 passed in 0.28s`.

### Session: RED
`PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_session.py -q -p no:cacheprovider -p no:xonsh -k resolution`
```
E       AttributeError: 'SiteSession' object has no attribute 'remember_slice_resolution'. ...
E       AttributeError: 'SiteSession' object has no attribute 'remember_slice_resolution'. ...
E       AttributeError: 'SiteSession' object has no attribute 'site_resolution'
E       AttributeError: 'SiteSession' object has no attribute 'remember_slice_resolution'. ...
4 failed, 1 passed, 83 deselected
```
The one pass is an older test whose name also matches `-k resolution`.

### Session: GREEN
The whole file: `88 passed in 17.30s`.

### Dock: RED
I ran the eight new dock tests with `-k` before writing any dock code:
```
E       AssertionError: assert {} == {'cell': 0.1}
E       assert 0.2 == 0.1 ± 1.0e-07
E       TypeError: 'NoneType' object is not subscriptable
E       assert -11.086 == -16.086000442504883 ± 0.001
E       assert -11.086 == 109.5614667236805 ± 0.001
E       assert 0.2 == 0.01
E       KeyError: 'cell'
7 failed, 1 passed
```
The one pass was `test_seeding_never_remembers_a_resolution`, which is vacuous until remembering exists.

The work was then staged:
1. **Restore and slot without the `_seeding` check in the slot.** 6 failed. The seeding test failed (`{'dz_ns': 0.2..., 'cell': 0.2} == {}`), and so did the reopen test (`assert not True`, dirty), proving the guard is load-bearing.
2. **`_seeding` check added.** 7 passed. The one remaining failure was the fallback test: `assert (109.561, 99.5614) == (-11.086, 99.5614)`.
3. **Clamp fallback added.** `8 passed`.

### Two site-scope tests for the #70 path
Both were added after the code, so I proved each one RED by disabling the feature temporarily. Each temporary edit was reverted, and I confirmed that no `TEMP-RED` marker was left.
- `test_landing_on_the_grid_the_engine_holds_falls_back_from_a_range_past_its_data`: with the fallback disabled, `assert 109.561 == -2.424` (1 failed). Restored: 1 passed. Its "the no-op path" assertion passed, so this really exercises the `_clamp_z_to_prepared` call inside `_run_pending_grid_prepare`.
- `test_the_opened_grid_brings_its_remembered_resolution_to_the_engine`: with the restore disabled, `assert 0.2 == 0.1` (1 failed). Restored: 1 passed. It asserts on `engine.frame.cell` and `engine.z.dz_ns`, as well as on the spins.

### Dock: GREEN (Step 6)
`test_plugin_slices_dock.py`, `test_plugin_site_scope.py` and `test_plugin_session.py` together: `243 passed in 132.16s`. No test that existed before this task failed, so there is no "edit now remembered" finding to report.

## Verification commands (Step 8)
| Command | Result |
|---|---|
| core + pure | `821 passed, 3 skipped in 6.33s` (808 + 13 new; skips still 3) |
| qgis (full) | `1214 passed in 586.07s (0:09:46)`, exit 0 |
| lint | `All checks passed!` / `155 files already formatted` |
| types | `Success: no issues found in 36 source files` |

## Files changed
- `packages/nsgeo-core/src/nsgeo/project.py`
- `packages/nsgeo-core/tests/test_project.py` (+3 tests; 13 cases)
- `packages/nsgeo-qgis/nsgeo_qgis/session.py`
- `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py` (+4 tests)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py` (+8 tests, plus helpers `_switch`, `_settle_sources`, `_snapped_bounds`)
- `packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py` (+2 tests: the #70-path restore, and the #70 no-op-path fallback)
- `docs/guide/getting-started.md`

## Self-review findings
1. **The clamp's fallback reads the brief literally.** It fires whenever the clamped pair is empty, so it also covers a hand-typed reversed pair that is present when a preparation lands. Before, that pair reached `_apply_resolution` as a `Resolution` error; now it shows the prepared range. The record is not touched either way. The clamp runs only when a preparation lands, never on a spin edit, so a user part-way through typing is not affected. The docstring states the rule exactly as coded.
2. **Two tests needed work so they could not pass vacuously.**
   - **`test_seeding_never_remembers_a_resolution`:** A and B in `docked_two_grids` seed identical values, so a switch would emit nothing. The test now gives B a 0.3 m spacing, so its cell seed is 0.15, and asserts that `cell_spin.valueChanged` actually fired.
   - **Sources settled first:** a grid-combo pick already remembers the preset and lines (M12) and dirties the survey, so the "not dirty" tests settle those (A→B→A, then save) before the step under test.
   - **The two z-range tests** assert that the remembered `t0_ns` is in the box before preparation lands. That makes them fail without the restore, rather than pass on seeds that happen to equal the prepared bounds.
3. **The remembered radius is restored quietly**, like its seed. That keeps Task 3's `test_a_seeded_radius_emits_no_value_changed` meaningful. The geometry spins emit, as seeds do, and that is how they reach the engine.
4. **An existing #70 helper now writes a record.** `_narrow_a_then_site_mid_window` edits A's z1 by hand, so that value is now remembered for A. `test_landing_on_the_grid_the_engine_already_holds_clamps_the_seeded_range` therefore lands on A with the remembered narrowed z1 and a seeded z0. It still clamps z0, because site3's `time_zero` crops the start, and it still passes.
5. **The session accepts any float.** `remember_*_resolution` does not validate values. Its only callers are the spins and `restore_cube`, whose `Resolution` is already validated, and the loader cleans whatever reaches disk.

## Concerns
- **A seed can land on the site's spins while Whole site shows. This predates the task and is not made worse by it.** `rebuild_source` runs `_sync_included` in any scope. So if This grid's selected grid is removed while the site shows, the combo falls back to another grid, and `_seed_resolution_defaults` writes that grid's seed onto the shared spins, which belong to the site at that moment. It now also writes that grid's remembered values. `_seeding` keeps any of it from being remembered. Task 5 may want to look at this when it gives the site its own memory.
- **The double restore on the grid-change path** (point 2 under Dock above) is cosmetic.
