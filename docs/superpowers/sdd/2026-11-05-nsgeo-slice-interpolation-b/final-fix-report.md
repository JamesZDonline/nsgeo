# Final fix report: milestone B final review (ruling R14)

Branch `nsgeo-slice-interpolation-b`, from c13b7e9. All pushed to origin.

| Commit | Subject |
|---|---|
| db8b2f5 | fix(export): a slow export shows its cursor, paints and hears Cancel from band 1 |
| 21e51cf | fix(refine): rests never build a plan; the site judges slow per tick and drops a stale list |
| 75d286e | fix(curvature): a plan's arrays refuse writes |
| 0a31911 | docs(slices): minimum curvature overshoots past the outer lines, not only between them |

## Final verification (exact plan-context commands, run once at the end on 0a31911)

| Check | Result | Baseline |
|---|---|---|
| QGIS suite | **1471 passed** in 784.68 s | 1452 (+19 new tests) |
| core + pure | **991 passed, 3 skipped** in 14.22 s | 990 + 3 skipped (+1 new) |
| `ruff check .` | All checks passed | |
| `ruff format --check .` | 170 files already formatted | |
| mypy | Success: no issues found in 39 source files | |

All runs used `PYTHONDONTWRITEBYTECODE=1`; the QGIS run also used `QT_QPA_PLATFORM=offscreen` and `-p no:xonsh`.

---

## I-1: a slow export gives no feedback for its first two bands

**What changed** (`plugin.py`, `ui/slices_dock.py`)
1. Both exports run under `busy_cursor()`: `with busy_cursor(), dock.refining_paused():`.
2. In `_export_progress`'s callback, after `setValue(done)`, it calls `QCoreApplication.processEvents()` whenever `dialog.isVisible()`.
3. `_export_progress` takes a new `show_now` keyword. When it is set, the band-0 callback calls `dialog.show()` before `setValue(0)`. Events are then processed, as in item 2, before band 0 is computed. This happens inside `refining_paused()`, so the refiner and rest are already stopped.
   - The plugin sets `show_now` from the new `_bands_are_slow(engines, finish)`. That is true when the method is minimum curvature and the engines' last solves sum to more than `LIVE_SOLVE_BUDGET_MS`, or one of them is `None`.
   - This grid passes `[engine]`. The site passes every ready grid's engine, because a site band solves each grid once.
4. `refining_paused()`'s `finally` redraw is now inside `try/except Exception` with `_log(...)`. A failed redraw can no longer replace the export's own outcome.
5. `_export_progress`'s docstring now says when events are processed: not at the band-0 call, not by the `setValue` that first shows the dialog, and from then on by the callback itself.

**Covering tests**
- `test_plugin_slice_export_dialogs.py`:
  - `test_a_cancel_during_a_slow_first_band_is_heard_before_the_second`: a real dialog. Band 0 sleeps 0.6 s with no events and queues a click on the dialog's Cancel button. The test asserts that the click is processed at the band-1 callback with the dialog visible (`heard == [(1, True)]`), that the callbacks seen are `[0, 1]` so band 1 is never computed, and that the export reports "export cancelled" and leaves no file.
  - `test_a_slow_export_shows_its_progress_before_the_first_band[...]`: four cases. Minimum curvature at 500 ms or `None` shows the dialog before band 0 and processes the queued event. Minimum curvature at 5 ms and kriging do not, so a quick export keeps plan call 11's no-flash rule.
  - `test_an_export_shows_the_wait_cursor_throughout`: patches `plugin_module.busy_cursor` and checks the cursor depth is 1 at every band and `[1, -1]` overall.
  - `test_a_failed_redraw_after_an_export_changes_nothing_it_reported[False|True]`: the first `refresh_slice` raises. The good export keeps its file and reports success; the cancel reports "export cancelled"; neither raises a Critical.
