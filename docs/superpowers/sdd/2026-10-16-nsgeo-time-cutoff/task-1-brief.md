### Task 1: The `time_cutoff` step, the `"time"` kind, and `result_bypassing`

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/processing/timecutoff.py`
- Modify: `packages/nsgeo-core/src/nsgeo/processing/__init__.py` (import `timecutoff` beside `timezero` so it registers)
- Modify: `packages/nsgeo-core/src/nsgeo/processing/base.py`: `ParamSpec.KINDS` and its docstring; `_validate_params`'s numeric branch
- Modify: `packages/nsgeo-core/src/nsgeo/processing/stack.py`: add `result_bypassing`
- Test: create `packages/nsgeo-core/tests/test_steps_timecutoff.py`
- Test: modify `packages/nsgeo-core/tests/test_stack.py`, `test_schema.py`, `test_steps_background.py`, `test_real_files.py`

**Interfaces:**
- Produces: `build_step("time_cutoff", end_ns=<float>)`. The step's `params` is `{"end_ns": float}`. `schema()` returns one `ParamSpec(name="end_ns", kind="time", label="Cutoff", default=REQUIRED, unit="ns", help="Hide every sample at or after this two-way time. Drag the line on the profile to set it.")`.
- Produces: `ParamSpec.KINDS == ("float", "int", "choice", "curve", "time")`. A `"time"` parameter is a float two-way time in ns, on the radargram's own axis. It validates and bounds-checks exactly like `"float"`.
- Produces: `StepStack.result_bypassing(index: int) -> Radargram`. It returns what `result()` would be with step `index` switched off. It raises `IndexError` for an index out of range, with the same message `intermediate` uses.

- [ ] **Step 1: Write the failing step tests** in `test_steps_timecutoff.py`. Use a `make()` helper like the one in `test_steps_timezero_dewow.py`.

```python
def test_keeps_the_rows_before_the_cutoff_and_the_start_time():
    rg = make(n_samples=100, dt_ns=0.5, t0_ns=-4.0)
    out = build_step("time_cutoff", end_ns=-4.0 + 37 * 0.5).apply(rg)
    assert out.n_samples == 37
    assert out.t0_ns == rg.t0_ns
    np.testing.assert_array_equal(out.data, rg.data[:37])

def test_a_snapped_boundary_on_a_real_world_axis_keeps_exactly_m_rows():
    # dt and t0 as this repo's real HS350 headers carry them; t0 + m*dt is inexact in binary
    rg = make(n_samples=512, dt_ns=0.21653111279010773, t0_ns=-11.086392402648926)
    for m in (1, 2, 255, 300, 511):
        end = rg.t0_ns + m * rg.dt_ns
        assert build_step("time_cutoff", end_ns=end).apply(rg).n_samples == m

def test_a_cutoff_between_samples_keeps_every_sample_before_it():
    rg = make(n_samples=100, dt_ns=0.5, t0_ns=0.0)
    assert build_step("time_cutoff", end_ns=10.2).apply(rg).n_samples == 21  # samples at 0.0 .. 10.0

def test_a_cutoff_past_the_record_is_a_no_op():
    rg = make(n_samples=100, dt_ns=0.5, t0_ns=0.0)
    assert build_step("time_cutoff", end_ns=50.0).apply(rg) is rg  # exactly the record end
    assert build_step("time_cutoff", end_ns=1e6).apply(rg) is rg

def test_a_cutoff_at_or_before_the_first_sample_is_refused():
    rg = make(n_samples=100, dt_ns=0.5, t0_ns=2.0)
    for end in (2.0, -5.0):
        with pytest.raises(ValueError, match="would leave no samples"):
            build_step("time_cutoff", end_ns=end).apply(rg)

def test_end_ns_is_required_and_must_be_a_finite_number():
    with pytest.raises(ValueError, match="end_ns"):
        build_step("time_cutoff")
    with pytest.raises(ValueError, match="must be a number"):
        build_step("time_cutoff", end_ns="late")

def test_the_schema_declares_a_time_parameter_in_ns():
    (spec,) = get_step("time_cutoff").schema()
    assert (spec.name, spec.kind, spec.unit, spec.required) == ("end_ns", "time", "ns", True)
```

- [ ] **Step 2: Run them and see them fail.** Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_steps_timecutoff.py -q`. Expected: FAIL with `KeyError: unknown step 'time_cutoff'`.

