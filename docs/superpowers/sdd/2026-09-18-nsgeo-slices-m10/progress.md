# SDD ledger — plan: docs/superpowers/plans/2026-09-18-nsgeo-slices-m10.md

Spec: docs/superpowers/specs/2026-09-18-nsgeo-slices-design.md (present, read)
Worktree: /home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m10
Branch: nsgeo-m10, based on docs/slices-design @ 493a15e
Venv: ./.venv (worktree-local, editable install of THIS worktree's nsgeo-core)
Real data: packages/nsgeo-core/tests/data/local/ symlinked from the main checkout (22 files)
Baseline: 317 passed, 2 skipped; ruff clean; mypy clean.

Test commands (from the worktree root):
  ./.venv/bin/python -m pytest packages/nsgeo-core/tests -q
  ./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
  ./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src

## Pre-flight scan

### Cross-task rows (every pair sharing a file or an interface)

| Pair | Produced | Consumed | Found |
|---|---|---|---|
| T1 -> T4 | `CubeFrame` (`cell_index` flat `iy*nx+ix`, `-1` outside), `ZAxis.level_range` half-open | `plan_line`, `build_cube` | agree |
| T1 -> T5 | same two objects | `stream_slice`, `fill` | agree |
| T1 -> T6 | `CubeFrame`/`ZAxis` frozen fields | `store._meta` serialises them | agree |
| T4 -> T5 | `binning.py` module, `resample_window`, `accumulate`, `LinePlan` | `stream_slice` appended to same file, reuses `resample_window` (plan:1724) | agree |
| T4 -> T6 | `SliceCube`, `Provenance.to_dict/from_dict` | `save_cube`/`load_cube` | agree |
| T2 -> T3 | `StepStack.output_unipolar` | T3 declares "Consumes: nothing new" | agree — the two only meet in M11 |
| T1,T4,T5,T6 | `slices/__init__.py` | created T1, modified T4/T5/T6 | strictly sequential, no conflict |
| T3 -> existing plugin | `colormap_names(unipolar=None)` | `nsgeo_qgis/ui/profile_dock.py:153` calls `colormap_names()` | compatible — new arg defaults |

### Self-consistency rows (each task's tests against its own code)

| Task | Found |
|---|---|
| T1 | tests and impl agree. Impl annotates with `typing.Tuple` -> Finding A |
| T2 | tests and impl agree; `register` reads `cls.name`, which `_NoParams` subclasses set. Impl uses `Dict`/`Tuple` -> Finding A |
| T3 | Interfaces and impl agree. New test `test_every_colormap_is_a_valid_table` duplicates the existing `test_every_colormap_is_a_256_by_3_uint8_table` in the same file -> Finding C |
| T4 | tests and impl agree. `slice_extent` (plan:1470) is defined and called nowhere -> Finding B. Impl uses `Tuple`/`Dict` -> Finding A |
| T5 | tests and impl agree |
| T6 | Interfaces says `path: str | Path`; impl writes `Union[str, Path]` -> Finding A (the plan contradicts itself here) |

### Findings and rulings

Ruling A: the plan's code samples annotate with `typing.Tuple`/`Dict`/`Union` in Tasks 1, 2, 4 and 6. Implementers must write `tuple`/`dict`/`X | Y` instead, keeping everything else verbatim. Why: the plan's own Global Constraints require `ruff check .` to pass with `UP` selected, and `typing.Tuple`/`Dict`/`Union` raise UP035/UP006/UP007 (verified by running ruff on a sample); every module carries `from __future__ import annotations`, so the lowercase forms are strings at runtime and safe on the 3.9 floor; and the existing codebase already annotates this way (`render.py:102 dict[str, np.ndarray]`, `base.py:137`, `stack.py:26 Radargram | None`). Task 3 and Task 6's own Interfaces block already use the modern forms, so the plan contradicts itself and this resolves it. Cost if wrong: annotation style only — nothing in this plan evaluates annotations at runtime, so a mistake here is cosmetic and reversible with a find-and-replace.

Ruling B: drop `slice_extent` from Task 4. Why: nothing in the plan, the spec, or the task's own Interfaces block calls it — it is dead code the plan mandates, and the review rubric treats that as a defect. Cost if wrong: M11 needs a four-line helper computing a frame's world-space bounding box and writes it then, with a caller and a test.

Ruling C: drop Task 3's `test_every_colormap_is_a_valid_table`. Why: `tests/test_render.py:94` already asserts exactly this — `for name in colormap_names(): lut.shape == (256, 3) and lut.dtype == np.uint8` — and Task 3 appends to that same file, so the plan would land two identical loops. The existing test covers the three new tables automatically, because Task 3 adds them to `_COLORMAPS`. Cost if wrong: none; the coverage is unchanged.

Ruling D: work in a manually created worktree (`.worktrees/nsgeo-m10`) rather than the harness's `EnterWorktree`. Why: the branch must be based on `docs/slices-design` so the spec and plan travel with the code, and `EnterWorktree` branches from origin/main or HEAD into `.claude/worktrees/`, against this repo's established `.worktrees/` convention. Cost if wrong: the harness does not auto-clean the worktree; I remove it by hand at finish.

Ruling E: give the worktree its own `.venv`. Why: the main checkout's `.venv` has `nsgeo` editable-installed against the MAIN checkout's `src`, so running pytest here would silently have tested main's code, not the worktree's (verified). Cost if wrong: ~200 MB of disk, deleted with the worktree.

## Progress

Task 1: dispatched (sonnet, agent a11fba1adddf2e741), BASE 493a15e
Task 1: implementer DONE_WITH_CONCERNS, commit 265d8e6 (pushed to origin/nsgeo-m10).
  16/16 new tests; full suite 333 passed / 2 skipped; ruff + mypy clean.
  Implementer concerns: (a) added `eps = 1e-9 * cell` in `cell_index` to fix a real
  floating-point boundary bug the brief's own test caught — a `for_points`-sized frame
  could exclude the point that defined its own edge at non-axis-aligned azimuths;
  (b) left the brief's stray `nextafter` comment in `for_points` (frame.py:141-142),
  which names a function the code never calls.
Task 1: task review dispatched (opus, agent afe4b3e8d32beb80a), diff 493a15e..265d8e6
Task 1: review verdict — spec COMPLIANT on interfaces, quality NEEDS FIXES.
  Critical 1: `eps = 1e-9 * cell` in cell_index is scaled to cell size; the round-off it
    absorbs is scaled to world-coordinate magnitude. Reproduced independently at UTM
    magnitudes: 25/300 combos drop a defining point at cell 0.5, 133/300 at 0.1,
    142/300 at 0.05. Also a NEW false negative: a point at 4.0-1e-12 inside a
    nx=4 cell=1.0 frame now returns -1.
  Important 2: `ZAxis.from_range` drops the last level on 335/1350 exactly-divisible
    windows (verified with Fraction); e.g. (0, 0.3, 0.1) -> nz=3, should be 4. The
    brief's own test picks (0, 50.0, 0.5), which is exactly representable, so it never
    exercises the contract its name asserts.
  Important 3: stale `nextafter` comment at frame.py:142-143 misattributes the `+1`.
Task 1: minor (deferred): `margin` parameter of for_points has no test coverage (frame.py:118,137-140)
Task 1: minor (deferred): error branches untested — to_local shape guard (65-66), for_grid cell
  guard (102-103), from_range ordering guard (189-190), level_range thickness guard (200-201),
  __post_init__ nx/ny guard (47-48)
Task 1: minor (deferred): level_range clamps top and end differently (overlap vs one level);
  undocumented and unpinned by any test (frame.py:202-205)

Ruling F: fix `from_range` even though the brief mandates the fragile expression. Why: the
  method's name and its test's name both assert the end is included, and the spec's ZAxis is
  the axis that covers the requested range; a 25% failure rate against its own contract is
  not shippable. Cost if wrong: an axis one level longer than intended when the division is
  genuinely ambiguous — one extra level at the bottom of a cube.
Ruling G: the Critical-1 fix must not change `CubeFrame`'s field list, which closes the
  reviewer's "store the local origin offset" option. Why: Task 4's binner consumes those
  fields and Task 6's .npz writer serialises them; a numerical fix should not ripple into
  two later tasks. The implementer picks the mechanism subject to five stated properties.
  Cost if wrong: if no in-place mechanism satisfies all five, the field change comes back
  in fix round 2 and Tasks 4 and 6 inherit it — visible, not silent.
Ruling H: fix the stale `nextafter` comment now rather than deferring it as cosmetic. Why:
  it names a mechanism absent from the code and misattributes the `+1`, so it actively
  misleads. Cost if wrong: none; it is two lines of prose.

Task 1: fix round 1/5 dispatched (resumed implementer a11fba1adddf2e741, 3 findings)
Task 1: fix round 1/5 implemented — commit 60e6e2d (pushed). Mechanism chosen: floor as before
  with no upfront nudge, then correct only results that land at -1 or at nx/ny, using
  tol = 8 * float eps * max(1, |world|) computed per point. No CubeFrame field added.
  from_range now snaps via math.isclose(span, round(span), rel_tol=1e-9).
  19/19 focused, full suite 336 passed / 2 skipped, ruff + mypy clean.
Task 1: scoped re-review dispatched (opus, agent a58fe067b84918ed3), diff 265d8e6..60e6e2d
Task 1: fix round 1/5 (3 addressed, 0 open; commits 265d8e6..60e6e2d). Re-reviewer independently
  swept 4 coordinate offsets x 120 seeds x 9 azimuths at cell 0.05: worst boundary excursion
  2.24 ulps against a tolerance of 8, zero drops; and confirmed the new UTM test is not vacuous
  (564 of its 900 combinations actually exercise the correction path).
Task 1: minor (deferred): the multiplier 8 in `tol` (frame.py:98) is empirically calibrated from
  a sweep topping out at 2.24 ulps, but a term-by-term error walk of the for_points -> to_local
  round trip admits ~8-10 ulps under adversarial rounding. tol at UTM scale is 8e-9 m, seven
  orders below the smallest realistic cell, so 32 or 64 would cost nothing and remove the
  reliance on the sweep. FLAG THIS ONE TO THE FINAL REVIEW: it guards the bug that cost two rounds.
Task 1: minor (deferred): `tol` is sized from the query point's magnitude, not the frame origin's
  (frame.py:98). Unreachable for GPR-scale cubes; would matter only for a frame spanning ~1e6 m.
Task 1: minor (deferred): frame.py:95-96 relies on out-of-range float->int conversion yielding
  INT_MIN rather than wrapping, for points astronomically far from the frame. Pre-existing.
Task 1: complete (commits 493a15e..60e6e2d, review clean)

Task 2: dispatched (sonnet), BASE 60e6e2d
Task 2: implementer DONE, commit 00dddbc (pushed). 361 passed / 2 skipped (baseline 336/2),
  ruff + mypy clean. One unbriefed change: extended test_steps_background.py's _STEP_PARAMS
  table (a pre-existing test enumerating every registered step) to cover the three new names.
Task 2: task review dispatched (opus, agent ae5cffd70bebbbdca), diff 60e6e2d..00dddbc
Task 2: review verdict — spec COMPLIANT, quality APPROVED, one Important finding.
  Important: the envelope's ODD-length branch (amplitude.py:112, the line the 463-sample
    production data executes) has no correctness assertion. The reviewer built the plausible
    off-by-one (`weights[1 : n//2]` for odd n, dropping the top positive bin) and all 13 tests
    in the file pass against it.
  Both of the reviewer's ⚠️ items resolved by me: Co-Authored-By trailer present on all three
    commits (checked with git log --format trailers); 361 passed / 2 skipped, ruff clean,
    ruff format clean (97 files), mypy clean (25 files) — re-run, not taken on report.
