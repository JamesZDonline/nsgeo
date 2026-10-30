# nsgeo migration (M14) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse diffraction hyperbolas in a radargram with constant-velocity Stolt f-k migration, as one registered processing step whose velocity the user types.

**Architecture:** A numpy-only solver in the core (`processing/migration.py`) registered as the step `migrate_fk` in a new `"Migration"` group. Velocity is a `REQUIRED` float parameter, prefilled by the plugin from `resolve_velocity`'s existing chain. Trace spacing is the one piece of context, derived in `Radargram.from_profile` from `header.traces_per_metre`, which means the slices engine needs no change and the cube inherits migration from any preset that contains it.

**Tech Stack:** Python 3.9+, numpy only in the core (no scipy, no Qt). PyQt/QGIS in `nsgeo-qgis`. pytest.

**Spec:** `docs/superpowers/specs/2026-10-30-nsgeo-migration-design.md`

## Global Constraints

- **`nsgeo-core` is numpy-only.** No scipy, no Qt, no plugin imports. Enforced by `packages/nsgeo-core/tests/test_boundary.py` and `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py` — 6 tests across the two. Do not weaken them.
- **`nsgeo-qgis` does no signal processing.** Same two test files.
- **`SCHEMA_VERSION` stays 1.** Step parameters are a free-form dict inside a saved stack, so a new step and a new parameter are additive. Nothing in `project.py` changes.
- **Output preserves `data.shape`, `dt_ns` and `t0_ns`.** Picks, map↔profile cursor sync and cube binning all index by trace, and `StepStack.difference()` refuses a step that changes the sample count.
- **`velocity_m_ns` carries no sentinel values.** Not `0` meaning "follow the line", not `-1` meaning "auto". An empty value must stay free to mean "follow the line" in a later milestone. This is the one rule that cannot be relaxed (spec §3.6).
- **Velocity units are m/ns throughout**, matching `VelocityModel` and M13's fit output. Bounds `(0, C_M_PER_NS)` where `C_M_PER_NS = 0.299792458` from `nsgeo.velocity`.
- **Display attributes are never serialised.** `title`, `group` and `order` can be reworded later for free; `name` cannot.
- **Mutation testing runs in a throwaway worktree**, never in the tree the branch is committed from, and always with `PYTHONDONTWRITEBYTECODE=1` — a stale `.pyc` fakes a survivor.
- **Commit message trailer:** `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

**Verification commands — exact, do not improvise:**

```
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:xonsh
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
```

**Baseline to measure before Task 1 and record in the ledger:** core+pure and qgis counts on `main` at `7069959`.

## Review Focus

Five conditions the spec implies that no task's happy path exercises, most likely to bite first. Each has its pinning test named in the task that owns the code.

1. **Migration added to a stack that already contains `time_zero`.** `ProcessingDock.build_add_dialog` probes the candidate step with `stack_for(key).source` — the **raw** radargram, `t0 = −11.09` on every real file — so migration's time-zero refusal fires and OK is disabled even though time zero *is* corrected in the stack. Expected: OK enabled, step addable. Owned by Task 3, step 1.
2. **A line containing a non-finite sample.** One NaN propagates through `fft2` to every pixel, so a single dropped trace silently blanks the whole image. Expected: a refusal naming the problem, not an empty radargram. Owned by Task 1, step 9.
3. **A line shorter than the derived pad.** A 1 m stub is ~60 traces against a 243-trace aperture pad. Expected: it migrates, no wrap, no crash, no division by a zero-width window. Owned by Task 1, step 11.
4. **One preset across lines of differing length and spacing.** The step instance is reused for every line the cube prepares. Expected: each line migrates at its own `dx_m` and trace count, with no state carried between `apply` calls. Owned by Task 2, step 7.
5. **A velocity near the upper bound.** At 0.29 m/ns the evanescent cut removes nearly everything. Expected: an almost-empty output, never a plausible-looking image, and the user can tell the difference. Owned by Task 1, step 13.

---

## File Structure

| File | Responsibility |
|---|---|
| `packages/nsgeo-core/src/nsgeo/processing/migration.py` | **Create.** The Stolt f-k transform, the derived pad, the refusals, the registered `MigrateFk` step. |
| `packages/nsgeo-core/src/nsgeo/processing/base.py` | **Modify.** `Radargram.dx_m`, `from_profile` deriving it, `"Migration"` in `STEP_GROUPS`. |
| `packages/nsgeo-core/src/nsgeo/processing/__init__.py` | **Modify.** Import `migration` so the step registers. |
| `packages/nsgeo-core/tests/test_steps_migration.py` | **Create.** Solver, refusals, padding measurement, real-data validation. |
| `packages/nsgeo-core/tests/test_processing_base.py` | **Modify.** `dx_m` on `Radargram` and `from_profile`. |
| `packages/nsgeo-core/tests/test_step_titles.py` | **Modify.** `TITLES` and `test_grouped_steps_is_the_processing_flow`. |
| `packages/nsgeo-qgis/nsgeo_qgis/ui/add_step_dialog.py` | **Modify.** Accept a `params` seed. |
| `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py` | **Modify.** Prefill velocity; probe the stack's result, not its source; the stale-velocity read-out. |
| `packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py` | **Modify.** Prefill, probe and read-out tests. |

---

## Task 1: The solver

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/processing/migration.py`
- Test: `packages/nsgeo-core/tests/test_steps_migration.py`

