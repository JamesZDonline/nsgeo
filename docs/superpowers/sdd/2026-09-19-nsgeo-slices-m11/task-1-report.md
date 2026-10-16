# Task 1 report: Core — the arithmetic a viewer and an exporter need

## Summary

All four production changes were implemented exactly as specified in the brief
(`slice_extent` in `frame.py`; `SliceWindow`, `plan_windows`, `window_times_ns`,
`window_depths_m`, `window_label`, `limit_over_slices`, `shared_limit`,
`to_north_up` in the new `display.py`; `_smooth_size`, `_kernel_spectrum`,
`clear_kernel_cache` plus the padded/cached `fill` in `fill.py`; the
`__init__.py` re-exports), together with every test the brief specifies,
transcribed verbatim. `ruff check`, `ruff format --check`, and `mypy` are all
clean on the final state.

**One thing is not green**: the Step 30 real-data test
(`test_the_shared_stretch_on_a_real_cube_uses_most_of_the_colour_table`) runs
against the real, symlinked GSSI DZT corpus — it does **not** skip — and its
first assertion (`correct < over_raw_levels`, "the direction M10 measured")
passes, but its second assertion (median colour-index ratio `> 1.5`) fails.
This was investigated in depth (below) and diagnosed as a property of this
real corpus's `amp_envelope` data at `thickness=10`, not a defect in
`shared_limit`/`plan_windows`/`limit_over_slices` — those three pass ~30 other
unit and mutation-based checks, including all five required mutation-check
steps. The test was committed exactly as the brief specifies (not weakened),
per the instruction to use its values verbatim; this is flagged as the
task's one open concern rather than silently resolved.

Baseline before starting matched the brief's stated expectation exactly:
502 passed / 2 skipped (`packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests`).
Final combined suite: **529 passed, 1 failed, 2 skipped** (532 total; the 2
skips are the same pre-existing `bandpass`/`gain_curve` schema skips as
before).

## Commits

1. `6e5a0d3` — `feat(slices): slice_extent, a frame's world bounding box`
2. `43f2b56` — `feat(slices): window plans, window labels, shared stretch, and to_north_up`
3. `bf52eaf` — `perf(slices): smooth-size FFT padding and a cached kernel spectrum`
4. `87af23a` — `test(slices): the shared-stretch real-data check from the M11 brief`

