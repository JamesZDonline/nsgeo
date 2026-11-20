# Task 3 report: the shared stretch as a job

Status: DONE_WITH_CONCERNS. Commit: see `git log -1` on nsgeo-site-never-stuck (not pushed).

## Changes
- `P/stretch_jobs.py` (new): `WindowSource`, `StretchJob`, `GridStretch`, and the shared pure functions `shared_windows`, `shown_window`, `limit_of`, `draw_window` (+ `_Fills`, `_Unsolved`).
- `P/slices_engine.py`: `window_source`, `stretch_parts`, `stretch_job`; `shared_limit` now uses `shared_windows`.
- `P/site_engine.py`: `stretch_job`; `_shown` uses `shown_window`; `_measure` uses `limit_of`.
- `P/ui/refine_flow.py`: `held_stretch`, `land_stretch`.
- Tests: new `test_plugin_stretch_jobs.py` (16 cases), two in `test_plugin_refine_flow.py`.

## Shared functions and callers
- `shared_windows`: SliceEngine.shared_limit, SliceEngine.stretch_job.
- `shown_window` (normalise + `a*draw+b`): SiteEngine._shown (so slice ticks, `_measure`, shared_limit, stretch_limit), StretchJob (site).
- `limit_of`: SiteEngine._measure, StretchJob.
- `draw_window` is used only by the job: the engines' `finish`/`preview` are stateful (build/hold fills, touch the solved cache), so they keep their own code; both end in the same `finish_slice` / `smooth` calls. Not a single function for the draw.

## Thread safety
`StretchJob.run` uses numpy, the frozen `WindowSource`, copied solved dict, immutable frames/settings/seams. `stream_slice` and `SliceCube.slice_levels` do not write inputs (`resample_window` fancy-indexes to copies; results are fresh arrays; `cube.coverage()` builds a fresh array each call). Copied: the line/plan lists (as tuples) and the solved cache (dict copy; arrays in it are never written). A test checks line data unchanged after a run. Fill built for a mismatched window is held in the job and never installed.

## Fail-first (impl stashed with pathspec, tests kept)
18 failed, 8 passed: `AttributeError: 'SliceEngine' object has no attribute 'stretch_job'` (8), `'SiteEngine' ... 'stretch_job'` (7), `'RefineFlow' ... 'held_stretch'`/`'land_stretch'` (2), `'SliceEngine' ... 'stretch_parts'` (1). (8 passing were pre-existing refine_flow tests.) One test (refused landing) first failed from my own wrong assertion (`land()` returns False on refusal), corrected.

## Counts
stretch_jobs 16, refine_flow 10, site_engine 68, slices_engine 88, fill_jobs 14 all pass; pure 396 passed 4 skipped; `-m real_data` 46 passed; ruff check/format clean; CI mypy clean (66 files). Core suite not rerun (no core changes).

## Deviations / concerns
- The brief's streaming "one line ends early so the last window's coverage differs" does not occur in a single engine: `stream_slice` coverage is constant across windows (plans cover the full z). The test instead installs a held fill built for other covered cells, asserts the job leaves `engine._weights[1]` untouched and equals `stretch_limit`.
- Minimum curvature with a mismatched mask: the job builds the whole `build_fill` (plan + preview) although only the preview is used; correct but wasteful. Matches today's `_fill_for`.
- With a `fill=` FillJob given, the solved cache is NOT captured (fill_job drops it anyway), so min-curvature gives the provisional limit.
- The job holds all windows' slices in a list before `limit_of` (today's slice-scope path streams a generator); `limit_over_slices` copies finite values anyway.
- Site `stretch_job` also calls `_site_seams()` on the GUI thread for edge, which does slice_at (cached after first).

## Fix round 1
1. Fill reuse / fill-job read: tests count `slices_engine.build_fill` calls (`_count_builds`). This grid's `warm` is now really warm (fill held via a fill job first) and asserts 0 builds; new `test_a_cold_job_builds_the_fill_it_lacks` (1 build, nothing installed); `test_a_stretch_job_uses_its_fill_jobs_fill_without_building[idw|min_curvature]` (min_curvature pins the `preview` read); the site fill-job test now asserts 0 builds. Mutants in a detached scratch worktree (removed afterwards), on the fixed code: M1 (delete the `holds` branch) -> `6 failed, 16 passed`; M2 (`fill, preview = None, None` after the stale check) -> `3 failed, 19 passed`.
2. Streaming: `limit_of` takes an iterable (consumes lazily); the job's windows are a generator; the slice scope passes the generator, the site still lists. `test_this_grids_stretch_job_streams_its_windows` asserts a non-list reaches `limit_over_slices` and no window is finished before the previous is consumed. Failed against b2b192a (`assert not isinstance([array..., (list, tuple))`). Bit-equality tests unchanged and pass.
3. `RefineFlow.stretch_limit` = `held_stretch` else `measure()` + `land_stretch`; one arming rule. Existing refine_flow tests green.
4. `run` releases `_grids`, `_steps`, `_seams` in a `finally` (also on stop/stale). `test_a_finished_stretch_job_lets_go_of_what_it_captured` (weakref to the held FillWeights dies after the engine drops it) and `test_a_stopped_stretch_job_lets_go_too`; both failed against b2b192a (`the finished job still holds the fill it captured`; `assert {'': GridStretch...} == {}`).
5. Docstrings of both `stretch_job`s state the caller's obligation to pass a fill job for any grid without a held fill.

Commands: `qgis_tests.sh <file>`: stretch_jobs 22 passed, refine_flow 10, site_engine 68, slices_engine 88, fill_jobs 14; pure 396 passed 4 skipped; `-m real_data` run (exit 0); ruff check/format clean; CI mypy `Success: no issues found in 66 source files`.
