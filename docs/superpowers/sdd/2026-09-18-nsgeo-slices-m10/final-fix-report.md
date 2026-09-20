# M10 final fix dispatch — report

Worktree: `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-m10`, branch `nsgeo-m10`.
Started at `9ea8dd7`, ends at `94279e4` (7 new commits, all pushed to `origin/nsgeo-m10`).

All commands run with `PYTHONDONTWRITEBYTECODE=1` exported, using the worktree's own venvs
(`./.venv/bin/python`, `./.venv-qgis/bin/python`), never bare `python`.

## Baseline confirmed

```
$ ./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
486 passed, 2 skipped in 1.58s
```

Matches the brief's stated baseline exactly.

---

## Item 1 — CRITICAL: `LinePlan` carries no identity of the frame/z it was built for

**Commit:** `bc9a9d2 fix(slices): give LinePlan the frame/z identity it was built for`

**Change** (`packages/nsgeo-core/src/nsgeo/slices/binning.py`):
- Added `frame: CubeFrame` and `z: ZAxis` fields to `LinePlan`, set by `plan_line`.
- Added a shared `_check_plans_current(lines, plans, frame, z)` helper, called at the top of both
  `build_cube` and `stream_slice` (before any array indexing). It compares `plan.frame != frame`
  and `plan.z != z` individually — never the whole `LinePlan`, which holds ndarrays and would
  raise `ValueError: truth value of an array is ambiguous` on `==`. `CubeFrame` and `ZAxis` are
  frozen, all-scalar dataclasses, so the comparison is cheap and total.
- The error message names the line and states exactly which of `frame`/`z` differ, e.g.
  `line 'a.dzt': plan is stale (frame CubeFrame(...) != current CubeFrame(...)) -- call
  plan_line() again against the current frame and z axis before binning`.
- **Replaced** the old `stream_slice`-only guard (`plan.z_index.shape[0] != z.nz`) entirely
  rather than keeping it alongside the new one. Reasoning: the old guard only ever compared
  `nz`, which is one field of `ZAxis`; the new `plan.z != z` comparison already subsumes it (any
  `nz` mismatch makes `ZAxis.__eq__` return `False` too), and additionally catches the cell-size
  and same-`nz`-different-`t0_ns` cases the old guard missed outright. There is nothing left for
  the old guard to catch that the new one does not.
- Updated one pre-existing test (`test_slices_streaming.py::test_streaming_rejects_a_plan_built_for_a_different_z_axis`)
  whose `match="different z axis"` no longer matched the new message; changed to `match="plan is stale"`.

**Tests added** (`packages/nsgeo-core/tests/test_slices_binning.py`):
- `test_build_cube_rejects_a_plan_built_for_a_different_cell_size`
- `test_stream_slice_rejects_a_plan_built_for_a_different_cell_size`
- `test_build_cube_rejects_a_plan_built_for_a_different_t0_at_the_same_nz`
- `test_stream_slice_rejects_a_plan_built_for_a_different_t0_at_the_same_nz`

## Item 3 — binning pinned only at toy magnitude (folded into the same commit)

Added `test_binning_at_utm_magnitude_and_a_rotated_azimuth_drops_no_traces` in
`test_slices_binning.py`: a `CubeFrame(origin=(500000.0, 4500000.0), azimuth=33.0, cell=0.05,
nx=20, ny=20, crs="EPSG:32617")`, with 77 trace coordinates built from frame-local coordinates
via `f.axes()` (forward-transformed rather than hand-computed, so the test is independent of any
particular rotation-matrix sign convention), asserting `cube.coverage().sum() == n_traces`.

### Mutant evidence (item 1)

Reverted `binning.py` to the pre-fix baseline (`git show 9ea8dd7:...`) and ran only the four new
stale-plan tests:

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_binning.py -q \
    -k "different_cell_size or different_t0_at_the_same_nz"