**Interfaces:**
- Consumes: `Radargram` (`processing/base.py:19`) — this task uses `dx_m` **as if it already exists**; Task 2 adds it. Add it first locally if needed, but it is Task 2's deliverable and Task 2 owns its tests. `C_M_PER_NS` from `nsgeo.velocity`.
- Produces: `migrate_fk(data, dt_ns, dx_m, velocity_m_ns) -> np.ndarray`, a module-level function, and class `MigrateFk` with `name = "migrate_fk"`, `title = "Migration (Stolt f-k)"`, `group = "Migration"`, `order = 1`, one parameter `velocity_m_ns`. Module constant `MAX_T0_NS = 2.0`.
- Imports `C_M_PER_NS` from `nsgeo.velocity` — the first import out of `nsgeo.processing.*` into another core module by any step. No runtime cycle (spec §5.1); note it in the module docstring.

- [ ] **Step 1: Write the failing synthetic point-diffractor test**

In `test_steps_migration.py`. Build a zero field, insert the hyperbola a single point scatterer at `(x0, t0_apex)` would produce at a known velocity, then migrate at that velocity and assert the energy lands on the scatterer.

```python
def test_a_point_diffractor_collapses_to_its_apex():
    v, dt_ns, dx_m = 0.0733, 0.2165, 1 / 60.0
    n_samples, n_traces = 512, 640
    apex_trace, apex_t_ns = 320, 40.0
    data = _diffraction(n_samples, n_traces, dt_ns, dx_m, v, apex_trace, apex_t_ns)

    out = migrate_fk(data, dt_ns=dt_ns, dx_m=dx_m, velocity_m_ns=v)

    peak = np.unravel_index(np.argmax(np.abs(out)), out.shape)
    assert abs(peak[1] - apex_trace) <= 2
    assert abs(peak[0] - round(apex_t_ns / dt_ns)) <= 2
    # The collapse, not merely a narrowing: most of the energy inside a
    # small box around the apex.
    box = np.abs(out[peak[0] - 8 : peak[0] + 9, peak[1] - 8 : peak[1] + 9]).sum()
    assert box / np.abs(out).sum() > 0.5
```

Write `_diffraction` as a test helper in the same file: for each trace at offset `x` from the apex, place a unit sample at `t = sqrt(apex_t_ns**2 + (2 * x / v) ** 2)`, nearest sample, nothing else. The 0.5 fraction is a literal chosen to sit above what blurring achieves and below a true collapse; do not derive it from anything the solver computes.

- [ ] **Step 2: Run it to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_steps_migration.py -q`
Expected: FAIL, `ImportError` / no module named `migration`.

- [ ] **Step 3: Implement `migrate_fk(data, *, dt_ns, dx_m, velocity_m_ns) -> np.ndarray`**

In `packages/nsgeo-core/src/nsgeo/processing/migration.py`. The algorithm is spec §5.1 and is not determined by the signature, so it is given here:

```
vm = velocity_m_ns / 2
pad each side by ceil(vm * t_max / dx_m) traces (t_max = n_samples * dt_ns),
  then round the total width up to the next power of two
