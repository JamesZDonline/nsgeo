# M12 final-review fix wave: report

Base 3ef95d2, head e68419a, branch `nsgeo-m12`, pushed. Every item in `final-fix-brief.md` is done: I1, I2, M1–M5, D1–D6. Each test was written first and seen failing, then passing.

Mutant runs used `PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider`. A scratch script applied each mutant as an exact text replacement, ran the named tests, and restored the file. "KILLED" below means the named tests failed on the mutant. Every one of them passes on the committed code.

## Commits

| SHA | Subject | Items |
|---|---|---|
| 895b81f | perf(slices): compose each site grid over its own lattice window | I1 |
| d8e994c | fix(qgis): a velocity edit drops only its own grid's cube | I2 |
| c698fb8 | fix(qgis): site scope line choice, held memory, one-pass grid list | M1, M2, M3 |
| 18a9899 | fix(qgis): the site GeoTIFF records grids it left out; tests close datasets | M4, D5 |
| 997c982 | fix(slices): a frame a hair off a right angle keeps the full pitch | D3, M5 |
| 5157b38 | fix(qgis): close two trap-1 windows -- a dropped grid, and leaving the site | D1, D2 |
| 40d2bd7 | fix(qgis): an empty remembered line set is the default | D4 |
| e68419a | docs: point the site-view spec's starting state at ruling T3-c | D6 |

Each commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Push:** pushing c698fb8 and 5157b38 failed once each with `Could not resolve host: github.com`. Each retry succeeded. The branch is level with `origin/nsgeo-m12`.

## Final verification (on e68419a, the exact tree pushed)

| Check | Command | Result |
|---|---|---|
| core + pure | `./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q` | **609 passed, 2 skipped** (baseline 604 / 2). Both skips are `test_schema.py`'s "required parameters by design", not real data. |
| qgis | `QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh` | **846 passed in 378.81 s** (baseline 826, plus 20 new) |
| ruff | `./.venv/bin/ruff check .` | All checks passed |
| format | `./.venv/bin/ruff format --check .` | 133 files already formatted |
| mypy | the plan's command | Success: no issues found in 34 source files |
| concurrency loop | 17 tests × 20 runs (below) | **20/20, "17 passed" every run**, 33.0–36.8 s per run |

The real-data tests ran and did not skip: `test_real_halves_at_different_azimuths_compose_and_find_their_seam` is among the 609.

### The 20-run loop

These 17 tests ran 20 times in a row, one pytest process per run:

- Task 3's seven from `test_plugin_site_engine.py`:
  - `two_engines_never_prepare_at_once`
  - `a_preparation_that_outlives_its_cancel_wait…`
  - `a_dropped_grid_whose_preparation_outlives…`
  - `a_moved_grid_whose_preparation_outlives…`
  - `a_moved_grid_re_prepares_through_the_queue…`
  - `a_grid_moved_while_it_prepares…`
  - `closing_the_site_mid_preparation…`
- D1's new test, `a_retry_inside_a_dropped_grids_cancel_wait…`.
- Task 5's seven from `test_plugin_site_scope.py`:
  - `editing_a_grid_in_site_scope_never_overlaps…`
  - `flipping_scope_mid_preparation…`
  - `leaving_the_site_waits_out…`
  - `unload_with_the_site_scope_open…`
  - `the_list_shows_each_grids_progress…`
  - `the_site_export_is_disabled_while_a_grid_prepares`
  - `a_burst_of_slider_moves…`
- D2's two new tests:
  - `moving_this_grids_grid_while_a_site_task_outlives_its_cancel_never_overlaps`
  - `leaving_an_idle_site_hands_this_grids_moves_straight_back`

Result: runs 1–20 all exited 0 with "17 passed". There were no failures and no flakes.

## Per item

### I1. Compose over each grid's own window