FFFF
FAILED ...test_build_cube_rejects_a_plan_built_for_a_different_cell_size - Failed: DID NOT RAISE ValueError
FAILED ...test_stream_slice_rejects_a_plan_built_for_a_different_cell_size - Failed: DID NOT RAISE ValueError
FAILED ...test_build_cube_rejects_a_plan_built_for_a_different_t0_at_the_same_nz - Failed: DID NOT RAISE ValueError
FAILED ...test_stream_slice_rejects_a_plan_built_for_a_different_t0_at_the_same_nz - Failed: DID NOT RAISE ValueError
4 failed, 15 deselected in 0.13s
```

Restored the fix; all 25 tests in `test_slices_binning.py` + `test_slices_streaming.py` pass.
**FAILS against the wrong (baseline) version, PASSES against the fix.**

Item 3's UTM test is additive coverage of already-correct code (once item 1 is fixed), not a
behavioural change on its own, so no separate mutant was constructed for it; it does exercise
exactly the class of bug item 1 fixes, at realistic magnitude.

---

## Item 2 — `fill`'s denominator ignores the finiteness mask

**Commit:** `62622b1 fix(slices): fill's denominator masks NaN the same as the numerator`

**Change** (`packages/nsgeo-core/src/nsgeo/slices/fill.py`): the denominator now convolves
`np.where(np.isfinite(values), counts, 0.0)` instead of raw `counts` — one line, matching the
numerator's existing mask.

**Test added** (`test_slices_fill.py::test_fill_denominator_masks_out_a_nan_value_with_a_nonzero_count`):
3×3 grid, `(NaN, count 4)` at `[1,0]` and `(6.0, count 1)` at `[1,2]`, asserts `out[1,1] ==
approx(6.0)`.

### Mutant evidence

Reverted `fill.py` to baseline, ran the new test:

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_fill.py -q -k denominator_masks
F
E       assert np.float32(1.2) == 6.0 ± 6.0e-06
E         Obtained: 1.2000000476837158
E         Expected: 6.0 ± 6.0e-06
1 failed, 10 deselected in 0.11s
```

Matches the brief's own described error (1.2 vs 6.0). Restored the fix: all 11 fill tests pass.
**FAILS against baseline, PASSES against the fix.**

---

## Item 4 — `tol` multiplier bound

**Commit:** `c6f6b81 fix(slices): bound cell_index's edge tolerance, document level_range's intersection`

**Change** (`packages/nsgeo-core/src/nsgeo/slices/frame.py:113`): `8.0` → `64.0`. Docstring
rewritten to state the reasoning as a bound (an analytic error walk of the `to_local` /
re-projection round trip admits 8–10 ulps under adversarial rounding; the empirical sweep's
worst case of 0.81 ulps was never the basis for the multiplier) rather than as a value fitted to
the sweep. At UTM scale 64 ulps is 5.7e-9 m, seven orders below the smallest realistic cell.

**No new test**, per the brief's own instruction — the existing UTM sweep and genuine-miss tests
in `test_slices_frame.py` already characterise this bound and both continue to pass unchanged.
Since no test's pass/fail status changes on this multiplier value (it's a numeric-bound
tightening within a range no existing test can distinguish), no mutant/wrong-implementation pair
applies here in the same sense as the other items — this is documentation-of-intent plus a
value change that no test was designed to pin either way.

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_frame.py -q
21 passed in 0.25s
```

---

## Item 5 — the unipolar display path is under-pinned

**Commit:** `89061ef test(render): pin amp_heat's midpoint and UnipolarClip's validation/subsampling`

**Tests added** (`packages/nsgeo-core/tests/test_render.py`), no source change (existing
`_amp_heat`/`UnipolarClip` code was already correct):

- `test_amp_heat_runs_black_through_red_and_orange_to_white`: keeps the endpoint assertions
  (`lut[0] == (0,0,0)`, `lut[255] == (255,255,255)`) but adds a midpoint assertion
  (`lut[128]`: r==255, b==0, 100<=g<=160) that a channel-permuted mutant cannot satisfy.
- `test_unipolar_clip_validates_its_arguments` (mirrors `test_percentile_clip_validates_its_arguments`)
- `test_unipolar_clip_subsamples_large_arrays_deterministically` (mirrors
  `test_percentile_clip_subsamples_large_arrays_deterministically`, using non-negative data)

### Mutant evidence — `_amp_heat` channel permutation

