# Task 2 report

Status: DONE_WITH_CONCERNS (minor deviations below).

Changed: P/fill_jobs.py (new FillJob; run builds fill, plus kriging preview for min_curvature, progress 0.7/0.3, fraction=1.0 at end; land -> engine._land_fill); P/slices_engine.py (fill_key, fill_held, fill_job, _land_fill, _fill_epoch bumped in _drop_fill, _disposed set in dispose, epoch rule in _rebuild_geometry); P/refine.py Refiner.settle; P/slices_plan.py FILL_BUDGET_S/FILL_POLL_MS/FILL_THREAD_NAME_PREFIX; P/ui/slices_dock.py self.fill_worker; P/plugin.py unload shuts it down beside refiner.

Epoch decision: _drop_fill always bumps. _rebuild_geometry records (frame, epoch) before its drop; if the rebuilt frame == old frame (z/dz edit, nothing a fill depends on) it restores the epoch, so a running job still lands. Different frame: bump stays (and job.frame != _frame anyway). set_source/clear/dispose/another fill_job all bump for good. Pinned by test_a_dz_edit_keeps_a_running_job_landable.

Fail-first: all new tests failed before implementation (AttributeError: 'Refiner' object has no attribute 'settle'; fill_job/fill_held/fill_worker missing): ran `qgis_tests.sh test_plugin_fill_jobs.py test_plugin_refine.py -k "settle or fill"` -> 14 failed.
(The dz-edit test was written with the rest and failed with the same AttributeError; not separately mutation-checked.)

Final: fill_jobs+refine+slices_engine 125 passed; core+pure whole suite passed (exit 0); `-m real_data` 46 passed; ruff check/format clean; CI mypy clean (66 files).

Deviations: `sourced` fixture not moved; imported from test_plugin_slices_engine (repo pattern, e.g. test_plugin_cut_picks). The worker-names test runs the job on dock.fill_worker via _docked_with. Progress split 0.7/0.3 is my choice.
Concerns: none blocking; fill_job asserts _choice is not None after _require_geometry.

## Fix round 1

1. and 2. One fill rule: `build_fill(populated, cell, settings, *, should_stop, progress)` now lives in P/slices_engine.py (beside `_fill_for`, with `CURVATURE_SHARE = 0.7`); `_fill_for` and `FillJob.run` (lazy import, since the engine imports fill_jobs) both call it. It lives in the engine module so the many existing tests that monkeypatch `slices_engine.plan_fill` still see every build. Tests: `test_a_fill_job_builds_what_fill_for_builds[min_curvature]` now also records `engine.preview(...)` before and requires it equal after landing with no plan_fill calls; new `test_a_min_curvature_job_reports_the_plan_then_the_preview` (plan progress <= 0.7, kriging >= 0.7, ends 1.0).
   Mutants, in a detached scratch worktree (removed): preview never built -> `FAILED ...test_a_fill_job_builds_what_fill_for_builds[min_curvature]` and `...reports_the_plan_then_the_preview` (2 failed, 11 passed); unscaled plan progress -> `FAILED ...test_a_min_curvature_job_reports_the_plan_then_the_preview` (1 failed). My first version of that test recorded fraction before the update and did not catch the unscaled mutant; fixed to record after.
3. `FillJob.land()` now releases `fill`, `preview` and its mask in a `finally`, installed or refused. New `test_a_refused_landing_lets_go_of_the_fill`; mutant (no release) -> `FAILED ...test_a_refused_landing_lets_go_of_the_fill` (1 failed, 12 passed).

Run: `qgis_tests.sh test_plugin_fill_jobs.py test_plugin_refine.py test_plugin_slices_engine.py` -> 127 passed; pure 396 passed, 4 skipped; `-m real_data` 46 passed; ruff and CI mypy clean.

## Fix round 2

Finding 4: `FillJob.land()` (P/fill_jobs.py) now releases fill, preview and mask only when `_land_fill` returned False; an installed job keeps them. Docstring says a refused job's `fill is None` means stale: measure nothing.
Test: `test_an_installed_landing_keeps_the_fill_a_refused_one_lets_go` (installed: `job.fill is engine._weights[1]`; refused: None). Mutant (release always, i.e. the previous HEAD code, with the new test) in a detached scratch worktree (removed): `FAILED ...test_an_installed_landing_keeps_the_fill_a_refused_one_lets_go` (1 failed, 13 passed).
Run: `qgis_tests.sh test_plugin_fill_jobs.py test_plugin_slices_engine.py` -> 102 passed; ruff and mypy clean (mypy on core + slices_plan.py + line_edit.py subset; fill_jobs/engine are not in CI's list).
