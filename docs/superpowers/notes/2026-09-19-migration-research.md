# GPR migration — research and sizing

**Status: parked.** Researched and part-designed on 2026-09-19, then deliberately
re-ordered behind the velocity fit tool. This note records what was established so
that resuming costs no rework.

## Why this note exists

The question asked was how big a challenge migration would be — a pulse, not a
commitment. Research and two design sections were done before the ordering
question settled it: the **velocity fit tool becomes its own milestone and lands
first**, because migration's output quality is entirely determined by its velocity,
and because the fit tool earns its place with no migration at all (the profile
viewer's depth axis, `ZAxis.depths_m`, and pick depths all currently run on
`header.epsr`, the manufacturer default).

## What is available externally

| Tool | Licence | Migration it has | Use to us |
|---|---|---|---|
| GPRPy | MIT, Python | `fkMigration()` — a *wrapper* around `mig_fk.fkmig` from Nat Wilson's irlib, imported in a `try/except` printing "Install fk migration if needed". Constant-velocity Stolt, output in time, x-axis resampled. Also `hypStackedAmplitude`/`linStackedAmplitude` velocity panels and `correctTopo` (scipy pchip). | Closest analogue. Even it does not own its migration. |
| RGPR | GPL, R | The most complete: `migration(type="kirchhoff")`, including topographic Kirchhoff. | Reference for behaviour. GPL and R — no code path to us. |
| readgssi | GPL, Python | None. | — |
| GPRImagingPy (2026, SoftwareX) | Open access | F-K migration, RTM with several imaging conditions, source-independent FWI, MTV regularisation. | Worth reading. HPC-oriented, heavy dependencies. |
| PyLops / DiffraPy / Madagascar | BSD-ish | Kirchhoff operators, diffraction imaging. | Correct, but scipy-and-up. |

**The finding that decides the approach:** nothing exists that is both numpy-only and
permissively licensed. Every candidate fails either the licence test (RGPR) or the
core's numpy-only constraint. So we implement — which is proportionate, because
Stolt f-k is a couple of dozen lines of numpy given `rfft`/`irfft` and `np.interp`,
an idiom `processing/bandpass.py` and `amp_envelope` already demonstrate here.

## Algorithm shortlist

- **Stolt f-k** — 2-D FFT, map ω→kz through the dispersion relation with the obliquity
  scale factor, one 1-D interpolation per kx, inverse FFT. Constant velocity
  (exploding reflector, v/2). Fastest, `O(N log N)`.
- **Gazdag phase-shift** — downward continuation in f-k, layer by layer. Handles v(z)
  exactly with no interpolation, and would consume the existing layered
  `VelocityModel` as-is. Costs roughly nz × Stolt.
- **Kirchhoff summation** — time domain, over an aperture. The only one that takes
  topography and irregular geometry. Slowest; needs aperture and anti-alias care or
  it manufactures artefacts.
- RTM / FWI — out of proportion for this project.

Focusing quality: Kirchhoff ≈ Stolt > phase-shift > plain hyperbolic summation, with
Kirchhoff the slowest (Özdemir et al. 2014; Kirchhoff-vs-FK comparison, 2016).