F = np.fft.fft2(padded)                          # axes (omega, kx)
w  = 2*pi * np.fft.fftfreq(n_samples, d=dt_ns)
kx = 2*pi * np.fft.fftfreq(n_padded,  d=dx_m)
sort w ascending and F with it, so np.searchsorted is valid
kz = w_sorted / vm
wmap = vm * sqrt(kx[None, :]**2 + kz[:, None]**2)
interpolate F linearly in w at wmap, per kx, real and imaginary separately
scale by vm * kz[:, None] / sqrt(kx[None, :]**2 + kz[:, None]**2), 0 where the root is 0
zero where abs(wmap) < vm * abs(kx)               # evanescent
out = real(ifft2(...)), cropped back to the original trace count
```

Vectorise the interpolation with `searchsorted` + linear weights rather than looping `np.interp` per column: the loop measured 102 ms against 74 ms vectorised on a 512 × 640 line.

- [ ] **Step 4: Run it to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests/test_steps_migration.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/nsgeo-core/src/nsgeo/processing/migration.py packages/nsgeo-core/tests/test_steps_migration.py
git commit -m "feat(core): Stolt f-k migration collapses a point diffractor"
```

- [ ] **Step 6: Write the wrong-velocity tests, run, implement nothing, commit**

Two tests, because a test that only checks the correct velocity cannot tell migration from blurring:

```python
def test_too_slow_a_velocity_leaves_a_downward_residual(): ...
def test_too_fast_a_velocity_produces_an_upward_smile(): ...
```

Each migrates the same synthetic diffractor at 0.6× and 1.6× the truth and asserts the box fraction from step 1 is **below 0.5**, and that the residual's curvature sign differs between them (compare the trace-width of the energy above and below the apex row). These should pass against a correct solver; if either fails, the solver is wrong, not the test.

- [ ] **Step 7: Write the refusal tests**

One test each, asserting the message names the fix. Use `pytest.raises(ValueError, match=...)` with a literal fragment.

```python
def test_refuses_when_there_is_no_trace_spacing():      # dx_m None and dx_m 0.0
def test_refuses_a_velocity_of_zero():                  # the schema's min=0.0 is inclusive
def test_refuses_an_uncorrected_time_zero():            # t0_ns = -11.086, the real value
def test_refuses_non_finite_samples():                  # one np.nan in one trace
```

And the three that must **pass**, which are the whole point of the tolerance (spec §5.4) and go in
the same commit as the refusals, never after. The values are what the shipped `time_zero` actually
leaves on the real lines, measured at its three threshold settings:

```python
@pytest.mark.parametrize("t0_ns", [-0.6929, -0.4764, +0.8228])
def test_accepts_what_time_zero_actually_leaves(t0_ns):
    # threshold 0.15 / 0.20 (default) / 0.40 on every local file.
    # All three MUST migrate. An earlier draft refused two of them.
```

The boundary is `MAX_T0_NS = 2.0`, in **time, not depth**: the refusal must not move with the
velocity the user typed. Add one test either side of it at a velocity far from the local one
(0.0250 and 0.2500 m/ns at `t0_ns = 1.9` and `2.1`) to pin that independence — a tolerance derived
from velocity would pass one and fail the other.

- [ ] **Step 8: Run them to verify they fail**

Expected: FAIL — no refusals implemented.

- [ ] **Step 9: Implement the refusals and the step class**

In `migration.py`. Refuse, as `ValueError`:
- `dx_m` is `None` or `<= 0` → name the cause (collected on a timer, not a survey wheel) and that migration needs a spatial axis.
- `not velocity_m_ns > 0` → see below.
- `abs(t0_ns) > MAX_T0_NS` → name `time_zero` as the fix, and state the implied depth error (`velocity_m_ns / 2 * abs(t0_ns)`) so a user who needs better precision can see what it costs.
- `not np.all(np.isfinite(data))` → say how many traces are affected.

