# Task 3 report: SiteEngine, one engine per grid, prepared one at a time

Status: DONE_WITH_CONCERNS. The concerns are below. None blocks Task 4; two are inputs for the controller's Task 5 ruling.

Commits, pushed to `origin/nsgeo-m12` (a3304aa..886962d, first try):
- `4bbef84` feat(qgis): site source, stretch windows and the engine hooks the site needs
- `43f9787` feat(qgis): SiteEngine -- one engine per grid, prepared one at a time
- `886962d` perf(qgis): bench_site -- time the site view on a ten-grid synthetic site

## Implemented

**`slices_plan.py`** (Qt-free, pure-tier tested):
- `SiteSource(transform, grids)`. It raises `ValueError` naming the grid when a choice's transform differs from the site's, or when a grid id repeats.
- `radius_cells_for(spacing_m, radius_spacings, cell)` returns `max(0, int(round(...)))`, the same rounding as the dock's `radius_cells`. It raises on `cell <= 0`.
- `SITE_LIMIT_WINDOWS = 12` and `limit_windows(z, thickness_levels, max_windows=12)`. These are `plan_windows(z, t, t)` plus `display.shared_limit`'s thinner tail. Beyond the cap, the picks are `round(i·(n-1)/(m-1))`, which always include the first and the last window. `max_windows < 2` raises.

