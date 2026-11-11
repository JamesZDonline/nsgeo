## Design

### The user's words

- **#3, from the M4 checkpoint:** *"Often lines will appear slightly longer than the grid size due to terrain modulations making the terrain distance greater than the linear distance. In these cases its better to compress the line to fit the grid. On the other hand if we intentionally run a line longer or shorter, we don't want it auto-compressing or stretching."*
- **#47 and #3, 2026-11-06:** *"Destagger is becoming more important. I found some grids that are clearly suffering from stagger (feature across 4 lines that looks wiggly in the slice due to stagger). This may also be helped by working with Issue #3 (which should include lines that are too long OR too short) If I could say stretch(compress) the lines to the edges of the grid for example, that would help smooth out the stagger across the whole line, but I want it to be configurable."*
- **#47's design from M12:**
  - A grid-wide shift is the starting point, then it can be adjusted line by line.
  - It applies everywhere a trace is positioned.
  - It is stored separately from the line's recorded start.
  - Picks follow it.

### The model (Claude's calls 1–4)

1. **The formula:** `distance_along[i] = start_along + direction × (scale × i / traces_per_metre + travel_shift)`.
   - **`scale`** defaults to 1.0. It is grid metres per metre the wheel recorded. The header stays untouched, so the change can be undone. This is the shape #3's comment suggested.
   - **`travel_shift`** defaults to 0.0, in metres. It moves every trace forward along the line's own direction of travel, and it is not scaled.
   - A positive shift is the usual fix. On the spike's survey, the positions as logged sat about 24 cm behind the radar.
2. **The shift applies to every line, each along its own direction of travel**, not to the reversed lines only. This is spike finding 2, and M17's decision 10 relies on it.
   - On a zigzag the two models differ only by a move of the whole grid along its axis.
   - Splitting the opposite-line disagreement half each way keeps features where they are.
3. **The shift is stored per line; there is no grid-level value.** "A grid-wide shift, then line by line" is done in Edit lines: select every row and press Set, then change the rows that need it. Lines imported later start at 0. The mount can sit differently from one survey to the next, so the shift is measured each time, not remembered (spike finding 3).
4. **Start, the Note's edge check and the edge-inset rules ignore `travel_shift`.** Start is where the line was recorded to begin. The shift corrects where its traces are drawn.

### Fit to grid edges (calls 5–8)

5. **Fit puts the line's first trace on the edge it starts at and its last trace on the other edge.**
   - In numbers: Start inset 0 and `scale = L / span`, where `span = (n_traces − 1) / traces_per_metre` and `L` is the grid's length along the line's axis.
   - Like Snap's inset, the scale is worked out at OK, against the grid's length at that moment.
   - A line with no distance axis, or with fewer than two traces, cannot be fitted. The table says so and leaves that line as it is.
6. **Fitting is opt-in everywhere.** It is offered in Edit lines (for a selection), and as an import checkbox that is off by default. There is no threshold and no automatic fitting. That is #3's "configurable".
7. **A fitted line stays fitted when its grid's length changes.** This extends line editing decision 4.
   - A line counts as fitted when its scale ≠ 1 (by more than `SAME_M`) and both its recorded ends lie within `START_TOLERANCE_M` of the grid's two edges. The ends are judged without `travel_shift`.
   - Such a line is fitted again to the new length: its Start follows the inset rule, and its scale becomes `fit_scale(span, new_length)`.
   - The message bar counts the lines refitted. A line that is not fitted keeps its scale. A reversed one still moves with the far edge, as today.
8. **The Note flags a scale more than 20% away from 1** (`SCALE_NOTE = 0.2`), for example "scale ×1.450 stretches it by 45%". A fit across a selection that includes a deliberately short line then stands out before OK.

### Where it shows (calls 9–12)

9. **Edit lines:**
   - Two editable columns go after Start: **Scale** and **Destagger (m)**.
   - Two bulk rows go after the Start row: **Scale [spin] Set · Fit to grid edges**, then **Destagger (m) [spin] Set**.
   - These use the existing look, so there is no lavish mock-up. The user chose this bulk panel for line editing, and the walkthrough judges the result.
10. **The Survey panel** adds ` · ×0.954` to a line's text when its scale ≠ 1, and ` · destagger +0.24 m` when its shift ≠ 0.
11. **Import** gains a checkbox, **Stretch or compress each line to the grid's length**, on a form row named **Line length**. A fitted row's Note reads `fitted to the grid's 10.00 m (scale ×0.9032)` instead of `exceeds grid size …`.
12. **Picks, the profile, the map, the map link, velocity fitting and slices get no new code.**
    - They all read `Line.distance_along()` or `trace_coords()`.
    - Edit lines' existing paths already cover a scale or shift change once `same_placement` compares the two new fields: picks follow on refresh, and a slice source re-prepares when a placement differs.
    - Tests pin this (Task 2).

### The survey file (call 13)

