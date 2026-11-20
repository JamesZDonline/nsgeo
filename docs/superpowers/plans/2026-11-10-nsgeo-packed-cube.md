# Packed Resident Cube (#113) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every code task is written test-first with superpowers:test-driven-development: run the failing test and see it fail before writing any production code.

**Goal:** A resident `SliceCube` holds only the cells that have data, so it takes 3–8× less memory at the cells people use, and slices come out bit-for-bit as they do today.

**Architecture:**
- **Core cube.** `SliceCube` holds one or more `CubeBlock`s. Each block is one direction group's data, packed to the cells it covers: the sorted flat cell ids, a `(nz, n)` float32 mean and an `(n,)` int32 count. `build_cube` always makes exactly one block, for every direction. #47's direction balancing will add more blocks later.
- **One read path.** Everything outside the cube reads through `slice_levels`, `level`, `values_at` and `coverage`. `mean` and `count` stop being attributes, so M15 and M16 never depend on the layout.
- **Saved file.** `.npz` store version 2 writes the packed blocks. Version 1 files (nsgeo 0.1–0.3, dense) still load.
- **Plugin.** The memory estimate counts the covered cells exactly, from the traces' positions: before preparing (from the line placements) and after (from the prepared lines). Residency, the status line, the "Keep the volume in memory (N MB)" checkbox and the over-budget warning all follow.

**Tech Stack:** Python 3, numpy (core); the plugin's `slices_plan.py`, `slices_engine.py` and `ui/slices_dock.py`; pytest on two tiers: core and pure in `.venv`, QGIS in `.venv-qgis`.

**Spec:** issue #113 (body, and the scheduling comment of 2026-11-07), plus the design agreed in chat on 2026-11-10, recorded below. There is no separate design document.

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

## Before Task 1 (coordinator)

Done on 2026-11-10 in `.worktrees/nsgeo-packed-cube` (branch `nsgeo-packed-cube`, off main `ddebce6`):
- both venvs built;
- the top-level real files symlinked into `packages/nsgeo-core/tests/data/local`. `with-dzg/` is left out on purpose, because of #141, which another session is fixing;
- baseline core + pure: 1070 passed, 5 skipped. QGIS: see the ledger.
- ruff and mypy clean.

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

---

