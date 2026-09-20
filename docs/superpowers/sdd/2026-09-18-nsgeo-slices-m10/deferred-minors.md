# Deferred minors and parked items from the six task reviews

Each was found by a task review, judged Minor (or noted), and deliberately not fixed in the loop.
Triage which must be fixed before merge.

Task 1: minor (deferred): `margin` parameter of for_points has no test coverage (frame.py:118,137-140)
Task 1: minor (deferred): error branches untested — to_local shape guard (65-66), for_grid cell
  guard (102-103), from_range ordering guard (189-190), level_range thickness guard (200-201),
  __post_init__ nx/ny guard (47-48)
Task 1: minor (deferred): level_range clamps top and end differently (overlap vs one level);
  undocumented and unpinned by any test (frame.py:202-205)

Ruling F: fix `from_range` even though the brief mandates the fragile expression. Why: the
--
Task 1: minor (deferred): the multiplier 8 in `tol` (frame.py:98) is empirically calibrated from
  a sweep topping out at 2.24 ulps, but a term-by-term error walk of the for_points -> to_local
  round trip admits ~8-10 ulps under adversarial rounding. tol at UTM scale is 8e-9 m, seven
  orders below the smallest realistic cell, so 32 or 64 would cost nothing and remove the
--
Task 1: minor (deferred): `tol` is sized from the query point's magnitude, not the frame origin's
  (frame.py:98). Unreachable for GPR-scale cubes; would matter only for a frame spanning ~1e6 m.
Task 1: minor (deferred): frame.py:95-96 relies on out-of-range float->int conversion yielding
  INT_MIN rather than wrapping, for points astronomically far from the frame. Pre-existing.
Task 1: complete (commits 493a15e..60e6e2d, review clean)

--
Task 2: minor (deferred): analytic_envelope's docstring states four benchmark figures
  (2.2x faster, ~1.3% interior, ~13% last rows, reflect-padding ~2.6%) that nothing in the
  repo substantiates; carried verbatim from my plan. Cite or drop the decimal precision.
Task 2: minor (deferred): a zero-row array slips past the `ndim != 2` guard (amplitude.py:102-105)
  into numpy's own FFT error. Not reachable from a real Radargram.
Task 2: minor (deferred): stack.output_unipolar is conservative — [amp_abs, gain_agc] reports
  False though AGC preserves unipolarity. Safe direction; Task 3's author should know.

