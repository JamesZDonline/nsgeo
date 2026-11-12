### Task 1: The clock in the core

**Files:**
- Modify:
  - `packages/nsgeo-core/src/nsgeo/processing/base.py`: `Radargram`, the module docstring, and
    the new `retime_ns`.
  - `packages/nsgeo-core/src/nsgeo/processing/timezero.py`: the module docstring, `apply`, the
    schema help, and the new helpers.
  - `packages/nsgeo-core/src/nsgeo/processing/stack.py`
  - Docstrings: `packages/nsgeo-core/src/nsgeo/processing/timecutoff.py:1-5`,
    `packages/nsgeo-core/src/nsgeo/velocity.py:8-9`, and the comment at
    `packages/nsgeo-core/src/nsgeo/processing/migration.py:32-41`.
- Test:
  - `packages/nsgeo-core/tests/test_steps_timezero_dewow.py`
  - `packages/nsgeo-core/tests/test_stack.py`
  - `packages/nsgeo-core/tests/test_processing_base.py`
  - `packages/nsgeo-core/tests/test_real_files.py`
  - Number and comment updates only: `test_steps_migration.py:245-253`, `test_velocity.py:1-5`.

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - **New `Radargram` fields,** added after `dx_m` with defaults, so every existing construction
    and `replace()` still works:
    - `zero_ns: float = 0.0`: the radar-clock time this axis calls 0. Row `i` is at radar time
      `zero_ns + t0_ns + i * dt_ns`.
    - `zero_set: bool = False`: True once a Time zero step has set the clock.
  - **Clock conversions on `Radargram`:**
    - `Radargram.to_radar_ns(t)`, which returns `t + zero_ns`;
    - `Radargram.from_radar_ns(r)`, which returns `r - zero_ns`.

    Both accept a float or an array and return the same kind.
  - **`retime_ns(t, from_zero_ns: float, to_zero_ns: float)`** in `nsgeo.processing.base`. It
    returns `t + from_zero_ns - to_zero_ns`, for a float or an array. It is the one conversion
    rule (spec §4.3), and every later task calls it.
  - **In `nsgeo.processing.timezero`:**
    - `first_break_row(rg: Radargram, threshold: float = 0.2) -> int`. This is the existing
      `first_break` rule, moved out of `TimeZero._pick` so the fit strip's note can share it.
      `_pick` calls it.
    - `TIME_BASE_TIME_ZERO = "time_zero"` and `TIME_BASE_RADAR = "radar"`.
    - `sets_time_zero(steps: Iterable[Mapping[str, Any]]) -> bool`. True when any dict has
      `step == "time_zero"` and `enabled` true; a missing `enabled` counts as true.
    - `time_base_of(steps: Iterable[Mapping[str, Any]]) -> str`. One of the two constants.
  - **On `StepStack`:**
    - `StepStack.sets_time_zero() -> bool`, which checks the stack's enabled entries;
    - `StepStack.zero_ns() -> float`. With no enabled `time_zero`, it returns `source.zero_ns`
      when there is a source, else `0.0`. Otherwise it returns `intermediate(i).zero_ns` for the
      last enabled `time_zero` index `i`, so the steps after it never run. It raises `ValueError`
      when a source is needed and missing, as `result()` does.

- [ ] **Step 1: Write the failing tests**

In `test_steps_timezero_dewow.py`, replace `test_time_zero_updates_t0_consistently_with_dropped_rows`
and `test_time_zero_sample_zero_is_a_no_op` with these tests, and add the rest:

```python
def test_time_zero_makes_its_row_read_zero_and_records_its_radar_time():
    rg = make(n_samples=100, dt_ns=0.25, t0_ns=1.0)
    out = build_step("time_zero", mode="sample", sample=8).apply(rg)
    assert out.n_samples == 92
    assert out.t0_ns == 0.0
    assert out.times_ns()[0] == 0.0
    assert out.zero_ns == pytest.approx(1.0 + 8 * 0.25)
    assert out.zero_set is True


def test_time_zero_at_sample_zero_still_sets_the_clock():
    rg = make(n_samples=50, t0_ns=2.0)
    out = build_step("time_zero", mode="sample", sample=0).apply(rg)
    assert out.n_samples == 50
    assert out.t0_ns == 0.0
    assert out.zero_ns == pytest.approx(2.0)
    assert out.zero_set is True


def test_every_kept_row_keeps_its_radar_time():
    rg = make(n_samples=100, dt_ns=0.25, t0_ns=-3.0).replace(zero_ns=1.5)
    out = build_step("time_zero", mode="sample", sample=12).apply(rg)
    np.testing.assert_allclose(out.to_radar_ns(out.times_ns()), rg.to_radar_ns(rg.times_ns())[12:])


def test_a_second_time_zero_changes_nothing():
    data = np.zeros((200, 20))
    data[40:, :] = 100.0
    rg = make(n_samples=200).replace(data=data)
    once = build_step("time_zero", threshold=0.5).apply(rg)
    twice = build_step("time_zero", threshold=0.5).apply(once)
    assert twice.n_samples == once.n_samples
    assert twice.zero_ns == pytest.approx(once.zero_ns)
    assert twice.t0_ns == 0.0


def test_first_break_row_is_the_steps_own_pick():
    data = np.zeros((200, 20))
    data[40:, :] = 100.0
    rg = make(n_samples=200).replace(data=data)
    assert first_break_row(rg, 0.5) == 40
    assert build_step("time_zero", threshold=0.5).apply(rg).n_samples == 200 - first_break_row(rg, 0.5)


def test_sets_time_zero_reads_enabled_entries_only():
    assert sets_time_zero([{"step": "time_zero", "params": {}, "enabled": True}])
    assert sets_time_zero([{"step": "time_zero", "params": {}}])
    assert not sets_time_zero([{"step": "time_zero", "params": {}, "enabled": False}])
    assert not sets_time_zero([{"step": "dewow", "params": {}, "enabled": True}])
    assert time_base_of([]) == "radar"
    assert time_base_of([{"step": "time_zero", "params": {}, "enabled": True}]) == "time_zero"
```

In `test_processing_base.py`:

```python
def test_retime_ns_converts_between_clocks():
    assert retime_ns(10.0, -0.5, 0.0) == pytest.approx(9.5)
    assert retime_ns(10.0, 0.0, -0.5) == pytest.approx(10.5)
    np.testing.assert_allclose(retime_ns(np.array([1.0, 2.0]), 2.0, 0.5), [2.5, 3.5])


@pytest.mark.parametrize(
    "name, params",
    [
        ("dewow", {}), ("gain_agc", {}), ("gain_parametric", {}),
        ("gain_curve", {"points": [[0.0, 0.0], [10.0, 6.0]]}),
        ("bandpass", {"low_mhz": 100.0, "high_mhz": 800.0}),
        ("background_mean", {}), ("background_sliding", {"window_traces": 5}),
        ("background_svd", {}), ("amp_abs", {}), ("amp_square", {}), ("amp_envelope", {}),
        ("time_cutoff", {"end_ns": 10.0}), ("migrate_fk", {"velocity_m_ns": 0.1}),
    ],
)
def test_every_other_step_passes_the_clock_through(name, params):
    rg = Radargram(
        data=np.random.default_rng(0).normal(size=(128, 40)),
        dt_ns=0.2, t0_ns=0.0, dx_m=0.02, zero_ns=-1.25, zero_set=True,
    )
    out = build_step(name, **params).apply(rg)
    assert out.zero_ns == -1.25
    assert out.zero_set is True
```

Import whatever registers the steps, as `test_processing_base.py` already does.

The list must cover every registered step except `time_zero`. Add an assertion that it does:
`set(names) | {"time_zero"} == set(registered_names)`.

In `test_stack.py`:

```python
def test_zero_ns_runs_only_up_to_the_last_enabled_time_zero(monkeypatch):
    # Build a stack of: time_zero(sample=5), then a step that raises if it runs.
    # zero_ns() must return the source's radar time of row 5 without calling it.
    ...
    assert stack.zero_ns() == pytest.approx(src.t0_ns + 5 * src.dt_ns)


def test_zero_ns_is_the_sources_without_an_enabled_time_zero():
    # With the time_zero entry disabled, zero_ns() == 0.0, and sets_time_zero() is False.
    ...
```

The step that raises when it runs is the stack's last entry: a `dewow` whose `apply` the test
monkeypatches to raise.

In `test_real_files.py`, build each line's source the way the file already does:
`Radargram(data=read_samples(path)[0].astype(float), dt_ns=h.dt_ns, t0_ns=h.position_ns)`.

```python
@pytest.mark.parametrize("path", CAMPUS_LINES, ids=lambda p: p.name)
def test_the_default_time_zero_puts_each_campus_line_at_its_first_break(path):
    # Spec §2: the default pick lands on row 49 of every campus line: -0.4764 ns on the radar clock
    # (header position -11.0864, dt 0.216531; measured 2026-11-10).
    out = build_step("time_zero").apply(<source>)
    assert out.zero_ns == pytest.approx(-0.4764, abs=0.001)
    assert out.t0_ns == 0.0


@pytest.mark.skipif(not GPS_LINES, reason="no GPS survey in tests/data/local/with-dzg")
def test_the_gps_survey_first_breaks_sit_between_minus_1_56_and_minus_1_34_ns():
    zeros = {round(build_step("time_zero").apply(<source of p>).zero_ns, 3) for p in GPS_LINES}
    assert min(zeros) >= -1.57
    assert max(zeros) <= -1.34
    assert len(zeros) <= 2  # -1.559 and -1.3425 measured 2026-11-10: one sample apart
```

- [ ] **Step 2: Run them to make sure they fail**

Run the core command on the four test files.
Expected: FAIL, because `Radargram` has no `zero_ns` and `first_break_row`, `sets_time_zero` and
`retime_ns` do not exist.

- [ ] **Step 3: Implement**

- Add the fields, methods and functions listed in Interfaces.
- **`TimeZero.apply`:** at pick row `k`, return
  `rg.replace(data=rg.data[k:, :].copy(), t0_ns=0.0, zero_ns=rg.zero_ns + rg.t0_ns + k * rg.dt_ns, zero_set=True)`.
  Do this for every `k`, including 0; the `k <= 0` early return goes. Keep the
  "would leave no samples" refusal.
- **Schema help** for `mode`: "Find the first arrival automatically, or give the row. That row
  becomes 0 ns."
- **Docstrings:**
  - `base.py`'s module docstring says that `time_zero` relabels the clock and that `zero_ns`
    keeps every row's radar time.
  - `timecutoff.py:1-5` no longer says that `time_zero` "moves t0_ns" by cropping.
  - `velocity.py:8-9` says that depth is measured from 0 on the radargram's own clock, which is
    the first break after a Time zero step and the radar's zero without one.
- **`migration.py:32-41`:** rewrite the comment only. After a Time zero step, `t0_ns` is exactly
  0. The guard now catches a record with no Time zero step, and `MAX_T0_NS = 2.0` stays. In
  `test_steps_migration.py:245-253`, update the numbers and comment that describe the old
  −0.476 ns residual. Keep the assertions.

- [ ] **Step 4: Run them to make sure they pass, then run the whole core suite**

Run the core + pure command on `packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure`.
Expected: all pass, except tests elsewhere that pin the old crop-only clock.

- **Core tests:** fix them here. The spec's §9 list names them.
- **QGIS tests:** do not fix them here. They belong to Tasks 2, 3 and 5.

List any QGIS failures in your report.

- [ ] **Step 5: Lint, then commit and push**

```bash
git add -A packages/nsgeo-core
git commit -m "feat(processing): time_zero relabels the clock, so its row reads 0 ns (#97)"
git push
```

---