**What changed**
- `nsgeo/slices/site.py`:
  - `Footprint` (:178): the window `(row0, row1, col0, col1)` and the ids for that window only, shape-checked.
  - `footprint(ids, row0, col0)` (:208): the tight window around every placed pixel of a 2-D id block.
  - `compose_footprints(lattice, layers)` (:230): accumulates each layer into its window only. It uses the same sums and counts, in the same layer order, as `compose`, so the result is bit-identical.
  - `compose` is unchanged, and its signature and behaviour are kept for existing callers. All three new names are exported from `nsgeo.slices`.
- `site_engine.py`:
  - `_gather` (:782) computes ids on the padded window, as before, then keeps the tight `Footprint`. There is no longer a whole-lattice array per grid.
  - `slice_at` (:922) calls `compose_footprints`.
- `scripts/bench_site.py`: an `--azimuths` option (default `0 30`). At 30° the block of grids is turned about the first grid's origin and the grids still meet edge to edge. The table gains bearing and pixel columns.

**Covering tests**
- Core (`test_slices_site.py`):
  - `test_a_footprint_is_the_tight_window_around_every_placed_pixel`
  - `test_footprint_compose_equals_full_compose_on_a_rotated_frame` (33°)
  - `test_footprint_compose_still_averages_overlapping_layers`: frames at 20° and 50° that overlap, with NaN cells, plus one overlap pixel checked against the mean.
  - `test_compose_footprints_refuses_a_window_off_the_lattice`
  - Real data: `test_real_halves_at_different_azimuths_compose_and_find_their_seam` gained a bit-identical footprint comparison.
- Plugin: `test_a_rotated_site_composes_exactly_as_whole_lattice_gathers_would`. B is at 30°, the pitch is 0.125 m, and B overlaps C. The tick is checked against `compose` over whole-lattice gathers with `np.array_equal(..., equal_nan=True)`.

**Mutants**

| Mutant | Result |
|---|---|
| I1-a `footprint` drops the last row (`r1 = rows[-1]`) | KILLED: 4 core tests, including the real-data one, and the plugin test |
| I1-b `footprint` drops the first column (`c0 + 1`) | KILLED: 4 core tests |
| I1-c `compose_footprints` skips the window's edge row | KILLED: rotated, overlap, real-data and plugin tests |
| I1-d `compose_footprints` skips the window's first column | KILLED: rotated, overlap and real-data tests |

### I2. A velocity edit drops only its own grid's cube

**What changed**
- `slices_engine.py`:
  - `_grid_seen` (:225) holds the chosen `Grid` as of `set_source` (:580) or the last `grids_changed`. It is cleared in `set_source` (:540) and `clear()` (:1164).
  - When the fingerprint is unchanged, `_on_grids_changed` drops `_cube` only when `grid != _grid_seen` (:893). Ruling Q still drops the engine's cube when its own grid's velocity changes.
  - The module and slot docstrings are updated.
- `site_engine.py`:
  - `_on_grids_changed` calls `_drop_stale_caches` (:551, :752) instead of `_drop_caches`.
  - `_drop_stale_caches` compares a per-grid snapshot of `(fingerprint, default_spacing)` (`_seen`, `_grid_snapshot` :743). It drops a grid's gather only when that grid's fingerprint changed, or the grid came or went. It drops the seams when any fingerprint or spacing changed.
  - The snapshot is refreshed in `set_source` and reset in `clear()`.
  - New `values_key()` (:771).
  - The geometry rebuild (resolution change, a grid becoming ready, moving or leaving) still drops everything, as it must.
- `ui/site_scope.py`:
  - `on_session_changed` (:605) no longer sets `limit_cache = None`.
  - The stretch cache key gained `engine.values_key()` (:940), which is each ready grid's registration and line spacing. A velocity-only edit keeps the stretch. A move, source, resolution, method, gain, radius or thickness change still re-measures it.
  - A spacing edit also re-measures it, because spacing sets the fill radius in cells and the seam width.

**Covering tests**
- `test_a_velocity_edit_keeps_every_other_grids_cube_and_every_cache` (site3, forced resident). Under `set_grid_velocity("B", …)`:
  - nothing re-prepares;
  - A's and C's cubes stay, and B's is dropped (Ruling Q);
  - all three gathers and the seams are the same objects;
  - `slice_at` is bit-identical afterwards, and B's cube is rebuilt on use.
