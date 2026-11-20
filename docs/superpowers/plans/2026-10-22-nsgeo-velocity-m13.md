# nsgeo velocity fitting (M13) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure radar velocity by fitting a diffraction hyperbola clicked on the profile, store the fit with its uncertainty, and close the line-velocity stub.

**Architecture:** A numpy-only solver in the core (`nsgeo/velocity_fit.py`) that takes metres and nanoseconds and knows nothing about Qt; a new profile-view mode that only paints and emits, mirroring pick mode; a dock that owns the working point list, does every unit conversion, and calls the solver; and a dialog that selects among stored fits. The core never learns about traces, and the view never learns about metres.

**Tech Stack:** Python 3, numpy (core — nothing else, ever), PyQt5/QGIS 3.44 (plugin), pytest in two tiers.

**Spec:** `docs/superpowers/specs/2026-09-20-nsgeo-velocity-fit-design.md`

---

## Measured against main, 2026-10-22

The spec was measured on 2026-09-20. M8, M11, M12, #7, #31 and #59 have landed since. **Every line number in spec §2 has moved.** Re-measured against `87fcaa3`:

| Spec said | Actually, on main |
|---|---|
| `plugin.py:834` stub | `plugin.py:1278` — still the same two-line stub, wired from `plugin.py:220` |
| `session.py:461/526/535` | `session.py:518` `set_grid_velocity`, `:615` `set_line_velocity`, `:624` `resolved_velocity` |
| `profile_view.py:434` pick gate | `profile_view.py:650`, inside a new `_handle_mouse_press` (`:634`) |
| `profile_dock.py:67/740` | `velocity_source` `:89`, `fit_button` `:207`, `velocity_label` `:215`, `set_pick_mode` `:632` |
| colours | unchanged: `CURSOR_COLOUR:56`, `SELECTION_EDGE:58`, `PICK_COLOUR:59` |

Five amendments that change the work:

1. **#59 added a third claimant on the left button.** `_handle_mouse_press` now runs: middle → pan; `_pick_mode or shift` → bounds-check then emit pick; near the time-cutoff line → grab it; otherwise → selection drag. Velocity fit mode joins that chain, and the spec's "left-drag selection and middle-drag pan are untouched" now has to include the cutoff handle too.
2. **Mode exclusivity is now a real problem.** M8 shipped `act_pick` as a *checkable* toolbar action (`plugin.py:204-205`). A second checkable action means two modes can be on at once, both claiming the left click. Turning one on must turn the other off.
3. **`test_public_api.py` is new** and asserts the core's public surface is exactly `EXPECTED_PUBLIC`. Any module one level under `nsgeo/` that declares `__all__` must be listed there, or that test fails.
4. **M8's pattern is now concrete, not predicted.** `self._toolbar_action("Pick", self._toggle_pick_mode)` + `setCheckable(True)`; `_update_enabled` (`:488`) disables and unchecks it when there is no current line; `_toggle_pick_mode` (`:846`) drives `ProfileDock.set_pick_mode`, never the view. Copy all four.
5. **The spec's one `HyperbolaFit` is really two records.** §5.1's solver result is in metres (`apex_x_m`, `n_points`); §6.1's stored record is in trace indices (`apex_trace`, `points`). They are named `HyperbolaFit` and `StoredFit` here.

---

## Global Constraints

- **`nsgeo-core` imports numpy and nothing else.** No scipy, no Qt, no PyQt, no QGIS. Enforced by `packages/nsgeo-core/tests/test_boundary.py`.
- **The plugin contains no signal processing.** Enforced by `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py`.
- **There are TWO boundary test files, 6 tests total.** Never report one file's count as the total.
- **Every new signal needs a `connect`.** `tests/pure/test_no_orphan_signals.py` fails otherwise. Grep the `connect`, never the `emit`.
- **A new public core module must join `EXPECTED_PUBLIC`** in `tests/test_public_api.py`.
- **`SCHEMA_VERSION` stays at 1.** New keys are additive and optional.
- **Units:** velocity m/ns, time ns, distance m. `C_M_PER_NS = 0.299792458` already exists in `velocity.py`.
- **Every Qt slot guards its own body.** An exception escaping a slot is swallowed locally and `qFatal()`s in CI.

