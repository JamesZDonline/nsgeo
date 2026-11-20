# M17a walkthrough results (Checkpoint C2)

Walked by the author on profile `ns_geo_gps` (QGIS 3), 2026-11-17 to 2026-11-18, on the two real GPS
surveys (`with-dzg`, `grid2`). Page: the M17a walkthrough artifact (version 2 added G12 and reworded
G1 and G5 after fix W1).

| Check | Result | Note |
|---|---|---|
| G1 Import the first survey with no grid | pass | Asked what "zigzag turn-arounds visible" meant: badly worded (each line is its own file); reworded in v2. |
| G2 FILE__011 at its walked length | pass | |
| G3 Obstacle lifts | pass | |
| G4 Real dropouts in the second survey | pass | |
| G5 A GPS line's profile | pass | The axis reads "m along line", starting at 0; reworded in v2. |
| G6 Set destagger on the zigzag | pass | |
| G7 Save, close and reopen | skip | Covered by `test_a_gps_line_round_trips_with_identical_positions_without_its_dzg` (core) and G12's save, close and reopen. |
| G8 Add a grid to the GPS-only site | pass | |
| G9 The tape import is unchanged | pass | Question answered: `rtk_gaps` only once a site has GPS lines → fix W1. |
| G10 The Survey panel reads well | pass | Asked what Open does (opens the line in the Profile panel, as a click does) and whether Move to grid and Measure come later (M17b and M17d). |
| G11 QGIS 4 (optional) | skip | CI's qgis/qgis:4.2 job is the Qt 6 check; it had failed since Task 4 (fix W2). |
| G12 rtk_gaps only with GPS lines (new in v2) | pass | |

## Decisions the author made during the walkthrough

Recorded in the spec (`docs/superpowers/specs/2026-11-06-nsgeo-gps-lines-design.md`):

- **Decision 13** (2026-11-16): outlines can have holes; the slices' colour stretch ignores masked cells.
- **C9 revised** (2026-11-16): switching a tape line to GPS is an in-place **Place by GPS**, because removing a
  line drops its processing, velocity override and fits. The import's refusal no longer says "remove it first".
- **Decision 14** (2026-11-17): one **Add data ▾ ▸ GPR…** menu with a Grid / GPS switch; GPS lines always go
  into a grid, existing or new (fitted to the lines' main direction, half a spacing outside the outer lines);
  "GPS available" is noted only in the dialog's Grid mode. Milestones relettered: M17b GPS grids, M17c
  true-distance profiles, M17d outlines with holes and the rest.

## Fixes after the walkthrough

- **W1** (278fa2e, 6d3ecb1): `rtk_gaps` exists only while the site has GPS lines.
- **W2** (1fce783, adad164): two QGIS 4.2 failures — a test helper compared a PyQt6 enum to an int; `rtk_gaps`
  stayed identifiable on QGIS 4 because `flags() & ~LayerFlag.Identifiable` is an int there
  (`qtcompat.without_layer_flag`).
