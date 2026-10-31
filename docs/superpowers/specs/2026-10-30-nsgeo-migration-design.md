# nsgeo migration (Plan 5, M14) — design

Collapse diffraction hyperbolas back to the objects that made them, as one registered processing
step. Second milestone of Plan 5; depends on M13, which supplies the measured velocity that makes
it worth doing.

Supersedes the sizing and two of the decisions in
`docs/superpowers/notes/2026-09-19-migration-research.md`. That note's research — the tool survey,
the algorithm comparison and the sources — still stands and is not repeated here.

---

## 1. What this milestone is for

A buried object does not appear in a radargram where it is. It appears as a hyperbola, because the
antenna sees it from every position that can reach it. The tails of that hyperbola are real
recorded energy sitting in the wrong place, and they are the single largest source of confusion in
a GPR product.

In a profile they make a point look like an arch. In a **slice** they are worse: the hyperbola is
really a hyperboloid, so a horizontal cut through one below its apex is a ring, and a wall crossing
the survey lines appears as two parallel features flanking the real one. An interpreter can read
that as a corridor that was never there.

Migration moves the energy back. It is the step that turns a radargram into an image.

**What makes it possible now.** Migration's output quality is entirely determined by its velocity,
and a wrong velocity is worse than not migrating at all: it over- or under-collapses hyperbolas
into plausible-looking artefacts that no longer announce themselves as artefacts. Until M13 this
product had no measured velocity anywhere. The ten local lines carry `epsr = 14`, which the
manufacturer's default makes `0.0801 m/ns`; the two hyperbolas fitted on real ground during M13's
walkthrough measured `0.0701 ± 0.0018` and `0.0733 ± 0.0024`. **The header is about 10% fast.**
Migrating at it would have been exactly the failure mode above.

---

## 2. Starting state, measured

Read from `main` at `7069959` on 2026-10-30. Every line number is from that commit.

| What | Where | State |
|---|---|---|
| Step protocol | `processing/base.py:127` | `name`, `title`, `group`, `order`, `params`, `schema()`, `apply(rg) -> Radargram`. Pure function, no I/O. |
| `Radargram` | `processing/base.py:19` | `data`, `dt_ns`, `t0_ns`. **No spatial axis of any kind.** |
| `Radargram.from_profile` | `processing/base.py:49` | Reads `profile.header.dt_ns` and `.position_ns`. Takes nothing else. |
| Step groups | `processing/base.py:122` | `("Time", "Filters", "Background", "Gain", "Amplitude")`. A closed list, **validated at registration** (`_display_problem`). Never serialised. |
| Parameter kinds | `processing/base.py:88` | `float`, `int`, `choice`, `curve`, `time`. Validated centrally in `_validate_params`. |
| Optional parameters | — | **Do not exist.** Every parameter is a concrete default or `REQUIRED`. No `default=None` anywhere. |
| Cache invalidation | `processing/stack.py:68` | Editing index *i* invalidates *i* onward. Setting `source` clears everything. |
| Per-step enable | `processing/stack.py:110`, `ui/processing_dock.py:462` | A checkbox per row, already wired. **This is the before/after comparison.** |
| Difference view | `processing/stack.py:181` | `after - before`, refused when the sample count changes. Already in the UI. |
| Velocity resolution | `velocity.py:109` | `resolve_velocity`: line override → grid → `from_dielectric(header.epsr)`. |
| `VelocityModel` | `velocity.py:38` | Layered from day one; `is_constant`, `surface_velocity`. Only ever one layer in practice. |
| Trace spacing | `io/dzt.py:36` | `header.traces_per_metre`. Already what `GridPlacement.distance_along` uses. `<= 0` means time-triggered collection. |
| `from_profile` callers | `session.py:697`, `slices_engine.py:652` | **Two**, not one. The second runs **on a worker thread**. |
| Cube preparation | `slices_engine.py:645-666` | Builds its own `Radargram`, runs the preset, hands `PreparedLine` to the binner. |
| Slices velocity rule | `slices_engine.py:76-85` | **Ruling Q (M12):** a velocity-only edit is deliberately excluded from the rebuild fingerprint, on the stated grounds that "the prepared lines do not depend on velocity at all". |
| Add-step validation | `ui/add_step_dialog.py:66` | Applies the step to `radargram.data[:, :1]` — **a one-trace probe** — on every keystroke. |
| Parameter prefill | `ui/add_step_dialog.py:40` | Calls `form.set_step(name)` with no params. `ParamForm.set_step` already accepts a `params` seed; the dialog just never passes one. |

