# M16 Plan D walkthrough: results

The author ran it on this machine with profile `ns_geo_m16d`, which links the plugin to the branch's worktree. The site was a copy of the Sunnyside check site with 186 picks, one cut and no surfaces. The page, with its checks and results in its database, is https://claude.ai/artifact/VkhPWErf6zmJg62JmVWyJH.

- **Round 1** (2026-11-19 evening): branch at 9e2fac8, nine checks.
- **Round 2** (2026-11-20): branch at 0db8e53, after the walls were dropped. Two checks: E2 replaced E1, and G2 offered the guide again.

## Results

| Check | Round 1 | Round 2 | Author's note |
|---|---|---|---|
| S1 A surface from line picks | pass | (stands) | |
| S2 Pick the bowl on a cut | pass | (stands) | |
| S3 Add the cut picks and rebuild | pass | (stands) | |
| S4 A new surface from line and cut picks | pass | (stands) | |
| V1 Cut picks in the 3-D view | pass | (stands) | |
| E1 Export Grid1 with its walls | **fail** | (replaced by E2) | "I don't think the walls are useful. They don't render particularly well and I don't think they add a ton above the cut :/ They also add a lot of extra things to the browser which I'm not sure is useful. Maybe we just scrap that part of this work." |
| E2 Export with picks on a cut, no walls | (new) | pass | |
| C1 Switch Time zero and back | pass | (stands) | |
| D1 Delete the cut | pass | (stands) | |
| G1 The guide | skip | (replaced by G2) | Asked for a toolbar divider and a **3D Analysis** drop-down holding Surface from picks, 3D view and the ParaView export, with ParaView… out of the Slices panel. The author left it open whether it belonged in this branch or a follow-up. |
| G2 The guide, without walls | (new) | skip | Optional. The reviews had checked the guide against the code. |

## After round 1

**The walls were dropped (ruling R20, 0db8e53).**
- Every file the walls commits touched went back to its state at 97aa5fc, before the walls. Those commits are e987486 (core walls and the StructuredGrid writer), 501f0c5 (walls in the export and the scene), e896885 (the walls' amplitude scale and levels) and 463bdf7 (the dialog test).
- The final fix wave's (9e2fac8) wall hunks went with them. The guide and the scene's README kept 9e2fac8's other lines.
- The spec's §5.5 and the plan's header note the drop.
- Check: the diff from 97aa5fc to 0db8e53 holds only 9e2fac8's non-wall files.
- The walls can be brought back from those four commits.

**The 3D Analysis drop-down is a follow-up, #227 (ruling R21).** It moves controls that Plans A–C put in place, so it gets its own branch and walkthrough.

## Follow-ups

- **#227**, toolbar: a 3D Analysis drop-down for Surface from picks, the 3D view and the ParaView export.
- **#228**, Plan D tidy-ups:
  - a cut pick with no distance gets the wrong reason;
  - two parsers for a cut pick's time base;
  - two lost test assertions;
  - a cut-pick outlier leaves the cursor where it was;
  - the `selection_refusal` docstring.

The review findings that only concerned walls went with them.
