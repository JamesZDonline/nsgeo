## Design (agreed with the user, 2026-11-10)

1. A resident cube stores only the covered cells. Slices are identical to today's. Streaming mode is unchanged.
2. The cube and the file hold **one packed block per travel direction**. There is always exactly one block until #47 builds the grouping. None of the balancing is built here.
3. **One way to read values:** a level, a window, or the values at chosen cells. M15 and M16 use these, never the arrays.
4. **New saved files are packed.** Old files still load. Nothing outside nsgeo reads the files (user, 2026-11-10), and nsgeo itself never reads one back, so the format is free to change.
5. **The memory figure counts the covered cells,** before preparing as well as after.

**Measured on Sunnyside (2026-11-10, 216 levels, all ten grids, cubes only):**

| Cell | Covered | Dense today | Packed |
|---|---|---|---|
| 0.2 m | 19–40% per grid | 30 MB | 11 MB (2.9×) |
| 0.1 m | 9–20% | 121 MB | 21 MB (5.7×) |
| 0.05 m | 7–16% | 484 MB | 63 MB (7.6×) |

## Plan calls (decisions this plan makes where the design leaves a choice)

1. **`CubeBlock`** (in `nsgeo/slices/cube.py`, frozen dataclass):
   - `cells`: int64, 1-D, strictly increasing, every id in `[0, frame.n_cells)`;
   - `mean`: float32, `(nz, n)`;
   - `count`: int32, `(n,)`, every value ≥ 1;
   - `heading_deg: float | None = None`. `None` means the block holds every direction. #47 will set it.

   The block validates its own shapes and dtypes. The cube validates the cell ids against its frame and `z.nz`. Either raises `ValueError`.
2. **`SliceCube(frame, z, blocks, provenance)`** with `blocks: tuple[CubeBlock, ...]`, at least one block. The `mean` and `count` fields go away.
3. **Reading several blocks:** the count-weighted mean, `Σ count·mean / Σ count`, accumulated in float64 and returned as float32. That equals the mean of every trace in the cell. Overlapping blocks are allowed. With one block, a read takes the window mean of the block's columns and scatters it into a NaN `(ny, nx)` array. That is the same float32 arithmetic as today, so it is bit-identical (Task 1 pins this on real data).
4. **`values_at(cells, k0=0, k1=None)`** takes flat cell ids and returns `(k1 − k0, len(cells))` float32. `−1` (outside the frame, as `CubeFrame.cell_index` returns it) and uncovered cells give NaN. Any other id outside `[0, n_cells)` raises `ValueError`. M15's columns past a grid edge are `−1`, which is why `−1` is accepted.
5. **`build_cube`** never allocates a dense array. The covered cells are the union of `plan.cells` (`np.unique` of their concatenation). Each plan's columns come from `np.searchsorted`. The total is accumulated into a `(nz, n_covered)` float32 array and divided by the count in place, so the peak is one packed array plus one line's resampled block. `accumulate` (private to the module, not exported) takes the plan's packed column positions as an extra argument.
6. **`SliceCube.from_dense(frame, z, mean, count, provenance)`** packs a dense `(nz, n_cells)` mean and `(n_cells,)` count, keeping the columns where `count > 0`, as one block. It keeps today's shape error messages (`mean must be (nz, n_cells), got …`). Version 1 files load through it, and the tests use it to build small cubes.
7. **`SliceCube.nbytes`** is the sum of every block array's `nbytes`. The plugin's estimate must equal it for a cube built from the same lines (Task 2 pins this).
8. **`coverage()`** is computed on each call (a zeros array plus one scatter, about 1 ms at a million cells), not cached. A cache would hold 4 B per frame cell that the estimate would then have to count.
9. **Store version 2.**
   - Arrays: `cells_{i}` (int64), `mean_{i}` (float32), `count_{i}` (int32) for each block `i` from 0, plus `meta`.
   - `meta` gains `"blocks": [{"heading_deg": null}, …]`, one entry per block, in order.
   - The `.npz` stays `savez_compressed`, loaded with `allow_pickle=False`.
   - `STORE_VERSION = 2`. `load_cube` reads versions 1 and 2. Any other version raises `CubeStoreError`, as today.
   - Every malformed version 2 file raises `CubeStoreError` and nothing else. That covers a missing block array, a `blocks` list that disagrees with the arrays, unsorted or out-of-range cells, a zero count, a wrong shape and an object array. `load_cube` builds the cube and turns the cube's `ValueError` into `CubeStoreError`.