### Task 1: The packed cube in the core (layout, binning, reads, store)

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/slices/cube.py` (whole `SliceCube`; add `CubeBlock`)
- Modify: `packages/nsgeo-core/src/nsgeo/slices/binning.py:132-202` (`accumulate`, `build_cube`)
- Modify: `packages/nsgeo-core/src/nsgeo/slices/store.py` (version 2; read version 1)
- Modify: `packages/nsgeo-core/src/nsgeo/slices/__init__.py` (export `CubeBlock`)
- Create: `packages/nsgeo-core/tests/test_slices_cube.py`
- Modify: `packages/nsgeo-core/tests/test_slices_binning.py`, `test_slices_store.py`, `test_slices_display.py`, `test_real_files.py`. These are the 17 places that read `cube.mean` or `cube.count`, or construct `SliceCube(mean=…, count=…)`. Move them to the read path, or to `SliceCube.from_dense` for constructed cubes. Where a test measures `clip.limit(cube.mean)` over every level, use `np.stack([cube.level(k) for k in range(cube.z.nz)])`.

**Interfaces:**
- Produces:
  - `CubeBlock(cells: np.ndarray, mean: np.ndarray, count: np.ndarray, heading_deg: float | None = None)`
  - `SliceCube(frame: CubeFrame, z: ZAxis, blocks: tuple[CubeBlock, ...], provenance: Provenance)`
  - `SliceCube.from_dense(frame, z, mean: np.ndarray, count: np.ndarray, provenance) -> SliceCube` (classmethod)
  - `SliceCube.slice_levels(k0: int, k1: int) -> np.ndarray`: `(ny, nx)` float32, contract unchanged
  - `SliceCube.level(k: int) -> np.ndarray`: `(ny, nx)` float32, equal to `slice_levels(k, k + 1)`
  - `SliceCube.values_at(cells: np.ndarray, k0: int = 0, k1: int | None = None) -> np.ndarray`: `(k1 − k0, len(cells))` float32
  - `SliceCube.coverage() -> np.ndarray`: `(ny, nx)` int32, contract unchanged
  - `SliceCube.nbytes -> int` (property)
  - `build_cube(...)`: signature unchanged; returns one block with `heading_deg=None`
  - `STORE_VERSION = 2`; `save_cube` and `load_cube` signatures unchanged

- [ ] **Step 1: Write the failing cube tests** in `test_slices_cube.py`.
  - Helper `_dense_reference(lines, plans, frame, z)`: today's algorithm, copied into the test. It accumulates a dense `(nz, n_cells)` total and an `(n_cells,)` count, then does `np.divide(total, count, out=np.full_like(total, np.nan), where=count > 0)`. It returns `(mean, count)`. Read a dense slice as `mean[k0:k1].mean(axis=0).reshape(ny, nx)`.
  - `test_build_cube_stores_only_covered_cells`: synthetic lines along X at y = 0.25 + 0.5 i, frame 20 × 25 at 0.2 m.
    ```python
    (block,) = cube.blocks
    np.testing.assert_array_equal(block.cells, np.flatnonzero(dense_count > 0))
    assert block.mean.shape == (z.nz, block.cells.size) and block.mean.dtype == np.float32
    assert block.heading_deg is None
    ```
  - `test_slices_match_the_dense_layout_bit_for_bit` (`needs_real_files`), parametrised over cell `0.2` and `0.05`, and over two frames: axis-aligned, and the rotated UTM grid from `test_binning_at_utm_magnitude_and_a_rotated_azimuth_drops_no_traces`. For every `(k0, k1)` in `WINDOWS`:
    ```python
    np.testing.assert_array_equal(cube.slice_levels(k0, k1), dense_mean[k0:k1].mean(axis=0).reshape(ny, nx))
    np.testing.assert_array_equal(cube.coverage(), dense_count.reshape(ny, nx))
    ```
  - `test_crossing_lines_match_the_dense_layout`: five lines along X and five along Y on one frame, cell 0.75 m on 0.5 m lines. Same two assertions.
  - `test_level_is_a_one_level_window`: `level(k)` equals `slice_levels(k, k + 1)` for k = 0, nz // 2 and nz − 1.
  - `test_values_at_reads_levels_at_chosen_cells`: the cell ids are 3 covered, 2 uncovered and one `−1`.
    ```python
    out = cube.values_at(ids)
    assert out.shape == (z.nz, ids.size) and out.dtype == np.float32
    for k in (0, 7):
        np.testing.assert_array_equal(out[k], np.where(ids >= 0, cube.level(k).ravel()[ids], np.nan))
    assert cube.values_at(ids, 2, 5).shape == (3, ids.size)
    ```
  - `test_values_at_rejects_ids_outside_the_frame`: ids `[frame.n_cells]` and `[-2]` each raise `ValueError`.
  - `test_two_blocks_read_as_the_count_weighted_mean`: build one cube from the outward lines and one from the return lines (alternate lines), and combine their blocks into one `SliceCube`. Compare with a cube built from all the lines: every `slice_levels` window and `values_at` agree within `rtol=1e-6`, with `equal_nan=True`, and `coverage()` is equal. Repeat with the two cubes' blocks overlapping (lines 2 and 3 in both).
  - `test_a_malformed_block_is_refused`, parametrised. Each case raises `ValueError`:
    - unsorted cells;
    - a duplicate cell;
    - a cell equal to `n_cells`;
    - a negative cell;
    - a mean of the wrong shape;
    - a mean whose `nz` differs from `z.nz`;
    - a zero count;
    - `blocks=()`.
  - `test_from_dense_keeps_only_covered_columns`: `from_dense(dense_mean, dense_count)` has `blocks[0].cells == flatnonzero(dense_count > 0)`, and reads equal the dense slices.
  - `test_nbytes_counts_the_packed_arrays`: `cube.nbytes == block.cells.nbytes + block.mean.nbytes + block.count.nbytes`, and for one block it equals `nz·n·4 + n·4 + n·8`.

- [ ] **Step 2: Write the failing store tests** in `test_slices_store.py`. Rework `make_cube` onto `SliceCube.from_dense`.
  - `test_round_trip_preserves_every_read`: after save and load, each block's `cells`, `mean`, `count` and `heading_deg` are equal, and so are `slice_levels(0, nz)`, `level(3)` and `coverage()`. This replaces `test_round_trip_preserves_the_arrays_exactly`.
  - `test_saved_file_holds_only_covered_cells`: `np.load` the file. It has `cells_0`, `mean_0`, `count_0` and `meta`; `mean_0.shape == (nz, n_covered)`; `meta` has `store_version == 2` and `blocks == [{"heading_deg": None}]`.
  - `test_a_two_block_cube_round_trips_with_its_headings`: headings `12.5` and `192.5` survive in order.
  - `test_a_version_1_file_loads_and_reads_the_same`: write the old layout by hand with `np.savez_compressed`: dense `mean` (NaN where `count == 0`), `count`, and `meta` with `store_version: 1` and no `blocks` key. `load_cube` returns one block. Its reads equal the dense slices.
  - `test_a_damaged_version_2_file_fails_clearly`, parametrised. Each case raises `CubeStoreError`:
    - `cells_0` missing;
    - `meta.blocks` listing two blocks for a file with one;
    - unsorted `cells_0`;
    - `cells_0` past `n_cells`;
    - a zero in `count_0`;
    - `mean_0` of the wrong shape;
    - `cells_0` saved as an object array.
  - Keep every existing store test passing. `test_dtypes_survive_the_round_trip` checks int64, float32 and int32 on the block. `test_save_narrows_a_wider_input_dtype` builds its wide cube with float64 and int64 block arrays. `test_load_cube_refuses_a_pickled_object_array` puts the object array in `mean_0`.

- [ ] **Step 3: Run them and see them fail**
  Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_cube.py packages/nsgeo-core/tests/test_slices_store.py -q -p no:cacheprovider`
  Expected: FAIL. `CubeBlock` does not exist, and `SliceCube` has no `blocks`.