- [ ] **Step 3: Add the `"time"` kind and the step.** In `base.py`, add `"time"` to `KINDS`, describe it in the `ParamSpec` docstring, and change `_validate_params`'s `spec.kind in ("float", "int")` to include `"time"`. In `timecutoff.py`, write `@register class TimeCutoff` with `name = "time_cutoff"`, `__init__(self, end_ns: float)` storing `float(end_ns)`, plus `params`, `schema` and `apply`. `apply` keeps `m = math.ceil((end_ns - t0_ns) / dt_ns - 1e-9)` rows. The tolerance is a billionth of a sample, so a snapped boundary `t0 + m*dt` keeps exactly `m`. When `m >= n_samples`, return `rg` itself. When `m <= 0`, raise `ValueError(f"time_cutoff at {end_ns:g} ns would leave no samples (the record starts at {t0_ns:g} ns)")`. Otherwise return `rg.replace(data=rg.data[:m, :].copy())`. Mirror `timezero.py`'s module docstring and layout. Import the module in `processing/__init__.py`.

- [ ] **Step 4: Run them and see them pass.** Same command. Expected: 7 passed.

- [ ] **Step 5: Write the failing `result_bypassing` tests** in `test_stack.py`, using its `stack_of` helper:

```python
def test_result_bypassing_skips_only_that_step():
    st = stack_of(("dewow", {"window_ns": 4.0}), ("time_cutoff", {"end_ns": 6.0}), ("gain_agc", {"window_ns": 2.0}))
    expected = stack_of(("dewow", {"window_ns": 4.0}), ("gain_agc", {"window_ns": 2.0})).result()
    np.testing.assert_array_equal(st.result_bypassing(1).data, expected.data)
    assert st.result_bypassing(1).n_samples == 64 and st.result().n_samples == 30

def test_result_bypassing_reuses_the_prefix_and_leaves_the_real_chain_alone():
    st = stack_of(("dewow", {"window_ns": 4.0}), ("time_cutoff", {"end_ns": 6.0}), ("gain_agc", {"window_ns": 2.0}))
    st.result_bypassing(1)
    assert st.cache_size == 1  # only the prefix before the bypassed step
    assert st.result().n_samples == 30

def test_result_bypassing_honours_disabled_steps_after_it():
    st = stack_of(("time_cutoff", {"end_ns": 6.0}), ("background_mean", {}))
    st.set_enabled(1, False)
    np.testing.assert_array_equal(st.result_bypassing(0).data, st.source.data)

def test_result_bypassing_rejects_an_out_of_range_index():
    with pytest.raises(IndexError, match="out of range"):
        stack_of(("dewow", {"window_ns": 4.0})).result_bypassing(1)

def test_a_cutoff_round_trips_through_dicts():
    st = stack_of(("time_cutoff", {"end_ns": 6.0}))
    again = StepStack.from_dicts(st.to_dicts())
    assert again.entries[0][0].params == {"end_ns": 6.0}
```

(`source()` in that file is 64 samples at dt 0.2 from t0 0.0, so `end_ns=6.0` keeps 30 rows.)

- [ ] **Step 6: Run them and see them fail** with `AttributeError: 'StepStack' object has no attribute 'result_bypassing'`. Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_stack.py -q`.

- [ ] **Step 7: Implement `StepStack.result_bypassing`.** Start from `self.intermediate(index - 1)` (or `self._source` when `index == 0`), so the cached prefix is reused and only the real chain is ever cached. Then apply each later enabled step in order, without caching.

- [ ] **Step 8: Run it and see it pass.** Same command.

- [ ] **Step 9: Update the registry-wide tests the new step and kind touch.** In `test_schema.py`, `_placeholder` returns `1.0` for `"time"` as well as `"float"`. `test_only_the_two_known_steps_have_required_params` becomes `test_only_the_known_steps_have_required_params` and adds `"time_cutoff": ("end_ns",)` to the expected dict; keep its docstring's point and add one line on why. In `test_steps_background.py`, `_STEP_PARAMS` gains `"time_cutoff": {"end_ns": 10.0}`. Then add one real-data test to `test_real_files.py`:

```python
def test_a_cutoff_after_time_zero_keeps_the_first_rows_of_a_real_profile():
    h = read_header(FILES[0])
    rg = Radargram(data=read_samples(FILES[0])[0].astype(float), dt_ns=h.dt_ns, t0_ns=h.position_ns)
    stack = StepStack()
    stack.source = rg
    stack.append(build_step("time_zero", mode="first_break", threshold=0.25))
    zeroed = stack.result()
    stack.append(build_step("time_cutoff", end_ns=zeroed.t0_ns + 300 * zeroed.dt_ns))
    out = stack.result()
    assert out.n_samples == 300 and out.t0_ns == zeroed.t0_ns
    np.testing.assert_array_equal(out.data, zeroed.data[:300])
    assert stack.result_bypassing(1).n_samples == zeroed.n_samples
```

- [ ] **Step 10: Run the whole core + pure tier, lint and types.** Expected: 588 + the new tests passed, 2 skipped (the real-data tests must not be among the skips). ruff and mypy clean.

- [ ] **Step 11: Commit and push.**

```bash
git add packages/nsgeo-core
git commit -m "feat(core): time_cutoff step, the time parameter kind, and StepStack.result_bypassing"
git push
```

---

