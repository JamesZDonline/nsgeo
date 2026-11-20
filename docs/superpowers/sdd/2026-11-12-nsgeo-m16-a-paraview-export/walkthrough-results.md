# M16 Plan A walkthrough — results

Run by the author on 2026-11-13 on another machine, on a copy of the Sunnyside site, with the branch at
4a04ee4 (first session) and then b8ec2ed (after the "Down to" fix round). Page:
https://claude.ai/artifact/9FJsin3NSYnsugaQ2EMJkC (14 checks, results in its database).

## Results

| Check | Result | Author's note |
|---|---|---|
| D1 the dialog states the size | fail → fixed → pass | First session: "400 × 320 cells × 1001 depths, 0 – 3.55 m" — the export ignored Grid1's z1 (40 ns) and took the whole record. Fixed by "Down to" (below); re-run after the restart: pass. |
| D2 typed values refresh the size | pass | The added Down to step (20, then 40) confirmed in chat: "worked perfectly". |
| D3 | pass | |
| X1 export and open | pass | |
| X2 stated size against written size | pass | Confirmed in chat: "size looks good". |
| P1 | pass | |
| P2 the isosurface and the box | pass | "I assume there's a way to connect values like this to a slider so I could control it without typing and clicking apply repeatedly?" — answered: Auto Apply, or an Animation View track on the Isosurfaces value; a scene-side slider offered as a follow-up. |
| P3–P5 | pass | |
| R1–R3 | pass | R3 included changing the panel's z1: the export kept its own Down to. |
| R4 the guide's new step | skip | |

## The fix round the walkthrough caused

D1 showed the export had no depth range of its own. The author chose to give it one, the same way as the
3-D cell and depth step (spec decision 8): **Down to**, the export's deepest time, remembered per grid,
starting from the Slices panel's z1 at first use, never following the panel afterwards. Built in
c3b33af/e037125 (with the parked residuals R18 a–c), reviewed (spec ❌: the remembered value went stale
or followed the panel at the record's end), fixed in b8ec2ed, re-reviewed clean. Whole QGIS tier on
b8ec2ed: 2654 passed, 3 skipped.

Deferred: the spin box rounds the record end to 4 decimals, which can cost one extra refill (fixed on the
Plan B branch by rounding the maximum up, Ruling R11 there); a stored "Down to" no longer follows a
lengthened record (decision 8 behaviour).
