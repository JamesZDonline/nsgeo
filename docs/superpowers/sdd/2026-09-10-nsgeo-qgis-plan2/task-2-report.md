# Task 2 report: `nsgeo.render` — amplitude to colour, numpy only

## What was implemented

`packages/nsgeo-core/src/nsgeo/render.py`, a standalone numpy-only module (no
imports from `nsgeo.processing`, no Qt/matplotlib/scipy), providing:

- `Normalizer` — a `Protocol` with `limit(data) -> float`.
- `PercentileClip(percentile=99.0, max_samples=200_000)` — limit = percentile
  of `|data|`, strided-subsampled above `max_samples` for a deterministic,
  interactive-speed estimate on large arrays. Validates `percentile` in
  `(0, 100]` and `max_samples >= 1`; returns `1.0` for all-zero or empty data.
- `FixedRange(limit_value)` — a user-chosen limit, drop-in for
  `PercentileClip`; validates `limit_value > 0`.
- `DEFAULT_COLORMAP = "grey_black_high"` and two other tables
  (`"grey_white_high"`, `"seismic"`), each a `(256, 3)` uint8 lookup table.
  `colormap_names()` lists them; `colormap(name)` returns a **copy** (so
  callers can't corrupt the shared table) and raises `KeyError` naming the
  valid options on an unknown name.
- `to_index8(data, limit)` — maps amplitude to a `uint8` index, `-limit -> 0`,
  `0 -> 128`, `+limit -> 255`, clipped and rounded; rejects non-positive
  `limit`.
- `to_rgb8(data, limit, lut)` — index-then-LUT-lookup, returns a
  C-contiguous `(H, W, 3)` uint8 array ready to wrap in a `QImage` (or any
  other image type) with zero extra copies on the front-end side.
- `decimate_columns(data, max_width)` — block-mean along the trace axis,
  handling a ragged last block via NaN-padding + `nanmean`; returns `data`
  itself (no copy) when already narrow enough.

`packages/nsgeo-core/tests/test_render.py` — the brief's test file, verbatim.

## Files changed

- `packages/nsgeo-core/src/nsgeo/render.py` (new, 143 lines)
- `packages/nsgeo-core/tests/test_render.py` (new, 137 lines)

Commit: `37f9b23` — "feat: add nsgeo.render, numpy-only amplitude-to-colour
mapping"

## TDD Evidence

**RED** — wrote `test_render.py` verbatim from the brief, then ran it before
`render.py` existed:

```
$ .venv/bin/python -m pytest packages/nsgeo-core/tests/test_render.py -q
...
ModuleNotFoundError: No module named 'nsgeo.render'
1 error in 0.19s
```

Expected and correct: the module under test does not exist yet.

**GREEN (first pass, with one real failure)** — after creating `render.py`
verbatim from the brief:

```
$ .venv/bin/python -m pytest packages/nsgeo-core/tests/test_render.py packages/nsgeo-core/tests/test_boundary.py -q
...
FAILED packages/nsgeo-core/tests/test_render.py::test_seismic_is_blue_white_red
AssertionError: assert [255, 254, 254] == [255, 255, 255]
1 failed, 17 passed in 0.22s
```

This is a genuine bug in the brief's reference `_seismic()`: it builds the
ramp with a single `np.linspace(-1.0, 1.0, 256)`. With an even-sized
256-entry table, the zero-crossing of that ramp falls at index 127.5 — not on
an integer index — so no table entry is exactly `t=0`. Index 128 (where
`to_index8` places a zero amplitude, matching its own passing test) lands at
`t = 1/255 ≈ 0.00392`, so `g = 1 - |t|` rounds to 254, not 255, and the
"white at zero" entry is a shade of grey instead. All 17 other tests
(including the real-DZT-file test — real files are present and not skipped)
passed unmodified with the brief's code as given.

**Fix applied**: `_seismic()` now builds the ramp from two linear segments
that meet exactly at index 128 (`np.linspace(-1, 0, 129)` for indices 0–128,
`np.linspace(0, 1, 128)[1:]` for indices 129–255), so `t[128] == 0.0` exactly
regardless of table parity. Nothing else in `render.py` was changed from the
brief's code — `PercentileClip`, `FixedRange`, `_grey`, `to_index8`,
`to_rgb8`, and `decimate_columns` are verbatim.

**GREEN (after fix)**:

```
$ .venv/bin/python -m pytest packages/nsgeo-core/tests/test_render.py packages/nsgeo-core/tests/test_boundary.py -q
..................
18 passed in 0.19s
```

```
$ .venv/bin/python -m pytest packages/nsgeo-core/tests/test_render.py -v
... (16 items)
test_real_file_renders_with_both_extremes_present PASSED
============================== 16 passed in 0.18s ==============================
```

## Full verification

```
$ .venv/bin/python -m pytest packages/nsgeo-core/tests -q
245 passed, 2 skipped in 0.65s
```
(baseline before this task: 229 passed, 2 skipped — 16 new tests, 0 new
skips: the ten real `.DZT` symlinks in `tests/data/local/` are present, so
`test_real_file_renders_with_both_extremes_present` ran for real rather than
skipping.)

```
$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
42 files already formatted

$ .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo
Success: no issues found in 20 source files
```

## Empirical performance check (not part of the brief's tests; done for diligence)

The ten real `.DZT` fixtures under `tests/data/local/` stitch column-wise to
exactly `(512, 6301)` — the same shape cited in the plan's performance
figures — so I timed the hot path against it directly rather than trust a
synthetic array of the same shape:

- Full-percentile `limit()` + `to_rgb8()` (no subsampling,
  `max_samples=data.size`): steady-state ~140 ms (median of 8 warm runs;
  min 139.6 ms), versus the plan's cited ~120 ms.
- Default `PercentileClip()` (200k-sample subsample): ~110 ms end to end.
- Breakdown of the full-percentile path: `limit()` ~60 ms, `to_index8` alone
  ~27 ms, `lut[idx]` fancy-indexing + `ascontiguousarray` copy ~54 ms.

The ~140 ms is somewhat above the plan's ~120 ms figure. I did not change
any of the hot-path code from the brief's implementation — `PercentileClip`,
`to_index8`, and `to_rgb8` are verbatim; only `_seismic()` (a one-time
256-entry table built once at import time, irrelevant to the per-render
hot path) was touched. I read the ~140 ms as measurement/hardware variance
against whatever machine produced the plan's figure, not a regression
introduced by this change, since there is no prior version of this code to
regress from and the algorithm matches the brief's spec exactly. Flagging
it for visibility in case the plan's number was load-bearing for a later
task's budget.

## Self-review

- **Completeness against the brief**: every named symbol in the "Produces"
  interface list is present with the exact signature given:
  `Normalizer.limit`, `PercentileClip(percentile, max_samples)`,
  `FixedRange(limit_value)`, `DEFAULT_COLORMAP`, `colormap_names()`,
  `colormap(name)`, `to_index8(data, limit)`, `to_rgb8(data, limit, lut)`,
  `decimate_columns(data, max_width)`.
- **Naming**: matches the brief's interface list verbatim; no renaming.
- **YAGNI**: no extra public symbols, no extra colormaps, no extra
  parameters beyond the brief. The two non-default colormaps
  (`"grey_white_high"`, `"seismic"`) are both exercised by the brief's own
  tests (`test_every_colormap_is_a_256_by_3_uint8_table`,
  `test_seismic_is_blue_white_red`), so they are not speculative additions.
- **Tests verify behaviour, not implementation**: shape/dtype/contiguity
  checks, symmetry checks (`idx[0]+idx[1]==255`), copy-isolation
  (`test_colormap_returns_a_copy`), and validation-raises tests all assert
  observable behaviour. The real-file test asserts a domain invariant (a
  direct-wave-clipped GPR trace must reach both index extremes) rather than
  a hardcoded implementation detail. These are the brief's tests, unmodified.
- **Pristine test output**: no warnings, no xfails, no flaky/timing-sensitive
  assertions (the subsample determinism test recomputes the same striding
  the implementation uses, so it is testing the *contract* — deterministic,
  matches manual striding — not a magic number).
- **Module boundary**: `test_boundary.py`'s AST walk passed, confirming
  `render.py` has no forbidden module-level imports; visual inspection
  confirms only `math` (stdlib), `dataclasses`, `typing.Protocol`, and
  `numpy` are imported.
- **Docstrings**: kept the brief's "why" framing (display gain vs.
  processing step) verbatim in the module docstring; added one docstring
  paragraph to `_seismic()` explaining the two-segment construction and why
  a single linspace doesn't work for an even-sized table.