### The real data, measured

All ten `packages/nsgeo-core/tests/data/local/FILE__0NN.DZT`:

| | |
|---|---|
| Samples × traces | 512 × 606–666 |
| `dt_ns` | 0.2165 |
| `t0_ns` | **−11.09** (every file) |
| Time range | 110.9 ns |
| `traces_per_metre` | 60.000 (every file) → `dx = 0.01667 m` |
| Line length | 10.1 – 11.1 m |
| `epsr` | 14.0 → 0.0801 m/ns |
| `antenna` | `HS350US` (every file) — GSSI HyperStacking, 350 MHz |

Consequences worth having in hand: spatial Nyquist is 30 cycles/m, so **spatial aliasing is not a
risk on this data**; `t0 = −11.09 ns` means the time-zero refusal fires on every raw local line,
which is correct; and the arrays are small enough that the whole transform is cheap.

### Cost, measured

A throwaway probe on a real-sized 512 × 640 line, vectorised, `.venv` numpy:

| Padded width | Per line | 24 lines |
|---|---|---|
| 1024 | 74 ms | 1.8 s |
| 2048 | 194 ms | 4.7 s |

---

## 3. Decisions taken in brainstorming

1. **Judged in the profile viewer, on real lines, by eye.** The slices are why the work matters;
   they are not the test it has to pass. Success is: the hyperbolas collapse, and **nothing new
   appears**. The second half is as binding as the first.

2. **Velocity is a step parameter, prefilled from the line — not acquisition context.**
   This reverses decision 5 of the research note. The user's words: *"velocity will be a tunable
   parameter in the migration tool, which defaults to whatever the line says, but isn't stuck to
   it."* It is common to have readings from a few sources spread across a grid rather than one per
   line, so per-line velocity resolution at apply time buys a case the data mostly does not
   support.

   The consequence was put to the user explicitly and accepted: a preset carries **one** velocity
   to every line it touches, so a grid cannot express "lines 1–3 at one value, 4–6 at another" in
   the cube. Per-line tuning in the profile viewer is unaffected, because each line already owns
   its own `StepStack`.

3. **Trace spacing is context, and only trace spacing.** It comes from `header.traces_per_metre`,
   which the worker thread already holds, so `from_profile` can derive it with no session call and
   no main-thread hop. This is what keeps the slices engine untouched.

4. **Stolt f-k first.** Phase-shift (for v(z)) and Kirchhoff (for topography) become sibling
   registered steps if and when wanted, per the note's decision 3 — distinct algorithms get
   distinct step names, not a `choice` parameter.

5. **No velocity scrubbing in v1.** Every migration tool the user has used is type-a-number-and-
   wait, so a typed parameter meets the expectation. A live drag was measured at 74 ms per line
   before the profile repaint — and that was at a 1024-wide transform; at the pad §5.3 actually
   derives it is **194 ms, about 5 redraws a second**, which is not draggable. A mediocre version
   of a feature nobody else offers is not worth a task. Recorded as known-possible, and it would
   need the pad question reopened to be worth doing.

6. **Extensibility rule, agreed explicitly.** The velocity parameter is a plain positive float with
   **no sentinel values** — not `0` meaning "follow the line", not `-1` meaning "auto". That keeps
   an empty value free to mean "follow the line" later, and keeps every saved stack valid when that
   day comes. This is the one choice that could foreclose the future, and it is the one rule the
   builder must not relax.