**Verification commands — run these, do not improvise them:**

```bash
# core + pure
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
# qgis tier
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:xonsh
# lint and types
ruff check . && ruff format --check .
mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
```

Report the two test tiers separately, never summed. In a fresh worktree both venvs must be built by hand first, or `pytest` silently tests the main checkout's code.

---

## Review Focus

Five conditions the spec implies that no task's happy path exercises. Each has a test assigned below.

1. **Both toolbar modes checked at once.** Pick and Velocity are both checkable and both claim the left click. Checking one must uncheck the other. → Task 3.
2. **A fit click outside the radargram.** `time_of_y` does not clamp, so a click on the depth-axis margin yields a negative time. Pick mode already bounds-checks for exactly this reason; the fit click must too, or the point is silently rejected by the solver several clicks later. → Task 3.
3. **The working line changes mid-fit.** Half-placed points belonging to line A must never be fitted or applied to line B. → Task 3.
4. **A line with no `traces_per_metre`** (time-mode collection). `GridPlacement.distance_along` raises; the dock converts clicks to metres through it. The strip must explain, not let an exception escape a slot. → Task 4.
5. **`velocity_from_fit` naming a fit that is not in `velocity_fits`.** A hand-edited or partly-deleted file must load and read as "no fit selected", not raise on open. → Task 2.

---

## File Structure

| File | Responsibility |
|---|---|
| `packages/nsgeo-core/src/nsgeo/velocity_fit.py` | **Create.** The solver and both records. Pure numpy; metres and nanoseconds only. |
| `packages/nsgeo-core/src/nsgeo/model/survey.py` | **Modify.** `Line` gains `velocity_fits` and `velocity_from_fit`. |
| `packages/nsgeo-core/src/nsgeo/project.py` | **Modify.** Serialise both keys. |
| `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py` | **Modify.** The mode, two signals, one painter. Paints what it is given; no units, no solver. |
| `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` | **Modify.** Owns the working points, converts traces↔metres, calls the solver, owns the result strip. |
| `packages/nsgeo-qgis/nsgeo_qgis/ui/velocity_dialog.py` | **Create.** The line-velocity dialog: spin box, fit list, clear. |
| `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` | **Modify.** The Velocity toolbar toggle, mode exclusivity, and the stub at `:1278`. |

---

### Task 1: The core fit

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/velocity_fit.py`
- Create: `packages/nsgeo-core/tests/test_velocity_fit.py`
- Modify: `packages/nsgeo-core/tests/test_public_api.py` (add `"velocity_fit"` to `EXPECTED_PUBLIC`)

**Interfaces:**
- Consumes: nothing.
- Produces:
  ```python
  @dataclass(frozen=True)
  class HyperbolaFit:
      apex_x_m: float
      t0_ns: float
      v_m_ns: float
      v_stderr_m_ns: float
      rms_ns: float
      n_points: int

  def fit_hyperbola(
      x_m: np.ndarray, t_ns: np.ndarray, apex_guess_m: float, *, search_m: float = 0.25
  ) -> HyperbolaFit
  ```
  Raises `ValueError` for every refusal. `__all__ = ["HyperbolaFit", "fit_hyperbola"]`.

- [ ] **Step 1: Write the failing exactness test**

```python
def test_points_on_an_analytic_hyperbola_recover_its_parameters():
    v, t0, x0 = 0.1, 20.0, 5.0
    x = np.array([2.0, 3.5, 5.0, 6.5, 8.0])
    t = np.sqrt(t0**2 + (4.0 / v**2) * (x - x0) ** 2)
    fit = fit_hyperbola(x, t, apex_guess_m=x0, search_m=0.0)
    assert fit.v_m_ns == pytest.approx(v, rel=1e-9)
    assert fit.t0_ns == pytest.approx(t0, rel=1e-9)
    assert fit.rms_ns == pytest.approx(0.0, abs=1e-9)
    assert fit.n_points == 5
