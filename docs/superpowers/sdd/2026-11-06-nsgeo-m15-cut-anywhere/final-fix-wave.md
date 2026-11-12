# M15 final review — the fix wave (controller's list, 2026-11-11)

The whole-branch review (d8acb01..650870e) said "Ready to merge: with fixes". It found no Critical issues.

Fix everything below in one wave. Items marked "Ruling" are the controller's decisions; build them as stated.

## I1 (Important) — under minimum curvature, a cut disagrees with the slice across coverage holes at higher max distance

**Where:** `packages/nsgeo-core/src/nsgeo/slices/section.py:175-186` (`curvature_margin_cells` ignores `max_distance_m`) and `packages/nsgeo-qgis/nsgeo_qgis/cut_sections.py:171-180, 572-576`.

**The cause:** the reach of "six line spacings" rests on coupling that decays by a fixed factor per line crossed. A coverage hole has no lines to cross, so its coupling reaches much further.

**The reviewer's measurements** (worst gap on the cut's columns, as a fraction of the level's range):
- Real ten lines with lines 3–6 dropped (a 2 m hole):

  | Max distance | Worst gap | Against 1e-3 |
  |---|---|---|
  | 0.75 spacings | 3.3e-4 | passes |
  | 1.0 spacing | 2.1e-3 | fails |
  | 1.5 spacings | 0.5–0.9% | fails |
  | 2.0 spacings | up to 1.4% | fails |

- Synthetic grids (0.5 m lines, 0.05 m cells), 7 m hole:
  - at 6 spacings, about 10% off;
  - at 7.5 or 9 spacings, the solved cut is blank on all 321 columns where the slice is filled. The kriging stand-in had values there, so the section visibly blanks out as the solve lands.

**Why it matters:** this breaks spec §4.7's 0.1%, the §6 goal ("agree … under every method"), and the first anti-goal. It also bites exactly when a user raises max distance to fill a gap.

**Ruling:**
- **Thresholds.** Use crops only when `max_distance_m <= CROP_MAX_DISTANCE_SPACINGS * spacing_m`, with `CROP_MAX_DISTANCE_SPACINGS = 0.75`, a module constant in `section.py` (exported, with a README row).
- **Above that threshold,** each depth job solves with the engine's whole-frame `CurvaturePlan`. That plan is what `SliceEngine.section_fills(finish)` returns as `fill`; `CutSections._build` currently throws it away. Each job then smooths with the settings and samples with the columns' taps. Put the whole-frame path in core next to `solve_section_level`, for example `solve_section_level_whole(level, columns, plan, settings, cell, should_stop=None) -> (n,)`, so the plugin does not hand-roll it.
- **Thread safety.** `CurvaturePlan.solve` writes nothing, so a job may share the engine's plan.
- **Expected cost.** About 0.30 s a depth on Grid 1, against 0.215 s on crops.
- **Tests.**
  - A core test on the real lines with lines 3–6 dropped, at 1.5 spacings: the cut's minimum-curvature section agrees with the slice view (whole-frame solve, smoothed, sampled) within 1e-3 of the range at three levels.
  - The spec's test 3 × test 12 combination: a cut through a coverage hole under minimum curvature, at the default 0.75 spacings (crops) and at 1.5 spacings (whole frame), both agreeing with the slice.
  - A test that the threshold picks the path: at or below 0.75 spacings, crops; above it, whole-frame.

## I2 (Important) — opening a cut on a streaming engine builds and holds the whole resident cube with no budget check

**Where:** `cut_sections.py:307-319`, through `SliceEngine.cube()` (`slices_engine.py:~1662`).

**The cause:** `choose_residency` streams when the estimate exceeds `DEFAULT_BUDGET_BYTES` (1.5 GB). Opening a cut then builds that cube synchronously on the GUI thread and keeps it until `set_source`/`clear`, while the status line still says "streaming". In Whole site scope, cubes pile up across grids.