---

## 4. Prior art, and where we differ

The research note's survey stands: nothing exists that is both numpy-only and permissively
licensed. GPRPy's `fkMigration()` is a wrapper around a module it does not ship and imports inside
a `try/except` that prints "Install fk migration if needed"; RGPR is the most complete and is GPL
and in R.

Two deliberate differences from GPRPy, the closest analogue:

- **GPRPy resamples the x-axis** and returns a new `profilePos`. We cannot. Picks, map↔profile
  cursor sync and cube binning all index by trace, and `StepStack.difference()` refuses any step
  that changes the sample count. Our output has the same shape, `dt_ns` and `t0_ns` as its input.
- **GPRPy migrates whatever it is handed.** We refuse (§5.4). A migration that silently runs on
  uncorrected time zero, or on trace index because there is no spatial axis, produces a confident
  image that is wrong by half a metre, and nothing downstream will ever flag it.

---

## 5. The core step

New module `packages/nsgeo-core/src/nsgeo/processing/migration.py`. numpy only — `fft2`, `ifft2`,
`fftfreq`, `searchsorted`. No scipy; the core forbids it.

One layering note: importing `C_M_PER_NS` from `nsgeo.velocity` for the upper velocity bound would
be the **first** import out of `nsgeo.processing.*` into another core module by any step. There is
no runtime cycle — `velocity.py` is a numpy-only leaf whose model imports are `TYPE_CHECKING`-only
— and duplicating the speed of light would be worse. Take the import, and note it, because it sets
a precedent for every step after this one.

### 5.1 The algorithm

Stolt f-k, constant velocity, exploding-reflector. With `vm = v / 2`:

1. Pad in x (§5.3), extend the record to **twice its length in time**, and 2-D FFT to `F(ω, kx)`.
2. For the uniform `kz` grid conjugate to depth `z = vm·t`, map `ω = sign(kz)·vm·√(kx² + kz²)`.
   The sign is not optional: without it the negative frequencies map onto the positive ones,
   Hermitian symmetry breaks, and the image comes back with an imaginary part as large as its
   real one.
3. Move the time origin to the middle of the record (multiply `F` by `e^{iω·T/2}`), interpolate
   linearly in ω at the mapped frequency per `kx`, and move it back (multiply by
   `e^{-iω_map·T/2}`).
4. Scale by the obliquity factor `|kz| / √(kx² + kz²)` — the Jacobian `dω/dkz = vm·|kz|/root`
   divided by the `vm` that taking the output on the input's own time grid has already absorbed.
   It is dimensionless and equals **1 at zero dip**, so a flat reflector comes through at its own
   amplitude.
5. Zero where the mapped frequency falls outside the band the record contains. The evanescent
   region needs no separate mask: `√(kx²+kz²) ≥ |kx|` holds by construction, so `|ω_map| ≥ vm·|kx|`
   always and energy below that line — which corresponds to no propagating wave — is never read.
   What does need zeroing is the steep-dip energy whose mapped frequency the record does not have,
   which the interpolation would otherwise extrapolate from the band edge without bound.
6. Inverse transform, take the real part, crop back to the original sample count and trace count.

The output stays in **time**. `VelocityModel` relabels the axis to depth exactly as it does today,
which is the same decision `ZAxis` took for the cube. Migration does not change what a sample
means; it changes which sample the energy is in.

