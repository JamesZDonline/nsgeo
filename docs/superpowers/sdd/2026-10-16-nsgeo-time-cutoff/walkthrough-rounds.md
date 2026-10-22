# Time cutoff — walkthrough rounds

The acceptance walkthrough ran on the user's own lines in QGIS 3.44 (Linux), in a new profile, `ns_geo_cutoff`, which was a copy of `ns_geo` linked to this branch. The checks and marks were kept on a claude.ai page with the `db` capability (collection `results`).

## Round 1: build 0981d9d, 2026-10-22

22 checks passed, none failed, and one was skipped.

- **Skipped: D4,** closing the site with the cutoff selected. Only an automated test covers it (`_cutoff_row` returns -1 once the session is closed).
- **The user's answers to the open questions:**
  - Zoom refitting when switching between the cutoff and another step is acceptable (B4).
  - The drag is fine (B7).
  - The line and the dimming should stay visible while the step is unticked (C2).
  - The display-gain shift between the dimmed and clipped views is acceptable (F2).
- **Changes requested:**
  - B7: "A bounded spinbox for the number might not go amiss".
  - C6: "I'd rather a red notification directly below the number if I put an invalid number in". The user later ruled: "just have it snap to the nearest limit and no need for a note".
  - F1: "magenta line is easy to see, the magenta text is very hard to read".
  - F3: "drop needs values".

## Round 2: build ade0972, 2026-10-22

**What changed:**

- The label is white text on a magenta tag.
- Steps that add without a dialog show as bare names in the Add step menu.
- The cutoff field is a spinbox bounded to the record as it reaches the step, `(t0 + dt, t0 + n*dt)`. A typed value outside it snaps to the nearest limit with no message, and arrow steps are one sample.
- The spinbox ignores the mouse wheel until it has focus.

**What the review found.** A spinbox re-reads its 6-significant-digit display on Return. That silently rewrote dragged cutoffs: on the real HS350 axis, 300 kept samples became 301, and the session went dirty. The rule now (Rulings R10 and R12): a field the user has not really changed reports the exact value it was built from, and never writes.

**Result:** G1–G7 all passed. The user's verdict: "it looks great".