## Concerns

1. **One deviation from the brief's literal code**: `_seismic()`'s ramp
   construction was changed from a single `np.linspace(-1, 1, 256)` to two
   segments meeting at index 128, because the brief's given code fails its
   own `test_seismic_is_blue_white_red` (off-by-one rounding at the
   zero-crossing of an even-length table — demonstrated in the RED/GREEN
   evidence above). This is a narrow, mechanical fix confined to one
   private helper function; it does not touch any public signature, the
   default colormap, or the hot rendering path. Flagging for the reviewer
   since the task said to implement the brief's code and I did deviate from
   one function's literal body to make its own test pass.
2. Local full-percentile timing (~140 ms) runs somewhat above the plan's
   cited ~120 ms figure on this machine; not attributable to any choice made
   in this task (see performance section above), but noted for visibility.

No other concerns. Scope, file layout, and public API match the brief
exactly.

---

# Fix round 1 (review response)

Reviewer accepted the `_seismic()` deviation (verified independently, ruled
in my favour) and raised two Important findings, both addressed below. No
Minors were addressed — the reviewer explicitly deferred the unreferenced
`Normalizer` protocol, unreachable validation branches, the 1-D `IndexError`
message, and the round-half-to-even tie exceptions to the whole-branch
review, and I left them alone as instructed.