**Steps 1 and 3 are what the first draft of this spec got wrong, and they are the whole
milestone.** The draft said only "interpolate `F` linearly in ω", and that was built and shipped
into a branch where the collapse failed below about 1.5 m and a broad smear appeared instead —
precisely the artefact §1 calls worse than not migrating. The reason is not the interpolator's
width. An event at two-way time `t` turns the spectrum through `t·Δω` radians per bin; over a
record of length `T` sampled at `Δω = 2π/T` that reaches a **full turn per bin** at the bottom of
the record, which is past Nyquist along the frequency axis, and an aliased phasor cannot be
recovered by any interpolator — an eight-point windowed sinc was measured at 0.780 / 0.250 / 0.056
at 1.5 / 2.0 / 2.5 m, no better than the two-point form. Centring the time origin halves the
winding; doubling the transform halves it again. Measured focus at 0.5 m through 3.5 m:

| | 0.5 m | 1.0 m | 1.5 m | 2.0 m | 2.5 m | 3.0 m | 3.5 m |
|---|---|---|---|---|---|---|---|
| over the record alone | 0.98 | 0.92 | 0.68 | **0.33** | **0.13** | **0.08** | **0.08** |
| centred, doubled | 0.98 | 0.98 | 0.97 | 0.97 | 0.96 | 0.95 | 0.92 |

Doubling the record in time earns its cost twice: it also removes a **temporal** circular wrap.
Migration moves energy up the record, and over the record's own length the time axis is circular,
so energy passing `t = 0` returns at the bottom as a band of invented reflectivity under
everything shallow and strong. On a real line the migrated bottom tenth held 6.8× the middle's
energy against 0.56× in the input; doubled, it holds 0.82×.

**Where these go wrong.** The sign in the ω→kz map, the obliquity factor, and the conditioning of
the ω interpolation. A synthetic point-diffractor test (§9) catches the first two — but only if it
is run at **several depths**: a single apex at 40 ns is the last depth that still clears a
sensible threshold, and a suite with one operating point there sees none of the table above.

### 5.2 Trace spacing is context; velocity is a parameter

`Radargram` gains **one** optional field:

```python
@dataclass(frozen=True, eq=False)
class Radargram:
    data: np.ndarray
    dt_ns: float
    t0_ns: float
    dx_m: float | None = None
```

`from_profile` fills it from `1 / header.traces_per_metre` when that is positive, and leaves it
`None` otherwise — time-triggered collection has no spatial axis, which is the same condition
`GridPlacement` already refuses on.

It defaults, so every existing `Radargram(...)` construction keeps working untouched, and both
`from_profile` call sites get it without either one changing. The `from_profile` docstring says the
method keeps processing "independent of the data model"; that is still true — `traces_per_metre` is
a header field, not a model object — but the docstring should say what it now reads.

Velocity does **not** go on `Radargram`. It is `velocity_m_ns`, a `REQUIRED` float parameter on the
step, in m/ns, bounded `(0, C_M_PER_NS)`. `REQUIRED` is correct and not laziness: there is no safe
default velocity, which is the sentinel's documented meaning, and it makes the UI collect a value
before the step can exist.

### 5.3 Padding is derived, not a knob

The artefact padding exists to prevent is FFT circular wrap at the line ends: energy migrating off
the left edge reappearing on the right. The note left `pad_frac` as the step's one parameter. It
should not be one.

The required pad is **physically determined**: the farthest energy can move laterally is the
migration aperture, `vm · t_max`. On the local data that is `0.0366 × 110.9 = 4.1 m`, which at
`dx = 0.0167 m` is 243 traces each side. The builder computes it; the user has no way to calibrate
a fraction and no reason to.

Round the padded width up to a convenient FFT size. Do the arithmetic rather than assuming it is
free: 606–666 real traces plus 243 each side is 1092–1152, which rounds to **2048, never 1024**.
So the derived pad costs the 194 ms row of §2's table, not the 74 ms row — about **4.7 s across 24
lines**, and that is the number §8 records.

Capping the pad at 1024 would buy 2.6× for 79% of the aperture. Rejected: the pad is physically
determined, this milestone exists to remove edge artefacts rather than create a new one, and 4.7 s
on a cube build nobody runs in a loop is the cheaper side of that trade. Revisit only if the
padding measurement shows the full aperture is unnecessary on real data.

