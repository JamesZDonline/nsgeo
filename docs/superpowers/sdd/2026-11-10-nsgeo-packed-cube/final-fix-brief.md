# Final-review fix wave — #113 packed cube (branch nsgeo-packed-cube, head 89a6b4d)

Context: the branch is built and reviewed. The final whole-branch review found no Critical or Important issues. These are the small fixes the controller ruled in. Right-size the work: edit, add the few tests named, run the touched test files, push. No mutation probes in this worktree. If you want to confirm that a new test can fail, mutate a scratch copy, or mutate in place and restore before committing. Never commit a mutant.

Line numbers were taken at c7bd8ce. main has since been merged in, so re-locate each spot by its text.

## F1. The checkbox shows a stale figure during a re-preparation (`packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`)

- **What happens now.** `_on_source_changed`, `set_included` and the restore path each call `_update_included_label()` before `prepare()`. At that moment the engine still holds the old lines, so `is_prepared` is True and the checkbox shows the old line set's `engine.estimate`. `prepare()` then calls `self.engine.set_source(choice)`, which empties the engine's lines. Only `_refresh_source_status()` follows that call, so nothing refreshes the checkbox until `_on_prepared`.
- **Fix.** Call `self._update_resident_check_label()` right after `self.engine.set_source(choice)` in `prepare()`. The engine is then not prepared, so the checkbox takes the before-preparing estimate.
- **The docstring.** `_included_estimate` (or wherever it says the label and checkbox "never disagree") must now say what is true. Until `_on_prepared` runs on a grid change, the figure counts against the frame on screen.
- **Add a QGIS test in `tests/qgis/test_plugin_slices_dock.py`.**
  - Prepare with all the lines, then `set_included` with one line fewer.
  - While the engine is not prepared, the checkbox's figure equals the before-preparing estimate for the new line set.
  - Assert on bytes, not on the rounded MB string, using the existing `_spy_on_the_estimate` pattern or a direct value. The fixture rounds every figure to "1 MB", so the rounded string cannot tell the figures apart.
  - If the fixture cannot hold the engine unprepared, re-using the existing pattern of clearing the engine's `_lines` after `set_source` is acceptable.

## F2. Docstrings this branch made false (a sweep, no behaviour change)

- `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`:
  - `MemoryEstimate`'s docstring says "cube memory grows with resolution and not with line count". A packed cube grows with the covered cells, which grow with the lines and with resolution. Reword it.
  - `format_status`'s docstring says halving the cell "quadruples the cube". For a packed cube of line data it roughly doubles, while the fill weights still quadruple. Reword it.
- `packages/nsgeo-core/src/nsgeo/slices/cube.py`, the one-block read docstring (~190-194). "Bit-identical" holds for blocks of two or more covered cells. A single-column block sums its column pairwise, so it can differ by one ulp. Say so in one clause.
- `packages/nsgeo-core/src/nsgeo/render.py` (~106, 109), `packages/nsgeo-core/src/nsgeo/slices/display.py` (~151, 153) and `packages/nsgeo-core/tests/test_real_files.py` (~264, 271) name `cube.mean`, which no longer exists. Reword each to "every raw level" (or "the raw levels"), keeping the measured numbers they cite.
- `packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py` (~160-162), the `n_covered=120*120` value. Add a one-line comment saying it is a deliberate upper bound. `choose_residency` returns "streaming" from the trace-count branch before it reads the estimate, so the value does not decide the outcome.

## F3. A test for plan call 13's skip path (`tests/qgis/test_plugin_slices_dock.py`)

`_included_estimate` skips a line whose `trace_coords` raises, the same way preparation skips it. Removing that try/except would make the label and checkbox refresh raise inside slots, where QGIS swallows the exception silently.

Add `test_a_line_whose_position_cannot_be_computed_is_left_out_of_the_count`:
- Monkeypatch one included line's `trace_coords`, or its placement, so that it raises `ValueError`. In real use this is, for example, a line with `traces_per_metre <= 0`.
- Call `dock._update_included_label()`.
- It does not raise.
- The `n_covered` passed to `estimate_memory` (use the spy) equals `covered_cells` over the other lines only.

## F4. Store test upkeep (`packages/nsgeo-core/tests/test_slices_store.py`)

- **Dead setup (~396-399).** Remove the dead `cube` / `good` / `save_cube(cube, good)` lines that `_good_parts` made unused.
- **`test_loading_a_file_missing_one_required_array_fails_clearly`.** Its docstring is stale: it no longer covers "every one of the three arrays". Reword it to say what it now covers. Also add a version 1 case: meta with `store_version: 1` and no `mean` array must raise `CubeStoreError`.
- **A new damaged-file case.** Add "count_0 saved as float", with values + 0.7, to `test_a_damaged_version_2_file_fails_clearly`. This pins the `same_kind` cast on `count_{i}`.

## Out of scope (leave alone)

- the `_window` → `_check_window` rename;
- `load_cube`'s placeholder state;
- a rotated-frame test helper;
- `same_kind` upcast hardening;
- the int64 count wrap;
- `load_cube` letting `zlib.error` escape;
- a site-wide memory budget.

## Verify, commit, push

- core + pure: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider`. Expected now: 1114 passed, 5 skipped, plus your new tests.
- QGIS, the dock file only: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py -q -p no:cacheprovider -p no:xonsh`
- lint: `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- types: `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py packages/nsgeo-qgis/nsgeo_qgis/line_edit.py`
- One commit, `fix(slices): final-review polish for the packed cube (#113)`, ending with `Co-Authored-By: <your model name> <noreply@anthropic.com>`. Then `git push`.
- Never commit anything under `tests/data/local`. `with-dzg` there is a symlink and is git-ignored.
