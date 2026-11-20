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
    - dewow at `window_ns` 0.1 raises matching `"is shorter than one sample"`;
    - dewow and AGC at 0.2 raise matching
      `"is one sample at this line's 0.217 ns sampling; use 0.33 ns or more."`;
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

