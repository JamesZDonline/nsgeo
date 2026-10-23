# SDD ledger — plan: docs/superpowers/plans/2026-10-23-nsgeo-grid-dialog-corners.md

Spec: docs/superpowers/specs/2026-10-23-nsgeo-grid-dialog-corners-design.md (reachable, binding).
Branch nsgeo-grid-dialog, worktree .worktrees/nsgeo-grid-dialog, branch base 21e0b5c (main), plan head dc1a16d.
User chose subagent-driven, 2026-10-23 ("subagent driven sounds good. lets go").

## Setup
- .venv (nsgeo editable → this worktree, verified) and .venv-qgis (--system-site-packages, QGIS 3.44.7) built.
- ruff pinned to 0.17.1 in .venv (pip had pulled 0.17.2); mypy 2.4.0.
- Real data symlinked into packages/nsgeo-core/tests/data/local/ (README.md left tracked, not symlinked).
- Baseline at dc1a16d: core+pure 698 passed / 3 skipped; ruff clean, format clean, mypy clean (34 files).
- Baseline qgis at dc1a16d: 929 passed (7m31s).

Models: implementers sonnet (Task 5 opus: snapping + lifecycle); per-task reviews and scoped re-reviews opus
(user's standing tier rule: reviews → opus); final review opus.

## Pre-flight scan

| Pair / task | Produces → consumes | Found |
|---|---|---|
| T1 → T2 | CORNER_ROLES, corner_frame, rotate_roles | names/signatures match |
| T1 → T3 | roles_from_ring, compass_label; T1 leaves corners_from_polygon, T3 deletes it | consistent |
| T1 → T4 | utm_epsg | consistent |
| T2 → T3 | grid_dialog.py; set_corner, corners_changed, rotate_corners | consistent; T2 removes polygon tab, T3 adds row |
| T2 → T4 | fit_corners; T2's "metric CRS" refusal | T4 narrows it to hand-picked CRS; T2's test sets crs_widget by hand → still passes |
| T2 → T5 | pick_requested, pick_all_requested, set_corner; T2 deletes digitise-flow tests, T5 ports them | consistent; digitise tool unit tests stay until T5 |
| T3 → T4 | fill_from_polygon used in one T4 test | consistent (T3 first) |
| T3 → T5 | pick_polygon_requested, set_polygon_feature | consistent |
| T4 → T5/T6 | `canvas` param; `_real_canvas` (conftest) | consistent after the self-review move to "Shared test geometry" |
| T5 → T6 | pick flow for the "close mid-pick" overlay case; plugin.py | T6 Files omits plugin.py but its step 3 edits clear_if_current — see R3 |
| T1 self | tests vs rules | checked rows (1,2),(1,3),(0,2) → X first; coincide before X; mirrored triple (0,1,3); reversed ring idx [3,2,1,0]; compass 0.38/0.42 — all agree |
| T2 self | Step 1 deletions vs the current file | lists "polygon-tab and use_polygon tests (5)" but there are 6; omits test_corner_fit_fills_origin_azimuth_and_sizes and test_fit_corners_reports_bad_numeric_entry_without_crashing, which break with the new table — see R1, R2 |
| T3 self | tests vs code | consistent (crs_widget set by hand, T3 precedes T4) |
| T4 self | tests vs code | site-first test now discriminates (site 32617 vs project 32616); hand-pick test uses 32619 (would be replaced in auto mode) — consistent |
| T5 self | snap tests vs geometry | `test_a_click_beyond_the_radius_is_free` clicks (416,300), 2 px from the polygon vertex at (414,300) → it would snap to the vertex, not free — see R4 |
| T6 self | Files vs steps | plugin.py edit not listed — R3 |

Ruling: R1 — Task 2 deletes all SIX polygon-tab/use_polygon tests (the plan said five; the sixth is test_use_polygon_success_still_gets_a_visible_crs_refusal, obsolete because Fill no longer sets the grid CRS) — the plan's count was a slip, the intent is "every test of removed UI" — if wrong, a test of removed UI is deleted that should have been ported; Task 3's ports cover the polygon path.
Ruling: R2 — Task 2 also deletes test_corner_fit_fills_origin_azimuth_and_sizes and test_fit_corners_reports_bad_numeric_entry_without_crashing (old local/world columns); their replacements are test_typed_corners_fit_the_grid and test_a_non_number_cell_reports_and_leaves_the_row_empty — the old tests drive columns that no longer exist — if wrong, nothing: both behaviours stay pinned by the replacements.
Ruling: R3 — Task 6 may edit plugin.py (clear_if_current disposes the overlay; passing anything else the overlay needs) — its step 3 requires it; the Files list omitted it — if wrong, a one-line scope widening.
Ruling: R4 — Task 5's free-click test clicks (384, 300) instead of (416, 300): G4 is 16 px away and the polygon vertex at (414,300) is 30 px away, so nothing is in range — (416,300) is 2 px from that vertex and would snap — if wrong, nothing: the 12 px boundary is still tested from the other side.

## Tasks
Task 1: dispatched (sonnet), BASE dc1a16d, implementer a3160289c9c5af6d9
Task 1: implementer DONE cae096a (core+pure 746/3); review dispatched (opus)
Task 1: review (opus) — Needs fixes: I1 tie rule inverted on clockwise rings (lookup.py:422-428); I2 plan-mandated: four corners in crossed order give "lie in a line" (exact) or a fitted bad frame (noisy).
Ruling: R5 — crossed four-corner orders are refused: with four rows, mixed signs among the four consecutive-triple signed areas → ValueError("these corners are out of order: check which row each corner is in"), checked before the collinear check — spec §6 anti-goal "a convincing fit on wrong numbers" and C14's intent (a wrong correspondence is refused, not fitted) cover a crossed set as much as a mirrored one; Z-order entry (origin, +X, +Y, +X+Y) is a plausible user slip — if wrong, a user with a genuinely concave four-corner set gets a refusal and must fix a row; costs one message.
Task 1: minor (deferred): collinear threshold uses largest pairwise distance, comment says "largest edge" (lookup.py:388 vs :323).
Task 1: minor (deferred): some docstrings omit their rule (utm_epsg zone formula, compass_label sectors, corner_frame "needed axis").
Task 1: minor (deferred): tie tolerance 1e-9 is an unnamed literal (lookup.py:427).
Task 1: minor (deferred): rotate_roles silently accepts lengths other than four.
Task 1: minor (deferred): a corner duplicated onto its diagonal reports "lie in a line", not "coincide" (follows the brief).
Task 1: fix round 1/5 (2 addressed, 0 open — tie to lower vertex on any winding; crossed corners refused; commits cae096a..fe2ea5a). Re-review (opus) verified the new clockwise test fails on the old loop.
Task 1: minor (deferred): four float-collinear corners usually report "out of order" not "in a line" — the crossed check's sign test has no zero tolerance (lookup.py:397-403); suggested |t| <= _DEGENERATE_AREA*spread**2 counts as no sign.
Task 1: minor (deferred, pre-existing in this task's code): _signed_area (lookup.py:348) uses uncentred coordinates; at UTM magnitudes rounding (~1e-4 m^2) exceeds the in-a-line threshold, so float-collinear corners at UTM scale can be fitted (14/200 in a probe). Centre on world.mean() first.
Task 1: complete (commits dc1a16d..fe2ea5a, review clean after 1 fix round; verified 752/3, ruff, format, mypy clean)
Task 2: dispatched (sonnet), BASE fe2ea5a, implementer a2bb32e31253786d8 (R1, R2 carried)
Task 2: PAUSED 2026-10-23T06:04:40Z at the user's request ("pause for 1 hour and then continue working") — implementer a2bb32e31253786d8 stopped mid-task with UNCOMMITTED work in the worktree (plugin.py, grid_dialog.py, test_no_orphan_signals.py, test_plugin_grid_dialog.py; +643/-930). Its last note: 'Two failures in core/pure — look.' On resume: SendMessage the same implementer to continue from the worktree as it stands; do not discard the changes.
Task 2: RESUMED 2026-10-23T07:04:48Z after the hour's pause; worktree changes intact
Task 2: implementer DONE_WITH_CONCERNS 80e3c86 (qgis 923, core+pure 752/3, excepthook check clean); concerns: row change clears fit_status + measured size; KNOWN_UNCONSUMED entries added for Task 5 to revisit
Task 2: review (opus) — Needs fixes: I1 typed-state rules for the dialog's own writes unpinned (two mutants survive: Fit/Rotate/Use-these writes counted typed; Rotate not swapping _typed); I2 row changes clear fit_status + _measured (contradicts C13 and measured_size() "None before any Fit"); I3 half-filled row never named (Review Focus #4); ⚠️ spec §4.1 "not-square caution" has no owner.
Ruling: R6 — fit_status keeps the last Fit's line (RMS or refusal) and _measured survives row changes; a newer cell-entry or transform error replaces the line on screen, and the next successful edit / set_corner brings the last Fit's line back; only Clear clears both; Rotate swaps _measured with the sizes; a Corners-in change clears nothing — C13 ("the status line's RMS stays the last Fit's") and the brief's measured_size() contract — if wrong, a stale RMS line shows after edits until Fit is pressed, which C1/C13 intend.
Ruling: R7 — a half-filled row (one coordinate cell filled) is named on the edit ("<role>: needs both coordinates") and makes Fit refuse ("<role> has only one coordinate: fill both or clear it") rather than silently fitting the other rows — Review Focus #4 and the §6 anti-goal (a fit that silently drops a corner the user meant is a convincing fit on the wrong input) — if wrong, a user must clear a half-typed row before fitting; one extra click.
Ruling: R8 — the RMS line keeps a short not-square note when the displayed RMS is not 0.000: "rigid fit RMS 0.090 m from 3 corners · not quite square: see off by"; the mirrored half of the old caution is gone because C14 now refuses mirrored sets — spec §4.1 names the caution; C13's live off-by column is what it points to — if wrong, wording only.
Ruling: R9 — _select_sole_feature (deleted in 80e3c86) is recovered by Task 3 from fe2ea5a and retargeted to the new combos, as Task 3's brief already says to reuse it; not a Task 2 fix item — if wrong, nothing: Task 3 needs it and will have it.
Task 2: minor (deferred → carried to Task 4): off-by blanks only on a missing authid (grid_dialog.py:556); it should blank unless the grid CRS is usable (metres + scale) — Task 4 builds that predicate and must use it here and for the §4.8 preview.
Task 2: minor (deferred): off-by turns a QgsCsException into blank offsets with no message (grid_dialog.py:564) — at least a comment.
Task 2: minor (deferred → Task 5 sweep): stale digitise comments at grid_dialog.py:646 and plugin.py:23, :376, :1121.
Task 2: minor (deferred → Task 5 brief): KNOWN_UNCONSUMED in test_no_orphan_signals.py now holds generic names (cancelled, points_picked) and pins pick_requested 3/2 — Task 5 must revisit when it wires/removes them.
Task 2: minor (deferred): Rotate and a Corners-in change rewrite every row and drop a half-typed row's lone number silently.
Task 2: minor (deferred): an invalid "Corners in" CRS returns without reverting the widget (grid_dialog.py:407), so widget and _prev_corners_crs fall out of step (hard to reach).
Task 2: minor (deferred): flag-on/try/finally/flag-off repeated 7 times (_filling, _sizing) — a context manager would shrink it; grid_dialog.py grew 558→713 lines.
Task 2: minor (deferred): LOCAL constant in the test file is unused.
Task 2: fix round 1/5 (3 addressed + R8, 0 open — typed-state tests pinned with mutants; last Fit line + _measured survive row changes; half rows refused; not-square note; commits 80e3c86..fa73755)
Task 2: minor (deferred): test step at test_plugin_grid_dialog.py:1042 is vacuous (same text → no itemChanged); _measured surviving a cell edit / set_corner is unpinned.
Task 2: minor (deferred): _half_filled_row's role-order tie-break untested.
Task 2: minor (deferred, FINAL-REVIEW CANDIDATE): a row whose text doesn't parse (e.g. "518204,112") is dropped silently at Fit — same anti-goal R7 closed for half rows; Fit should probably refuse when any row holds unparsed text.
Task 2: minor (deferred): Rotate / Corners-in rewrite rows and erase half-typed or unparsed text with no message.
Task 2: complete (commits fe2ea5a..fa73755, review clean after 1 fix round; qgis 927, core+pure 752/3)
Task 3: dispatched (sonnet), BASE fa73755, implementer ad77bf35502d6a022 (R9 carried; R6 status rule carried; partial-fill atomicity asked)
Task 3: implementer DONE 7014906 (grid file 59, qgis 939, core+pure 748/3, excepthook clean); concerns: compass centre = vertex mean; Fill emits corners_changed 4x
Task 3: review (opus) — Approved, spec ✅, no Critical/Important.
Task 3: minor (deferred): by_plane lookup (grid_dialog.py:563) is load-bearing (idx indexes the CLEANED ring) but uncommented and untested at dialog level; v<i> labels number the cleaned ring.
Task 3: minor (deferred): compass centre is the vertex mean, not the area centroid (spec §4.6 says centroid; same for parallelograms).
Task 3: minor (deferred, FINAL-REVIEW CANDIDATE): a layer with an invalid/unknown CRS is copied raw with no message (QgsCoordinateTransform from an invalid CRS is identity); same gap in set_corner — UTM numbers into lon/lat rows, can even mirror roles. Refuse when not crs.isValid().
Task 3: minor (deferred → Task 5 brief): chosen_polygon/_fill_from_polygon take the layer from layer_combo and the fid from feature_picker; if layer_combo.setLayer refuses, they disagree — read feature_picker.layer().
Task 3: minor (deferred): _fill_from_polygon repeats chosen_polygon's lookup steps.
Task 3: minor (deferred): no test pins R6 for Fill errors.
Task 3: minor (deferred): test nits — wrong "long thin site" comment (test :1175), unused plan_layer fixture (:1209), function-local import math (:1188).
Task 3: minor (deferred → Task 6): corners_changed fires 4x per Fill, 3 with mixed rows — Task 6's overlay redraws on each.
Task 3: minor (deferred): pre-existing shutdown noise "QBasicTimer::start: QBasicTimer can only be used with threads started with QThread" x6 with -s.
Task 3: complete (commits fa73755..7014906, review clean)
Task 4: dispatched (sonnet), BASE 7014906, implementer a62885bcbb0c1b53d (Task 2 off-by-usable minor carried; _real_canvas extent note)
Task 4: implementer DONE 57db966 (grid file 70, qgis 950, core+pure 748/3, excepthook clean); concerns noted in report (no-canvas note only when project CRS unusable; failed hand-pick reverts; non-metre source keeps azimuth; auto switch stays if Fit fails)
Task 4: review (opus) — Needs fixes: I1 a hand-pick round trip through a non-metre CRS moves/rotates the grid silently (UTM16→4326→UTM16: 36.7 m, +2.41°; via EPSG:2264: +4.62°), causes: 3-decimal origin spinbox in degrees, and an azimuth rule applied one way only; test_off_by_is_blank... dodges it by resetting the origin.
Ruling: R10 — the dialog keeps a full-precision ground anchor (CRS, origin, azimuth) in the last metric CRS the grid was in; it is refreshed whenever origin/azimuth are set (Fit, a conversion, a hand edit) while the grid CRS is in metres. A hand pick converts FROM the anchor: the origin is transformed, and the azimuth is the bearing (in the target CRS's own axes) between the transformed origin and the transformed point 100 m along +Y measured in the anchor's metric CRS. A hand edit of origin/azimuth while the grid CRS is NOT in metres drops the anchor (the user's typed numbers then win, converted best-effort as today). Spec §4.4's "100 m along +Y" is read as 100 ground metres in the anchor's CRS — §4.4 is silent for non-metre CRSs and C11 ("keeps the grid where it is on the ground") is the binding intent — if wrong, a user who hand-edits numbers in a degree CRS and switches back gets best-effort conversion; nothing silent otherwise.
Task 4: minor (deferred, FINAL-REVIEW CANDIDATE): _apply_auto_crs discards _convert_grid's error (grid_dialog.py:917); if the following Fit also fails, the widget shows the new CRS over old-CRS numbers silently (§4.5).
Task 4: minor (deferred, FINAL-REVIEW CANDIDATE): _project_reason has no "outside" branch (:883-892) → false hint "is off by 0.0% here".
Task 4: minor (deferred): a failed hand pick's _crs_message lingers until the next hand pick, even across an automatic switch at Fit (:975-991).
Task 4: minor (deferred): _on_grid_crs_changed's catch-all can leave _crs_auto cleared with _grid_crs/origin stale (:990-991).
Task 4: minor (deferred, FINAL-REVIEW CANDIDATE): no test pins the no-canvas + unusable project → Fit → UTM path (the hint's promise); test_a_4326_polygon... already has 32616 from the canvas.
Task 4: minor (deferred → Tasks 5/6 briefs): _real_canvas's 1 m/px guard uses exact float equality (conftest.py:148) — a non-representable extent would skip the assertion silently.
Task 4: minor (deferred): nits — _site_extent docstring "800 x 600 m" for the 4326 box; three → EPSG:4326 transform builders; empty authid in the conversion error for a custom CRS.
Task 4: fix round 1/5 (1 addressed, 1 open — anchor round trips exact incl. multi-hop; OPEN: fallback (no anchor) still converts azimuth one way only: UTM16→2264, edit origin, back → +4.62°; via 4326 nudge-and-undo → 36.7 m, +2.41°; commits 57db966..18c3dd9)
Ruling: R11 (refines R10) — (a) the fallback conversion applies the same chord rule from ANY source CRS: step 100 source units along +Y for a linear CRS, 1e-3° for a geographic one; the one-way metres-only rule goes; (b) a hand edit while the grid CRS is not in metres no longer drops the whole anchor: it re-derives only the edited part — an origin edit transforms the boxes' origin into the anchor's CRS, an azimuth edit chord-converts the boxes' azimuth into the anchor's CRS — and the other part keeps full precision — the re-review measured the "best-effort" fallback rotating 4.62° from a feet CRS that holds 0.001° (so the rotation is the rule, not precision), and an azimuth-only nudge dropping the origin to 3-decimal degrees (36.7 m) — if wrong, an edit made in a degree CRS still carries that CRS's display precision into the edited part only.
Task 4: minor (deferred): origin spin boxes keep 3 decimals when the grid CRS is geographic (~100 m), so typing a lon/lat origin there is useless (pre-existing; the CRS is refused anyway).
Task 4: minor (deferred): the off-by test's new comment (test :1446) claims a round-trip guarantee the test does not assert.
Task 4: fix round 2/5 (2 addressed, 0 open — chord rule from any source; partial anchor re-derivation; commits 18c3dd9..23da978). Re-review probes: feet case 10.000° (was 14.620), all round trips 0.0 m / 0.0°.
Task 4: minor (deferred): stale comments — grid_dialog.py:141-144 says a non-metric hand edit "drops" the anchor; _convert_grid docstring (949-953) says "100 m along +Y".
Task 4: minor (deferred): an origin edit in a degree CRS re-derives the WHOLE origin from 3-decimal boxes, so the untouched axis snaps (−33.1 m probe); refinement: replace only the edited axis.
Task 4: minor (deferred, QUESTION FOR FINAL REVIEW): an azimuth shown/typed in a geographic grid CRS is a bearing in lon/lat degree space (~2° off a ground bearing at 36°N); only reachable when the grid CRS is hand-picked geographic (refused) — spec silent on what an azimuth in a geographic CRS means.
Task 4: minor (deferred): a transform failure on a non-metric origin edit drops the anchor with no message.
Task 4: complete (commits 7014906..23da978, review clean after 2 fix rounds; qgis 957, core+pure 748/3)
Task 5: dispatched (opus — snapping + lifecycle), BASE 23da978, implementer a1c6486d788ad65c6 (R4 carried; Task 3 layer/fid minor, Task 4 _real_canvas approx minor, orphan-signal list, stale digitise comments carried)
Task 5: implementer DONE_WITH_CONCERNS 2e1d1db (tool+dialog 111, qgis 991, core+pure 748/3; 14/15 lifecycle mutants killed); deviations: fid as qint64, extra failed(str) signal, set_polygon_feature -> bool, snap reuse requires unchanged view, refused conversion ends pick, canvas focus on start
Task 5: review (opus) — Approved, spec ✅, all seven deviations judged sound, no Critical/Important.
Task 5: minor (deferred): polygon pick's right-click-cancels wiring (plugin.py:1405) untested.
Task 5: minor (deferred): a polygon-mode click on no polygon does nothing and says nothing (pick_tool.py:261-265).
Task 5: minor (deferred): polygon "topmost" = last of getFeatures(), not draw order; renderer rules and layer scale ranges ignored (point snapping too).
Task 5: minor (deferred, FINAL-REVIEW CANDIDATE): a double-click during Pick all fills two consecutive corners with the same point (two releases); Fit then refuses "coincide", so no data damage — ignore a release on the last accepted pixel within the double-click interval, or file it.
Task 5: minor (deferred): each pick builds a fresh QgsMapCanvasSnappingUtils → synchronous index rebuild per pick on large layers (walkthrough check).
Task 5: minor (deferred): nits — set_polygon_feature compares layers by `is` (grid_dialog.py:539), deactivate()'s super()/emits outside the try, plugin.py now 1653 lines (pick-flow class a later extraction).
Task 5: ⚠️ CI-only: QgsMapToPixel.__eq__ value-based on QGIS 3.40 / 4.2 (pick_tool.py:266-268); Esc convention and "qint64" signal type on Qt6 — CI's 3.40/3.44/4.2 matrix confirms.
Task 5: complete (commits 23da978..2e1d1db, review clean; qgis 991, core+pure 748/3)
Ruling: R12 — Task 6's `git grep -i digitis` check is scoped to user-facing text (docs/guide, README.md, nsgeo_qgis/metadata.txt) and must return only metadata.txt's 0.1.0 changelog line; the verb uses in layers.py and map_link.py comments are unrelated code comments — the spec §7 rule is "every mention of Digitise on map from user-facing text" — if wrong, an unrelated code comment keeps the word "digitising".
Task 6: dispatched (sonnet), BASE 2e1d1db, implementer ae850ecf6f4a4ae51 (R3, R12 carried; overlay must share Task 4's usable predicate; corners_changed off KNOWN_UNCONSUMED)
Task 6: implementer DONE dfe0f49 (dialog file 115, qgis 1012, core+pure 748/3); concern: test_a_dialog_closed_mid_pick_leaves_no_canvas_items now expects baseline-1 (baseline included the overlay)
Task 6: review (opus) — Needs fixes: I1 a failed overlay transform (QgsCsException, and the non-finite branch) hides the element with no message (grid_dialog.py:306-321), against spec §4.5. Changed Task 5 test (baseline-1) judged sound.
Ruling: R13 — the overlay message rides R6's status-line rule: failures are collected per refresh into ONE transient message on fit_status (e.g. "the map cannot show the +X corner in EPSG:xxxx"), never written to _fit_line; a later refresh with no failures restores the last Fit's line if an overlay message is showing; all three payloads (corners, polygon, grid) are computed before any is applied, so an exception cannot leave the outline and "off by" disagreeing (folds the coupled half of review Minor 1 into the fix) — §4.5 "never swallowed silently" and R6 — if wrong, an overlay message can briefly cover the Fit line; Fit's line returns on the next clean refresh.
Task 6: minor (deferred): overlay created first in __init__ (grid_dialog.py:137); if a later part of __init__ raises, the item is orphaned on the canvas — create it in _wire_overlay instead.
Task 6: minor (deferred): tag_text guesses polygon sources by prefix (grid_overlay.py:37-41); a snapped feature named "v3" would read as a vertex — match ^v\d+ [NSEW]{1,2}$ or carry the kind.
Task 6: minor (deferred): ring-reading duplicated between _chosen_ring (:323-334) and _fill_from_polygon (:688-695).
Task 6: minor (deferred): chosen_polygon() calls layer.getFeature() on every refresh (every spin step) — cache the ring on featureChanged/layerChanged.
Task 6: minor (deferred): boundingRect/updatePosition catch only RuntimeError; _dispose_overlay and clear_if_current's new body unguarded.
Task 6: minor (deferred): tests — "ok" case of test_overlay_leaves_nothing_behind never unloads its plugin (leaks into later tests); _close's dead parameter + non-strict zip; paint-failure test doesn't assert the log entry; Task 5 test's baseline-1 should say what it measures.
Task 6: minor (deferred, FINAL-REVIEW CANDIDATE — user docs): guide :168 "and then to a vertex" → "or, failing that"; :173 bolds Layer/Feature controls that have no labels; :178 Rotate "round the polygon" (it works however rows were filled; sizes swap too); :140 "set the project's CRS first" misleading (dialog CRS box; site grids outrank the project).
Task 6: minor (deferred → WALKTHROUGH): overlay look differs from the chosen mock-up — #ff00ff/#0050ff vs mock-up #c2185b/#2f6fb2 (white on #ff00ff low contrast), filled r=4 dots vs hollow r=8 rings, open-V arrowhead vs filled triangle. Cosmetic; decide on real imagery in the walkthrough.
Task 6: fix 071d12b landed (report evidence: dialog file 118, qgis 1015, core+pure 748/3); re-review dispatched (opus)
Task 6: fix round 1/5 (1 addressed, 1 new open — R13 reporting in place; NEW Important: a persistent overlay failure overwrites the Corners-in conversion error in the same emission (grid_dialog.py:397 vs :635) and takes over the status line on every refresh, defeating R6's restore; commits dfe0f49..071d12b)
Ruling: R14 (refines R13) — the overlay writes fit_status only when its message CHANGES (a repeat of the already-reported failure leaves the label alone); the except branch's "could not draw the map overlay: …" is recorded as the overlay's message too, so a clean refresh restores the Fit line after it; the all-or-nothing test must fail against apply-as-you-go code — R13's intent (report once, never swallow) and R6 (the Fit line returns on a good change) — if wrong, a failure that persists unchanged is reported once, not on every refresh.
Task 6: minor (deferred): _on_corners_crs_changed (:629-631) catches only QgsCsException; a non-finite PROJ result is accepted into _corners.
Task 6: minor (deferred): an empty authid (ad-hoc custom canvas CRS) gives "…in " with nothing after it; same pattern across the dialog's messages.
Task 6: fix round 2 landed bd668a1 (dialog file 121, qgis 1018, core+pure 748/3; bite check 3 tests fail on reverted code); re-review dispatched (opus)
Task 6: fix round 2/5 (4 addressed, 0 open — dedup'd overlay message; except-branch message recorded; drawing-failure test bites; commits 071d12b..bd668a1)
Task 6: minor (deferred, FINAL-REVIEW CANDIDATE): _overlay_message is recorded when written, not when seen — fit_corners (:826 then :842), _on_cell_edited (:619 then :621/:623) and rotate_corners (:674 then :683) write the overlay message then overwrite it in the same handler, so a NEW failure first appearing there is never visible while it persists (narrow; corners usually already reported).
Task 6: minor (deferred): the "good row change" step in test_a_persistent_overlay_failure_does_not_replace_the_fit_line (:2302) retypes identical text → no itemChanged → vacuous; R14's "a good cell edit brings the Fit line back" clause untested.
Task 6: minor (deferred): the _refresh_derived half of the overwrite finding has no test of its own.
Task 6: complete (commits 2e1d1db..bd668a1, review clean after 2 fix rounds; qgis 1018, core+pure 748/3)
FINAL: whole-branch review dispatched (opus) over 21e0b5c..bd668a1 (16 commits, 18 files, +5384/-1303); reviewer told to triage every deferred minor and the FINAL-REVIEW CANDIDATE lines individually
FINAL review (opus): Ready to merge "With fixes". No Critical. I1 degrees typed as metres → "RMS 0.000", OK enabled (existing grid would move ~4000 km); Fill from a CRS-less layer the same. I2 unparsed row dropped silently at Fit. Minors M1 guide errors, M2 "outside" branch, M3 stale comments, M4 refused Fit still switches auto CRS, M5 metres under lon/lat, M6 misleading site-CRS note, M7 test hygiene. Probes at scratchpad/probes/.
Ruling: R15 — Fit refuses any measured size below MIN_MEASURED_SIZE = 0.1 m with a message naming Corners in; Fill refuses a layer with an invalid CRS — spec §6 first anti-goal (a convincing fit on wrong numbers), reproduced — if wrong, a genuine grid under 10 cm can't be fitted (no GPR grid is that small).
Ruling: R16 — Fit refuses when any row has text that did not parse, naming the row and the text (generalises R7) — Review Focus #4 and §6 — if wrong, a user must fix or clear a bad cell before fitting.
Ruling: R17 — a refused Fit undoes an automatic CRS switch made in that same Fit (CRS, origin, azimuth, anchor restored), and _apply_auto_crs records its conversion error instead of discarding it; a successful automatic switch clears a stale hand-pick message — §4.2 step 4 "nothing changed" and §4.5 — if wrong, a refused Fit leaves the CRS as before rather than pre-switched; Fit re-decides next time anyway.
Ruling: R18 — the fix wave also takes M1 (guide), M2 ("outside" hint), M3 + _signed_area centring, M5 (|lat|>90 → "these are not longitudes and latitudes"), M6 (site-CRS note only when it differs from the project's), M7 (test hygiene) — each a few lines, all in files the wave touches anyway — if wrong, a slightly larger wave.
Ruling: R19 (declined-to-judge items) — (1) "usable" stays a local scale test as §4.4 defines it (an area-of-use check would contradict C10); (2) Rotate on a non-square grid → walkthrough; (3) comma decimals stay refused (Review Focus #4) now that Fit names the row; (4) nsgeo's own grids/marks/picks layers taking part in picks → walkthrough; (5) dialog shown+raised but not activated after a pick → walkthrough (Windows focus); (6) synchronous snap index per pick → walkthrough on the largest layer; (7) overlay colours → walkthrough; (8) no 3.40 qgis test tier in CI → pre-existing, out of scope; (9) nsgeo-core fit.py docstring "on-map digitising" → core is off limits and not user-facing; leave — each is either spec-defined, a walkthrough check, or outside this branch — if wrong, a walkthrough item becomes an issue.
Deferred minors left (final triage: leave/file): double-click in Pick all (Fit refuses "coincide"); overlay message recorded-when-written; Rotate/Corners-in erase half-typed text; topmost polygon not draw order; per-pick snap index; R13 PostGIS/WFS getFeature per refresh; the rest per the final review's grouped triage.
FINAL: fix wave dispatched (sonnet) from final-fix-brief.md, FIX_BASE bd668a1
FINAL: fix wave DONE 6ef2762 (dialog file 131, qgis 1028, core+pure 749/3; each new test failed on bd668a1); scoped re-review dispatched (opus)
FINAL: fix wave re-review (opus) — all F1–F9 ADDRESSED (probes P1, P3, P7a/b/c, P8c re-run on 6ef2762; probe4 cases A–J), no new Critical/Important.
Ruling: R20 (residuals at the end of the single fix wave, parked) — (a) on the automatic path _apply_auto_crs stores "could not convert the grid into X; kept Y" while the widget already shows X — not visible to users (path runs only in Fit; success clears it, refusal restores the old message) — park; (b) a refusal line written before _restore_grid could in theory be covered by an overlay message if the switch changed what the overlay can draw — not reproduced — park; (c) F5's test calls _project_reason directly though _choose_crs(QgsPointXY(3,0)) reaches it — test gap, park; (d) guide says "only centimetres apart" (limit 10 cm) and omits the "not longitudes and latitudes" refusal — park; (e) a failed hand-pick message survives a successful Fit that lands on the same CRS (literally true) — park — none is load-bearing and the single-fix-wave rule allows no second wave; they go to the user with the walkthrough and to issues — if wrong, a stale or slightly wrong hint text in rare paths.
FINAL: complete — branch 21e0b5c..6ef2762; verified by the fix wave: qgis 1028 passed, core+pure 749 passed / 3 skipped, ruff + format + mypy clean, digitis grep clean.