Zero padding, unless the measurement in §9 shows a taper is needed. The slices spec measured and
rejected zero-padding for `amp_envelope` because padding shifted the interior of a non-local
transform; that is the opposite concern and does not transfer. **This earns its own numbers either
way** — the test must show the edge artefact present without the pad and absent with it, not assert
that padding happened.

So the step has exactly one parameter. If the real-data check in §9 shows migration smiles off
noise, a `max_dip` aperture limit returns to scope; it is designed-for, not built.

### 5.4 Refusals

Each is a real failure mode, and each says what to do about it. The UI shows the solver's own
words — M13 established that and it held up in the walkthrough.

| Condition | Refuse because |
|---|---|
| `dx_m` is `None` or not positive | Time-triggered collection has no spatial axis. Migrating on trace index is a metres-versus-traces scale error that produces a plausible image. Name the cause: the file was collected on a timer, not a survey wheel. |
| `velocity_m_ns` outside `(0, C_M_PER_NS)` | Faster than light, or zero. The schema bounds catch the top; **they do not catch the bottom** — `_out_of_bounds` (`base.py:246`) tests `value < spec.min`, so `min=0.0` *accepts* exactly `0.0`, and the float editor is a `QLineEdit` that will happily take it. `v = 0` makes the ω→kz map identically zero and the obliquity factor `0/0`: a NaN image with no complaint, and `0` quietly becomes the sentinel value §3.6 forbids. A step-level `if not velocity_m_ns > 0` guard is required. |
| Time zero not corrected | See below. |
| Data not finite | A NaN anywhere spreads across the whole image through the FFT. One bad trace must not silently destroy the line. |

**The time-zero tolerance: measured, after two wrong answers.** The research note said "`t0_ns`
within half a sample of zero". A half-sample slip costs `vm · dt/2 = 8 mm` of depth — nothing — so
that would reject a first-break pick one sample off for no reason. What the refusal must actually
catch is the uncorrected `−11.09 ns`, which costs **0.41 m**.

The first draft of this spec then tied the tolerance to that consequence: refuse when the implied
depth error `vm · |t0_ns|` exceeds 0.02 m. **That was also wrong, and measuring the shipped
`time_zero` on the real lines is what showed it.** On all ten files, every threshold setting:

| `time_zero` threshold | pick `k` | `t0` after | depth error at 0.0733 | at 0.0900 |
|---|---|---|---|---|
| 0.15 | 48 | −0.6929 ns | 0.0254 m | 0.0312 m |
| **0.20 (default)** | 49 | −0.4764 ns | 0.0175 m | 0.0214 m |
| 0.40 | 55 | +0.8228 ns | 0.0302 m | 0.0370 m |

A 0.02 m rule refuses two of the three threshold settings outright, and at the default it refuses
any velocity above about 0.084 m/ns. A user who had correctly run `time_zero` and typed 0.09 — an
ordinary dry-soil value — would be told to fix a time zero that is already fixed.

**So the tolerance is expressed in time, not depth: refuse when `|t0_ns| > 2.0 ns`.** Three
reasons. The residual is produced by `time_zero`'s sample pick, which is a time quantity; the
measured post-correction band across threshold settings is −0.69 to +0.82 ns, so 2.0 ns leaves
better than twice the headroom while still refusing the uncorrected −11.09 ns by 5.5×; and a
threshold that moves with the number in the velocity box makes the refusal depend on something
unrelated to the fault it is reporting.

