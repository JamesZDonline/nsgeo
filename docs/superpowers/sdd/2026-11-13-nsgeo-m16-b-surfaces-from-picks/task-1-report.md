# Task 1 report: the surface builder (core)

## Implemented
- `nsgeo/slices/surface.py` (new): `SurfaceSettings`, `Surface`, `SurfaceFit`, `Outlier`, `picks_span_an_area`,
  `surface_volume`, `build_surface`, `surface_mesh`, and the constants in the brief.
- `PreparedVolume.swing(j0, j1)` in `volume.py`.
- Exports in `nsgeo.slices.__init__` (`__all__` kept sorted), 16 README rows. `test_public_api.py` needed no edit:
  `slices` was already in `EXPECTED_PUBLIC` and surface is a submodule.
- `squared_volume()` moved to `tests/real_lines.py` (private `_provenance` helper added there), imported back in `test_slices_volume.py`.
- `tests/test_slices_surface.py`: 15 synthetic + 6 real-data tests.
- Memory: the volume is read in slabs of <= `max_levels` levels over only the depths the offsets/windows touch (+1 level
  each side); only region columns are held; a test checks `max_levels=7` gives the identical surface.

## TDD evidence
RED: `pytest packages/nsgeo-core/tests/test_slices_surface.py` before `surface.py` existed:
`ImportError: cannot import name 'FIT_CLOSE_M' from 'nsgeo.slices'` (collection error, expected: nothing implemented).
GREEN: same command after implementation: `21 passed in 3.44s`.
Then `test_slices_volume.py` 18 passed after the fixture move; full core tier result below.

## Deviations and calls (please review)
1. **Window clamp after the 3x3 median (added, not in the brief).** The median can borrow a neighbour's depth and carry a cell
   outside its own window (real test saw 5.0 cm from the guide with a 2 cm window; steep min-curvature guide near isolated picks).
   The spec's honesty rule says tracking never leaves its window, so after the median I clip to `guide + offset +- window`.
   Parity needed it (see numbers): without it the trial's 82/88 is missed.
2. **Fit slack of 1 micron.** The surface is float32; a cell sitting exactly on the window edge measured 0.02000001 and was
   counted "2-5 cm" and an outlier. `_fit` subtracts 1e-6 from the miss before comparing.
2b. **Outliers include picks pinned at the window edge.** With the clamp, a pick whose reflection lies beyond the window ends with
   the surface held exactly at the window edge, so "more than the window" never fired (the real-data test of a pick moved 0.15 m
   deeper found its cell kept at miss = 0.0200 exactly). `_fit` now lists as an outlier any pick on a hole or with miss >= window - 1 micron.
   `within_close` still counts them (they are within 2 cm), so they appear in both counts.
3. **Picks outside the depth range** (above the first depth or below the last) take no part in the guide or offset, like out-of-frame
   picks, and are reported on a hole. Otherwise a pick at -0.01 m would shift the guide and break "other picks unchanged".
4. **Span check runs on the usable picks** (in frame and in depth range); fewer than 3 usable / collinear raises ValueError.
5. `Surface.strength` is NaN at holes (strength of the kept cell otherwise). `Surface` arrays are `compare=False`.
6. **Real-data fixture adjusted.** The brief's "refined swing peak within +-0.05 m of the level at 15 cells" gave picks scattered
   0.66-0.91 m (two half-cycles in reach) and only 7-11 of 15 kept. The fixture now takes 15 of the chosen level's cells that have
   strength >= 1.5 (spread over x 4-16 m, on the data rows), at the argmax swing peak within 5 cm. Result: 15 of 15 kept, within 5 mm.
7. **`test_real_joins_differ_as_described`: the roughness clause is replaced.** On this data the min-curvature guide is *rougher*
   (sum of squared second differences 0.38) than IDW (0.012): minimum curvature has a bulls-eye at an isolated pick. So the
   test asserts what is true and distinguishing: min-curvature passes through every populated pick cell (+-1e-6) and IDW is
   pulled off at least one by > 1e-4. The brief's premise that IDW is the rougher guide did not hold on the real data.