- `test_a_spacing_edit_drops_the_seams_but_no_gather`.
- `test_a_velocity_edit_keeps_the_site_stretch_and_a_spacing_edit_re_measures_it` (dock): `shared_limit` is not called after a velocity edit, and is called once after a spacing edit.
- M11's Ruling Q test, `test_a_velocity_edit_drops_a_resident_cube_rather_than_serving_stale_provenance`, passes unchanged.

**Mutants**

| Mutant | Result |
|---|---|
| I2-a SliceEngine drops its cube on any grid edit (the old behaviour) | KILLED: the site cube test |
| I2-d SliceEngine never drops its cube (no Ruling Q) | KILLED: the site cube test and M11's Ruling Q test |
| I2-b SiteEngine drops every cache on any edit (old) | KILLED: the cube test and the spacing test |
| I2-c the dock drops its stretch on every session change (old) | KILLED: the dock stretch test |
| I2-e the stretch key ignores grid edits | KILLED: the dock stretch test, on the spacing half |
| I2-f a spacing edit keeps the seams | KILLED: the spacing test |
| I2-g a spacing edit drops the gathers too | KILLED: the spacing test |

### M1. A site-scope line choice is applied to its own grid

**What changed:** `plugin.py:1465`. Ruling Z's moved-selection check runs only when `dock.scope() == "grid"`. In site scope the dialog's result goes to `set_included_for(grid_id, …)`, which addresses the grid by id. The docstring is updated.

**Covering tests**
- `test_a_line_choice_is_dropped_when_the_selection_moved_meanwhile` is flipped for site scope and renamed `test_a_line_choice_goes_to_its_grid_when_the_selection_moved_meanwhile`. The chooser is opened for B and the selection moves to C. B gets the choice: 3 of 4 lines remembered, B's engine holds 3 lines, C is untouched, and there is no "grid changed" message.
- This grid's Ruling Z test, `test_plugin_loads.py::test_accepting_the_line_chooser_after_the_grid_changed_is_discarded`, is unchanged and passes.

**Mutants**

| Mutant | Result |
|---|---|
| M1-a check in both scopes (old) | KILLED: the flipped test |
| M1-b no check at all | KILLED: the M11 grid-scope test |

### M2. This grid names the site's memory

**What changed**
- `site_engine.py:969`: new `held_bytes`, the accounting `status_text` already used (prepared lines, plus a cube only where an engine is resident). `status_text` now uses it.
- `slices_dock.py:2252`: `_grid_status_text()` appends ` · +<format_bytes(held)> held by the site view` when `held_bytes > 0`. It is used for This grid's status line (:1910).

**Covering test:** `test_this_grid_names_the_memory_the_site_view_still_holds`.
- Before the site is entered there is no suffix.
- After leaving it, the status line is exactly `engine.status_text() + " · +<N MB> held by the site view"`.
- N is computed independently as the sum of `lines_bytes` (every site engine streams).

**Mutants**

| Mutant | Result |
|---|---|
| M2-a never appended | KILLED |
| M2-b appended even at 0 bytes | KILLED |
| M2-c the figure counts every cube, resident or not | KILLED: the M2 test and the existing status-line test |

### M3. One pass over the lines per refresh

**What changed:** `ui/site_scope.py`.
- New `keys_by_grid(session)` (:73).
- `grid_keys`, `source_keys`, `included_grids` and `site_rows` take an optional `by_grid`.
- `refresh_rows` (:619) builds the map once and passes it on. It also reads the included set once instead of twice.
- `site_source` and `header_z_seed` build it once per call.

**Covering test:** `test_refreshing_the_grid_list_reads_each_line_once`.
- `line_for_key` is called exactly once per line: 12 calls for site3, down from 96 before the fix.
- The rows and tooltip are unchanged.

**Mutants**

| Mutant | Result |
|---|---|
| M3-a `site_rows` walks the lines per grid | KILLED |
| M3-b `refresh_rows` reads the included set again | KILLED |

