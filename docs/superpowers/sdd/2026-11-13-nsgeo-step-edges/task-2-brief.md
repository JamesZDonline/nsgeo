### Task 2: Bad samples (#43, #42, spec §4.1, §4.1a, §4.5)

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/processing/_util.py`
- Modify: `processing/background.py` (BackgroundMean, BackgroundSvd), `processing/bandpass.py`,
  `processing/amplitude.py` (AmpEnvelope), `processing/migration.py` (use the shared helper,
  keeping its message), `processing/timezero.py`
- Test: `tests/test_processing_base.py`, `tests/test_steps_timezero_dewow.py`,
  `tests/test_steps_gain.py`, `tests/test_steps_background.py`, `tests/test_steps_bandpass.py`,
  `tests/test_steps_amplitude.py`

**Interfaces:**
- Consumes: `real_radargram` (Task 1).
- Produces:
  - `running_mean(a: np.ndarray, window: int, axis: int = 0) -> np.ndarray`, same signature. It
    skips non-finite samples, and a window with no finite sample gives NaN.
  - `refuse_non_finite(data: np.ndarray, consequence: str) -> None` in `_util.py`. It raises
    `ValueError(f"{bad} of {n} traces hold samples that are not finite; {consequence}")`, where
    `bad` is the number of traces (columns) holding any NaN or inf.

- [ ] **Step 1: Write the failing `running_mean` tests** in `test_processing_base.py`

  - `test_running_mean_skips_nan_and_inf`: random `(64, 5)` data with NaN at `[10, 1]`, `+inf` at
    `[30, 2]` and `-inf` at `[31, 2]`. For windows 7 (axis 0) and 3 (axis 1), compare against a
    direct loop. Each output `i` is the mean of the finite samples in `[lo, hi)`, where
    `lo = max(i - w // 2, 0)` and `hi = min(i - w // 2 + w, n)`, which is today's edge rule.
    `assert_allclose(rtol=1e-12)`, NaN matching NaN.
  - `test_running_mean_of_a_window_with_no_finite_sample_is_nan`: a column `[nan, nan, nan, 1.0]`
    at window 3 gives NaN at rows 0 and 1, and a number at rows 2 and 3.
  - `test_running_mean_keeps_precision_beside_a_huge_value`: `a = rng.normal(size=200)`,
    `a[0] = 1e12`. At window 5, every output from row 3 on (windows clear of row 0) equals the
    direct mean to `rtol=1e-12`. Fails today.

- [ ] **Step 2: Write the failing step tests**, using FILE__007 via `real_radargram`

  - **Dewow, AGC, sliding background** (in their test files), with a NaN at `[100, 300]` and
    default settings:
    - dewow and AGC: the output holds exactly one NaN, at `[100, 300]`;
    - sliding background: exactly one NaN in row 100.
    - The same with `+inf` instead: exactly one non-finite output sample, at the bad sample, and no
      NaN anywhere. For AGC, the 91 samples around the inf are not zero.
  - **The AGC cap:** `test_gain_agc_output_never_exceeds_its_cap_beside_a_huge_burst`. A
    `(512, 3)` normal trace with rows 100–110 multiplied by 1e10, at `dt_ns` 0.21653 and default
    AGC (a window of 92 samples). Assert `abs(out) <= 1.0 * sqrt(92) * (1 + 1e-9)` everywhere.
    Fails today.
  - **Background mean:** a NaN at `[100, 300]` on FILE__007 leaves exactly one NaN; the same with
    inf.
  - **Bandpass `(250, 750)`, envelope and SVD (1 component)** on FILE__007 with a NaN at
    `[100, 300]`: each raises `ValueError` matching `"1 of 635 traces hold samples that are not finite"`.
    The SVD test proves it is no longer a `LinAlgError`.
  - **Time zero:**
    - FILE__007 crops 49 rows clean, with a NaN at `[300, 5]`, and with an `inf` at `[300, 5]`;
    - an all-zero `(100, 20)` radargram: `build_step("time_zero").apply` raises `ValueError`
      matching `"Time zero found no first arrival: every sample on this line is zero"`, while
      `first_break_row` on it returns 0 and `mode="sample"` still works;
    - an all-NaN radargram raises matching `"Time zero found no first arrival"`.
  - **Review Focus 5:** `test_one_nan_through_the_users_stack_stays_one_sample`. FILE__007 with a
    NaN at `[150, 300]`, through `time_zero`, `time_cutoff(end_ns=45.0)`, `dewow`,
    `background_mean`, `gain_agc`, and
    `gain_curve(points=[[0.0, 0.0], [20.0, 6.0], [45.0, 0.0]])`. The output holds exactly one
    NaN, at row `150 - 49` (21.9 ns, inside the cutoff), trace 300.

- [ ] **Step 3: Run them and confirm they fail** for the reasons stated, not for import errors.

- [ ] **Step 4: Implement**

  - **`running_mean`:** a masked cumsum of the finite values plus a cumsum of the finite count.
    Accuracy relative to each window's own magnitude, by your method (spec §4.1). A fast path for
    data with no bad samples is expected. `window < 1` still raises; `window == 1` returns a copy
    (bad samples stay bad).
  - **`BackgroundMean.apply`:** subtract each row's mean over its finite samples. A row with no
    finite sample subtracts NaN, which only touches samples that are already bad.
  - **Bandpass, envelope, SVD:** call `refuse_non_finite` first. The consequence wording:
    - bandpass and envelope: `"the filter would spread each one along its whole trace"`;
    - SVD: `"the decomposition cannot run on them"`;
    - migration keeps its current text, `"one of them would spread across the whole image through the transform"`.
  - **`first_break_row`:** the envelope is each row's mean `|x|` over its finite samples. Rows
    without one are never picked. The peak is the largest finite envelope value. It returns 0 when
    there's no signal, as today.
  - **`TimeZero.apply`, first-break mode:** raise the message above when no row has a finite
    sample or the finite peak is 0. Use a private helper `_first_break_or_none(rg, threshold) -> int | None`
    that both functions share. Sample mode is unchanged.

- [ ] **Step 5: Run the core suite and the QGIS processing set.** Expected: all pass.

  If a QGIS test fails because it runs first-break Time zero on all-zero synthetic data, give that
  test signal or `mode="sample"`. Don't weaken the refusal. Name each such test in your report.

- [ ] **Step 6: Measure and record.** Time `dewow` and `background_sliding(window_traces=200)` on
  Grid 2 FILE__033 (512 × 1751) before your change (`git stash` is shared, so time it on
  `origin/main` in a scratch checkout) and after. Put both in your report. The aim is about 100 ms
  per call or less (spec §4.1a); it is not a test.

- [ ] **Step 7: Mutation-probe** the finite mask in `running_mean`, the finite-count divisor, and
  `refuse_non_finite`'s count. Each mutant must fail a test. Report the probes.

- [ ] **Step 8: Commit and push**

  `fix(processing): one bad sample damages only itself; first break skips bad samples (#43, #42)`

---