**Ruling:**
- **Refuse when over budget.** When `engine.mode == "streaming"` and the engine's memory estimate exceeds the residency budget the engine itself uses, do not build. Return a message: `TOO_BIG_TEXT = "{grid}'s cube is too large to hold in memory for a cut. Use a coarser cell or a shorter depth range in the Slices panel."` Use the engine's existing estimate and budget names; read `slices_engine.py` / `slices_plan.py` for `choose_residency`, `estimate` and `DEFAULT_BUDGET_BYTES`.
- **Drop the cube when nothing reads it.** For a streaming engine (one whose cube was built only for a cut), call `engine.drop_cube()` when no open cut reads that engine any more: the working item leaves the cut, the cut is deleted, or the site closes. Never drop a cube the engine holds by its own residency choice ("resident" mode).
- **Tests.**
  - A streaming engine over budget gives `TOO_BIG_TEXT` and `has_cube` stays False.
  - A streaming engine under budget builds, then drops its cube when the working item moves to a line.
  - A resident engine's cube is never dropped by `CutSections`.

## Minors folded into this wave

1. **"Being prepared again" message (minor 2).** While the cut's grid re-prepares (`engine.is_running`, in either scope), a cut shows `PREPARING_TEXT = "{grid} is being prepared again. The cut will redraw when it is ready."` instead of `NO_SOURCE_TEXT`. The same text replaces `NO_SOURCE_TEXT` for a cube build that failed: use `BUILD_FAILED_TEXT = "{grid}'s cube could not be built for this cut: {reason}"`, and log the reason. Keep the waiting/redraw behaviour of Task 3, so the cut redraws when preparation ends. Pin both messages in tests.
2. **Re-centre the solve on a rested window change (minor 3).** `_on_window_changed` (`cut_sections.py:413-418`) only records the band. After the band rests for `CUT_SOLVE_REST_MS`, re-arm the working cut's solve so the unsolved depths are reordered outward from the new centre. `_start_solve` already resumes from the solved set. Test: after a window change mid-solve, the next depth landed is the new centre (or the nearest unsolved one).
3. **A plain click on a cut in the Survey panel opens it (minor 4).** It currently does nothing (`ui/survey_dock.py:403`; `key_of` handles lines only). Make a click on a cut item open it, the way a line opens on click. Test it.
4. **Guide wording** (`docs/guide/getting-started.md`):
   - :544 "clicking one opens it" → *selecting* a cut with QGIS's Select tool opens it.
   - :594 "refuse the site and say why" → older versions refuse to open it, saying its file version is newer than they read. Match 0.3.0's real refusal: "declares schema version 2, but this build reads version 1".
   - :535 the example's "211 depths" → Grid 1 has 463. Better still, do not quote a depth count.
   - Rewrap the over-long lines (~:529 and the "starts again" sentence, plus any others) to the guide's width.
5. **Unused `SPREAD` constant** in `packages/nsgeo-core/tests/test_slices_section.py`: remove it.
6. **Dirtiness tests:** assert that `rename_cut` and `remove_cut` each mark the site dirty, in `test_plugin_session_cuts.py`.
7. **The survey-order test** (`test_plugin_cut_drawing.py`, `test_a_first_click_inside_two_grids_takes_the_first_in_survey_order`) cannot tell survey order from id order. Add the grids as "B" then "A", overlapping, and expect B.
8. **The marker assert:** `test_the_marker_and_band_follow_a_selection_on_a_cut` (`test_plugin_map_link_cuts.py`) never asserts the marker. Assert it sits at the selection's column world position in canvas CRS.
9. **A NULL `distance_m` cut pick in `follow_lines`:** add a `test_plugin_cut_picks.py` test. Across a grid move, the row's geometry and its depth/velocity stay exactly as they were, and nothing raises.

## Not in this wave (follow-ups; do not do them)
- A grid velocity change discards a finished solve (velocity-only cube drop).
- A cuts-only layer refresh.
- Extracting `_CutSolve` from `cut_sections.py`.
- Partial-solve provenance.
- Vectorising `finish_section` across levels for the 0.9–1.4 s first preview.
- The other deferred minors the review marked "later".
