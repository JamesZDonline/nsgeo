# Task 3 report: This grid — the method, the preview, refining, the cache, the stretch

**Status:** DONE_WITH_CONCERNS (minor; listed at the end)

**Commits** (pushed to `origin nsgeo-slice-interpolation-b`):
- `c3d4459` feat(slices): minimum curvature in the engine — kriging preview, solved-slice cache, background jobs
- `0c3eeeb` feat(slices): minimum curvature in This grid — kriging preview, background refine, solved-slice cache

## What I implemented

**`slices_plan.py`**
- `METHOD_LABELS["min_curvature"] = "Minimum curvature"`.
- New constants, with the exact values from the table: `LIVE_SOLVE_BUDGET_MS = 50.0`, `REFINE_REST_MS = 300`, `SOLVED_SLICES_KEPT = 16`, `PREVIEW_METHOD = "kriging"`, `PREVIEW_STATUS` and `REFINING_STATUS`.

**`ui/finish_panel.py`**
- `_METHOD_TIP` gains the brief's minimum-curvature line, placed after Inverse distance and before None.

**`slices_engine.py`**
- `solve_key(values)` (module function): `blake2b(values.tobytes(), digest_size=16)`, updated with `str(shape)` and `str(dtype)`.
- `PendingSolve` (a `RefineJob`):
  - It holds the engine, the plan (identity is what `land` checks), a private copy of the values, and `key`.
  - `run(should_stop)` solves and times it, sets `solved` and `ms`, then releases its values.
  - `land()` goes through `engine._land(plan, key, solved, ms)`. That stores the result only if `engine._weights[1] is plan`, and returns whether it did.
- `_weights` is now `(key, fill, preview)`.
  - For `min_curvature`, `_fill_for` builds the `CurvaturePlan` and a `PREVIEW_METHOD` `FillWeights` at the same max distance and search radius, together and under one key. For every other method, `preview` is None.
  - `_solved` (an LRU `OrderedDict`) and `_last_solve_ms` sit beside it.
  - `_drop_fill()` empties all three. It is called from `set_source`, `clear` and every rebuild.
  - `_rebuild_geometry` keeps all three together when the frame is unchanged (a z-only edit) and drops them otherwise.
- `finish()` keeps its signature. For min_curvature it is `smooth(cached or freshly solved slice)`, and a fresh solve's time goes into `_last_solve_ms`.
- New on `SliceEngine`, as specified: `last_solve_ms`, `finish_is_slow`, `preview`, `pending_solve`, `stretch_solves`, and `shared_limit(..., *, preview=False)`.
  - `shared_limit` measures min_curvature over `limit_windows`. For other methods it is unchanged.
  - `finish_is_slow` builds nothing. It is True when the plan for these settings and cells isn't held, so the first draw on a new plan is always a preview.
- `weights_nbytes` counts the plan, the preview and the cache.
- `weights_cached` keeps key-only semantics, which for min_curvature means the plan and the preview are both built.
- Annotations widened to `SliceFill`.
- The module docstring gains a hazard bullet: a background solve must never land on a plan it wasn't made from.

**`ui/slices_dock.py`**
- New state: `self.refiner = Refiner(self)`, `self.provisional`, the `_rest` single-shot timer (`REFINE_REST_MS`), and the previewed `(values, coverage)` with its key and the done/total counts.
- `refresh_slice` delegates the finish draw to a focused `_finished(...)` that follows the brief's state machine:
  - **Slow min_curvature:** `refiner.cancel()`, then `preview` (under `busy_cursor()` when not cached), `provisional = True`, remember the slice and key, and `rest.start()`.
  - **Otherwise:** a full `finish`, `provisional = False`. Any method other than min_curvature also cancels the refiner and stops the rest.
  - The coverage view sets `provisional = False`.
  - The early-return and `except` branches call `_end_refine()`, which cancels, stops the rest and clears the provisional state.
  - The status line comes from `_refine_status()`: REFINING while busy, PREVIEW while provisional, and `_grid_status_text()` otherwise.