- [ ] **Step 4: Implement** `CubeBlock`, the new `SliceCube`, `build_cube`'s packed accumulation (plan call 5) and store version 2 with the version 1 reader (plan call 9). Then move the other test files listed above onto the read path.

- [ ] **Step 5: Run the core suite**
  Run: the core + pure command. Expected: all pass. The 5 skips are unchanged.

- [ ] **Step 6: Measure the redraw cost on real data (record it, no test).** In a scratch script, time 50 calls of `slice_levels(k0, k0 + 23)` followed by `coverage()`. Use the ten real lines on a 40 × 5 m frame at 0.05 m, and compare with the dense reference's `mean[k0:k1].mean(axis=0)`. Put both times in the commit message. **Escalate rather than ship** if packed is slower than 1.5× dense.

- [ ] **Step 7: Lint, types, commit, push**
  ```bash
  git add packages/nsgeo-core
  git commit -m "feat(slices): a resident cube stores only its covered cells (#113)"
  git push -u origin nsgeo-packed-cube
  ```

### Task 2: The memory figure counts the covered cells (core helper, estimate, engine, dock)

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/slices/binning.py` (add `covered_cells`) and `__init__.py` (export it)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py:405-416` (`estimate_memory`; its docstring names the packed layout)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py:502-507` (`estimate`, with the cache from plan call 12), plus each `self._plans = None` (lines 667, 972, 1727) and the `self._lines = …` assignments (665, 880, 1725)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py:1094-1098` (`_update_included_label`)
- Test: `packages/nsgeo-core/tests/test_slices_cube.py`, `packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`

**Interfaces:**
- Consumes: `build_cube`, `SliceCube.blocks` and `SliceCube.nbytes` from Task 1.
- Produces:
  - `covered_cells(frame: CubeFrame, coords: Iterable[np.ndarray]) -> int` (exported from `nsgeo.slices`)
  - `estimate_memory(prepared_samples: int, n_cells: int, nz: int, n_covered: int) -> MemoryEstimate`