```

- [ ] **Step 2: Run it and watch it fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_velocity_fit.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'nsgeo.velocity_fit'`

- [ ] **Step 3: Implement `fit_hyperbola` in `packages/nsgeo-core/src/nsgeo/velocity_fit.py`**

The solve, which the signature does not determine:

```
dx2   = (x_m - apex)**2
A     = column_stack([ones_like(dx2), dx2]);  y = t_ns**2
b     = lstsq(A, y)           ->  intercept = t0**2,  slope = 4/v**2
t0    = sqrt(intercept);      v = 2 / sqrt(slope)
s2    = sum((y - A@b)**2) / (n - 2)          # residual variance, in y-space
cov   = s2 * inv(A.T @ A);    sigma_slope = sqrt(cov[1, 1])
sigma_v = sigma_slope / slope**1.5           # chain rule through v = 2/sqrt(slope)
rms   = sqrt(mean((t_ns - sqrt(t0**2 + slope*dx2))**2))   # in TIME, not t^2
```

With `search_m > 0`, run the solve at each of `np.linspace(apex_guess_m - search_m, apex_guess_m + search_m, 101)` and keep the lowest `rms`; with `search_m == 0`, solve once at the guess.

- [ ] **Step 4: Run it and watch it pass**

- [ ] **Step 5: Write the apex-recovery test, run, implement if needed, run**

```python
def test_a_wrong_apex_guess_is_recovered_by_the_search():
    v, t0, x0 = 0.1, 20.0, 5.0
    x = np.array([2.0, 3.5, 5.0, 6.5, 8.0])
    t = np.sqrt(t0**2 + (4.0 / v**2) * (x - x0) ** 2)
    fit = fit_hyperbola(x, t, apex_guess_m=5.4, search_m=0.5)
    assert fit.apex_x_m == pytest.approx(5.0, abs=0.011)   # grid step is 0.01 m
    assert fit.v_m_ns == pytest.approx(v, rel=1e-3)
```

- [ ] **Step 6: Write the noise test**

```python
def test_the_reported_sigma_brackets_the_error_under_noise():
    v, t0, x0 = 0.1, 20.0, 5.0
    x = np.linspace(2.0, 8.0, 9)
    t = np.sqrt(t0**2 + (4.0 / v**2) * (x - x0) ** 2)
    t = t + np.random.default_rng(0).normal(0.0, 0.2, size=t.size)
    fit = fit_hyperbola(x, t, apex_guess_m=x0, search_m=0.0)
    assert abs(fit.v_m_ns - v) <= 3.0 * fit.v_stderr_m_ns
```

- [ ] **Step 7: Write the clustered-points test — the one that earns `v_stderr_m_ns`**

```python
def test_points_clustered_near_the_apex_report_a_large_sigma_while_the_residual_stays_quiet():
    v, t0, x0 = 0.1, 20.0, 5.0
    def noisy(x):
        t = np.sqrt(t0**2 + (4.0 / v**2) * (x - x0) ** 2)
        return t + np.random.default_rng(1).normal(0.0, 0.2, size=t.size)
    spread_x = np.array([2.0, 3.5, 5.0, 6.5, 8.0])
    tight_x = np.array([4.7, 4.85, 5.0, 5.15, 5.3])
    spread = fit_hyperbola(spread_x, noisy(spread_x), apex_guess_m=x0, search_m=0.0)
    tight = fit_hyperbola(tight_x, noisy(tight_x), apex_guess_m=x0, search_m=0.0)
    assert tight.v_stderr_m_ns > 5.0 * spread.v_stderr_m_ns   # sigma warns
    assert tight.rms_ns < 2.0 * spread.rms_ns                 # the residual does not
```

- [ ] **Step 8: Write one test per refusal**