### M4. The file records included grids it left out (Ruling F-2)

**What changed**
- `site_export.py`:
  - `SiteExportPlan.left_out: dict[str, str]` (:92).
  - `plan_site_export` and `export_site` take `left_out=`.
  - The writer sets `NSGEO_SITE_LEFT_OUT` as compact JSON only when the mapping is non-empty (:234).
  - The coverage companion carries it too, because it leaves out the same grids.
  - The module docstring lists the key.
- `site_scope.left_out_states` (:208) maps grid id to its `grid_state` for failed or "no lines" grids. `left_out` (the message text) is built from it.
- The dock has `site_left_out_states()` (:2355), and the plugin passes it (`plugin.py:924`).

**Covering tests**
- `test_plugin_site_export.py::test_an_included_grid_left_out_is_recorded_and_absent_otherwise`:
  - the key is absent by default;
  - present it is exactly `{"D":"no lines","E":"failed: no line could be prepared"}`;
  - the companion carries it too.
- `test_plugin_site_scope.py::test_the_site_file_records_an_included_grid_it_left_out` (through the plugin):
  - the key is absent with every grid present;
  - with C made "no lines" it reads back as `{"C": "no lines"}`, which equals `grid_state("C")`.

**Mutants**

| Mutant | Result |
|---|---|
| M4-a the key is written even when empty | KILLED: both tests (see D5 for the crash this exposed) |
| M4-b the key is never written | KILLED: both |
| M4-c the plugin does not pass `left_out` | KILLED: the plugin test |
| M4-d not compact JSON | KILLED: the export test |

### M5. The refusal names the half pitch

**What changed:** `site_engine.py:608`. When `lattice.pixel < res.cell`, the `MAX_FRAME_CELLS` refusal adds: "A rotated grid puts the site on a half-cell pitch (0.125 m for a 0.25 m cell), four times the pixels of the same grids north-up." The rest of the message is unchanged.

**Covering test:** `test_a_refusal_with_a_rotated_grid_names_the_half_cell_pitch`. With the grids far apart and north-up, "half-cell" is absent. With C also at 30°, the sentence is present and the message still ends "Choose a coarser cell or include fewer grids".

**Mutants**

| Mutant | Result |
|---|---|
| M5-a never named (old) | KILLED |
| M5-b always named | KILLED |

### D1. `_drop_grid` order

**What changed:** `site_engine.py:383`. `_drop_grid` takes the grid off `_queue`, then pops `_states` and `_errors`, and only then calls `_drop_engine`. It has a docstring giving the reason.

**Covering test:** `test_a_retry_inside_a_dropped_grids_cancel_wait_does_not_re_dispatch_it`.
- Setup:
  1. A's task outlives a 1 ms cancel.
  2. `set_source(ABC)` resumes with A at the head of the queue.
  3. `set_source(BC)` drops A.
- A's `cancel_preparation` is wrapped to call the real one, which waits out A's task, and then the retry slot `_dispatch_next()`. That models the retry timer firing inside the wait.
- Expected: no stall, B and C ready, no live task, `max_concurrent == 1`.
- The retry is injected at the moment the brief describes; I did not find a natural event ordering that reaches it deterministically. See Concerns.

**Mutant:** D1-a, the old order (engine first). KILLED. "the queue stalled behind the dropped grid": `wait_until_idle(10 s)` is False, because A was re-dispatched on the engine being released and `_preparing` never cleared.

### D2. Leaving the site keeps `_mark_grid_stale` until no site task is live

**What changed:** `slices_dock.py`.
- `set_scope("grid")` no longer resets `engine.on_grid_moved` (comment at :2192).
- `_resume_grid` always ends with `_run_pending_grid_prepare()` (:2227).
- `_run_pending_grid_prepare` retries while `site_engine.has_live_task`. Once no site task is live, it sets `engine.on_grid_moved = None` (:2291) and only then runs any owed preparation.
- The docstrings of `_mark_grid_stale` and `_run_pending_grid_prepare` say so.