8. Synthetic fixture: the picks' rows are `5 + (7 i + 1) % 20` so none falls in the weak patch (the first arrangement put pick 7
   in it). `test_refinement_finds_a_peak_between_levels` measures only cells whose 3x3 neighbourhood is all kept: at the edge
   of the kept area the median meets a tilted neighbour and moves 1 mm (0.2 step) for reasons unrelated to refinement.
   Parabola error in the interior is well under 0.1 step.

## Parity check (spec section 7), run outside the repo
Script: `/home/jameszd/nsgeo-m4-check/m16-paraview-trial/core_parity.py` (main `.venv` python, `PYTHONPATH=<worktree>/packages/nsgeo-core/src`).
88 bowl picks, 455-level ZAxis from -0.476 ns at 0.1 ns, 0.071 m/ns, 0.05 m cells, `min_curvature`:
- volume 5-8 s, build 2.4 s (450 depth levels, 320x400).
- **Final recipe (clamp + 1 micron slack): offset 3.52 cm; within 2 cm 86, 2-5 cm 0, further 0, on holes 2 (lines 21 and 33); outliers 7 (those 2 holes + 5 picks pinned at +2.0000 cm on lines 25, 26, 31, 32).**
  HONEST CAVEAT: 5 of the 86 are pinned at the window edge by the clamp; counted by the unclamped distance only 81 are inside 2 cm,
  one short of 82. The strictly "natural" figure for this recipe is 79-81 (below). Controller: decide whether the clamp is acceptable
  or whether the acceptance wants a different change (e.g. a wider default window). 14057 kept of 16039 region cells. South-west picks (lines 23-24): 14 picks, 0 on holes. Meets >= 82 and ~3.6 cm.
- The brief's recipe as written (no clamp, no slack): offset 3.52 cm; within 2 cm 79, 2-5 cm 7, on holes 2 (miss).
- Clamp but no slack: 81 (five picks sat at 2.00000001 cm). No clamp but slack: 80.
  So both changes are needed to reach 82; the clamp is the substantive one (call 17 allows adjusting the recipe).
- IDW join for comparison: many picks 2-3.5 cm off (not the acceptance case).

## Checks
- ruff check / format --check: clean. mypy (constraints command minus the not-yet-existing `surface_plan.py`): no issues in 54 files.

## Final test run
Full core tier, before the last change (outlier rule): `1 failed, 1246 passed, 4 skipped in 232s`; the one failure was
`test_real_pick_on_another_reflection_is_reported` (pinned pick not listed), fixed by 2b. After: `test_slices_surface.py`,
`test_slices_volume.py`, `test_public_api.py`: 54 passed. ruff clean, mypy clean. (Full tier re-run once more before commit, see below.)
Full core tier after the last change: 1247 passed, 4 skipped in 427 s.

# Fix report (R4, R5)

## Changes
- `SurfaceFit` gains `at_edge`; `Outlier` gains `reason` ("hole" | "edge" | "far"). Categories are disjoint:
  `within_close + within_near + further + at_edge + on_holes == n picks`. Edge = kept and `|depth_m - guide_m| >= window - 1e-6`
  at the pick's cell; close/near/further count only kept non-edge picks. Outliers = hole, edge, and far (> window) picks, in input order.
  The clamp and the 1 micron slack are kept as ruled.
- Tests: disjoint-sum asserts; new `test_fit_categories_are_disjoint_and_edge_picks_are_named` (synthetic: a pick 3 cm off is listed
  with reason "edge"); synthetic hole tests assert reason "hole"; the real "pick on another reflection" test asserts the pick moved
  0.15 m deeper has `reason == "edge"` (that is what the data gives: surface pinned at the window edge, not a hole) and the sum is 15.

## Parity against the trial's surface (core_parity.py extended, outside the repo; min_curvature, 88 bowl picks)
- Fit: offset 3.52 cm; within 2 cm 79, 2-5 cm 0, further 0, **at edge 7**, on holes 2; outliers 9 (7 edge at +-2.0000 cm on lines 25 x2, 26 x2, 30, 31, 32; holes on lines 21 and 33); sum 88.
- Kept cells: trial 14035, mine 14057; both 14021, only trial 14, only mine 36; **agreement 99.6% of the union** (need >= 90%).
- |delta depth| on cells both keep: **median 0.097 cm, p95 0.226 cm**, max 4.16 cm (need median <= 0.5 cm).
- South-west x 9.5-11.0, y 1.5-4.0 (1500 cells): hole fraction **mine 49.5%, trial 50.3%** (need within 10 points).
- All three acceptances met. Note the strictly-inside-2-cm count is 79 (the 82 figure was not reached without counting pinned picks), but the surfaces agree with the trial's almost cell for cell.

