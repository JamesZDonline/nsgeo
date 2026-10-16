# Deferred minors and parked items from the task reviews

Each was found by a task review, judged Minor (or carried forward by a ruling), and deliberately
not fixed in the loop. The final whole-branch review triages which must be fixed before merge.

## Task 1

- `_smooth_size`'s docstring says a short transform "would WRAP the convolution and corrupt the
  edges of the slice, SILENTLY". Measured by the reviewer: the corrupted indices are `[0, L-1-M]`
  and the crop starts at `r`, so any `M >= ny+r` is bit-identical and any `M < ny+r` yields a
  short crop that makes `np.divide(..., out=np.full((ny,nx), nan))` RAISE. Silent corruption is
  unreachable; the failure is loud. Keep the `m >= n` test (it pins the correct linear-convolution
  size) but the justification should say "loudly", and the plan's Step 29 amendment inherits the
  same correction.
- `display.py:150-152` cites 2.59 -> 0.87 (a ~3x brightness claim) inherited from an M10
  measurement on other data. This repo's own fixture measures 2.585 -> 1.274 (2.03x) and the real
  corpus 2.718 -> 2.074. Direction right, figures unreproducible here. Cite or drop the decimals.
- The real-data test's strongest assertion mirrors the implementation (recomputes `plan_windows`
  + `np.percentile` and compares). It does kill both named mutants, but it pins the mechanism
  rather than an independent expectation, and the closing median-direction assertion is
  arithmetically implied by the first. After Ruling D the test's real content is "the pipeline
  runs on 4 genuine DZT files and shared_limit != limit(cube.mean) on them" — worth having, less
  than its name suggests.
- `window_times_ns`'s axis-overrun guard (display.py:92) has no test; it is the only ValueError
  path in the module without one.
- FOR TASK 6 AND THE FINAL REVIEW (Ruling I): `to_north_up` drops 15-18% of frame cells at
  rotated azimuths — measured on a 23x19 frame at cell=0.1, 437/437 cells kept at azimuth 0, 366
  at 45 deg, 360 at 315 deg. This follows from an output pixel size equal to the cell size under
  nearest neighbour, not from nearest neighbour itself. Consequence for the exporter: an isolated
  one-cell anomaly on a rotated grid has roughly a one-in-six chance of not appearing in the
  exported GeoTIFF. Largely mitigated in practice because the export path is slice -> fill ->
  to_north_up and the fill at spec 6.4's default radius has already spread any isolated cell, so
  it bites hardest at radius 0. A half-cell output pitch would remove it at 4x the pixel count.
  Task 6 owns the exporter and is where this is decided.
- Reviewer performance note, not a defect: a 39-band export repeats the `cell_index` solve per
  band (~1.4 s total on a 400x300x400 cube). Task 6 could hoist the gather indices out of the
  per-band loop, since the frame does not change between bands.

### Task 1 — resolved in fix round 3 rather than deferred (Ruling J)
The four Minors from the round-2 re-review were all fixed: the false equal-weight sentence in
`shared_limit`'s docstring (now states the non-monotonicity with its measured numbers), the
self-contradicted plan amendment at Step 17, the real-data cross-check's now-non-independent
comment, and the window-count assertion (strengthened to pin tail identity; controller verified
it kills both an overlapping and a duplicate tail). Nothing from Task 1 is carried to the final
review EXCEPT the five items above this section, of which the load-bearing one is the
`to_north_up` rotated-azimuth cell loss carried into Task 6's dispatch.