Ruling I: the Important finding is plan-mandated (the 13 tests are my brief's, verbatim) and I
--
Task 3: minor (deferred): UnipolarClip's validation and subsampling untested — a UnipolarClip
  with __post_init__ deleted passes all four new clip tests; the max_samples stride branch
  (render.py:99-100) is never exercised. The file already tests both for PercentileClip.
Task 3: minor (deferred): to_index8_unipolar's "limit must be positive" guard untested (render.py:219)
Task 3: minor (deferred): _amp_heat has no endpoint assertions — a channel-order mutant
  (blue->cyan->white) passes every test in the file (render.py:138-145)
Task 3: minor (deferred): UnipolarClip.limit filters on isfinite but nothing distinguishes that
  from ~isnan; with +inf the two diverge and to_index8_unipolar then maps everything to 0
Task 3: minor (deferred): posinf/neginf in nan_to_num are dead against the following np.clip (render.py:224)
Task 3: minor (deferred): docstring typo "index 8" should be "an 8-bit index" (render.py:217)
Task 3: minor (deferred): test_render.py now mixes module-qualified and bare import styles
Task 3: fix round 1/5 dispatched (resumed implementer a342bacce89350f9f, 3 findings)
Task 3: fix round 1/5 implemented — commits 801dbbc..d21d22f (pushed). 374 core passed / 2 skipped.
  Implementer reported the nsgeo-qgis test as unrunnable (no qgis.core in .venv). THAT WAS WRONG
--
Task 3: minor (deferred): task-3-brief.md:14 still carries the stale Interfaces line "alpha 0
  where the input is not finite"; the code and docstring are now correct, the brief text is not.
  The PLAN has the same stale line and should be corrected before the plan is treated as history.
Task 3: complete (commits 7d43e01..d21d22f, review clean)
--
Task 4: minor (deferred): SliceCube/PreparedLine/LinePlan are frozen dataclasses holding ndarrays,
  so __eq__ raises for distinct-but-equal instances and all three are unhashable; Provenance is
  hashable only while steps is empty and velocity is None. Add eq=False if anything caches them.
Task 4: minor (deferred): resample_window materialises two full-width temporaries then subsets
  (binning.py:112-113); np.ix_ does it in one pass. ~two extra 4 MB copies per line per build.
Task 4: minor (deferred): test_provenance_round_trips_through_a_dict covers only the empty case,
  so the dict-copying at cube.py:53,64 and the velocity path are unverified.
Task 4: minor (deferred): all 13 tests use origin=(0,0), cell=1.0. The reviewer confirmed no
  magnitude hazard recurs here because the binner delegates all coordinate arithmetic to
  cell_index, but nothing committed pins the composition.
Task 4: fix round 1/5 dispatched (resumed implementer a46f24d12fe31b49b, 2 findings + 2 promoted)
--
Task 4: minor (deferred): frame.py:105 `position = local / self.cell` runs before the finite
  check, so ~1e308 coordinates raise an overflow warning under simplefilter("error"). Result is
  still deterministically -1; only the no-warning property stops at ~DBL_MAX * cell.
Task 4: minor (deferred): frame.py:69 to_local warns on +-inf at axis-aligned azimuths (inf * -0.0
  in the matmul). Result -1 in every case; pre-existing, not a regression.
Task 4: minor (deferred): the two new binning tests use the toy 1.0 m frame; both discriminate
  their mutants there, but finding 1's most vivid form (UTM, cell 0.05) lives only in the
  implementer's ad hoc script, not the suite.
Note, NOT a finding — correcting the re-reviewer: it suggested that at UTM magnitude with
  cell=0.05, float granularity can collapse traces 0.05 m apart into one cell. That explanation
  is wrong. One ulp at easting 5e5 is ~5.8e-11 m, nine orders below a 0.05 m spacing. Its
  observation (three traces landing in two cells) is ordinary boundary alignment, not precision
--
Task 5: minor (deferred): fill's radius_cells==0 fast path gates on counts > 0 while every r>=1
  path gates on den >= min_count; coincide at the default, diverge with a caller-supplied value.
Task 5: minor (deferred): fill.py:64 a NaN value with non-zero count contributes 0 to the
  numerator but full weight to the denominator, biasing toward zero. Unreachable while cube.py
  guarantees NaN iff count 0, but silent if a preset ever emits NaN samples.
Task 5: minor (deferred): stream_slice's len(lines)!=len(plans) guard has no test (nor does
  build_cube's copy); the window guard is exercised only at k0==k1, not k0<0 or k1>z.nz;
  min_count is never passed a non-default value.
Task 5: minor (deferred): fill builds three FFTs per call with no next-fast-size rounding and no
  cached kernel spectrum — 53 ms at 600x600 r=10, 327 ms at 1021x1019 r=10. The M11 radius
  slider will want debouncing or smooth-size padding.
Task 5: noted, not a defect: stream_slice's three-line overlap with accumulate is justified
  duplication (different accumulator ranks, pinned against each other by the property test).
  A future edit to accumulate needs mirroring there.
Task 5: fix round 1/5 dispatched (resumed implementer a514ef517d41a7f71, 2 findings + 2 promoted)
--
Task 5: minor (deferred): the new r=1 fill test does not pin the "itself included" half of its
  own docstring — a centre-excluded kernel (kernel[r,r]=0) passes all 10 fill tests. Whether a
  cell's own value participates in its smoothed value is still undecided for M11's slider.
Task 5: minor (deferred): make_survey(n_lines=N) now returns N+1 lines and appends the repeat
  pass unconditionally at collide_with=1's y, so make_survey(n_lines=1) would not collide.
  No caller passes n_lines today.
Task 5: FOR THE FINAL REVIEW — a genuine product-level hazard, pre-existing and symmetric: the
  new guard catches a LENGTH mismatch only. A plan built against a z axis with the same nz but a
  different t0_ns/dz_ns passes it and resamples at the wrong times. build_cube has the identical
  hole (accumulate takes its level count from total.shape[0]), so the two residency paths still
--
Task 6: minor (deferred): save_cube has no documented error contract — a read-only directory or
  full disk raises raw OSError, and a non-JSON-serialisable value in Provenance.velocity/steps
  (e.g. np.float32, not a float subclass) raises raw TypeError.
Task 6: fix round 1/5 dispatched (resumed implementer ac4f0101b810cf80a, 3 findings + 2 promoted)
--
Task 6: minor (deferred): store.py:113 passes frame_doc["crs"] through unconverted, so a cube
  with "crs": null loads with frame.crs is None and no complaint; CubeFrame does not validate it.
Task 6: noted, not a defect: with the widened tuple a future genuine TypeError/KeyError inside
  Provenance.from_dict or SliceCube.__post_init__ would be reported as a corrupt file. Accepted
  cost of what finding 1 required; the traceback survives via `from exc` chaining.
Task 6: fix round 2/5 dispatched (resumed implementer ac4f0101b810cf80a, 2 new Important + 1 minor)
--
Task 6: minor (deferred) FLAG TO FINAL REVIEW: test_slices_store.py:176 is a VACUOUS assertion —
  `assert not np.array_equal(back_v1.mean, back_v2.mean)` cannot fail, because mean contains NaN
  and np.array_equal without equal_nan=True returns False for any NaN-bearing array (confirmed:
  np.array_equal(a.mean, a.mean) is False). It would pass even if the two cubes were byte-
--
Task 6: minor (deferred): store.py:45, `.npz` alone normalises to `.npz.npz` — pathlib treats a
  leading dot as a stem, not a suffix. Save and load agree, so no data risk; the docstring's
  claim to mirror numpy exactly is wrong for that one hidden-file name.
Task 6: minor (deferred): store.py:91, `if not path.exists()` sits outside the try, so a stat
  failing with EACCES on an unsearchable parent escapes as raw PermissionError.
Task 6: minor (deferred): save_cube stays asymmetric with the now-guarded load_cube —
  save_cube(cube, "") raises raw ValueError, a read-only directory raises raw PermissionError.
Task 6: complete (commits f3473ee..9ea8dd7, review clean)

