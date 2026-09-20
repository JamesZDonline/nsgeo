# nsgeo velocity fitting (Plan 5, M13) — design

Measure radar velocity by fitting a diffraction hyperbola in the profile viewer, and close the
line-velocity stub while we are there. First milestone of Plan 5; migration (M14) follows it and
depends on it.

---

## 1. What this milestone is for

Every depth this product shows is currently a guess.

`resolve_velocity` falls back to `VelocityModel.from_dielectric(header.epsr)` — the permittivity
the manufacturer wrote into the DZT — unless a human typed a number into the grid dialog. That
fallback feeds the profile viewer's depth axis, `ZAxis.depths_m` on every slice cube, and the
depth on every pick. None of it is measured.

A diffraction hyperbola is the measurement. A point-like buried object is recorded from every
antenna position that can see it, so it appears as a hyperbola whose **curvature is set by
velocity alone**. Fitting it converts the guess into a number with an uncertainty attached.

This also unblocks migration, whose output quality is entirely determined by its velocity: a
wrong velocity is worse than not migrating, because it collapses hyperbolas into plausible-looking
artefacts at the wrong place. See `docs/superpowers/notes/2026-09-19-migration-research.md`.

---

## 2. Starting state, measured

| What | Where | State |
|---|---|---|
| Grid velocity | `grid_dialog.py:143-145`, seeded at `:214-216` | **Built.** A 0–0.3 m/ns spin box, 4 dp, `setSpecialValueText("required")`, hinted "from the header dielectric". |
| Line velocity override | `plugin.py:834`, wired from `survey_dock.py:53,317` | **Stub.** The menu item exists and pops *"Velocity dialog arrives in a later task."* |
| Velocity precedence | `velocity.py: resolve_velocity` | Line override, then grid, then header dielectric. |
| Velocity write path | `session.py:461`, `:526`, `:535` | `set_grid_velocity`, `set_line_velocity` (both accept `None`), `resolved_velocity(key)`. Built and tested. |
| Velocity read-out | `profile_dock.py:67`, `:740` | `velocity_source()` names the tier that won; the bar shows `v = 0.098 m/ns (grid)`. |
| Layered model | `velocity.py: VelocityModel` | `layers` has been a tuple since day one, so layers need no file-format change. **Nothing has ever populated more than one.** |
| Screen↔data conversion | `view_transform.py:80-105` | `x_of_trace`/`trace_of_x`, `y_of_time`/`time_of_y`. Both directions already exist. |
| Click gating precedent | `profile_view.py:434` | `_pick_mode` (or Shift) turns a left click into `pick_requested`. M8 wires it from a `plugin.py` toolbar toggle and `ProfileDock.set_pick_mode`. |
| Orphan rule | `tests/pure/test_no_orphan_signals.py` | Automated. A new signal with no `connect` fails a test. |
| Real data | `nsgeo-core/tests/data/local/` | Ten real DZT lines, gitignored, guarded by `skipif(not FILES)`. |

---

## 3. Decisions taken in brainstorming

| Decision | Choice | Why |
|---|---|---|
| Interaction | **Limb points only.** Apex click, then clicks along the limbs. No drag gesture. | Objective and reproducible, and it yields a residual. A drag-to-widen gesture feels better but can never tell you the fit is poor. |
| Velocity count | **One constant now**, designed so layers are not blocked | `VelocityModel.layers` already supports layers; what would block them is discarding the measurements, not the model. |
| Fit record | Store `(t₀, v, σ, rms, points)`, not just the answer | A hyperbola measures the **RMS velocity to that reflector**, not an interval velocity. Dix conversion needs the `(t₀, v_rms)` pairs. Discarding them is the thing that would block layered velocity. |
| Several fits | **The user selects which fit drives the line.** No averaging. | Averaging fits at different depths erases a real depth trend and reports a number matching neither reflector — and would teach a meaning that Dix later contradicts. |
| Fits collection | A **dict keyed by id**, not a list | The codebase's own ruling: the slices spec records that `cubes` was specified as a list and shipped as a dict keyed by id, "which is better — it matches `presets`, and it makes lookup by id direct". An id also survives deleting a sibling, which an index does not. |
| Scope | Fit tool **and** the line-velocity dialog | The stub is a live orphan of exactly the kind Plan 3 §6 says cost a manual testing session. "Every route to setting velocity works" is one coherent story. |
| Placement | **After M12**, ahead of migration (M14) | Keeps Plan 4 unbroken; velocity and migration become a clean Plan 5. |

