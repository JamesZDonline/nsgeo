# Task 4 report: Whole site with minimum curvature

**Status:** DONE_WITH_CONCERNS (minor; listed at the end)

**Commit:** `e203151` feat(site): minimum curvature in Whole site — kriging preview and background refine (pushed to `origin nsgeo-slice-interpolation-b`).

## What I implemented

### Shared helper: `nsgeo_qgis/ui/refine_flow.py` (new)

Copying Task 3's state machine into `site_scope.py` would have duplicated `_refine_status`, the rest's dedupe/start/redraw block, `_on_landed`'s redraw rule, the error text and `display_limit`'s provisional arming almost verbatim. So both scopes now own one `RefineFlow` each, on the dock's one `Refiner`. It holds:
- the scope's rest timer (`REFINE_REST_MS`), `provisional`, the running list's `done`/`total`, and the scope's shared stretch `(key, limit, final)`;
- `status(normal)`: REFINING_STATUS / PREVIEW_STATUS / normal;
- `previewed(awaited)`, `finished(stop=)`, `stop() -> bool`: the draw rules;
- `rested(current, stretch, on_landed, on_error) -> redraw`: dedupe by `(engine, key)`, start, or (nothing queued) drop a provisional stretch;
- `landed(job) -> redraw`, `failed(message) -> text`;
- `stretch_limit(key, measure)`, `stretch_final(key)` (Ruling R11).

What each scope queues at a rest, how it redraws and where its status goes stay in the scope. Solves are told apart by `(engine, key)`, never the key alone: two site grids can hold equal values (`site3_factory(same_data=True)` does exactly that).

### `slices_engine.py`
- `PendingSolve.engine` (read-only property): the engine a job lands in.
- `SliceEngine.is_solved(values, coverage, finish, *, key=None)`: whether `finish` would be a cache hit; builds and solves nothing.
- `SliceEngine.window_solve(window, finish)`: `pending_solve` for the engine's own window, sliced privately (no copy). `stretch_solves` now uses it.

### `site_engine.py`
- `SiteSlice` gains `previewed: dict[str, PreviewedGrid]` and `provisional: bool = False` (still the last field). `PreviewedGrid(engine, window, values, coverage, key)` is the tick's binned slice and key for a previewed grid.
- `_shown` takes a `draw` strategy instead of `finish`: `_draw_full`, `_draw_preview`, `_draw_live` (a tick: hash once, `finish_is_slow` → `preview` and record, else `finish(key=)`), `_draw_solved` (cache only; raises `_NotSolved`). Factors and composition are unchanged, so a preview is normalised exactly as the full result.
- `slice_at(..., preview=False)`: `preview=True` uses `_draw_live`.
- `pending_solves(top, thickness, finish, *, drawn=None)`: one job per ready grid with an unsolved slice, in `ready_grids` order. With `drawn` (the tick on screen), a previewed grid's job reuses that tick's slice and key (same engine and grid window only), so the rest neither re-slices nor re-hashes.
- `shared_limit(..., preview=False)`, `stretch_limit(...) -> (value, final)` and `stretch_solves(thickness_ns, finish)` all walk `_limit_windows_ns`: the SITE axis's `limit_windows`, each mapped onto every grid by `window_on` (Ruling R3). `stretch_limit` mirrors `SliceEngine.stretch_limit`: one pass, hash once per grid window, final = `shared_limit` over the cached solves, else `shared_limit(preview=True)`.

### `ui/site_scope.py`
- `SiteScope.refine` (a `RefineFlow`), the `provisional` property, `drawn_at = (top_ns, thickness_ns)` of the last tick (the rest solves exactly that window, never one re-derived from the spins), `status_text()`, `stretch_key(z)`.
- Tick (`refresh_slice`): `slice_at(..., preview=method == "min_curvature")`; `refine.previewed(...)` with the tick's `(engine, key)` pairs when provisional, else `refine.finished(stop=not curvature)`. Early-return and `except` branches stop the flow.
- `_on_rest` / `_on_landed` / `_on_refine_error`: Task 3's flow with `pending_solves(..., drawn=self.slice)`, the site's rest, `dock.refiner` and `schedule_refresh()`. Each guards its body (`# noqa: BLE001`) and reports through `dock.error` or `_log`.
- `display_limit`: `limit_cache` replaced by `refine.stretch_limit(stretch_key(z), lambda: engine.stretch_limit(...))`, so the provisional stretch is carried exactly as This grid carries it.
- `leave()` and `dispose()` stop the flow: the site's list is cancelled and its rest stopped when This grid comes back.