`pytest.raises(ValueError, match=...)` for each, with these names and triggers:
`test_two_points_are_refused` (2 points) · `test_a_non_positive_time_is_refused` (a `0.0` in `t_ns`) · `test_a_non_finite_time_is_refused` (`np.nan`) · `test_an_upward_opening_set_is_refused` (times that *decrease* away from the apex, giving slope ≤ 0) · `test_a_superluminal_fit_is_refused` (points whose solve gives `v > C_M_PER_NS`) · `test_all_points_at_one_offset_are_refused` (every x equal — singular design matrix).

- [ ] **Step 9: Implement the refusals, run the whole file**

Each message names the condition in the project's voice; the superluminal one cites `C_M_PER_NS`.

- [ ] **Step 10: Add `"velocity_fit"` to `EXPECTED_PUBLIC` and run the public-API test**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_public_api.py -q`

- [ ] **Step 11: Full core + pure tier, ruff, mypy, then commit**

```bash
git add packages/nsgeo-core/src/nsgeo/velocity_fit.py packages/nsgeo-core/tests/test_velocity_fit.py packages/nsgeo-core/tests/test_public_api.py
git commit -m "feat(velocity): fit a diffraction hyperbola, with its standard error"
```

---

### Task 2: Persistence

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/velocity_fit.py` (add `StoredFit`)
- Modify: `packages/nsgeo-core/src/nsgeo/model/survey.py` (`Line` gains two fields)
- Modify: `packages/nsgeo-core/src/nsgeo/project.py` (write near `:183`, read near `:241`)
- Modify: `packages/nsgeo-core/tests/test_project.py`

**Interfaces:**
- Consumes: Task 1's module.
- Produces:
  ```python
  @dataclass(frozen=True)
  class StoredFit:
      t0_ns: float
      v_m_ns: float
      v_stderr_m_ns: float
      rms_ns: float
      apex_trace: int
      points: tuple[tuple[int, float], ...]   # (trace index, two-way time ns)
      fitted_at: str                           # ISO-8601 UTC
      def to_dict(self) -> dict[str, Any]: ...
      @classmethod
      def from_dict(cls, doc: dict[str, Any]) -> StoredFit: ...
  ```
  `Line.velocity_fits: Mapping[str, StoredFit] = field(default_factory=dict)` and
  `Line.velocity_from_fit: str | None = None`. Both default, so every existing `Line.open` call is unchanged. Add `"StoredFit"` to `__all__`.

  `Line` is a **frozen** dataclass. Adding or selecting a fit replaces the line via
  `dataclasses.replace`, exactly as `session.set_line_velocity` (`:615`) already does — never by
  mutating the mapping in place, which would skip the session's dirty flag and its
  `lines_changed` emit.

- [ ] **Step 1: Write the round-trip test**

```python
def test_velocity_fits_survive_a_save_and_load(tmp_path):
    fit = StoredFit(t0_ns=18.4, v_m_ns=0.0984, v_stderr_m_ns=0.0041, rms_ns=0.31,
                    apex_trace=412, points=((389, 21.2), (412, 18.6), (437, 21.9)),
                    fitted_at="2026-10-22T14:02:11Z")
    # save a site whose single line has velocity_fits={"f1": fit}, velocity_from_fit="f1"
    loaded = load_site(path).lines[0]
    assert loaded.velocity_fits == {"f1": fit}      # whole-record equality, not field by field
    assert loaded.velocity_from_fit == "f1"
    assert loaded.velocity_fits["f1"].points == ((389, 21.2), (412, 18.6), (437, 21.9))
```

- [ ] **Step 2: Write the two compatibility tests**