- `test_plugin_site_scope.py`:
  - `test_a_site_export_shows_the_wait_cursor_throughout`.
  - `test_a_slow_site_export_shows_its_progress_before_the_first_band[30.0-True|10.0-False|None-True]`: three grids at 30 ms each sum to 90 ms and show early; at 10 ms each they sum to 30 ms and do not.

**RED** (before db8b2f5's production change; `pytest ... -k "slow_first_band or before_the_first_band or wait_cursor_throughout or failed_redraw_after"`; 6 failed, 2 passed):
```
E  AssertionError: the Cancel was not heard, visible, at the band-1 callback
E  assert [(2, True)] == [(1, True)]          <- the reviewer's finding exactly: heard only at band 2
E  assert [(False, [])] == [(True, [1])]       <- min curvature 500 ms: hidden, nothing pumped at band 0
E  assert [(False, [])] == [(True, [1])]       <- min curvature None
E  AttributeError: module 'nsgeo_qgis.plugin' has no attribute 'busy_cursor'
E  AssertionError: [('could not export the GeoTIFF: the redraw failed', 2), ...]   <- [False] and [True]
```
Site (`-k "site_export_shows_the_wait_cursor or slow_site_export_shows"`; 3 failed, 1 passed):
```
E  AttributeError: module 'nsgeo_qgis.plugin' has no attribute 'busy_cursor'
E  assert [(False, False)] == [(True, True)]   <- 30 ms x 3, and None
```
**GREEN:** `test_plugin_slice_export_dialogs.py` 27 passed. The site export subset (`-k export`) 13 passed.

**Notes**
- The test helpers `_progress_calling(...).make` in both files now accept `**_options`, because the plugin passes `show_now=`. Without this the cancel tests raised `TypeError`.
- Reading of "a cancel queued before band 1 must stop the export before band 2 is computed": the test queues the Cancel during the first band (index 0). It asserts that the second band (index 1) is never computed, because the Cancel is heard at the band-1 callback. That is the strongest version that fails on c13b7e9. The weaker reading, that a cancel stops before the third band, already held before the fix.

## I-2: where minimum curvature overshoots

**What changed** (docs only, no tests, as briefed)
- **Guide** (`docs/guide/getting-started.md`, Method bullet), in the guide's voice: "Past the outermost lines it carries on the trend of the data, out to the max distance. So a grid's edges, the sides of a skipped line, and the seams between grids in **Whole site** can show values higher or lower than any line recorded, even below zero on an amplitude slice. It can also overshoot a little beside a strong contrast between lines." The "faint ring … between lines" sentence is gone.
- **Spec §5.4 "Known behaviour"**: the original sentence is untouched. Below it is `*Corrected 2026-11-05 (milestone B final review):* …`, which gives the mechanism (natural conditions continue the across-line slope past the outermost line, past line ends and along a skipped-line gap) and the real-line numbers:
  - up to 1.6% of cells out of range;
  - the lowest value −0.51 on data ranging 0.03–2.15;
  - 77–100% of those cells in the strip past the outermost line.
- **Plan, "After Task 5" item 1**: three bullets added:
  - "grid edges, Whole site seams and the sides of a skipped line (the overshoot): …";
  - "a multi-grid Whole site drag at 0.1 m";
  - "an export at 0.05 m with a cancel: …".

## M-1: a rest can rebuild the plan itself, with no wait cursor

**What changed**
- `SlicesDock._on_rest` returns early when `not self.engine.weights_cached(finish)`.
- `SiteScope._on_rest` returns early when `not self.engine.weights_cached(finish, at=at)`, where `at` is the `drawn_at` already read there.
- Both docstrings say why.

**Covering tests**
- `test_plugin_slices_dock.py::test_a_rest_during_a_finish_edits_pause_builds_nothing`
- `test_plugin_site_scope.py::test_a_site_rest_during_a_finish_edits_pause_builds_nothing`

How the tests work:
1. Preview a new window, then edit max distance with the widget, so the debounce is active.
2. Call `_on_rest()` directly, which is the rest running out inside the pause.
3. Assert that `plan_fill` was not called and that no list started.
4. Let the edit's redraw rebuild. Assert that its rest refines once and that the final slice is drawn.

**RED:**
```
This grid:  E  AssertionError: the rest built the new plan itself      assert [1, 1] == []
Site:       E  AssertionError: the rest built the new plans itself     assert [1, 1, 1, 1, 1, 1] == []
```
**GREEN:** 1 passed in each file.

The reviewer's `review-final/test_rest_in_debounce.py`, re-run against the fix, now shows the only plan build coming from `_on_finish_timeout → refresh_slice`, with the wait cursor on (`True`).

## M-2: Whole site judges "slow" per grid, not per tick

**What changed**
- `SliceEngine.solve_cost_ms(values, coverage, finish, *, key=None) -> float | None` is new. It returns:
  - 0.0 when there is nothing to solve: another method, or the values are already solved on the plan held;
  - the last solve's time on the plan held otherwise;
  - `None` when no solve is timed on it yet, or the plan for these settings and cells is not built.

  `finish_is_slow` is now `cost is None or cost > LIVE_SOLVE_BUDGET_MS`, the same results as before.
- `SiteEngine.slice_at` slices the tick first (the new `_sliced`) and passes the slices to `_shown` (new `sliced=` keyword). The redraw timer still covers the slicing.
- `_draw_live(finish, binned, previewed)` hashes each grid once and sums the uncached grids' costs. If any cost is `None` or the sum exceeds the budget, every grid with a nonzero cost is previewed. Otherwise every grid is solved at once.
- A coverage tick no longer builds the live draw, so it hashes nothing.
- `_shown`'s docstring documents the per-tick rule, citing plan call 5 and M-2.

**Covering tests** (`test_plugin_site_engine.py`)
- `test_a_live_site_tick_is_slow_by_its_grids_solves_together[30.0-True|10.0-False]`: 3 × 30 ms is previewed; 3 × 10 ms is solved at once.
- `test_a_live_site_tick_counts_only_the_grids_it_must_solve`:
  - one grid cached and two at 30 ms: the two uncached grids are previewed and the cached one is drawn in full;
  - only one uncached grid at 30 ms: it is solved at once;
  - one grid untimed: every grid is previewed.

**RED:**
```
E  AssertionError: assert (False) where False = SiteSlice(... previewed={}, provisional=False).provisional   [30.0-True]
E  AssertionError: assert [] == ['B', 'C']                                                                  counts_only
```
**GREEN:** `test_plugin_site_engine.py` + `test_plugin_slices_engine.py` 110 passed.

**Departure, an existing test updated.** `test_plugin_site_scope.py::test_a_site_tick_hashes_each_grids_slice_once[quick]` set one grid's last solve to 5 ms among 500 ms grids and expected that grid drawn in full. That pinned the per-grid rule R14 replaces: under R14 the tick is slow, so the quick grid is previewed with the others. The parameter is now `solved`. That grid's slice at slider 30 is landed in the cache beforehand, so it is still "a grid drawn in full, never re-sliced by the rest", and the test keeps its purpose. The docstring notes the change.

## M-3: the rest-timing test has a thin margin

**What changed:** `test_the_refine_waits_for_the_depth_to_rest` now takes `moved = time.monotonic()` before `dock.slice_slider.setValue(value)`, with a comment explaining why. The rest starts inside `setValue`, before the preview is computed. A time taken after it therefore ate into the 5% a coarse timer may fire early.

I chose this over `PreciseTimer` because it changes only the test and keeps the assertion meaningful. A last move that failed to restart the rest would put the start about 0.2 s after `moved`, below the 0.27 s bound, so the test still fails. The assertion `remainingTime() > left` also still pins the restart.

**Tests:** the same test passes (`-k waits_for_the_depth_to_rest`: passed, and in both full runs). **No RED is shown**: this is a flake margin, not a deterministic fault.

## M-5: Whole site keeps a stale stretch-only list after a grid is excluded

**What changed**
- `RefineFlow.cancel()` is new. It cancels the refiner and clears the head, and leaves the rest and the preview to the next draw. `before_draw(rebuilds=True)` now calls it.
- `SiteScope._run_tick`'s `ready != self.ready_handled` branch, which already resets the stretch, now also calls `self.refine.cancel()`.

**Covering tests**
- `test_plugin_site_scope.py::test_a_grid_leaving_the_site_cancels_a_stretch_list`:
  1. Start on minimum curvature, with the tick refined and the stretch "this slice".
  2. Switch to the shared stretch, so a stretch-only list starts. Its first solve is held by a gate.
  3. Exclude C. The following tick is a full draw.
  4. Assert `not dock.refiner.busy` right after the tick.
  5. Release the gate and assert the stretch settles final.
- `test_plugin_refine_flow.py::test_cancel_stops_the_list_and_leaves_the_rest_to_the_next_draw`: a unit pin for `cancel()`.

**RED:**
```
E  AssertionError: the stretch list for the old grids ran on
E  assert not True  where True = <Refiner>.busy
```
**GREEN:** 3 passed (the new test plus both existing "leaving the site cancels" tests). `test_plugin_refine_flow.py` 8 passed.

## M-6: nits

**What changed**
- **Key docstrings.** In `SliceEngine.finish`, `is_solved` and `pending_solve` (and the new `solve_cost_ms` and `finish_is_slow`), `key` is now described as trusted and never checked. It must be `solve_key` of this very `values` array, and every caller hashes the array it passes.
- **Read-only plans.** `CurvaturePlan.__post_init__` sets `flags.writeable = False` on `populated`, `reach`, `domain` and `coefficients`.
  - `plan_curvature` already copies the caller's mask (`astype(bool)`), so no caller's array is frozen.
  - Nothing writes to a plan afterwards. `solve` copies `pop` for the non-finite path and builds a new plan there. All other uses read.

**Covering test:** `packages/nsgeo-core/tests/test_slices_curvature.py::test_a_plan_is_read_only`. It checks:
- writing `plan.coefficients[0, 0, 0]` raises `ValueError`;
- all four arrays are non-writeable;
- the caller's mask is still theirs;
- the non-finite re-plan path still works on a frozen plan.

**RED:** `E  Failed: DID NOT RAISE ValueError`. **GREEN:** `test_slices_curvature.py` + `test_slices_interpolate.py` 103 passed. The full core + pure run is green, so nothing else wrote to a plan.

---

## Departures and concerns

1. **M-2's existing test.** `test_a_site_tick_hashes_each_grids_slice_once`'s `quick` case pinned the old per-grid rule. It was re-pointed to a grid already solved; see M-2 above.
2. **I-1 "slow" criterion.** "For minimum curvature (or whenever the engine's last solve exceeded the budget)" is implemented as: minimum curvature, with the last solves summed over the band's engines exceeding `LIVE_SOLVE_BUDGET_MS`, or one untimed. That is plan call 5's rule applied per band, the same as M-2. A minimum-curvature export of quick solves (for example 5 ms at 0.2 m) therefore keeps plan call 11's "nothing flashes under 500 ms" rule. If the controller meant "always show early for minimum curvature", the change is one line in `NsgeoPlugin._bands_are_slow`.
3. **Not changed (out of the findings' scope).** The Method tooltip (`finish_panel._METHOD_TIP`, pinned by `test_plugin_finish_panel.py`) still says "It can overshoot beside a sharp change". After I-2 that is incomplete: it does not mention grid edges or seams. This could be a follow-up.
4. **Existing hazard, not made worse.** Processing events during an export, which `setValue` already did from band 2 on, can let a pending timer fire mid-export, such as a finish debounce from an edit made just before Export. The window-modal dialog blocks new input. This fix only moves the first processing earlier, after `refining_paused()` has stopped the refine and its rest. I note it in case the walkthrough sees an export interleaved with a redraw.
5. **M-3** has no RED evidence; it is a timing-margin change, not a deterministic fault.
