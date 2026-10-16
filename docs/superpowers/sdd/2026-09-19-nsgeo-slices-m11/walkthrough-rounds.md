# The walkthrough gate: three rounds, eight defects

M11 is entirely UI, so the manual walkthrough was the only thing that could test what the
milestone claims. It ran three times. **Every defect below was found by a human using the
plugin, and none of them would have been caught by the test suite as it stood** — several were
shipped *with* passing tests covering the same code.

The deploy target is the `ns_geo` QGIS profile, symlinked at this worktree. Measurements marked
"real QGIS" come from running the actual application headlessly
(`QT_QPA_PLATFORM=offscreen qgis --profile ns_geo --nologo --code probe.py`, the probe writing
JSON from a timer and ending in `os._exit(0)` so the profile's own saved layout is not
overwritten on exit). That technique is what turned three "cannot reproduce" reports into
measurements, and is recorded in the environment-facts note.

---

## Round 1 — three defects

### 1. A seeded z range that no preset could slice *(blocking)*

Reported as, verbatim:

```
nsgeo: line 'FILE__001.DZT' spans -0.476..99.561 ns, which does not cover
the cube's -11.086..99.546 ns; shrink the z range or exclude the line
```

`_seed_dz_z_defaults` seeded `z0`/`z1` from the **raw DZT header**, but the engine bins the
**processed** line. `time_zero` — first in any ordinary preset — crops rows off the front: 49 of
512 on this repo's own files, moving the start from −11.086 ns to −0.476. The cube then demanded
10.6 ns of two-way time that no prepared line had.

Fixed by `SliceEngine.prepared_z_bounds()` — the range every prepared line covers, the
**intersection**, which is what `plan_line` demands — with the dock clamping into it in
`_on_prepared`, before anything asks for a slice.

**Why the suite was green.** The one real-data test that would have caught this documented the
hazard and then excluded `time_zero` from its preset so it could pass:

> No `time_zero`: it crops rows off the front of the radargram, which would shrink the line's own
> `t0_ns` below the header's raw `position_ns` this test seeds `z0` from directly (the dock's own
> `_seed_dz_z_defaults` formula)

A correct diagnosis of a product defect, filed as a test-setup note. This is the single most
useful lesson of the milestone: **a test that avoids the input which breaks the product is worse
than no test, because it looks like coverage.**

### 2. The Slices dock never stayed tabbed with Processing

`initGui()` *did* call `tabifyDockWidget`. QGIS restores its saved window layout **after**
loading plugins and wipes it. Instrumented in a real QGIS 3.44 with a 100 ms polling timer:

| t | what happened |
|---|---|
| 1.40 s | our tab is in place |
| 2.67 s | QGIS restores the saved layout — tab gone, main window resized in the same tick |
| 2.95 s | `initializationCompleted` fires |

Fixed by tabbing from `iface.initializationCompleted`, QGIS's own "startup is over" signal and
the first moment after the restore — never a fixed `QTimer` delay, which would only guess at a
number that varies by machine and profile. A `QTimer.singleShot(0, …)` runs alongside it for the
Plugin-Manager path, where startup is long over and that signal will never fire again. Done once
per profile, keyed in settings, so a user who drags the two apart is not overruled on their next
start.

### 3. The dock forced the whole QGIS window to grow

A dock widget's minimum size is a **hard floor on the main window's**. Four stacked group boxes
plus a `QCheckBox` whose text cannot elide or wrap gave this dock a 556 × 1013 minimum — against
449 × 239 for Processing and 101 × 132 for Survey. Stacked rather than tabbed (defect 2), those
floors *add*, which is why these two were one story.

| | before | after |
|---|---|---|
| Slices dock minimum | 556 × 1013 | **68 × 93** |
| QGIS main window | 1334 × 1440 | **1227 × 686** |

Fixed with a `QScrollArea(widgetResizable=True)` and by moving the residency checkbox's long
wording to its tooltip.

---

## Round 2 — five findings, one of them a crash

Twelve of thirteen steps marked; seven clean.

### W7 — one arrow click killed QGIS

> "These also tick by 1 unit at a time, which is too much. It also leads to cell size going to
> .001 which then crashes qgis because it is too fine a grid."

`cell_spin` spans 0.01–5.0 m but kept Qt's default `singleStep` of **1.0**, so one press of the
down-arrow from the seeded 0.5 m clamped straight to the 0.01 m minimum. Cell count goes as
1/cell²:

| grid | cell | frame | one filled slice |
|---|---|---|---|
| 40 m | 0.5 m | 80 × 80 | negligible |
| 40 m | 0.01 m | 4000 × 4000 | ~1.0 GB |
| 100 m | 0.01 m | 10000 × 10000 | ~6.4 GB |