- [ ] **Step 1: Write the failing tests**
  - Core, `test_covered_cells_counts_a_shared_cell_once`: two traces in one cell, an X line crossing a Y line, and a trace outside the frame. The result equals the hand count, and the outside trace raises nothing.
  - Core, `test_covered_cells_equals_the_cubes_cell_count` (`needs_real_files`): the ten real lines on the rotated UTM frame at 0.2 m and 0.05 m. `covered_cells(frame, (l.coords for l in lines)) == cube.blocks[0].cells.size`.
  - Pure, replacing the dense assertion at `test_pure_slices_plan.py:90-93`:
    ```python
    est = estimate_memory(prepared_samples=10_000_000, n_cells=90_000, nz=230, n_covered=18_000)
    assert est.cube_bytes == 230 * 18_000 * 4 + 18_000 * 4 + 18_000 * 8
    assert est.weights_bytes == 90_000 * WEIGHT_BYTES_PER_CELL
    ```
    Update the other `estimate_memory` calls in that file (lines 159 and 516) to pass `n_covered`.
  - Pure, `test_the_estimate_matches_the_cube_it_describes`: build a cube from synthetic lines. Then `estimate_memory(0, frame.n_cells, z.nz, covered_cells(frame, coords)).cube_bytes == cube.nbytes`.
  - QGIS engine, `test_the_estimate_follows_a_new_cell_size_and_a_new_line_set` (the `sourced` fixture, prepared):
    - `engine.estimate.cube_bytes == engine.cube().nbytes`;
    - after a new resolution at a different cell, it equals the new cube's `nbytes` and differs from the first;
    - after re-preparing with one line fewer, it equals that cube's `nbytes`.
  - QGIS dock, `test_the_included_label_counts_only_covered_cells` (the `docked` fixture, before preparing but with a frame; set the resolution first if the fixture has none): the label's figure equals `format_bytes(estimate_memory(samples, n_cells, nz, covered).total_bytes)`, where `covered` comes from the session lines' `trace_coords`, and `covered < frame.n_cells`.

- [ ] **Step 2: Run them and see them fail**
  Run: the core + pure command, then `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py -q -p no:cacheprovider -p no:xonsh`
  Expected: FAIL. `covered_cells` cannot be imported, and `estimate_memory` takes three arguments.

- [ ] **Step 3: Implement** `covered_cells` (plan call 10), the new `estimate_memory` (plan call 11), the engine's cached count (plan call 12) and the dock's count before preparing (plan call 13).

- [ ] **Step 4: Run everything**
  Run: core + pure, then the full QGIS tier, lint and types. Expected: all pass, with the QGIS count equal to the baseline plus the new tests.

- [ ] **Step 5: Commit and push**
  ```bash
  git add packages
  git commit -m "feat(slices): the memory figure counts only covered cells (#113)"
  git push
  ```

---

## After Task 2 (coordinator)

- **Hand check on the user's own old cubes** (not committed). Load each `.npz` in `~/nsgeo-m4-check/Sunnyside/`: `grid1cube`, `grid2cube`, `mincurv_cube`, `testcube`. Confirm `coverage()` matches the file's dense `count`, and `slice_levels` matches the dense mean, for three windows each.
- **Whole-branch review**, then deploy to a new QGIS profile `ns_geo_packed` with `scripts/dev_link.py`.
- **Walkthrough** as an Artifact with the `db` capability, on Sunnyside:
  - At 0.05 m in This grid, the "Keep the volume in memory" figure is roughly the packed figure above for that grid.
  - Slices look the same with the checkbox on and off.
  - The Whole site status line at 0.1 m shows a smaller figure than `main`'s.
  - **Save cube…** writes a file that this build saves without error.
- **README roadmap:** on merge, move the #113 row to Done ("next release") and trim item 2 of *Next*.
- **M15's plan, after this merges** (branch `nsgeo-m15-cut-anywhere`, `docs/superpowers/plans/2026-11-06-nsgeo-m15-cut-anywhere.md`): merge main into that branch first. Then:
  - `finish_section` takes the cube and reads `cube.level(k)`, instead of `levels`, "the cube's `mean`, (nz, ny·nx)";
  - the anchor test reads `cube.values_at(cells)[k]`, not `cube.mean[k][cells]`;
  - `finish_slice(cube.mean[k].reshape(ny, nx), …)` becomes `finish_slice(cube.level(k), …)`.

  M16 is not designed yet. Its plan reads the cube the same way.
