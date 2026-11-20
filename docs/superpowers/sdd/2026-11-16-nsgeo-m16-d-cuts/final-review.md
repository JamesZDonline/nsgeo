# Final review: M16 Plan D (cuts in 3-D), 9691c7b..463bdf7

Reviewer: opus, whole branch, read-only. Probes are in
`/tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/7ec288b0-6c3d-4401-b51d-656c73323d21/scratchpad/final/`.

**What I ran:**
- Core and pure tests (`test_slices_walls`, `test_vtkxml`, `test_paraview_scene`, `test_pure_surface_plan`, `test_pure_volume_choice`): 75 passed. The 3 skips are the old pvpython tests in `test_paraview_scene`, which this run did not get `NSGEO_PVPYTHON`.
- QGIS tests (`paraview_export`, `surface_build`, `scene3d`, `surfaces_dock`), filtered with `-k "cut or wall or stated_size or cancel or skipped or writes_the_folder"`, with `NSGEO_PVPYTHON` set: 32 passed, none skipped. The pvpython scene test and the real-data wall tests ran.
- Linters on the changed files: `ruff check` and `ruff format --check` are clean, and so is CI's exact mypy command.
- Two probes of my own (below), plus a pvpython probe of duplicate registration names.

## Strengths

- **One clock rule.** `cut_pick_on_clock` (surface_plan.py) decides for all four consumers: `place_picks`, `pick_depths`, the dialog count and the surface build's reasons.
  - It is tested on both clocks, with and without a distance.
  - A cut pick lands where the line pick under it lands, at the same depth and within half a cell, through a rotated and offset grid.
- **Old surfaces stay fresh (R7).** `test_a_line_only_surface_hashes_its_source_as_before_cut_picks_existed` rebuilds the old source dict by hand and compares the hashes, so a surface built before this branch stays fresh after the upgrade.
- **Walls agree with the slices.**
  - `wall_amplitude` reuses the volume's own `_rms_levels`, rather than copying it.
  - The window is applied over every level and the levels before time zero are dropped afterwards, which matches how `_amplitude` reads them.
  - Wall points use frame-local metres, the same frame as cube.vti, whose origin is at `cell/2`.
  - Wall rows sit at `depth_at(t_k)`. The cube.vti planes are evenly spaced in depth and blend the same source levels, so a layered velocity still agrees between rows. The top and bottom match exactly.
  - Under both transforms, the real-data scale tests would fail on squared or doubly-squared values.
- **One column rule.** `cut_wall_columns` is shared by the wall and the size estimate.
- **Export safety holds with walls.** The cancel tests now tell a cancel in the cube's slabs apart from one in the walls. The 2% size test and the refusal test work at the real cube-to-wall ratio.
- **The scene test is real.** It opens the scene under pvpython with a quoted, slashed, accented cut name and asserts that every wall is registered and hidden.
- **Memory.** The fill is a read-only memmap, sampled level by level. No second cube copy exists.
- **Clean fix rounds.** The CI regressions in tests outside a task's brief (the dialog's "Also" row, the New surface refusal) were caught and fixed.

## Issues

### Critical (Must Fix)

None.

### Important (Should Fix)