### `ui/slices_dock.py`
- This grid's `provisional`, `_rest`, `_refine_done/_total` and `_shared_limit_cache` move into `self._grid_refine` (`RefineFlow`). `provisional` stays as a read-only property. `_stretch_key(window, finish)` carries the old cache field's explanation. `_refine_slice` and `_refine_key` stay in the dock.
- `_on_rest` skips `stretch_solves` when the stored stretch is final for the current key (**Ruling R11**).
- `set_scope("site")` calls `_end_refine()`: **entering Whole site cancels This grid's list and stops its rest.**

## Tests and results

| Tier | Command | Result |
|---|---|---|
| core + pure | `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider` | **990 passed, 3 skipped** in 13.87 s (unchanged baseline) |
| QGIS, full | `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:cacheprovider -p no:xonsh` | **1426 passed** in 726.20 s (baseline 1411 + 15 new) |
| lint | `.venv/bin/ruff check . && .venv/bin/ruff format --check .` | All checks passed! / 169 files already formatted |
| types | the plan's mypy command | Success: no issues found in 39 source files |

- The five touched QGIS files together (site scope, dock, slices engine, refine, site engine): 347 passed in 229 s.
- **Flakiness:** the 33 refine-related tests across the three files, run 3 times: 33 passed each time (48.8 s, 50.1 s, 49.0 s).

**New tests (15)**
- `test_plugin_site_engine.py` (3):
  - `test_site_gains_commute_with_every_method[min_curvature]`, with `rtol=1e-4, atol=1e-4 * nanmax|after|`;
  - `test_a_live_site_tick_previews_each_slow_grid_until_its_solve_lands`: preview per slow grid, normalised and composed like the full result; `pending_solves` order and keys, with and without `drawn`; final once landed. Not in the brief;
  - `test_the_site_stretch_solves_cover_what_its_shared_limit_measures` (R3): C's axis ends early, so a grid's own windows differ from the site's mapped ones; `stretch_limit` is `(shared_limit(preview=True), False)`, then `(shared_limit, True)`. Not in the brief.
- `test_plugin_site_scope.py` (11):
  - the brief's five: `test_a_slow_site_tick_previews_then_refines`, `test_a_quick_site_tick_draws_minimum_curvature_at_once`, `test_a_site_refine_for_a_window_left_behind_never_draws`, `test_the_site_stretch_with_minimum_curvature_uses_twelve_windows`, `test_a_site_with_minimum_curvature_exports_and_reopens`;
  - R11 (site): `test_a_final_site_stretch_queues_no_stretch_solves_at_rest`;
  - scope switch: `test_entering_the_site_cancels_this_grids_refine`, `test_leaving_the_site_cancels_its_refine`;
  - another method: `test_a_site_tick_by_another_method_stops_the_refine`;
  - extras: `test_a_grid_landing_redraws_without_stopping_the_others` and `test_a_site_tick_hashes_each_grids_slice_once`.
- `test_plugin_slices_dock.py` (1): R11 (This grid): `test_a_final_stretch_queues_no_stretch_solves_at_rest`.
- **Helpers:** `_wait_for_refine` is copied into the site file (R4). It also waits on the site's tick and Interpolation pause, since the site redraws through a coalesced timer.
- **Task 3 test edits**, which follow from moving the state into `RefineFlow`:
  - `dock._rest` became `dock._grid_refine.rest`, and `dock._shared_limit_cache` became `dock._grid_refine.stretch`;
  - `_Looping` gains `engine = None`, because jobs are told apart by `(engine, key)`.

## TDD evidence

**RED**
- **Engine.** The QGIS command on `test_plugin_site_engine.py` gave `2 failed, 46 passed`. Both failures were expected:
  - `TypeError: SiteEngine.slice_at() got an unexpected keyword argument 'preview'`;
  - `AttributeError: 'SiteEngine' object has no attribute 'stretch_solves'`.
  - The `min_curvature` gains-commute case already passed. That is expected: `SliceEngine` is linear in the data, so this one is a coverage pin.