The cost of the looser rule is honest and should be stated: 2.0 ns is up to 7 cm of depth shift at
0.0733 m/ns, which is more than the quarter-wavelength resolution (0.21 m wavelength at the
header's `HS350US` 350 MHz antenna, so 5.2 cm). That shift is near-uniform rather than a focusing
error, and it is bounded by what `time_zero` itself can deliver — refusing would not let the user
do any better. The refusal's job is to catch the gross case, not to police the last sample.

The message must name `time_zero` as the fix and state the implied depth error, so a user who
genuinely needs better precision can see what it is costing them.

**There is no minimum-trace refusal, deliberately.** `AddStepDialog._validate` probes a candidate
step by applying it to `radargram.data[:, :1]` — one trace — on every keystroke. A step that
refused fewer than *N* traces would be permanently un-addable, with a disabled OK button and no
explanation. A one-trace FFT is mathematically fine. The builder must confirm the probe path is
fast: skip padding when `n_traces == 1`, or the dialog pays a 512 × 512 transform per keystroke.

---

## 6. Registration, and a new group

`STEP_GROUPS` has no home for this. It is a closed list validated at registration, so the
milestone adds one.

- **Group: `"Migration"`**, inserted between `"Background"` and `"Gain"`:
  `("Time", "Filters", "Background", "Migration", "Gain", "Amplitude")`.
  Migration belongs after time zero and after noise removal — migrating un-filtered noise is the
  classic way to manufacture smiles — and before gain, which is a display operation, and before the
  amplitude transforms, which `slices_engine._build_stack` asserts must be last.
- **Step name: `migrate_fk`.** Permanent; it is what a saved stack stores.
- **Title: `"Migration (Stolt f-k)"`**, matching `"Background removal (mean)"`. Titles are display
  only and are never serialised, so this can be reworded later for free.
- `order = 1` within the group.
- Add `migration` to the import list in `processing/__init__.py` so importing the package registers
  the step.

Group is a display attribute and is never saved, so adding one changes no project file.

---

## 7. The plugin

**No new widgets.** `param_form` already renders a bounded float with a unit, the Processing dock
already lists steps with a per-step checkbox, and `add_step_dialog` already collects `REQUIRED`
parameters. Two small changes:

**7.1 The Add-step dialog must probe what the step will actually receive.** This is a blocker, and
it is not migration's fault. `ProcessingDock.build_add_dialog` (`processing_dock.py:541`) passes
`stack_for(key).source` — the **raw** radargram — and `AddStepDialog._validate` applies the
candidate step to one trace of it on every keystroke. Every real line has `t0 = −11.09` in its
source, so migration's time-zero refusal fires and OK stays disabled **even when `time_zero` is
already the first step in the stack**. That is precisely the "permanently un-addable, with a
disabled OK button and no explanation" failure §5.4 rules out for a minimum-trace refusal.

Pass the stack's `result()` instead, falling back to `source` when it raises `ValueError` and
logging that it did. This is not a new judgement: `ProcessingDock.time_axis`
(`processing_dock.py:516`) already defines "the input a step appended right now would actually
receive" as `result()` "exactly as the new step's own `apply()` will see it", and already
specifies this fallback and this log for the case where another step in the stack is
misconfigured. The probe is simply inconsistent with the decision beside it, and there is no
comment anywhere claiming otherwise.

It changes probe behaviour for every step, not only this one, which is why it gets its own test
rather than riding along with the prefill.

**7.2 Prefill the velocity.** `AddStepDialog` calls `form.set_step(name)` with no seed, though
`ParamForm.set_step` already takes a `params` dict. Give the dialog an optional seed and have its
caller in the Processing dock pass `{"velocity_m_ns": session.resolved_velocity(key).surface_velocity}`
for this step. That is `resolve_velocity`'s existing chain — line override, then grid, then header
dielectric — so the prefill is the same number the depth axis and every pick already use, and the
user confirmed that is what they want it to be.

Prefill only. The value is then the step's own, and a later velocity change does not reach back
into it.

**7.3 Show the number against the line.** The hazard in a prefilled value is not being wrong, it is
being **silent**: a velocity frozen three lines ago looks identical to one that belongs to the open
line. Where the Processing dock names the step, show its velocity and, when the open line resolves
to something materially different, say so — `0.0733 m/ns · this line says 0.0801`. No refusal, no
auto-correction, no dialog. The user decides whether to retype it.

"Materially different" needs a threshold; a builder call. Something like 2% is defensible, but
whatever is chosen must be a named constant with its reasoning beside it, and it must not be
derived from any value it is comparing — M13 shipped four tests that read as correct while pinning
nothing, every one because a probe value was computed from the constant it checked.

---

## 8. The cube

**Nothing to do.** This is the whole payoff of §3.2 and §3.3.

The step is a pure function of its parameters and a `Radargram`, and the only context it needs
comes from the header, which the worker thread already has. So `slices_engine` needs no change at
all: the moment `migrate_fk` is in a preset, every line prepared for the cube is migrated, at the
velocity the preset carries.

Three consequences to record rather than discover:

- **Ruling Q survives.** M12 deliberately excluded a velocity-only edit from the rebuild
  fingerprint because "the prepared lines do not depend on velocity at all". That remains true:
  the velocity that migrates a line is in the preset, not in the line. Had velocity been context,
  this ruling would have had to be reopened and a velocity edit would have re-prepared every line
  for about a second. It does not.
- **Provenance is free.** `Provenance.steps` already records every step's parameters, so the
  velocity a cube was migrated at is written into the cube and travels with the export. No new
  field.
- **The cost is real:** about **10.2 s** added across 24 lines, on top of the existing
  preparation — the derived pad always lands on a 2048-wide transform for these lines (§5.3), and
  §5.1's time extension doubles the rows again. Measured at 426 ms a line. (An earlier draft of
  this section said 4.7 s, from before the time extension existed.) Worth stating in the plan so
  nobody reports it as a regression, and worth a second look if a site ever holds hundreds of
  lines rather than twenty-four.