## Finding 1: NaN unhandled in both directions

**`PercentileClip.limit`** (`render.py:52` at review time): `np.percentile`
propagates NaN, and `nan > 0.0` is `False`, so a single NaN anywhere in the
sampled data silently collapsed the limit to the all-zero fallback of `1.0`
— on data whose real amplitudes are in the thousands, that saturates the
whole display to black/white. Fixed by masking to the finite samples before
computing the percentile:

```python
finite = flat[np.isfinite(flat)]
if finite.size == 0:
    return 1.0
lim = float(np.percentile(np.abs(finite), self.percentile))
```

I used an explicit `np.isfinite` mask rather than `np.nanpercentile` for two
reasons: it also excludes `+inf`/`-inf` (the finding's fix note asked for
"the limit computed from the finite samples", not just NaN-safe), and it
avoids `nanpercentile`'s "All-NaN slice encountered" `RuntimeWarning` on an
all-NaN input, which the all-NaN-input test below pins as warning-free by
construction (the empty-after-masking case returns `1.0` before any
percentile call is made).

**`to_index8`** (`render.py:119` at review time): `np.round(...).astype(np.uint8)`
on data containing NaN raised `RuntimeWarning: invalid value encountered in
cast` and silently produced index `0` (pure white) for the NaN pixel —
indistinguishable from a strong negative reflector. Fixed by masking NaN to
the neutral middle of the table (127.5, which rounds to 128 same as a true
zero amplitude) before clipping:

```python
nan_mask = np.isnan(scaled)
if nan_mask.any():
    scaled[nan_mask] = 127.5
```

The `.any()` gate matters for finding 2 (below): it costs one cheap
reduction pass and is skipped past on the common NaN-free path rather than
always paying for a replacement pass.