Mutated `_amp_heat` to assign `b = clip(t*3)`, `g = clip(t*3-1)`, `r = clip(t*3-2)` (blue → cyan →
white):

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_render.py -q
        assert r == 255
E       assert 0 == 255
1 failed, 36 passed in 0.34s
```

Only the new test fails; all 36 others (including the pre-existing endpoint-only test) pass —
confirms the brief's claim that endpoint-only assertions miss a channel permutation. Restored the
fix.

### Mutant evidence — `UnipolarClip` with `__post_init__` and the stride branch removed

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_render.py -q \
    -k "unipolar_clip_validates or unipolar_clip_subsamples"
FF
test_unipolar_clip_validates_its_arguments: Failed: DID NOT RAISE ValueError
test_unipolar_clip_subsamples_large_arrays_deterministically:
    assert 0.9900807863504554 == 0.9897025950496376
2 failed, 35 deselected in 0.18s
```

Restored the fix: all 37 tests in `test_render.py` pass. **Both new tests FAIL against the
respective mutant, PASS against the real implementation.**

---

## Item 6 — small correctness and clarity fixes

### 6a. `store.py` — non-string `crs`

**Commit:** `0fe192e fix(slices): reject a non-string crs and fix a vacuous store test`

`load_cube` now raises `CubeStoreError` if `frame_doc["crs"]` is not a `str`, before constructing
`CubeFrame`. New test `test_loading_a_file_with_a_null_crs_fails_clearly`.

Mutant evidence (reverted `store.py` to baseline):
```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_store.py -q -k null_crs
F
Failed: DID NOT RAISE CubeStoreError
1 failed, 27 deselected in 0.14s
```
Restored: all 28 store tests pass. **FAILS against baseline, PASSES against the fix.**

### 6b. Vacuous `np.array_equal` assertion

**Commit:** same as 6a.

`test_save_does_not_alias_two_dotted_names_onto_one_file` (`test_slices_store.py:176`): changed
`assert not np.array_equal(back_v1.mean, back_v2.mean)` to
`assert not np.array_equal(back_v1.mean, back_v2.mean, equal_nan=True)`, per the brief's
instruction to fix rather than delete. (This is a test-only fix to an already-passing test, not
a behavioural source change — no mutant applies; the vacuity itself is the bug, and
`equal_nan=True` is what makes the assertion capable of failing at all when it should.)

### 6c. `render.py` docstring typo

**Commit:** `89061ef` (same commit as item 5, both touching `render.py`/`test_render.py`).

"index 8 has no spare entry" → "an 8-bit index has no spare entry" in `to_index8_unipolar`.

### 6d. `ZAxis.level_range` intersection contract

**Commit:** `c6f6b81` (same commit as item 4, both in `frame.py`).

Docstring now states the contract as intersection explicitly, with both example directions
(overhang at the start, overhang at the end), and states that a depth readout must derive its
window from the returned `(k0, k1)`, never re-derive it from `(top_ns, thickness_ns)`.

New test `test_level_range_is_a_genuine_intersection_not_a_clamped_copy`: on a 100-level axis,
`level_range(top_ns=-5, thickness_ns=10)` must return `(0, 5)` (not `(0, 10)`), and
`level_range(top_ns=95, thickness_ns=10)` must return `(95, 100)` (not `(90, 100)`).

Mutant evidence: implemented a "shift instead of truncate" version of `level_range`
(`k0 = max(0, min(k0, nz - n_levels)); k1 = k0 + n_levels`, always keeping the full requested
level count):
```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_frame.py -q
..................F..
assert (0, 10) == (0, 5)
1 failed, 20 passed in 0.27s
```
Only the new test fails; the pre-existing `test_level_range_clamps_to_the_axis_and_never_empties`
(which only checks `k0`) passes against the shift-to-fit mutant too, confirming the brief's claim
that it never noticed the difference. Restored the fix: 21 passed.

### 6e. `fill`'s r=1 "itself included" semantic

**Commit:** `62622b1` (same commit as item 2, both in `fill.py`/`test_slices_fill.py`).

New test `test_fill_at_r1_includes_the_cells_own_value_in_its_smoothed_value`: a deterministic
3×3 case (centre 100.0, four neighbours 1/2/3/4, all count 1) asserts `out[1,1] ==
approx(22.0)` — the centre-included plus-kernel mean. A centre-excluded kernel would give 2.5.