---

## 9. Testing

Real data is the primary validation; synthetic goes only as far as it mirrors it.

**Synthetic, and unforgiving.** A single point diffractor in a zero field, at a known position and
a known velocity. Migrating at that velocity must collapse it to a compact spot **at the right
trace and the right time**, not merely to something narrower. Assert the peak's location and that
the energy within a small window around it rises above a literal fraction of the total. This is
the test that catches a sign error, an `fftshift` slip and a wrong obliquity factor, and it should
be written before the solver.

Also synthetic: migrating at a velocity well above and well below the truth must leave it
**not** collapsed, in the two distinguishable directions — under-migrated keeps a downward-opening
residual, over-migrated produces an upward-opening smile. A test that only checks the correct
velocity cannot tell migration from blurring.

**The padding measurement.** Place a diffractor near a line end. Show the wrap artefact at the far
end **with no pad** and its absence **with the derived pad**, as numbers. If zero padding leaves a
visible edge discontinuity, measure a taper and say so. Do not assert that padding was applied.

**The refusals**, one test each, asserting the message names the fix. Include `t0 = −11.09`
verbatim from the real headers, and a first-break-corrected `t0` a sample or two off zero which
must be **accepted** — that boundary is the entire point of §5.4's tolerance, and a test that only
checks the refusing side pins nothing.

**Shape invariance.** Output `shape`, `dt_ns` and `t0_ns` identical to input, so
`StepStack.difference()` and the trace-index join hold. Assert on a real line, not a square array.

**Real data — and this is blocked on an answer, not on code.** On a local `FILE__0NN.DZT` line
with a genuine diffraction: `time_zero`, then `migrate_fk` at the velocity measured in M13's
walkthrough. The hyperbola must collapse.

The first draft of this section said "record the coordinates, as M13 did". **M13 did not.** Its
ledger states "a real diffraction fitted, the velocity judged physically sane, coordinates
recorded", and its own task-5 report, written later, still lists "identify a real diffraction in a
local `FILE__00n.DZT`; the spec §9 real-data test does not exist yet" as outstanding. Nothing in
the repository or the session transcript records a file, a trace or a time. The two measured
velocities survive only as bare numbers. **The ledger's claim was false**, and the gap it hid is
now this milestone's.