`test_a_line_entry_without_fits_loads` (no keys present → empty mapping, `None` pointer) and
`test_a_file_with_fits_still_declares_schema_version_1` (the written JSON's `schema_version` is `1`).

- [ ] **Step 3: Write the Review Focus #5 test**

```python
def test_a_velocity_from_fit_naming_a_missing_fit_loads_as_no_selection(tmp_path):
    # hand-write a survey JSON whose line entry has velocity_from_fit = "gone"
    # and a velocity_fits dict that does not contain it
    site = load_site(path)
    assert site.lines[0].velocity_from_fit is None
```
A dangling pointer is dropped on load rather than raising: the fits are evidence, and losing a selection must not cost the user the file.

- [ ] **Step 4: Run all four and watch them fail**

- [ ] **Step 5: Implement `StoredFit`, the two `Line` fields, and the `project.py` read/write**

Write beside the existing `entry["velocity"]` (`project.py:183`); read beside the existing velocity parse (`:241`), wrapping a malformed fit in `ProjectError` the way the velocity parse already does.

- [ ] **Step 6: Run the tests, then the full core + pure tier, ruff, mypy, commit**

```bash
git commit -m "feat(velocity): persist hyperbola fits and the active selection"
```

---

### Task 3: Fit mode and the point overlay

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (toolbar near `:204`, `_update_enabled` `:488`)
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_velocity_fit.py`

**Interfaces:**
- Consumes: nothing from Tasks 1–2 yet; this task collects and paints points only.
- Produces, on `ProfileView`:
  ```python
  velocity_point_requested = pyqtSignal(int, float)   # trace index, two-way time (ns)
  velocity_point_discarded = pyqtSignal(int)          # index into the last points list
  def set_velocity_fit_mode(self, flag: bool) -> None
  def set_velocity_fit(self, points: list[tuple[int, float]],
                       curve: list[tuple[float, float]]) -> None
  ```
  On `ProfileDock`: `set_velocity_fit_mode(flag: bool)` — a passthrough, like `set_pick_mode` at `:632`.
  On `NsgeoPlugin`: `act_velocity`, `_toggle_velocity_fit_mode(checked: bool)`.

  The view is a painter: it receives points and a curve in **view units** (trace index, ns) and never converts, never fits. `curve` is empty in this task.

- [ ] **Step 1: Write the mode-exclusivity test (Review Focus #1)**

```python
def test_turning_on_velocity_mode_turns_off_pick_mode(fake_iface, tmp_path):
    # open a site, check act_pick, then check act_velocity
    assert not plugin.act_pick.isChecked()
    assert plugin.profile_dock.view._pick_mode is False
```
And its mirror, `test_turning_on_pick_mode_turns_off_velocity_mode`.

- [ ] **Step 2: Write the out-of-bounds test (Review Focus #2)**

```python
def test_a_velocity_click_on_the_axis_margin_adds_no_point(fake_iface, tmp_path):
    # with velocity mode on, press at a local y above the image rect
    assert plugin.profile_dock.velocity_points() == []
```
Mirrors the bounds guard pick mode already applies in `_handle_mouse_press`.

- [ ] **Step 3: Write the line-change test (Review Focus #3)**

```python
def test_opening_another_line_clears_the_working_points(fake_iface, tmp_path):
    # place two points on line A, open line B
    assert plugin.profile_dock.velocity_points() == []
```

- [ ] **Step 4: Write the collection tests**

`test_a_click_in_velocity_mode_adds_a_point` (first click is the apex), `test_a_right_click_drops_the_nearest_point`, and `test_velocity_mode_leaves_selection_drag_and_the_cutoff_handle_alone` — the last one presses near the time-cutoff line with velocity mode **off** and asserts the cutoff still grabs, so the new branch has not stolen the gesture.

- [ ] **Step 5: Run the new file and watch it fail**

Run: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_velocity_fit.py -q -p no:xonsh`

- [ ] **Step 6: Implement the view's mode, signals and `_paint_velocity_fit`**

Insert the velocity branch in `_handle_mouse_press` **immediately after** the `_pick_mode or shift` branch and before the cutoff test, with the same bounds guard. Right-click finds the nearest painted point in *screen* space and emits its index. `_paint_velocity_fit` sits beside `_paint_picks` (`:511`): points in `SELECTION_EDGE`, curve in `CURSOR_COLOUR`, both already defined.

- [ ] **Step 7: Implement the dock passthrough and the working point list**

The dock owns `_velocity_points: list[tuple[int, float]]` and a `velocity_points()` accessor, appends on `velocity_point_requested`, removes on `velocity_point_discarded`, and clears whenever the open line changes. Every slot guards its own body.

- [ ] **Step 8: Implement the plugin toggle and exclusivity**

`act_velocity = self._toolbar_action("Velocity", self._toggle_velocity_fit_mode)`, `setCheckable(True)`, a tooltip in the same voice as Pick's. `_toggle_velocity_fit_mode` unchecks `act_pick` and calls `_toggle_pick_mode(False)` before enabling itself; `_toggle_pick_mode` does the reverse. Extend `_update_enabled` (`:488`) so `act_velocity` is disabled and unchecked with no current line, exactly as `act_pick` is.

- [ ] **Step 9: Run the new file, then the whole qgis tier, then the orphan-signal test**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py -q`
Both new signals must have a `connect`.

- [ ] **Step 10: Commit**

```bash
git commit -m "feat(velocity): a fit mode on the profile that collects points"
```

---

### Task 4: The fit, the curve and the result strip

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (strip after `viewer_row`, added at `:231`)
- Modify: `packages/nsgeo-qgis/tests/qgis/test_plugin_velocity_fit.py`

**Interfaces:**
- Consumes: `fit_hyperbola`, `HyperbolaFit`, `StoredFit` (Tasks 1–2); `ProfileView.set_velocity_fit` (Task 3); `session.set_line_velocity` (`:615`), `set_grid_velocity` (`:518`), `resolved_velocity` (`:624`).
- Produces, on `ProfileDock`: `velocity_fit_result() -> HyperbolaFit | None`, and the strip's four buttons. Conversion lives here and nowhere else: `line.distance_along()` turns trace indices into metres on the way in, and the curve is sampled back into `(trace, ns)` pairs on the way out.

- [ ] **Step 1: Write the read-out test**

```python
def test_three_points_produce_a_velocity_and_a_sigma_in_the_strip(fake_iface, tmp_path):
    # place an apex and four limb points taken from a synthetic hyperbola
    assert "±" in dock.velocity_readout.text()
    assert dock.velocity_fit_result().v_m_ns == pytest.approx(expected, rel=1e-2)
```

- [ ] **Step 2: Write the time-zero warning test**

With a working radargram whose `t0_ns` is not ≈ 0, the strip warns and names `time_zero`. Assert the step's name appears in the strip's text.

- [ ] **Step 3: Write the time-mode test (Review Focus #4)**

```python
def test_a_line_with_no_traces_per_metre_explains_instead_of_raising(fake_iface, tmp_path):
    # a header with traces_per_metre = 0
    # velocity mode on, one click: the strip explains, no exception escapes
```
Assert the strip's text mentions distance calibration and that `dock.velocity_fit_result() is None`. `GridPlacement.distance_along` raises for this input and the dock must catch it.

- [ ] **Step 4: Write the apply tests**

`test_apply_to_line_sets_the_line_velocity` (asserts through `session.resolved_velocity(key)` and that `velocity_source` now reads `line`), `test_apply_to_grid_sets_the_grid_velocity`, and `test_save_fit_stores_it_without_changing_any_velocity` — the last one is §6.2's rule, and it is the test that would catch a well-meaning implementer wiring Save to also apply.

- [ ] **Step 5: Run them and watch them fail**

- [ ] **Step 6: Build the strip**

A `QHBoxLayout` added to the dock's `layout` after `viewer_row`, hidden unless velocity mode is on: a `velocity_readout` label (`v = 0.0984 ± 0.0041 m/ns · rms 0.31 ns · 5 pts`, `tabular-nums` not available in Qt — use a fixed-width format string) and four buttons: Apply to line, Apply to grid, Save fit, Clear.

- [ ] **Step 7: Wire the fit**

On every point change with ≥ 3 points: convert to metres, call `fit_hyperbola`, sample the curve across the line's trace range (200 samples is plenty), push both to the view, update the read-out. Fewer than 3 points, or a `ValueError` from the solver, puts the solver's own message in the strip and clears the curve — the refusals were written to be read by a person, so show them rather than paraphrase.

- [ ] **Step 8: Wire the four buttons**

Apply to line → `set_line_velocity(key, VelocityModel.constant(fit.v_m_ns))`; Apply to grid → `set_grid_velocity`. Save fit → build a `StoredFit` (converting metres back to trace indices) under a fresh id and set `velocity_from_fit`. Clear empties the working points.

- [ ] **Step 9: Run the file, the whole qgis tier, ruff, commit**

```bash
git commit -m "feat(velocity): fit the clicked points and apply the result"
```

---

### Task 5: The velocity dialog, and the fits you already have

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/velocity_dialog.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py:1278` (the stub)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (draw saved fits faint)
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_velocity_dialog.py`

**Interfaces:**
- Consumes: `StoredFit` (Task 2), the dock's conversion helpers (Task 4), `session.set_line_velocity` / `resolved_velocity`.
- Produces: `VelocityDialog(session, key, parent)` with `selected_fit_id() -> str | None` and `velocity() -> VelocityModel | None` (`None` meaning "clear the override"). Modelled on `grid_dialog`'s spin box: range 0–0.3 m/ns, 4 decimals, step 0.001.

- [ ] **Step 1: Write the dialog tests**

`test_the_dialog_lists_every_saved_fit_for_the_line` (t₀, v ± σ, rms, point count all present in the row text), `test_selecting_a_fit_and_accepting_applies_its_velocity`, `test_clear_override_removes_the_line_velocity` (asserts `line.velocity is None` and `velocity_source` falls back to grid or header), and `test_typing_a_velocity_with_no_fit_selected_still_applies`.

- [ ] **Step 2: Write the disagreement-flag test**

```python
def test_two_fits_disagreeing_beyond_their_combined_sigma_are_flagged(fake_iface, tmp_path):
    # f1: v 0.090 +/- 0.002 at t0 18; f2: v 0.120 +/- 0.002 at t0 41
    # combined sigma = sqrt(0.002**2 + 0.002**2) = 0.00283; the gap is 0.030
```
Assert the flag appears, and its mirror `test_two_fits_agreeing_within_their_combined_sigma_are_not_flagged`. Rows are sorted by t₀.

- [ ] **Step 3: Write the saved-fits overlay test**

With two saved fits on the open line, the view receives two faint curves and the working fit stays distinguishable.

- [ ] **Step 4: Run them and watch them fail**

- [ ] **Step 5: Build the dialog**

A modal `QDialog`: spin box seeded from `resolved_velocity(key)`, a list of fits sorted by t₀ with the disagreement flag, Apply / Clear override / Cancel. Under `QT_QPA_PLATFORM=offscreen` a modal `exec()` blocks indefinitely — follow whatever the existing dialog tests do (`answer_modal` in the qgis conftest).

- [ ] **Step 6: Replace the stub at `plugin.py:1278`**

Open the dialog, apply the result through the session, guard the slot body. The warning message disappears with it.

- [ ] **Step 7: Draw saved fits faint**

`ProfileDock` pushes the line's `velocity_fits` as curves whenever the line opens or the fits change; `_paint_velocity_fit` draws them at reduced alpha beneath the working fit.

- [ ] **Step 8: Run both tiers in full, ruff, mypy, the orphan test, and commit**

```bash
git commit -m "feat(velocity): the line velocity dialog, and the fits already measured"
```

- [ ] **Step 9: Record the manual checkpoints as open**

Spec §10 gates, none of which this plan can close:
1. **Identify a real diffraction** in a local `FILE__00n.DZT` and read off its coordinates, so the real-data test can be written. Until then that test does not exist, and the plan has not delivered §9's real-data tier.
2. **Sanity-check a fitted velocity** against site expectation.
3. **Build and walkthrough** before any merge decision.

Report all three as outstanding; do not mark the milestone complete on a green suite alone.

---

## Not in this plan

The real-data test (spec §9) depends on manual checkpoint 1 and is written after it. Everything in spec §11 stays out, Dix conversion and `VelocityModel.from_fits()` included.
