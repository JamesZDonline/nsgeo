# Plan-wide context for every task (from the plan's header; binding)

The coordinator has already created .venv and .venv-qgis and copied the real DZT files into packages/nsgeo-core/tests/data/local (gitignored). Baseline core+pure: 842 passed, 3 skipped (the three test_schema.py skips are by design).

**Spec:** `docs/superpowers/specs/2026-11-02-nsgeo-slice-interpolation-design.md`. This plan is milestone A of its §12. Minimum curvature is milestone B and is **not** in this plan. Read the spec before your task. Where the plan and the spec disagree, the plan wins, because it records the decisions listed below.

## Plan calls (decisions this plan makes where the spec leaves the builder a choice)

1. **Neighbourhood (spec §5.3).**
   - Four quadrants, with the 3 nearest data cells in each (up to 12 sources).
   - Search radius = max(2 × line spacing, 2 × max distance).
   - Quadrant boundaries: `q = floor((atan2(dy, dx) mod 2π) / (π/2))`. So for lines along X, two quadrants look up and two look down. For lines along Y, two look left and two look right. Either way every gap cell sees both of its lines.
2. **Weights are built synchronously, on first use.**
   - Spike on a 50 m grid of 0.5 m lines at the default 0.2 m cell: IDW about 60 ms, kriging about 300 ms; applying the weights costs about 4 ms per slice.
   - A 0.05 m cell takes seconds to set up. A wait cursor shows while weights are built, which is the "wait at setup" the user accepted.
   - **Escalate, rather than ship,** if Task 1 measures kriging setup above 0.5 s at the default cell on the 50 m synthetic grid.
3. **Two `FinishPanel` instances, one per scope** (`dock.grid_finish`, `dock.site_finish`), shown one at a time.
   - This is today's pattern for the two radius boxes, so each scope keeps its own remembered values without the shared-spin capture and restore machinery.
   - The user sees one Interpolation group either way. This refines the spec's §8 wording "collapses into one control".
4. **A remembered `method` lives in the same `resolution` record as the numbers,** so there is one remember path. `_merge_resolution` keeps strings as strings.
5. **A non-finite data value (a broken cube invariant) is skipped, not propagated.** `FillWeights.apply` renormalises a target's weights over its finite sources. That data cell itself shows NaN.
6. **The spec §9 stripe example is moved onto the cell lattice.** At a 0.05 m cell a 0.1 × spacing offset is one cell and leaves no stripe, so the test offsets a line by 0.2 × spacing instead (Task 1).
7. **The real-data helpers in `tests/test_slices_site.py` move to `tests/real_lines.py`** so the interpolation tests can share them.

## Global Constraints

- **The core stays numpy-only, with no Qt.**
  - `packages/nsgeo-core/tests/test_boundary.py` and `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py` stay green.
  - Do not add scipy, even as an accelerator.
  - The plugin imports Qt only through `qgis.PyQt`.
- Every slot connected to a Qt signal or timer guards its own body and reports through `_log` or `dock.error`. It never raises. Read the module docstrings of `slices_dock.py` and `site_scope.py` before touching either.
- **Seeds never write.** Opening a survey, switching scope or grid, seeding, restoring and clamping never mark the survey dirty and never write a remembered value. Only a user's edit, a line choice, or picking a saved cube writes one.
- **Files stay readable both ways.**
  - `SCHEMA_VERSION` does not change.
  - Surveys and cube records from 0.2.0 keep loading. 0.2.0 must still load what this build saves.
  - Old fill settings (`radius_spacings`, `radius_m`) are ignored on load, never mapped onto the new controls.
- **Exact values from the spec:**

  | Setting | Value |
  |---|---|
  | Default method | `"kriging"` |
  | Default max distance | `0.5` × line spacing |
  | Distance comparison | inclusive, `≤ max_distance_m + 1e-9` |
  | Smoothing default | `0.0` m on both axes |
  | Smoothing kernel | Gaussian σ in metres, truncated at 4σ |
  | IDW power | `2` |
  | Kriging | ordinary, linear variogram, no nugget, isotropic |
  | Interpolation | never changes a data cell |
  | Smoothing | never fills a blank |

- **Method keys and labels, in this order:** `"none"` → `None (binned only)`, `"idw"` → `Inverse distance (IDW)`, `"kriging"` → `Kriging`. Milestone B appends `"min_curvature"`.
- **Comments and docstrings** follow the file they are in. They say why, and cite the spec as `(interpolation spec §5.2)` the way existing comments cite rulings.
- **Shared-worktree safety.** Reviewers and any mutation testing never edit this worktree; they work on a scratch copy. Set `PYTHONDONTWRITEBYTECODE=1` for every test run.
- **Tool versions:** ruff 0.17.1 and mypy 2.4.0, as pinned in CI.
- **Commits:**
  - End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  - Push each commit to `origin nsgeo-slice-interpolation` as it is made.
- **The unmerged `nsgeo-m14` branch has a test that imports `fill` from `nsgeo.slices`.** Do not touch that branch. Whichever of the two merges second updates that test.

## Verification commands (exactly these, from the worktree root)

- **core + pure:** `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider`
- **qgis:** `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:cacheprovider -p no:xonsh`
  - This takes about 11 minutes. Run single files while iterating.
- **lint:** `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- **types:** `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`

## Review Focus

These are the inputs most likely to hurt a user that the spec does not spell out. Each is pinned by a test in the task named.

1. **A survey edge, a lone line, a lone data cell.**
   - Cells beyond the outermost line are filled from one side only, out to the max distance and no further. One line, or one data cell, must not crash.
   - Pinned by Task 1: `test_one_line_fills_both_sides_out_to_max_distance_and_no_further`.
2. **A grid's line spacing edited after its max distance was set.**
   - The metres readout and the drawn slice follow the new spacing without a grid switch.
   - Pinned by Task 4: `test_max_distance_follows_a_line_spacing_edit`.
3. **A 0.2.0 survey or cube.**
   - A 0.2.0 survey remembers `radius_spacings: 0.5`; a 0.2.0 cube record has only `radius_m`. Both open on the new defaults, with no holes, and opening them doesn't mark the survey dirty.
   - Pinned by Task 4: `test_a_0_2_0_remembered_radius_is_ignored` and `test_restoring_a_0_2_0_cube_record_shows_the_defaults`.
4. **Toggling method or max distance back and forth.**
   - For example kriging → IDW → kriging. The cache must never serve the other setting's weights.
   - Pinned by Task 4: `test_switching_method_back_gives_the_same_slice_as_from_scratch`.
5. **A fine cell on a large grid.**
   - The weights' memory counts in the estimate, so the over-budget warning fires before anything is built.
   - Pinned by Task 3: `test_the_estimate_counts_the_fill_weights`.