10. **`covered_cells(frame, coords) -> int`** (in `nsgeo/slices/binning.py`, exported) counts the distinct in-frame cells that any trace falls in. `coords` is an iterable of `(n_traces, 2)` world-coordinate arrays. It uses `frame.cell_index` and ignores `−1`, so it never raises for traces outside the frame. It equals the cell count of `build_cube`'s block for the same lines.
11. **`estimate_memory(prepared_samples, n_cells, nz, n_covered)`**: `n_covered` is a new, required fourth argument (not `covered_cells`, which would shadow the helper), so no caller can silently keep the dense figure.
    - `cube_bytes = nz·covered·4 + covered·4 + covered·8`, which is the mean, the count and the cell ids, and equals `cube.nbytes`.
    - `weights_bytes` is unchanged (`n_cells · WEIGHT_BYTES_PER_CELL`). The fill writes every cell.
12. **The engine's estimate** calls `covered_cells(self._frame, (line.coords for line in self._lines))`. The count is cached and reset at every place that sets `self._plans = None` or assigns `self._lines`. The status line reads the estimate on every redraw, so it must not recount each time. The estimate is a property read from slots, so it is never computed through `plan_line`, which can raise.
13. **The dock's figure before preparing** (`_update_included_label`) passes `n_covered = covered_cells(engine.frame, …)` over each included line's `line.trace_coords(session.site.frames)`. A line whose coordinates raise (a missing grid) is skipped, as preparation skips it. With no frame yet, `n_covered` is 0.

## Global Constraints

- **The core stays numpy-only, with no Qt.** `packages/nsgeo-core/tests/test_boundary.py` and `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py` stay green.
- **Python 3.9 floor for the core:**
  - no `zip(..., strict=...)`;
  - no `match`;
  - no `X | Y` outside annotations;
  - no `dataclass(slots=..., kw_only=...)`.
- **Slices do not change.** On real data, resident slices and coverage are `assert_array_equal` to the dense layout's, and resident still agrees with streaming as today.
- **Streaming is untouched:** `stream_slice` and `plan_line` keep their behaviour.
- **Slots guard their bodies.** Read the module docstrings of `slices_dock.py` and `slices_engine.py` before touching them.
- **Comments and docstrings** follow the file they are in. They say why, and cite `(#113)`. Update `cube.py`'s module docstring: the layout is still z-major, now over covered cells.
- **Shared-worktree safety.** Reviewers and any mutation testing never edit this worktree; they work on a scratch copy. Set `PYTHONDONTWRITEBYTECODE=1` for every test run.
- **Tool versions:** ruff 0.17.1 and mypy 2.4.0 (as CI; already installed in `.venv`).
- **Commits:**
  - End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  - Push each commit to `origin nsgeo-packed-cube` as it is made.
- **Real survey files are never committed.**

## Verification commands (exactly these, from the worktree root)

- **core + pure:** `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider`
- **qgis:** `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:cacheprovider -p no:xonsh` (about 11 minutes; run single files while iterating)
- **lint:** `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- **types:** `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py packages/nsgeo-qgis/nsgeo_qgis/line_edit.py`

## Review Focus

These are the inputs most likely to hurt a user that the design does not spell out. Each is pinned by a test in the task named.

1. **A cube saved by nsgeo 0.1–0.3.** It must load and read the same values. Pinned by Task 1: `test_a_version_1_file_loads_and_reads_the_same`. The coordinator also loads the user's four local Sunnyside `.npz` files by hand (below).
2. **Lines that share cells:** crossing X and Y lines, or a cell wider than the line spacing. The covered set is a union, never a sum. Pinned by Task 1: `test_crossing_lines_match_the_dense_layout`, and Task 2: `test_covered_cells_counts_a_shared_cell_once`.
3. **A rotated grid at UTM magnitude.** The estimate's covered count must equal what binning keeps. Pinned by Task 2: `test_covered_cells_equals_the_cubes_cell_count` (real lines, rotated frame).
4. **The cell size changed, or the lines re-prepared, after the estimate was cached.** The checkbox and status figures must follow. Pinned by Task 2: `test_the_estimate_follows_a_new_cell_size_and_a_new_line_set`.
5. **A damaged version 2 file.** It must raise `CubeStoreError`, never load a wrong picture. Pinned by Task 1: `test_a_damaged_version_2_file_fails_clearly` (parametrised).