---

## 4. Prior art, and where we differ

GPRPy has `hypStackedAmplitude` and `linStackedAmplitude`, which build stacked-amplitude panels
over a velocity range for CMP-style picking — velocity analysis, but not an interactive fit against
a diffraction on a common-offset profile. Commercial packages (RADAN, ReflexW, GPR-SLICE)
conventionally offer a hyperbola cursor the operator matches against the data by eye.

Two differences, both deliberate:

- **We report an uncertainty, not just a value.** Jacob and Urban's tutorial for archaeologists
  (Archaeometry, 2016) is specifically about *precision estimates* on GPR velocity. A velocity
  without one cannot be argued with, and a layered model later built by Dix conversion inherits
  bare numbers instead of real uncertainties.
- **A fit is a stored, re-openable record**, not a transient cursor state. That is what makes it
  provenance — you can see why a line's velocity is what it is — and what makes the layered
  extension additive rather than a rewrite.

---

## 5. The core fit

New module `nsgeo/velocity_fit.py`. numpy only, no Qt, no model imports.

### 5.1 The record and the function

```python
@dataclass(frozen=True)
class HyperbolaFit:
    apex_x_m: float          # solved, not clicked
    t0_ns: float
    v_m_ns: float
    v_stderr_m_ns: float     # how well the points actually pin v down
    rms_ns: float
    n_points: int

def fit_hyperbola(x_m, t_ns, apex_guess_m, *, search_m=0.25) -> HyperbolaFit
```

**The core takes metres along the line, not trace indices.** The plugin converts with
`line.distance_along()`, which already folds in `traces_per_metre`, `start_along` and `direction`.
This keeps the fit pure physics and keeps placement knowledge out of it — the same boundary
`Radargram` draws by taking `dt_ns` rather than a `Profile`.

### 5.2 Why it is closed-form

For a point diffractor at depth *d* under a constant velocity *v*, with the apex at x₀:

```
t(x) = (2/v)·sqrt(d² + (x − x₀)²),    t₀ = 2d/v
```

Squaring makes it **linear** in the two unknowns:

```
t² = t₀² + (4/v²)·(x − x₀)²
     └─┬─┘   └──┬──┘
   intercept   slope        against regressor (x − x₀)²
```

So once x₀ is fixed, the fit is one `np.linalg.lstsq` — no iteration, no initial guess, no
convergence failure, and no scipy. The standard error on v comes from the same solve, via
`σ²·(AᵀA)⁻¹` and the chain rule through `v = 2/sqrt(slope)`.

`rms_ns` is computed in **time**, not in t², so the number means nanoseconds to the person
reading it.

### 5.3 The apex click supplies x₀ only

t₀ is solved as the intercept, so a click that sits above or below the true wavelet peak does not
bias the result — which matters, because the apex is the hardest point to place by eye on a real
wavelet. `search_m` then scans candidate apex positions either side of the click, solving the
linear system at each and keeping the lowest residual, so the click's *horizontal* error is
removed too. Closed-form per candidate, so the whole scan is milliseconds.

The clicked apex is included as an ordinary fitted point. At the apex dx = 0, so its row in the
design matrix is `[1, 0]`: it pins the intercept and contributes nothing to the slope. Well
conditioned, no special case. If the apex search moves x₀, that point simply acquires a small
non-zero dx, which is correct.

### 5.4 Refusals

Each is a real failure mode, not a formality.

| Condition | Meaning |
|---|---|
| Fewer than 3 points | Two unknowns; the third is what makes the residual mean anything. |
| Any non-finite or non-positive time | A point at or above t = 0 is not on a diffraction. |
| Solved slope ≤ 0 | The points do not describe a downward-opening hyperbola — usually a limb clicked on the wrong side. |
| `v > C_M_PER_NS` | Faster than light in vacuum. `velocity.py` already defines the constant; a fit returning this was given something that is not a diffraction. |
| Singular design matrix | Every point at the same dx. The fully degenerate form of clustered points. |

