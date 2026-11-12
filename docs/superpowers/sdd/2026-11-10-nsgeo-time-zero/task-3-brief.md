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

