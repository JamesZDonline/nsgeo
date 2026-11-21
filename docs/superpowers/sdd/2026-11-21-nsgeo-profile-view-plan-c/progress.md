# SDD ledger — plan: docs/superpowers/plans/2026-11-21-nsgeo-profile-view-plan-c.md

Spec §4.14 (walkthrough decisions 2026-11-21: Q3 picture 4 with fallback; W1 checkbox; W5 build now — user's answers on the lavish follow-up page). Plan C commit 773e84e. Globals: Plan B's (docs/superpowers/sdd/2026-11-20-nsgeo-profile-view-plan-b/globals.md).

## Pre-flight scan
| Pair / task | Finding |
|---|---|
| T1 / T2 | both edit profile_dock.py: T1 current_radargram/_scale_reference, T2 the toolbar — disjoint |
| T1 / T3 | T3 edits profile_view.py only — disjoint |
| T1 self | bypass rows = input rows unless a later step crops the top; the (n_samples, t0) guard covers that; re-pins listed | clean |
| T2 self | keeps the attribute name and wiring; QCheckBox has setChecked/isChecked/isEnabled/toggled | clean |
| T3 self | expected text uses the drag's actual a, b (the test reads them) | clean |

## Tasks
Task 1: implemented 2664e3b (pushed); review next
Task 1: review dispatched (opus a213e487e3ae505a1, package review-773e84e..2664e3b.diff)
Task 1: review → Needs fixes (F1 ruling: first-row-time guard, spec edited; F2 scale tests; M1 M2 M4 M5); fix dispatched
Task 1: fix c71fa74 (pushed; F1 F2 M1 M2 M4 M5); re-review next
Task 1: re-review (opus afd50abd9b50d39bc) → all addressed, no new breakage. DONE at c71fa74.
  For the final review (minor, non-blocking): pin the zero_ns term of the first-row guard (a later Time zero at sample 0); add cutoff_ns≈0 to test_a_cutoff_after_time_zero_still_draws_the_bypass; _scale_reference docstring "(just result() when there is none)" is stale; test_the_line_shows_only_in_sample_mode_while_selected docstring "on the record it receives" dated; edge: a cutoff end_ns above the line's zero offset puts the cutoff line below the drawn record (no crash).
Task 2: dispatched (BASE c71fa74, implementer a6a31adece1127cc5, sonnet)
Task 2: implemented a388df3; controller review inline (cosmetic, right-sized): placement after colormap/before Difference ✓, wiring kept ✓; tidy 
73f342d: fit-move pin now checks velocity_label instead of the band (vacuous after the move), guide rewrapped. DONE.
Task 3: dispatched (BASE 73f342d, implementer a1e5fc99153012da6, sonnet)
Task 3: implemented 1db1f02 (pushed); controller read the diff (small); no separate task review — covered by the scoped final review. Note: guide line rewrap needed.
Final review (Plan C range 773e84e..1db1f02): dispatched (opus a0695bd138d738ad2); includes Task 3's task-level verdict. Ruling: Task 2 (cosmetic) reviewed inline by the controller, per the right-size rule; Task 3 (10 lines) gets its task verdict inside the final review rather than a separate seat. Cost if wrong: a Task 2/3 defect the final reviewer doesn't look for.
Final review → With fixes: I1 (Task 3 hover order), M1 release repaint, M2 guide wrap, Z1 zero_ns pin, Z2/Z3 docstrings, Z4 cutoff_ns assert; M3 spec notes done by controller (8f1bc46). Ruling: leave cutoff-above-zero edge (clamps) and lost-release stale selection (pre-Plan C). One fix wave dispatched.
Final fix wave: be27cba (pushed; I1 M1 M2 Z1-Z4); scoped re-review next
Final re-review (opus aa17b3da8a7244a36): all addressed, no new Critical/Important. Residual Minor: Z1 test name/docstring inverted (it pins the bypass, not a fallback); spec §4.11 "why not the bypass"/"display limit" unmarked. Controller fixed both (text only) plus the §4.14 ruling's sign (zero_ns ≈ −0.5 ns on the user's lines, so the cut is ~2 rows later, not earlier).
Ruling: the I1 reorder makes a lost left release (pre-Plan C) keep "… m selected" showing off the image; left, under the earlier ruling. Cost if wrong: a stale length after a lost release until the next click.
Ruling: Q5 added to the walkthrough so the user rules on the cutoff-in-bypass behaviour (the task review ruling) themselves.
CI: run 44846964364 on be27cba — success (all jobs incl. plugin-qgis 3.44 and 4.2).
