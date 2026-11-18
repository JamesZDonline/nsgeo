# Task 1 report: the prepared volume (core)

Commit 8dd5406 "feat(core): the prepared volume ..." pushed to origin nsgeo-m16.

## Implemented
`packages/nsgeo-core/src/nsgeo/slices/volume.py`: VolumeSettings (frozen, validated, to_dict/from_dict laying valid fields over defaults),
VolumeStopped, fill_levels, depth_axis (Ruling R5, snap within 1e-6), PreparedVolume (frozen; extra non-compared fields filled, source_level, cell, window),
prepare_volume. Order per spec 5.1: finish_slice on the cube level (as slices_engine does), then square unless transform == "amp_square".
RMS window level i = levels i - w//2 .. i + w - w//2 - 1, edge-clamped. The window is summed level by level (not a running cumsum) so a level's
value is independent of the slab (exact `slabs_equal_the_whole`; a cumsum would differ in the last bits). Blur with smooth() per RMS level; blend of two RMS levels
for fractional source levels; trend = moving mean of per-level median over covered, edge-padded; strength = amplitude / trend, NaN where trend <= 0.
Exports added to slices/__init__.py (sorted) and, because test_public_api requires it, rows in packages/nsgeo-core/README.md (not in the brief's file list).

## Tests
13 in tests/test_slices_volume.py (the brief's 8 plus: fill_levels equals finish_slice with idw+smoothing, no-level-after-t0 refused,
layered-velocity slab equality, empty cube refused, depth-axis source check). Whole core suite: 1044 passed, 4 skipped. ruff check, ruff format --check, mypy clean.

Real data strength test: median strength over covered cells ranged 0.884 to 1.080 across depths (all depths within [0.7, 1.3]).

## TDD
RED: with the new exports absent, `pytest tests/test_slices_volume.py` -> "ImportError: cannot import name 'VolumeSettings' from 'nsgeo.slices'" (expected, nothing implemented).
GREEN: same command, 13 passed. One test-design fix on the way: the single Ricker's squared main lobe alone exceeds half the max, so it never had 2 maxima;
the test uses a ringing 400 MHz wavelet (about five cycles, Gaussian window) whose square has several lobes.

## Self-review / concerns
- prepare_volume does one pass computing amplitude for every slab (the cost of the trend), and slab() recomputes; the brief intends this.
- Memory per slab: float64 (slab + RMS window) arrays; with slab_levels=64 on large frames the caller may want a smaller value.
- period window w is rounded to levels; for dz coarser than the period w=1 (RMS degenerates to |value|), acceptable.
- from_dict ignores invalid fields silently (per brief).

# Fix round 1

Commit: "fix(core): faster RMS pass, progress for prepare_volume, real-data volume tests (M16 A task 1)", pushed.

## Changes
1. `_rms_levels`: reads `filled[a-before .. b+after]` once as float64 (edge-padded with np.pad only at cube ends), zeroes `~covered` once, then `total += ext[off:off+n]` for each of w offsets (same summation order). Bit-identical to the old code: checked with `np.array_equal` on a 200x60x50 cube with NaN holes and slab_levels=37, old tree (git archive of the previous commit) vs new.
2. Timings on a 455x320x400 float32 random cube with NaN holes, w=25 (period 2.5 / dz 0.1), cell 0.05, blur 0.1 m:
   - before: prepare_volume 19.3 s; one slab(0, 64) 2.5 s (about 17.9 s for a full pass of 455 levels)
   - after: prepare_volume 12.0 s; one slab(0, 64) 1.34 s (about 9.5 s full pass)
   - isolated `_rms_levels` for one 64-level slab: 1.36 s -> 0.37 s (3.7x). The rest is the Gaussian `smooth` blur (1.19 s per 64 levels, unchanged), which is not in this finding's scope; this is why the whole-pass gain is about 1.7-1.9x, not 7x.
   Peak memory: one slab's float64 window (n + w - 1 levels) plus the float64 total.
3. R8: `prepare_volume(..., *, slab_levels=64, progress=None)`; `progress(done, total)` once per slab of the trend pass; False raises `VolumeStopped`. Tests: `test_prepare_volume_stops_when_progress_says_so` (calls == [(1,4),(2,4)]) and `test_prepare_volume_reports_every_slab`.
4. Real-data tests (marked `needs_real_files`), built from CAMPUS_LINES left bipolar (time_zero, dewow, background_mean, gain_agc, no envelope), squared, binned as `amp_square` on a 110x30 frame (spare rows/columns, so some cells are uncovered), idw fill:
   - `test_real_volume_is_unipolar_and_uncovered_cells_stay_nan` (amp and strength >= 0; finite on covered; NaN off covered; both exist)
   - `test_real_column_through_a_strong_reflection_has_one_hump`: over the 300 columns with the strongest peaks, each window of +-10 levels (about 2 ns) round the column's peak where the squared cube has >= 2 humps (258 columns) must read as exactly 1 hump in slab() amplitude: result 258 of 258. A hump is a maximum above half the window maximum; two maxima merge unless the dip between falls below 80% of the lower one (my first plain-maxima definition counted ripples on a plateau, and a wider +-4 ns window includes neighbouring reflections; both gave only about 1/3 to 1/2 merged, so the metric was refined, not loosened silently).
   - `test_real_slabs_equal_the_whole` (slabs of 23)
   GPS_LINES not used. Synthetic tests kept.

## Results
- test_slices_volume.py: 18 passed. Whole core suite: 1049 passed, 4 skipped. ruff check (one import-sort fix applied), ruff format --check, mypy: clean.