I first also restarted the retry timer from `_mark_grid_stale`. I removed that because it was redundant: the hook is only still installed in This grid scope while `_resume_grid`'s retry is running, so a mutant removing it would have survived.

**Covering tests**
- `test_moving_this_grids_grid_while_a_site_task_outlives_its_cancel_never_overlaps`:
  - `_CANCEL_TIMEOUT_MS = 1` and 0.8 s per line, so the window is wide.
  - The site is reading A's first line when the dock leaves the site, and the site task outlives its cancel.
  - A is then moved. This grid's engine does not start (`is_running` False), then prepares at the new origin.
  - `max_concurrent == 1`, and `on_grid_moved is None` afterwards.
- `test_leaving_an_idle_site_hands_this_grids_moves_straight_back`: with no site task live, the hook is None immediately after leaving.

**Mutants**

| Mutant | Result |
|---|---|
| D2-a hook reset on leaving (old) | KILLED at `assert not dock.engine.is_running`. With that one line removed in a scratch copy, the same mutant fails on **`two preparations ran at once (max_concurrent=2)`**: the old code really overlapped. |
| D2-b hook never reset | KILLED |
| D2-d `_resume_grid` runs the owed preparation only when one is owed (old) | KILLED: the idle-site test |

### D3. Azimuth snap (Ruling F-5)

**What changed**
- `nsgeo/slices/site.py`:
  - `AXIS_SNAP_CELLS = 0.01` (:35).
  - `snap_azimuth(azimuth_deg, extent_m, cell)` (:116) returns the nearest multiple of 90° when `extent_m * |sin(deviation)| < 0.01 * cell`, and the azimuth unchanged otherwise. Both are exported.
- `site_engine._covering_lattice` (:672) feeds `lattice_pixel` the snapped bearing, with `extent_m = hypot(nx, ny) * cell`. That is the distance to the frame's far corner, the corner the ruling names.

**Covering tests**
- Core `test_a_frame_a_hair_off_a_right_angle_counts_as_axis_aligned`:
  - 1e-6°, 90 + 1e-6°, -1e-6° and 270 - 1e-6° snap, and give pitch = cell.
  - 2° stays at cell / 2.
  - The threshold is pinned at 0.9% (snaps) and 1.1% (does not) of a cell.
- Plugin `test_a_grid_a_hair_off_north_keeps_the_full_cell_pitch`, with B rotated by each of:

  | B's bearing | Lattice pitch |
  |---|---|
  | 1e-6° | cell |
  | 90 + 1e-6° | cell |
  | 0.01° | cell |
  | 2° | cell / 2 |
  | 0.02° | cell / 2 |

  At 0.02° B's 8.49 m far corner moves 3.0 mm, over the 2.5 mm limit. Along one 6 m side it would be 2.1 mm and would wrongly snap.

**Mutants**

| Mutant | Result |
|---|---|
| D3-a no snap (old) | KILLED: 1e-6, 90 + 1e-6 and 0.01 |
| D3-b extent along one side | KILLED: 0.02 |
| D3-c threshold 10% of a cell | KILLED: plugin 0.02 and the core threshold test |
| D3-d snap every azimuth | KILLED: core |

**Side effect:** `test_a_grid_in_another_crs_lands_where_its_coordinates_say` (B declared in EPSG:32615) now runs at the full pitch, and still passes. Near the equator the zone change turns B by only 0.000665°, which moves its far corner 0.098 mm. The test still exercises what it is for, the transform of pixel centres into B's CRS.

### D4. An empty remembered line set is the default

**What changed:** `slices_dock.py`.
- `_restore_remembered_source` (:868): if the remembered keys filter to nothing, which is an empty choice or lines that have all left the grid, `_included` becomes every line and `_included_is_default = True`.
- `_remember_source(every_line=False)` (:872).
- `restore_cube` passes `every_line="lines" not in record` (:1620), so a record with no `lines` key remembers `lines=None`. The dock itself still restores that record's empty inclusion set, as M11's documented behaviour has it.

