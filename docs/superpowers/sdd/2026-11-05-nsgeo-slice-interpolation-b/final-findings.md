# Final review findings to fix (controller ruling R14)

The final whole-branch review covered 617399e..c13b7e9 and found the branch "Ready to merge with fixes": no Critical findings. Fix every item below. Line numbers are at c13b7e9.

## I-1 (Important): a slow export gives no feedback for its first two bands

**Where:** `plugin.py:1029–1053` (`_export_progress`). The exports are called at `plugin.py:973` and `:1114`.

**What happens:**
- `QProgressDialog.setValue` processes events only once the dialog has been shown.
- The band-0 call only starts its internal show timer, and that timer cannot fire during a solve on the GUI thread.
- The band-1 call calls `show()` but processes no events.
- So nothing paints, and no Cancel click is heard, until band 2.
- The reviewer confirmed this offscreen in `/tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/ac13f161-32cb-4b27-9f12-2ce0f0d8a39b/scratchpad/review-final/progress_paint.py`.
- No wait cursor is shown anywhere in the export path.

**Measured cost:**
- A band takes about 10 s at 0.05 m on a 50 m grid, and about 32 s at the 4-million-cell cap. A Whole site band costs that times the number of grids.
- So QGIS freezes for 20–64 s with no cursor and no dialog. Windows marks the window "Not Responding" after 5 s.

**Fix:**
1. Wrap both exports in `busy_cursor()` (from `nsgeo_qgis.ui.finish_panel`).
2. In the progress callback, after `setValue(done)`, call `QCoreApplication.processEvents()` whenever `dialog.isVisible()`. This covers the band-1 show.
3. For minimum curvature (or whenever the engine's last solve exceeded `LIVE_SOLVE_BUDGET_MS`), `dialog.show()` and `processEvents()` once before band 0, so the dialog is up before the first slow band.
4. Fold in this deferred Task 5 minor on the same lines: run `refining_paused()`'s `finally` redraw under `contextlib.suppress(Exception)` plus `_log`. A failed redraw must never turn a good export into a deleted file, or a cancel into a Critical.
5. Correct `_export_progress`'s docstring about when events are processed.
6. Add tests:
   - the dialog is visible, and has processed a queued Cancel, by the band-1 callback. A cancel queued before band 1 must stop the export before band 2 is computed.
   - the wait cursor is shown during an export in both scopes, e.g. by patching `busy_cursor` and counting.

## I-2 (Important): where minimum curvature overshoots is described wrongly

**Where:**
- the guide: `docs/guide/getting-started.md:397`;
- the spec's "Known behaviour": `docs/superpowers/specs/2026-11-02-nsgeo-slice-interpolation-design.md` §5.4, around line 233.

**What happens:**
- With natural boundary conditions, minimum curvature continues the across-line slope past the outermost line, out to the max distance. It does the same past line ends and along the sides of a skipped-line gap.
- On the ten real lines (amplitude-envelope preset), up to 1.6% of cells fell outside the data range. The lowest value was −0.51 on data ranging 0.03–2.15.
- 77–100% of those cells lie in the strip past the outermost line, not between lines.
- The guide currently promises "a faint ring … between lines".

**Fix:**
- **Guide.** Make the overshoot sentence say where it shows: past the outermost lines it continues the trend, so a grid's edges, the sides of a skipped line, and seams between grids in Whole site can show values outside the data. It can also overshoot beside a strong contrast between lines. Keep the guide's voice: it is written for archaeologists, not geophysicists, and stays short.
- **Spec §5.4 "Known behaviour".** Add a dated correction note in the spec's existing style: `*Corrected 2026-11-05 (milestone B final review):* …`, with the real-line numbers above. Do not rewrite the original sentence.
- **Plan walkthrough checklist.** In `docs/superpowers/plans/2026-11-05-nsgeo-slice-interpolation-b.md`, "After Task 5", item 1, add:
  - "grid edges, Whole site seams and the sides of a skipped line (the overshoot)";
  - "a multi-grid Whole site drag at 0.1 m";
  - "an export at 0.05 m with a cancel".

## M-1: a rest can rebuild the plan itself, with no wait cursor

**Where:** `slices_dock.py:2387` and `site_scope.py:1024`.

**What happens:** `_on_rest` reads the finish settings live. A finish edit made in the rest's last 120 ms (the debounce interval) lands before its debounced redraw. `pending_solve` then rebuilds the plan and the kriging preview inside the rest slot: about 6 s at 0.05 m, with no cursor. Demonstrated in `/tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/ac13f161-32cb-4b27-9f12-2ce0f0d8a39b/scratchpad/review-final/test_rest_in_debounce.py`.

**Fix:**
- In This grid, `_on_rest` returns early when `not engine.weights_cached(finish)`.
- In the site, use `weights_cached(finish, at=drawn_at)`.
- The coming redraw rebuilds under the cursor and re-arms the rest.
- Add one test per scope.

## M-2: Whole site judges "slow" per grid, not per tick

**Where:** `site_engine.py:969–987`.

**What happens:** a tick solves every grid that takes under 50 ms on the GUI thread. Six grids at about 40 ms each make a 240 ms tick.

**Fix (ruling R14):**
- When the method is minimum curvature and a tick allows previews, preview every uncached grid at this window if the sum of those grids' last solve times exceeds `LIVE_SOLVE_BUDGET_MS`. A `None` last solve counts as slow.
- Otherwise solve them all on the GUI thread, as now.
- Document this in `_shown`'s docstring, citing plan call 5.
- Test: three grids each at 30 ms are previewed (sum 90 > 50). Each at 10 ms is solved at once (sum 30).

## M-3: the rest-timing test has a thin margin

**Where:** `test_plugin_slices_dock.py:2660, 2673`.

**What happens:** `moved` is taken after `setValue` returns. Qt's default coarse timer may fire up to 15 ms early.

**Fix:** take `moved` before `setValue`, or make both scopes' rest timer `Qt.TimerType.PreciseTimer` (through `qgis.PyQt`, valid on Qt 5 and 6). Do whichever keeps the assertion meaningful.

## M-5: Whole site keeps a stale stretch-only list after a grid is excluded

**Where:** `refine_flow.py:133` and `site_scope.py` `refresh_slice`.

**What happens:** if the remaining grids are already solved at this window, the tick is a full draw. `finished(stop=False)` keeps the list running, and it goes on solving windows for the excluded grid and possibly for the old site axis.

**Fix:**
- Cancel the site's list when `ready_grids` changes, where the `ready_handled` branch already resets the stretch.
- Test: exclude a grid while a stretch list runs, then check that the refiner is not busy right after the tick.

## M-6: nits

- `SliceEngine.finish`, `is_solved` and `pending_solve` trust a caller's `key=`. Their docstrings must say that `key` must be `solve_key` of the same `values` array, and that all callers hash the array they pass.
- Make `CurvaturePlan`'s arrays read-only after construction (`flags.writeable = False` on each array field, in `plan_curvature` or `__post_init__`). This enforces the contract the worker thread relies on. Make sure nothing writes to them afterwards: the re-plan path for non-finite data builds a new plan.
- Add a test that writing to `plan.coefficients` raises `ValueError`.
