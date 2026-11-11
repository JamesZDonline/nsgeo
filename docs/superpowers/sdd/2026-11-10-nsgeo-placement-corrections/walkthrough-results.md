# Walkthrough results — placement corrections (#3, #47)

Run by the user on 2026-11-11, profile `ns_geo_placement`, page https://claude.ai/artifact/UqkaRx9zTNJ4mRQhqyPHQt (db `results`).
Result: 24 of 24 pass. Data: `~/nsgeo-placement-check/` (campus ten, the 60-line with-dzg survey, a copy of the Nashville City Cemetery site).

| Check | Result | Note |
|---|---|---|
| A1 | pass |  |
| A2 | pass |  |
| A3 | pass |  |
| A4 | pass |  |
| B1 | pass |  |
| B2 | pass |  |
| B3 | pass | It just doesn't seem to let me type 0. it goes back to the previous value, I'm not sure where the status line is. But that's ok. the behavior is good |
| B4 | pass |  |
| C1 | pass | Grid 1 depth 14.9-19.7ns/0.6-0.79m |
| C2 | pass | it did shrink, but is still slightly present |
| C3 | pass | With both scale on and with destagger at 0.15 it got worse! but when I set scale to 1 and destagger to 0.15 it got much better. 0.1 seemed a little too little and 0.25 a little too much. |
| C4 | pass |  |
| C5 | pass |  |
| C6 | pass |  |
| D1 | pass |  |
| E1 | pass |  |
| E2 | pass |  |
| F1 | pass |  |
| F2 | pass | With the scaling on it actually was -0.15, positive 0.15 made it worse, but at -0.15 it looks fantastic |
| G1 | pass |  |
| G2 | pass |  |
| G3 | pass |  |
| G4 | pass |  |
| G5 | pass |  |

**Finding:** the destagger a grid needs can change sign once its lines are fitted (C3, F2). Recorded in the guide and in #159 (automatic destagger).