**The schema does not catch a zero velocity, despite looking like it does.** `_out_of_bounds` (`base.py:246`) tests `value < spec.min`, so `ParamSpec(min=0.0, ...)` *accepts* exactly `0.0`; the float editor is a `QLineEdit` and a hand-edited project or preset can carry it too. `vm = 0` makes the ω→kz map identically zero and the obliquity factor `0/0` — a NaN image with no complaint — and it turns `0` into the de-facto sentinel the Global Constraints forbid. The step-level `> 0` guard is required. Do **not** "fix" this by giving `ParamSpec` exclusive bounds: that touches the central validator every step and every saved file passes through, for one step's benefit.

`MigrateFk.apply(rg)` reads `rg.dx_m`, `rg.dt_ns`, `rg.t0_ns`, calls `migrate_fk`, and returns `rg.replace(data=...)` — never a new `Radargram`, so `dx_m` and every other field survive.

**No minimum-trace refusal.** `AddStepDialog._validate` probes with `data[:, :1]`; a step that refused one trace would be permanently un-addable with a disabled OK button and no explanation. Skip padding entirely when `n_traces == 1` so the probe stays cheap.

- [ ] **Step 10: Run to verify they pass, then commit**

```bash
git commit -m "feat(core): migration refuses rather than guessing, four ways"
```

- [ ] **Step 11: Write the padding measurement and the short-line test**

The padding test must **measure**, not assert that padding happened:

```python
def test_padding_removes_the_wrap_at_the_far_end():
    # A diffractor 1 m from the left end. Migrate with the derived pad and
    # with pad=0, and compare the energy in the rightmost 10% of traces.
    ...
    assert unpadded_far_end_energy > 10 * padded_far_end_energy
```

Expose the pad width as a keyword-only `_pad_traces: int | None = None` on `migrate_fk` for the test to force zero — underscore-prefixed because it is not a user parameter and must never reach `schema()`.

```python
def test_a_line_shorter_than_the_pad_still_migrates():   # 60 traces, 243-trace aperture
```

- [ ] **Step 12: Run, implement any fix, commit**

- [ ] **Step 13: Write the near-light-speed test and the shape-invariance test**

```python
def test_a_velocity_near_c_empties_the_image_rather_than_inventing_one():
    # 0.29 m/ns on the same diffractor: the evanescent cut takes nearly
    # everything. Assert the output's total energy is under 1% of the input's
    # -- visibly empty, not a plausible image.

def test_output_preserves_shape_dt_and_t0():
    # On a real local line, not a square array.
```

- [ ] **Step 14: Run, commit**

```bash
git commit -m "test(core): migration's edges — padding, short lines, near-c, shape"
```

---

## Task 2: Trace spacing, the group, and registration

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/processing/base.py` (`Radargram`, `from_profile`, `STEP_GROUPS`)
- Modify: `packages/nsgeo-core/src/nsgeo/processing/__init__.py`
- Modify: `packages/nsgeo-core/tests/test_processing_base.py`, `packages/nsgeo-core/tests/test_step_titles.py`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py`

**Interfaces:**
- Consumes: `MigrateFk` from Task 1.
- Produces: `Radargram.dx_m: float | None = None`, populated by `from_profile`. `STEP_GROUPS` gains `"Migration"` between `"Background"` and `"Gain"`.

- [ ] **Step 1: Write the failing `dx_m` tests**

In `test_processing_base.py`:

```python
def test_from_profile_derives_dx_from_traces_per_metre():
    # synthetic.write_dzt default traces_per_metre=60.0 -> dx_m == 1/60
def test_from_profile_leaves_dx_none_for_a_time_triggered_file():
    # traces_per_metre=0.0 -> dx_m is None
def test_dx_m_defaults_to_none_so_existing_constructions_are_untouched():
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Add `dx_m` to `Radargram` and derive it in `from_profile`**

`dx_m: float | None = None`, last field, defaulted. In `from_profile`, `1 / tpm` when `profile.header.traces_per_metre > 0`, else `None`. Amend the `from_profile` docstring: it still keeps processing independent of the data model — `traces_per_metre` is a header field — but it should say what it now reads.

- [ ] **Step 4: Run to verify they pass**

- [ ] **Step 5: Add the `"Migration"` group and register the step**

`STEP_GROUPS = ("Time", "Filters", "Background", "Migration", "Gain", "Amplitude")`. Add `migration` to the import tuple in `processing/__init__.py`.

Update the two tests that pin the registry, which will now be failing:
- `test_step_titles.py::TITLES` gains `"migrate_fk": "Migration (Stolt f-k)"`.
- `test_grouped_steps_is_the_processing_flow` gains `("Migration", ["migrate_fk"])` between Background and Gain.

- [ ] **Step 6: Run the full core tier**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q`
Expected: PASS, with the count up by this task's and Task 1's new tests.