13. **`"scale"` and `"travel_shift"` are written only when they differ from their defaults.**
    - A site with no corrections saves exactly as it does today, so it still opens in nsgeo 0.3.0.
    - There is no schema bump. Presets, cubes and velocity fits were added the same way.
    - **Known hazard, not fixed:** 0.3.0 opening a corrected site draws its lines uncorrected, and drops the corrections on its next save.

### Known limits (recorded, not built)

- **Migration and velocity fitting use different spacings on a scaled line.** Migration takes its trace spacing from the header (`Radargram.dx_m`), while velocity fitting uses placed metres. On a line scaled ×0.95, migration sees a 5% longer spacing than the fit did. Processing at the true distance is M17b.
- **Profiles show the corrected distance.** The profile's ruler and its mirrored axis read `distance_along`, so a fitted line fills its grid's ruler exactly. This is intended.

## Global Constraints

- `nsgeo_qgis/line_edit.py` and `nsgeo_qgis/lookup.py` import no Qt and no `qgis`. Both are on CI's mypy list.
- The plugin imports Qt only through `qgis.PyQt`. `tests/pure/test_plugin_boundary.py` and `test_no_orphan_signals.py` stay green.
- Every Qt slot guards its own body and reports, never raises. In `EditLinesDialog`, a slot ends in `except Exception as exc: self._failed(exc)`, the pattern the dialog already uses.
- One change is one dirty mark and one `lines_changed`, however many lines it touches.
- **Numbers:**
  - Existing: `START_TOLERANCE_M = 0.05`, `SAME_M = 1e-9`.
  - New: `SCALE_NOTE = 0.2`.
  - The bulk Scale spin runs 0.5–2.0, with 4 decimals, step 0.001 and default 1.0. The bulk Destagger spin runs −5.0 to 5.0 m, with 3 decimals, step 0.01 and default 0.0.
- **Display:** the Scale cell is `f"{scale:.4f}"` and the Destagger cell is `f"{travel_shift:.2f}"`.
- **Copy, exactly:**
  - Note for a scale far from 1: `scale ×{s:.3f} stretches it by {abs(s-1):.0%}` when `s > 1`, and `scale ×{s:.3f} compresses it by {abs(s-1):.0%}` when `s < 1`.
  - A fit that skipped a row: `{label} has no recorded length to fit, so it was left as it is`. Several are joined with `; `.
  - A refused Scale cell: `{text!r} is not a scale above 0; unchanged`.
  - The grid length report:
    - Both kinds: `{grid} is now {L:.2f} m along {axis}; its {n} reversed line(s) moved with the far edge, and its {m} fitted line(s) were fitted to the new length.`
    - Fitted lines only: `{grid} is now {L:.2f} m along {axis}; its {m} fitted line(s) were fitted to the new length.`
    - Reversed lines only: unchanged from today.
  - Survey panel suffixes: ` · ×{scale:.3f}` and ` · destagger {travel_shift:+.2f} m`.
  - Import note: `fitted to the grid's {L:.2f} m (scale ×{s:.4f})`. With fitting on but no known grid length: `cannot be fitted without a known grid length`.
  - Tooltips (Edit lines column headers and bulk rows, and the import checkbox):
    - Scale: `Grid metres per metre the wheel recorded. Fit to grid edges sets it so the line's first and last traces sit on the grid's two edges. 1 leaves the line as recorded.`
    - Destagger: `Moves every trace of the line this far forward along its direction of travel, kept apart from Start. If features on lines walked one way sit behind the same features on lines walked the other way, increase it.`
    - Import checkbox: `For lines walked edge to edge whose wheel read long or short (terrain, calibration). Leave it off for lines run long or short on purpose. Edit lines… can fit or unfit any line later.`
- Comments and docstrings follow the file they are in. They cite this plan as `(placement corrections plan, call N)`.
- **Shared-worktree safety:** reviewers and any mutation probes work on a scratch copy, never this worktree. Set `PYTHONDONTWRITEBYTECODE=1` for every test run.
- **Commits:**
  - End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  - Push each commit to `origin nsgeo-placement-corrections` as it is made.
- Touch no other worktree.

## Verification commands (exactly these, from the worktree root)

The worktree uses the main checkout's virtualenvs, with the worktree's core on `PYTHONPATH`, plus a local `.venv-tools` (git-excluded) holding the CI-pinned ruff 0.17.1 and mypy 2.4.0. Real data is linked file by file under `packages/nsgeo-core/tests/data/local/` (git-ignored; never `git add -f` from it). A real-data test that skips has validated nothing, so the skip count must not rise.

- **core + pure:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider`
  - The baseline at `b55b2f0` is 1150 passed, 5 skipped.
- **qgis:** `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:cacheprovider -p no:xonsh`
  - This takes 10+ minutes. Run single files while iterating; the coordinator runs the full tier.
- **lint:** `.venv-tools/bin/ruff check . && .venv-tools/bin/ruff format --check .`
- **types:** `.venv-tools/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py packages/nsgeo-qgis/nsgeo_qgis/line_edit.py`

