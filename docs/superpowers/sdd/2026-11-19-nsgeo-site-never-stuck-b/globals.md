## Global Constraints

**Paths:**
- `P` = `packages/nsgeo-qgis/nsgeo_qgis`, `T` = `packages/nsgeo-qgis/tests`,
  `C` = `packages/nsgeo-core/src/nsgeo`, `CT` = `packages/nsgeo-core/tests`.

**Tests:** run them as Plan A did.
- **Core and pure:** `./.venv/bin/python -m pytest packages/nsgeo-core/tests -q -p no:xonsh` (and `…/nsgeo-qgis/tests/pure`).
- **QGIS:** `packages/nsgeo-qgis/scripts/qgis_tests.sh <file>`.
  - Never run the whole QGIS tier locally.
  - Before committing, also run `-m real_data`.

**Fail first:** every new test must fail before its fix, for the stated reason. A test that avoids the input that breaks the code is a bug report.

**Code rules:**
- Every Qt slot and timer callback guards its whole body and never raises.
- No Qt, no session and no QGIS object is touched off the GUI thread. A job's `run` uses only numpy and the immutable objects captured when it was made.
- Core stays numpy-only and on Python 3.9.
- Run ruff check and format, and CI's mypy command from `.github/workflows/ci.yml`.

**Copy** (the builder may tighten the wording, in this register):
- Working, This grid: `Working out the fill at {cell} m: {percent}%`.
- Working, Whole site: `Working out the fill at {cell} m: grid {n} of {total}`.
- Working, stretch: `Working out the colour stretch…`.
- The Cancel link: `Cancel`.
- Warnings note when there is no picture: `The picture was not drawn: its fill was cancelled. Change the cell or the interpolation to draw it.`

**Values:**
- `FILL_BUDGET_S = 0.2`, the no-flicker wait.
- `FILL_POLL_MS = 100`, for refreshing the progress line.
- `FILL_THREAD_NAME_PREFIX = "nsgeo-fill"`.
- All three go in `P/slices_plan.py`.

**Process:**
- Implementers commit locally. The controller pushes after review.
- **#196 is not yours:** `test_a_site_refine_for_a_window_left_behind_never_draws` and its This grid twin fail under load at `assert finished_late.is_set()`.
- The two narrow-window site-scope timing tests are not yours either: `…never_overlaps_preparations` and `…waits_out_a_task_that_outlived_its_cancel`.

**Out of scope:**
- **Inline builds:** cuts (`section_fills`), the ParaView export and the GeoTIFF exports keep building inline. The exports already build on their task's thread.
- **The per-tick draw cost.**
- **The fill key has no search radius setting.** It is derived from the max distance (`SliceFinish.in_metres`), so "a fill setting" means cell, method and max distance.

## Review Focus

1. **A fill landing after its engine moved on:** a cell edit, a new source, a removed grid or `clear()`. It must never install. Pinned in Task 2, and by "a stale fill never lands" in Tasks 4 and 5.
2. **The background stretch must equal today's synchronous one exactly.** This covers both scopes, IDW and kriging, minimum curvature both unsolved (provisional) and fully solved (final), normalisation and manual gains, and resident and streaming sources. Pinned in Task 3.
3. **A streaming window whose covered cells differ from the held fill's.** For example an edge window where a short line ends. The stretch job builds its own fill for that window and leaves the held one alone. Pinned in Task 3.
4. **Closing the survey or unloading the plugin while a fill runs.** The worker is shut down, nothing lands on a disposed engine, and nothing raises. Pinned in Task 4.
5. **Cancel when the picture's own cell was slow.** Going back rebuilds it, so the working line shows again over the unchanged map. That second Cancel has nothing to go back to, so it latches. Pinned in Task 4.