**Reachability confirmed independently**: I read `processing/gain.py` and
traced the path the reviewer described. `GainAgc.apply` (gain.py:59-61)
computes `rg.data * (self.target / np.maximum(rms, self.eps))`. With
`eps=0.0` (a value its own `ParamSpec` at gain.py:41-53 declares as `min=0.0`,
i.e. explicitly allowed) and an all-zero leading trace, `rms=0`, so
`np.maximum(0, 0) = 0`, `target / 0 = inf` (not NaN — division by exact zero
is `inf` in IEEE float, no warning), and then `0 * inf = NaN`. Confirmed this
is real, not hypothetical, and did not need to add a cross-module
integration test to `test_render.py` to pin it — the reviewer's citation
was for justification, and the fix and its tests are scoped to `render.py`
as the two Important findings specify.

## Finding 2: hot path did ~2.4x the necessary work

Applied the changes the finding described, plus one refinement discovered
while re-measuring on the real stitched dataset:

- **`to_index8`**: rewrote as one array allocated once (`data / limit`, which
  is guaranteed to allocate — see mutation note below) and reused in place
  via `+=`, `*=`, `np.clip(..., out=scaled)`, `np.rint(..., out=scaled)`,
  instead of a chain of temporaries plus `np.round`.
- **`to_rgb8`**: `lut.take(idx, axis=0)` instead of `lut[idx]` fancy
  indexing. Confirmed by profiling on the real 512 x 6301 stitched dataset
  that `.take` is markedly cheaper than fancy indexing for this shape (see
  measurements below); `np.ascontiguousarray` around it is unchanged and, as
  the reviewer noted, is a no-op here since `.take`'s result is already
  C-contiguous — I do not repeat the earlier report's incorrect claim that
  it was copying anything.
- **`decimate_columns`**: replaced NaN-padding the whole array to a multiple
  of the block size and taking `nanmean` throughout, with a plain
  `.mean(axis=2)` over the full blocks plus one plain `.mean(axis=1)` for
  the single ragged tail block (when one exists). This avoids paying
  NaN-detection overhead on every element of every block for the sake of at
  most one partial block.
- **Refinement beyond the finding's suggestion**: the finding's suggested
  `np.nan_to_num(scaled, nan=127.5)` for `to_index8`'s NaN guard works, but
  I measured it costing ~12-40 ms by itself on the real stitched array
  (noisy across repeated runs, but consistently the single most expensive
  step in the function after the initial divide) — because it also checks
  for and replaces `+inf`/`-inf`, which `to_index8` doesn't need (the
  existing `np.clip` already handles infinities correctly with no warning).
  I replaced it with an explicit `np.isnan(...).any()` gate that only pays
  for the replacement pass when a NaN is actually present, which is the
  rare AGC-edge-case path, not the common one. Verified this is not a
  premature/unjustified optimisation by profiling both variants on the real
  512 x 6301 array before choosing (see below).

**Mutation safety**: switching to in-place ops raises the mutation risk, so
I re-checked this specifically rather than asserting it. `data / limit`
(true division of an ndarray by a scalar) always returns a new array — it
is never in-place unless `/=` is used explicitly — so even when
`np.asarray(data, dtype=np.float64)` returns the *same* object as `data`
(when `data` is already a C-contiguous float64 array, `asarray` makes no
copy), the subsequent `/ limit` still allocates fresh memory before any
in-place op touches it. Added
`test_to_index8_does_not_mutate_its_input` and
`test_decimate_columns_does_not_mutate_its_input` to pin this as a test
rather than an assertion in prose.

**Equivalence, pinned as tests, not claimed**: added
`test_to_index8_matches_the_reference_formula` (exact match against the
original one-expression formula, `np.testing.assert_array_equal`),
`test_to_rgb8_matches_fancy_indexing` (exact match between `to_rgb8`'s
output and plain `lut[idx]` on the same index array), and
`test_decimate_columns_matches_the_reference_nan_padded_mean` (allclose
match, random data with a ragged tail, against literally the old
NaN-pad-then-nanmean implementation reproduced inline in the test as the
independent reference).

### Performance re-measurement (real stitched 512 x 6301 dataset)

Same ten real `.DZT` files as before, stitched to `(512, 6301)`. Min /
median of 11 warm runs per measurement, limit precomputed once outside each
timed call so `to_index8`/`to_rgb8` timings are isolated from `limit()`'s
cost:

