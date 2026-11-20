# Decision record: the hyperbola tracer (#140) and the Ctrl/Cmd shortcut (#88)

Spec: `docs/superpowers/specs/2026-11-13-nsgeo-hyperbola-tracer-design.md`.
Plan: `docs/superpowers/plans/2026-11-13-nsgeo-hyperbola-tracer.md`.
Built subagent-driven in five tasks, 2026-11-13 to 2026-11-17, with three review rounds.

The working ledger, briefs, reports and review packages quote the author's real fits (site names,
line paths, velocities). The plan keeps those out of the repository, so they are not committed
here. They are retired locally to `.worktrees/_retired-ledgers/nsgeo-hyperbola-tracer/`. This
record keeps the decisions only.

## What was built

- **`nsgeo.hyperbola_trace.trace_hyperbola`** (core, numpy only). It works in five steps:
  1. A coarse-to-fine scan for the strongest hyperbola in a box, on a coherent signed stack.
  2. The band's first strong lobe, chosen once from the traces near the apex.
  3. On each trace, the zero crossing into that lobe, inside a narrow window. No dot jumps a lobe.
  4. Cleaning, then thinning to about 10 dots, apex-nearest first.
  5. A refit of the dots exactly as the panel will fit them, with refusals:
     - the box is too small or too big;
     - no hyperbola, including an apex outside the dots;
     - too faint;
     - too few points;
     - too flat;
     - any `fit_hyperbola` reason, such as v > c.
- **The profile and its dock.**
  - In velocity mode a click places a dot and a drag draws a box.
  - The traced dots replace the working dots. A refusal leaves them and shows its reason in the
    velocity strip's note.
  - Refusals: Migration on, an amplitude transform on, a preview, a cut, a difference view, a line
    with no distance calibration.
- **#88.** Ctrl+click (Cmd+click on a Mac) switches Velocity on, leaves it on and places the dot
  where clicked. Ctrl+drag draws a box. Ctrl+Shift does neither. Shift still picks.
- **Tests.**
  - Planted radargrams built from measured instrument constants (`tests/planted.py`).
  - A local-only harness over the author's 22 saved hand fits, with three kinds of ruling: hand
    fit off (skip), pending (strict xfail), and accepted difference (a per-fit ratio band with a σ
    cap).
  - QGIS-tier tests with real mouse events.

## The author's decisions

- **2026-11-13: the edge.** The tracer follows the zero crossing into the band's first strong lobe,
  the spot the author marks. The first rule tried, 0.2 of the band's peak, sat on a faint
  precursor above the band. The author chose this edge from a side-by-side of their own lines.
- **2026-11-13: one fit was clicked "a level too low".** It is ruled "hand fit off".
- **2026-11-16: keep the leading edge.** An independent migration-focus check put the true
  velocity between the two picks:
  - hand fits read about 4% slow;
  - traced fits read about 5% fast;
  - the cause is the band stretching down the legs.

  The author accepted the difference, so 12 fits carry an accepted ratio band. #195 was filed:
  show migration's velocity beside a traced one.
- **2026-11-17 walkthrough** (20 checks): 13 pass, 1 fail accepted as is, 4 skipped, 2 noted.
  - **Ready to merge.** The author: "The tool works. I can use it multiple times with different
    boxes if I want to refine, and refine by hand if that fails. I think its ready for a merge and
    its one of my favorite additions in a while."
  - **One lobe rule is fine.** On about 5 of 20 fits it isn't the lobe the author clicks, but the
    author wants no lobe control.
  - **Ctrl+click "a little weird".** The author will file an issue later if it needs to change.
    The held-key feedback is not filed.
  - **Busy ground (the one fail).** Boxes there return nonsense hyperbolas or the speed-of-light
    refusal; the author is "comfortable with it as is".
  - **The strip resizes the view.** The panel jumps a little when the velocity strip appears.
  - **Not checked:** Cmd+click on a Mac, the tooltip and guide wording, and the fading leg.

## Rulings (from the ledger, in short)

| Ruling | What was decided |
|---|---|
| R2 | The hand-fit data script makes copied line paths absolute. |
| R3 | The planted noise is anchored to the measured per-trace peak, and edges are read by linear interpolation. |
| R7, R8 | The planted layer and leg-fade constants and the fading-leg calibration are accepted. |
| R9 | The edge definition is the author's call; it went to them with real examples. |
| R10 | A preview refusal uses the existing toast. |
| R11 | Ctrl+click maps the press to data coordinates before the strip resizes the view (a Critical, fixed). The Mac check moved to the walkthrough. |
| R12, R13 | The edge rule is a separate task. Each trace's crossing is locked to the lobe chosen once, in a narrow window, and never takes another lobe. |
| R14, R17 | Accepted differences are a checked per-fit ratio band with a σ cap, not a skip. |
| R15 | Refuse when the fitted apex lies more than about 3 trace spacings outside the dots, and when the moveout to the farthest dot is under about 0.45 of a period ("too flat"). |
| R16, R23, R27 | A fading leg on layered ground: the faint-floor fix failed one real-data bar each way. It stays pinned as a strict xfail; the scan and lobe fixes already shrank it. |
| R18 | The no-jump test checks against the planted truth. |
| R20 | In the repeatability test a refusal is not a disagreement. |
| R22, R26 | The lobe is chosen near the apex (moveout within 0.25 of a period), which makes the choice independent of the box's size. The author confirmed one rule is fine. |
| R24 | The scan keeps coarse apexes a few traces apart on wide boxes and refines from the unclipped step. |
| R25 | Five box sizes in the repeatability test. A discard clears the box note. An uncalibrated line gets friendly copy. |
| R28 | The final re-review's residuals are recorded as limits (spec §14), not fixed. |
| R29 | Main is merged at the merge decision, after the walkthrough. |

## Known limits (spec §14)

- A flat layer just after the apex's edge biases v about 2–3% fast on a third of boxes.
- A fading leg on layered ground reads about 2% slow on planted lines.
- A box holding only the apex and one leg, on layered ground, reads 2–5% fast.
- Rule B ("too flat") is a partial guard on tight layered boxes.
- On the same lobe, a looser box can read 4–5% off a tight one.
- Very wide boxes are limited by the scan's minimum run (a quarter of the box's width) and its
  capped apex grid (beyond about 253 traces).
- In busy ground a box often returns some curve rather than a refusal (walkthrough R3).

## Follow-ups

- #195: migration's velocity beside a traced one.
- Time zero could offer the tracer's own edge rule.
- The limits above, with the candidate faint-floor fix.
- The velocity strip makes the profile jump when it appears.
- Review leftovers: test tightening (the final review's M7 and M8).