Migration is only as good as its velocity, and a wrong velocity is **worse than not
migrating** — it over- or under-collapses hyperbolas into plausible-looking
artefacts. For common-offset archaeological data the standard is diffraction
hyperbola fitting (Jacob & Urban 2016 is the archaeologists' tutorial), optionally
refined by a migration velocity scan.

## Decisions taken

1. **Purpose: both, profiles first.** A step that composes into the cube for free,
   but judged and tuned in the profile viewer.
2. **Velocity: hyperbola fit tool, and it goes first** as its own milestone with its
   own design. Migration velocity scan refinement: designed for, not built.
3. **Algorithm: Stolt f-k first** (`migrate_fk`). Phase-shift and Kirchhoff become
   sibling registered steps whenever wanted, per the `background_mean` /
   `_sliding` / `_svd` precedent — distinct algorithms get distinct step names, and a
   `choice` param is only for variants inside one algorithm.
4. **Sequence: its own plan.** Originally placed after M11; the velocity milestone was then
   placed after M12, so migration follows it as **Plan 5, M14**. See
   `docs/superpowers/specs/2026-09-20-nsgeo-velocity-fit-design.md`.
5. **Velocity reaches the step as acquisition context on `Radargram`**, not as a step
   parameter — so one preset applied across a grid migrates each line at its own
   velocity, which is what per-line overrides exist for.

## What is not blocking between the methods

The three methods are independent registry entries. What they *do* share — decided
once by whichever ships first, and serialised into saved stacks and presets:

1. **How a step learns trace spacing.** `Radargram` has only `dt_ns`/`t0_ns`.
   Answered by `dx_m` from `header.traces_per_metre` — the same quantity
   `GridPlacement.distance_along` already uses. No new source of truth.
2. **Where velocity comes from** — context versus parameter (settled: context).
3. **Trace-count invariance.** GPRPy's `fkmig` resamples the x-axis and returns a new
   `profilePos`. We cannot: picks, map↔profile cursor sync and cube binning all index
   by trace. Pad internally, crop back.

**The one genuine exception:** Kirchhoff *with topography* outgrows
`Radargram → Radargram`, because its output rows are elevation, not time on a flat
datum — the same wall the slices spec hit with `ZAxis`. Flat-surface Kirchhoff is
fine as a step; topographic migration may need more than a new registry entry.

## Design reached before parking

### Acquisition context on `Radargram`

```python
@dataclass(frozen=True, eq=False)
class Radargram:
    data: np.ndarray
    dt_ns: float
    t0_ns: float
    dx_m: float | None = None
    velocity: VelocityModel | None = None
```

Both default to `None`, so all 34 test constructions and every `.replace()` keep
working untouched; there are no non-test `Radargram(...)` construction sites.
`from_profile` gains two optional arguments with fallbacks: `dx_m` from
`1 / header.traces_per_metre` when positive (`None` otherwise — the time-mode
collection case `GridPlacement` already refuses), and `velocity` from
`VelocityModel.from_dielectric(header.epsr)`, the third tier of `resolve_velocity`.

The single production caller is `session.py:572`, and `self.resolved_velocity(key)`
already exists at `session.py:535`. One line carries the full line→grid→header
precedence into the step.

`processing` importing `velocity` adds no cycle: `velocity.py` is a numpy-only leaf
whose model imports are already `TYPE_CHECKING`-only. It does soften `from_profile`'s
"independent of the data model" docstring, which should be amended rather than
quietly falsified.

### `migrate_fk`

New module `processing/migration.py`, one registered step. Four contracts, all
refusals rather than guesses:

| Contract | Why refusing beats guessing |
|---|---|
| `dx_m` present and positive | Time-mode collection has no spatial axis; migrating on trace index is a metres-vs-traces scale error that looks plausible. |
| `velocity.is_constant` | Stolt is a constant-velocity method. An RMS fudge over layers is a silent approximation; the error names phase-shift as the method for v(z). |
| `t0_ns` within half a sample of zero | A real SIR-4000 file starts at −11.09 ns; migrating that puts every diffractor at the wrong depth. `time_zero` lands t0 at ≈0 by construction, so the error names it. |
| Output preserves shape, `dt_ns`, `t0_ns` | Picks, cursor sync and cube binning index by trace; `StepStack.difference()` refuses steps that change sample count. |

Algorithm, all numpy (`fft2`, `ifft2`, `fftfreq`, `interp` — no scipy): half velocity
`vm = v/2`; zero-pad in x; 2-D FFT to `F(kx, ω)`; for the uniform `kz` grid conjugate
to `z = vm·t`, map `ω = vm·√(kx² + kz²)`, interpolate `F` in ω per kx (linear on real
and imaginary parts), scale by the obliquity factor `vm·kz / √(kx² + kz²)`; zero the
evanescent region `|ω| < vm|kx|`; inverse transform, take the real part, crop.
Output stays in **time** — the existing `VelocityModel` relabels the axis, as `ZAxis`
decided for the cube.

Two judgement calls:

- **Padding needs its own measurement.** The slices spec measured and rejected
  zero-padding for `amp_envelope`, because padding shifted the interior of a
  non-local transform. Here padding is the fix rather than the hazard — the artefact
  is FFT circular wrap at the line ends. Different concern; it earns its own numbers.
- **No dip limit in v1.** The evanescent cut is mandatory and included. A `max_dip`
  aperture is the usual remedy for migration smiles off noise, but whether real data
  needs one is measurable, so it stays designed-for. That leaves `pad_frac` as the
  single parameter.

## Sizing

**3–4 tasks. Small-to-medium, and not a research problem.**

- `migrate_fk` — one module about the size of `gain.py` (179 lines). The numerics are
  ~40 lines; the rest is schema, the four refusals, and house-style docstrings.
- Acquisition context, `from_profile`, the session line — ~30 lines across three
  files, no test churn because the new fields default.
- Tests are the bulk: synthetic point-diffractor round trip, the padding measurement,
  the four refusals, real-data validation on the local `FILE__00n.DZT` lines.
- UI: none. `param_form` already renders a float parameter.

Risks that would make it bigger: the ω→kz interpolation plus obliquity factor is
fiddly, and sign and `fftshift` conventions are where these implementations usually
go wrong (the synthetic diffractor test is unforgiving enough to catch it); uniform
trace spacing is assumed and should be verified against the local files; and if real
data shows migration smiles off noise, the dip limit returns to scope.

## Still to design when this resumes

Cube integration (expected to be free — `build_cube` takes already-prepared lines,
so M11's preparer supplies the context), the testing plan in full, and the milestone
breakdown. Then a spec, then a plan.

Acceptance test to aim for, once the fit tool exists: fit a hyperbola on a real line,
migrate at that velocity, confirm the hyperbola collapses to a point.

## Sources

- [GPRPy](https://github.com/NSGeophysics/GPRPy) — MIT, and [Plattner 2020](http://www.alainplattner.net/downloads/Plattner2020.pdf)
- [RGPR](https://github.com/emanuelhuber/RGPR) — GPL, R
- [GPRImagingPy, SoftwareX 2026](https://www.sciencedirect.com/science/article/pii/S235271102600258X)
- [Özdemir et al. 2014, A Review on Migration Methods in B-Scan GPR Imaging](https://onlinelibrary.wiley.com/doi/10.1155/2014/280738)
- [Kirchhoff and F-K migration to focus GPR images (2016)](https://link.springer.com/article/10.1186/s40703-016-0019-6)
- [Jacob & Urban 2016, CMP velocity determination: a tutorial for archaeologists](https://onlinelibrary.wiley.com/doi/abs/10.1111/arcm.12214)
- [Stolt migration, SEG Wiki](https://wiki.seg.org/wiki/Stolt_migration)
