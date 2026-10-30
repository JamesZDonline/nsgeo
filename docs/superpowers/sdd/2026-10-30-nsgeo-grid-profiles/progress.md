# SDD ledger — plan: docs/superpowers/plans/2026-10-30-nsgeo-grid-profiles.md

Spec: none as a file — the plan's "Design (approved in chat, 2026-10-30)" section is the spec (user approved in chat; issue #67 is the original request, plan wins where they differ).
Branch nsgeo-grid-profiles, worktree .worktrees/nsgeo-grid-profiles, off main 7069959. Baselines: core+pure 808 passed / 3 skipped; qgis 1165 passed (~9 min).
Models (user's standing rule): implementers sonnet, reviews opus, quick fixes haiku.

## Pre-flight scan

| Pair / task | Produces vs consumes | Found |
|---|---|---|
| T1 -> T2 | T1: ViewTransform(mirrored, bounds, trace_bounds, trace_at, traces_between, target_span, one_to_one, clipped source_rect); ruler.py(trace_units_at, metres_at, is_reversed, Ruler, bounds_on). T2 uses all of them in set_axes/window_m/set_window_m/ticks/gestures/paint | names and signatures match |
| T1 -> T3 | T1 moves _trace_to_metres/_metres_to_trace out of profile_dock.py (renamed public in ruler.py); T3 edits profile_dock.py again and uses ruler_for, Ruler.key | sequential edits to one file, no clash |
| T2 -> T3 | T2: set_axes(..., distance_along=None, ruler=None) 6th positional, .ruler, window_m(), set_window_m(lo,hi,tlo,thi). T3 calls exactly these | match |
| T1 self | 6 ruler tests + 12 VT tests = the "rises by 18" claim; test_bounds_must_be_finite_and_ordered uses match="bounds" for (0, inf) -> the existing finite-axes check would fire first with a message lacking "bounds" | conflict inside T1 -> Ruling R1 |
| T2 self | fixture numbers checked: bounds (-59.5, 300.5), data x~194..581, blank x=20/40/120 are traces >199; blank-window test metres (-0.9,-0.5) -> traces 270.5..294.5 all blank; ticks at fit -1..5 | consistent; file lacks _local/LEFT/SHIFT helpers -> plan already says add them |
| T3 self | ruler lo -239/60-1/120, hold rules 1-4, grid-resize test relies on _on_geometry_changed; fallout rule for old fixtures | consistent |
| Global | ruler.py imports core Grid only (allowed); paint keeps try/finally; mirroring is a painter transform | no conflicts |

Ruling R1: ViewTransform.__post_init__ validates `bounds` (finite, lo < hi) BEFORE the existing finite-axes check, so a bad bounds always raises a ValueError naming `bounds` — the plan's own test needs this order — costs nothing if wrong (message order only).

## Tasks
Task 1: dispatched (base a44b9e1, implementer sonnet)
Task 1: implementer DONE at 2f957f4 (826/3 core+pure, lint/types clean, velocity_fit 51); review dispatched (opus) on review-a44b9e1..2f957f4.diff. Note: ruler.py imports Grid via nsgeo.geometry (boundary test forbids nsgeo.geometry.grid).
Task 1: review (opus) — spec ❌ / Needs fixes: 1 Important (traces_between skips the shared _column_at lookup -> off-by-one on column boundaries: mirrored 1:1 traces_between(0,0)=(1200,1200) vs trace_at(0)=1199; forward drag 0..x_of_trace(19) gives (0,18) not (0,19)). Entering fix round 1.
Task 1: minor (deferred): ruler.py h = |d[1]-d[0]|/2 assumes uniform spacing (true for GridPlacement) — docstring could say so.
Task 1: minor (deferred): untested: trace_index_at over blank space on a bounded transform; n_traces==0 with explicit bounds; zero-width traces_between.
Task 1: minor (deferred): fit() stores bounds uncoerced (a list would make the frozen dataclass unhashable; length unchecked) — normalise to (float, float).
Task 1: minor (deferred): test_pure_view_transform.py:262-264 comment trails a lone ")" after ruff format.
Task 1: fix round 1/5 (1 addressed, 0 open — traces_between now shares _column_at; boundary test added; commits 2f957f4..a8b7eb6)
Task 1: complete (commits a44b9e1..a8b7eb6, review clean)
Task 2: dispatched (base a8b7eb6, implementer sonnet)
Task 2: implementer DONE at 89707a7 (profile_view 101, core+pure 827/3, qgis 1181, lint/types clean); review dispatched (opus).
Task 2: review (opus) — Needs fixes: 1 Important (_distance_ticks raises IndexError for a 1-trace line with a distance — metres_at reads d[1]; old code returned []; every repaint logs and loses the bottom axis). Entering fix round 1.
Ruling: Task 2 minors 1-3 (one_to_one assertion vacuous at fit; hatch assertion passes with the hatch deleted; "wheel" test calls zoom_at instead of a wheel event) go into fix round 1 — they are tests the plan itself specified that don't test what the plan says (my plan's fixture made 1:1 clamp to the bounds) — costs a few minutes if wrong.
Ruling: Task 2 minor 4 accepted as built — a drag wholly inside an axis margin of an UNRULED view now clears the selection instead of selecting trace 0 / n-1; it is the same blank-space rule and arguably better — costs: one more no-ruler behaviour change than the plan listed; walkthrough can catch it.
Task 2: minor (deferred): blank-drag release emits selection_cleared even with Shift held; defensible (band already cleared during the move) but needs a comment.
Task 2: minor (deferred): untested — clear() dropping the ruler; window_m()/set_window_m without a ruler; the n_traces<2 ruler-drop branch.
Task 2: minor (deferred): set_axes duplicates the ViewTransform.fit call; _selection_bounds docstring still calls b+1 the "right edge"; ruled fixture fills 12,800 pixels one by one.
Task 2: fix round 1/5 (4 addressed, 0 open — one-trace ticks guard; one_to_one test on a wider ruler (bounds 360 < 696 px always clamp); hatch pinned; real QWheelEvent; commits 89707a7..19f9bce). Implementer mutation-checked one_to_one in place and restored it — verified view_transform.py unchanged vs 89707a7 and tree clean.
Task 2: complete (commits a8b7eb6..19f9bce, review clean)
Task 3: dispatched (base 19f9bce, implementer sonnet)
Task 3: implementer DONE at f67e104 (core+pure 827/3; qgis first run 1186 passed + 7 velocity_fit fallout, fixed by GRID size_y 11->1.0, then velocity_fit+profile_dock 152 passed; full tier NOT re-run by implementer -> controller running it). Review dispatched (opus).
Task 3: controller full QGIS tier at f67e104: 1193 passed, 0 skipped (11 min).
Task 3: review (opus) — Needs fixes: 1 Important plan-mandated (rule 3 restores the old transform when the new line has no ruler and the shapes match, without checking the OLD view had no ruler -> a same-shape time-triggered line after a ruled line inherits mirror/bounds/window, blank after a zoom; owning test dodges it with 300 vs 240 traces; rule 3's own case untested; stale docstring at test 344). ⚠️ test_a_line_without_distance_neither_mirrors_nor_holds never asserts "no error logged" (takes caplog, unused; _log goes to QgsMessageLog -> use message_log fixture).
Ruling: rule 3 gains `old_ruler is None` — the plan's rule 3 was wrong; the design says a line without distance is never mirrored and never holds — costs nothing if wrong (no-ruler -> no-ruler keeps today's rule).
Ruling: the hold becomes a per-ruler-key remembered window (dict on the dock, recorded from the departing view before every axes change, cleared on site close), replacing my plan call "no separately remembered window" — the reviewer showed hovering a cross-line (or a line on another grid) mid-sweep resets the working line to Fit on return, which defeats the user's own sweep case on grids with cross-lines — costs a small dict and one test; if wrong, a stale window could reappear on a ruler the user left long ago (Fit fixes it).
Ruling: also in fix round 1 — a test that an import widening the ruler (lines_changed only) moves the ruler (no test covered the lines_changed connection); guide wording "running the same way" -> parallel lines in either direction; profile_dock docstring "never clamps"/"always fit" overstatement corrected — plan-text conformance, minutes each.
Task 3: minor (deferred): the same-metre dock tests compute x with trace_units_at (same function bounds_on uses), so a half-column error cancels — only the pure ruler test catches dropping the +0.5.
Task 3: minor (deferred): grid-resize test neither zooms first nor checks cursor/selection survive (hold through resize confirmed by hand in scratch).
Task 3: minor (deferred): unneeded abs=0.05 tolerance at test line ~1898.
Task 3: minor (deferred): REAL_DZT[i % len(REAL_DZT)] implies wrap-around but a reused path raises ValueError (key collision) instead of skipping; exactly 10 files exist.
Task 3: fix round 1 dispatched (resume implementer).
Ruling: with the remembered hold, returning to a ruled line after a no-distance line restores the held window instead of Fit (Review Focus #3 said 'starts at Fit') — follows from the per-ruler hold ruling — costs nothing if wrong (Fit is one click).
Task 3: fix round 1/5 (8 addressed, 0 open — rule 3 needs no ruler on both sides + 3 tests; message_log assertion; per-ruler _held hold + cross-line glance test; lines_changed import test; guide wording; docstrings; commits f67e104..fb62978)
Task 3: minor (deferred): _clear_view_only (current line removed, or preview ends with no working line) drops the window without filing it under _held, so the next line on that ruler gets an older held window (probe: zoom W1 on A, open B, zoom W2, remove B, open C -> W1).
Task 3: minor (deferred): neither half of the _held lifetime is pinned — removing `self._held = {}` from _clear, or adding it to _clear_view_only, passes all 106 dock tests; the first means a new site whose grid id+axis match the old one opens at the old site's zoom.
Task 3: minor (deferred): module docstring "running the same axis" -> "along the same axis"; test_switching_lines_does_not_inherit... docstring says it pins the metre carry-over but only asserts n_traces == 300.
Task 3: complete (commits 19f9bce..fb62978, review clean; full QGIS tier at fb62978 pending)
Final review: dispatched (opus) on review-7069959..fb62978.diff
Controller full QGIS tier at fb62978: 1198 passed in 694.91s (0:11:34)
Final review (opus): With fixes. 1 Important PLAN DEFECT — on a ruled line the held time window is applied unchanged when the same line's record changes size; clamping only handles shrinking: re-selecting a time_cutoff row shows the bypassed record still cropped at the cut (nothing below the line to drag over — breaks the cutoff UX on every gridded line), removing the cutoff or disabling time_zero leaves the view cropped; main refit on any n_samples change. Minors: rule 3's n_traces half untested (mutant survives); a zero-spacing distance (traces_per_metre=+inf header) -> bounds_on ±inf -> set_axes raises -> previous line's picture under the new title; trace_index_at now unused in production.
Ruling: fix wave = whole-record sentinel for the time window (a departing window showing the whole record within dt/2 is filed as "whole record" and rule 2 then takes the new fit's time window) PLUS the same sentinel horizontally (a window covering the whole ruler is filed as "whole ruler", so a line at Fit stays at Fit after a grid resize/import or on the next line) — the plan's clamp-only call was wrong; extending it to the horizontal axis answers the reviewer's declined "grid resize at Fit" question the way a user would expect — costs: if wrong, a user at Fit on a resized grid sees the new full length rather than the old one.
Ruling: fix wave also takes minors #2 (rule-3 n_traces test), #3 (drop the ruler when bounds aren't finite/ordered or spacing is zero), triage 12 (file the window in _clear_view_only, with _clear resetting _held AFTER its _clear_view_only call), triage 13 (site-close test for _held), and docstring ride-alongs (_selection_bounds "right edge"; "running the same axis"; the repurposed test docstring) — each is a few lines and the fix touches the same code — costs minutes.
Ruling: final minor #4 (trace_index_at unused in production) left as is — a clamped public lookup is harmless and pure-tested — costs nothing.
Final review: fix wave dispatched (resume Task 3 implementer, sonnet).
Final review: fix wave DONE at 2ddd7f4 (covering 4 files 280 passed, core+pure 827/3, lint/types clean); scoped re-review dispatched (opus); controller running full QGIS tier.
Controller full QGIS tier at 2ddd7f4: 1208 passed in 563.03s (0:09:23)
Final review: scoped re-review (opus) of the fix wave fb62978..2ddd7f4 — items 1-4 and 6 ADDRESSED (mutants: whole_t/whole_x always False/True all killed; rule-3 n_samples-only KILLED; no _file_window in _clear_view_only KILLED; `_held = {}` removed from _clear KILLED). Item 5 residual: the site-close test doesn't pin the ORDER inside _clear (resetting _held before _clear_view_only SURVIVES, because close_site emits line_opened("") first when a line is current); only a preview-only site close shows it. Reviewer left a drop-in test at scratchpad/mut/packages/nsgeo-qgis/tests/qgis/test_zz_probe.py (test_p1_preview_only_site_close_forgets_the_hold).
Final review: parked — item 5 ordering test gap — Ruling: the code is correct today (reset after _clear_view_only, outside its try); the missing test is not load-bearing and there is no second fix wave; carry the reviewer's drop-in test into the first walkthrough fix round — costs: a future reorder of two lines in _clear could go unnoticed until then.
Final review: minor (deferred): a deep time zoom is lost after visiting a shorter record (the clamped window on the short line is re-filed as "whole", so the long line returns at Fit; before the fix it returned cropped — neither keeps the zoom).
Final review: minor (deferred): a genuine zoom touching the end of a cut record (e.g. [150, 200] of a 200-sample cut) stays at the cut when the cutoff row is re-selected — follows the "genuine zooms held exactly" ruling; walkthrough D1 may surface it.
Final review: minor (deferred): constant-distance line — the dock's _ruler_for still returns a ruler while the view drops it, so _on_geometry_changed re-shows that line on every geometry change and rule 2 (not 3) handles it; harmless.
Final review: minor (deferred): profile_view.py computes bounds_on twice in set_axes; test helper _whole_time has an unused parameter and restates the threshold; no test pins the dt/2 and 0.5-trace tolerances; second bounds_on runs outside np.errstate (possible RuntimeWarning if a distance's first two samples coincide, unverified as reachable); _ruler_for docstring still says "running the same way".
Final review: complete — clean apart from the parked item-5 ordering test; full QGIS tier at 2ddd7f4 1208 passed; core+pure 827/3.