- [ ] **Step 7: Write the test that proves the cube gets migration for free**

In `test_plugin_slices_engine.py`. Prepare two lines of **different trace counts** through the engine's own path with `migrate_fk` in the preset, and assert both `PreparedLine`s come back migrated and shaped like their inputs. This is Review Focus 4: one step instance, two different lines, no state carried.

- [ ] **Step 8: Run the qgis tier, then commit**

Run: `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:xonsh`

```bash
git commit -m "feat(core): trace spacing reaches a step, and migration joins the registry"
```

---

## Task 3: The plugin, and the real ground

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/add_step_dialog.py:28-53`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py:541-547`
- Modify: `packages/nsgeo-qgis/tests/qgis/test_plugin_processing_dock.py`
- Modify: `packages/nsgeo-core/tests/test_steps_migration.py` (the real-data test)

**Interfaces:**
- Consumes: `MigrateFk` and `Radargram.dx_m` from Tasks 1–2; `SiteSession.resolved_velocity(key) -> VelocityModel` (`session.py:660`); `VelocityModel.surface_velocity` (`velocity.py:68`).
- Produces: `AddStepDialog(step_name, header=None, radargram=None, params=None, parent=None)`.

- [ ] **Step 1: Write the failing test for Review Focus 1 — the probe**

The blocker. `build_add_dialog` passes `stack_for(key).source`, the raw radargram with `t0 = −11.09`, so migration's time-zero refusal fires and OK is disabled even when `time_zero` is already in the stack.

```python
def test_migration_is_addable_to_a_stack_that_already_corrects_time_zero():
    # open a real local line, append time_zero, then build the add dialog
    # for migrate_fk with a sane velocity typed.
    assert dialog.ok_button.isEnabled()
    assert dialog.form.message.text() == ""
```

- [ ] **Step 2: Run to verify it fails**

Expected: FAIL — OK disabled, message naming time zero.

- [ ] **Step 3: Probe the stack's result, not its source**

In `ProcessingDock.build_add_dialog`, pass the radargram the new step will actually receive: `stack.result()` when the stack evaluates cleanly, falling back to `stack.source` when it raises `ValueError`, logged.

This is not a new judgement call, and should not be re-litigated during review. `ProcessingDock.time_axis` (`processing_dock.py:516`) already defines the quantity as "the input a step appended right now would actually receive: the stack's own `result()` ... exactly as the new step's own `apply()` will see it", and its docstring already specifies this exact fallback, for this exact reason (another step in the stack being misconfigured), and already logs it. `input_axis` (`:494`) does the same one step earlier. The probe is the one place that reaches for `source`, with no comment anywhere defending it.

Changing it affects every step's validation, not only migration — which is why it is its own step with its own test rather than a rider on the prefill.

- [ ] **Step 4: Run to verify it passes**

- [ ] **Step 5: Write the failing prefill test**

```python
def test_the_velocity_is_prefilled_from_the_line():
    # line with no override, grid with none: header epsr 14 -> 0.0801 m/ns
    # then set a line override of 0.0733 and assert the dialog now shows it
```

- [ ] **Step 6: Run to verify it fails, then implement**

`AddStepDialog.__init__` gains `params: dict[str, Any] | None = None` and passes it to `self.form.set_step(step_name, params)` — `ParamForm.set_step` already accepts the seed (`param_form.py:215`) and the dialog simply never passed one.

`ProcessingDock.build_add_dialog` passes `{"velocity_m_ns": self.session.resolved_velocity(key).surface_velocity}` when `name == "migrate_fk"`. Prefill only: the value then belongs to the step and a later velocity change does not reach back into it.

- [ ] **Step 7: Run to verify it passes, then commit**

```bash
git commit -m "feat(plugin): migration's velocity is prefilled from the line (#TBD)"
```

- [ ] **Step 8: Write the failing stale-velocity read-out test**

