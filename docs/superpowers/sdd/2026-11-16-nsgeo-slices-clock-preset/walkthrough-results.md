# Session B walkthrough results

Page: https://claude.ai/artifact/CbuQJrHdf6hkbKGcCrELrF (db collection `results`). Profile `ns_geo_clock`, sandbox `~/nsgeo-clock-walk/` (copies of the campus and GPS surveys). Run by the author 2026-11-17/18 on 4a7964c.

| Check | Result | Author's note |
|---|---|---|
| R1 a new cube comes back as it was | pass | |
| R2 a cube from before 0.4.0 moves by the median line zero (+0.48 ns) | pass | |
| R3 a preset that gained Time zero | pass | |
| R4 a preset that lost Time zero (−0.48 ns) | pass | |
| R5 an edit takes the note down | pass | |
| R6 saving takes the note down; the saved cube keeps its clock | pass | |
| G1 the GPS site's old cube moves by +1.34 ns | pass | Opening a site should zoom to the site's extent; the map stayed on the closed campus grid. → filed #205 |
| E1 saving a preset while the restore prepares keeps the shift | pass | Round 1 unmarked: steps 1–2 and "same as G1" were unclear; the page was reworded (version 2), then it passed. |
| S1 switching grid while a restore prepares carries nothing over | pass | |
| S2 opening another survey during a restore carries no palette over | pass | Could not get through the "are you sure" dialogs and the file picker before the preparation finished, so the hazard window was not reached by hand (the unit test covers it). Nothing carried over. |
| W1 closing from Whole site: the next survey starts at its first slice | pass | |
| W2 closing from This grid: the same | pass | |
| F1 the fallback grid opens on Whole site's preset | pass | |