- **Scope.** The QGIS command, `-k` on the 11 new tests, gave `11 failed`:
  - most with `'SiteScope' object has no attribute 'refine'` / `'provisional'`, or `SiteEngine ... has no attribute 'pending_solves'`;
  - `test_entering_the_site_cancels_this_grids_refine` failed on the real bug: `assert not True` where `True = dock.refiner.busy`. Entering Whole site left This grid's list running.
- **Dock.** `-k` on the new R11 test and two renamed tests: `4 failed`, `'SlicesDock' object has no attribute '_grid_refine'`.

**GREEN**
- Engine file: 48 passed. New scope tests: 11 passed. Dock file: 129 passed.
- The first GREEN run of the dock R11 test failed on my own test: slider 20 is one of the twelve stretch windows, already solved, so no preview was drawn. Both R11 tests now pick a window off the stretch programmatically.

**Mutation checks.** Run on a scratch copy of `packages/` in the session scratchpad, never this worktree, with `PYTHONDONTWRITEBYTECODE=1` and `__pycache__` wiped. All 11 mutants were killed:

| Mutant | Killed by |
|---|---|
| a preview always cancels (keep rule off) | `landing_redraws_without_stopping` |
| This grid's rest ignores R11 | dock `final_stretch_queues` |
| the site's rest ignores R11 | `final_site_stretch_queues` |
| no cancel when entering the site | `entering_the_site_cancels` |
| no cancel when leaving the site | `leaving_the_site_cancels` |
| `pending_solves` ignores `drawn` (re-slices and re-hashes) | `hashes_each_grids_slice_once` |
| a non-mc site tick keeps the list | `another_method_stops_the_refine` |
| site `stretch_solves` uses each grid's own `limit_windows` (R3) | `stretch_solves_cover` (see note) |
| the site tick never previews | `slow_site_tick_previews_then_refines` |
| a landed solve never redraws | `landing_redraws_without_stopping` |
| a preview never cancels | `site_refine_for_a_window_left_behind` |

- **The R3 mutant first SURVIVED.** In `site3`, every grid's axis equals the site axis, so the two window sets coincide. The test now uses `site3_factory(samples={"C": 128})` and asserts the two sets differ for C. After that it was killed.

## Files changed
- `packages/nsgeo-qgis/nsgeo_qgis/ui/refine_flow.py` (new)
- `packages/nsgeo-qgis/nsgeo_qgis/site_engine.py`
- `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`
- `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py`
- `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_site_engine.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py`
- `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`

## Departures from the brief, and why