Task 2: minor (deferred): analytic_envelope's docstring states four benchmark figures
  (2.2x faster, ~1.3% interior, ~13% last rows, reflect-padding ~2.6%) that nothing in the
  repo substantiates; carried verbatim from my plan. Cite or drop the decimal precision.
Task 2: minor (deferred): a zero-row array slips past the `ndim != 2` guard (amplitude.py:102-105)
  into numpy's own FFT error. Not reachable from a real Radargram.
Task 2: minor (deferred): stack.output_unipolar is conservative — [amp_abs, gain_agc] reports
  False though AGC preserves unipolarity. Safe direction; Task 3's author should know.

Ruling I: the Important finding is plan-mandated (the 13 tests are my brief's, verbatim) and I
  am ruling that it be fixed. Why: the spec's whole argument for the amplitude transforms is
  that slicing a bipolar trace cancels, so the transform is the load-bearing step; leaving its
  production code path numerically unpinned is the same defect that cost Task 1 two rounds.
  Cost if wrong: three extra tests on a module that is already correct.
Ruling J: the reviewer's proposed test is INSUFFICIENT and must not be added as written. I ran
  it: for n=463 the correct and off-by-one weightings differ at exactly one bin, index 231 =
  (n-1)/2, so a sinusoid at the reviewer's k=37 gives max-dev 0.000 against the wrong variant —
  measured, alongside k=100 and k=230 which also fail to discriminate; only k=231 gives 3.000.
  Replaced with a top-bin sinusoid, a Parseval-style energy identity over both parities
  (2.7e-15 correct vs 1.8e-2 wrong, measured), and the even-branch Nyquist pin. Cost if wrong:
  a test that is stricter than needed; the identity is exact, so it cannot be flaky.
Task 2: fix round 1/5 dispatched (resumed implementer a8ac50698e49e059e, 1 finding + corrected fix)
Task 2: fix round 1/5 implemented — commit 7d43e01 (pushed), tests only, implementation untouched.
  364 passed / 2 skipped, ruff + mypy clean.
  CORRECTION TO RULING J, raised by the implementer and confirmed by me: the energy identity I
  prescribed, mean(|z|^2) == 2*mean(x^2) - mean(x)^2, is wrong for EVEN n — the Nyquist bin is
  weighted 1, not 2, so the identity needs that term subtracted. I had verified it only on odd
  length (463) and generalised without checking. Measured on default_rng(2).standard_normal((512,3)):
  my form differs from the correct implementation by 9.09e-03; the Nyquist-corrected form matches
  to 1.78e-15. On n=463 both agree to 2.67e-15. The implementer derived and used the corrected
  form. My prescription was the defect, not their work.
Task 2: scoped re-review dispatched (sonnet, agent abce82bba99620262), diff 00dddbc..7d43e01
Task 2: fix round 1/5 (1 addressed, 0 open; commits 00dddbc..7d43e01). Re-reviewer rebuilt both
  wrong variants from source and ran each new test's assertion logic against correct/odd-bug/
  even-bug, reproducing every number from scratch: top-bin sinusoid fails the odd bug at dev
  3.000; the energy identity fails the odd bug at n=463 (0.01796) and the even bug at n=512
  (0.02727) while each length alone passes the other; the Nyquist pin fails the even bug at 2.0
  vs 1.0. It also independently reproduced my own flawed identity failing correct code at 9.09e-03.
Task 2: complete (commits 60e6e2d..7d43e01, review clean)

Task 3: dispatched (sonnet), BASE 7d43e01
Task 3: implementer DONE, commit 801dbbc (pushed). 373 passed / 2 skipped, ruff + mypy clean.
  All three prescribed mutants confirmed to fail their targeted tests.
Task 3: review verdict — quality NEEDS FIXES. Three Important findings.
  Important 1: to_rgba8's bipolar path derives alpha from isfinite, contradicting its own
    docstring and the task constraint. Worse, the bipolar test compares only rgba[...,:3] and
    the only alpha-asserting test runs unipolar=True, so an implementation returning alpha 0
    everywhere on the bipolar path — an invisible radargram — passes all eight new tests and
    the whole existing suite. This is the fourth mutant nobody had considered.
  Important 2 (plan-mandated): _amp_grey is byte-for-byte identical to _grey; amp_black_high
    and grey_black_high are array_equal, likewise the white pair.
  Important 3 (plan-mandated consequence): colormap_names() with no argument now returns all
    six, so the QGIS radargram combo silently gains three entries — two pixel-identical to
    existing ones and amp_heat, a unipolar table on bipolar data.

Ruling K: my plan contradicts itself on to_rgba8's bipolar alpha — the Interfaces block says
  "alpha 0 where the input is not finite" flatly, the docstring says the bipolar path is fully
  opaque. The DOCSTRING is right. Why: to_index8 deliberately maps NaN to the neutral middle of
  the table so an AGC divide-by-zero never reads as a feature; making those samples transparent
  would punch a transparent stripe through the radargram, which is worse than neutral grey. A
  radargram has no nodata, a slice does — that distinction is the entire reason `unipolar` is a
  parameter. Cost if wrong: a radargram with non-finite samples paints them neutral-opaque
  instead of transparent, which is the behaviour it has today on the to_rgb8 path.
Ruling L: keep both amp_* grey names and their UNIPOLAR_COLORMAPS membership, but delete the
  duplicate _amp_grey and alias the entries to _grey. Why: the names are not redundant even
  though the bytes are — membership in that frozenset decides which tables a slice is offered.
  Cost if wrong: if the amp greys should ever diverge from the radargram greys, the alias has
  to be split back out; one function, no data lost.
Ruling M: fix the profile_dock regression HERE, overruling the reviewer's "defer to M11". Why:
  a branch should not merge carrying a user-visible regression scheduled for a later milestone,
  and the fix is one call site plus its assertion. Cost if wrong: M10 touches one line of
  nsgeo-qgis, against a plan that said "no UI" — visible in the diff, trivially revertible.
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
  and I closed it myself: system python3 HAS QGIS 3.44.7, and the plugin conftest puts the
  worktree's own core source on sys.path, so no nsgeo install is needed. Created .venv-qgis
  (python3 -m venv --system-site-packages + pip install pytest) and ran the whole plugin suite:
    QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
    -> 373 passed in 87s
  The `-p no:xonsh` is required: a system-site-packages xonsh pytest plugin uses the removed
  `path` hookimpl argument and aborts collection otherwise.
  USE THIS FOR EVERY REMAINING TASK that touches nsgeo-qgis.

## Carry-forward established mid-run (from the project's recorded environment facts)

- The plan's Global Constraints give a mypy command narrower than CI's. CI runs it over core PLUS
  two numpy-only plugin modules. Use the CI form from here on; verified clean at d21d22f:
    ./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
      packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
      packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
    -> Success, 27 source files
- WARNING for the final review: a green LOCAL qgis suite does not imply a green CI plugin-qgis job.
  An exception raised in a slot Qt invoked from C++ prints to stderr and the test reports PASSED
  under local PyQt 5.15.10, while the qgis/qgis:ltr container routes it to qFatal() and aborts the
  whole job. This previously hid two broken tests for nine CI runs against a local "290 passed".
  My 373-passed plugin run above is subject to exactly this. Before merge, re-run the qgis tier
  with an autouse fixture that snapshots sys.excepthook AND sys.unraisablehook counts and fails
  any test that grew them.
- There are TWO boundary test files totalling 6 tests: packages/nsgeo-core/tests/test_boundary.py (2)
  and packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py (4). Never report only one.
Task 3: fix round 1/5 (3 addressed, 0 open; commits 801dbbc..d21d22f). Re-reviewer independently
  rebuilt the all-alpha-0 bipolar mutant as a pytest plugin and confirmed the amended tests kill
  it (2 failed / 32 passed mutated, 34 passed clean), and ran the plugin tier itself
  (test_plugin_profile_dock.py 27 passed) including a discrimination check on the new combo test,
  superseding the implementer's "verified by reading".
Task 3: minor (deferred): task-3-brief.md:14 still carries the stale Interfaces line "alpha 0
  where the input is not finite"; the code and docstring are now correct, the brief text is not.
  The PLAN has the same stale line and should be corrected before the plan is treated as history.
Task 3: complete (commits 7d43e01..d21d22f, review clean)

Task 4: dispatched (sonnet), BASE d21d22f
Task 4: implementer DONE, commit a54116d (pushed). 387 passed / 2 skipped, ruff + mypy clean.
  All 5 named mutants confirmed caught. slice_extent correctly omitted per Ruling B.
Task 4: task review dispatched (opus, agent TBD), diff d21d22f..a54116d
Task 4: review verdict — spec COMPLIANT, quality NEEDS FIXES. Reviewer found no behavioural
  defect in the implementation and confirmed the mean/count invariant holds structurally.
  Important 1: the multi-trace-per-cell segment sum is never numerically verified. Mutation
    `total[:, plan.cells] += block[:, plan.starts]` (first-column pick instead of reduceat)
    passes all 13 tests; on UTM/cell-0.05 input with traces of 2.0 and 8.0 in one cell the real
    code gives 5.0, the mutant 1.0, coverage 2 in both.
  Important 2: `order = keep[argsort(ids[keep])]`'s remap is never exercised — every test's kept
    set is a prefix, so the remap is a no-op throughout. Dropping it passes all 13 tests and
    scatters an EXCLUDED trace into the opposite corner of the grid while dropping a real one.
    The test written for this hazard puts the out-of-frame trace last, where it cannot show.
Ruling N: promote the reviewer's Minor on `accumulate`'s dead k0/k1 to this fix round. Why:
  the parameters raise on any window but the full axis and would double-count if the shapes
  matched, and Task 5 edits this same file next. I checked the plan's `stream_slice`: it inlines
  its own 1-D accumulation with `count * n_levels` bookkeeping and never calls `accumulate`, so
  they are dead for good. `accumulate`/`resample_window` are in no Interfaces block, so the
  signature is free. Cost if wrong: if some later caller does want a windowed accumulate, it
  writes the four lines then, against a real caller.
Ruling O: promote the reviewer's controller-note on non-finite coordinates to this fix round,
  and fix it in frame.py (Task 1's file). Why: NaN trace coordinates — an ordinary GPS dropout —
  emit two RuntimeWarnings from the unguarded np.floor().astype() cast, and Task 6 adds a
  real-data end-to-end test over ten actual GSSI files against a pristine-output requirement.
  The same unguarded cast is the deferred Task 1 minor about astronomically distant points
  relying on INT_MIN rather than wrapping into a VALID cell id; one explicit finite/range mask
  closes both. Cost if wrong: a few lines in cell_index's hot path; measurable if it matters.
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
Task 4: fix round 1/5 implemented — commits a54116d..fe27512 (pushed). 390 passed / 2 skipped.
  accumulate's dead (k0,k1) removed; frame.py gained an explicit finite/range mask.
  I re-ran Task 1's UTM guard myself after frame.py changed, since that invariant cost two
  rounds: 0/300 drops at cell 0.5, 0.1 and 0.05; far-edge 4.0-1e-12 -> [3]; NaN/1e300/valid
  -> [-1, -1, 1] with no warning under simplefilter("error"). Guard intact.
Task 4: scoped re-review dispatched (opus, agent a3e8d4927eb99717a), diff a54116d..fe27512
Task 4: fix round 1/5 (4 addressed, 0 open; commits a54116d..fe27512). Re-reviewer injected both
  mutants via scratchpad-only pytest plugins (checkout never modified): each now fails exactly
  the one new test and nothing else (1 failed / 14 passed, vs 15 passed clean), confirming the
  original suite never caught either. It also reimplemented the pre-fix cell_index and compared
  it against the current one over 456,750 finite points (25 seeds x 6 azimuths x 5 cell sizes,
  including corners, +-1e-9 overshoots, near-edge, and clouds translated by -1e7 and +1e9):
  0 mismatches — the mask is a no-op on finite input, so Task 1's tolerance is untouched. It
  further showed the mask can only fire at |ix| >= 2.3e18 while an in-frame point reaches at
  most max(nx,ny) (~5e3 worst case over 20,000 sampled frames), ~4.6e14x headroom.
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
  loss. Recorded so the claim does not propagate into the final review as a real hazard.
Task 4: complete (commits d21d22f..fe27512, review clean)

Task 5: dispatched (sonnet), BASE fe27512
Task 5: implementer DONE, commit 184049f (pushed). 403 passed / 2 skipped, ruff + mypy clean.
  All 6 named mutants confirmed caught.
Ruling P: accept commit 184049f's trailer `Co-Authored-By: Claude Sonnet 5` even though the
  plan's Global Constraints specify `Claude Opus 5 (1M context)` and the other five commits use
  that. Why: the implementer followed its own harness attribution reminder, and its trailer is
  the more ACCURATE of the two — every implementer in this plan was sonnet, so commits 265d8e6,
  60e6e2d, 00dddbc, 7d43e01, 801dbbc, d21d22f, a54116d and fe27512 arguably carry the wrong name
  already. Normalising would mean rewriting pushed history on a shared branch, which is a
  stop-and-ask action and wildly disproportionate to a metadata trailer. Cost if wrong: one
  commit on the branch names a different model than its siblings; surfaced to the user at the end.
Task 5: task review dispatched (opus), diff fe27512..184049f
Task 5: review verdict — spec COMPLIANT, quality NEEDS FIXES. The property test was confirmed
  genuinely discriminating (catches window off-by-one at BOTH ends; the interior window (4,12)
  is what does the work, the edge-flush ones would let a clamped off-by-one through), and
  stream_slice matched the resident cube to exactly 0.0 relative difference on a 230-level cube
  at amplitude ~5000.
  Important 1: a plan built against a SHORTER z axis makes stream_slice silently return a dimmed
    slice (~0.47-0.51x amplitude, no error) where build_cube raises ValueError on identical
    inputs. resample_window slices plan.z_index[k0:k1], .sum(axis=0) collapses the short
    dimension, and count is still multiplied by the requested n_levels.
  Important 2 (plan-mandated gap): an int32-accumulator mutant passes all four streaming tests,
    so the int64 Global Constraint is enforced by nothing but the source text. Verified pin:
    counts = 2**29 over a 6-level window gives coverage 536870912 shipped, -1073741824 int32.
Ruling Q: promote the reviewer's Minor about make_survey never putting two lines in one cell.
  Why: by the reviewer's own evidence it is the same class as the two Importants — a mutant that
  pools PER-LINE MEANS instead of pooling traces passes all four streaming tests while diverging
  4.5% from the resident cube on a shared-cell survey. Cross-line pooling is what happens at
  every tie-line crossing in a real cross-hatched survey, not an edge case, and this is the
  load-bearing test of the whole task. Cost if wrong: one extra line in a test fixture.
Ruling R: promote the reviewer's Minor on test_fill_preserves_a_fully_covered_slice. Why: it
  calls radius_cells=0, making it a duplicate of test_zero_radius_is_a_no_op, and its name
  asserts a property the code does not have — at r=1 the measured max deviation is 0.51. A
  duplicate test plus a false name is two rubric defects, and M11 puts a radius slider on this
  behaviour, so it should inherit a decided semantic rather than rediscover it. Cost if wrong:
  a renamed test and one added case.
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
Task 5: fix round 1/5 (4 addressed, 0 open; commits 184049f..f3473ee). Re-reviewer injected seven
  mutants via scratchpad-only plugins. Fixture-weakening check passed: window (4,12) is still
  strictly interior and still partial (180 finite / 300 NaN), empty cells unchanged at 300/480,
  and counts STRENGTHENED from {1,2} to {1,2,3,4} per cell. Off-by-one still dies at both ends
  and (4,12) is still the window doing that work — a +1 mutant is caught at (4,12) (max rel
  0.299) and NOT at (30,64), a -1 mutant caught at (4,12) (0.609) and NOT at (0,1). Guard
  over-rejection checked directly: every window (k0,k0+1), (k0,k0+7), (k0,nz) for k0 in 0..63
  accepted, 0 mismatches vs slice_levels. Per-line-mean mutant now fails (11/480 mismatched,
  max rel 0.308) where against the reconstructed pre-fix fixture it diverged by exactly 0.
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
  agree and the property test cannot see it. M11 caches plans; a stale cache would produce a
  wrong slice silently in BOTH modes. Worth a provenance/identity check on LinePlan in M11.
Task 5: complete (commits fe27512..f3473ee, review clean)

Task 6: dispatched (sonnet), BASE f3473ee. Real data confirmed present (10 DZT); the suite's only
  2 skips are deliberate schema skips, so the real-file tests do run rather than skip.
Task 6: implementer DONE_WITH_CONCERNS, commit 01afdec (pushed). 419 passed / 2 skipped.
  I verified the real-data claim myself rather than taking the report: the only 2 skips are the
  pre-existing deliberate schema skips (bandpass, gain_curve), and `-k real` gives 42 passed /
  0 skipped. The end-to-end test over the ten GSSI files genuinely ran.
  Disclosed concern 1 (good self-reporting): a dtype-loss test it first wrote did not
    discriminate, because a load-side cast masked a save-side bug. Rewrote it to inspect the
    on-disk array directly. Reviewer is verifying the shipped version really catches the mutant.
  Disclosed concern 2 (brief-verbatim): load_cube reads meta["frame"]/["z"]/["provenance"]
    outside the try/except, so a malformed-but-present meta blob raises a bare KeyError instead
    of CubeStoreError. No brief test exercises it.
Task 6: task review dispatched (opus, agent a3b7577d9f8ca5bf6), diff f3473ee..01afdec
Task 6: review verdict — spec COMPLIANT, quality NEEDS FIXES. The reviewer independently confirmed
  both disclosures and called the dtype rewrite "the first time in this plan that a disclosed
  non-discriminating test was actually replaced with one that discriminates" — and confirmed it
  is the ONLY test catching the save-side mutant, the brief's own dtype test being blind to it.
  Important 1: load_cube has FIVE uncaught escapes, not the one disclosed. A cube truncated to
    half its bytes raises zipfile.BadZipFile, which subclasses Exception (not OSError/ValueError)
    and so slips the guard — the likeliest corruption for this format and exactly the
    shared-drive threat model the plan names. Also KeyError on missing meta key, TypeError on
    meta=null, and ValueError from SliceCube.__post_init__ on a shape/meta disagreement.
  Important 2: np.savez_compressed appends .npz, so save_cube(dir/"cube") writes dir/cube.npz
    while load_cube(dir/"cube") raises "no cube file". The survey JSON stores the path verbatim,
    so an M11 caller writing a user-typed name gets a cube on disk with a path that never
    resolves — permanently un-built in the UI.
  Important 3 (plan-mandated): project.py:263 is the only key in load_site with no validation;
    its neighbour presets raises ProjectError for a non-dict. "cubes": ["x"] / 5 / "a.npz" all
    load and are written straight back out by save_site.
Ruling S: promote the reviewer's Minor on the real-data test's persistence leg. Why: it asserts
  only that provenance round-trips, and a save_cube mutant writing all-zero mean and count leaves
  the real-data test PASSING. Real files are this project's primary validation, and the single
  place a cube built from real data is written and read back currently checks only its label.
  Cost if wrong: one extra assertion on a test that already runs.
Ruling T: promote the reviewer's Minor on STORE_VERSION being written and never read. Why: a v2
  file would be parsed as v1 and yield either a wrong cube or one of finding 1's uncaught
  exceptions; format compatibility is painful to retrofit once files exist on people's drives.
  Scoped deliberately to "raise CubeStoreError naming both versions" — no migration machinery.
  Cost if wrong: a version check that never fires.
Task 6: minor (deferred): save_cube has no documented error contract — a read-only directory or
  full disk raises raw OSError, and a non-JSON-serialisable value in Provenance.velocity/steps
  (e.g. np.float32, not a float subclass) raises raw TypeError.
Task 6: fix round 1/5 dispatched (resumed implementer ac4f0101b810cf80a, 3 findings + 2 promoted)
Task 6: fix round 1/5 (5 addressed, 2 NEW Important introduced by the fix; commits 01afdec..2da595b).
  Re-reviewer measured all five original findings ADDRESSED: reinstating the old load_cube tail
  kills 6 tests; the all-zero save_cube mutant now fails the real-data test at 400/1200 mismatched,
  and mean-only and count-only mutants each fail their own assertion independently.
  NEW Important A: with_suffix(".npz") REPLACES the last suffix where np.savez_compressed APPENDS.
    Measured: 'grid.v2' -> grid.npz, 'Grid A v1.2' -> Grid A v1.npz, '2026-09-18.grid' ->
    2026-09-18.npz, 'cube.tar.gz' -> cube.tar.npz. Collision confirmed: saving two different
    cubes as grid.v1 then grid.v2 leaves ONE file and both load byte-identical arrays with no
    error. Silent cube-over-cube data loss — strictly worse than the mismatch it replaced.
  NEW Important B: the new docstring claims every bad .npz raises CubeStoreError "and nothing
    else", but a 0-byte file escapes as EOFError (np.load raises EOFError, not OSError, on an
    empty magic read — exactly what a killed or disk-full save leaves) and a short origin list
    escapes as IndexError. Both one-token additions to the tuple.
  New Minor folded in: _npz_path runs before the guard, so load_cube("") raises a raw ValueError
    where pre-fix it gave CubeStoreError. A hand-edited survey JSON with "array": "" reaches it.
Task 6: minor (deferred): store.py:113 passes frame_doc["crs"] through unconverted, so a cube
  with "crs": null loads with frame.crs is None and no complaint; CubeFrame does not validate it.
Task 6: noted, not a defect: with the widened tuple a future genuine TypeError/KeyError inside
  Provenance.from_dict or SliceCube.__post_init__ would be reported as a corrupt file. Accepted
  cost of what finding 1 required; the traceback survives via `from exc` chaining.
Task 6: fix round 2/5 dispatched (resumed implementer ac4f0101b810cf80a, 2 new Important + 1 minor)
Task 6: fix round 2/5 (3 addressed, 0 open; commits 2da595b..9ea8dd7). Re-reviewer drove
  save_cube/load_cube over 14 input forms (str and Path, already-.npz, grid.v2, cube.tar.gz,
  grid.NPZ, .grid, .npz alone, a missing nested dir, a.b/cube, sub/../c, absolute, trailing
  slash) and confirmed _npz_path's output is a FIXED POINT of numpy's own rule in every case,
  so save and load cannot disagree for any of them. Reinstating with_suffix kills 6 tests;
  unconditional append kills 10; identity kills 8. EOFError and IndexError each kill exactly
  their own test and are not carried by the other's. Round 1's five fixes all verified intact.
  I independently confirmed the collision fix myself before dispatching: grid.v1/grid.v2 give
  two files with means 1.0 and 2.0, aliased=False, and all dotted forms round-trip.
Task 6: minor (deferred) FLAG TO FINAL REVIEW: test_slices_store.py:176 is a VACUOUS assertion —
  `assert not np.array_equal(back_v1.mean, back_v2.mean)` cannot fail, because mean contains NaN
  and np.array_equal without equal_nan=True returns False for any NaN-bearing array (confirmed:
  np.array_equal(a.mean, a.mean) is False). It would pass even if the two cubes were byte-
  identical — precisely the aliasing case it claims to guard. Harmless today because the test's
  real discrimination comes from the iterdir() assertion and two NaN-aware assert_array_equal
  calls, which do kill the with_suffix mutant. One keyword fixes it: equal_nan=True.
Task 6: minor (deferred): store.py:45, `.npz` alone normalises to `.npz.npz` — pathlib treats a
  leading dot as a stem, not a suffix. Save and load agree, so no data risk; the docstring's
  claim to mirror numpy exactly is wrong for that one hidden-file name.
Task 6: minor (deferred): store.py:91, `if not path.exists()` sits outside the try, so a stat
  failing with EACCES on an unsearchable parent escapes as raw PermissionError.
Task 6: minor (deferred): save_cube stays asymmetric with the now-guarded load_cube —
  save_cube(cube, "") raises raw ValueError, a read-only directory raises raw PermissionError.
Task 6: complete (commits f3473ee..9ea8dd7, review clean)

ALL SIX TASKS COMPLETE. Branch nsgeo-m10 at 9ea8dd7. Full core suite 440 passed / 2 skipped.

## Final whole-branch review (opus, 493a15e..9ea8dd7) — verdict: READY TO MERGE WITH FIXES

CRITICAL 1 (cross-task, invisible to every per-task review): a LinePlan is a function of
  (line, frame, z) but carries the identity of none of them. The only guard compares
  plan.z_index.shape[0] against z.nz, and its message claims far more than it checks. Measured:
  plans built for cell=1.0/nx=4/ny=3 then used with cell=0.5/nx=8/ny=6 put traces in cells
  0/1/2 where the answer is 1/3/5 — no exception from build_cube OR stream_slice, coverage
  looks plausible, the cube is wrong everywhere. Shrinking the frame raises nothing either,
  because stale ids stay in bounds. And a z axis with matching nz but t0=20 gives times
  [0,1,2] where the answer is [20,21,22]. Spec 9.2 puts cell size and z range on LIVE SLIDERS,
  so this is M11's first bug. The Task 5 review saw only the z half; the FRAME half was never
  noticed by anyone.
IMPORTANT 2: fill's numerator masks non-finite values but its denominator does not, so a NaN
  with a non-zero count contributes 0 up top and full weight below. Measured 1.2 where the
  unbiased answer is 6.0 — a 5x error toward zero. The Task 5 review called it unreachable
  "while cube.py guarantees NaN iff count 0"; that guarantee is a docstring and nothing
  enforces it. Exactly the cross-task shape: invariant asserted in cube.py, relied on in fill.py.
IMPORTANT 3: the spec's shared stretch cannot be computed from what M10 ships. UnipolarClip()
  .limit(cube.mean) gave 2.59 where the correct limit for the displayed 10-level slice was 0.87
  — a window mean has far lower variance than the levels it averages, so every slice renders at
  ~1/3 intended brightness, identically at every depth, reading as "dim data" not a bug.
IMPORTANT 4: all 15 binning tests run at origin (0,0) cell 1.0. The Task 4 reviewer's reasoning
  that no magnitude hazard recurs is correct but lives nowhere in the repo.
IMPORTANT 5: tol's multiplier 8 — reviewer swept for_grid over 3 origins x 8 azimuths x 3 cells
  x 3 extents, worst slack actually needed 0.81 ulps, 0/3864 dropped. Holds with 10x margin
  empirically, but the analytic bound is 8-10 ulps and no test distinguishes 8 from 64.
IMPORTANT 6: Site.cubes bypasses save_site's path-portability enforcement and its record shape
  exists only as a literal in a test. Reviewer confirms NOT bumping SCHEMA_VERSION is correct
  and for a stronger reason than precedent: load_site compares version != SCHEMA_VERSION
  exactly, so bumping would make every existing survey file fail to load outright.
IMPORTANT 7: the unipolar display path is the least-pinned new code on the branch — a permuted
  _amp_heat passes every test, UnipolarClip passes all four of its tests with __post_init__
  deleted, and the max_samples stride branch is never executed by any test.
PLAN/SPEC STALENESS confirmed by grep: `coarsen` is in spec 6.1/7.1/11 (one of four named
  property tests) and appears ZERO times in the plan — no task, no deferral note; spec 11's
  "exactly" is unachievable and the test correctly uses rtol=1e-5; spec 5.4 says cubes is a
  LIST, the code uses a dict keyed by id (the dict is better); plus the known stale alpha line,
  the typing forms at 12 sites, slice_extent, accumulate's k0/k1, the dropped colormap test,
  and the fixed commit trailer at 7 sites.
Triage of the 39 deferred items: 11 fix-before-merge, 17 fix-later, 8 won't-fix.
Composition check the reviewer ran: 12 lines, 0.5 m spacing, 0.10 m cells, UTM, 17 deg azimuth,
  full pipeline plan_line -> build_cube -> slice_levels/coverage -> fill(r=8) -> UnipolarClip
  -> to_rgba8. Empty fraction exactly 0.80, matching spec 6.4's prediction; alpha tracked
  nodata bit-for-bit; streaming and resident agreed to 0.0 after the fill.

Ruling U: implement Important 3 and 6 as DOCUMENTATION only, not as new functions. The reviewer
  offered `shared_limit(cube, thickness, clip)` and routing site.cubes' array path through
  line_key. Both would be code with no caller in M10, which is what Ruling B dropped
  slice_extent for. Cost if wrong: M11 writes two small helpers it was going to need anyway,
  with real callers and real tests attached.
Final fix wave dispatched (sonnet), ONE dispatch per the skill, FIX_BASE 9ea8dd7

## Fix-wave re-review (opus, 9ea8dd7..94279e4) — ALL ADDRESSED, no new Critical/Important
Every behavioural fix discriminates against an independently injected wrong implementation, and
in each case ONLY the new test fails — the pre-existing tests were blind exactly as the findings
claimed. The guard and the fill denominator, the two highest-risk changes, were both checked for
over-rejection and silent output drift and are inert on every legitimate input measured,
including the real GSSI data (test_real_files.py 33 passed, not skipped). Reviewer: "I would
merge this branch."
Notable measurements: with the guard neutered, a cell=1.0 plan against a cell=0.5/nx=8/ny=6 frame
  bins into cells [0,1,2] where cell_index says [9,11,13], coverage 3, no exception — at HEAD both
  consumers raise. The fill change is BIT-IDENTICAL to the old formula for every well-formed slice
  (NaN iff count 0) at r=1/2/4, covered and 80%-empty; only the invariant-violating case moves.
  tol=64 still rejects a miss 6.394e-08 m outside a 0.05 m-cell UTM frame — ~780,000x finer than
  one cell.
Four new Minors, none blocking: a stale mechanism sentence in a streaming test docstring; the
  tol docstring's "5.7e-9 m / seven orders" computed at |world|=4e5 rather than a realistic
  4.5e6 northing (6.4e-8 m, ~six orders) — the bound's argument survives, the number is
  optimistic; save_cube still serialises a non-string crs that load_cube now refuses; and the
  guard would reject a list-vs-tuple origin, which violates CubeFrame's own annotation anyway.

Ruling V: the plan still LITERALLY PRESCRIBES two of the bugs this wave removed — plan:1821 has
  the unmasked fill denominator and plan:2111 the unvalidated crs pass-through — plus three
  interface blocks that predate LinePlan's new frame/z fields, and the two disclosed one-liners.
  The skill allows no second fix wave, but this is load-bearing for a later milestone rather
  than a code finding: an M11 implementer copying those blocks reintroduces two fixed defects.
  Ruling: seven documentation-only annotations, no code, dispatched as a quick fix rather than a
  review cycle. Cost if wrong: seven markdown notes in a document that is already annotated
  throughout; no behaviour touched, nothing to re-review.