## Checks
ruff check/format clean, mypy clean, full core tier: 1248 passed, 4 skipped.

# Fix report, round 1 (review findings, R6)

## Changes
- **R6 offset votes.** `_measure_offset`: each pick votes with the strongest local maximum (>= left, > right, judged against
  the neighbours just outside the search) within +-5 cm; no local maximum in reach means no vote.
- **Window pinned by tests.** Real data: `fit.at_edge == 0` and share of kept cells held at the window edge < 10%
  (measured 25 of 568 = 4.4%; the 5x-window mutant gives 242 of 778 = 31% and at_edge 1). Synthetic
  `test_tracking_ignores_a_decoy_outside_its_window`: decoy 8 cm below, amplitude 2x (squared 4x), strength test lowered to 0.5
  (the decoy lifts the depth trend and the true cells otherwise fail at 1.0); kept depths within 5 mm of truth, at_edge 0,
  12/12 within 2 cm. The 5x-window mutant gives max error 2.00 cm, 12 at the edge: killed.
- **Decoy / offset tests:** `(4 cm, gain 1.5)` and `(8 cm, gain 2.0)`: offset 1.71 and 2.15 cm (within one 5 mm step of 2.0), surface within one
  step of truth, 12/12 within 2 cm, no edge. NOTE: the reviewer's gain 3 cannot give 2.0 +- 0.5 cm under any rule: the decoy's own
  sidelobe (0.44 x 3 = 1.3 amplitude, 1.7 squared) is a stronger local maximum than the true peak (1.0) and lies in reach
  (measured 1.39 cm at 4 cm, 2.70 cm at 8 cm). So the decoys were chosen as strong enough to drag an argmax but with sidelobes below the true peak.
- **Flank case:** `_ramp` fixture (amplitude only grows with depth): `_measure_offset` = 0.0 for flank-only picks; mixed with picks on a swing,
  the flank picks leave the offset unchanged.
- **Minor:** at_edge and the clamp measured before smoothing (test with smoothing_m 0.3 keeps the edge pick as "edge"); "far" test
  (two disagreeing picks in one cell; reason "far", not edge); refusal text says "N of M picks are usable (a outside the frame,
  b outside the depth range ...)" with a test; `Surface` is `eq=False`; IDW computed only for region cells; region test assertion fixed;
  refinement test uses a flat reflector truly centred at 10.05 ns between the 10.0 and 10.1 ns levels (all kept cells within 0.5 mm);
  prints removed; `_reflector_picks` guards empty levels (tests run clean with `-W error`); README rows updated.

## Tests
`pytest packages/nsgeo-core/tests/test_slices_surface.py -W error`: 29 passed. Full core tier: 1255 passed, 4 skipped. ruff, ruff format, mypy clean.