Streaming is no escape: the **per-slice** array is the problem, not the cube — which is exactly
why the existing budget warning never saw it, since it only ever measured cube bytes.

Three layers, because the trigger and the hazard are separate problems:

1. Every spin steps by a useful increment. The three time spins step by the file's own `dt_ns` —
   one sample per click, the only meaningful increment on a time axis.
2. `cell_spin`'s minimum is raised per grid from `smallest_safe_cell`, so no number of clicks can
   reach an undrawable frame.
3. A `Resolution` arriving from a saved record — which never passed through the spin — is
   **refused** with a message naming a cell size that works.

Refused rather than warned-and-allowed on purpose: §7.4's "warn, do not hard-cap" is about memory
*budgets*, where the fallback is to degrade to streaming. There is no degraded mode for a frame
this size.

### W8 — the profile band, and it was caused by W7

> "If I open the line AFTER I have moved the position slider, the slice's time window isn't drawn
> until I move the position slider again."

`refresh_slice()` emits `window_cleared` on **every** tick that cannot produce a slice — an
exception, or a source that stopped being prepared. That wipes the band, and nothing ever put it
back, because `window_changed` only fires when the window *changes*, and it had not. So after any
failed tick (W7's own cell-size errors, as it happens) the band stayed gone through every line
opened afterwards, until the slider was nudged.

Fixed by re-announcing on `line_opened`, the same gap `_resync_gain_strip` already closes for the
gain strip.

**Worth recording honestly: the first two reproduction attempts passed.** The obvious scenario —
set the window, then open a line — keeps the band fine, in five separate orderings and under a
pixel-level render check. A fix written straight from the report would have targeted the wrong
trigger. Only the clear-between-the-two ordering loses it.

### W6 — the view was correct; the legend was lying

> "Don't know what this is doing. It does look gappy, not sure what legend you're talking about"

The gappiness was correct and deliberate: coverage is never filled, so the binned truth stays
visible under the cosmetic step (§6.4). But the legend read `0 – 15 traces`, and zero is the one
value that view never draws — a cell no line crossed is left **blank**, not coloured at the
bottom of the ramp. A legend naming a scale the picture did not use, on the one view whose entire
job is to be read literally.

Now `1 – 15 traces per cell · blank = no line crossed`, wrapped so it cannot widen the dock. Fill
radius, dz and the coverage toggle each carry the sentence that makes them actionable — all three
are terms of art with no shorter correct name, so renaming was not the fix.

### W5 — fill radius: same step-size defect, plus an opaque label

Covered by the W7 fixes and a tooltip.

### W10 — Temporal Controller

Deferred at the user's own priority. Not investigated.

---

## The spec amendment: §9.3's "live slider"

§9.3 says *"Everything outside Source is a **live slider**"*, and §6.4 says *"the radius is a
slider"*. M11 shipped `QDoubleSpinBox` for all seven, which the walkthrough caught the moment a
human touched it ("It isn't a drag, it's a number with up/down arrows").

Raised as a divergence I should have caught. **The user overruled it, and was right**: a slider
needs pre-determined bounds, and cell size, dz and the z range have none that are not
data-dependent — a slider would either clip a legitimate value or invent a range. The one control
whose bounds the data *does* define exactly, the cube's z extent, already is a slider (the depth
slider). What §9.3 was really asking for there is a **useful increment**, which Qt's `singleStep`
default of 1.0 had silently destroyed.

Recorded in the plan's spec-amendment list as a decision with its reasoning, not left as a silent
divergence.

---

## What the three rounds say about the test suite

Eight defects, none caught by a suite that was green at every point. The recurring shapes:

- **A test that excludes the input which breaks the product** (round 1, defect 1). The comment
  explaining the exclusion was an unfiled bug report.
- **A test that asserts the end state without exercising the mechanism.**
  `test_the_profile_band_follows_the_slice_window` emits `window_changed` directly and never
  opens a line, so it passed on both sides of W8.
- **Data that cannot discriminate.** All ten real DZT files are byte-identical in the sample
  axis, so a real-data test could not tell an intersection from a union — that mutation survived
  until synthetic lines built to disagree were added.
- **Defects only the real application exhibits.** Round 1's defects 2 and 3 are invisible to any
  offscreen harness, because the mechanism is QGIS's own startup sequence and its own dock-area
  layout arithmetic.

Every numeric and structural claim added across the three rounds was mutation-tested: the wrong
implementation was built and confirmed to fail. Twenty-six mutations in total; two equivalent
mutants noted rather than papered over.