**I1. Deleting a cut does not relabel its surface "(stale)" on the map.**
- **Where:** surface_layers.py:120-127 (connects) and :184-191 (`dispose`'s list). `SurfaceLayers` listens to `features_changed`, `picks_changed`, `slice_sources_changed`, `lines_changed`, `grids_changed`, `presets_changed` and `site_opened`, but not `cuts_changed`. `remove_cut` emits only `cuts_changed`.
- **Probe:** `probe/test_probe_cuts.py::test_probe_layer_label_after_cut_delete` builds a surface with a cut pick, then deletes the cut. Afterwards `surfaces.state(...).stale == ('source',)`, but the map layer is still named `'Mixed'`, with no " (stale)".
- **Why it matters:**
  - The guide promises "A stale surface is labelled in the Layers panel".
  - The Surfaces panel (R8) and the 3-D view's title (Task 2 I1) now say stale, while the map layer says fresh.
  - Walkthrough step 4 deletes the cut and will show the mismatch.
  - This is the third listener of the same bug class. Task 1 fixed the dock and Task 2 fixed `Scene3D`.
- **Fix:**
  - Add `session.cuts_changed.connect(self.request_sync)` to `SurfaceLayers.__init__`, and add it to `dispose`'s disconnect tuple.
  - Add a test in `test_plugin_surface_layers.py`: build with a cut pick, call `remove_cut`, spin, and expect the name to end with `STALE_SUFFIX`.

**I2. Both cut flows give a false reason for a stale surface (partly plan-mandated).**
- **Where:**
  - surfaces.py:362-375: the cut vertices go into the `"source"` hash, as the plan said.
  - surface_plan.py:291: `STALE_REASONS["source"] = "the grid's processing, lines or placement changed"`.
- **Probe:** `probe/test_probe_cuts.py` checks both cut flows.
  - Deleting a cut gives "Stale: the grid's processing, lines or placement changed since it was built."
  - Adding one cut pick to a line-only surface gives `('picks', 'source')`: "its picks changed and the grid's processing, lines or placement changed". The second half is false, because R7's conditional key appears as soon as the surface has a cut pick. Removing the last cut pick does the same.
- **Why it matters:**
  - The guide says "the panel says what changed".
  - In both of the plan's new flows, it tells the user that their processing, lines or placement changed when nothing of the kind happened.
  - The rebuild does report "their cut has been deleted", but the panel's reason sends the user looking in the wrong place first.
- **Fix:** move the cut vertices out of `"source"` and into `"picks"`, still conditional so R7 holds for line-only surfaces:
  `"picks": input_hash(picks) if not cuts else input_hash({"picks": picks, "cuts": cuts})`.
  - A deleted cut then reads "its picks changed", and a membership change no longer adds "source".
  - Update `test_a_deleted_cut_marks_its_surfaces_stale_and_is_reported` from `"source" in stale` to `stale == ("picks",)`, and update the dock test.
  - A cheaper alternative is to add "cuts" to the `"source"` wording. That fixes the deletion message but not the membership one.

### Minor (Nice to Have)

1. **Clicking a cut pick in the outlier list does not open the cut.** surfaces_dock.py:525 opens only keys in `session.keys()`, which holds lines only, so a cut pick is just selected on the map. The guide says "open its line in the Profile panel, at that pick".
   - **Fix:** also open the key when `is_cut_key(key)` and the cut exists, and move the cursor to the pick's distance. Don't use `trace`: a cut pick's trace is a record only.
2. **The surface build does not filter cuts by grid.** In surfaces.py:604-609 the `cuts` map takes every member cut that still exists, whatever its grid. `_write_picks` and `pick_depths` both restrict to `cut_keys_on_grid`.
   - If a cut pick from another grid ever reached a surface's members (by a hand edit of `feature_id`), it would be placed through the wrong grid's `to_world` and used with no warning.
   - **Fix:** a one-line `if cut.grid_id == grid_id` guard, so such a pick is reported, never placed.
3. **Wording for picks on a deleted cut.**
   - plugin.py builds the dialog label "(line F1; cut a deleted cut)".
   - The refusal says the pick "is not on a line of a grid".
   - **Fix:** leave a deleted cut out of `cut_names` (it has no grid), and consider a "their cut has been deleted" refusal.
4. **The docs.**
   - The guide's `walls/` row and the export README both say "every line". Lines that were skipped, or left out of the grid's slices, get no wall.
   - The README doesn't mention that cut picks are in `picks.vtp`, or its `cut` and `line` arrays.
   - The guide's "Rebuild after changes" list doesn't say that deleting a cut makes its surfaces stale.
5. **Small drift risks in the export.**
   - `_write_walls` (paraview_export.py:1211) rebuilds each cut's frame path instead of using `_cut_paths`, which feeds the size estimate.
   - `summary()` (:434) repeats `estimate()`'s sum, and `estimate()` no longer has a production caller.
6. **Duplicate item names (plan call, noted).** Walls are named by file stem. Two lines with the same stem on one grid, or two cuts renamed to the same name, give two identical items. I probed ParaView 6.2.1 and it accepts duplicate `registrationName`s, so nothing breaks. The items just can't be told apart.

## Deferred minors triage

| From | Item | Verdict |
|---|---|---|
| T1 M2 / T2 | A cut pick with `distance_m` None gets the wrong reason (now `WHY_OTHER_CLOCK`). | **Follow-up.** Only hand-edited rows can hit it, since `add_cut_pick` always stores a finite, clamped distance. Fix: check the distance first and report `WHY_NO_POSITION`. |
| T1 M5 | `cut_pick_base` and `profile_dock._time_base_of_provenance` differ on `""` (and on a None `stack_json`). | **Follow-up.** The profile view and the export can only disagree on hand-edited provenance. Fix: route the profile dock through `cut_pick_base`. |
| T1 M7 | The membership test lost its create-raise and mixed cut/line `grid_id` assertions. | **Follow-up.** Coverage only; the behaviour is pinned elsewhere (dialog test, `check` tests). |
| T3 M1 | No cut-wall cap test. | **Resolved.** `test_a_long_cut_wall_is_capped_at_300_columns` exists. |
| T3 M2 | Degenerate cut paths give unclear errors. | **Follow-up.** R13 skips and logs them, and `walls_size` doesn't count them. Only the log text is unclear. |
| T3 M3 | A 1-trace line raises. | **Resolved by R13.** |
| T3 M4 | Path and clock code duplicated from `section_columns` / `plan_line`. | **Follow-up.** It is bit-identical today (verified in Task 3). Share helpers when either is next touched. |
| T3 M5 | A third copy of vtkxml's `.part` write block. | **Follow-up.** |
| T3 M6 | Stale "Both write" docstring (vtkxml.py:3). | **Follow-up**, or fold into the I1/I2 round (one word). |
| T3 M7 | `test_structured_grid_round_trips_and_its_size_is_exact` asserts an upper bound. | **Follow-up** (rename). |
| T3 M8 | No `Wall` shape check; `write_structured_grid` accepts an empty extent. | **Follow-up.** No producer can make either today. |
| T4 | R13's `try` also wraps `wall_amplitude` (paraview_export.py:1185-1190). | **Follow-up, cheap to fold in.** Nothing raises there today. A future `ValueError` would drop every wall with only log lines, so narrowing the `try` costs about 4 lines. |
| T4 | The no-time-zero wall test doesn't assert `z.nz > nd` (test_plugin_paraview_export.py:1445). | **Follow-up, cheap to fold in.** The case is exercised today (512 against 460). One assertion stops it from silently testing nothing later. |
| T4 | The write-pass cancel comment says "last slab" (:235). | **Follow-up.** Harmless. |
| T4 | R13's 1-trace-line `run` path is tested only via `walls_size`. | **Follow-up.** It shares `one()` with the tested flat-cut skip. |
| T4 M9 | Notes: `announce` re-sources; the dialog's wall count is an upper bound; the pvpython "Could not determine array range" warning. | **No action.** The bound is acceptable, and the warning predates the walls. |

## Declined to judge

- **Cut picks after a change to the Time zero step's parameters** (not on/off). Such a change moves the cube's clock, while cut picks store no zero. This is M15 call 18's design, outside Plan D. The surface still goes stale through `steps`.
- **Scene3D places a cut pick at its picks-layer map point** rather than recomputing it. This is R4, the same as line picks, and the guide says the picks follow their grid.
- **Line picks in the dialog's count** include picks that `picks.vtp` drops (skipped lines, non-finite depth). This predates the branch; R11 covers cut picks only.
- **`_pick_counts` is never invalidated while the dialog lives.** This predates the branch (Plan A/B).
- **Walls coloured like the slices**, against spec §5.5's "like the profile view": author ruling R6.
- **Walls are unblurred** and slightly sharper than the slices: R14.
- **Line walls in sorted-key order**, and **named by file stem** rather than placement label: R16 and plan call 2/Task 4.
- **`int(p.trace)` raising on a None trace** in `place_picks`. This predates the branch for line picks, and the picks layer filters unreadable rows.
- **Progress totals if a cut is added mid-export.** The wait excludes user input, and only the progress bar is affected.
- **macOS CI jobs "cancelled" on e987486 and 501f0c5:** cancel-in-progress, not failures.

## Recommendations

1. Fix I1 and I2 in one small round: a listener plus test, and the hash move plus two assertion changes. Fold in the two cheap Task 4 deferrals (narrow the `try`; assert `z.nz > nd`) and the docstring word if convenient.
2. **CI must be green on the final head before merge.**
   - The run on 463bdf7 was still queued when I checked.
   - e896885's run was cancelled, so the whole QGIS tier has never run on the wall fixes. 463bdf7's run (or the next fix round's) is the first.
3. **The plan's human gate is still outstanding.** The ledger has no entry for it: profile `ns_geo_m16d`, a Sunnyside copy, steps 1-5, and an Artifact with a results database. Steps 2 (another clock) and 4 (delete the cut) are exactly where I1 and I2 would show. Run the walkthrough after the fix round and before any merge decision.
4. File the follow-ups above as one issue, "M16 D tidy-ups", rather than many.

## Assessment

**Ready to merge?** With fixes

**Reasoning:** The core of Plan D is correct and well tested:
- cut picks placed by one shared clock rule;
- walls on the cube's scale, levels and frame;
- the export's atomicity, size and refusal intact.

Two staleness gaps on the plan's own "delete the cut" path should be fixed before the walkthrough: the map label isn't updated (I1), and the panel gives a false reason (I2). CI on the final head and the human walkthrough are still pending.
