# Task 2 report: Bad samples (#43, #42)

**Status:** DONE (one note on speed against spec §4.1's 2x rule, under Concerns)
**Commits (pushed to origin/nsgeo-step-edges):**
- `8449263` fix(processing): one bad sample damages only itself; first break skips bad samples (#43, #42)
- `432d735` test(timezero): a bad sample on the first-break row itself still picks it (#42). Added after mutation probe M9 survived.

BASE `ab466c0`.

## What was implemented

- **`running_mean(a, window, axis=0)`** in `processing/_util.py`. The signature, the shrinking-edge rule and the `window < 1` refusal are unchanged, and `window == 1` still returns a copy with bad samples kept. Each output is the mean of the finite samples in `[i - w//2, i - w//2 + w)`, with `w` capped at the axis length as before (ruling R3). A window with no finite sample gives NaN. No RuntimeWarnings: the 0/0 and the fast-path `np.sum` are inside `errstate`.
- **`refuse_non_finite(data, consequence)`** in `_util.py` raises `ValueError(f"{bad} of {n} traces hold samples that are not finite; {consequence}")`. Here `bad` counts the columns holding any NaN or inf, and `n = data.shape[1]`.
- **BackgroundMean** subtracts each row's mean over its finite samples. A row with no finite sample subtracts NaN, which touches only samples that were already bad. It runs one code path. On clean data this is bit-identical to the old `mean(axis=1)`: the same reduction, divided by the same integer count.
- **Bandpass and AmpEnvelope** call `refuse_non_finite` first in `apply`, with the consequence "the filter would spread each one along its whole trace". **BackgroundSvd** uses "the decomposition cannot run on them". **migrate_fk** now calls the shared helper with its own wording ("one of them would spread across the whole image through the transform"), so the message is unchanged.
- **Time zero:** `_first_break_or_none(rg, threshold) -> int | None` builds the envelope from each row's mean `|x|` over its finite samples. Rows with no finite value, including inf from overflow, are never picked, and the peak is the largest finite value. It returns None when no row is usable or the peak is ≤ 0.
  - `first_break_row` keeps its signature and returns `0 if None`.
  - `TimeZero._pick`, in first-break mode, raises `"Time zero found no first arrival: <reason>."`. The reason is "every sample on this line is zero" when all samples are finite, "no sample on this line is a finite number" when none is, and "every sample on this line is zero or not a finite number" when they are mixed. Sample mode is unchanged.
- Dewow, AGC and sliding background have no code changes. They inherit the new behaviour through `running_mean`. AGC's `x²` turns NaN and inf into non-finite values, which are left out.

## The running_mean method and why

It uses a **compensated (two-sum) cumulative sum over a zero-padded array**, with a fast path for clean data.

1. **Padding.** The array is padded with zeros: `w//2` before and `w - w//2 - 1` after. Every window is then `padded[i:i+w]`, so the edges need no gathers or special cases. The padding sums to zero and is not counted.
2. **Clean data.** The fast-path check is `isfinite(np.sum(a))`. Any NaN or inf makes the total non-finite, and finite data that overflows simply takes the masked path, which still gives the right answer. On this path the counts are the old clipped `hi - lo`.
3. **Data with bad samples.** Only finite values are copied into the padding (`np.copyto(..., where=finite)`). The counts come from an `int64` cumulative sum of the finite mask, which is exact.
4. **Accuracy.** `np.cumsum` is `add.accumulate`, and numpy documents that each prefix is `fl(previous + x)`. Knuth's two-sum therefore recovers exactly what each addition dropped, in five vectorised operations. A second cumulative sum accumulates those dropped amounts. Each window sum is `(S[i+w] - S[i]) + (C[i+w] - C[i])`. Beside a huge value both `S` ends are about the same size, so their difference is exact (Sterbenz), and `C` restores what rounding lost. The window's mean is accurate to rounding relative to the window itself.
5. **Alternatives rejected.**
   - A sliding-window exact sum costs O(n·w), about 179M additions for `window_traces=200` on 512 × 1751, which is too slow.
   - A fallback based on an error bound needs a per-window magnitude, which means another cumulative sum, plus gathers for the flagged windows. The 1e12 case flags every later window anyway.
   - The two-sum costs a fixed few passes and needs no thresholds.
6. **Test reference.** The tests compare against a direct loop that sums with `math.fsum`, which is exactly rounded. A naive `np.sum` reference has its own rounding of about 1e-15, so on a window whose mean is near zero through cancellation it could miss `rtol=1e-12` by the reference's own error. With fsum, the test measures our error, not the reference's.

Sanity checks done outside the tests:
- empty axis;
- `n == 1`;
- window longer than the line (`[1,2,3]` at window 10 gives `[1.5, 2, 2.5]`, the same as today);
- negative axis;
- Fortran-ordered input bit-identical to C-ordered input;
- `[nan, inf, -inf, 1]` at window 2;
- no warnings with `warnings.simplefilter("error")`.

## TDD evidence

**RED.** I first added a do-nothing `refuse_non_finite` stub, so that `test_processing_base.py` would collect and the tests would fail on behaviour rather than on an import error. Then:

`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/{test_processing_base,test_steps_timezero_dewow,test_steps_gain,test_steps_background,test_steps_bandpass,test_steps_amplitude}.py -q -p no:cacheprovider`
gave `21 failed, 129 passed`. Every new test failed for its stated reason:

| test | failure |
|---|---|
| `running_mean_skips_nan_and_inf` | NaN location mismatch |
| `no_finite_sample_is_nan` | `assert nan == 1.0` at row 2 (NaN carried past the window) |
| `keeps_precision_beside_a_huge_value` | 197/197 mismatched, max relative difference 0.037 (e.g. 0.0878173828125 vs 0.08782871721067873) |
| `refuse_non_finite_counts_traces…` | DID NOT RAISE (stub) |
| `one_nan_through_the_users_stack` | 70,485 non-finite samples starting `[97, 0]` (no crop, then spread) |
| dewow nan / inf | non-finite at `[92,300]`… (420 samples), not just `[100,300]` |
| time zero 300-nan / 300-inf | `first_break_row` gave 0 / 300, expected 49 |
| time zero all-zero / all-NaN | DID NOT RAISE |
| AGC nan | non-finite from `[55,300]` |
| AGC inf | `[100,300]` plus NaN from `[151,300]` |
| AGC cap | `assert np.False_` (cap broken) |
| background_mean nan / inf | whole row 100 non-finite (`[100,0]…`) |
| background_sliding nan / inf | `[100,201]…` (every window holding it) |
| SVD | "Regex pattern did not match" (it was numpy's LinAlgError "SVD did not converge") |
| bandpass, envelope | DID NOT RAISE |

`test_mean_of_a_row_with_no_finite_sample_touches_only_bad_samples` passed at RED, as expected. It pins behaviour the brief keeps (an all-bad row subtracts NaN and touches only bad samples), not new behaviour.

**GREEN.** The same command plus `test_steps_migration.py` gave **189 passed** (after `432d735`). This includes:
- all the new tests above;
- the two row-49 cases;
- Task 1's `test_a_real_diffraction_collapses_at_its_measured_velocity[FILE__033…]` and `[FILE__032…]`, which pass with their thresholds untouched.

## Suites

- **Core:** `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests -q -p no:cacheprovider` gave **1284 passed, 4 skipped** in 221 s (run on `8449263`'s tree; `432d735` only adds two parametrized cases, and that file was rerun: 27 passed).
- **QGIS processing set**, each file run with the given command. I confirmed with a temporary probe test, since removed, that `.venv-qgis` imports this worktree's `nsgeo-core/src` through the tests' conftest.

| file | result |
|---|---|
| test_plugin_processing_dock.py | 31 passed |
| test_plugin_param_form.py | 55 passed |
| test_plugin_difference_presets.py | 12 passed |
| test_plugin_session.py | 126 passed |
| test_plugin_profile_dock.py | 119 passed |
| test_plugin_time_cutoff.py | 13 passed |
| test_plugin_gain_strip.py | 44 passed |
| test_plugin_survey_dock.py | 80 passed |
| test_plugin_site_scope.py | 162 passed |
| test_plugin_slices_engine.py | 74 passed |
| test_plugin_layers.py | 110 passed |
| test_plugin_grid_velocity_dialog.py | 29 passed |
| test_plugin_velocity_dialog.py | 84 passed |

- **QGIS tests changed:** none. No test in the set runs first-break Time zero on all-zero data.
- **Lint:** `ruff check packages` and `ruff format --check packages` are clean (224 files formatted).
- **mypy (CI line):** "Success: no issues found in 51 source files".

## Timings (Step 6)

Grid 2 FILE__033, 512 × 1751, `dt` 0.21653 ns. Each figure is the best of 15 runs, in ms. `origin/main` (c00b4fb) and this branch were run back to back, three rounds each, from a throwaway `git worktree add --detach` of `origin/main` with `PYTHONPATH` pointed at it; that worktree has been removed. The ranges are across the three rounds. The script is `/tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/e5cefd6a-84bc-4dcd-84d3-0990905b91d0/scratchpad/time_steps.py`.

| call | origin/main | branch | ratio |
|---|---|---|---|
| dewow, raw line (read F-ordered) | 25.9–26.8 | 40.1–41.5 | 1.55x |
| background_sliding 200, raw line | 47.2–48.0 | 44.5–47.1 | 0.95x |
| dewow after Time zero (463 × 1751, C-ordered) | 13.8–14.5 | 24.7–25.1 | 1.75x |
| background_sliding 200 after Time zero + dewow | 13.6–13.7 | 29.5–31.7 | 2.2–2.3x |
| gain_agc after Time zero + dewow | 22.6–22.9 | 34.4–35.7 | 1.55x |
| running_mean axis 0, window 18, raw | 20.0–20.9 | 32.1–32.9 | 1.6x |
| running_mean axis 1, window 200, raw | 39.7–41.2 | 37.4–38.2 | 0.95x |

Every call is at or under about 47 ms, well inside the ~100 ms aim of spec §4.1a.

Profiling on 463 × 1751 shows the two cumulative sums cost about 3.2 ms each and every other pass about 1–2 ms. A Fortran-ordered padding for the along-traces case was slower: the cumsum along traces took 3.7 ms on F-ordered padding against 2.4 ms on C-ordered, and the copy into it cost 1.8 ms against 0.65 ms. Reusing buffers made no measurable difference, so I stopped there.

## Mutation probes (Step 7)

The probes ran in a throwaway `git worktree add --detach` of `8449263` under the scratchpad, with `PYTHONDONTWRITEBYTECODE=1` and `PYTHONPATH` set to that tree's src; I asserted that `nsgeo` imported from the scratch tree. The real data was symlinked in entry by entry. The worktree has been removed. Each mutant replaced exactly one occurrence and ran the six processing test files.

| # | mutant | result | killed by |
|---|---|---|---|
| M1 | finite mask dropped from the values (`padded[inner] = a`) | KILLED | skips_nan_and_inf, no_finite_sample_is_nan, one_nan_through_the_users_stack, dewow/AGC/sliding real-line nan+inf (9) |
| M2 | mask gate: `clean = True` always | KILLED | same 9 |
| M3 | finite-count divisor counts every sample (`good[inner] = True`) | KILLED | skips_nan_and_inf, no_finite_sample_is_nan, dewow real-line nan+inf (neighbour value) |
| M4 | divisor is the window length on the masked path | KILLED | same 4 |
| M5 | `refuse_non_finite` counts rows | KILLED | refuse_non_finite_counts_traces_not_samples_or_rows |
| M6 | `refuse_non_finite` counts samples | KILLED | same |
| M7 | `refuse_non_finite` total is `shape[0]` | KILLED | the counting test, SVD, bandpass, envelope |
| M8 | two-sum compensation dropped | KILLED | keeps_precision_beside_a_huge_value, agc cap |
| M9 | first-break envelope ignores the finite mask | **SURVIVED → fixed** | see below |
| M10 | Time zero never refuses | KILLED | all_zero, no_finite_sample |
| M11 | background mean ignores the finite mask | KILLED | one_nan_through_the_users_stack, background_mean nan+inf |

M5 and M6 need a test with several bad samples. A single NaN gives 1 bad trace, 1 bad row and 1 bad sample alike, so the brief's 1-of-635 tests cannot tell them apart. `test_refuse_non_finite_counts_traces_not_samples_or_rows` puts 4 bad samples on 3 rows in 2 of 6 traces.

**M9.** With the bad sample at row 300 (the brief's case), leaving that whole row out of the envelope picks the same row as averaging its finite samples, because the `usable` mask alone hides the bad row. On the pick row it does not: on FILE__007, a NaN or inf at `[49, 5]` makes the mutant pick 50, while the correct code still picks 49. `432d735` adds `(49, nan)` and `(49, inf)` to the Time zero parametrization. I re-ran M9 in the scratch tree, where it was killed by `[49-nan]` and `[49-inf]`.

## Files changed

- `packages/nsgeo-core/src/nsgeo/processing/_util.py`
- `packages/nsgeo-core/src/nsgeo/processing/background.py`
- `packages/nsgeo-core/src/nsgeo/processing/bandpass.py`
- `packages/nsgeo-core/src/nsgeo/processing/amplitude.py`
- `packages/nsgeo-core/src/nsgeo/processing/migration.py`
- `packages/nsgeo-core/src/nsgeo/processing/timezero.py`
- `packages/nsgeo-core/tests/test_processing_base.py`
- `packages/nsgeo-core/tests/test_steps_timezero_dewow.py`
- `packages/nsgeo-core/tests/test_steps_gain.py`
- `packages/nsgeo-core/tests/test_steps_background.py`
- `packages/nsgeo-core/tests/test_steps_bandpass.py`
- `packages/nsgeo-core/tests/test_steps_amplitude.py`

## Self-review findings and small calls

- **SVD refusal placement.** I put it after the `n < 0` and `n == 0` checks, not literally first. Zero components is the identity and runs no decomposition, so refusing there would contradict its own wording ("the decomposition cannot run on them") and turn a valid "off" setting into an error on data it does not touch. It still comes before the rank check and the SVD itself. Bandpass and envelope refuse first in `apply`, as the brief says.
- **Time zero's refusal wording for non-zero cases.** The brief gives one message for both no-finite and zero-peak. I kept that message word for word where it is true (an all-finite, all-zero line) and gave the all-NaN and mixed cases true reasons. All of them begin "Time zero found no first arrival", which is what the all-NaN test matches.
- **Extra tests beyond the brief:**
  - the `refuse_non_finite` counting test (needed for the count probe);
  - the all-bad-row background mean test (pins "subtracts NaN, touches only bad samples");
  - a dewow neighbour check (a neighbour of the bad sample equals its sample minus the fsum mean of the good samples in its window, `rel=1e-12`; spec §8);
  - the row-49 Time zero cases.
- **Exact message pins.** The bandpass, envelope and SVD tests pin the full message including the consequence, since the plan gives that wording.
- **Review Focus 5** lives in `test_processing_base.py` and chains `build_step(...).apply` over the six steps. It asserts exactly one non-finite sample, at `[101, 300]`, and that it is NaN.
- **First-break regression risk.** For clean data, `first_break_row` is bit-identical to before: the same sum and the same integer count. `first_break_ns` and the profile dock's use of it are unchanged on finite data.

## Concerns

- **Speed against spec §4.1's "within 2x of today".** One case exceeds it: sliding background on a C-ordered line after Time zero and dewow is 2.2–2.3x (about 14 ms → 30 ms). Dewow after Time zero is 1.75x, and the rest are 0.95–1.6x. Spec §4.1a, the later designer's call, makes speed "measured and reported, not a hard test", with an aim of about 100 ms. Every call is ≤ 47 ms, so I did not trade accuracy for it.
- **Huge finite values.** A finite sample above about 1.3e154 squares to inf in AGC and is then treated as a bad sample, left out of its own window. That would break AGC's cap for that one sample. This is far outside any real GPR value, so it is noted, not handled.