So before this test can be written, someone has to open a line and say which diffraction: the
file, roughly which trace and two-way time, and which of 0.0701 / 0.0733 belongs to it. The real
DZTs are git-ignored, so this test is local-only and skipped on CI either way — which means
nothing downstream will notice if it is quietly never written. That is exactly how the M13 gap
survived.

The assertion must be as specific as the synthetic one — peak trace, peak time, and windowed
energy above a literal fraction — not prose about collapsing. §9's own warning applies here most
of all.

**Trace spacing.** Assert `from_profile` reads 60 traces/m from a real header, and that a
synthesised `traces_per_metre = 0` header yields `dx_m is None` and a refusal rather than a
migration on trace index.

**Mutation testing is the acceptance criterion for the test suite, not an extra.** M13's final
review found that computing the residual in t² instead of t passed all 57 tests while reporting a
number 89× wrong. Mutate at minimum: the sign of the ω→kz map, the obliquity factor, the evanescent
cut, the `v/2`, and the pad width. Run with `PYTHONDONTWRITEBYTECODE=1` in a throwaway worktree —
never in the tree the branch is committed from.

---

## 10. Manual checkpoints

These are human gates. They are tracked and reported, never silently passed.

- **M1.** On a real line, at a measured velocity: the hyperbola collapses, and the user judges it.
- **M2.** The anti-goal, checked deliberately rather than assumed: toggle the step off and on and
  look for anything that was not there before — smiles off noise, ringing, an edge discontinuity.
  This is half of the stated success criterion and no automated test covers it.
- **M3.** A grid of lines migrated into a cube, and the slices compared against the same cube
  unmigrated. Not a pass/fail gate — the user has said the profile is the test — but it is the
  reason the milestone exists, and it is the first time anyone will see whether the tails actually
  stop reaching the slices.

---

## 11. Out of scope

Named so the plan does not quietly grow:

- **Velocity scrubbing.** Measured, feasible at about 13 redraws a second, deliberately deferred
  (§3.5).
- **Per-line velocity in the cube.** The accepted consequence of §3.2. Reachable later by making
  `velocity_m_ns` optional, which §3.6 keeps possible.
- **Phase-shift migration** for v(z), and the layered velocity model that would feed it. A separate
  step. M13 already stores several fits per line at several depths without averaging them, which is
  the raw material.
- **Kirchhoff migration**, and topographic migration especially. The note's one genuine
  architectural exception: topographic output rows are elevation, not time on a flat datum, which
  outgrows `Radargram → Radargram`.
- **Migration velocity scan** — migrating at a range of velocities and scoring the focus. The
  natural successor to both this and M13.
- **3-D migration.** This is 2-D, line by line. It collapses along each line and does nothing
  across lines, so a point target becomes a streak perpendicular to the traverses rather than a
  ring. The user was told this and accepted it.
- **`max_dip` aperture limiting.** Returns to scope only if the real-data check shows smiles.

---

## 12. Tasks

Three, smaller than M13's five.

1. **The solver.** `processing/migration.py`: the transform, the derived pad, the four refusals.
   Synthetic point-diffractor tests written first. Pure core, no Qt, no scipy.
2. **Spacing and registration.** `Radargram.dx_m`, `from_profile`, the `"Migration"` group, the
   registry entry and the `processing/__init__.py` import. Small, and it is what makes the cube
   work for free — a test should assert that, by preparing a line through `slices_engine`'s own
   path with migration in the preset.
3. **The plugin and the real data.** The `AddStepDialog` prefill, the stale-velocity read-out, and
   the real-data validation on the local lines. Confirm the one-trace probe path is fast.

The test suite is the bulk of all three, which is the normal shape here.

---

Design: this document.
Research it supersedes in part: `docs/superpowers/notes/2026-09-19-migration-research.md`
Milestone it depends on: `docs/superpowers/specs/2026-09-20-nsgeo-velocity-fit-design.md`