**Covering tests**
- `test_an_empty_remembered_line_set_is_the_default`, parametrised over `()` and a key not on the grid. The dock includes every line of A, and a line imported later is picked up, so it is still the default.
- `test_a_cube_record_with_no_lines_key_is_remembered_as_every_line`: `slice_source("A")["lines"] is None`, and `included_keys() == ()`.

**Mutants**

| Mutant | Result |
|---|---|
| D4-a the empty filtered set is kept (old) | KILLED: both parametrisations |
| D4-b every line, but not marked default | KILLED: both |
| D4-c a no-lines record remembered as `[]` (old) | KILLED |

### D5. A failing export test exits 1, not 139

**What changed**
- `test_plugin_site_export.py`: `open_tif` is now a fixture. It records every dataset it opens and calls `Close()` on each at teardown. GDAL 3.8.4's `Close()` releases the dataset however many Python references remain. Every test that opens a file takes the fixture.
- `test_plugin_site_scope.py` had the same latent crash:
  - The new M4 test reads metadata through `_metadata(path)`, which closes the dataset before any assert runs.
  - The existing `test_export_routes_to_the_site_geotiff_in_site_scope` now calls `ds.Close()` in its `finally` instead of `ds = None`. Pytest's rewritten assert keeps a bound `ds.GetMetadata` / `ds.GetRasterBand` in its temporaries, so `ds = None` does not release the dataset.

**The check**
- Scratch copy `test_zz_scratch_d5.py`, with `assert ds.RasterCount == -1` forced into `test_there_is_a_band_per_planned_window`:

  | Code | Exit |
  |---|---|
  | Before the fix | **139**, "Segmentation fault (core dumped)" |
  | After the fix, that test alone | **1** |
  | After the fix, the whole scratch file | **1** (1 failed, 16 passed) |

- Scratch copy `test_zz_scratch_d5b.py`, forcing a failure in the site-scope export test: exit **1** with `Close()`, and **139** with the old `ds = None`.
- M4-a's first run had also crashed with -11 in the new site-scope test before `_metadata` existed. That is how the second instance was found.
- Both scratch files were deleted, and nothing was committed from them.

### D6. Spec drift

`docs/superpowers/specs/2026-10-16-nsgeo-site-view-design.md:142`, §3 starting state, directly under the residency paragraph, now has one line: "*M12 changed this to a per-trace estimate (ruling T3-c): see `slices_plan.choose_residency`.*" The rest of the paragraph is untouched.

## Benchmark (I1)

Command, from the worktree root, one process per configuration, run in sequence with nothing else of mine running:

```
QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python packages/nsgeo-qgis/scripts/bench_site.py \
    --sizes <50|20> --azimuths <30|0> --workdir <scratchpad>
```

**Why one process each:** the first attempt, all four configurations in one process, was killed at its 30-minute limit after both 20 m sites. The machine had about 1 GB of memory available at the time, swap was full, and the load average was around 240 (4 cores), so the 50 m site was thrashing. Once that process ended, about 5.5 GB was available and the per-configuration runs each took under a minute.

The 50 m at 30° row below is a rerun at a 1-minute load of 4.8. The first run, at a load of about 45 that was still falling, gave 104.4 / 122.6 ms, so the median agrees.

### New table, verbatim (head e68419a)