Mutant evidence: added `kernel[r, r] = 0.0` after `disc_kernel(r)`:
```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_fill.py -q
assert np.float32(2.5) == 22.0 ± 2.2e-05
1 failed, 11 passed in 0.14s
```
Only the new test fails; `test_fill_smooths_a_fully_covered_slice_rather_than_preserving_it`
(the existing r=1 test) passes against the centre-excluded mutant too, exactly as the brief
predicted. Restored the fix: 12 passed.

---

## Item 7 — documentation only (no new functions)

**Commit:** `543a30c docs: the (cube, thickness) stretch and the cubes record schema`

- `UnipolarClip` docstring (`render.py`) gained a paragraph stating the shared stretch is a
  property of `(cube, thickness)`, that `limit()` must be computed over slices at the display
  thickness rather than `cube.mean`, and why (measured 2.59 vs. correct 0.87, a uniform dimming
  that reads as "the data is dim" rather than a bug). No implementation added.
- `Site.cubes` docstring (`survey.py`) now names the record shape (`grid_id`, `preset`,
  `transform`, `cell`, `array` — matching the literal in `test_project.py`) and states explicitly
  that `save_site` routes every line path through `project.line_key` but `site.cubes` bypasses it
  entirely, recording routing `array` through `line_key` as M11's job. No implementation added,
  per the explicit instruction not to write these functions.

No tests added (nothing to pin — these are forward-looking docstrings with no M10 caller).

---

## Item 8 — plan and spec corrections

**Commit:** `94279e4 docs: correct the M10 plan and slices spec for what actually shipped`