1. **A shared `RefineFlow` module** (`ui/refine_flow.py`) instead of a second copy of Task 3's state machine. Task 3's dock code moved into it, so This grid was refactored too. Its behaviour is unchanged apart from items 2 and 3 below; all of Task 3's tests pass.
2. **The keep rule, in both scopes.**
   - **What it is.** A preview whose awaited `(engine, key)` solves are all still at the head of the running list leaves that list running, and does not restart the rest. Any other preview cancels and restarts as before.
   - **Why the site needs it.** A tick previews up to N grids, and the brief redraws on each landing. Without the rule, the redraw after grid A lands still previews B and C. It would cancel B's solve in progress and start the rest over at every landing (pinned by `test_a_grid_landing_redraws_without_stopping_the_others`).
   - **What it changes in This grid.** A redraw of the same still-solving slice no longer cancels its solve. Palette, stretch-combo and session-signal redraws all call `refresh_slice`.
   - **What it leaves alone.** Moving to a queued stretch window still cancels: only the head (the slice's own solves) counts. Plan call 5 says only "a preview draw (a new slow window)" cancels, so the rule matches the plan.
3. **`RefineFlow._arm` re-arms a provisional stretch only when no rest is pending**, for a fresh measurement too. Task 3's fresh-measurement branch restarted an active rest. This also settles the deferred Task 3 minor about the `display_limit` docstring.
4. **API beyond the brief's list:**
   - `SiteSlice.previewed` (placed before `provisional`, which stays last) and `PreviewedGrid`;
   - `pending_solves(..., drawn=)`;
   - `SiteEngine.stretch_limit` (Ruling R3 asked for it);
   - `SliceEngine.is_solved` and `window_solve`;
   - `PendingSolve.engine`;
   - `SiteScope.drawn_at`, `status_text`, `stretch_key`.

   `drawn=` exists for "hash once per tick per grid": without it, every rest would slice and hash each grid again.
5. **`test_the_site_stretch_with_minimum_curvature_uses_twelve_windows`** sits in the scope file, because it checks the scope's limit. It counts `SliceEngine.finish` per engine during `site.shared_limit` (each count is between 1 and 12).

## Self-review findings

- **Slots.** Every new slot body is guarded with `except Exception as exc:  # noqa: BLE001 -- <signal>` and reports through `dock.error` or `_log`: the site's `_on_rest` (QTimer), `_on_landed` and `_on_refine_error` (refine poll).
- **Two grids with equal values.** Dedupe and the redraw rule use `(engine, key)`, so they can't collide.
- **The rest's window.** It solves exactly the tick's `(top, thickness)` (`drawn_at`). Re-deriving the window from the spins could clamp differently at the end of the axis, so the jobs would never match the preview's keys, and rest and redraw would loop.
- **Reused slices are safe.** `pending_solves(drawn=)` reuses a held slice only for the same engine object and grid window. Key and values always travel together, so a reused pair can't poison the cache. At worst a race solves stale values, and the next tick corrects it.
- **Cancel order differs between the scopes.** The site decides keep-or-cancel only after `slice_at`, because the pairs come from the tick, so the worker runs on during one tick's computation. This grid still cancels before it computes the preview.
- **Memory.** `SiteSlice.previewed` holds each previewed grid's binned values and coverage until the next tick: the same as This grid's `_refine_slice`.
- **Exports.** `export_site` still calls `slice_at` without `preview`, so every band is the full solve (pinned by the export test, whose first two bands equal `slice_at`).

## Concerns (minor)

1. **This grid's behaviour changed slightly** through the keep rule (departure 2). I believe it is better and matches plan call 5, but it goes beyond the brief, and a reviewer should confirm it.
2. **No progressive drawing when solves finish together.** When several grids' solves land in one 20 ms poll, their redraws coalesce into one tick, so progress isn't drawn grid by grid. That is fine, but nothing pins it.
3. **`site_scope.display_limit`** reads `gains()`, the method and the finish both for `stretch_key` and for the measurement: two cheap session reads per draw.

---

# Fix round 1: Important 1 and Ruling R12 (three minors)

**Commit:** `ac4aab9` fix(slices): a kept refine list must still hold its plans; cancel before a site rebuild. Pushed; the first push attempt failed on a transient DNS error, and the retry succeeded.

## What changed

**Important 1: a kept list must still hold its plans.**
- `RefineFlow.previewed` keeps the running list only when all of these hold:
  - the refiner is busy;
  - the preview waits for exactly the list's head (`waits == set(head)`, no longer `<=`), so a grid that left the site cancels too;
  - every head job is still on the plan its engine holds (`job.engine.holds(job.plan)`).
- The head is now a dict, id → job, so those plans can be checked.
- New public `SliceEngine.holds(plan)`, which `_land` now uses too, and `PendingSolve.plan`.
- **I checked the plan apart from the id**, not as `(engine, plan, key)`. An id holding the plan would be kept in `_awaited` past the next rebuild, keeping the dropped plan alive: the very thing the drop-first rule exists to prevent. The head's jobs hold their plans only while the list runs, and the refiner holds them then anyway.

**R12 minor 2: cancel before building.** New `RefineFlow.before_draw(rebuilds=)` cancels the running list before any draw that will build weights or a plan.
- **Whole site:** `refresh_slice` calls `before_draw(rebuilds=not engine.weights_cached(finish))` before `slice_at`. A coverage tick builds nothing, so it skips this.
- **This grid:** `_finished` does the same with the `weights_cached` it already computed for the wait cursor.
- **Why both checks are needed.** In This grid the keep decision comes *before* the preview builds the new plan, while the old one is still held. So the holds check alone could not catch a finish edit there; `before_draw` does. The site decides keep-or-cancel only after `slice_at`, because which grids it previews is known only then. Whether it rebuilds is known before, so the cancel is not delayed.
- **Side effect in This grid:** a change to another method that builds new weights now also cancels before the build, rather than after.

**R12 minor 1: skip grids drawn in full.** With `drawn`, `pending_solves` now skips any grid present in `drawn.windows` at the same grid window but not in `drawn.previewed`. That draw solved it, or found it solved, so it is neither sliced nor hashed.

**R12 minor 3: This grid's keep rule is pinned directly.** See the tests below.

## New tests (11 cases)
- `test_plugin_refine_flow.py` (new; fake refiner, engines and jobs; 7 cases):
  - `test_a_preview_waiting_for_exactly_the_head_keeps_the_list`
  - `test_any_other_preview_cancels_the_list_and_restarts_the_rest`, over 4 cases: another window / a grid left / a plan dropped / a solve landed elsewhere
  - `test_a_draw_that_rebuilds_cancels_the_list_first`
  - `test_a_rest_queues_each_solve_once_telling_grids_apart_by_engine`
- This grid: `test_a_redraw_keeps_its_own_solve_but_a_new_plan_cancels_it`. With the head solve gated:
  - a palette redraw keeps it (busy, no rest restarted);
  - a max-distance edit cancels it (`not refiner.busy`, rest active);
  - the refiner was idle at every `plan_fill` call;
  - after that the slice settles final, with 2 starts.
- Whole site:
  - `test_a_max_distance_edit_cancels_the_site_list_before_rebuilding`: the same checks, including idle at every `plan_fill`, which pins the cancel before the build;
  - `test_a_grid_leaving_the_site_cancels_the_list`;
  - `test_a_site_tick_hashes_each_grids_slice_once` is now parametrised `quick=[0, 1]`. The `1` case is a mixed tick (first grid fast, others previewed), and it also asserts that `SliceEngine.window_solve` is never called at the rest.

## TDD evidence

**RED.** The new tests against e203151's five source files, in a scratch copy under the session scratchpad (`red5/`; the worktree was untouched). The QGIS command on the flow file and the four named tests gave **8 failed, 4 passed**:
- the flow file's `[a grid left]`, `[a plan dropped]` and `[a solve landed elsewhere]`: `assert not True` (busy);
- `test_a_draw_that_rebuilds_cancels_the_list_first`: `AttributeError: 'RefineFlow' object has no attribute 'before_draw'`;
- This grid: `AssertionError: a solve on the dropped plan ran on`;
- site max distance: `AssertionError: a list for the dropped plans ran on`;
- site grid leaving: `AssertionError: the list for a grid that left ran on`;
- `hashes_each_grids_slice_once[1]`: `assert 'rest' not in ['tick', 'tick', 'tick', 'rest', ...]`.

The 4 that passed pin behaviour that did not change: keep for an exact head, cancel for another window, dedupe, and the all-previewed hash case.

**GREEN.** The same selection in the worktree: `12 passed in 12.51s`.

**The reviewer's experiments**, re-run on the fix (`scratchpad/review-t4/`):

| Scope | After the edit | Solves queued | Lands |
|---|---|---|---|
| This grid | `busy False rest active True` | 5 | 6 True, 0 False |
| Whole site | `busy False rest active True` | 39 | 39 True, 0 False |

Each still counts one "stale run": the gated head job itself, which was already blocked in `gate.wait` when it was cancelled. It stops at once on release and lands nothing.

**Mutants** (scratch copy `mut5/`). All 6 were killed:

| Mutant | Result |
|---|---|
| `==` → `<=` | 2 failed (flow: a grid left, a solve landed elsewhere) |
| holds check removed | 1 failed (flow: a plan dropped) |
| `before_draw` a no-op | 3 failed |
| This grid without `before_draw` | 1 failed |
| site without `before_draw` (holds still cancels after the build) | 1 failed: busy during `plan_fill` |
| no skip for full-drawn grids | 1 failed (`hashes[1]`) |

- **Note:** in the site's grid-leaving test, the holds check alone also cancels, because the departed engine is disposed and holds nothing. The `==` rule is pinned by the flow unit tests. It matters on its own for a retiring engine, which still holds its plan.

## Commands and outputs

| Command | Output |
|---|---|
| `... pytest test_plugin_site_scope.py test_plugin_slices_dock.py` (QGIS command), run 1 | `231 passed in 204.29s` |
| the same, run 2 | `231 passed in 204.29s` |
| `... pytest test_plugin_site_engine.py test_plugin_slices_engine.py test_plugin_refine_flow.py test_plugin_refine.py` | `127 passed in 26.26s` |
| `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:cacheprovider -p no:xonsh` | `1437 passed in 706.55s` (1426 + 11) |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider` | `990 passed, 3 skipped in 14.81s` |
| `.venv/bin/ruff check . && .venv/bin/ruff format --check .` | `All checks passed!` / `170 files already formatted` |
| the plan's mypy command | `Success: no issues found in 39 source files` |

## Remaining notes
- **"Solved meanwhile" now cancels.** With `==`, a redraw where one head grid's slice was solved by another path (an export) while its job was still queued cancels the list and restarts the rest, rather than letting the duplicate run. The flow test pins this. It is rare, and costs one rest plus the solve in progress.

---

# Fix round 2: N1, a grid with no window at the depth shown

**Commit:** `85b08cf` fix(site): a grid with no window at this depth is not a rebuild. Pushed.

## What changed

**`SiteEngine.weights_cached(finish, *, at=None)`.**
- With `at = (top_ns, thickness_ns)` it counts only the ready grids with a window there (`_grid_window`). A grid whose axis misses that window is not finished there, and never builds weights for it.
- Without `at` it counts every ready grid that has an axis. Before, it counted every ready grid, so a grid with no axis would read as uncached forever.

**`SiteScope.refresh_slice`** computes `builds` once, from the tick's own window:

```python
builds = not coverage and not self.engine.weights_cached(finish, at=(top, thickness * z.dz_ns))
```

- That one value drives both `RefineFlow.before_draw(rebuilds=builds)` and the tick's wait cursor (`busy_cursor()` only when `builds`).
- `_run_tick` no longer decides the cursor, because only the tick knows which grids it finishes.

**`SiteScope.display_limit`.** A fresh stretch measurement finishes every grid at up to twelve windows, so it can build for a grid the tick shown missed. It shows the cursor when `weights_cached(finish)` (every grid) is False. That keeps the wait cursor around builds the old whole-tick cursor covered.

**Optional item (release a dropped plan when `run()` ends): not taken.**
- `PendingSolve.land()` needs `_plan`: it calls `engine._land(self._plan, ...)`, which checks `holds(plan)`.
- `RefineFlow.previewed` reads `job.plan` for head jobs that may have finished but not yet drained.
- `_values` is already released at the end of `run()`, in its `finally`.

## Tests (3 cases)
- **Engine:** `test_a_grid_with_no_window_at_a_tick_is_not_a_rebuild_there`. With C ending near 16.4 ns:
  - `weights_cached(at=deep)` is True;
  - `at=shallow` is False until a shallow tick has run;
  - plain `weights_cached` is False while C has built nothing.
- **Scope:** the landing test is factored into `_landing_keeps_the_others(dock, monkeypatch, at)` and now also asserts that no wait cursor shows. It runs on:
  - `site3` (the existing test, unchanged in what it pins);
  - the new `test_a_grid_missing_the_depth_does_not_stop_the_others_landing`: `site3_factory(samples={"C": 128})`, minimum curvature chosen at 60 ns, then 70 ns, which C misses. It asserts `refiner.busy` after the first landing, `len(starts) == 1`, and no cursor.
- `_site_minimum_curvature` gains `at=` (default 10).

## TDD evidence
- **RED**, with the QGIS command on the three tests before the fix: **2 failed, 1 passed** (the `site3` variant passes, as before).
  - engine: `TypeError: SiteEngine.weights_cached() got an unexpected keyword argument 'at'`;
  - scope: `AssertionError: the first grid's redraw stopped the others' solves` / `assert False` where `False = refiner.busy`. This is N1 itself.
- **GREEN:** `3 passed in 6.73s`.
- **Reviewer's experiment** (`review-t4/test_short_grid_experiment.py`):

  | | busy after the first landing | rest active | rebuild flags | starts |
  |---|---|---|---|---|
  | before the fix | False | True | `[True, True, True]` | 2 |
  | after the fix | True | False | `[False, False, False]` | 1 |

- **Mutants** (scratch copy `mut6/`), both killed:
  - the tick ignores the window: 1 failed;
  - `weights_cached` ignores `at`: 2 failed.

## Commands and outputs

| Command | Output |
|---|---|
| QGIS command on `test_plugin_site_scope.py test_plugin_site_engine.py`, run 1 | `151 passed in 189.83s` |
| the same, run 2 | `151 passed in 188.95s` |
| QGIS command on `test_plugin_refine_flow.py test_plugin_slices_dock.py` | `137 passed in 45.08s` |
| `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:cacheprovider -p no:xonsh` | `1439 passed in 738.57s` (1437 + 2) |
| `.venv/bin/ruff check . && .venv/bin/ruff format --check .` | `All checks passed!` / `170 files already formatted` |
| the plan's mypy command | `Success: no issues found in 39 source files` |
