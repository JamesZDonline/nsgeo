# Time Zero (#97) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After this change, the Time zero step relabels the clock, so the row it lands on reads
0 ns. Picks, saved fits, slices and exports all measure from that row, while every stored time
stays on the reflection it was made on.

**Architecture:**
- A `Radargram` carries `zero_ns`: the radar-clock time its axis calls 0.
- `time_zero` sets that field. Every other step passes it through.
- Every conversion between clocks goes through one core function, `retime_ns`.
- Stored times keep their own zero:
  - pick rows carry a `zero_ns` column;
  - saved fits keep their points on the radar clock, plus the zero their results were measured
    at;
  - cubes and exports record a time base.
- Readers convert whatever they read onto the clock they are drawing on.

**Tech Stack:** Python 3.9+, numpy (the core uses numpy only), QGIS 3.40 / 3.44 / 4.2 (PyQt5 and
PyQt6), GDAL, pytest.

**Spec:** `docs/superpowers/specs/2026-11-10-nsgeo-time-zero-design.md`. Read it first. §3 lists the
decisions, and §5 sets the rule for every stored time.

## Global Constraints

- **Run every test from the worktree root with `PYTHONPATH=packages/nsgeo-core/src`.** Without it,
  `.venv`'s editable `nsgeo` imports the main checkout's core. Below,
  `R=/home/jameszd/Documents/Github/archaeo_geophysics`.
  - **Core and pure:** `PYTHONPATH=packages/nsgeo-core/src $R/.venv/bin/python -m pytest <path> -q -p no:xonsh -p no:cacheprovider`
  - **QGIS:** `PYTHONPATH=packages/nsgeo-core/src QT_QPA_PLATFORM=offscreen $R/.venv-qgis/bin/python -m pytest <path> -q -p no:xonsh -p no:cacheprovider`. The whole QGIS suite takes about 12 minutes, so run single files while iterating.
- **Lint as CI does.** Line length is 100.
  - `$R/.venv/bin/ruff check .`
  - `$R/.venv/bin/ruff format --check .`
  - `$R/.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`
- **The core uses numpy only.** Python 3.9 floor in the core: `from __future__ import annotations`,
  and no `zip(strict=...)`. No new dependencies anywhere.
- **Plugin boundary rule.** Arithmetic and message text live in the core or in `slices_plan.py`,
  never in widgets. Every conversion between clocks is a call to `nsgeo.processing.base.retime_ns`.
- **Qt.** Use fully qualified enums. Every Qt-invoked slot guards its body with
  `try/except Exception`, because an escaping exception reaches `qFatal()` in CI.
- **No stored value is converted on open, and opening a site never dirties it** (spec §5 and §9).
  Old files mean what they always meant: a missing zero is the radar's own clock.