**Three points is necessary and not sufficient**, and the standard error is what catches the rest.
Points clustered near the apex have a tiny lever arm in dx², so 1/v² is barely constrained — and
the RMS residual looks *excellent*, because a near-degenerate fit passes beautifully through its
own clustered points. Reporting σ is what makes "the tool can tell you it fitted badly" true in
that case rather than merely claimed.

---

## 6. Storage

### 6.1 The fits record

The survey JSON's line entry gains two optional keys:

```json
"velocity_fits": {
  "f1": {
    "apex_trace": 412,
    "t0_ns": 18.4,
    "v_m_ns": 0.0984,
    "v_stderr_m_ns": 0.0041,
    "rms_ns": 0.31,
    "points": [[389, 21.2], [412, 18.6], [437, 21.9]],
    "fitted_at": "2026-09-20T14:02:11Z"
  }
},
"velocity_from_fit": "f1"
```

`SCHEMA_VERSION` stays at 1. Both keys are additive and optional, and `load_site` reads only the
keys it knows — so a file with fits opens in an older build (ignoring them) and a file without
opens here. This is the argument M10 used for `cubes`, and it is tested rather than asserted.

**Points are stored as trace indices, not metres.** Metres-along depend on the placement's
`start_along` and `direction`, which re-georeferencing a grid can change; a stored fit that
silently slid sideways when a grid corner moved would be a nasty and near-invisible bug. Trace
indices are intrinsic to the DZT file. The velocity is unaffected either way, because the
metres-per-trace it depends on comes from the header, which does not change. The plugin converts
in both directions at the boundary — `line.distance_along()` on the way into `fit_hyperbola`, and
back to indices on the way into the JSON.

`velocity_from_fit` is what lets the dialog show which fit is active, and lets `velocity_source`
report **"line (fit at 18.4 ns)"** rather than a bare "line" — so a velocity that was measured
stays distinguishable from one that was typed.

### 6.2 A fit is evidence, not a setting

Saving a fit changes no velocity anywhere. Applying one is a separate, explicit act, through the
existing `set_line_velocity` / `set_grid_velocity`. This is the step stack's "nothing runs
automatically" principle applied to measurement: recording what you observed and deciding what the
survey should use are different decisions, and conflating them would make a stray click silently
redefine every depth on the line.

---

## 7. Several fits on one line

Fits at several depths on one line are exactly the Dix input — `(t₀, v_rms)` pairs in increasing
t₀ — so this situation is the layered feature in embryo, and v1's job is to record it faithfully
and decline to pretend it is one number.

- **Exactly one fit is active**, selected by the user, recorded in `velocity_from_fit`.
- **No averaging.** Fits at different depths are different measurements, not repeat readings.
- **A passive disagreement flag.** The dialog lists fits sorted by t₀ and marks any pair whose
  velocities differ by more than their combined σ, taken as `sqrt(σ₁² + σ₂²)`. Nearly free, and it is precisely the diagnostic
  that says "this is a layered situation" — the natural on-ramp to Dix conversion.

---

## 8. The plugin

### 8.1 "Fit" is already taken

`profile_dock.fit_button` is **"Fit" = zoom-to-fit**, wired to `ProfileView.fit()`. Anything here
named `fit_button` or `set_fit` would collide with real, unrelated behaviour. The control is
**"Velocity"**; the mode is `set_velocity_fit_mode`; the overlay setter is `set_velocity_fit`.

### 8.2 Fit mode

A toolbar toggle in `plugin.py` → `ProfileDock.set_velocity_fit_mode` → `ProfileView`, mirroring
the structure M8 established for pick mode. In the mode, left-click appends a point (the first is
the apex) and right-click drops the nearest. The mode owns the click the way `_pick_mode` does at
`profile_view.py:434`, so left-drag selection and middle-drag pan are untouched.

Because M8 is unmerged at the time of writing, the implementation plan reads M8's shipped
pick-mode code rather than this description of it.

### 8.3 The overlay

`_paint_velocity_fit`, beside `_paint_picks`. Working points in the selection blue
`(48,140,198)`, the fitted curve in the cursor orange `(255,159,26)` — both already defined in
`profile_view.py`, and both distinct from picks' red `(224,66,27)`. The curve is sampled per
screen column, which is cheap.

**Every saved fit on the line is drawn faint**, with the one being edited highlighted, so the
profile itself answers "what have I already measured here?" without opening a dialog.

### 8.4 The result strip

Under the view while the mode is on:

```
v = 0.0984 ± 0.0041 m/ns · rms 0.31 ns · 5 pts    [Apply to line] [Apply to grid] [Save fit] [Clear]
```

It carries the **time-zero warning**: the fit reads the displayed time axis, so if the working
radargram's `t0_ns` is not ≈ 0 the apex time is measured from the wrong origin and the velocity
comes out wrong. `fit_hyperbola` receives bare coordinates and cannot detect this; the strip can,
and names `time_zero` when it does.

### 8.5 The velocity dialog closes a stub

`open_velocity_dialog` becomes real:

- A spin box mirroring `grid_dialog`'s (0–0.3 m/ns, 4 dp), seeded from the resolved velocity.
- A list of that line's saved fits — t₀, v ± σ, rms, point count, the disagreement flag — with
  selection and Apply.
- **Clear override**, since `set_line_velocity` accepts `None` and an override that cannot be
  removed is a trap.

---

## 9. Testing

Two tiers, unchanged.

**Pure core** (`tests/test_velocity_fit.py`):

- **Exactness.** Points sampled from an analytic hyperbola with known (x₀, t₀, v) recover all
  three to floating-point tolerance. It is a closed-form solve; "approximately" would mean
  something is wrong.
- **Apex recovery.** A deliberately wrong apex guess; `search_m` finds the true x₀.
- **Noise**, fixed seed: the error sits inside 3σ of the reported standard error. Deterministic,
  not flaky.
- **Clustered points**: small rms *and* large σ. This is the test that makes §5.4's claim true.
- **Each of the five refusals.**

**Persistence** (`tests/test_project.py`): round-trip the fits dict and `velocity_from_fit`; a
file without the keys loads; a file with them loads in a build that ignores them.

**Real data** (`tests/test_real_files.py`, under the existing `skipif(not FILES)` guard): points
from an actual diffraction in a local `FILE__00n.DZT` give a velocity inside roughly
0.06–0.15 m/ns — the range spanning wet clay to dry sand, wide enough not to encode a site
expectation and narrow enough to catch a sign or unit error — with a small residual.

**QGIS tier**: fit mode gates clicks without disturbing selection or pan; the overlay paints
working and saved fits; the strip reports v ± σ and warns about time-zero; apply calls the
existing session setters; the dialog lists, selects, applies and clears.
`test_no_orphan_signals.py` catches any new signal with no `connect` automatically.

---

## 10. Manual checkpoints

Human gates, to be tracked and reported rather than silently passed:

1. **Identify a real diffraction.** Someone must look at the local lines, find a clean hyperbola
   and read off its coordinates once, before the real-data test in §9 can exist. Blocks that test
   only, not the core.
2. **Sanity-check the fitted velocity against site expectation.** A number that is arithmetically
   correct and physically absurd is the failure mode that automated tests cannot see.
3. **Build and walkthrough before any merge decision**, per standing practice.

---

## 11. Out of scope

**Designed for, not built:** Dix conversion and `VelocityModel.from_fits()`; the layered-velocity
editor; inverse-variance combination of repeated fits at one depth; grid velocity weighing fits
from all of its lines; re-opening a stored fit's points back into the editor for adjustment (the
points are stored, so this is additive); the antenna-separation form of the hyperbola, which is
not linearisable and biases shallow fits; migration velocity scan refinement.

**Out entirely:** CMP/WARR acquisition and semblance panels (we do not collect CMP data);
automatic hyperbola detection; velocity from a known target depth; migration itself, which is M14.

---

## 12. Tasks

Five, each independently reviewable, with the entire core testable before any Qt exists.

| | Task | Ends with |
|---|---|---|
| 1 | Core fit — `velocity_fit.py`, apex search, standard error, five refusals | A velocity from points, fully tested, no UI |
| 2 | Persistence — id-keyed fits, `velocity_from_fit`, `project.py` | Fits survive save and reload |
| 3 | Overlay and fit mode — view painter, click handling, toolbar toggle per M8 | You can click a hyperbola and see it fitted |
| 4 | Result strip and apply — v ± σ read-out, apply to line/grid, time-zero warning | The fit becomes the line's velocity |
| 5 | The velocity dialog — closes the `plugin.py:834` stub, fit list, clear override | Every route to setting velocity works |

The implementation plan is written when M12 lands, so that it reflects what was built rather than
what was predicted.