**`slices_engine.py`** (M11 behaviour unchanged when the hook is None; M11's 28 tests pass untouched):
- `cancel_preparation()` is public and wraps `_cancel_in_flight()`. Its docstring gives the Ruling 1 reason it exists. It also covers the bounded-wait case: if the wait gives up, `is_running` stays True until the task really ends.
- R-P2: `__init__(..., parent=None, *, on_grid_moved=None)`, kept as a public attribute and nulled by `dispose()`. When it is set, `_on_grids_changed`'s fingerprint-changed branch calls `_hand_over_the_move`. That calls `clear()`, then the hook. Both halves are guarded and report through `_report`; neither raises. When it is None, the existing `set_source(self._choice)` path runs as before.

**`site_engine.py`**: `SiteSlice` and `SiteEngine` with the brief's whole interface.
- `set_source` diffs against the current source:
  - unchanged grids keep their lines;
  - changed grids are queued (one already preparing is cancelled and confirmed first);
  - removed grids' engines are disposed;
  - a grid with no line keys is `"no lines"`, gets no engine, and is never dispatched.
- `_dispatch_next` starts the queue head only when no own engine and no `exclusive_with` peer `is_running`. Otherwise it restarts a 50 ms retry timer. It never blocks.
  - It is reentrancy-safe: a synchronous `on_prepared` from inside the engine's own `set_source` (no jobs, or `addTask` refused) sets `_dispatch_again` rather than recursing.
  - An engine whose `set_source` raises (a preset carrying a transform) is marked `failed: ...`, and the queue moves on.
- Per tick: `window_on` → `engine.slice_at` → `normalise(method, binned, seams, manual)` → `a·fill(v, cov, radius_cells_for(spacing_g, …)) + b` → `compose`. Coverage mode shows counts with 0 as NaN and skips normalisation.
- Caches are dropped on any resolution change, grid edit or source change:
  - gathers: once per grid per lattice, computed only over the frame's extent plus one pixel, with pixel centres transformed into the frame's CRS when it differs;
  - seams: once per geometry, from a one-level slice's coverage of every ready grid.
- `set_resolution` re-derives:
  - `site_axis` over the ready grids' `prepared_z_bounds`;
  - for each grid, `grid_axis` and then `Resolution(cell, dz, gz.t0_ns, gz.t_end_ns)`. **R-P3:** a None or one-level `gz` gives no resolution.
  - the lattice: extents transformed to the site CRS (`grids[0].crs`) and `lattice_pixel` over the bearings. Past `MAX_FRAME_CELLS` it raises `ValueError` naming `{n:,} pixels`.
  - An engine whose frame and z already equal the wanted ones is not given `set_resolution` again. Every grid becoming ready re-derives the geometry, and re-setting an unchanged resolution would throw away plans and cubes (trap 3 still holds: any change goes through).
- Also: `shared_limit` (Ruling 4 windows, normalised and filled, after manual gain), `cancel`, `clear`, `dispose`, `status_text`, `wait_until_idle`, `grid_state`, `engine_for`, `ready_grids`, `site_z`, `lattice`, `is_running`.

### Slot order, and how R-P2 is driven
`SiteEngine` connects `grids_changed` before any engine exists, so its `_on_grids_changed` runs first. That handler reads no engine state. It drops the caches and handles grids that no longer exist in the session: it disposes their engines, drops them from the source, rebuilds the geometry (the remaining engines are unaffected by a removal) and calls `on_changed`.

A moved grid is handled only in `_on_grid_moved`. The engine calls it after its own `clear()`, so the state read there is current. It marks the grid `queued`, re-queues it in source order only while active, rebuilds the geometry, notifies and dispatches. After `cancel()` the grid stays `queued` and re-prepares at the next `set_source`.

One subtlety. When the moved grid is the one preparing, its cancelled callback arrives from inside the engine's `clear()`, before `_on_grid_moved`. `_on_engine_prepared` recognises this because the grid's current registration (M11's own `_grid_fingerprint`) differs from the one captured at dispatch. It ignores the callback rather than marking the grid failed. Every deliberate cancel (`cancel`, a changed or dropped grid, `clear`) clears `_preparing` before cancelling, so those callbacks are ignored too.

### Choices where the brief left one, or where I departed from it
1. **The other-CRS test uses EPSG:32615 (the next UTM zone), not EPSG:26916.** I measured QGIS's 26916→32616 operation as a null datum shift: 1.6e-8 m at the fixture's coordinates and 1e-4 m at realistic ones. Mutant 4 (gathers not transformed) would therefore survive with 26916. B's origin is the 32615 image of (506, 700), so it lies between A and C on the ground. The test's docstring records why.
2. **`status_text` memory is what is held, not `estimate.total_bytes`.** That means lines, plus a cube only where an engine is resident, as M11's `format_status` counts it. `total_bytes` always adds a hypothetical cube. The brief's own example agrees: 62 real lines take about 78 MB, consistent with "74 MB" for lines alone.
3. **`SiteSlice` is `@dataclass(frozen=True, eq=False)`**, following Ruling T1-a for `Seam`: a generated `__eq__` over an ndarray raises.
4. **One restartable `QTimer` instead of `QTimer.singleShot(50, …)`.** Same behaviour, and the timers do not pile up while a peer prepares.
5. **A failed grid with an unchanged choice stays failed on `set_source`.** It is retried when its choice changes or the grid moves. A caller that re-sends the same source from `on_changed` would otherwise re-run a failing preparation forever.
6. **`shared_limit` is measured over each present grid's grid-local filled, normalised array**, not over the composed lattice. That is the same population M11 measures, it is cheaper, and it does not depend on the lattice.
7. **Coverage mode's `factors` is `(1.0, 0.0)`** for each present grid: the identity, which is literally what was applied.
8. **`lattice_pixel` receives each frame's bearing in the site CRS.** A grid declared in another zone is turned by the difference in meridian convergence, so Ruling 2 treats it as rotated (`cell/2`).
9. **`clear()` does not call `cancel_preparation` before `dispose()`.** On `site_closed`, every confirm wait runs to its full 250 ms (see concern 2), and the extra wait added a quarter of a second and one more spurious warning. Measured: 787 ms and 3 warnings before, 525 ms and 2 after. The 2 that remain come from inside M11's `dispose()`.
10. **`site_closed` connects to a guarded `_on_site_closed`**, which calls `clear()`.

## Verification (final code, `886962d`)
- core + pure: **602 passed, 2 skipped** (598 + 4 new pure tests). The 2 skips are the known `test_schema.py` ones.
- qgis tier (`-p no:xonsh`): **771 passed in 201 s**. That is 739, plus 24 site-engine tests, 4 new SliceEngine tests, and the 4 new pure tests that this tier also collects.
- `ruff check .`: all passed. `ruff format --check .`: 128 files already formatted. mypy (including `slices_plan.py`): no issues in 34 files.
- **The 20-run loop**, over the five concurrency tests (`never_prepare_at_once`, `outlives_its_cancel_wait`, `re_prepares_through_the_queue`, `moved_while_it_prepares`, `closing_the_site_mid_preparation`): **20/20 passed, 0 failures**, each run "5 passed" in 7.9–8.3 s. I ran it twice, once before and once after the last code edit; both runs were 20/20.

## TDD evidence
- Pure tier: 4 new tests failed with `ImportError` (no `SiteSource`, `radius_cells_for` or `limit_windows`). After implementing: 18 passed.
- SliceEngine: 4 new tests failed for the right reasons:
  - `assert [] == [1]`: the hook was never called;
  - `errors == []`: there was no "boom" report;
  - `TypeError: unexpected keyword argument 'on_grid_moved'`;
  - `AttributeError`: no `cancel_preparation`.
  
  After implementing: 32 passed.
- SiteEngine: the file failed at collection with `ModuleNotFoundError: nsgeo_qgis.site_engine`. After implementing: 23 passed. Two test bugs were fixed on the way: the fixture's site folder must exist before `new_site`, and in the new moved-while-preparing test, `on_changed` was attached before the grid was in the source. Then 24 passed.

## Mutants
Run with `PYTHONDONTWRITEBYTECODE=1`, every `__pycache__` under the plugin deleted before each run, and the sources byte-compared afterwards to confirm they were restored. Final run on the committed code:

| # | Mutant | Result | Failing test(s) |
|---|---|---|---|
| 1 | `_dispatch_next` ignores `exclusive_with` | KILLED | `test_two_engines_never_prepare_at_once` |
| 2 | ignores its own engines | KILLED | `test_a_preparation_that_outlives_its_cancel_wait_holds_back_every_other` |
| 3 | `set_source` re-queues unchanged grids | KILLED | `test_changing_one_grids_preset_re_prepares_only_that_grid`, `test_dropping_a_grid_from_the_source_releases_it_and_keeps_the_rest` |
| 4 | gathers not transformed for another CRS | KILLED | `test_a_grid_in_another_crs_lands_where_its_coordinates_say` |
| 5 | factors applied before fill, `fill(a·v + b)` | **SURVIVED: equivalent mutant** | none (see below) |
| 6 | shared limit measured on unnormalised slices | KILLED | `test_the_shared_limit_follows_normalisation` |
| R-P2 | hook ignored, M11 self-dispatch (in `slices_engine.py`) | KILLED | `test_a_moved_grid_re_prepares_through_the_queue_never_alongside_another`, `test_a_grid_moved_while_it_prepares_is_re_queued_not_failed`, `test_moving_a_grid_rebuilds_the_lattice_and_seams` |
| x1 | seams kept across a geometry change | KILLED | `test_moving_a_grid_rebuilds_the_lattice_and_seams` |
| x2 | R-P3 one-level guard removed | KILLED | `test_a_grid_overlapping_the_site_by_one_level_is_absent_not_an_error` |
| x3 | a moved grid's cancelled callback counts as its result | KILLED | `test_a_grid_moved_while_it_prepares_is_re_queued_not_failed` |
| x4 | histogram shift dropped, `a·fill(v)` only | KILLED | `test_histogram_factors_apply_to_the_filled_slice_as_a_gain_and_a_shift` |
| e1 | (SliceEngine tests) hook ignored | KILLED | `test_with_a_grid_moved_hook_…`, `test_a_raising_grid_moved_hook_…` |
| e2 | `cancel_preparation` a no-op | KILLED | `test_cancel_preparation_stops_the_task_and_keeps_nothing_else_running` |
| e3 | hook called unguarded | KILLED | `test_a_raising_grid_moved_hook_is_reported_not_propagated` (failure plus the slot-exception conftest error) |
| p1–p6 | (pure) radius truncates; no tail; subset misses the last; subset is the first 12; mixed transforms accepted; repeated grid accepted | all KILLED | the four new pure tests |

**Mutant 5 cannot be killed: it is mathematically equivalent.** `fill` is a normalised weighted mean, `Σw(a·v+b)/Σw = a·Σwv/Σw + b`, with the same NaN mask either way, because the weights depend only on the counts. Measured on site3 with the histogram method (b = −0.08, −0.02, +0.12): `max |a·fill(v)+b − fill(a·v+b)| = 1.2e-7` on values up to 1.95, which is one float32 ulp. A synthetic check gave 4.8e-7 on values up to 7.8. The only way a test could tell the two apart is by float32 rounding, which would be a test of operation order rather than behaviour, so I did not write one.

The histogram test does pin the composition: x4 (`b` dropped) is killed. Whether the brief's mutant 5 still matters is the controller's call. My reading is that it doesn't, as long as fill stays a normalised mean.

## Benchmark (Step 6), verbatim
`QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python packages/nsgeo-qgis/scripts/bench_site.py` (final clean run, nothing else running):

```
10 grids per site, 0.5 m line spacing, 60 traces/m, 128 samples/trace (time_zero, dewow, gain_agc; transform none); cell 0.25 m, native dz, thickness 5 ns, radius 1.5 spacings; 20 windows per timing.

| site | lines | traces/line | lattice | engine mode | prepare site (s) | first tick (ms) | slice_at median / p90 (ms) | edge median / p90 (ms) | shared_limit (ms) | one-grid baseline median / p90 (ms) |
|---|---|---|---|---|---|---|---|---|---|---|
| 10 x 20 m | 400 | 1200 | 400 x 160 | streaming | 2.3 | 233 | 91.2 / 93.1 | 93.2 / 94.6 | 342 (4 windows at 5 ns); 572 (12 at 1.5 ns) | 9.2 / 9.8 |
| 10 x 50 m | 1000 | 3000 | 1000 x 400 | streaming | 16.1 | 1052 | 520.4 / 553.2 | 519.3 / 539.7 | 1849 (4 windows at 5 ns); 3015 (12 at 1.5 ns) | 46.1 / 46.7 |

10 x 20 m: 10 grids · 400 lines held in memory, 169 MB · slices redraw in 93 ms; site axis 88 levels; set_resolution 1 ms; one grid's tick is 8.6 ms binning + 0.5 ms fill (medians); lines written in 0 s; 0 errors
    with every cube resident (23 MB of cubes, built in 343 ms): slice_at median / p90 9.9 / 10.7 ms
10 x 50 m: 10 grids · 1000 lines held in memory, 1.1 GB · slices redraw in 528 ms; site axis 88 levels; set_resolution 1 ms; one grid's tick is 43.5 ms binning + 2.6 ms fill (medians); lines written in 8 s; 0 errors
    with every cube resident (142 MB of cubes, built in 2328 ms): slice_at median / p90 59.5 / 62.0 ms
```

An earlier clean run agreed: the 10 × 50 m median was 507.9 ms and the baseline 46.9 ms.

For the controller's rule: the 10 × 50 m median `slice_at` is **520.4 ms**; the one-grid baseline median is **46.1 ms**. I have not applied the rule.

Notes on the measurement:
- **128 samples per trace, to fit in memory.** At 512 samples the 10 × 50 m site would hold about 5.7 GB of prepared lines; this machine has about 3.5 GB free. Tick cost goes with traces and frame size, and traces are at the real 60 per metre.
- **The short axis has 88 levels**, so the stretch at 5 ns measures only 4 windows. I also timed it at 1.5 ns, which gives Ruling 4's full 12.
- **Binning dominates, not fill.** Spec 4.8 assumes the fill dominates. Here, binning is 43.5 of the 46.1 ms of one grid's tick; the fill is 2.6 ms.
- **`choose_residency` misjudges these grids.** It estimates 100 lines × 0.14 ms = 14 ms, which is under 16, so it streams. But 0.14 ms per line was measured on roughly 670-trace lines; a 3000-trace line streams in about 0.44 ms.
- **Resident cubes would be cheap.** They are 14 MB per 50 m grid, and with every cube resident the site tick drops to 59.5 ms. That points to residency as a candidate for Task 5's drag handling. I am recording it, not deciding it.

## Files changed
- `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`: SiteSource, radius_cells_for, SITE_LIMIT_WINDOWS, limit_windows.
- `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`: cancel_preparation, on_grid_moved, `_hand_over_the_move`.
- `packages/nsgeo-qgis/nsgeo_qgis/site_engine.py` (new, 908 lines including docstrings).
- `packages/nsgeo-qgis/scripts/bench_site.py` (new).
- `packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py`: 4 tests.
- `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py`: 4 tests, appended; M11's tests untouched.
- `packages/nsgeo-qgis/tests/qgis/conftest.py`: `Site3`, `site3_factory` (options `samples`, `scale`, `crs`, `same_data`) and `site3`, for Task 4.
- `packages/nsgeo-qgis/tests/qgis/test_plugin_site_engine.py` (new, 24 tests). These are the brief's 15, the R-P2 test, and 8 more: the cancel-wait timeout (mutant 2), moved while preparing, dropping a grid from the source, a failed grid with the rest continuing, R-P3 one level, the histogram composition (mutant 5 and x4), coverage mode, and the status line.

## Self-review
- No orphan signals: no `pyqtSignal` was added. Every slot and callback (`_dispatch_next`, `_on_engine_prepared`, `_on_engine_error`, `_on_grid_moved`, `_on_grids_changed`, `_on_site_closed`, `wait_until_idle.check`, SliceEngine's `_hand_over_the_move`) guards its body and reports. The slot-exception conftest is untouched and passes.
- `site_engine.py` is longer than the brief implies, mostly docstrings. The geometry helpers (CRS outline and bearing, the restricted gather) are what that size buys. It is a single cohesive class, so I did not split it.
- The tests run real behaviour: real QgsTasks, real synthetic DZT files, real transforms. They use only public SiteEngine API; the one exception is that the M11-pattern tests reuse `engine._pending`, which M11's tests already use.

## Concerns
1. **Mutant 5 is equivalent.** It survives by construction (see above). It needs a ruling, not a fix. *[Ruled T3-a: equivalent; no action.]*
2. *[Fixed in fix round 1, ruling T3-e.]* **M11 reports a spurious "did not stop in time" when the site closes mid-preparation (pre-existing).** `SliceEngine.finished()`'s site-mismatch branch returns without `_finish_preparation`, so `_cancel_in_flight`'s wait always runs its full 250 ms and then reports.
   - In this task: `SliceEngine.dispose()` does that twice, so closing the site while a site grid prepares stalls about 0.5 s and reports twice. M11's own dock engine does it once through `clear()`.
   - Not fixed here: it is M11 behaviour outside this task. The test for this path does not assert on errors, and its docstring says why.
3. *[CORRECTED in fix round 1: this concern understated the hole, and the next two bullets are wrong. Fixed under ruling T3-b.]* **A residual hole in trap 1 remains, inherited from M11.** M11's `clear()` (and so `dispose()`) forces `_running = False` even when its bounded wait gave up.
   - *(Wrong.)* "Only through R-P2's hook path..." It was also reachable through SiteEngine's own `_drop_engine`, which removed the engine and then disposed it. That covers dropping a preparing grid with `set_source`, switching a grid to "no lines", deleting a grid from the session, and `clear()` followed by a new `set_source`. The reviewer reproduced max_concurrent == 2.
   - *(Wrong.)* "`SiteEngine`'s own paths avoid it": only `cancel()` did.
   - A one-line SliceEngine fix exists: `is_running` returns `_running or bool(_pending)`. But if a task's `finished` ever failed to run, `is_running` would stay True forever, so I left it for a ruling.
   - The bench shows one 3000-trace line prepares in about 16 ms (16.1 s for 1000 lines), well under the 250 ms limit.
4. *[Fixed in fix round 1, ruling T3-d.]* **No per-grid progress.** Spec 4.2 wants "preparing n of m" in the list, but `grid_state` returns only `"preparing"`, as the brief specifies. Task 5 will need per-grid progress, for example by wiring each engine's `on_progress`.
5. **The site CRS follows `grids[0]` only as of the last geometry rebuild.** Removing grid 0, or changing its CRS, while it is not in the site source does not rebuild the lattice until the next rebuild. This only matters on mixed-CRS sites.
6. **The stretch pass is expensive at this size.** `shared_limit` at 12 windows costs about 3 s on 10 × 50 m streaming. Task 5 should cache it, as M11's dock caches by key.

---

# Fix round 1 (base 886962d)

Status: DONE_WITH_CONCERNS. The one new concern is a pre-existing M11 flake under load, below.

Commits, pushed to `origin/nsgeo-m12` (886962d..2bf7023, first try):
- `89f0ea5` fix(qgis): SliceEngine -- has_live_task, a prompt silent close, residency per trace
- `461588a` fix(qgis): SiteEngine -- gate on live tasks, retire dropped engines, per-grid progress
- `2bf7023` perf(qgis): bench_site -- count engine modes, label the cube build in the first tick

## What changed

**1. Ruling T3-b: the dispatch gate no longer loses sight of a live task.**
- `SliceEngine.has_live_task` returns `self._running or bool(self._pending)`. `_pending` holds a task until its `finished` has run, whatever its generation. `is_running` keeps M11's meaning.
- `SiteEngine._anything_live()` replaces `_anything_running()`. It reads `has_live_task` over own engines, retiring engines and `exclusive_with` peers.
- `_drop_engine` now:
  - calls `cancel_preparation()` while the engine is still in `_engines`, so a retry firing inside the cancel's nested wait still sees it;
  - re-checks that a reentrant call did not already release the engine;
  - removes it, then disposes it if its task is gone, or otherwise `_retire`s it.
- `_retire` swaps the engine's callbacks: `on_prepared` and `on_progress` become None, and `on_grid_moved` becomes a no-op. A no-op, not None, because None would restore M11's self-dispatch on a move. The engine joins `_retiring`, and a `_reaper` QTimer (50 ms) disposes it once `has_live_task` is false.
- `clear()` drops every engine through `_drop_engine`. `dispose()` also disposes retiring engines. `cancel()` uses `has_live_task`.
- `SiteEngine.has_live_task` (any own or retiring engine) is exposed for Task 5. `is_running` is now "preparing, or queued while active, or `has_live_task`".
- The module docstring and the earlier concern 3 are corrected.
- The R-P2 hook path is closed by the same gate. That path is M11's own `clear()` with a timed-out wait: `_pending` still holds the old task, so the moved grid waits for it. The unfixed code reproduced max = 2 there.

**2. Ruling T3-d: per-grid progress.**
- Each engine is built with `on_progress=functools.partial(self._on_engine_progress, grid_id)`.
- `grid_progress(grid_id)` returns (lines done, lines total) while the grid is `"preparing"`, otherwise None. It is set to `(0, len(line_keys))` at dispatch.
- `on_changed` fires when a grid starts (before its `set_source`, re-checking afterwards that the callback did not change the plan) and on each progress step. Progress for a grid that is not the one preparing is ignored. `grid_state` keeps the brief's values.

**3. Ruling T3-f.** `set_source` calls `on_changed` when the ready set changed or ANY grid state changed (dropped, "no lines", queued). One effect: `test_grids_prepare_in_order…` now filters out the empty ready tuples that the queue and start notifications add. Its claim about order and drawing as soon as ready is unchanged.

**4. Ruling T3-c: residency costed per trace.**
- `slices_plan` keeps `STREAM_MS_PER_LINE = 0.14` and adds `MEASURED_TRACES_PER_LINE = 630` and `STREAM_MS_PER_TRACE = STREAM_MS_PER_LINE / MEASURED_TRACES_PER_LINE` (2.2e-4 ms).
- The basis is M11 spec §7: "All figures: the ten real files cycled to the stated line count". Those files hold 606–666 traces, 630 on average; I counted them with `Line.open`.
- Cross-check: the rule predicts 0.67 ms for a 3000-trace line; the M12 bench measured 0.44 ms, so the estimate errs cautious.
- `choose_residency(estimate, n_traces, budget_bytes, always_resident)` keeps M11's rule and both budgets. `SliceEngine._choose_mode` passes `sum(line.data.shape[1] for line in self._lines)`. That is its only call site.
- **What M11's real ten lines now choose: streaming.** They hold 6301 traces, which costs 1.40 ms per tick, against a 16 ms budget. The same decision as before.

**5. Ruling T3-e: closing a site mid-preparation is prompt and silent.**
- In `finished`, the closed-site branch (reached with the generation still matching) now sets `_running = False` and calls a waiter-only wake.
- `wait_for_preparation` installs that wake (`self._wake_waiter`, chained to any outer waiter and restored afterwards). It ends the confirm wait without `on_prepared`. Nothing is applied and nothing is reported.
- I checked the alternative of waking through `_finish_preparation` and rejected it. The dock's `_on_prepared` clamps z, clears the stretch cache, refreshes labels, refills the palette combo and consumes `_pending_palette`, none of which belongs to a site that is gone. SiteEngine's handler would have ignored it (`_preparing` is already None), but the dock's would not. Mutant e2 below shows a test catches that variant.
- The M11 docstring paragraph about the silent branches is updated.

## Covering tests (new or changed)
- **Pure:**
  - the four residency tests now pass a trace count (24 / 200 × 630 traces), with the same intent;
  - new `test_streaming_is_costed_per_trace_so_long_lines_go_resident`: 100 × 3000 is resident, 100 × 670 streams, an over-budget cube streams;
  - new `test_the_ten_real_lines_still_stream` (real data, ran, not skipped).
- **SliceEngine:**
  - `test_closing_the_site_mid_preparation_stops_promptly_and_silently`: errors == [], close under `_CANCEL_TIMEOUT_MS`, no live task, `on_prepared` not called;
  - `test_has_live_task_outlasts_a_clear_whose_wait_gave_up`;
  - `test_residency_is_chosen_from_the_prepared_trace_count` (engine level: the per-trace rate is raised so 240 traces exceed a frame).
- **SiteEngine:**
  - new `test_a_dropped_grid_whose_preparation_outlives_its_cancel_wait_holds_back_every_other` (`_CANCEL_TIMEOUT_MS = 1`, load +0.15 s, `set_source(ABC)` then `set_source(BC)` after A's first read; max_concurrent == 1, B and C "ready", no live task at the end);
  - new `test_a_moved_grid_whose_preparation_outlives_its_cancel_wait_is_held_back`;
  - `test_a_preparation_that_outlives_its_cancel_wait_holds_back_every_other` extended with `has_live_task` assertions;
  - new `test_each_grid_reports_its_progress_while_it_prepares`;
  - new `test_dropping_a_grid_or_emptying_its_lines_is_announced_even_before_it_is_ready`;
  - `test_closing_the_site_mid_preparation_clears_without_overlap` now asserts errors == [] and close under `_CANCEL_TIMEOUT_MS`. This removes the test that dodged its own hazard.

RED before the fix:
- `has_live_task`, `grid_progress` and `STREAM_MS_PER_TRACE` did not exist;
- the move-timeout test failed with **max_concurrent = 2** (the real hole);
- the M11 close test reported "did not stop in time";
- the site close test reported it twice;
- the announcement test saw no `on_changed`.

## Commands and output (final code, 2bf7023)
- `./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q`: **604 passed, 2 skipped**.
- `QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh`: **780 passed in 318.96 s**. That is 771, plus 4 site-engine tests, 3 SliceEngine tests and 2 pure tests.
- The covering files (`test_plugin_site_engine.py` plus `test_plugin_slices_engine.py`): 63 passed.
- `ruff check .`: all passed. `ruff format --check .`: 128 files already formatted. mypy (including `slices_plan.py`): no issues in 34 files.
- **20-run loop** over the seven concurrency tests (`never_prepare_at_once`, both `outlives_its_cancel_wait`, `re_prepares_through_the_queue`, `moved_while_it_prepares`, `is_held_back`, `closing_the_site_mid_preparation`): **20/20 passed**, each run "7 passed" in 10.5–12.9 s.

## Mutants
Run with `PYTHONDONTWRITEBYTECODE=1`, `__pycache__` cleared before each run, sources byte-compared afterwards.

| Mutant | Result | Failing test(s) |
|---|---|---|
| b1 dispatch gate uses `is_running` | KILLED | `test_a_moved_grid_whose_preparation_outlives_its_cancel_wait_is_held_back` |
| b2 `_drop_engine` disposes straight away | KILLED | `test_a_dropped_grid_whose_preparation_outlives_its_cancel_wait_holds_back_every_other` |
| b3 `_drop_engine` cancels, then disposes even if live | KILLED | the dropped-grid test |
| d1 progress not wired | KILLED | `test_each_grid_reports_its_progress_while_it_prepares` |
| d2 no `on_changed` when a grid starts | KILLED | the progress test |
| f1 `on_changed` only when the ready set changes | KILLED | `test_dropping_a_grid_or_emptying_its_lines_is_announced_even_before_it_is_ready` |
| c1 per-trace rate from the wrong basis (÷3000) | KILLED | `test_a_large_site_is_promoted…`, `test_streaming_is_costed_per_trace…` |
| c2 engine passes its line count | KILLED | `test_residency_is_chosen_from_the_prepared_trace_count` |
| e1 closed-site edge silent again (M11) | KILLED | both close tests (M11 and site) |
| e2 closed-site edge wakes through `on_prepared` | KILLED | `test_closing_the_site_mid_preparation_stops_promptly_and_silently` (`prepared == []`) |

The ruling asked for both new tests to fail against both mutants. They don't: each is caught by one of them.
- **b1 and the drop test:** with the retiring design, a dropped engine is only *cancelled*, never `clear()`ed, while its task lives. `cancel_preparation` leaves `is_running` truthful, so an `is_running` gate would also hold the drop path back. The path where `is_running` lies is M11's `clear()`, reached on the R-P2 move. The move-timeout test kills b1 there.
- **b2 and b3** are killed by the drop test.

## Benchmark after T3-c, verbatim (clean run, nothing else running)
```
10 grids per site, 0.5 m line spacing, 60 traces/m, 128 samples/trace (time_zero, dewow, gain_agc; transform none); cell 0.25 m, native dz, thickness 5 ns, radius 1.5 spacings; 20 windows per timing.

| site | lines | traces/line | lattice | engine mode | prepare site (s) | first tick, incl. cube builds (ms) | slice_at median / p90 (ms) | edge median / p90 (ms) | shared_limit (ms) | one-grid baseline median / p90 (ms) |
|---|---|---|---|---|---|---|---|---|---|---|
| 10 x 20 m | 400 | 1200 | 400 x 160 | 10 streaming | 2.5 | 227 | 92.2 / 96.8 | 95.0 / 98.2 | 364 (4 windows at 5 ns); 611 (12 at 1.5 ns) | 9.2 / 10.1 |
| 10 x 50 m | 1000 | 3000 | 1000 x 400 | 10 resident | 16.7 | 3077 | 67.9 / 70.2 | 72.9 / 78.4 | 132 (4 windows at 5 ns); 373 (12 at 1.5 ns) | 2.9 / 3.0 |

10 x 20 m: 10 grids · 400 lines held in memory, 169 MB · slices redraw in 95 ms; site axis 88 levels; set_resolution 1 ms; one grid's tick is 8.7 ms binning + 0.5 ms fill (medians); lines written in 0 s; 0 errors
    forced resident, for comparison (23 MB of cubes, built in 381 ms): slice_at median / p90 10.5 / 11.0 ms
10 x 50 m: 10 grids · 1000 lines held in memory, 1.2 GB · slices redraw in 74 ms; site axis 88 levels; set_resolution 1 ms; one grid's tick is 0.4 ms binning + 2.5 ms fill (medians); lines written in 8 s; 0 errors
    forced resident, for comparison (142 MB of cubes, built in 62 ms): slice_at median / p90 63.8 / 66.5 ms
```
The 50 m engines were already resident here, so the "built in 62 ms" line rebuilt nothing.

- **10 × 50 m median `slice_at` under automatic residency: 67.9 ms** (p90 70.2), down from 520.4 ms.
- **One-time cube build cost:** the first tick is 3077 ms. That includes building the ten 50 m cubes (142 MB). The pre-fix run timed those builds alone at 2328 ms, about 0.23 s per grid; the rest of the first tick is plans, gathers and seams.
- The one-grid baseline is now 2.9 ms median.
- **Where the rest of the 67.9 ms goes:**
  - ten grids' bin and fill: about 29 ms;
  - `compose` alone, measured standalone (10 layers on the 1000 × 400 lattice): **39.6 ms median**, ten full-lattice passes in Task 1's core `compose`;
  - normalisation: small with "none".
- **The 10 × 20 m site stays streaming** (40 lines × 1200 traces is about 10.7 ms per grid, under a frame), so the site tick stays about 92 ms. That is M11's per-grid rule applied as ruled, ten times over.

These are inputs for the controller's Task 5 ruling. I have not applied the rule.

## Concerns (fix round 1)
1. **M11's `test_a_choice_delivered_during_the_cancel_wait_does_not_reopen_the_overlap` flakes under full CPU load (pre-existing, not a regression).**
   - The failure: `wait_for_preparation(20000)` returns False.
   - With four busy-loop processes saturating the cores, it failed 4/8 runs on the fix code and **5/8 on HEAD 886962d** (HEAD's engine and test file).
   - At normal load: 0 failures in 44 runs (both versions, alone and in-file).
   - I saw it fail during this round while the machine was busy, then could not reproduce it at normal load. M11's own docstring records the test as load-sensitive. Ledgered for the final review; not chased here.
2. **`compose` is now the largest part of a resident 10 × 50 m tick** (about 40 of 68 ms), because it makes full-lattice passes per layer. Recorded for the Task 5 ruling; not acted on.
3. Original concerns 5 (site CRS follows `grids[0]` as of the last rebuild) and 6 (the stretch pass's cost) stand. At 10 × 50 m the stretch is now 373 ms for 12 windows, down from 3015 ms.
