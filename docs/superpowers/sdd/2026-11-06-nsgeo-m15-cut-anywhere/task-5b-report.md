# Task 5b report

Commits: 425d9ed (Part A), 7291b1b (B1), e86cef4 (B1 test key fix), d7975c9 (B2-B7). All pushed.

## Part A
A1 provenance `time_base` (cut_sections._provenance_json); A2 cut picks already write zero_ns None, pinned by tests; A3 line_zero(cut) -> None, silent; A4 _follow_key returns for a cut; A5 _push_slice_band branches on cut key, _set_cut_chrome(True) clears _shown_radargram; A6 _refresh_picks leaves out/counts other-clock picks, title built in `_apply_cut_title` only (" · {n} picks on another clock"); A7 guide paragraph.
Extra (controller note + found while testing): `_velocity_time_zero_note` read a cut's stack -> "could not update the velocity fit: no line with key cut:" ; now returns "" for a cut. Pinned by test_showing_a_cut_and_removing_its_grid_logs_nothing_from_the_velocity_fit. The three controller-named tests pass.
Fixtures: `_shown_with`/`shown_zeroed` in test_plugin_cut_sections.py, `profile_zeroed` in test_plugin_profile_cut.py. Extra test: pick with no time_base reads as radar.
RED: with the Part A source reverted, 10 of the Part A/related tests failed (incl. the three above); restored -> green.

## Part B
B1 CROP_MAX_DISTANCE_SPACINGS 0.5; section.py docstring rewritten; cut_sections docstrings; guide "three quarters" -> "half" (was now false). core README row wording still correct. test_plugin_cut_refine crops test uses 0.5, whole-frame test adds 0.75.
Hole test: 1 m/2 m/3 m holes, x=4.0/10.2/17.5, diagonal, beside; spacings 0.5/0.75/1.5; levels 10..170 step 20; 1e-3 everywhere. All 31 cases pass (no case missed 1e-3 at 0.5). Timing 102 s on one quiet run (118 s under load) - OVER the ~60 s. Applied the brief's drops (beside and 1.5 for 1 m and 3 m holes); more could go (the 0.5-spacing crop cases cost 5-17 s each).
DEVIATION: the existing "beside" path y=1.55 is blank at 0.5 spacings on the 2 m hole and sits inside the 3 m hole (all-NaN, vacuous). Moved it to y=1.45 (0.2 m inside the 2 m hole's edge), kept for the 2 m hole only.
B2 _hold() releases an overwritten engine; line visit drops nothing; only a cut-key open calls _release_cubes(only=key). B3 `_ordered_centre`; re-arm only on a moved centre. B4 `_preparing` reads site_engine.grid_state (preparing/queued), KeyError -> False; test drives a real re-queue (B line edit) from the site engine's on_changed callback. B5 reason `str(exc) or type(exc).__name__`. B6 failure memo (engine, SliceEngine.preparation_generation, reason); wait reason "failed"; retried on new engine, re-preparation, or the cut being opened (section_changed emitted since the profile asks before CutSections' slot). B7 docstring and guide example.
RED: with cut_sections.py/slices_engine.py reverted, 7 of 8 new B tests failed (the "another engine opens" test passes on old code, as the old code already did that).

## Results
Core+pure: 1380 passed, 1 failed (stop-test key rename, fixed in e86cef4, then passes), 5 skipped. Full QGIS after d7975c9: 1898 passed (22 min). ruff check, ruff format --check, mypy (CI list) clean.

## Concerns
- Hole test 102 s (see above). cut_sections.py is now ~900 lines; the failure memo and cube-holding helpers could split out later.
- Scratchpad files not committed.

## Fix round 1 (commit: "fix(cut): a failed build retries once per open and after a resolution change")
- I1: the failure memo (`_Failure`) is stamped with a new read-only `SiteSession.open_serial`, bumped in `open_line` before `line_opened` is emitted. `_on_item_opened` retries only a memo with an older serial. My first design (a CutSections counter bumped at the end of the slot) was order-dependent (wrong when the profile asks after the slot), so I moved the counter to the session. Test (plugin with its own ProfileDock): first open of a failing cut -> 1 `cube()` call, 1 warning; reopen after a line visit -> exactly one more.
- I2: memo also keys on engine frame and z; `"failed"` waiting counts `has_cube` as ready. Tests: `cell_spin` change retries once (and `preparation_generation` shown not to move); an engine-built cube re-announces.
- I3: A4 test monkeypatches `session.line_zero` to 5.0. Mutant (guard removed in the worktree, reverted at once, not committed): test FAILED; restored: passes.
- Minors: 1 `_unhold_other` before the build; 2 sourceless cut skips release (test keeps cube + solved row 3); 3 `_waiting` comment; 4 `preparation_generation` docstring (set_source dispatch and clear only); 5 `_failed` swept for deleted cut and on site close; 6 `== NULL`; 7 spy asserts the palette change emitted `window_changed` with the same band; 8 `_hole_cases` docstring (1 m reason: y=1.45 is 0.8 m from that hole).
- Results: full QGIS 1902 passed (21 min); pure + boundary 253 passed, 1 skipped; ruff check/format and mypy (CI list) clean. Core src untouched (docstring-only test edit). Push needed one retry after a DNS failure; pushed.
