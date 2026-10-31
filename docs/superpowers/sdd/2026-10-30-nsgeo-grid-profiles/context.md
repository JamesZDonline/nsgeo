## Design (approved in chat, 2026-10-30)

What the user said:
- The user had found a reflection and swept the mouse across neighbouring lines on the map to follow it. On a zigzag survey the reflection jumped from the left of the profile to the right and back, because every other line was walked the other way.
- Every line should read the same way, so the reflection stays put during the sweep.
- When zoomed in on a reflection and sweeping across lines, the Profile should stay on the same stretch of ground on every line ("Yes").
- "I don't think there's any reason to see a reversed line drawn the way I walked it." So there is no toggle. The behaviour is always on.
- Approved the description below with "That all sounds good to me" and then "go for it".

Calls made by Claude and played back to the user without objection:
- Only the picture flips. Trace index stays the join between data and geometry (`nsgeo/geometry/placement.py`). Picks, selections, the map link, slices, velocity fits and saved sites keep counting traces in recorded order. Nothing in `SiteSession`, the core or the saved file changes.
- The low end of the grid goes on the left, the way a forward line already reads.
- The distance axis already shows metres along the grid on main (`GridPlacement.distance_along` is `start_along + direction × i / traces_per_metre`), so the issue's "label the axis in grid metres" bullet is already true. What changes is that the numbers now rise left to right on every line and carry on across blank space.
- **One ruler per grid and axis:** `[0, the grid's size along the lines]`, widened to take in any line on that grid and axis that runs past the edge. A line shorter than the ruler leaves blank space at its end instead of being stretched to fill the panel. At full view, a given metre sits at the same pixel on every line.
- **The window is held in metres along the grid,** and the time window is held too, when the Profile moves to another line on the same grid running the same way. This applies to opening a line and to the map hover preview alike. Moving to a line on another grid, or to a cross-line on the other axis, starts at Fit.
- **Fit shows the whole ruler.** Pan and zoom can go anywhere along it, including past the end of a short line.
- **Blank space does nothing.** Hover, a pick click and a velocity click there produce nothing, with no snapping onto the last trace. A drag-select that runs off the end of a line stops at the last trace.
- The arrow next to the distance axis shows which way the line was walked, so a mirrored line shows ←.
- A line with no distance axis keeps today's view: its own length, counted in traces, never mirrored.
- Every gesture is covered on a mirrored line: hover and the map cursor, drag-select, pick clicks, velocity-fit clicks and right-click discards, wheel zoom, middle-drag pan, Fit, 1:1 and the cutoff drag.

Calls made while writing this plan. Check these:
- **Each trace is drawn centred on its own ground position.** Trace `i`'s column spans `distance[i] ± half a trace spacing`, in both directions. Today the tick for `distance[i]` sits on the column's left edge. That half-trace offset is harmless on one line, but it would put a forward and a reversed line a whole trace apart. So ticks move by half a trace (about 8 mm at 60 traces/m). The cursor, picks and fit curves are already drawn at `trace + 0.5`, so they now sit exactly on their metre.
- **Blank space is a light diagonal hatch** (`NO_DATA_HATCH`, grey 200, `BDiagPattern`) over the panel background, so it can't be read as data in any colour table. This is a walkthrough check.
- **Caption:** a line on a ruler reads `m along grid · walked ←` (or `→`). A line without one keeps today's `m along line →` / `trace along line →`.
- **A drag-select that covers only blank space clears the selection,** the same as a plain click: `selection_cleared` fires and `range_selected` doesn't.
- **The hold reads the window off the line being left.** No separate window is remembered. Every line on a ruler has the same bounds in metres, so the horizontal window never clamps. The time window is clamped into each line's record, so a line with a shorter record narrows the time window for the lines after it.
- **Re-rendering the same line** (a stack, display or channel change with the same shape) keeps the exact transform object, as today. When the same line's sample count changes, for example after adding `time_zero`, today's code refits. On a ruled line the hold applies instead: the horizontal zoom stays and the time window is clamped into the new record. This is a small change from today.
- **The ruler follows edits.** On `grids_changed` and `lines_changed`, a displayed line whose ruler has changed is shown again with the window held, so Fit follows a grid resize or an import without reopening the line.
- `_trace_to_metres` and `_metres_to_trace` move out of `profile_dock.py` into the new pure module as `trace_to_metres` and `metres_to_trace`, unchanged, so the view and the pure tier can use them.

## Global Constraints

- `nsgeo_qgis/ui/ruler.py` and `nsgeo_qgis/ui/view_transform.py` import no Qt and no `qgis`. The pure tier imports both. `ui/__init__.py` stays empty for that reason.
- Nothing outside the Profile panel's drawing changes meaning. A trace index stays a trace index everywhere: signals, `SiteSession`, picks, selections, slices, saved files.
- The plugin imports Qt only through `qgis.PyQt`. `packages/nsgeo-core/tests/test_boundary.py` and `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py` must stay green.
- Every slot connected to a signal, and every Qt-invoked override, guards its own body and reports through `_log`. It never raises. `paintEvent` keeps its `try/finally` around `painter.end()`. Read the module docstrings of `profile_view.py` and `profile_dock.py` before touching either file.
- Pan and zoom never rebuild the image. Mirroring is a painter transform at draw time, not a mirrored copy made per frame.
- ruff 0.17.1 and mypy 2.4.0, as pinned in CI. `ui/ruler.py` joins the CI mypy file list in `.github/workflows/ci.yml`.

## Verification commands (exactly these)

- core + pure: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q`. Baseline at `7069959`: 808 passed, 3 skipped.
- qgis: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:xonsh`. Baseline at `7069959`: 1165 passed, about 9 minutes.
- lint: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- types: `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`

The worktree is `.worktrees/nsgeo-grid-profiles` on branch `nsgeo-grid-profiles`, off main `7069959`. Its own `.venv` and `.venv-qgis` are built, and the real DZT files are symlinked into `packages/nsgeo-core/tests/data/local/`. A real-data test that skips has validated nothing, so check the skip count.

## Review Focus

These are the input classes most likely to hurt a user that the main tests don't cover on their own. Each is pinned by a test in the task named.

1. **A zoom window lying entirely in blank space** (zoomed past the end of a long line, then sweeping onto a short one). The panel must show hatch and axes, paint nothing from the image, and raise nothing. Hover and clicks do nothing (Task 1: `test_a_window_in_blank_space_has_an_empty_source`; Task 2: `test_a_window_entirely_in_blank_space_paints_without_error`).
2. **Two lines on one grid with different traces per metre** (a second instrument, or a recalibrated wheel). The held window must stay the same in metres, not in traces (Task 3: `test_the_hold_is_in_metres_across_different_trace_spacings`).
3. **Moving from a ruled line to a line with no distance axis, and back** (a time-triggered file). The Profile must not mirror it, must not carry a window onto it and must not raise. Coming back starts at Fit (Task 3: `test_a_line_without_distance_neither_mirrors_nor_holds`).
4. **The difference view on a mirrored line.** The Profile must stay mirrored and keep its metre window when the difference toggles on and off (Task 3: `test_the_difference_view_keeps_the_mirror_and_the_window`).
5. **A preview of a line whose samples are not loaded yet.** This is the first hover over each line in a sweep. The header-only axes must already be ruled and held, and the load that follows must not jump the window (Task 3: `test_a_header_only_preview_is_ruled_and_held_through_its_load`).

---