All 3 corrections/notes to the plan required by the brief, each with an "amended during
execution:" note:
- `to_rgba8`'s Interfaces line (alpha-0-when-not-finite) qualified to `unipolar=True` only.
- All 12 named `Tuple[`/`Dict[`/`Optional[` sites (lines 268, 285, 415, 667, 671, 1238, 1240,
  1242, 1246, 1258, 1470, 1705, verified against the exact original line content before editing)
  corrected to `tuple`/`dict`/`X | None`, each with an inline `# amended during execution (ruff
  UP)` comment. Line 2041 (`_meta`'s `Dict[str, Any]`), which has the same issue but was **not**
  in the brief's list, was deliberately left untouched.
- `slice_extent`'s code block replaced with a note that it was dropped as dead code and that
  M11's GeoTIFF export is its actual caller.
- `accumulate`'s definition and its one call site corrected to the no-`k0`/`k1` signature that
  shipped, each annotated.
- `test_every_colormap_is_a_valid_table` replaced with a comment noting it was dropped as a
  duplicate of `test_every_colormap_is_a_256_by_3_uint8_table`.
- All 7 `Co-Authored-By: Claude Opus 5 (1M context)` sites (1 prose bullet + 6 identical
  commit-heredoc trailers, confirmed by count after `replace_all`) annotated as superseded by
  each implementer's own harness attribution.
- Added a "No `coarsen`" bullet to the existing "What M10 deliberately does not do" section,
  noting the spec names it in three places (including its required-property list) while the
  plan previously mentioned it zero times; deferred to M11.

Two spec corrections in `docs/superpowers/specs/2026-09-18-nsgeo-slices-design.md`:
- §11: reworded the "exactly" claim about streaming vs. resident-cube equality to state it is
  mathematical, not bit, equality, and explains why `rtol=1e-5` is correct and should not be
  tightened.
- §5.4: "the survey JSON gains a `cubes` list" corrected to "a `cubes` object, keyed by cube id"
  matching the dict implementation, with a note on why the dict is better (matches `presets`,
  direct lookup by id).

Sanity checks performed: fenced-code-block count in the plan doc is unchanged (76, even, before
and after all edits — confirmed by comparing against `git show HEAD:...` prior to any edits),
so no code fence was left unbalanced by an inserted prose note.

No implementation changed as part of item 8; no tests apply.

---

## Full verification (after all 7 commits, at `94279e4`)

```
$ ./.venv/bin/python -m pytest packages/nsgeo-core/tests -q
452 passed, 2 skipped in 1.38s

$ ./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
498 passed, 2 skipped in 1.74s

$ QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
373 passed in 86.51s (0:01:26)

$ ./.venv/bin/ruff check .
All checks passed!

$ ./.venv/bin/ruff format --check .
105 files already formatted

$ ./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
    packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
    packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
Success: no issues found in 31 source files
```

**Skip accounting:** core+pure shows exactly 2 skips, both the deliberate schema ones named in
the brief (`bandpass` and `gain_agc`/`gain_curve` requiring parameters by design — confirmed by
running with `-rs` during earlier iterations; no new or unexpected skips were introduced).

**Count reconciliation:** core+pure went from 486 → 498 passed (+12), matching exactly: 4 tests
(item 1) + 1 test (item 3) + 3 tests (item 5) + 1 test (item 6a) + 1 test (item 6d) + 1 test
(item 6e) + 1 test (item 2) = 12. qgis stayed at 373 passed (untouched by this dispatch — nothing
in `packages/nsgeo-qgis/` was modified). Ruff, ruff format and mypy are all clean, matching the
baseline's clean state.

---

## Commits (in order)

1. `bc9a9d2` fix(slices): give LinePlan the frame/z identity it was built for — items 1, 3
2. `62622b1` fix(slices): fill's denominator masks NaN the same as the numerator — items 2, 6e
3. `c6f6b81` fix(slices): bound cell_index's edge tolerance, document level_range's intersection — items 4, 6d
4. `0fe192e` fix(slices): reject a non-string crs and fix a vacuous store test — items 6a, 6b
5. `89061ef` test(render): pin amp_heat's midpoint and UnipolarClip's validation/subsampling — items 5, 6c
6. `543a30c` docs: the (cube, thickness) stretch and the cubes record schema — item 7
7. `94279e4` docs: correct the M10 plan and slices spec for what actually shipped — item 8

All pushed to `origin/nsgeo-m10`.

---

## Things done differently from the letter of the brief, with reasoning

1. **Item 1's error message** does not use the literal phrase "different z axis" (the old
   guard's wording) since the new guard covers frame *and* z, so I wrote a message that names
   whichever of the two actually differs (`"frame ... != current ..."`, `"z ... != current
   ..."`, or both, joined with `"; "`), under a common `"plan is stale (...)"` prefix. I updated
   the one pre-existing test whose `match=` string depended on the old wording.

2. **Item 4 has no new test**, exactly as instructed, and therefore no mutant/wrong-implementation
   pair was constructed for it in the same form as the other items — there is no test that
   distinguishes 8.0 from 64.0 by design (per the brief: "no test can distinguish 8 from 64").
   I verified only that the existing sweep and genuine-miss tests still pass at the new value.

3. **Item 6b (vacuous assertion)** is a test-only correctness fix to a test that was already
   passing for the wrong reason; I did not construct a "wrong implementation" mutant for it since
   there is no source behaviour to mutate — the bug was entirely in the test's own assertion. I
   note this distinction rather than force a mutant that wouldn't be testing anything real.

4. **Left `packages/nsgeo-core/src/nsgeo/slices/store.py`'s `_meta`/plan-doc line 2041
   (`Dict[str, Any]`)** and the plan's "§5.4 ... the JSON `cubes` list" phrase in its own
   "Spec coverage" self-review section untouched, even though both have the same
   Tuple/Dict/Optional or list-vs-dict staleness as items explicitly listed elsewhere — neither
   was in the brief's line list, and the brief was explicit: "Do not restructure either document
   or change anything not listed here."

5. **Commit grouping**: grouped by module/theme (binning, fill, frame, store, render-tests,
   render/survey-docs, plan/spec-docs) rather than a strict "all source, then all tests, then all
   docs" three-commit split, since several items pair a source fix with its own pinning test in
   the same file and splitting those apart would leave intermediate commits with an
   unfixed-but-tested or fixed-but-unverified state. This still satisfies "logical groups ...
   rather than one giant commit."

No items were skipped or judged incorrect; all six original review tasks' fix items, all
documentation-only items, and both spec corrections were applied as specified.