```
10 grids per site, 0.5 m line spacing, 60 traces/m, 128 samples/trace (time_zero, dewow, gain_agc; transform none); cell 0.25 m, native dz, thickness 5 ns, radius 1.5 spacings; 20 windows per timing.

| site | bearing | lines | traces/line | lattice (pixel) | engine mode | prepare site (s) | first tick, incl. cube builds (ms) | slice_at median / p90 (ms) | edge median / p90 (ms) | shared_limit (ms) | one-grid baseline median / p90 (ms) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 10 x 50 m | 0° | 1000 | 3000 | 1000 x 400 (0.25 m) | 10 resident | 14.4 | 2718 | 35.0 / 35.9 | 43.2 / 45.6 | 132 (4 windows at 5 ns); 354 (12 at 1.5 ns) | 2.9 / 3.0 |
| 10 x 50 m | 30° | 1000 | 3000 | 2133 x 1693 (0.125 m) | 10 resident | 13.2 | 3288 | 104.1 / 105.5 | 123.1 / 125.3 | 128 (4 windows at 5 ns); 348 (12 at 1.5 ns) | 2.9 / 2.9 |
| 10 x 20 m | 0° | 400 | 1200 | 400 x 160 (0.25 m) | 10 streaming | 2.4 | 210 | 86.5 / 88.1 | 88.5 / 89.6 | 341 (4 windows at 5 ns); 565 (12 at 1.5 ns) | 8.6 / 8.9 |
| 10 x 20 m | 30° | 400 | 1200 | 853 x 678 (0.125 m) | 10 streaming | 2.5 | 295 | 112.5 / 115.3 | 116.3 / 118.3 | 383 (4 windows at 5 ns); 620 (12 at 1.5 ns) | 9.8 / 10.1 |

10 x 50 m at 0°: 10 grids · 1000 lines held in memory, 1.2 GB · slices redraw in 44 ms; site axis 88 levels; set_resolution 1 ms; one grid's tick is 0.4 ms binning + 2.5 ms fill (medians); lines written in 7 s; 0 errors
    forced resident, for comparison (142 MB of cubes, built in 35 ms): slice_at median / p90 35.5 / 36.0 ms
10 x 50 m at 30°: 10 grids · 1000 lines held in memory, 1.2 GB · slices redraw in 121 ms; site axis 88 levels; set_resolution 1 ms; one grid's tick is 0.4 ms binning + 2.5 ms fill (medians); lines written in 4 s; 0 errors
    forced resident, for comparison (142 MB of cubes, built in 83 ms): slice_at median / p90 102.9 / 104.4 ms
10 x 20 m at 0°: 10 grids · 400 lines held in memory, 169 MB · slices redraw in 89 ms; site axis 88 levels; set_resolution 1 ms; one grid's tick is 8.1 ms binning + 0.5 ms fill (medians); lines written in 0 s; 0 errors
    forced resident, for comparison (23 MB of cubes, built in 342 ms): slice_at median / p90 6.7 / 6.9 ms
10 x 20 m at 30°: 10 grids · 400 lines held in memory, 169 MB · slices redraw in 116 ms; site axis 88 levels; set_resolution 1 ms; one grid's tick is 9.3 ms binning + 0.5 ms fill (medians); lines written in 0 s; 0 errors
    forced resident, for comparison (23 MB of cubes, built in 380 ms): slice_at median / p90 20.2 / 20.4 ms
```

The engine mode column is the residency chosen automatically. The "forced resident" lines are for comparison only.

### Before and after, same machine and same session

The 3ef95d2 code ran the same bench script from a detached scratch worktree, since removed. Its `nsgeo` resolved to that worktree's own core, which I checked.

| 10 × 50 m, `slice_at` median / p90 | 3ef95d2 (before) | e68419a (after) |
|---|---|---|
| north-up (1000 × 400, 0.25 m) | 62.6 / 64.7 ms | **35.0 / 35.9 ms** |
| 30° (2133 × 1693, 0.125 m) | 355.7 / 361.7 ms | **104.1 / 105.5 ms** |

`compose` alone, pure numpy, on the same ten-frame geometry, with 15 calls each. The outputs were checked bit-identical with `np.array_equal(..., equal_nan=True)`:

| | `compose` (whole-lattice gathers) | `compose_footprints` |
|---|---|---|
| north-up, 0.40 Mpx (footprints 0.40 Mpx in all) | 31.3 / 32.5 ms | **5.8 / 6.2 ms** |
| 30°, 3.61 Mpx (footprints 2.98 Mpx in all) | 276.5 / 282.2 ms | **44.4 / 46.4 ms** |

These match the reviewer's figures: `compose` at 281–426 ms before, and the prototype at 44 ms (30°) and 5 ms (north-up).