- `_on_rest`, `_on_landed` and `_on_refine_error` follow the pseudo-code. Each guards its own body (`# noqa: BLE001`) and reports through `error` or `_log`.
  - **`_on_rest`:** the current job, then the stretch jobs when the stretch is shared. It drops Nones and dedupes by key, then starts the refiner and sets REFINING_STATUS (0 of N).
  - **`_on_landed`:** `land()`, then bump the count. It redraws once if the job is the previewed slice, or the list ended (dropping a provisional stretch); otherwise it updates the count.
  - **`_on_refine_error`:** emits `minimum curvature failed: {message}`, restores the normal status, and leaves the preview.
- `_shared_limit_cache` is now `(key, value, final)`.
  - Writers are `_on_prepared` (two places), `_apply_resolution` (sets None), `display_limit` and `_on_landed` (drops a provisional entry). The only reader is `display_limit`. Site scope has its own cache and doesn't touch it.
  - `display_limit`'s shared branch: if `stretch_solves` is non-empty, use `shared_limit(preview=True)` with `final=False`, and `rest.start()` if the refiner is idle. Otherwise use the final measurement.

**`plugin.py`**
- `unload()` calls `self.slices_dock.refiner.shutdown()` before `dispose_site()`.

## Tests and results

| Tier | Command | Result |
|---|---|---|
| core + pure | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider` | **990 passed, 3 skipped** (baseline 982 + 8 new) |
| QGIS, full | `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:cacheprovider -p no:xonsh` | **1406 passed in 694 s** (baseline 1380 + 26 new) |
| QGIS, dock file after the extra error-path test | `... test_plugin_slices_dock.py` | **125 passed** (that test was added after the full run, so the suite total is now 1407) |
| lint | `.venv/bin/ruff check . && .venv/bin/ruff format --check .` | All checks passed; 168 files already formatted |
| types | the plan's mypy command | Success: no issues found in 39 source files |

- **Flakiness check.** The 21 new engine and dock tests were repeated 5 times: 21 passed each time.

**New tests**
- **Pure:**
  - `min_curvature` added to the close-every-gap (5 cases), skipped-line and estimate parametrisations.
  - `test_method_labels_follow_methods`.
- **Engine (11):**
  - `test_minimum_curvature_finishes_through_the_engine`
  - `test_the_preview_is_kriging_at_the_same_max_distance`
  - `test_a_repeated_solve_is_served_from_the_cache`
  - `test_the_solved_slice_cache_never_serves_other_values` (also pins that the key covers shape and dtype)
  - `test_the_cache_keeps_at_most_sixteen_and_drops_with_the_plan` (also: a z-only edit keeps it)
  - `test_finish_is_slow_follows_the_last_solve` (also: exactly the budget is not slow)
  - `test_a_pending_solve_lands_in_the_cache` (also: the job solves its private copy)
  - `test_a_solve_for_a_dropped_plan_does_not_land[source|cell]`
  - `test_the_minimum_curvature_stretch_is_measured_over_twelve_windows_at_most`
  - `test_weights_nbytes_counts_the_plan_the_preview_and_the_cache`
- **Dock (10):**
  - `test_a_slow_slice_shows_the_preview_then_refines[slider|step]`
  - `test_the_refine_waits_for_the_depth_to_rest`
  - `test_a_quick_solve_draws_minimum_curvature_at_once`
  - `test_kriging_never_previews`
  - `test_a_refine_for_a_window_left_behind_never_draws`
  - `test_the_shared_stretch_is_provisional_until_its_windows_are_solved`
  - `test_a_landed_slice_does_not_cancel_the_stretch_solves`
  - `test_unloading_mid_refine_stops_the_worker`
  - plus `test_a_failed_refine_is_reported_and_leaves_the_preview`, which is not in the brief
- **Export:** `test_view_settings_round_trip_the_finish` and `test_a_record_from_this_build_still_loads_in_0_2_0` are parametrised over `METHODS`.
- **Fixture:** the `docked` fixture's teardown now calls `dock.refiner.shutdown()` first.

## TDD evidence

**RED**
- **Pure.** `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py -q -p no:cacheprovider` gave `FAILED test_method_labels_follow_methods — AssertionError: assert ['none', 'idw', 'kriging'] == ['none', 'idw...in_curvature']` (1 failed, 55 passed).
  - Expected: the label is missing.
  - The new min_curvature parametrisations already passed, because Task 1's core exists.
- **Engine.** The QGIS command on `test_plugin_slices_engine.py` gave `ImportError: cannot import name 'PendingSolve' from 'nsgeo_qgis.slices_engine'` (collection error). Expected.
- **Dock.** The QGIS command on `test_plugin_slices_dock.py` gave `ImportError: cannot import name 'solve_key' from 'nsgeo_qgis.slices_engine'`. Expected; `refiner`, `provisional` and `_rest` didn't exist either.
- **Export.** Both parametrisations already passed (8 passed). That is expected and not a RED: `SliceFinish.updated` already accepts any key in `METHODS`, so these are coverage pins.

**GREEN**
- Pure: 56 passed.
- Engine: 57 passed. The first GREEN attempt failed on my own test: its reference solve went through the counted `CurvaturePlan.solve`. Fixed by computing the reference first and clearing the counter.
- Dock: the 9 new tests passed, and the whole file 125 passed.
- `test_plugin_finish_panel.py::test_the_tooltips_are_the_pinned_copy` failed as a direct result of the specified tooltip change, and I updated its pinned copy.

**Mutation checks**, run on a scratch copy of `packages/` under the session scratchpad, never in this worktree. All 8 mutants were killed:

| # | Mutant | Killed by |
|---|---|---|
| M1 | `land` without the plan-identity check | `dropped_plan[source,cell]` |
| M2 | a preview draw doesn't cancel the refiner | `left_behind` |
| M3 | a full minimum-curvature draw also cancels | `landed_slice` |
| M4 | unload without `refiner.shutdown()` | `unloading_mid` |
| M5 | a provisional stretch is never dropped | `provisional_until` |
| M6 | `finish_is_slow` ignores the cache | `finish_is_slow` |
| M7 | the cache key without shape and dtype | `never_serves` |
| M8 | the rest timer isn't restarted on each preview | `waits_for_the_depth` |

## Files changed

- `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`
- `packages/nsgeo-qgis/nsgeo_qgis/ui/finish_panel.py`
- `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`
- `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`
- `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- `packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_finish_panel.py` (pinned tooltip copy; not in the brief's file list)

## Departures from the brief, and why

1. **The estimate test measures `plan_fill` plus one `apply` for `min_curvature` only.**
   - Measured with chunks at 1024/256: IDW and kriging are 108.5 and 109.3 B/cell to build, but 149.6 and 149.7 B/cell with an `apply`. That is over the unchanged 144 bound.
   - Their `apply` is a per-slice transient, which `MAX_FRAME_CELLS` already counts at about 55 B/cell. Ruling R2 asked for plan + apply for minimum curvature.
   - Minimum curvature measures 103.3 B/cell, plan plus solve. The docstring says this.
2. **Added a public `solve_key(values)` in `slices_engine`.** The dock needs "the current job key" at preview time, before any job exists. `PendingSolve.key` is computed with the same function.
3. **`PendingSolve(..., copy=False)` is used only by `stretch_solves`, and `run` releases its values afterwards.** `stretch_solves` passes arrays the engine has just sliced for that job alone, which are already private. Without this, a `display_limit` cache miss would copy 12 slices just to test emptiness, and a 12-job list would hold every copy until the list ends.
4. **`_on_rest` dedupes jobs by key**, because the slice on screen can also be a stretch window. `REFINING_STATUS`'s total is the deduped count.
5. **`_wait_for_refine` also waits while `dock._rest.isActive()`**, because a list ending can restart the rest when a stretch is still provisional.
6. **`_end_refine` restores the normal status text** in the early-return and `except` branches, but only when a preview or refine was showing. Otherwise the label would keep saying "Kriging preview" with nothing drawn.
7. **`_rest` is built at the top of `__init__`, next to `refiner`.** `refresh_slice`'s `except` branch reaches both, and a timer built mid-constructor would have turned an early call into an escape from the `except` itself.
8. **`_on_rest` returns in site scope or the coverage view, and `_on_landed` doesn't redraw in site scope.** Task 4 owns the site; a This-grid result still lands in This grid's cache.

## Self-review findings

- **The redraw key check is defensive.** In `_on_landed`, `job.key == self._refine_key` can't currently be made to matter by a test. While `provisional` is True, any running list was started after the latest preview, with the current job first. I kept it as the brief specifies. A mutant removing it would survive.
- **The engine module docstring's "Five hazards, …" count was already stale** (7 bullets before this task, 8 now). I left the sentence alone.
- **Switching min_curvature → kriging → min_curvature drops the plan and its cache**, because the engine holds a single weights slot. That is plan call 8 as written; the walkthrough may notice the second preview pass.
- **A coverage-view draw doesn't cancel a running refine.** It is neither a preview nor "another method", and the solves still fill the cache.
- **Status text and the site's refiner.** `_refine_status()` reads `refiner.busy`. Once Task 4 starts site lists on the same refiner, This grid's status logic must not misread a site list. Today only This grid starts lists.

## Concerns

1. **Two timing assumptions in the dock tests.**
   - `test_the_refine_waits_for_the_depth_to_rest` asserts that nothing starts within about 100 ms of each move, with a 300 ms rest. A stall over 200 ms in event processing on a loaded CI runner could flake it.
   - The same test allows a coarse Qt timer to fire up to 10% early (Qt documents 5%).
   - Neither depends on solve timing. Both were stable here over 5 runs plus the full suite.
2. **`test_unloading_mid_refine_stops_the_worker` asserts that no `nsgeo-refine*` thread is alive anywhere**, as the brief says. It would also fail if some other test leaked a started `Refiner`. Today only `docked`-fixture tests start lists, and that fixture now shuts the refiner down.
3. **Whole site before Task 4.** Its Method combo now offers Minimum curvature too, since it shares `METHOD_LABELS`. Choosing it there solves synchronously per grid on the GUI thread, and builds an unused kriging preview per grid, until Task 4 wires the preview and refine.
4. **Transient memory not in plan call 9's figures.** While a refine list is queued, each job not yet run holds its values. That is 4 B/cell per job: the current slice's copy, plus at most 12 stretch windows, which aren't copied. The values are released as each job runs. It is roughly 0.2 GB at the 4-million-cell cap with 12 windows queued.
5. **The baseline in the brief is out of date.** Step 5 says "1366 + the new QGIS tests"; the actual baseline was 1380, after Task 2, and the result is 1406, or 1407 with the extra error-path test.

---

# Fix round 1 (Ruling R10): all six minor findings

**Commit:** `e8a0d9e` fix(slices): hash a slice once per draw; never strand a preview; drop the old plan before building. Pushed.

## What changed

1. **Hashing once per draw.**
   - `finish`, `finish_is_slow` and `pending_solve` take an optional keyword `key: bytes | None = None` (`finish` keeps its positional signature).
   - The dock's `_finished` hashes once, only for min_curvature, and passes the key to `finish_is_slow` and `finish`. It stores the same key as `_refine_key`, and `_on_rest` passes it to `pending_solve`.
   - Result: the slow path, the fast path and the landed redraw each hash once, and the rest's job hashes nothing.
   - `display_limit` no longer calls `stretch_solves`. A new `engine.stretch_limit(thickness_levels, clip, finish) -> (value, final)` does it in one pass. It slices and hashes each window once and builds no jobs. If every window is cached, it smooths the cached solves (equal to `shared_limit(...)`, final). At the first window not solved, it returns `shared_limit(..., preview=True)`, provisional. Other methods return `(shared_limit(...), True)`.
2. **Never strand a preview.**
   - (a) `_on_rest`: when `provisional` is set and no job was made for the current slice (solved meanwhile, or no longer min_curvature), it calls `refresh_slice()`. That happens after starting any stretch jobs, since a full draw doesn't cancel them. When no job at all is made and the cached stretch is non-final, it drops that entry and redraws too: every window is solved, so the final stretch can be measured.
   - (b) `display_limit`: a cached entry that isn't final re-arms the rest when the refiner is idle and no rest is active.
   - Related, for LRU safety: `_job_for` marks a cached slice recently used (`move_to_end`) when it declines to make a job. Without it, landing a list could evict the stretch windows the list is completing, so the re-arm in (b) could cycle through several rounds before settling.
3. **Drop before building.** `_fill_for` calls `_drop_fill()` before `plan_fill`.
4. **The estimate test's data.** It now uses `sin(x·0.05) + cos(y·0.03)` on the binned rows and asserts the solve iterated (`fw.solve(values)[1] > 0`). Measured with a smooth field: 103.2 B/cell over 328 iterations; with a random field: 103.2 B/cell over 438 iterations; with the old constant data: 103.3 B/cell over 0 iterations. The bound is unchanged at 144.
5. **Timing-fragile tests.**
   - The unload test asserts only on its own worker: the thread the looping job recorded, named `nsgeo-refine*`, must stop within 2 s. The process-wide scan helper is gone.
   - `test_the_refine_waits_for_the_depth_to_rest` no longer processes events between moves. It sleeps 100 ms with `time.sleep`, so the rest cannot fire between moves however long the process stalls. It asserts `remainingTime()` after each move is greater than just before it (the restart), that nothing started, and that the refiner starts once, at least 0.9 × `REFINE_REST_MS` after the last move.
6. **`display_limit`'s docstring** now says it arms the rest timer, from a fresh provisional measurement and from a cached one.

Test wrappers that patch `engine.pending_solve` now accept `**kwargs`, since the dock passes `key=`.

## New tests

- Engine:
  - `test_a_rebuild_drops_the_old_plan_before_building_the_new`: `weights_nbytes` is 0 at both `plan_fill` calls.
  - `stretch_limit` assertions (provisional, final, kriging) in the twelve-windows test.
- Dock:
  - `test_a_preview_solved_during_the_rest_is_drawn_at_the_rest` (2a)
  - `test_a_provisional_stretch_left_by_a_failed_refine_is_retried_at_the_next_draw` (2b)
  - `test_a_draw_hashes_its_slice_once` (1)

**Mutants** (scratch copy, never this worktree). All killed:

| Mutant | Killed by |
|---|---|
| no redraw at an empty rest | the 2a test |
| no re-arm for a cached provisional stretch | the 2b test |
| the full draw re-hashes | the hash test |
| the rest re-hashes | the hash test |
| drop after building | the drop-before-build test |
| the rest not restarted by a move | the rest test |

## Commands and outputs

| Command | Output |
|---|---|
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py -q -p no:cacheprovider` | `56 passed in 1.96s` |
| `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py -q -p no:cacheprovider -p no:xonsh` | `58 passed in 5.24s` |
| the same, `test_plugin_slices_dock.py`, three runs | `128 passed in 40.24s`, `128 passed in 40.14s`, `128 passed in 39.94s` |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider` | `990 passed, 3 skipped in 13.93s` |
| `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:cacheprovider -p no:xonsh` | `1411 passed in 698.61s` (1407 + 4 new) |
| `.venv/bin/ruff check . && .venv/bin/ruff format --check .` | `All checks passed!` / `168 files already formatted` |
| the plan's mypy command | `Success: no issues found in 39 source files` |

## Departures

- **`stretch_limit` instead of a `stretch_ready` check.** It is the "reuse one pass" option: when final, it decides and measures in the same pass, with no second slicing or hashing. When provisional, it stops at the first unsolved window and measures the previews.
- **Extras beyond the findings.** The `_job_for` recency touch, and dropping a stale non-final stretch at an empty rest. Both close loops the 2b re-arm could otherwise run, explained above.
