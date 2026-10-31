# Task 5 report: Whole site remembers its resolution (#71), seeding rules pinned (#75)

**Status: DONE_WITH_CONCERNS.** The concerns are minor and listed at the end. None blocks the task.

## Commits (branch nsgeo-slices-cleanup, all pushed)

- `f4e8930` Slices: pin the site's resolution seeding rules (#75). This holds the characterisation tests only.
- `7ac9bf8` Slices: Whole site remembers its resolution settings (#71). This is the feature, plus Ruling 1's test rewrite.
- `7887292` Slices: keep This grid's seeds off the site's spins (#71). This is Ruling 12, a separate commit because it reads better that way.

I tested the intermediate state at `7ac9bf8` on its own: test_plugin_site_scope.py and test_plugin_slices_dock.py gave 167 passed, and lint was clean. The tree at `7887292` is byte-identical to the one the four verification commands ran on.

## What I implemented

### `ui/site_scope.py`

- **New `set_radius_quietly(dock, value)`.** A module-level function that sets the value with signals blocked. Every programmatic set of `radius_spacing_spin` now goes through it.
- **`__init__`.** The three `_note_z_edit` connections are removed. The `z_custom` comment now says that a hand edit or a remembered value makes the range the user's.
- **`enter`.** A remembered `radius_spacings` is applied quietly before `refresh_rows()`, so the tooltip's metres follow it.
- **`forget`.** It also resets the radius to `DEFAULT_RADIUS_SPACINGS` quietly. Before this, a second survey inherited the first one's radius.
- **`_on_radius_changed`.** It is still guarded. While the site shows and `not dock._updating`, it also calls `remember_site_resolution(radius_spacings=value)`.
- **`seed_resolution`.** The seed runs exactly as before. Then a remembered `cell` is laid over the cell seed quietly, and the floor just raised clamps it. After the z seed, any remembered `dz_ns`/`t0_ns`/`t1_ns` are laid over quietly and `z_custom` is set to True. Each field stands on its own: a remembered cell alone leaves the z range seeded.
- **`seed_z_from_ready`.** When `z_custom` is set and the clamp would leave z1 <= z0, both ends take the snapped ready bounds. This is the site twin of Task 4's rule. The clamp writes nothing, so the remembered values stand.
- **`_note_z_edit`** is deleted (#75).

### `ui/slices_dock.py`

- **`_on_resolution_edited`, site branch.** For `cell`, `dz_ns`, `t0_ns` and `t1_ns` it calls `session.remember_site_resolution(**{field: value})`. For the three z fields it also sets `self._site.z_custom = True`. A `radius_spacings` field is ignored in site scope, because that spin is This grid's and is hidden there. The branch also returns when no survey is open. The existing `_updating`/`_seeding` guard is unchanged.
- **Ruling 12:**
  - `_seed_resolution_defaults`, `_seed_dz_z_defaults` and `_restore_remembered_resolution` return early in site scope. They do not touch the spins, and `_dz_z_seeded_for` stays unmarked, so a later call retries.
  - `set_scope("site")` now records `_grid_spins_for`, the combo's grid when the snapshot was taken. It is initialised to None in `__init__`.
  - `_resume_grid`'s no-target path restores the snapshot as before. Then:
    - If the combo's grid differs from `_grid_spins_for`, it runs `_seed_resolution_defaults(grid)`. That seeds the fallback grid and lays its remembered values over the seed.
    - Otherwise it runs `_seed_dz_z_defaults(grid)`. That catches a dz/z0/z1 seed owed by lines imported while the site showed, and is a no-op once the grid is seeded.
  - Both run inside `_seeding` with signals live, as a This-grid grid change does, so the debounce carries the values to the engine.
  - Docstrings are updated on `_seed_resolution_defaults`, `_seed_dz_z_defaults`, `_restore_remembered_resolution`, `_on_resolution_edited` and `_resume_grid`.
- **Target path (`_switch_resumed_grid`) is unchanged.** `set_scope` sets `_scope = "grid"` before `_resume_grid`, so `_sync_included` still seeds the target. `test_the_opened_grid_brings_its_remembered_resolution_to_the_engine` passes, and it would fail if the new guards blocked that path.
- **Ruling 13.** `capture_spins` and `restore_spins` are unchanged and still quiet.

## Characterisation results on unchanged code (Step 1–2)

All three passed on 88ba267 and were committed alone as `f4e8930`.

```
pytest .../test_plugin_site_scope.py -k "finest_spaced or every_grid_with_lines_by_default or reseeded_only_when"
3 passed, 59 deselected in 4.75s
```

- `test_the_site_cell_seeds_from_the_finest_spaced_grid`: B at 0.3 m gives a cell of `default_cell(0.3, floor)`, which is 0.15.
- `test_the_site_includes_every_grid_with_lines_by_default`: with C's lines removed, the site is `("A", "B")`, and nothing is stored under `grids`.
- `test_the_site_cell_is_reseeded_only_when_the_included_grids_change`: this is today's rule, and Ruling 1 rewrites it in `7ac9bf8` (see below).

## TDD evidence

There is no earlier test of `_note_z_edit` anywhere in the tests. `test_a_hand_z_edit_in_the_site_is_clamped_from_then_on` pins its intent: a hand z edit is clamped from then on and never re-seeded.

**RED 1: all Step 3 tests plus Ruling 1's rewrite, on the unchanged code.**

```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py -q -p no:cacheprovider -p no:xonsh -k "reseeded_only_when or site_resolution or seeded_resolution or z_range or site_radius or hand_z_edit or this_grids_grid_while"
8 failed, 3 passed, 60 deselected in 16.42s
```

The 8 failures were:

- reseeded_only_when: `0.15 == 0.35`, "the remembered cell outlives the seed"
- site_resolution_edit: `{} == {'cell': 0.35}`
- survives_save_and_reopen: `{} == {'cell': 0.35, 'radius_spacings': 1.25, 't0_ns': 2.576}`
- clamped_not_reseeded: `0.2165 == 0.433`
- site_radius_from_the_default: `1.25 == 0.5`
- hand_z_edit: `{} == {'dz_ns': 0.433, 't0_ns': 2.576}`
- removing_this_grids_grid: `(0.1, 0.5, 2.0, 30.0) == (0.2, 0.2165, -2.424, 99.5614)`. B's remembered values bled onto the site's spins.
- importing_lines: `z_custom` was True. The unguarded `_note_z_edit` caught This grid's seed.

The 3 passes were:

- `test_entering_the_site_never_remembers_its_seeded_resolution` is a guard test, so it passes before the change by construction.
- The "wholly outside" test passes before the change only because nothing remembered is laid over yet.
- The third is an existing test the `-k` filter also matched: `test_moving_this_grids_grid_while_a_site_task_outlives_its_cancel_never_overlaps`.

**RED 2: the fallback.** I first implemented the remembered layering without the z1 <= z0 fallback:

```
FAILED test_a_remembered_site_z_range_wholly_outside_the_data_falls_back_to_the_ready_range
E  assert (109.561, 99.5614) == (-2.424, 99.5614)
```

After adding the fallback, that test went GREEN.

**RED 3: Ruling 12**, with the site_scope feature in and the dock's Ruling 12 not yet written. I tightened both Ruling 12 tests so the bled-onto grid is kept out of the site. Otherwise a ready-grid tick re-seeded the site's z range over the bleed and hid it.

```
FAILED test_removing_this_grids_grid_...   (0.1, 0.5, 2.0, 30.0) == (0.2, 0.2165, -2.424, 99.5614)
FAILED test_importing_lines_under_...      (0.2, 0.2165, -11.086, 99.5615) == (0.2, 0.2165, -2.424, 99.5614)
2 failed, 9 passed
```

**RED 4: the seeded fall-back test.** A mutation run (below) found a survivor, so I added `test_the_grid_this_grid_fell_back_to_under_the_site_comes_back_seeded`. It failed against HEAD's `slices_dock.py` with `assert 0.2 == 0.15`, and passed on the implementation.

**GREEN:**

```
same -k command, after the implementation:  11 passed, 60 deselected in 17.08s
test_plugin_site_scope.py + test_plugin_slices_dock.py:  169 passed in 142.21s (before the 13th new test)
```

**Mutation check.** I ran each mutant against the new tests, then restored the files from copies and confirmed them with `cmp`.

| Mutant | Result |
|---|---|
| M1: no `z_custom` from a hand edit | killed by hand_z_edit |
| M3: no site guard in `_seed_dz_z_defaults` | killed by removing and importing |
| M4: no fallback-grid seed on return | **survived at first**. B was fully remembered, so `_seed_dz_z_defaults` → `_restore_remembered_resolution` restored every field anyway. The seeded fall-back test now kills it. |
| M6: `enter` does not restore the radius | killed by survives_save_and_reopen |
| M9: remembered z not marked custom | killed by survives_save_and_reopen and clamped_not_reseeded |
| No fallback | killed by wholly_outside (RED 2) |
| `forget` without the radius reset | killed by site_radius (RED 1) |

## Verification commands (final tree = 7887292)

- **core + pure:** **821 passed, 3 skipped** in 6.41s. The skip count is 3.
- **qgis:** **1227 passed** in 687.37s, exit 0. That is the baseline 1214 plus 13 new tests: 3 characterisation and 10 new.
- **lint:** `All checks passed!` and `155 files already formatted`.
- **types:** `Success: no issues found in 36 source files`.

## Files changed

- `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py`
- `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py`

## Ruling 1's test rewrite

`test_the_site_cell_is_reseeded_only_when_the_included_grids_change` now uses `site3_factory` with B's spacing set to 0.3 m, so an untick really changes the seed:

1. On entry the cell is `default_cell(0.3, floor)`, which is 0.15.
2. With nothing remembered, unticking B re-seeds it to `default_cell(1.5, floor)`, which is 0.2. This is the re-seed observed.
3. A hand-set 0.35 survives leaving the site and coming back.
4. Re-ticking B changes the included set again, so the seed would be 0.15. The remembered 0.35 is laid over it: "the remembered cell outlives the seed".

## Tests added in `7ac9bf8` and `7887292`

- **Feature (`7ac9bf8`):**
  - `test_a_site_resolution_edit_is_remembered_in_the_site_view`
  - `test_entering_the_site_never_remembers_its_seeded_resolution`, which also leaves and re-enters.
  - `test_the_site_resolution_survives_save_and_reopen`. The first plugin is opened with `_open` and closed with `_close` in a `finally`; the reopen goes through `open_plugin`. It checks the cell, `t0_ns` and a radius of 1.25, the tooltip's metres, `res_applied`, a drawn slice, and that the survey is not dirty.
  - `test_a_remembered_site_z_range_is_clamped_not_reseeded`. Remembered dz and z0 stand, and z1 is clamped.
  - `test_a_remembered_site_z_range_wholly_outside_the_data_falls_back_to_the_ready_range`
  - `test_a_different_survey_starts_the_site_radius_from_the_default`
  - `test_a_hand_z_edit_in_the_site_is_clamped_from_then_on`. A site transform change re-prepares every grid, which would re-seed a seeded range.
- **Ruling 12 (`7887292`):**
  - `test_removing_this_grids_grid_while_the_site_shows_leaves_the_site_resolution`. B is remembered. The site is (B, C), so A's removal changes no ready grid.
  - `test_the_grid_this_grid_fell_back_to_under_the_site_comes_back_seeded`. Nothing is remembered for B, which is at 0.3 m spacing, and A has a hand radius.
  - `test_importing_lines_under_this_grids_grid_while_the_site_shows_leaves_the_site_resolution`. The site is (A, B). This grid shows C, which has no lines until the import.
  - "Not dirtied beyond the removal or import itself" is checked through record equality (`site_view()`, `slice_source`/`slice_resolution`), because the removal and the import dirty the survey themselves.

## Self-review findings

1. **The two Ruling 12 tests were hiding the bleed (fixed).** As first written, a grid joining or leaving the site made a ready-grid tick re-seed the site's z range over the bled values. Only the old `z_custom` symptom showed the problem, and that disappears once `_note_z_edit` is removed. I fixed it by keeping the bled-onto grid out of the site with `set_site_view(grids=...)`.
2. **M4 survivor (fixed).** It is now covered by the seeded fall-back test.
3. **On the no-target return, This grid's seeds now run with signals live inside `_seeding`.** `_mark_cube_unsaved` therefore resets the cube combo to "(unsaved)" when the grid changed, and the debounce applies the new values. Both match what a This-grid grid change does.

## Concerns (minor, pre-existing or shared with Task 4; not acted on)

1. **Pre-existing quirk in `seed_resolution`.**
   - It falls through to the header seed whenever `seed_z_from_ready()` returns False. That happens when nothing is ready, but also when the ready seed moved nothing.
   - In the second case the spins briefly take the header values.
   - The next ready-grid tick corrects it, but only if the ready set changes. On an untick of a ready grid it does.
   - I kept the behaviour unchanged.
2. **Possible transient error message on entering the site.**
   - It needs a remembered single z bound that is incompatible with the header seed. Example: only `t0_ns` = 80 is remembered, after the long lines were removed and the headers now end at 50.
   - Then z1 <= z0 before any grid is ready, and `apply_resolution` emits one `Resolution` error. The first ready tick's fallback then corrects it.
   - This grid has the same transient for its own records in Task 4, via the restore and the debounce before `_on_prepared`.
3. **The site's z clamp only ever narrows.**
   - A remembered range narrowed against a partial ready set comes back only on the next `seed_resolution`: an included-set change, or entering a survey anew.
   - This matches This grid's documented "a freed range comes back on the next grid change or reopen".

---

# Fix round 1 (Ruling 14 plus the cheap items)

**Status: DONE.** Commit `4886510` Slices: the site's z bounds are remembered field by field (#71). It is pushed.

## What changed

### `ui/site_scope.py`

- **`z_custom` is gone.** It is removed from `__init__` and `forget`, and the dock no longer sets it. Which z fields are the user's is now read from `session.site_resolution()` every time.
- **New `SiteScope.seed_z(included=None)`** replaces `seed_z_from_ready`. It runs on every seed (`seed_resolution`) and on every ready-set change (`_run_tick`).
  - **Bounds.** The ready union, snapped inside it. Before any grid is ready, the bounds are the headers of `included`. Only `seed_resolution` passes `included`, so a tick with nothing ready leaves the spins alone. That matches the old tick.
  - **dz** is the remembered `dz_ns`, else the data's dt.
  - **z0** is the remembered `t0_ns`, clamped up to the low bound; else the low bound.
  - **z1** is the remembered `t1_ns`, clamped down to the high bound; else the high bound.
  - **Empty pair.** If z1 <= z0, both take the bounds (Review Focus 1).
  - **singleStep** stays one data sample, whatever dz the user chose.
  - **Nothing is written.** The record stands.
  - Clamping always starts from the record, never from a spin. A remembered dz no longer holds z0/z1.
- **`seed_resolution`** now does three things: the cell seed, the remembered cell laid over it (the floor clamps it), then `seed_z(included)`. This also removes Concern 1 from the main report: the drop to the header seed when nothing moved is gone.
- **Concern 2 from the main report** is also gone. Before any grid is ready, a remembered value is now clamped into the header range, with the same fallback, so z1 <= z0 can no longer reach the engine.

### `ui/slices_dock.py`

- **`_on_resolution_edited`** only remembers in site scope. Its docstring now names `seed_z`.
- **Cheap item 2.** The `_resume_grid` comment now says that a fallback grid with no lines keeps the left grid's dz/z0/z1, as This grid's own grid change does: its seed needs a line, and `_sync_included` retries it when one arrives.

### Readers of `z_custom`

`set_lines` and `refresh_rows` never read it. The remaining readers were `forget` and `seed_resolution` (removed), `_run_tick` (now calls `seed_z`), and the dock slot (removed). In the two Ruling 12 tests, the `z_custom is False` assertions are dropped. With no flag left, "the bleed marks nothing" means "nothing is remembered", and both tests already assert that through `site_resolution() == {}` or the unchanged `site_view()`.

## Tests

The new tests run on `site3_factory(samples={"A": 128})`. A's range is (-2.424, 16.41) and the union is (-2.424, 99.56). A is ready first. The helpers `_short_a_site` (reopen) and `_every_grid_shown` assert that every grid is ready and that A is the short one.

- `test_a_z_bound_never_chosen_follows_every_ready_grid`, parametrised over three cases:
  - `nothing`
  - `dz`
  - `cell`, which covers Review Minor 4.

  Each gets the full union, the remembered dz or the ready dt, the record unchanged and the survey not dirty.
- `test_a_remembered_z1_comes_back_once_every_grid_is_ready`: remembered `t1_ns=60` gives (union low, 60), and the engine holds 60.
- `test_a_remembered_range_wider_than_the_union_is_clamped_to_all_of_it`: (-50, 500) gives the union. The record is unchanged and the survey is not dirty.
- `test_a_remembered_range_past_the_first_ready_grid_comes_back_with_the_rest`: (30, 60) is wholly past A, so A alone takes the fallback. Once every grid is ready the spins read (30, 60).
- `test_a_remembered_site_z_range_wholly_outside_the_data_falls_back_to_the_ready_range`: converted to short A with (200, 300). It falls back to the full union, with no errors, a drawn slice, the record unchanged and the survey not dirty.
- `test_a_hand_z_edit_in_the_site_is_clamped_from_then_on`: converted to short A. Hand-set dz and z0 survive a transform change, and the z1 that was never edited follows the full union.
- **Cheap item 1:**
  - `test_the_site_cell_is_reseeded_only_when_the_included_grids_change` now unticks C after the hand-set 0.35. It asserts `cell_seeded_for == ("A",)` (the untick really seeded the cell again), and the cell stays 0.35.
  - New `test_a_remembered_site_cell_below_the_floor_is_clamped_up_to_it`: A is grown to 40 x 40 m and is the only grid in the site. Its floor is above 0.012, which is above the box's own 0.01. A remembered cell of 0.012 lands at the floor, the record is unchanged and the survey is not dirty. The test checks on entry and leaves at once, so no 4-million-cell frame is drawn.

**RED, on 7887292's implementation:**

```
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py -q -p no:cacheprovider -p no:xonsh -k "reseeded_only_when or below_the_floor or never_chosen or z1_comes_back or wider_than_the_union or past_the_first_ready or wholly_outside or hand_z_edit or this_grids_grid_while_the_site"
6 failed, 6 passed
```

The six failures were all A's narrowing:

- never_chosen[dz]: `(-2.424, 16.4134) == (-2.424, 99.5614)`
- z1_comes_back: `(-2.424, 16.4134) == (-2.424, 60.0)`
- wider_than_the_union: `(-2.424, 16.4134) == (-2.424, 99.5614)`
- past_the_first_ready: `(-2.424, 16.4134) == (30.0, 60.0)`
- wholly_outside: `(-2.424, 16.4134) == (-2.424, 99.5614)`
- hand_z_edit: `16.4134 == 99.5614`

The six passes were:

- the `nothing` and `cell` controls
- the untick and floor pins (behaviour that already existed)
- the two Ruling 12 tests

My first RED run had two more failures, in `nothing` and `cell`. They were a test bug: the box's 4-decimal dz compared against the raw `ready_dt`. I fixed it with `abs=1e-4`.

**GREEN:** the same command gives 12 passed.

**Mutation check.** Each mutant ran against the new tests, then the file was restored from a copy and confirmed with `cmp`.

| Mutant | Result |
|---|---|
| Clamp z1 from the spin instead of the record | caught by z1_comes_back, wider, past_first |
| A remembered dz holds z0/z1 | caught by never_chosen[dz], clamped_not_reseeded |
| No fallback | caught by wholly_outside |
| Remembered t0 ignored | caught by past_first, survives_save, clamped_not_reseeded, hand_z |

After the restores, `git diff` held only the intended changes: the only lines reading a spin's value are removals.

## Verification (tree = 4886510)

- **The two full files.** `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py -q -p no:cacheprovider -p no:xonsh` gives **177 passed** in 146.88s. That is 170 after Task 5 plus 7 new.
- **lint:** `.venv/bin/ruff check . && .venv/bin/ruff format --check .` gives `All checks passed!` and `155 files already formatted`.
- **Also run:**
  - core+pure: **821 passed, 3 skipped**
  - mypy: `Success: no issues found in 36 source files`
- **Not re-run:** the full qgis tier, which was not asked for this round.

## Concerns

- **Concern 3 from the main report is resolved.** The site's z bounds now widen again as grids become ready.
- **Still open (pre-existing, #75 "dz depends on preparation order"):** an unchosen dz is the dt of the first ready grid, so until the others are ready it is that grid's.