| stage | before this fix round | after this fix round |
|---|---|---|
| `to_index8` (limit precomputed) | ~27 ms (round-1 measurement) | ~22.8 / 23.6 ms |
| `to_rgb8` (limit precomputed) | ~75-80 ms (round-1 measurement, fancy indexing) | ~42.3 / 44.0 ms |
| `decimate_columns(max_width=2000)` | ~55.7 ms (round-1 measurement) | ~9.2 / 10.1 ms |
| full pipeline, full percentile (`limit()` + `to_rgb8()`) | ~140 ms steady-state (round-1) | ~118.1 / 119.9 ms |
| full pipeline, default 200k-subsample `limit()` + `to_rgb8()` | ~110 ms (round-1) | ~77.2 / 78.4 ms |

The full-percentile end-to-end path now lands almost exactly on the plan's
~120 ms budget (was ~140 ms before this round), and the interactive
(default-subsample) path is ~77 ms, comfortably under it. This directly
answers the round-1 report's open concern about the ~140 ms figure: it was
construction (fancy indexing + NaN-padded `nanmean` + a chain of temporary
arrays), not machine variance, exactly as the reviewer said.

**Docstring correction** (`PercentileClip`, `render.py:30-41`): corrected
the misattributed "~120 ms" figure, which the brief's original docstring
attached to the full percentile inside `limit()` alone. Re-measured: `limit()`
alone (full percentile, no subsample) is ~70-88 ms on this dataset, and the
default 200k-subsample is ~34 ms — neither is 120 ms, and the plan's figure
is for the whole normalise + LUT render. Rather than replace one
machine-specific number with another (which would go stale the same way),
the corrected docstring now just states that the ~120 ms budget belongs to
the whole render, not to this method alone, without asserting a new
machine-specific number for `limit()` in its place.

## Covering tests run

Scoped run (not the whole suite) for the amended code, exactly as the round
contract asked:

```
$ .venv/bin/python -m pytest packages/nsgeo-core/tests/test_render.py packages/nsgeo-core/tests/test_boundary.py -v
============================= test session starts ==============================
...
packages/nsgeo-core/tests/test_render.py::test_zero_maps_to_mid_grey_and_extremes_to_black_and_white PASSED [  3%]
packages/nsgeo-core/tests/test_render.py::test_index_is_symmetric_about_zero PASSED [  7%]
packages/nsgeo-core/tests/test_render.py::test_to_rgb8_shape_dtype_and_contiguity PASSED [ 11%]
packages/nsgeo-core/tests/test_render.py::test_to_rgb8_matches_fancy_indexing PASSED [ 15%]
packages/nsgeo-core/tests/test_render.py::test_non_positive_limit_is_rejected PASSED [ 19%]
packages/nsgeo-core/tests/test_render.py::test_to_index8_nan_is_neutral_not_a_reflector PASSED [ 23%]
packages/nsgeo-core/tests/test_render.py::test_to_index8_does_not_mutate_its_input PASSED [ 26%]
packages/nsgeo-core/tests/test_render.py::test_to_index8_matches_the_reference_formula PASSED [ 30%]
packages/nsgeo-core/tests/test_render.py::test_every_colormap_is_a_256_by_3_uint8_table PASSED [ 34%]
packages/nsgeo-core/tests/test_render.py::test_seismic_is_blue_white_red PASSED [ 38%]
packages/nsgeo-core/tests/test_render.py::test_unknown_colormap_names_the_options PASSED [ 42%]
packages/nsgeo-core/tests/test_render.py::test_colormap_returns_a_copy PASSED [ 46%]
packages/nsgeo-core/tests/test_render.py::test_percentile_clip_is_symmetric_and_ignores_sign PASSED [ 50%]
packages/nsgeo-core/tests/test_render.py::test_percentile_clip_on_all_zero_data_returns_one PASSED [ 53%]
packages/nsgeo-core/tests/test_render.py::test_percentile_clip_ignores_non_finite_samples PASSED [ 57%]
packages/nsgeo-core/tests/test_render.py::test_percentile_clip_on_all_nan_data_returns_one_without_warning PASSED [ 61%]
packages/nsgeo-core/tests/test_render.py::test_percentile_clip_subsamples_large_arrays_deterministically PASSED [ 65%]
packages/nsgeo-core/tests/test_render.py::test_percentile_clip_validates_its_arguments PASSED [ 69%]
packages/nsgeo-core/tests/test_render.py::test_fixed_range_is_a_drop_in_normalizer PASSED [ 73%]
packages/nsgeo-core/tests/test_render.py::test_decimate_columns_block_means_and_is_a_no_op_when_narrow PASSED [ 76%]
packages/nsgeo-core/tests/test_render.py::test_decimate_columns_handles_a_ragged_last_block PASSED [ 80%]
packages/nsgeo-core/tests/test_render.py::test_decimate_columns_does_not_mutate_its_input PASSED [ 84%]
packages/nsgeo-core/tests/test_render.py::test_decimate_columns_matches_the_reference_nan_padded_mean PASSED [ 88%]
packages/nsgeo-core/tests/test_render.py::test_real_file_renders_with_both_extremes_present PASSED [ 92%]
packages/nsgeo-core/tests/test_boundary.py::test_no_forbidden_module_level_imports PASSED [ 96%]
packages/nsgeo-core/tests/test_boundary.py::test_src_tree_is_actually_being_scanned PASSED [100%]

============================== 26 passed in 0.22s ==============================
```