The rest of the 104 ms tick at 30° is made of three parts:
- the ten grids' bin and fill, about 29 ms, which does not depend on the bearing;
- the per-tick full-lattice float64 sum, count and divide and the float32 cast. Bit-identity with `compose` needs these.
- normalisation, the coverage `where` and the readout.

The 10 × 20 m site stays streaming, at about 9 ms of binning per grid, as Task 3 found.

## Files changed (3ef95d2..e68419a)

- `docs/superpowers/specs/2026-10-16-nsgeo-site-view-design.md`
- `packages/nsgeo-core/src/nsgeo/slices/__init__.py`
- `packages/nsgeo-core/src/nsgeo/slices/site.py`
- `packages/nsgeo-core/tests/test_slices_site.py`
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- `packages/nsgeo-qgis/nsgeo_qgis/site_engine.py`
- `packages/nsgeo-qgis/nsgeo_qgis/site_export.py`
- `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`
- `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py`
- `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`
- `packages/nsgeo-qgis/scripts/bench_site.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_site_engine.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_site_export.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`

There is no new dispatch path. Every preparation still starts only from `SiteEngine._start_next` (behind `_anything_live`) or This grid's `prepare()` (behind `site_engine.has_live_task`). D1 and D2 narrow the existing paths.

## Concerns

1. **D1's test injects the retry.** I could not find an event ordering that reaches the hazard on its own.
   - The cancelled task's `finished` quits the confirm wait from inside the same callback that clears `has_live_task`.
   - So the test wraps the dropped grid's `cancel_preparation` to call `_dispatch_next()` once the real wait returns. That is "a retry timer that fires inside the cancel wait", placed at the one moment that matters.
   - The fix is structural: the grid is off the queue before any wait can start. With the old order the injected retry re-dispatches the dropped grid and the queue stalls.
2. **D2 changes when This grid's engine regains M11's self re-preparation.** Before, it was regained on leaving the site; now it waits until no site task is live.
   - In the normal case, with nothing live, this still happens before `set_scope` returns: `_resume_grid` ends with `_run_pending_grid_prepare`, which is now called every time, not only when a preparation is owed.
   - M11's tests are unchanged and pass.
3. **The same exit-139 pattern is in M11's `test_plugin_slice_export.py`.** It uses `try: … finally: ds = None` in eight places (lines 107–499). A failing assert there can hold the dataset through pytest's assert temporaries and crash at `exitQgis()`, as I reproduced for the site tests (D5). I did not touch it, because M11's tests stay unchanged. `ds.Close()` in those `finally` blocks is the one-line fix.
4. **I2's stretch key includes each grid's line spacing**, in addition to the brief's list (fingerprint, source, resolution, method, gains, radius, thickness). A spacing edit changes the fill radius in cells and the seam width, so it changes the values drawn. A velocity edit never re-measures.
5. **D4 makes This grid and the site disagree on an empty remembered set.** This grid treats it as every line, as the brief rules. The site still treats it as "no lines", and the existing export left-out test relies on that. I followed the brief, which limits D4 to the dock's restore.
6. **D3 moves one existing test to the full pitch.** `test_a_grid_in_another_crs_lands_where_its_coordinates_say` declares B in EPSG:32615. Near the equator that turns B by 0.000665° on the EPSG:32616 site, a 0.1 mm corner shift, so B now snaps and the site uses the full pitch there. The test still checks the transform of pixel centres into B's CRS, and passes.
7. **M4's `left_out` comes from the caller.** The plugin passes `dock.site_left_out_states()`. A direct `export_site` caller that passes nothing writes no key. The engine knows only the grids it was sent, not what the user included.
8. **Noise in mutant runs only.** Failing plugin tests printed GDAL `ERROR 1: sqlite3_get_table … unable to open database file` at teardown. This never appears in passing runs.
9. **The machine was under heavy memory pressure** for much of this session: swap full, and the load average at times above 200 on 4 cores. The full qgis tier, the 20-run loop and the final benchmark rows all ran after it eased, and are consistent. The loop timings varied only 33–37 s per run.

