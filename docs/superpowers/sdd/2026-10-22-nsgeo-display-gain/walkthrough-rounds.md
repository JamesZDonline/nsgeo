# Display gain: walkthrough rounds

The acceptance walkthrough ran in QGIS 3.44 (Linux), in a new profile, `ns_geo_gain`, which was a copy of `ns_geo` linked to this branch. The checks and marks were kept on a claude.ai page with the `db` capability (collection `results`).

## Round 1: build ed92b2b, 2026-10-23

Six of the 24 checks were marked, all passing, none with a note:

- A1: the build opens in the new profile.
- B1: a line without a gain curve looks as before.
- B2: the Display gain slider's tooltip.
- C1: raising the deep point brightens only the deep part, with no AGC in the stack.
- C2: pushing past the limit burns that band out without darkening the rest.
- C3: moving every point right brightens the whole profile.

The other 18 were left unmarked: C4–C7, all of stage D (the strip), all of stage E (line switches, previews, the cutoff), and F1. That includes E1, which checks the final review's fix by hand, and E4, which asked whether the cutoff drag's brightness change is acceptable. The user then said: "I think we're ready for a pull request/merge".

**What actually happened.** The user ran all 24 checks. An internet outage meant only the first six marks were saved. The user's account: "There was nothing mission critical that came up in the full walk and if I discover problems as I use it I'll open up new issues." E4 (the cutoff drag's brightness change) therefore stands as built. The merge went ahead on that basis.