## TDD evidence for this round

**RED** — confirmed both new NaN tests fail against the pre-fix (commit
`37f9b23`) code before touching `render.py`, by temporarily swapping the old
file back in, running just the new tests, then restoring:

```
$ .venv/bin/python -m pytest packages/nsgeo-core/tests/test_render.py -q -k "nan or mutate or matches"
...
FAILED packages/nsgeo-core/tests/test_render.py::test_to_index8_nan_is_neutral_not_a_reflector
...
E       RuntimeWarning: invalid value encountered in cast
packages/nsgeo-core/src/nsgeo/render.py:119: RuntimeWarning
1 failed, 6 passed, 17 deselected in 0.13s
```

```
$ .venv/bin/python -m pytest packages/nsgeo-core/tests/test_render.py -q -k "test_percentile_clip_ignores_non_finite_samples or test_percentile_clip_on_all_nan_data_returns_one_without_warning"
...
FAILED packages/nsgeo-core/tests/test_render.py::test_percentile_clip_ignores_non_finite_samples
E       assert 1.0 == 4.0
1 failed, 1 passed, 22 deselected in 0.11s
```

Both failures are exactly the defects the reviewer described: the cast
warning plus wrong index for `to_index8`, and the limit collapsing to `1.0`
instead of the finite data's real percentile for `PercentileClip`. (The
`does_not_mutate` and `matches_the_reference`/`matches_fancy_indexing`/
`matches_the_reference_nan_padded_mean` tests are equivalence pins for the
refactor, not bug reproductions, so they pass against both old and new code
by design — they weren't expected to be RED.)

**GREEN** — after the fix, restored the working file (bit-for-bit identical
to before the swap, confirmed with `diff`) and re-ran; all 26 pass (shown
above).

## Full verification after this round

```
$ .venv/bin/python -m pytest packages/nsgeo-core/tests -q
253 passed, 2 skipped in 0.68s
```
(up from 245 passed / 2 skipped after round 1 — 8 new tests, 0 new skips)

```
$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/ruff format --check .
42 files already formatted

$ .venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo
Success: no issues found in 20 source files
```

## Concerns after this round

None. Both Important findings are fixed and covered by tests that fail
against the pre-fix code and pass against the fix; the performance
regression is not just closed but the full-percentile path now lands
almost exactly on the plan's cited ~120 ms budget on the real dataset the
plan measured against, and the interactive default-subsample path is
comfortably under it. The Minors the reviewer deferred were left untouched
as instructed.