## Parity (core_parity.py, min_curvature, 88 bowl picks) -- R5 NOT fully met
- Offset **2.85 cm** (was 3.52; trial about 3.6). Fit: within 2 cm 79, at edge 7, holes 2, outliers 9, sum 88.
- Kept: trial 14035, mine 14019; both 13911, only trial 124, only mine 108; **agreement 98.4% of union (pass)**.
- |delta depth| median **0.614 cm (FAIL, limit 0.5 cm)**, p95 2.84 cm, max 4.11 cm.
- South-west hole fraction mine 51.5% vs trial 50.3% (pass).
- Why: 31 of the 88 picks had their strongest swing on the search limit (|vote| = 5 cm +- 4 mm in the old code; a flank or a swing just out of reach). Under R6 19 votes change by > 1 cm
  (median per-pick vote 3.57 -> 2.85 cm); the surface shifts accordingly, by a median 0.6 cm against the trial's. Not tuned; stopping per the instruction.
  Options for the controller: accept (the trial's offset is itself inflated by flank votes); or allow the search limit level to vote when it
  is the strongest swing and only the climb toward an out-of-reach reflection is excluded; or widen OFFSET_SEARCH_M.

# Fix report, round 2 (R6' replaces R6)

## Changes
- `_measure_offset` back to the trial's vote (refined argmax within +-5 cm) and now returns `(offset, votes, at_limit)`;
  a vote is at the limit when its argmax is the first or last search level, and still counts at the limit value in the median.
- `Surface` gains `offset_votes`, `offset_at_limit` and the property `offset_reliable`
  (`offset_votes > 0 and 2 * offset_at_limit < offset_votes`), documented: unreliable means a stronger reflection out of reach is likely
  pulling the surface, so check the picks. README row updated.
- Tests: milder decoys (4 cm x1.5, 8 cm x2.0) give offset within one step, reliable, 12 votes, surface on truth; strong decoys (x3 at 4 and 8 cm)
  give `offset_reliable False` with `offset_at_limit == offset_votes == 12`; a parametrised invariant over six decoys: offset within one step of 2.0 cm OR unreliable;
  the flank-only picks now vote at the limit (3 of 3, offset 0.05) and mixed with swing picks count (5 votes, 2 at limit); the real fixture asserts `offset_reliable`.
  Round-1 window-pinning tests and the minors are kept.

## Tests
`test_slices_surface.py -W error`: 37 passed. Full core tier: 1263 passed, 4 skipped. ruff, ruff format, mypy clean.

## Parity (core_parity.py, min_curvature, 88 bowl picks) -- all R5 met, back to the pre-R6 run
- Offset **3.52 cm**; offset_votes 88, offset_at_limit 29, reliable True. Fit: within 2 cm 79, at edge 7, holes 2, outliers 9.
- Kept: trial 14035, mine 14057; both 14021, only trial 14, only mine 36; **agreement 99.6%** of the union.
- |delta depth| median **0.097 cm**, p95 0.226 cm, max 4.16 cm.
- South-west hole fraction mine 49.5%, trial 50.3%.

# Fix report, round 3 (R8)

## Changes
- Docstring of `Surface.offset_reliable` and the README `Surface` row: False at *at least half* the votes on the limit; a stronger reflection whose
  sidelobe falls inside the +-5 cm search can still pull the offset unflagged (known blind spot). The vote is unchanged, so the parity is unchanged.
- `test_the_offset_is_right_or_flagged_for_decoys_with_no_sidelobe_in_reach` (renamed invariant; comment says what it covers: main peak beyond the
  search or censored votes, the six 4 / 8 cm decoys) plus a **strict xfail** `test_the_offset_is_right_or_flagged_when_a_sidelobe_falls_in_reach`
  on the 6.5 cm-below x3 decoy (offset 3.07 cm flagged reliable today); reason text as ruled.
- Renamed `..._unreliable_never_wrong_and_reliable` to `test_a_strong_decoy_puts_every_vote_on_the_limit_and_flags_the_offset`.
- Duplicate removed: the window test now uses a decoy 10 cm below at 2x (measured earlier: kept depths within 1 mm of truth; the 5x-window mutant,
  whose search reaches 10 cm, is killed with a 2 cm error).
- `test_smoothing_never_hides_a_pick_held_at_the_edge` rebuilt: flat guide at 0.48 m over a flat reflection at 0.50 m, with a 3-column strip through
  pick 5 whose reflection is 3 cm deeper; `window_m = 0.0225` so a depth level lies exactly at the window edge (the edge only arises when the
  clamp acts, which needs the refined argmax to reach it). Unsmoothed: surface - guide at the pick = 2.25 cm (= window, held). With
  `smoothing_m = 0.1`: 1.987 cm (drawn back inside); `at_edge` still counts it and the pick is listed with reason "edge".
  **Mutation check:** temporarily passing the smoothed depth (`in_surface`) to `_fit` as the held depth made this test fail
  (assertion at the `at_edge`/reason check); the mutation was reverted and `git diff` carries no trace of it.

## Tests
`test_slices_surface.py -W error`: 37 passed, 1 xfailed. Full core tier: 1263 passed, 4 skipped, 1 xfailed. ruff, ruff format, mypy clean.