```python
def test_the_step_row_says_when_its_velocity_is_not_this_lines():
    # step holds 0.0733, open line resolves to 0.0801
    assert "this line says 0.0801" in dock.list.item(row).text()
def test_the_step_row_says_nothing_when_they_agree():
```

- [ ] **Step 9: Implement the read-out**

Where the Processing dock builds each row's text. Show the step's velocity and, when the open line's resolved velocity differs by more than `_VELOCITY_MISMATCH_FRACTION = 0.02`, append ` · this line says <v>`. No refusal, no auto-correction, no dialog.

The threshold is a named module constant with its reasoning beside it. **It must not be derived from either velocity being compared** — M13 shipped four tests that read as correct while pinning nothing, each because a probe value was computed from the constant it checked. The test's two velocities are literals chosen to straddle it.

- [ ] **Step 10: Run both tiers, then commit**

- [ ] **Step 11: Write the real-data test**

**This step is BLOCKED until the coordinates arrive — it is a human gate, not a code task.**

M13's ledger says "a real diffraction fitted, the velocity judged physically sane, coordinates recorded." Its own task-5 report still lists identifying that diffraction as outstanding, and neither the repository nor the session transcript holds a file, a trace or a time. **The claim was false.** The two measured velocities, 0.0701 and 0.0733, survive only as bare numbers.

What is needed before this can be written: which `FILE__0NN.DZT`, roughly which trace and two-way time, and which velocity belongs to it.

Then, in `test_steps_migration.py`: `time_zero`, then `migrate_fk` at that velocity, asserting the same box-fraction measure as Task 1 step 1 around that apex — peak trace, peak time, windowed energy over a literal fraction. **Prose about "collapsing" is not an assertion.** Record the file, trace and time in the test's docstring so the next person can reproduce it.

The real DZTs are git-ignored, so this test is local-only and skipped on CI. Nothing downstream will notice if it is quietly never written — which is exactly how M13's gap survived. Mark it `@pytest.mark.skipif` on the data's absence, and report it as outstanding in the ledger until it exists.

- [ ] **Step 12: Run, commit**

- [ ] **Step 13: Mutation pass**

In a throwaway worktree, never the committed tree, with `PYTHONDONTWRITEBYTECODE=1`. Mutate at minimum: the sign of the ω→kz map; the obliquity factor (drop it, and invert it); the evanescent cut (remove it); `vm = v / 2` → `v`; the pad width → 0; `MAX_T0_NS` → 20.0 (must let the uncorrected −11.09 through) and → 0.3 (must refuse what `time_zero` leaves); the zero-velocity guard (remove it). Every one must be killed. Report survivors honestly — M13's final review found `rms` computed in t² passing all 57 tests while reporting a number 89× wrong.

- [ ] **Step 14: Full verification and the manual gates**

All four commands from Global Constraints, clean. Then the three manual checkpoints in spec §10 — **human gates, tracked and reported, never silently passed**: the collapse on real ground, the deliberate artefact hunt with the step toggled off and on, and the migrated-versus-unmigrated slice comparison.

---

## Self-review notes

- **Spec coverage.** §5.1 → T1 s3; §5.2 → T1 s9, T2 s1–4; §5.3 → T1 s11; §5.4 → T1 s7–9; §6 → T2 s5; §7.1 → T3 s1–4; §7.2 → T3 s5–7; §7.3 → T3 s8–9; §8 → T2 s7; §9 → distributed, with the mutation pass at T3 s13; §10 → T3 s14; §11 is out of scope by construction.
- **Performance to record, not to discover:** migration adds about **4.7 s** across 24 lines to a cube build. The derived pad always lands on a 2048-wide transform for these line lengths — 194 ms each, not the 74 ms a 1024 transform costs. Do not report it as a regression.
- **Three corrections a builder check caught in the first draft of the spec**, all now folded in: the time-zero tolerance was expressed in depth at 0.02 m, which refused two of `time_zero`'s three threshold settings outright; `ParamSpec(min=0.0)` was said to reject a zero velocity and does not; and the cube cost was quoted from the wrong row of the measurement table.
- **Blocked:** Task 3 step 11. M13's ledger claims the diffraction's coordinates were recorded; they were not, anywhere. The recovered M13 record is at `.worktrees/_retired-ledgers/nsgeo-m13/` if anyone wants to check that claim again.