**Deviation from the brief's commit granularity**: the brief lays out four
separate commits for the `display.py` material (window plans at step 12,
shared stretch at step 18, and to_north_up folded into step 24's export
commit). I combined these into one commit (#2 above). Reason: the brief's own
Step 7 test file imports all eight `display` names
(`SliceWindow, limit_over_slices, plan_windows, shared_limit, to_north_up,
window_depths_m, window_label, window_times_ns`) in one `from nsgeo.slices.display
import (...)` block from the very first version of the test file — before
`shared_limit` or `to_north_up` exist. That means there is no intermediate
point between steps 9, 15, and 21 where the test module is importable, so no
intermediate commit in that range can have a genuinely green test suite. Since
splitting into three commits would have meant either editing the brief's
verbatim test text (not permitted) or committing states that fail to import,
I built the complete module and its complete test file, verified the whole
thing together (`ModuleNotFoundError` before, 18/18 passed after), and
committed it as one coherent, honestly-green change. This is noted plainly
rather than presented as having followed the step-by-step commit sequence.

## Mutation-check results (Steps 5, 11, 17, 23, 29)

### Step 5 — `slice_extent` (two-corner mutant)

Mutated `corners = np.array([origin, origin + span_x, origin + span_y, origin + span_x + span_y])`
to `corners = np.array([origin, origin + span_x + span_y])` (origin and far
corner only).

Result: **caught**.
- `test_slice_extent_covers_all_four_corners_of_a_rotated_frame` FAILED:
  `ymin` obtained `-1.5358983848622443`, expected `-4.999999999999999 ± 5.0e-06`.
- `test_slice_extent_is_wider_than_the_frame_when_rotated` FAILED:
  `ymax - ymin` obtained `8.881784197001252e-16` (≈0), expected
  `14.142135623730951 ± 1.4e-08`.
- `test_slice_extent_of_an_axis_aligned_frame_is_its_own_box` still PASSED
  (as expected — the two-corner form is correct only at azimuth 0).

Reverted; full `test_slices_frame.py` returned to 24/24 passed.

### Step 11 — window functions (two mutants)

**Mutant 1**: `window_times_ns`'s `(window.k1 - 1) * z.dz_ns` → `window.k1 * z.dz_ns`.

Result: **caught**, and more broadly than predicted.
- `test_a_windows_time_span_is_n_minus_one_sample_intervals` FAILED.
- `test_the_label_reports_what_level_range_actually_returned_not_what_was_asked_for`
  FAILED (obtained `(48.0, 50.0)`, expected `(48.0, 49.5)`).
- **Bonus catch not named in the brief**:
  `test_the_label_carries_both_units_when_a_velocity_is_given` also FAILED
  (obtained `(0.6, 0.8)`, expected `(0.6, 0.78)`).

**Mutant 2**: `plan_windows`'s `range(0, z.nz - thickness_levels + 1, step_levels)`
→ `range(0, z.nz, step_levels)`.

Result: **partially caught — one predicted test did not fail**.
- `test_overlapping_windows_match_the_specs_band_count_formula` FAILED as
  predicted: `len(windows)` obtained `20`, expected `19`.
- `test_abutting_windows_tile_the_axis_without_gaps_or_overlap` did **NOT**
  fail, contrary to the brief's stated expectation. Reason: this test uses
  `thickness_levels=10, step_levels=10, nz=100`. Because `thickness == step`
  here, `range(0, 100 - 10 + 1, 10) = range(0, 91, 10)` and the mutant's
  `range(0, 100, 10)` produce the *same* sequence of tops
  (`0, 10, 20, ..., 90`) — both floor to the same last multiple of the step,
  so this particular abutting-window test cannot distinguish the two forms.
  The mutation is real and is caught (by the other test), but this specific
  test does not discriminate it. Reported plainly rather than adjusted.

Reverted; `test_slices_display.py` returned to 18/18 passed.

### Step 17 — `shared_limit` (two mutants)

**Mutant 1**: `shared_limit` body replaced with `return clip.limit(cube.mean)`
(M10's exact wrong implementation).

Result: **caught**.
- `test_the_shared_limit_is_measured_over_displayed_slices_not_raw_levels`
  FAILED: `over_slices < over_levels` obtained `2.5851687622070316 <
  2.5851687622070316` (equal, since both sides now compute the identical
  quantity). This value lands almost exactly on the "2.59" the
  `shared_limit`/`UnipolarClip` docstrings cite from the original M10 review.

**Mutant 2**: `plan_windows(cube.z, thickness_levels, thickness_levels)` →
`plan_windows(cube.z, thickness_levels, 1)` inside `shared_limit`.

Result: **caught, but not by the test the brief names**.
- `test_the_shared_limit_covers_every_level_exactly_once` did **NOT** fail.
  Reason: that test calls `plan_windows(cube.z, 10, 10)` directly with
  hard-coded arguments — it never calls `shared_limit` at all, so a mutation
  inside `shared_limit`'s body cannot affect it. The brief's expectation here
  does not match what the named test actually exercises.
  Reported plainly rather than adjusted.
- The mutation *is* caught, by
  `test_the_shared_limit_is_measured_over_displayed_slices_not_raw_levels`'s
  own internal cross-check: obtained `1.2989398205280307`, expected
  `1.2735263109207153 ± 1.3e-06` (the step-1 windows over-weight the axis's
  middle and shift the measured percentile).

Reverted; `test_slices_display.py` returned to 18/18 passed.

### Step 23 — `to_north_up` (three mutants)

**Mutant 1**: `ys = ymax - (...)` → `ys = ymin + (...)` (the no-flip version).

Result: **caught**.
- `test_north_up_puts_frame_row_zero_at_the_BOTTOM_of_the_raster` FAILED.

**Mutant 2**: `np.where(ids >= 0, gathered, np.nan)` → `gathered` (clamp
instead of mask).

Result: **caught**.
- `test_north_up_of_a_rotated_frame_fills_a_larger_box_and_masks_the_corners`
  FAILED.
- `test_north_up_never_invents_a_value_outside_the_frame` FAILED.

**Mutant 3**: `-cell` → `cell` in the returned geotransform's pixel height.

Result: **caught**.
- `test_north_up_geotransform_is_north_up_and_anchored_at_the_top_left` FAILED
  (`px_h` obtained `1.0`, expected `-1.0`).

Each mutant was reverted individually and `test_slices_display.py` confirmed
back at 18/18 passed after each revert; final state 18/18 passed.

### Step 29 — `_smooth_size` (wrap mutant)

Mutated `_smooth_size` to `return n - 1 if n > 1 else 1`.

Result: **partially caught — the second predicted failure did not occur, and
was independently verified as a real non-detection, not a fluke**.
- `test_smooth_size_is_never_smaller_than_asked_and_is_five_smooth` FAILED as
  predicted: `AssertionError: _smooth_size(2) = 1 would WRAP the convolution`.
- `test_padding_to_a_smooth_size_does_not_change_the_answer` did **NOT** fail
  at any of its three parametrizations (`(37,41,3)`, `(100,100,8)`,
  `(213,209,10)`), contrary to the brief's expectation that "at least one
  parametrisation" would fail. I verified this independently with a
  standalone script comparing the correctly-padded convolution against the
  exactly-one-short one for `(37, 41, 3)`: max absolute difference between
  the cropped results was `2.74e-14` (floating-point noise) — bit-identical.
  Mechanism: with an FFT circular-convolution shape exactly one short of the
  safe linear-convolution size, the wraparound aliasing lands exactly at
  index 0 (mod M) in each padded dimension — which sits outside the crop
  window `[r : r+ny, r : r+nx]` for any `r >= 1`, since the crop starts at
  `r`, not `0`. So this specific "off by exactly one" undersizing is
  invisible to the crop for every radius the parametrization uses. The wrap
  invariant is genuinely enforced only by `_smooth_size`'s own direct test
  (`m >= n`), not by the agreement test. Reported plainly, per instruction,
  rather than adjusting the claim that this test is "load-bearing" against
  this specific mutant.

Reverted; `test_slices_fill.py` returned to 18/18 passed.

## Other observed deviations from the brief's step-by-step predictions
(not among the five required mutation checks, noted for completeness)

- **Step 2** expected "3 errors"; actual behaviour was one collection-level
  `ImportError` for the whole module (pytest cannot partially collect a
  module whose import statement fails), which is the same underlying
  condition described differently.
- **Step 8/10/14/16/20/22**: because the Step 7 test file already imports all
  eight `display` names up front, the module could not be exercised in the
  intermediate states the brief describes (window-half-only, +stretch,
  +north-up). I verified the two states that are actually reachable:
  `ModuleNotFoundError` before any of `display.py` existed (matching Step 8
  exactly), and 18/18 passed once the complete module existed (matching Step
  22's final count exactly, `8 + 4 + 6 = 18`).
- **Step 26** predicted "3 FAIL on ImportError"; actual was 2 FAIL
  (`test_smooth_size_is_never_smaller_than_asked_and_is_five_smooth`,
  `test_clearing_the_kernel_cache_does_not_change_results`).
  `test_the_kernel_spectrum_cache_returns_the_same_answer_on_a_second_call`
  passed already at this point too, since it only calls the existing `fill`
  three times and checks determinism — it does not reference any of the new
  cache internals directly, so nothing about it required the cache to exist
  yet.

## Fill timings (Step 28)

Measured on this machine, 5-iteration mean per size after one warm-up call:

| Size          | Radius | Measured (padded + cached) | Brief's expectation | M10 baseline (unpadded) |
|---------------|--------|------------------------------|----------------------|---------------------------|
| 300×300       | 10     | **6.2 ms**                   | ~6 ms                | ~7 ms                     |
| 600×600       | 10     | **35.0 ms**                  | ~32 ms               | ~45 ms                    |
| 1021×1019     | 10     | **106.7 ms**                 | ~114 ms               | ~361 ms                   |

Shape of the improvement matches the brief closely (large win at the worst
case, still fast at mid-size so a slider debounces comfortably).

## Real-data test (Steps 30–31)

**Confirmation the test ran rather than skipped**: yes — verified via
`-v` output, which shows the test executing to its final assertion (not a
`SKIPPED` result), and independently by directly invoking the identical setup
in a standalone diagnostic script that produced numeric output rather than a
skip. `FILES` resolved 10 real `.DZT` files from
`packages/nsgeo-core/tests/data/local/` for both this test and the whole
`test_real_files.py` module (35 tests total in that file, including the two
pre-existing full-cube/full-stack tests, all of which continue to pass).

**The two measured limits and two median indices** (Step 31's requested
numbers), from `FILES[:4]`, `thickness=10`, `UnipolarClip()`:

- `shared_limit(cube, 10, clip)` = **2.516453001499176** ("correct")
- `UnipolarClip().limit(cube.mean)` = **2.7177778840065017** ("over_raw_levels")
- `median(to_index8_unipolar(shown, correct))` = **79.0**
- `median(to_index8_unipolar(shown, over_raw_levels))` = **73.0**

First assertion (`correct < over_raw_levels`) **passes**: `2.5165 < 2.7178`.
Second assertion (`79.0 > 1.5 * 73.0 = 109.5`) **fails**: `79.0` is not
`> 109.5`.

### Investigation of the failing magnitude assertion

Before accepting this as a real-data finding rather than a bug, I checked
`shared_limit`'s behaviour across a range of thicknesses on the same real
cube, and the depth-autocorrelation structure of the real, processed data:

| thickness | `shared_limit` |
|-----------|-----------------|
| 1         | 2.7244 (≈ `over_raw_levels`, as expected at thickness 1) |
| 2         | 2.7059 |
| 5         | 2.6757 |
| 10        | 2.5165 |
| 20        | 2.1655 |
| 40        | 1.7333 |
| 90        | 1.2646 |

This is smooth and monotonically decreasing, exactly the behaviour
`shared_limit` is specified to have. Separately, adjacent-level correlation
among covered cells in this real, `amp_envelope`-processed cube measures
**0.95–0.99** at every depth sampled — i.e., consecutive time levels are
nearly identical, because envelope detection is itself a smoothing operation
on the analytic signal. The synthetic fixture used everywhere else in this
plan's tests (`_cube_with_varying_levels`) instead uses i.i.d. Gaussian noise
per level with zero cross-level correlation, which is why it shows a much
larger reduction (`over_slices / over_levels < 0.8`, measured ~0.55) than
this real cube does at the same thickness (0.926). At `thickness=10` the
real data's near-total depth correlation means a 10-level window barely
differs from any single level within it, so the percentile — and therefore
the displayed colour-index median — barely moves. Larger thicholds (20, 40,
90) show progressively larger, expected reductions, confirming the mechanism
rather than a bug: `shared_limit`, `plan_windows`, and `limit_over_slices`
are behaving exactly as designed; this specific real corpus simply does not
produce enough depth decorrelation at `thickness=10` to clear the brief's
`1.5x` bar.

I did not alter the test's `1.5` threshold or the production code, per the
explicit instruction to use the brief's exact values verbatim. This is
flagged as the task's one open item for the plan's reviewer to resolve
(recalibrate the bar for this real corpus/thickness, choose a different
thickness for this specific check, or accept the finding and adjust the
plan's expectation).

## Files touched

- `packages/nsgeo-core/src/nsgeo/slices/frame.py` — added `slice_extent`.
- `packages/nsgeo-core/src/nsgeo/slices/display.py` — new module: `SliceWindow`,
  `plan_windows`, `window_times_ns`, `window_depths_m`, `window_label`,
  `limit_over_slices`, `shared_limit`, `to_north_up`.
- `packages/nsgeo-core/src/nsgeo/slices/fill.py` — added `_smooth_size`,
  `_kernel_spectrum`, `clear_kernel_cache`; `fill` now pads to a smooth FFT
  size and uses the cached spectrum.
- `packages/nsgeo-core/src/nsgeo/slices/__init__.py` — re-exports the new
  names, alphabetical within each import line, matching the existing
  `# noqa: F401` convention.
- `packages/nsgeo-core/tests/test_slices_frame.py` — 3 new tests for
  `slice_extent`.
- `packages/nsgeo-core/tests/test_slices_display.py` — new file, 18 tests.
- `packages/nsgeo-core/tests/test_slices_fill.py` — 6 new tests (4 new test
  functions, one parametrized ×3).
- `packages/nsgeo-core/tests/test_real_files.py` — 1 new real-data test
  (currently failing its magnitude assertion; see above).

## Final verification

- `./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q`
  → **529 passed, 1 failed, 2 skipped**.
- `./.venv/bin/ruff check .` → All checks passed.
- `./.venv/bin/ruff format --check .` → 110 files already formatted.
- `./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`
  → Success: no issues found in 32 source files.

Not pushed, per instruction — left for the controller.

---

## Fix round 1/5 — Ruling D: the real-data magnitude bar is removed

The coordinator confirmed both findings above (Step 11 mutant 2, Step 29) as
corrections to the brief, and identified the real-data test's `1.5x`
threshold as a defect in the brief itself — for two reasons: `thickness=10`
at `dz=0.2165 ns` is a 2.2 ns window, shorter than this 350 MHz antenna's
~2.9 ns pulse width (spec 6.6 and Conyers require at least one pulse width
per slice), and the `1.5x` figure was generalised from an M10 measurement on
different data without checking it held on this corpus.

### What changed

In `test_the_shared_stretch_on_a_real_cube_uses_most_of_the_colour_table`
(`packages/nsgeo-core/tests/test_real_files.py`):

1. `thickness = 10` → `thickness = 23` (~5.0 ns at this dz, satisfying spec
   6.6's one-pulse-width minimum), with a comment explaining why.
2. Deleted the `np.median(...) > 1.5 * np.median(...)` magnitude assertion.
3. Added the exact-mechanism assertion:
   `assert correct == pytest.approx(float(np.percentile(shown, clip.percentile)), rel=1e-6)`.
4. Kept a direction-only assertion:
   `assert np.median(to_index8_unipolar(shown, correct)) > np.median(to_index8_unipolar(shown, over_raw_levels))`.
5. Extended the docstring with the thickness rationale and the measured
   numbers (2.724 / 2.166 / 1.265 at thickness 1 / 20 / 90; 0.95–0.99
   adjacent-level correlation; ~0.55 reduction on the synthetic fixture by
   contrast), and an explicit instruction not to re-add a magnitude
   threshold to this test.

All text matches the coordinator's instructions exactly, including the
`pytest.approx` mechanism assertion and the direction-only final assertion.
`pytest` was already imported in this module (line 13), so no import change
was needed.

### Covering run

```
./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_real_files.py -q -k shared_stretch -v
```
Result: **1 passed, 0 skipped** (34 collected / 33 deselected / 1 selected).

### Mutation re-check on the amended test

**Mutant 1** — `shared_limit` body → `return clip.limit(cube.mean)` (M10's
exact wrong implementation):

Result: **caught**, but by the *first* assertion rather than the new
exact-mechanism one, because under this mutant `correct` and
`over_raw_levels` become the identical quantity:
```
assert correct < over_raw_levels
E       assert 2.7177778840065017 < 2.7177778840065017
```
The coordinator expected the exact-mechanism assertion to be what kills it;
in fact the pre-existing direction assertion already does, since the
mutation collapses `correct` and `over_raw_levels` to the same value before
execution ever reaches the percentile check. Reported plainly rather than
reshaped to match the prediction. The mutation is still unambiguously
caught.

**Mutant 2** — `plan_windows(cube.z, thickness_levels, thickness_levels)` →
`plan_windows(cube.z, thickness_levels, 1)` inside `shared_limit` (the
windows-overlap mutant):

Result: **caught, and here the exact-mechanism assertion is exactly what
kills it**, as predicted:
```
assert correct == pytest.approx(float(np.percentile(shown, clip.percentile)), rel=1e-6)
E       assert 2.0861064910888683 == 2.0737717151641846 ± 2.1e-06
```
`correct` (2.0861064910888683, computed with overlapping step-1 windows that
double-weight mid-depths) disagrees with the abutting-window percentile
(2.0737717151641846) by far more than the `1e-6` relative tolerance.

Both mutants reverted; `test_the_shared_stretch_on_a_real_cube_uses_most_of_the_colour_table`
and the full `test_slices_display.py` suite (18/18) confirmed passing again
after each revert.

### Full verification after the fix

```
./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
```
Result: **530 passed, 2 skipped** (the same two pre-existing schema skips).

```
./.venv/bin/ruff check .
./.venv/bin/ruff format --check .
```
Result: All checks passed; 110 files already formatted.

```
./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
```
Result: Success: no issues found in 32 source files.

### Commit

`8dc5ff3` — `fix(slices): drop the real-data magnitude bar per Ruling D`
(not pushed, per instruction).

### Documentation-only corrections accepted into the plan (no code change)

Per the coordinator's request, both "prediction did not hold" findings from
the original mutation-check pass are recorded here as accepted corrections
to the brief:

- **Step 11 mutant 2** (`plan_windows`'s `range(0, z.nz - thickness_levels + 1, step_levels)`
  → `range(0, z.nz, step_levels)`): the test that actually discriminates
  this mutant is `test_overlapping_windows_match_the_specs_band_count_formula`.
  `test_abutting_windows_tile_the_axis_without_gaps_or_overlap` cannot,
  because with `thickness == step == 10` and `nz == 100`, both
  `range(0, 91, 10)` and `range(0, 100, 10)` floor to the identical sequence
  `0, 10, ..., 90` — the two forms only diverge when `thickness != step` or
  when `nz` does not leave both bounds flooring to the same last multiple.

- **Step 29** (`_smooth_size` mutated to `n - 1 if n > 1 else 1`): an FFT
  padded to exactly one less than the safe linear-convolution size produces
  a circular-convolution wraparound whose aliasing lands at index 0 (mod M)
  in each padded dimension. Because the crop window `[r : r+ny, r : r+nx]`
  always starts at `r >= 1`, that index-0 corruption sits outside the crop
  for every radius tested, so `test_padding_to_a_smooth_size_does_not_change_the_answer`
  cannot see this specific off-by-exactly-one defect at any of its three
  parametrizations (independently verified: max abs diff `2.74e-14`,
  floating-point noise). The wrap invariant (`m >= n`) is enforced only by
  `_smooth_size`'s own direct test, not by the agreement test.

---

## Fix round 2/5 — Important 1 (Ruling G), Important 2 (Ruling F), Important 3, two Minors (Ruling H)

The coordinator's review found and independently reproduced two Important
numerical defects and one plan-doc defect. Both numerical findings match
exactly the pattern this milestone targets: a green test that structurally
cannot see the defect it is named for.

### Important 1 — Ruling G: `to_north_up` sizing rounds an exact integer up

**Reproduced before fixing**, exactly matching the coordinator's numbers:
`CubeFrame(origin=(0,0), azimuth=0, cell=0.1, nx=29, ny=12)` → raster shape
`(13, 30)` (not `(12, 29)`), last column all-NaN.

**New test added first** (`test_north_up_of_an_axis_aligned_frame_has_exactly_the_frames_shape`,
verbatim from the ruling), confirmed to **FAIL** against the pre-fix code:
```
AssertionError: 29x12 at cell=0.1 gained a phantom row/column
assert (13, 30) == (12, 29)
```

**Deviation from the literal fix snippet, found and corrected before
committing**: I implemented Ruling G's exact snippet first
(`- 1e-9` on the ratio) and re-ran the new test — it still failed, now with
shape `(13, 29)` (width fixed, height still wrong). Diagnosis: the new
test's fixture uses `origin=(500000.0, 4500000.0)` (UTM-scale, as spec 6.4's
realistic case is), and at that magnitude the float round-off in
`slice_extent`'s subtraction is itself larger than `1e-9`:
- `(29, 12, cell=0.1)`: ratio residual `1.863e-9` — exceeds `1e-9`.
- `(23, 19, cell=0.05)`: ratio residual `3.725e-9` — exceeds `1e-9`.
- `(7, 3, cell=0.2)` and `(13, 11, cell=1.0)`: both comfortably under `1e-9`.

This is the identical lesson `cell_index`'s own docstring in `frame.py`
already documents: round-off from subtracting two large, similar-magnitude
floats scales with their magnitude, not with the cell size, so a fixed
epsilon that works near the origin is provably insufficient at UTM scale.
I replaced the fixed `1e-9` with a scale-aware bound following the same
`64 * eps * max(1, |coord|)` margin `cell_index` already uses (Sonnet-5
edit, credited to Ruling G's underlying intent but not its literal
constant):
```python
eps = 64.0 * np.finfo(float).eps * max(1.0, abs(xmin), abs(xmax), abs(ymin), abs(ymax)) / cell
width = max(1, int(math.ceil((xmax - xmin) / cell - eps)))
height = max(1, int(math.ceil((ymax - ymin) / cell - eps)))
```
Confirmed **PASSES** with this corrected epsilon (full `test_slices_display.py`:
19/19 passed). Also re-ran the coordinator's own 1000-sample fuzz check
(random UTM-scale origins, `cell=0.1`) against the fixed code: **0 of 1000
widths/heights tripped**, down from the coordinator's reported 102/1000.
Reported plainly per the established practice rather than silently using
the literal `1e-9` and leaving two of the ruling's own four test cases
unfixed.

### Important 2 — Ruling F: `shared_limit` silently excludes the axis tail

**Reproduced before fixing**, exactly matching the coordinator's numbers:
`nz=181, thickness=23` → 7 windows covering 161 of 181 levels (20 excluded);
`nz=40, thickness=10` (the fixture) → 4 windows covering all 40 (0 excluded,
which is why the existing test could not see the defect).

**Fix applied to `shared_limit`** exactly as Ruling F specifies: `plan_windows`
is left untouched (still whole-windows-only, since its output doubles as the
GeoTIFF's bands); `shared_limit` now appends one final, thinner tail window
when `windows[-1].k1 < cube.z.nz`. Docstring's closing paragraph updated to
state the tail-window behaviour rather than the now-false "exactly once"
claim on its own.

**Deviation from the literal test snippet, found and corrected before
committing**: I implemented the ruling's exact new assertions inside
`test_the_shared_limit_covers_every_level_exactly_once` first, and ran them
against the **pre-fix** code as instructed:
```
AssertionError: shared_limit saw 1200 values; the whole cube is 14800
```
This is the expected FAIL, but re-running the same literal assertion
against the **fixed** `shared_limit` still failed:
```
AssertionError: shared_limit saw 1600 values; the whole cube is 14800
```
Diagnosis: `SliceCube.slice_levels(k0, k1)` returns one aggregated value per
CELL per WINDOW (a `.mean(axis=0)` reduction), never one value per level —
so the true maximum `shared_limit` can ever hand to `clip.limit` is
`(n_windows * n_cells)`, not `(nz * n_cells)`. For `nz=37, thickness=10,
n_cells=400`: 3 windows before the fix (1200), 4 windows after (1600, the
newly-added tail 30-37) — never `37 * 400 = 14800`. The ruling's assertion
was arithmetically unsatisfiable regardless of the fix. I corrected it to
check the window count directly, keeping the coordinator's `_Recording`
capture mechanism and its "must still see all 37 [levels, via a tail
window]" intent:
```python
expected_n_windows = -(-odd.z.nz // 10)  # ceil(37 / 10) == 4
assert seen and seen[0].size == expected_n_windows * odd.frame.n_cells, (...)
```
Verified this corrected assertion **FAILS** against the pre-fix code
(`1200` seen, `1600` expected — 3 windows, tail dropped) and **PASSES**
against the fixed code (`1600 == 1600`). Reported plainly rather than
silently substituting a number that happened to make the literal snippet
pass.

### Important 3 — plan doc-only correction

Added an "(Amended during execution: ...)" note to Step 17 in
`docs/superpowers/plans/2026-09-19-nsgeo-slices-m11.md`, in the same shape
as the two existing amendments (Step 11, Step 29), recording that
`test_the_shared_limit_covers_every_level_exactly_once` cannot fail against
the `plan_windows(cube.z, thickness_levels, 1)` mutant — it never calls
`shared_limit` — and that the mutant is instead caught by the percentile
cross-check inside `test_the_shared_limit_is_measured_over_displayed_slices_not_raw_levels`.

### Minors (Ruling H)

1. Added `clear_kernel_cache` to the `from nsgeo.slices.fill import ...`
   line in `packages/nsgeo-core/src/nsgeo/slices/__init__.py`
   (alphabetical: `clear_kernel_cache, disc_kernel, fill`).
2. Corrected `packages/nsgeo-core/src/nsgeo/render.py`'s `UnipolarClip`
   docstring: "a limit taken over raw levels is systematically too low for
   a multi-level window" → "...too high...", matching the cited numbers
   (2.59 measured over raw levels vs. 0.87 for the correct multi-level
   window — raw-level is the larger, i.e. too high, figure). No other text
   in that M10 file touched.

### Real-data test: consistency with the tail fix

Updating `shared_limit` to include the tail window changed its own output
on the real corpus, which in turn broke the real-data test's
exact-mechanism cross-check added in the previous fix round (that
cross-check built its own `windows`/`shown` locally, via the same
`plan_windows` call, without the new tail-window step, so it now measured a
different — and, per Ruling F, wrong — set of displayed slices than
`shared_limit` itself does). Fixed by adding the identical tail-window step
to the test's own `windows` construction (imports `SliceWindow` from
`nsgeo.slices.display`), so both sides of the cross-check agree again.

**`shared_limit` on the real cube, before vs. after the tail fix, at
`thickness=23`**: **2.0738 → 2.0608** (a small drop, consistent with the
coordinator's own reviewer measurement of "2.0738 before, 2.0608 with the
tail folded in" — matched to 4 significant figures).

I also recomputed the docstring's cited `shared_limit` trend numbers
(thickness 1/20/90) after the fix, since two of the three don't evenly
divide `nz=181` and are therefore affected by the same tail-window change:
- thickness=1: **2.7244** (unchanged — `181 % 1 == 0`, no tail needed).
- thickness=20: **2.1710** (was 2.166 before the fix — small change).
- thickness=90: **2.0513** (was **1.265** before the fix — a large change).

The thickness=90 change is large because at that thickness the tail window
is just the single last level (`nz=181, thickness=90` → windows `(0,90)`,
`(90,180)`, tail `(180,181)`), and that lone level is one of the brightest
in the cube (per the coordinator's own finding, level-mean 1.169 vs. 0.858
for the included levels) — previously it was excluded entirely at large
thickness, understating how much the limit should fall; with the fix it
keeps contributing on its own, unmixed with 89 dimmer neighbours. The
sequence is still monotonically decreasing (2.7244 > 2.1710 > 2.0608 >
2.0513), just far flatter past thickness 20 than the pre-fix numbers
suggested. Updated the test's docstring to state the corrected numbers and
this explanation, so nobody re-derives the old (now-inaccurate) 1.265
figure from stale documentation.

### Full verification after round 2

```
./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_real_files.py -q -k shared_stretch -v
```
Result: **1 passed, 0 skipped**.

```
./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
```
Result: **531 passed, 2 skipped**.

**Discrepancy from the coordinator's stated expectation ("532 passed / 2
skipped, two new tests"), reported plainly**: I get 531, not 532. Only one
new pytest-collected test item exists after this round —
`test_north_up_of_an_axis_aligned_frame_has_exactly_the_frames_shape`
(Important 1). Important 2's new assertions were added inside the
*existing* `test_the_shared_limit_covers_every_level_exactly_once` function,
per the ruling's own literal snippet, rather than as a second, separately
named test — so pytest's collected-item count only rises by one, not two.
Confirmed via `pytest --collect-only`: `test_slices_display.py` collects 19
items (18 before this round + 1 new), and no other file gained a test
function.

```
./.venv/bin/ruff check .
./.venv/bin/ruff format .   # 2 files needed reformatting (long line wraps); reformatted, then re-verified clean
./.venv/bin/ruff format --check .
```
Result: All checks passed; 110 files formatted.

```
./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
```
Result: Success: no issues found in 32 source files.

### Commit

`fa8db17` — `fix(slices): UTM-scale north-up sizing, shared_limit's dropped tail`
(not pushed, per instruction).

---

## Fix round 3/5 — final pass: four Minors (all verdicted ADDRESSED for the prior five findings)

The re-review confirmed all five prior findings ADDRESSED and confirmed both
of my departures from the coordinator's literal prescriptions were correct
(including bisecting the UTM-scale epsilon and confirming it swallows at
most 71 nanometres of genuine excess span — comfortably safe in both
directions). This round is four Minors: three false documentation
statements (two false because of wording the coordinator gave me in earlier
rounds) and one test strengthening.

### Minor 1 — `shared_limit`'s false equal-weight claim

Verified the coordinator's numbers before writing anything, on the real
corpus at thickness values around the claimed non-monotone step:

| thickness | `shared_limit` |
|---|---|
| 178 | 2.0255 |
| 179 | 2.0916 |
| 180 | **2.1455** |
| 181 (no tail needed) | **0.9972** |

Matches the coordinator's cited numbers exactly. Replaced the docstring's
closing paragraph: "every level contributes exactly once and no depth is
weighted more heavily than another -- including the tail" (false, since a
tail window of `t` levels carries the same `frame.n_cells`-value weight as
a full window and so weights each of its individual levels `thickness`
times as heavily) with the coordinator's suggested text — no depth is
*omitted* or double-counted, but the tail is not equally weighted, and the
function is not monotone in `thickness_levels` as a direct consequence,
stated with the measured 2.1455/0.9972 numbers and the "under 1% across
realistic thicknesses, and conservative (clips less)" characterisation.

### Minor 2 — the plan's self-contradicting amendment note

Verified before rewriting: re-ran the `plan_windows(cube.z, thickness_levels, 1)`
mutant against the **current** `test_the_shared_limit_covers_every_level_exactly_once`
(which now does call `shared_limit`, per Round 2's Important 2 fix) and
confirmed it fails outright:
```
AssertionError: shared_limit saw 11200 values from an implied 28 window(s); expected 4 windows
```
matching the coordinator's cited "11200 seen vs 1600 expected" exactly.
Rewrote the amendment at `docs/superpowers/plans/2026-09-19-nsgeo-slices-m11.md`
(around the old lines 811-818) to record both states in sequence: the
prediction did not hold *as the test stood at Step 17* (it only called
`plan_windows` with literal arguments then), and became true again once
Ruling F's fix added a `shared_limit` call to that same test — rather than
asserting the now-outdated "never calls shared_limit" as a standing fact.

### Minor 3 — the real-data cross-check's scope

Verified the coordinator's claim independently before writing the comment:
built the correct tail `SliceWindow(161, 181)` and an overlapping tail
`SliceWindow(158, 181)` and measured the resulting percentile both ways —
**2.060750 vs. 2.060750**, indistinguishable to 6 decimal places, because
the cross-check re-derives the same "append from the last whole window's
end to nz" rule `shared_limit` itself uses rather than pinning placement
independently. (For contrast, the duplicate-first-window tail
`SliceWindow(0, 23)` gave 2.107441 — that one *is* caught.) Added a comment
in `test_real_files.py` stating plainly what the assertion does pin
(kills the `clip.limit(cube.mean)` and step-overlap mutants, since both
change the percentile's value) and does not (tail placement — pinned
instead by the exact-identity test in `test_slices_display.py`, per Minor
4 below).

### Minor 4 — strengthen the window-count assertion to pin identity

Replaced the count-only assertion in
`test_the_shared_limit_covers_every_level_exactly_once` with the
coordinator's suggested sorted-multiset comparison against a locally built
expectation (`odd.slice_levels(k0, k1)` for the four correct windows
`(0,10), (10,20), (20,30), (30,37)`), keeping the existing `_Recording`
capture mechanism. Confirmed it **PASSES** against the correct
implementation, then verified it **discriminates both wrong tails** named
in the review, each applied as a temporary one-line change to
`shared_limit`'s appended-window line and reverted after:

- **Overlapping tail** `SliceWindow(windows[-1].k1 - 3, cube.z.nz)`:
  FAILED — `1598 / 1600 (99.9%)` elements mismatched, max absolute
  difference `0.0668`.
- **Duplicate-of-the-first-window tail** `SliceWindow(0, thickness_levels)`:
  FAILED — `1587 / 1600 (99.2%)` elements mismatched, max absolute
  difference `0.0668`.

Both mutants reverted; `test_slices_display.py` confirmed back to 19/19
passed after each revert.

### Full verification after round 3

```
./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
```
Result: **531 passed, 2 skipped** — matches the coordinator's expectation
exactly this time (no new pytest-collected items were added this round;
all four Minors are docstring/comment/plan-doc text and one in-place test
strengthening).

```
./.venv/bin/ruff check .
./.venv/bin/ruff format --check .
```
Result: All checks passed; 110 files already formatted.

```
./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
```
Result: Success: no issues found in 32 source files.

### Commit

`17536ce` — `docs(slices): correct three false claims, pin tail-window identity`
(not pushed, per instruction).

This closes all findings from the task review's final pass. Per the
coordinator's note, no further review cycle is expected on Task 1 — they
will verify it themselves.