- **A hover preview never writes** (`session.add_pick`'s guard; spec §5.1).
- **Commits:** every message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  Push each commit to `origin nsgeo-time-zero` as you make it.
- **Real survey files are never committed.**
- **Other open branches touch the same files.**
  - `nsgeo-scopes-agree` (#100…) touches `slices_dock.py` and `site_scope.py`.
  - `nsgeo-refine-worker` (#120) touches `slices_engine.py`.
  - `nsgeo-placement-corrections` (#47, #3) touches the placement code.

  Before Task 5, run `git fetch && git merge origin/main`. Resolve conflicts in favour of main's
  behaviour plus this plan's additions.

## Before Task 1 (coordinator)

- Symlink the real data into the worktree, file by file. `tests/data/local/README.md` is tracked,
  so link the files rather than the folder.
  - Every top-level `FILE__0NN.DZT`/`.DZX` goes into `packages/nsgeo-core/tests/data/local/`.
  - Every file of `with-dzg/` goes into `packages/nsgeo-core/tests/data/local/with-dzg/`.
- Record a baseline with the two suites above: core + pure, then QGIS.

## Review Focus

These are the inputs most likely to hurt a user that the spec does not spell out. Each one is
pinned by a test in the task named.

1. **Velocity points clicked on both sides of a time-zero change.** The user clicks three points,
   adds or edits Time zero, then clicks two more. All five must stay on the hyperbola they were
   clicked on, and the fit must equal a fit of those five points on the new clock. Pinned in
   Task 3 by `test_working_points_stay_on_their_reflection_across_a_time_zero_change`.
2. **A line whose file cannot be read when its zero is needed:** moved, renamed, or on an
   unplugged drive.
   - The velocity dialog opens with each fit's stored values.
   - Picks keep their rows.
   - Nothing raises out of a slot.

   Pinned in Task 3 by `test_the_dialog_shows_stored_values_when_the_line_cannot_be_read`, and in
   Task 4 by `test_a_line_that_cannot_be_read_leaves_its_picks_alone`.
3. **A click on a cutoff or gain handle with no movement,** on a step whose clock differs from the
   view's. Converting from the view and back must not make a phantom edit that dirties the site.
   Pinned in Task 2 by `test_an_unmoved_handle_across_clocks_writes_nothing`.
4. **A channel switch on a line with picks.** The new channel's first break can differ, so the
   rows must follow the new zero. `set_channel` is not one of the stack edits the spec lists.
   Pinned in Task 4 by `test_a_channel_switch_moves_picks_to_the_new_channels_zero`.
5. **An old cube recipe whose lines all fail to prepare.** There is no median zero to shift by.
   The range must restore unshifted, with no message and no exception. Pinned in Task 5 by
   `test_an_old_recipe_with_nothing_prepared_is_not_shifted`.

---

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

### Task 2: The profile draws on the radargram's own clock

**Files:**
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`: `_set_axes_holding`, `_render`,
    `_show_line`, `_refresh_picks`, `_show_cutoff`, `_on_cutoff_dragged`, plus new helpers.
  - `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`: `_sync_gain_strip` and `_on_gain_points`.
- Test:
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_time_cutoff.py`
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py`
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py`
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py:346-372`

**Interfaces:**
- Consumes: `Radargram.zero_ns` and `retime_ns` from Task 1.
- Produces, on `ProfileDock`:
  - `_shown_radargram: Radargram | None`. Set in `_render` to the radargram it drew. Set to
    `None` in `_show_line`'s header-only branch and in `_clear`.
  - `shown_zero_ns() -> float`: `_shown_radargram.zero_ns`, or `0.0` when it is None.
  - `step_input_zero_ns(row: int) -> float`: the `zero_ns` of what the working stack's step at
    `row` receives. That is `intermediate(row - 1)`, or the source when `row == 0`. It returns
    `0.0` when there is no source, or when the stack raises `ValueError`.

- [ ] **Step 1: Write the failing tests**

In `test_plugin_time_cutoff.py`, use its `_plugin_with_line` and `_unload`. The synthetic header
puts row 0 at −11.0864 ns with `dt = 0.216531`, so `time_zero(sample=51)` makes
`zero = -0.0433` ns.

```python
def test_a_cutoff_ahead_of_time_zero_is_drawn_and_dragged_on_its_own_clock(fake_iface, tmp_path, answer_modal):
    plugin, s, key = _plugin_with_line(fake_iface, tmp_path)
    try:
        s.append_step(key, build_step("time_cutoff", end_ns=60.0))
        s.append_step(key, build_step("time_zero", mode="sample", sample=51))
        plugin.processing_dock.list.setCurrentRow(0)
        dock = plugin.profile_dock
        zero = dock.shown_zero_ns()
        assert zero == pytest.approx(-0.0433, abs=1e-3)
        assert dock.view.cutoff_ns == pytest.approx(60.0 - zero)
        dock.view.cutoff_dragged.emit(40.0)
        assert s.stack_for(key).entries[0][0].params["end_ns"] == pytest.approx(40.0 + zero)
    finally:
        _unload(plugin, answer_modal)


def test_an_unmoved_handle_across_clocks_writes_nothing(fake_iface, tmp_path, answer_modal):
    # Review Focus 3: the same stack, but emit the line's own drawn value back.
    # The dirty flag stays as it was before the emit, and the step object is unchanged (`is`).
    ...
```

In `test_plugin_gain_strip.py`, use its plugin fixture:

```python
def test_a_gain_curve_ahead_of_time_zero_is_shown_and_written_on_its_own_clock(...):
    # Stack: gain_curve(points=[[0.0, 0.0], [40.0, 12.0]]), then time_zero(sample=51); select row 0.
    zero = plugin.profile_dock.shown_zero_ns()
    assert plugin.profile_dock.gain_strip.points() == pytest.approx([[0.0 - zero, 0.0], [40.0 - zero, 12.0]])
    plugin.profile_dock.gain_strip.points_changed.emit([[0.0 - zero, 0.0], [30.0 - zero, 12.0]])
    assert step_points(s, key, 0) == pytest.approx([[0.0, 0.0], [30.0, 12.0]])
```

Also add a no-movement case to this file: emitting the strip's own `points()` back writes
nothing.

In `test_plugin_profile_dock.py`, use the existing opened-line fixture:

```python
def test_a_time_zero_that_crops_nothing_still_moves_the_axis(...):
    # Synthetic line, then append time_zero(mode="sample", sample=0).
    assert dock.view.transform.t0_ns == 0.0     # was -11.086; spec §4.4's Rule 1 trap


def test_picks_stay_on_their_sample_when_time_zero_is_added(...):
    session.add_pick(key, 30, 20.0)               # radar clock: no step yet
    session.append_step(key, build_step("time_zero", mode="sample", sample=51))
    zero = dock.shown_zero_ns()
    assert dock.view._picks == [(30, pytest.approx(20.0 - zero))]
```

In `test_plugin_param_form.py:346-372`, change the ground truth.
`time_zero(sample=5)` now gives `t0 == 0.0` and `n == source.n_samples - 5`. Keep
`t0 != approx(source.t0_ns)`, and update the docstring.

- [ ] **Step 2: Run the four files to make sure the new tests fail**

Run the QGIS command on those files.
Expected: the new tests FAIL. The cutoff line, the strip points and the picks are still on the
step's clock, and the axis stays at −11.086.

- [ ] **Step 3: Implement**

- **`_set_axes_holding`:** add `t0_ns` and `dt_ns` to both comparisons that put back the old
  transform: Rule 1's tuple and the `ruler is None` branch.
- **`_render`:** set `_shown_radargram = rg` before the axes. Call `_refresh_picks()` after
  `_update_velocity_fit()`, because a stack change can now move every pick on screen.
- **`_refresh_picks`:** draw each pick at `retime_ns(p.time_ns, 0.0, self.shown_zero_ns())`.
  Today's stored `time_ns` is on the radar clock. Task 4 replaces the `0.0` with the pick's own
  zero.
- **`_show_cutoff`:** draw at
  `retime_ns(value, self.step_input_zero_ns(row), self.shown_zero_ns())`.
- **`_on_cutoff_dragged(end_ns)`:**
  1. Return without writing when `end_ns` equals the value as drawn (the line above).
  2. Otherwise write `retime_ns(end_ns, self.shown_zero_ns(), self.step_input_zero_ns(row))`.
- **`plugin._sync_gain_strip`:** hand the strip points converted with the same
  `retime_ns(t, input, shown)`.
- **`plugin._on_gain_points`:**
  1. Compare the emitted points with the step's own points converted to the shown clock. If they
     are equal, return without writing.
  2. Otherwise convert the emitted points to the input clock and write them.

  Comparing in the shown clock is what keeps an unmoved handle from writing.

- [ ] **Step 4: Run the four files, then every QGIS file that mentions `time_zero`, cutoff or gain**

Run the QGIS command on `test_plugin_time_cutoff.py test_plugin_gain_strip.py test_plugin_profile_dock.py test_plugin_param_form.py test_plugin_processing_dock.py test_plugin_profile_view.py`.
Expected: all pass.

- [ ] **Step 5: Lint, then commit and push**

```bash
git commit -am "feat(profile): draw picks, cutoff and gain curve on the radargram's own clock (#97)"
git push
```

---

### Task 3: Saved fits follow the line's time zero

**Files:**
- Modify:
  - `packages/nsgeo-core/src/nsgeo/velocity_fit.py`
  - `packages/nsgeo-qgis/nsgeo_qgis/session.py` (new `line_zero`)
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`: the velocity sections, and
    `velocity_source`.
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/velocity_dialog.py`
- Test:
  - `packages/nsgeo-core/tests/test_velocity_fit.py`
  - `packages/nsgeo-core/tests/test_project.py`
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_velocity_fit.py`
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_velocity_dialog.py`
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py`

**Interfaces:**
- Consumes:
  - from Task 1: `retime_ns`, `first_break_row`, `StepStack.zero_ns`, `StepStack.sets_time_zero`;
  - from Task 2: `ProfileDock.shown_zero_ns`.
- Produces:
  - **`StoredFit.zero_ns: float = 0.0`,** the last field.
    - Its `points` are on the radar clock, which is what every existing fit already holds.
    - `zero_ns` is the radar-clock time that `t0_ns`, `v_m_ns`, `v_stderr_m_ns` and `rms_ns`
      were measured from.
    - `to_dict` writes `"zero_ns"`. `from_dict` reads `doc.get("zero_ns", 0.0)`.
    - This representation is the plan's call within spec §5.2. It carries the same information
      as "points as clicked plus their zero", and old fits need no conversion.
  - **`refit(fit: StoredFit, distance_m: np.ndarray, zero_ns: float) -> HyperbolaFit`** in
    `nsgeo.velocity_fit`.
    - `x` is `distance_m` at each point's trace, clamped to the line.
    - `t` is each point's radar time minus `zero_ns`.
    - The apex guess is `x[0]`, the first click, with `fit_hyperbola`'s default search.
    - It raises `ValueError` as `fit_hyperbola` does.
  - **`fit_at_zero(fit: StoredFit, distance_m: np.ndarray, zero_ns: float) -> StoredFit`.**
    - When `zero_ns == fit.zero_ns`, it returns `fit` itself.
    - Otherwise it calls `dataclasses.replace(fit, ...)` with the refit's `t0_ns`, `v_m_ns`,
      `v_stderr_m_ns` and `rms_ns`, with `apex_trace` set to the index of `distance_m` nearest the
      refit apex, and with `zero_ns=zero_ns`.
    - It raises `ValueError` when the refit fails.
  - **`radar_clock_note(first_break_ns: float, dt_ns: float, v_now: float | None, v_from_break: float | None) -> str`.**
    - It returns `""` when `abs(first_break_ns) <= dt_ns / 2`.
    - Otherwise it returns the spec §7 text, ASCII-formatted:
      `"Times are from the radar's own zero; the first break is at -0.5 ns. Measured from the first break, this fit would be 0.0712 m/ns (+1.2%). Add a Time zero step to measure from it."`
    - The middle sentence appears only when both velocities are given. The percentage is
      `(v_from_break / v_now - 1) * 100`, with a sign and one decimal.
  - **`applied_fit_note(applied_v: float, current_v: float) -> str`.** It returns `""` when the
    two agree at 4 dp. Otherwise it returns
    `f"applied {applied_v:.4f}; measured from the current time zero {current_v:.4f}"`.
  - **`SiteSession.line_zero(key: str, *, load: bool = False) -> float | None`:** the radar-clock
    time the line's own stack calls 0.
    - **No time zero in the stack:** `0.0`, without loading. It reads
      `stack_for(key, insert=False).sets_time_zero()`.
    - **Source attached:** `stack.zero_ns()`.
    - **No source, `load=True`:** read the line with `line.load()`, build
      `Radargram.from_profile(profiles[self.channel(key)])`, run a **copy**
      (`StepStack.from_dicts(stack.to_dicts())`) and return its `zero_ns()`.
    - **No source, `load=False`:** `None`.
    - **On any failure** (`ValueError`, `OSError`, a bad step): log it and return `None`. Never
      raise.
    - The `stack_for(..., insert=False)` guard means a read never plants a stack.
  - **The working velocity points (`ProfileDock._velocity_points`, `velocity_points()`) are on the
    radar clock.** A click at shown time `t` stores `t + shown_zero_ns()`.

- [ ] **Step 1: Write the failing tests**

In `test_velocity_fit.py`:

```python
def test_refit_at_the_fits_own_zero_reproduces_it():
    # Synthetic hyperbola, t0 20 ns, v 0.1, 9 points; fit_hyperbola, then store the points on the
    # radar clock with zero_ns=-0.5, and the times as fitted + (-0.5).
    again = refit(stored, distance, -0.5)
    assert again.v_m_ns == pytest.approx(stored.v_m_ns, rel=1e-12)
    assert again.t0_ns == pytest.approx(stored.t0_ns, rel=1e-12)


def test_refit_at_a_moved_zero_equals_a_fresh_fit_of_the_shifted_points():
    moved = refit(stored, distance, -2.0)
    fresh = fit_hyperbola(x, radar_t - (-2.0), x[0])
    assert moved.v_m_ns == pytest.approx(fresh.v_m_ns, rel=1e-12)


def test_fit_at_zero_returns_the_stored_fit_when_the_zero_is_unchanged():
    assert fit_at_zero(stored, distance, stored.zero_ns) is stored
    assert fit_at_zero(stored, distance, -2.0).zero_ns == -2.0


def test_an_old_fit_reads_as_the_radar_clock():
    assert StoredFit.from_dict({<a fit dict without "zero_ns">}).zero_ns == 0.0


@pytest.mark.parametrize("fb, quiet", [(-0.10, True), (0.108, True), (-0.48, False), (-11.0, False)])
def test_radar_clock_note_is_quiet_within_half_a_sample(fb, quiet):
    assert (radar_clock_note(fb, 0.2165, None, None) == "") is quiet


def test_radar_clock_note_names_the_first_break_and_the_corrected_velocity():
    text = radar_clock_note(-0.48, 0.2165, 0.0703, 0.0712)
    assert "first break is at -0.5 ns" in text
    assert "0.0712 m/ns (+1.3%)" in text
    assert text.endswith("Add a Time zero step to measure from it.")
```

In `test_project.py`, add a round trip: a fit saved with `zero_ns=-0.4775` loads back with it.

In `test_plugin_session.py`:

```python
def test_line_zero_is_zero_without_a_time_zero_step_and_loads_nothing(...):
    # Line with no profiles set and an empty stack: line_zero(key) == 0.0.
    # No stack was planted: key not in session.site.stacks.
    ...


def test_line_zero_loads_the_line_only_when_asked(...):
    # Stack with time_zero(sample=51) and no profiles.
    assert s.line_zero(key) is None
    assert s.line_zero(key, load=True) == pytest.approx(-0.0433, abs=1e-3)
```

In `test_plugin_velocity_fit.py`, replace
`test_time_zero_added_after_a_save_leaves_the_fit_on_its_feature_and_apply_still_names_it`,
`test_a_radargram_not_at_time_zero_warns_and_names_the_step`,
`test_time_zero_at_the_nearest_sample_is_quiet`,
`test_a_time_zero_more_than_half_a_sample_out_still_warns` and
`test_the_tolerance_scales_with_the_sample_interval` with:

```python
def test_adding_time_zero_moves_a_saved_fit_exactly_as_shifting_its_points(plugin):
    s, dock = plugin.session, _velocity_on(plugin)
    key = s.keys()[0]
    _click_hyperbola(plugin)
    dock.save_fit_button.click()
    (fit_id,) = s.line_for_key(key).velocity_fits
    stored = s.line_for_key(key).velocity_fits[fit_id]
    s.append_step(key, build_step("time_zero", mode="sample", sample=51))
    zero = s.line_zero(key)
    x = <distance at each stored point's trace>
    expected = fit_hyperbola(x, np.array([t for _, t in stored.points]) - zero, x[0])
    assert dock.velocity_fit_result().v_m_ns == pytest.approx(expected.v_m_ns, rel=1e-9)
    dock.apply_line_button.click()
    assert s.line_for_key(key).velocity_from_fit == fit_id   # points are compared on the radar clock


def test_without_time_zero_the_note_names_the_first_break(plugin):
    dock = _velocity_on(plugin)
    assert "radar's own zero" in dock.velocity_note.text()


@pytest.mark.parametrize("sample", [49, 50, 51, 52])
def test_with_a_time_zero_step_the_note_is_quiet(plugin, sample):
    dock = _time_zero_to(plugin, sample)
    assert dock.velocity_note.text() == ""


def test_a_disabled_time_zero_brings_the_note_back(plugin):
    dock = _time_zero_to(plugin, 51)
    plugin.session.set_step_enabled(plugin.session.keys()[0], 0, False)
    assert "radar's own zero" in dock.velocity_note.text()


def test_working_points_stay_on_their_reflection_across_a_time_zero_change(plugin):   # Review Focus 1
    # Click APEX_TRACE, 15 and 45; append time_zero(sample=51); click 5 and 55, each at
    # _hyperbola_ns(tr) - shown_zero (the same reflection on the new clock).
    # The fit equals fit_hyperbola of all five radar times minus line_zero.
    ...
```

In `test_plugin_velocity_dialog.py`:

```python
def test_the_dialog_lists_each_fit_at_the_lines_current_zero(...):
    # Save a fit with no step; add time_zero(sample=51). The velocity cell shows the refit's v
    # (fit_at_zero), not the stored one.
    ...


def test_the_dialog_flags_an_applied_velocity_its_fit_no_longer_measures(...):
    # Save and Apply with no step; add time_zero(sample=51). flag_text(row) contains
    # applied_fit_note(applied, current). Apply in the dialog sets the refit v and keeps
    # velocity_from_fit.
    ...


def test_the_dialog_shows_stored_values_when_the_line_cannot_be_read(...):   # Review Focus 2
    # Stack with time_zero; the DZT file is renamed away before the dialog opens.
    # The dialog opens, the cells show the stored fit's numbers, and nothing is logged Critical.
    ...
```

Spec §9 also asks for a real-ground fit to match the shifted-points fit. The repo holds no
clicked points on real ground, so these synthetic refits stand in for it. The walkthrough's fit
check (§10, item 4) is the real-data check.

- [ ] **Step 2: Run them to make sure they fail**

Run the core command on `test_velocity_fit.py test_project.py`, and the QGIS command on the three
QGIS files.
Expected: FAIL. `refit`, `fit_at_zero`, `line_zero` and `StoredFit.zero_ns` do not exist, and the
note still warns after the step.

- [ ] **Step 3: Implement**

- **Core:** add the functions and the field in Interfaces.
- **`SiteSession.line_zero`:** add it as specified.
- **`ProfileDock`:**
  - `_on_velocity_point_requested` stores `(trace, time_ns + self.shown_zero_ns())`.
  - `velocity_points_in_metres()` returns times on the line's own clock:
    `retime_ns(t, 0.0, line_zero)`, with `line_zero = session.line_zero(working_key) or 0.0`.
  - The fitted curve is computed on the line's clock. It is drawn with
    `retime_ns(t, line_zero, shown_zero)`. So are the working points: `retime_ns(t, 0.0, shown_zero)`.
  - `_saved_velocity_curves()` draws `fit_at_zero(f, distance, line_zero)` for each fit, and
    skips a fit whose refit raises.
  - `_save_velocity_fit` stores the radar-clock points, `zero_ns=line_zero`, and the current fit's
    numbers.
  - Apply's points-equality match stays as it is, because both sides are on the radar clock.
    Rewrite its comment, which says no step rebases time.
  - Rewrite `_velocity_time_zero_note()` to read the **working line's own stack result**, not the
    view.
    1. Return `""` when there is no working line, no source, or `result().zero_set`.
    2. Otherwise find `fb = rg.t0_ns + first_break_row(rg) * rg.dt_ns`.
    3. When there is a fit, refit the working points with times shifted by `-fb`; a `ValueError`
       there means "no corrected velocity".
    4. Return `radar_clock_note(fb, rg.dt_ns, v_now, v_from_break)`.
- **`velocity_source`:** when the override names a fit and `session.line_zero(key)` is known and
  differs from `fit.zero_ns`, label it with `fit_at_zero(...).t0_ns`. If that raises, fall back to
  the stored `t0_ns`.
- **`VelocityDialog._fill_table`:**
  - Build `self._fits` from `fit_at_zero(f, distance, zero)` for each fit, with
    `zero = session.line_zero(key, load=True)`.
  - When `zero` is None, or the line has no distance calibration, keep the stored fits.
  - A fit whose refit raises keeps its stored values. Its flag cell says
    `f"cannot be fitted at this time zero: {exc}"`.
  - Join the flag cell's parts with `"; "`: the existing disagreement flag, then
    `applied_fit_note(line.velocity.surface_velocity, current.v_m_ns)` for the fit that
    `velocity_from_fit` names.
  - Everything downstream already reads `self._fits`: sorting, selection, `velocity()` and the
    disagreement check.

- [ ] **Step 4: Run the files, then the whole velocity area**

Run the core command on `packages/nsgeo-core/tests`, and the QGIS command on
`test_plugin_velocity_fit.py test_plugin_velocity_dialog.py test_plugin_session.py test_plugin_profile_dock.py test_plugin_slices_dock.py`.
Expected: all pass. The last file is included because `slices_dock.py:2737` also calls
`velocity_source`.

- [ ] **Step 5: Lint, then commit and push**

```bash
git commit -am "feat(velocity): saved fits are measured from the line's current time zero (#97)"
git push
```

---

### Task 4: Pick rows follow their line's zero

**Files:**
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/session.py`: `Pick`, `add_pick`.
  - `packages/nsgeo-qgis/nsgeo_qgis/layers.py`: `TABLES["picks"]`, `write_pick`, `_row_to_pick`,
    the new `follow_zero`, and the wiring.
  - `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`: `_on_pick_requested`.
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`: `_refresh_picks`.
- Test:
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py`
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py`

**Interfaces:**
- Consumes:
  - from Task 1: `retime_ns`;
  - from Task 2: `ProfileDock.shown_zero_ns`;
  - from Task 3: `SiteSession.line_zero`.
- Produces:
  - **`Pick.zero_ns: float | None = None`,** the last field. None means the radar clock.
  - **`Pick.radar_ns`,** a property: `time_ns + (zero_ns or 0.0)`.
  - **The picks table gets a `("zero_ns", "float")` column,** listed right after `("time_ns", "float")`.
    `_ensure_table` sees the changed field set and routes it through `_rebuild_picks`. That
    migrates rows by field name, so every existing row keeps its values with `zero_ns` NULL.
  - **`SiteSession.add_pick(key, trace, time_ns, *, zero_ns: float = 0.0) -> Pick`.**
    - `time_ns` is measured from `zero_ns`, so its radar time is `time_ns + zero_ns`.
    - It clamps the **radar** time into the header window, as today.
    - It then stores the time measured from `line_zero(key)`, with that zero.
    - When `line_zero(key)` is None, it stores the radar time with `zero_ns=None`.
    - `derived_pick_fields` gets the stored time.
  - **`SiteLayers.follow_zero(key: str, zero_ns: float) -> int`.**
    - It rewrites the rows of `key` whose stored zero (NULL counts as 0.0) differs from `zero_ns`.
    - For each row:
      - `time_ns` becomes `retime_ns(time_ns, old, zero_ns)`;
      - `zero_ns` becomes `zero_ns`;
      - `depth_m` and `velocity_m_ns` come from `derived_pick_fields`.
    - It writes through the data provider only, as `follow_lines` does. It returns the number of
      rows written.
    - It skips rows with a NULL trace or time.
  - **`SiteLayers._on_line_clock_changed(key: str)`,** connected to `session.stack_changed` and
    `session.line_loaded`.
    - It returns at once:
      - for a preview-only key (`key == session.preview_key != session.current_key`);
      - when the key has no pick rows;
      - when `session.line_zero(key, load=True)` is None.
    - Otherwise it calls `follow_zero`.
    - The body is guarded, and a failure is logged Critical.

- [ ] **Step 1: Write the failing tests**

In `test_plugin_layers.py`, next to the pre-M8 migration test:

```python
def test_a_pre_time_zero_picks_table_migrates_with_its_rows_intact(qgis_app, tmp_path, message_log):
    # As test_a_package_with_the_pre_m8_picks_schema_..., with old_spec = TABLES["picks"][1]
    # minus "zero_ns" and two authored rows. After reopening: same rows, same time_ns,
    # zero_ns NULL; picks_for() gives Pick.zero_ns None; session.dirty is False.
    ...


def test_adding_time_zero_moves_a_rows_time_but_not_its_sample(...):
    # Pick at (30, 20.0) on the radar clock, line loaded; append time_zero(sample=51).
    row = picks_row(...)
    assert row["zero_ns"] == pytest.approx(zero)
    assert row["time_ns"] == pytest.approx(20.0 - zero)
    assert row["time_ns"] + row["zero_ns"] == pytest.approx(20.0)
    assert row["depth_m"] == pytest.approx(model.depth_at([20.0 - zero])[0])


def test_changing_the_threshold_keeps_picks_on_their_sample(...):
    # replace_step with another sample; the radar time is unchanged, the row follows.
    ...


def test_applying_a_stack_to_the_grid_moves_picks_on_lines_not_open(...):
    # A row written on line 2 (never loaded) with zero_ns None; apply line 1's stack (time_zero)
    # to the grid. Line 2's row now carries line 2's zero (it was loaded to find it).
    ...


def test_a_hover_load_never_rewrites_picks(...):
    # Line 2 has a time_zero stack and a row with zero_ns None. Only previewing it and loading
    # its profiles (set_preview, set_profiles) leaves the row byte-for-byte unchanged.
    ...


def test_a_channel_switch_moves_picks_to_the_new_channels_zero(...):   # Review Focus 4
    # set_profiles(key, [p0, dataclasses.replace(p0, data=np.roll(p0.data, 10, axis=0))]) with a
    # first_break time_zero stack; pick; set_channel(key, 1). The row's zero moves by 10 * dt, and
    # its radar time is unchanged.
    ...


def test_a_line_that_cannot_be_read_leaves_its_picks_alone(...):   # Review Focus 2
    # time_zero stack on an unloaded line whose file was renamed away; apply_stack_to_grid.
    # The row is unchanged, and nothing escapes the slot.
    ...


@needs_real_data
def test_on_a_real_line_adding_time_zero_moves_a_pick_by_its_first_break(...):
    # REAL_DZT[0], default time_zero: the row's time_ns grows by 0.4764 ns (spec §2), and its
    # depth follows.
    ...
```

In `test_plugin_session.py`:

```python
def test_a_pick_made_on_a_relabelled_view_is_stored_from_the_lines_zero(...):
    # time_zero(sample=51), line loaded. add_pick(key, 30, 5.0, zero_ns=zero) stores time_ns 5.0
    # and zero_ns zero. The same pick given on the radar clock, add_pick(key, 30, 5.0 + zero),
    # stores the same row.
    ...
```

- [ ] **Step 2: Run them to make sure they fail**

Run the QGIS command on the two files.
Expected: FAIL. There is no `zero_ns` column, `add_pick` takes no `zero_ns`, and nothing follows
a stack change.

- [ ] **Step 3: Implement**

- **The Interfaces items above.**
- **`write_pick`** writes `("zero_ns", pick.zero_ns)`.
- **`_row_to_pick`** reads `_as_float(_attr(feature, "zero_ns"))`.
- **`plugin._on_pick_requested`** calls
  `add_pick(key, trace, time_ns, zero_ns=self.profile_dock.shown_zero_ns())`.
- **`ProfileDock._refresh_picks`** draws `retime_ns(p.radar_ns, 0.0, self.shown_zero_ns())`.
- **The `follow_lines` docstring** says that `time_ns` is measured from the row's `zero_ns`, and
  that `follow_zero` is the only writer of the time.

- [ ] **Step 4: Run them, then every picks file**

Run the QGIS command on `test_plugin_layers.py test_plugin_session.py test_plugin_profile_dock.py test_plugin_map_link.py test_plugin_profile_view.py test_plugin_loads.py`.
Expected: all pass, including every existing picks migration test.

- [ ] **Step 5: Lint, then commit and push**

```bash
git commit -am "feat(picks): a pick row keeps its zero and follows its line's time zero (#97)"
git push
```

---

### Task 5: Cubes on the time-zero clock

Run `git fetch && git merge origin/main` first (Global Constraints).

**Files:**
- Modify:
  - `packages/nsgeo-core/src/nsgeo/slices/binning.py` (`PreparedLine`)
  - `packages/nsgeo-core/src/nsgeo/slices/store.py` (`_meta`)
  - `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`: the prepare `work()`, plus `line_zero`
    and `median_zero`.
  - `packages/nsgeo-qgis/nsgeo_qgis/site_engine.py` (`line_zero`)
  - `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py`: `cube_record`, `CubeRecipe`,
    `recipe_from_record`.
  - `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py` (`old_cube_note`)
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`: `restore_cube`, `_on_prepared`, and
    `line_zero_in_cube`.
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`: `set_slice_band`, `clear_slice_band`,
    and `_render`.
  - `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`: the cube save call and the band lookup wiring.
- Test:
  - `packages/nsgeo-core/tests/test_slices_store.py`
  - `packages/nsgeo-qgis/tests/pure/` (the existing `slices_plan` test file)
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export.py`
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py:1694-1700` (comment and numbers
    only)

**Interfaces:**
- Consumes:
  - from Task 1: `zero_ns`, `retime_ns`, `sets_time_zero`, `time_base_of`;
  - from Task 2: `shown_zero_ns`.
- Produces:
  - **`PreparedLine.zero_ns: float = 0.0`,** the last field. The engine sets it from
    `result.zero_ns`.
  - **On `SliceEngine`:**
    - `SliceEngine.line_zero(key: str) -> float | None`, from the prepared lines;
    - `SliceEngine.median_zero() -> float | None`, the `np.median` of the prepared lines' zeros,
      or None when nothing is prepared.
  - **`SiteEngine.line_zero(key: str) -> float | None`:** the first non-None answer from its grid
    engines.
  - **`SlicesDock.line_zero_in_cube(key: str) -> float | None`:** from the scope on screen. That
    is `self.engine` for This grid, or the site engine.
  - **`cube_record(..., *, line_keys, time_base: str)`:** a new required keyword, written as
    `record["time_base"]`. The one caller in `plugin.py` passes
    `time_base_of(engine.provenance().steps)`.
  - **`CubeRecipe.time_base: str | None = None`.** None means the record predates the marker.
    `recipe_from_record` raises `ValueError` for a present value that is not one of the two
    constants.
  - **The cube store's `_meta`** gains `"time_base": time_base_of(cube.provenance.steps)`.
    `STORE_VERSION` is unchanged, because the key is additive and readers ignore it.
  - **`slices_plan.old_cube_note(shift_ns: float) -> str`:**
    `f"This cube was saved before times were measured from each line's first break. It was rebuilt that way, with its range moved by {shift_ns:+.2f} ns."`
  - **`ProfileDock.set_cube_zero_lookup(fn: Callable[[str], float | None] | None) -> None`.**
    - `set_slice_band(lo, hi)` stores the cube-clock band and draws it through
      `_push_slice_band()`.
    - `_push_slice_band()` converts with
      `retime_ns(t, fn(displayed_key) if known else self.shown_zero_ns(), self.shown_zero_ns())`.
    - `_render` calls `_push_slice_band()`.
    - `clear_slice_band` forgets the stored band.
    - `plugin.py` wires it with `set_cube_zero_lookup(self.slices_dock.line_zero_in_cube)`.

- [ ] **Step 1: Write the failing tests**

In `test_plugin_slices_dock.py`:
- Rework `test_prepared_z_bounds_is_the_intersection_not_the_union` (`:1785-1860`).
  `assert len(starts) == 3` becomes two assertions:
  - `assert starts == {0.0}`: decision 1, every line reads 0 at its first break;
  - `assert len({round(l.zero_ns, 6) for l in prepared}) == 3`: three different zeros.

  Keep the ends and the tightness checks. Update the docstring.
- Rework the comment and numbers in `:1723-1780` (−0.476..99.561). Keep the assertions unless the
  numbers move.

Then add:

```python
def test_a_cube_built_with_time_zero_starts_at_zero(...):
    # Preset [time_zero] on two synthetic lines.
    assert dock.engine.prepared_z_bounds()[0] == 0.0
    assert dock.z0_spin.value() == 0.0


def test_an_old_recipe_with_time_zero_restores_its_range_moved_by_the_median_zero(...):
    # A record without "time_base", z {t0_ns: 5.0, t1_ns: 40.0, dz_ns: 0.5}, preset [time_zero].
    # After restore and preparation, z0 == approx(5.0 - median), where median is the engine's
    # median_zero(). dock.error received old_cube_note(-median) exactly once.
    ...


def test_an_old_recipe_without_time_zero_restores_unchanged(...):
    ...


def test_an_old_recipe_with_nothing_prepared_is_not_shifted(...):   # Review Focus 5
    # Every line's file renamed away; restore: z0 stays 5.0, no note, no exception logged.
    ...


def test_the_slice_band_marks_the_same_samples_on_a_line_whose_stack_differs(...):
    # Preset [time_zero]; the working line's own stack is empty (radar clock). Band (10, 12) on the
    # cube clock is drawn at (10 + line_zero, 12 + line_zero) on the profile.
    ...
```

In `test_plugin_slice_export.py`:

```python
def test_a_cube_record_names_its_time_base(...):
    assert record["time_base"] == "time_zero"
    assert recipe_from_record(record).time_base == "time_zero"
    assert recipe_from_record({**record_without_time_base}).time_base is None
    with pytest.raises(ValueError):
        recipe_from_record({**record, "time_base": "sideways"})
```

In `test_slices_store.py`, add a test that a saved cube's metadata carries `"time_base"`,
matching its provenance steps, and that `load_cube` still reads it.

- [ ] **Step 2: Run them to make sure they fail**

Run the QGIS command on `test_plugin_slices_dock.py test_plugin_slice_export.py`, and the core
command on `test_slices_store.py`.
Expected: FAIL.

- [ ] **Step 3: Implement**

- **The Interfaces items above.**
- **`restore_cube`:** when `recipe.time_base is None` and the record's preset sets a time zero,
  set `self._pending_z_shift = True`. Check this with `sets_time_zero` on
  `session.site.presets.get(recipe.choice.preset, [])`.
- **`_on_prepared`:** consume the flag before `_clamp_z_to_prepared()`, the way it consumes
  `_pending_palette`.
  - If `engine.median_zero()` is not None, move both z spins by `-median`, using the same
    signal-blocked writes `_clamp_z_to_prepared` uses.
  - Emit `old_cube_note(-median)` once on `self.error`.
  - Clear the flag on every pass, so it never outlives one preparation.
- **The header seeds** (`_seed_dz_z_defaults`, `site_scope.header_z_seed`) need no change. Their
  −11.09 ns start is clamped into the prepared bounds. Confirm that the existing
  `test_the_seeded_z_range_survives_a_preset_that_crops_the_sample_axis` still passes, and record
  the result in your report (spec §4.3, "shown harmless").

- [ ] **Step 4: Run every slices file**

Run the QGIS command on
`test_plugin_slices_dock.py test_plugin_slices_engine.py test_plugin_slice_export.py test_plugin_site_engine.py test_plugin_site_scope.py test_plugin_slice_layer.py`,
and the core command on `packages/nsgeo-core/tests`.
Expected: all pass.

- [ ] **Step 5: Lint, then commit and push**

```bash
git commit -am "feat(slices): cubes on the time-zero clock; old recipes restore at their old depths (#97)"
git push
```

---

### Task 6: Mixed clocks in a site, and the time base in every GeoTIFF

**Files:**
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py` (`mixed_clock_note`)
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py`: `grid_time_bases` and `show_note`.
  - `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py`: the `GeoTiffSliceWriter.write` metadata.
  - `packages/nsgeo-qgis/nsgeo_qgis/site_export.py`: `SiteGridRecord`, `plan_site_export`, the
    dataset metadata, and the module docstring.
- Test:
  - `packages/nsgeo-qgis/tests/pure/` (the `slices_plan` tests)
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py`
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export.py`
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_site_export.py`

**Interfaces:**
- Consumes: from Task 1, `sets_time_zero`, `time_base_of` and the two constants.
- Produces:
  - **`slices_plan.mixed_clock_note(radar_grids: Sequence[str]) -> str`.** It returns `""` for an
    empty sequence. For one grid it returns
    `"Grid A has no Time zero step, so its times are from the radar's own zero and will not line up with the other grids."`.
    For several it returns `"Grids A, C have no Time zero step, so their times are …"`.
  - **`site_scope.grid_time_bases(session, source: SiteSource) -> dict[str, str]`:** grid id to
    `time_base_of(session.site.presets.get(choice.preset, []))`.
  - **`show_note`** appends `mixed_clock_note([...radar grids])` to the note and its hint.
    This happens only when the bases are **mixed**. When every grid is on the radar clock, they
    still line up, so it shows nothing.
  - **Per-grid GeoTIFF:** the dataset item `NSGEO_TIME_BASE` =
    `time_base_of(plan.provenance.steps)`. The coverage companion gets it too, because it shares
    the writer.
  - **Site GeoTIFF:**
    - `SiteGridRecord.time_base: str` is a new field, filled from each grid engine's
      `provenance().steps`.
    - The dataset item `NSGEO_SITE_TIME_BASE` is `"time_zero"`, `"radar"` or `"mixed"`.
    - The module docstring lists it.

- [ ] **Step 1: Write the failing tests**

In the pure tests:

```python
def test_mixed_clock_note_names_the_radar_grids():
    assert mixed_clock_note([]) == ""
    assert mixed_clock_note(["A"]).startswith("Grid A has no Time zero step")
    assert mixed_clock_note(["A", "C"]).startswith("Grids A, C have no Time zero step")
```

In `test_plugin_site_scope.py`:

```python
def test_the_site_note_warns_when_grids_are_on_different_clocks(...):
    # Grid A's preset has time_zero; grid B's does not.
    # site_note.text() contains mixed_clock_note(["B"]).
    ...


def test_the_site_note_says_nothing_when_every_grid_is_on_the_radar_clock(...):
    ...
```

In `test_plugin_slice_export.py`, test that an exported GeoTIFF's dataset metadata has
`NSGEO_TIME_BASE == "time_zero"` for a time_zero preset, and `"radar"` without one.

In `test_plugin_site_export.py`, test that a two-grid export with mixed presets writes
`NSGEO_SITE_TIME_BASE == "mixed"`, and that each `NSGEO_SITE_GRIDS` entry carries its own
`time_base`.

- [ ] **Step 2: Run them to make sure they fail**

Run the core command on the pure tests, and the QGIS command on the three QGIS files.
Expected: FAIL.

- [ ] **Step 3: Implement the Interfaces items**

- [ ] **Step 4: Run the full suites and lint**

Run the core + pure suite, the whole QGIS suite, and all three lint commands.
Expected: everything passes, and the counts are at least the baseline plus the new tests. Report
the counts.

- [ ] **Step 5: Commit and push**

```bash
git commit -am "feat(site): warn on mixed clocks; every GeoTIFF records its time base (#97)"
git push
```

---

## After Task 6 (coordinator)

1. **Final review** of the whole branch (opus).
2. **Deploy** to a new QGIS profile `ns_geo_time_zero`: `cp -a` from `ns_geo`, plus a `dev_link`
   to this worktree. Confirm that the branch code loads.
3. **Walkthrough** on real data (spec §10, eight checks). Record it on an Artifact page with a
   `results` db. The user runs it. Do not merge until it is done, or until the user waives it.
4. **At the PR:**
   - In the README roadmap, move time zero from In progress to Done ("next release"), and remove
     item 4 of Next.
   - Post a comment on #97 recording the decision and the PR.
   - Note on M15's branch that its plan needs the check described in spec §13.
