# Processing steps: edge cases, the migration test, trace stacking — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task by task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Processing steps stop silently returning a blank, NaN or uncropped line. A setting that
cannot work is refused by name, a bad sample damages only itself, a saved project holding a refused
setting still opens with a note, migration gets its real-data test, and a Trace stack step is added.

**Architecture:** Almost everything is in `nsgeo-core`:
- `processing/_util.py` holds the finite-skipping `running_mean` and two shared refusal helpers.
- The steps themselves hold their run-time refusals.
- `processing/base.py` holds one per-setting check, used by `build_step` and by `project.py`'s load
  repair.
- The plugin only shows the load notes.

**Tech Stack:** Python 3.9+ (core: numpy only), QGIS 3.44 / 4.2 (PyQt5 / PyQt6), pytest.

**Spec:** `docs/superpowers/specs/2026-11-13-nsgeo-step-edges-design.md`. §3 lists the user's
decisions (1–6), §4–§7 the behaviour, §8 the tests. Read it before your task.

## Global Constraints

- **Core:** numpy only, runtime Python 3.9: no `match`, no `zip(strict=)`, no PEP 604 unions
  outside annotations. Every new file starts with `from __future__ import annotations`.
- **Leave alone:**
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/param_form.py`;
  - the `nsgeo-help-pages` branch;
  - `first_break_row`'s signature and its 0-for-no-signal return.
- **Running things.** Run everything from the worktree root
  `/home/jameszd/Documents/Github/archaeo_geophysics/.worktrees/nsgeo-step-edges`. It has its own
  `.venv` and `.venv-qgis`, and the real data linked under `packages/nsgeo-core/tests/data/local/`.
  - Core: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests -q -p no:cacheprovider`
  - One QGIS file: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/<file> -q -p no:xonsh -p no:cacheprovider`
  - **The QGIS processing set**, which the user asked for. Tighter validation can break QGIS tests
    that build steps with odd values. Run each of these files with the command above:
    - `test_plugin_processing_dock.py`, `test_plugin_param_form.py`,
      `test_plugin_difference_presets.py`, `test_plugin_session.py`;
    - `test_plugin_profile_dock.py`, `test_plugin_time_cutoff.py`, `test_plugin_gain_strip.py`,
      `test_plugin_survey_dock.py`;
    - `test_plugin_site_scope.py`, `test_plugin_slices_engine.py`, `test_plugin_layers.py`,
      `test_plugin_grid_velocity_dialog.py`, `test_plugin_velocity_dialog.py`.

    Don't run the whole QGIS tier; CI does.
  - Lint: `.venv/bin/ruff check packages && .venv/bin/ruff format --check packages`
  - mypy, as CI runs it: `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`
- **Real lines first.** Every fix gets a test on campus `FILE__007.DZT` or a Grid 2 line, as well
  as any synthetic test.
  - Load real lines with `tests.real_data.real_radargram(path)` (Task 1). It skips when the file is
    missing, as on CI.
  - Key files by path (`DATA / "FILE__007.DZT"`, `DATA / "grid2" / "FILE__033.DZT"`), never by stem
    (#141).
  - FILE__007 facts: 512 samples × 635 traces, `dt_ns` 0.21653, position −11.09 ns. The default
    Time zero crops 49 rows.
- **Messages** are plain words, with no issue numbers. Where this plan gives a message, tests pin it.
- **Commits:** one or more per task, pushed to `origin nsgeo-step-edges` as made. End each message
  with a `Co-Authored-By:` line naming your own model.
- **Mutation testing**, where a task asks for it: `PYTHONDONTWRITEBYTECODE=1`, in a throwaway copy
  of the tree (`git worktree add` under the scratchpad), **never** in this worktree.

## Review Focus

1. **Numpy scalars from plugin code.** A pick or a spin box can hand `np.int64` or `np.float32` to
   `build_step`. Ints and floats must still accept them. Pinned in Task 3.
2. **A repaired preset applied later.** After a load repair, applying the preset to a grid or using
   it for slices must build and run, not raise. Pinned in Task 4.
3. **Save, then reopen, after a repair.** The repaired state persists, and the second open has no
   notes. Pinned in Task 4.
4. **The Add-step dialog's one-trace test run** (bandpass, migration, gain curve) on an all-zero
   first trace. A valid bandpass must still pass it; the empty-band check depends only on the
   sample count and interval. Pinned in Task 3.
5. **One NaN through the user's real stack.** Time zero, time cutoff 45 ns, dewow, background mean,
   AGC and gain curve end with exactly one NaN in the output, at the bad sample. Pinned in Task 2.

---

### Task 1: The migration real-data test (#125)

No product code. It lands first, and its numbers guard the later changes to dewow and background
mean.

**Files:**
- Modify: `packages/nsgeo-core/tests/real_data.py` (add `real_radargram`)
- Modify: `packages/nsgeo-core/tests/test_steps_migration.py` (new section at the end)

**Interfaces:**
- Produces: `real_radargram(path: Path) -> Radargram` in `tests/real_data.py`. It reads channel 0
  as float with `dt_ns=header.dt_ns`, `t0_ns=header.position_ns`, and
  `dx_m=1/header.traces_per_metre` (None when that is ≤ 0). It calls `pytest.skip` when `path` does
  not exist. Later tasks use it.

- [ ] **Step 1: Add `real_radargram` and write the test**

  Constants, with a provenance comment. They come from the user's hand fits on Nashville City
  Cemetery 2023 Grid 2, saved 2026-11-06 in the gitignored hand-fit site file. The times are after
  the default Time zero, which sits at −0.476 ns on the radar clock; the fits were saved on the
  radar clock (19.947 and 19.363 ns).

  ```python
  REAL_DIFFRACTIONS = (  # (file in grid2/, apex trace, apex ns after time zero, velocity m/ns)
      ("FILE__033.DZT", 1375, 20.42, 0.1027),
      ("FILE__032.DZT", 386, 19.84, 0.1061),
  )
  ```

  The measurement, the one algorithm here that the assertions don't determine:

  ```python
  def _real_focus(img, apex_row, apex_trace, dt_ns, dx_m):
      """(focus, d_row, d_trace) at the strongest sample near the apex.

      The window is +-10 ns x +-1.5 m around the hand apex. The peak is searched from 1 ns
      above to 4 ns below it and +-0.3 m across. Focus is `_focus` (17 x 17 box) over that
      window: the synthetic test's measure, with the window as the total.
      """
      hr, ht = round(10 / dt_ns), round(1.5 / dx_m)
      r0, t0 = max(apex_row - hr, 0), max(apex_trace - ht, 0)
      win = img[r0 : apex_row + hr + 1, t0 : apex_trace + ht + 1]
      ar, at = apex_row - r0, apex_trace - t0
      lo, hi, st = round(1 / dt_ns), round(4 / dt_ns), round(0.3 / dx_m)
      sub = np.abs(win[ar - lo : ar + hi + 1, at - st : at + st + 1])
      pr, pt = np.unravel_index(np.argmax(sub), sub.shape)
      pr, pt = pr + ar - lo, pt + at - st
      return _focus(win, pr, pt), pr - ar, pt - at
  ```

  The test is `test_a_real_diffraction_collapses_at_its_measured_velocity`, parametrized over
  `REAL_DIFFRACTIONS`:
  - Processing: `time_zero` → `dewow` → `background_mean`, then `migrate_fk(velocity_m_ns=v)`,
    all at defaults.
  - `apex_row = round(t_ns / dt_ns)`.
  - Assertions:
    - `abs(d_trace) <= 2`;
    - `0.5 <= d_row * dt_ns <= 2.0`. The hand dots sit on the band's top edge and the migrated
      peak is mid-band. Measured: +5 rows (1.08 ns) and +6 rows (1.30 ns).
    - `focus_migrated > 0.04` and `focus_migrated >= 2 * focus_unmigrated`. Measured: 0.075 vs
      0.024, and 0.050 vs 0.020.
    - `focus(v) > focus(0.6 v)` and `focus(v) > focus(1.6 v)`. Measured: 0.047 / 0.075 / 0.038
      and 0.035 / 0.050 / 0.017.

  The docstring says there is **no deep case** and why, with spec §7.3's numbers:
  - below 50 ns, the median signal is 1.3–1.6× the noise of the 80–90 ns band, on the campus lines,
    Grid 1 and Grid 2;
  - a search of all 130 local lines at 40–85 ns found only flat layers;
  - the deep coverage is the synthetic `test_a_point_diffractor_collapses_to_its_apex`.

- [ ] **Step 2: Run it**

  Run: core command on `packages/nsgeo-core/tests/test_steps_migration.py`.
  Expected: PASS for both cases. If a measured value differs from the numbers above by more than
  rounding, stop and report it. Don't loosen a threshold to make it pass.

- [ ] **Step 3: Check it fails when it should**

  Temporarily change the velocity to `v * 0.6` in the test. At least the focus assertions must
  fail. Revert.

- [ ] **Step 4: Commit and push**

  `test(migration): real diffractions on Grid 2 collapse at their hand-fit velocity (#125)`

---

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

### Task 3: Settings that cannot work (#44, #40, #46, spec §4.2, §4.3, §4.6)

**Files:**
- Modify: `processing/base.py` (`ParamSpec`, `_out_of_bounds`, `param_problem`,
  `_validate_params`), `processing/_util.py` (`window_samples`), `processing/dewow.py`,
  `processing/gain.py`, `processing/background.py`, `processing/bandpass.py`
- Test: `tests/test_schema.py`, `tests/test_steps_timezero_dewow.py`, `tests/test_steps_gain.py`,
  `tests/test_steps_background.py`, `tests/test_steps_bandpass.py`

**Interfaces:**
- Produces:
  - `ParamSpec.min_exclusive: bool = False`. When true, the value must be `> min`, and the reason
    reads `"must be > {min}"`.
  - `param_problem(spec: ParamSpec, value: Any) -> str | None` in `base.py`, not in `__all__`. It
    returns the reason phrase or None:
    - choice: `"must be one of {list(spec.choices)}"`; a non-string is refused too;
    - int: `numbers.Integral` and not `bool`, else `"must be a whole number"`;
    - float and time: `numbers.Real` and not `bool`, else `"must be a number"`; then finite, else
      `"must be a finite number"`;
    - then the bounds: `"must be >= {min}"`, `"must be > {min}"`, `"must be <= {max}"`;
    - curve: at least two points, each a pair of finite numbers, plus today's dB bounds, with
      today's curve wording.

    `_validate_params` keeps its message format:
    `f"step {name!r}: {pname} {reason}, got {value!r}{unit}"`.
  - `window_samples(window_ns: float, dt_ns: float, title: str) -> int` in `_util.py`. It returns
    `round(window_ns / dt_ns)`, or raises when that is below 2:
    - `f"{title} window {window_ns:g} ns is one sample at this line's {dt_ns:.3f} ns sampling; use {minimum:.2f} ns or more."`
    - with `"is shorter than one sample"` in place of `"is one sample"` when the count is 0.
    - `minimum` is `ceil(150 * dt_ns) / 100`, plus 0.01 if that still rounds to fewer than 2
      samples.

- [ ] **Step 1: Write the failing tests**

  - `test_schema.py`, `test_settings_that_used_to_pass_build_are_refused`, parametrized
    `(step, params, setting)`. Each raises `ValueError` matching the setting name. Add
    `low_mhz=250.0, high_mhz=750.0` to the bandpass cases that don't set them.
    - choices: time_zero `mode="bogus"`; gain_parametric `mode="bogus"`;
    - ints: background_sliding `window_traces` = `200.0`, `True`, `"200"`; background_svd
      `n_components` = `1.5`, `2.0`, `21`; time_zero `sample` = `10.7`, `True`, `inf`;
    - floats:
      - bandpass: `low_mhz=nan`, `high_mhz=nan`, `taper_frac=nan`, `taper_frac=inf`;
      - gain_parametric: `alpha` = `nan`, `8.0`, `"0.1"`; `exponent=50.0`;
      - gain_agc: `window_ns` = `nan`, `inf`; `eps` = `0.0`, `inf`; `target` = `0.0`, `inf`;
      - time_zero: `threshold=nan`;
    - bounds: background_sliding `window_traces=1`.
  - `test_numpy_scalars_and_ints_for_floats_still_build` (Review Focus 1):
    - `time_zero(mode="sample", sample=np.int64(40))`;
    - `dewow(window_ns=np.float32(4.0))`;
    - `dewow(window_ns=4)`;
    - `background_sliding(window_traces=np.int32(200))`.
  - Update `test_the_registry_declares_the_bounds_these_tests_cover`: add `gain_parametric.alpha`
    and `gain_parametric.exponent`.
  - Update `test_every_declared_bound_is_enforced_by_build_step` for `min_exclusive`: the edge
    itself is refused there, and `edge + 1e-9` is accepted.
  - **One-sample windows** on FILE__007 (`dt_ns` 0.21653):
    - dewow at `window_ns` 0.1 and 0.2, and AGC at 0.2, raise matching `"is shorter than one sample"`
      and `"is one sample at this line's 0.217 ns sampling; use 0.33 ns or more."` respectively;
    - 0.33 ns runs for both.
    - Replace the `match="window_ns"` in `test_dewow_rejects_window_shorter_than_one_sample`.
  - **Bandpass** on FILE__007:
    - `low 300.0, high 302.0, taper 0.0` raises matching
      `"holds no frequency on this line, whose frequencies are 4.51 MHz apart"`;
    - `low 300.0, high 300.0 + df, taper 0.0`, with `df = 1 / (1024 * 0.21653e-9) / 1e6`, runs.
  - **Review Focus 4:** `Bandpass(250, 750)` applied to `rg.replace(data=np.zeros((512, 1)))`
    runs.
  - **ParamForm question (spec §4.3):** in `test_schema.py`, a project whose parametric gain is
    saved with `mode="bogus"` is covered by Task 4's repair. Here, assert only that
    `build_step("gain_parametric", mode="bogus")` raises.

- [ ] **Step 2: Run them and confirm they fail** for the stated reasons.

- [ ] **Step 3: Implement**

  - **`base.py`:** `min_exclusive`, `param_problem`, and `_validate_params` built on it.
  - **Schema changes**, exactly:
    - `background_sliding.window_traces`: min 2;
    - `gain_agc.eps`: min 0.0, `min_exclusive=True`;
    - `gain_agc.target`: min 0.0, `min_exclusive=True`;
    - `gain_parametric.alpha`: min −1.0, max 1.0;
    - `gain_parametric.exponent`: min −10.0, max 10.0;
    - `background_svd.n_components`: max 20.
  - **`Dewow.apply` and `GainAgc.apply`** get their window from `window_samples` with titles
    `"Dewow"` and `"AGC"`. The message must read `"Dewow window 0.2 ns is one sample …"`.
  - **`BackgroundSliding.apply`:** guard `< 2` with
    `f"window_traces must be >= 2, got {self.window_traces}"`.
  - **`Bandpass.apply`:** after building the mask, if `not mask.any()`, raise:
    `f"Bandpass {low:g}–{high:g} MHz holds no frequency on this line, whose frequencies are {df:.2f} MHz apart. Make High − Low at least {df:.2f} MHz."`.
    `df` is `freqs_mhz[1]`. Keep the two `< 0` checks as they are.

- [ ] **Step 4: Run the core suite and the QGIS processing set.** Expected: all pass. A QGIS test
  that builds a step with a now-refused value gets a valid value, and is named in your report.

- [ ] **Step 5: Mutation-probe** these: the 1.5-sample threshold (`< 2` to `< 1`), `min_exclusive`
  (`<=` to `<`), the bool exclusion for ints and floats, and `mask.any()`. Report.

- [ ] **Step 6: Commit and push**

  `fix(processing): refuse settings that cannot work, by name (#44, #40, #46)`

---

### Task 4: A project holding a refused setting still opens (spec §5, decisions 1 and 6)

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/model/survey.py` (`Site.load_notes`),
  `packages/nsgeo-core/src/nsgeo/project.py` (`_repair_steps`, `load_site`),
  `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (`open_site`)
- Test: `tests/test_project.py` (or a new `tests/test_project_repair.py`), `tests/test_schema.py`,
  `tests/test_presets.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py`

**Interfaces:**
- Consumes: `param_problem`, `ParamSpec.label` and `.required`, `get_step`, `step_title`,
  `build_step` (Task 3).
- Produces:
  - `Site.load_notes: list[str] = field(default_factory=list)`. It is never saved; comment it so.
  - `_repair_steps(entries: list[dict], where: str, notes: list[str]) -> list[dict]` in
    `project.py`. It returns new dicts and appends notes.
    - `where` is `f"Line {Path(entry['path']).name}"` or `f"Preset {name!r}"`.

- [ ] **Step 1: Write the failing core tests** (use `_write_project_with_stack` from
  `test_schema.py`, or an equivalent writer):

  - **A refused setting turns the step off.** AGC `eps=0.0` on the line: `load_site` succeeds, the
    stack's AGC is disabled with `eps == 1e-12`, and `site.load_notes` holds exactly this:
    `"Line L0.DZT: Automatic gain control is turned off. Its Epsilon was 0.0, which must be > 0.0; it is now 1e-12. Check the step and turn it back on."`
  - **A preset:** `background_sliding window_traces=1` in preset `"p"` comes back with the step
    disabled, `window_traces == 200`, and a note starting `"Preset 'p': "`.
  - **Review Focus 2:** `StepStack.from_dicts(site.presets["p"])` builds, and the stack runs on a
    random radargram.
  - **Review Focus 3:** `save_site`, then `load_site`. The step is still off, and `load_notes` is
    empty.
  - **Two refused settings on one step:** parametric gain `mode="bogus", alpha=8.0` gives one
    note naming both, and comes back `mode == "exponential"`, `alpha == 0.05`, off.
  - **Time zero stays on (decision 6):** `time_zero` with `sample=12.0` comes back
    **enabled** with `sample == 0`. Its note:
    `"Line L0.DZT: Time zero's Sample was 12.0, which must be a whole number; it is now 0. The step stays on, because turning Time zero off would move every time after it."`
  - **No default, so removed:**
    - bandpass with `low_mhz=nan` is removed, with a note containing
      `"Bandpass is removed"` and `"Low"`;
    - a gain curve with one point is removed. Rewrite
      `test_load_site_reports_an_invalid_stack_as_project_error` to expect this.
  - **A missing required setting:** bandpass without `high_mhz` is removed, with a note.
  - **Still refused:**
    - an unknown step name (the existing `test_invalid_preset_is_a_project_error`);
    - an unknown setting name (the existing `test_an_unknown_parameter_name_is_refused_rather_than_ignored`);
    - an entry that isn't an object.

    All three stay `ProjectError`.
  - **A constructor refusal the check doesn't know about:** monkeypatch a registered step's
    `__init__` to raise `ValueError("x")`. Loading removes the step with a note. Without this
    safety net, "still opens" would depend on every rule living in `param_problem`.

- [ ] **Step 2: Run them and confirm they fail.**

- [ ] **Step 3: Implement `_repair_steps` and wire it into `load_site`**, around current lines
  ~495 (line stacks) and ~520 (presets). Presets are stored repaired in `site.presets`. Other
  rules:
  - Structural faults keep raising, and the existing `try` turns them into `ProjectError`: a
    non-dict entry, a missing `"step"`, `params` not a dict, an unknown step or setting.
  - Note wording follows the examples above:
    - one sentence per refused setting: `Its <Label> was <repr>, which <reason>; it is now <repr>.`
    - then the ending: `Check the step and turn it back on.` for steps turned off, or the Time zero
      sentence;
    - removed steps: `"<where>: <Title> is removed. Its <Label> was <repr>, which <reason>, and <Label> has no default. Add it again with the settings you want."`
    - a missing required setting: `"<where>: <Title> is removed. It has no <Label>, which it needs. Add it again with the settings you want."`

- [ ] **Step 4: Write the failing QGIS test** in `test_plugin_survey_dock.py`:
  `test_opening_a_project_with_a_refused_setting_turns_the_step_off_and_says_so`. Use the
  `fake_iface`, `monkeypatch` and `message_log` fixtures, and `getOpenFileName` monkeypatched as in
  `test_open_site_discarding_abandons_the_old_site_without_saving_it`. The file holds AGC `eps=0`
  on a line. After `plugin.open_site()`:
  - the session is open;
  - `plugin.session.stack_for(key).entries[i][1] is False` for the AGC entry;
  - `message_log` contains the note text;
  - and it contains the summary:
    `"1 processing step in this project had settings that cannot work. It was turned off, reset or removed; the nsgeo log says what changed."`
    For n > 1: `"{n} processing steps … They were turned off, reset or removed; …"`.

- [ ] **Step 5: Implement** in `plugin.open_site`. After `self.session.open_site(...)` succeeds,
  if `self.session.site.load_notes` is not empty:
  - log each note with `QgsMessageLog.logMessage(note, "nsgeo", Qgis.MessageLevel.Warning)`;
  - then `self.message(summary, Qgis.MessageLevel.Warning)`.

  Nothing marks the session dirty. The repair reaches the file at the next save.

- [ ] **Step 6: Run the core suite and the QGIS processing set.** Expected: all pass.

- [ ] **Step 7: Commit and push**

  `feat(project): a saved setting that cannot work turns its step off with a note, instead of blocking the project`

---

### Task 5: Trace stack (#114, spec §6)

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/processing/trace_stack.py`
- Modify: `processing/__init__.py` (add `trace_stack` to the registering import),
  `tests/test_step_titles.py`, `tests/test_schema.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py` (the pinned Filters list,
  around line 57)
- Test: `packages/nsgeo-core/tests/test_steps_trace_stack.py` (new)

**Interfaces:**
- Consumes: `running_mean` (Task 2), `real_radargram` (Task 1).
- Produces: a registered step `TraceStack` with:
  - `name = "trace_stack"`, `title = "Trace stack"`, `group = "Filters"`, `order = 3`;
  - schema `(ParamSpec(name="window_traces", kind="int", label="Window", default=3, unit="traces", min=1, help="Averages each trace with its neighbours: this many traces in all, centred on it. 1 leaves the line unchanged."),)`;
  - `params == {"window_traces": ...}`;
  - `apply(rg) = rg.replace(data=running_mean(rg.data, self.window_traces, axis=1))`.

- [ ] **Step 1: Write the failing tests** in `test_steps_trace_stack.py`:

  - `test_window_one_leaves_the_line_unchanged` (FILE__007, exact equality).
  - `test_a_constant_section_is_unchanged`.
  - `test_trace_count_and_time_axis_are_unchanged`, on FILE__007 after `time_zero`: shape,
    `dt_ns`, `t0_ns`, `zero_ns`, `zero_set` and `dx_m` all equal.
  - `test_the_line_ends_average_what_is_there`: at window 3, `out[:, 0] == data[:, :2].mean(1)`
    and `out[:, -1] == data[:, -2:].mean(1)`. This is sliding background's edge rule.
  - `test_stacking_lowers_trace_to_trace_noise_on_real_lines`, on FILE__007 and Grid 2
    FILE__033, after `time_zero` and `dewow`:
    - `var(diff(out, axis=1)) / var(diff(data, axis=1)) < 0.75` at window 3. Measured 0.655 and
      0.614.
    - Each trace's strongest row in 8–40 ns doesn't move: the median absolute shift is 0 rows.
      Measured: 0.
  - `test_a_bad_sample_takes_its_neighbours_mean`: FILE__007 with a NaN at `[100, 300]`, window 3:
    - `out[100, 300] == mean(data[100, 299], data[100, 301])`;
    - no NaN anywhere in the output.
  - `test_the_difference_view_works_across_it`: a `StepStack` holding `trace_stack(5)` on
    FILE__007. `difference(0)` has the input's shape and equals input minus output.
  - `test_a_window_longer_than_the_line_averages_the_whole_line`: window 10000.
  - Registration:
    - `TITLES["trace_stack"] = "Trace stack"`, and the Filters list
      `["dewow", "bandpass", "trace_stack"]` in `test_step_titles.py`;
    - `trace_stack.window_traces` in the bounded set in `test_schema.py`;
    - `("Filters", ["dewow", "bandpass", "trace_stack"])` in
      `test_add_menu_is_grouped_in_processing_order`.

- [ ] **Step 2: Run them and confirm they fail** (unknown step).

- [ ] **Step 3: Implement** `trace_stack.py` and the import.

- [ ] **Step 4: Run the core suite, `test_plugin_processing_dock.py` and the rest of the QGIS
  processing set, lint and mypy.** Expected: all pass, with no new mypy errors.

- [ ] **Step 5: Commit and push**

  `feat(processing): Trace stack averages each trace with its neighbours (#114)`

---

## After the tasks

These are the controller's steps, not a task:
- the whole-branch review;
- deploy to its own QGIS profile, then the user's walkthrough (spec §9):
  - Trace stack on a real line, with the Difference view;
  - opening a project copy that holds AGC epsilon 0 on a line and sliding background 1 in a preset;
- the PR, listing the settings changes for the help pages (spec §10) and the tracer rerun note;
- the README roadmap entry moves from "Being designed" to "Being built", and later to Done.

Merging asks the user first.
