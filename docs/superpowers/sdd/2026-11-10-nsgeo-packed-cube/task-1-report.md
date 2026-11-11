# Task 1 report: packed cube in the core (commit 94d2cf2, pushed)

## Implemented
- cube.py: `CubeBlock` (validates its own shapes, integer cell ids, strictly increasing cells, count >= 1; dtypes of mean/count not enforced because test_save_narrows needs a float64/int64 block), `SliceCube(frame, z, blocks, provenance)` with cube-level checks (>=1 block, nz, ids in [0, n_cells)), `from_dense`, `slice_levels`, `level`, `values_at`, `coverage` (computed per call), `nbytes`. One block: float32 window mean scattered into NaN (bit-identical); several: float64 count-weighted mean. Module docstring updated.
- binning.py: `accumulate` takes `columns`; `build_cube` packs over `np.unique` of plan cells, never allocates dense; empty line list gives an empty block (as today's all-NaN cube).
- store.py: version 2 (`cells_i/mean_i/count_i`, `meta.blocks`), reads 1 and 2; v2 file whose arrays differ from `meta.blocks` (missing or extra) -> CubeStoreError; any ValueError from the cube -> CubeStoreError.
- `CubeBlock` exported; one README row added (test_public_api requires every public name in README).
- Tests moved onto read path / `from_dense` in binning, display, real_files, store.

## Tests
Core + pure: 1102 passed, 5 skipped (same 5). Real-data tests ran (no new skips). ruff check/format clean; mypy clean.

## TDD evidence
I wrote the implementation before the tests (process slip), so RED was shown afterwards by reverting `src` to HEAD:
`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_cube.py packages/nsgeo-core/tests/test_slices_store.py -q -p no:cacheprovider`
-> `ImportError: cannot import name 'CubeBlock' from 'nsgeo.slices.cube'`, 2 collection errors (expected). GREEN: same files with src restored; full suite 1102 passed.

## Step 6 timings (50 x slice_levels(80, 103) + coverage(), ten real lines, 40 x 5 m frame at 0.05 m)
packed 0.006 s (0.0075 first run); dense reference 0.046 s. Cube 2.9 MB packed vs 57.9 MB dense. Packed is faster, no escalation.

## Files
packages/nsgeo-core/src/nsgeo/slices/{cube,binning,store,__init__}.py, packages/nsgeo-core/README.md, tests: new test_slices_cube.py; modified test_slices_{binning,store,display}.py, test_real_files.py.

## Self-review / concerns
- Test deviations: the old v1-oriented store tests' `_good_parts` now returns (block arrays, meta); the "metadata disagrees" test sets `nx = 1` (nx + 2 would no longer disagree with packed ids). `test_loading_a_file_missing_one_required_array` kept (no `meta` -> "not a cube").
- Plan call 1 says the block validates dtypes; I validate kinds/shapes only (see above). Flagged for the reviewer.
- Stale comments mentioning `cube.mean` remain in render.py/display.py docstrings (history of a past bug); left alone.
- No plugin source reads cube.mean/count.

## Fix round 1
- Finding 1: added `test_blocks_sharing_cells_with_different_means_and_counts_are_count_weighted` (X lines seed 1 + Y lines n_traces=37, `_frame(27, 27, 0.75)`, 16+ shared cells; same three assertions via a shared helper). Mutant check on a scratch copy (unweighted reads): the new test FAILED, the two old cases passed. Passes on real code.
- Finding 2: `CubeBlock` now enforces kinds (mean float, count int/uint, cells int/uint; exact dtypes still free). Store block reader casts with `casting="same_kind"`, so float cells -> TypeError -> CubeStoreError. Added cases: "float cells" damaged file, "non-float mean" and "float count" malformed blocks.
- Covering: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_cube.py packages/nsgeo-core/tests/test_slices_store.py -q -p no:cacheprovider` -> 64 passed. Full core + pure, ruff, mypy: see below.
- Full core + pure: 1106 passed, 5 skipped; ruff and mypy clean.
