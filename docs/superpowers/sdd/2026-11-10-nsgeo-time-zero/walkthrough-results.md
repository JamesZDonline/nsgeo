# Walkthrough results — time zero (#97)

Run by the user on 2026-11-11, profile `ns_geo_time_zero`, page https://claude.ai/artifact/TgsSVMT8TFmjbVvc4nUgqx (db `results`).
Result: 11 of 11 pass.

| Check | What | Result | Note |
|---|---|---|---|
| P1 | Adding Time zero makes the top row read 0 ns | pass |  |
| P2 | A pick made before the step stays on its reflection | pass |  |
| P3 | A new threshold keeps picks on their reflections | pass |  |
| P4 | A cutoff placed before Time zero lands where you drop it | pass |  |
| F1 | A saved fit follows the line's time zero | pass |  |
| F2 | Without the step, the fit strip names the first break | pass |  |
| S1 | A cube built with Time zero starts at 0 ns | pass |  |
| S2 | A site with grids on different clocks warns | pass | no only in its tooltip |
| S3 | Exported GeoTIFFs record their clock | pass |  |
| O1 | An old project opens with everything where it was | pass |  |
| O2 | An old saved cube comes back at the depths it showed | pass |  |

**Finding:** at the usual dock width the mixed-clock warning (S2) can be read only in the site note's tooltip. Filed as #163 item 1, alongside #157 item 5.

Follow-ups: #162 (three restore paths that can still land a cube on the wrong clock) and #163.
