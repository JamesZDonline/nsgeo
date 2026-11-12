### Task 6: Minimum curvature behind the kriging, and the guide

**Files:**
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/refine.py` (`thread_name_prefix`)
  - `packages/nsgeo-qgis/nsgeo_qgis/cut_sections.py`
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (the title's progress)
  - `docs/guide/getting-started.md`
- Test:
  - Create: `tests/qgis/test_plugin_cut_refine.py`
  - Modify: `test_plugin_refine.py`

**Interfaces:**
- Consumes:
  - Task 1: `section_crops`, `plan_section_curvature`, `solve_section_level`, `smoothing_reach_cells`, `curvature_margin_cells(settings, cell, spacing_m)` (with `spacing_m` = the cut's grid's `default_spacing`).
  - Task 3: `CutSections`.
  - `Refiner.start` / `cancel` / `shutdown`.
- Produces:
  - `Refiner.__init__(self, parent: QObject, *, thread_name_prefix: str = THREAD_NAME_PREFIX)`.
  - In `cut_sections.py`:
    - `CUT_THREAD_NAME_PREFIX`, `CUT_SOLVE_REST_MS`, `CUT_REDRAW_MS`
    - `class CutLevelJob`, with `level: int`, `result: np.ndarray | None`, and `run(should_stop)`.

- [ ] **Step 1: Write the failing tests** (`test_plugin_cut_refine.py`, using `slow_jobs` and `spin_until` from `plugin_testing.py`; method `min_curvature` at cell 0.25)
  - `test_the_working_cut_is_solved_after_a_rest_and_replaces_kriging` (§4.7):
    - right after opening: `standing_in`, and the title is `Kriging preview · minimum curvature 0 of {nz} depths`;
    - after `spin_until` all depths land: `method == "min_curvature"`, `standing_in is False`, and the title ends `Minimum curvature`;
    - each row equals `solve_section_level` for that level;
    - `provenance_json` has no `standing_in_for`.
  - `test_depths_near_the_slice_band_are_solved_first`: the first landed job's level is the band's centre level.
  - `test_a_hover_preview_starts_no_solve`: no job runs, and the title is `Kriging preview (minimum curvature when opened)`.
  - `test_a_settings_change_discards_the_solve`: a change mid-solve cancels; no old row lands; a new solve starts after the rest.
  - `test_a_pick_while_kriging_stands_in_records_kriging`.
  - `test_the_slices_own_refine_lands_while_a_cut_is_solving` (fairness): with a slow cut list running, a slice refine started on the dock's `Refiner` lands before the cut list ends.
  - `test_the_cut_worker_thread_is_named_nsgeo_cut`.
  - `test_deleting_the_working_cut_mid_solve_stops_the_worker` (Review Focus 5).
  - `test_closing_the_site_mid_solve_stops_the_worker` (Review Focus 5).
  - `test_opening_another_item_cancels_the_solve`.
  - In `test_plugin_refine.py`: `test_a_custom_thread_name_prefix_names_the_thread`.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
  - `Refiner`'s prefix.
  - In `CutSections`:
    - a second `Refiner(self, thread_name_prefix=CUT_THREAD_NAME_PREFIX)`, shut down in `dispose`;
    - a single-shot rest timer (`CUT_SOLVE_REST_MS`), restarted whenever the working cut's section is built or rebuilt while standing in;
    - jobs are one `CutLevelJob` per level, ordered by distance from the slice band's centre level (the dock's last `window_changed`, through `z.level_range`), with crops and plans built once per solve;
    - `on_landed` writes the row only if the fingerprint and working key still match;
    - a `CUT_REDRAW_MS` timer throttles `section_changed`;
    - `line_opened`, `cuts_changed`, `site_closed` and a fingerprint change cancel the solve.
  - The profile title follows the Global Constraints table.
- [ ] **Step 4: Run them and see them pass.**
- [ ] **Step 5: Update the guide** (`docs/guide/getting-started.md`, spec §7 and plan call 11):
  - **The toolbar table** gains **Cut**.
  - **New Step 8, "Draw a cut",** after Build slices. It covers:
    - drawing and reading a cut;
    - that a cut needs its grid shown in the Slices panel and uses the panel's interpolation settings and palette;
    - that under minimum curvature it shows kriging first, then the finished section;
    - that the map works on cuts while the cuts layer is current, and on lines otherwise;
    - picks on cuts.
  - The old Step 8 becomes Step 9.
  - **§4, Where your data lives:**
    - `survey.nsgeo.json` holds the cuts, and **Save site** writes them;
    - the **cuts** layer is redrawn from them and is read-only;
    - a cut moves with its grid, and its picks with it;
    - a pick on a deleted cut stays on the map;
    - a site with cuts does not open in nsgeo 0.3.0 or earlier.
  - It is written for archaeologists, in the guide's existing voice.
- [ ] **Step 6: Measure on Grid 1** (`needs_sunnyside` from `plugin_testing.py`), and record the numbers in `cut_sections.py`'s module docstring (spec §5), at its remembered settings (0.05 m, minimum curvature, smoothing Y 0.1 m):
  - the first preview after the panel prepared the grid;
  - a repeat preview;
  - the redraw after a settings change;
  - the time until the walkthrough-length cut (about 12 m) is solved.

  Task 1 measured 0.20 s a level for a 12 m cut at 0.05 m on the ten real lines, so expect about 40 s for Grid 1's 211 levels. If a hover under kriging takes over 100 ms, or the solve takes over a minute, stop and report rather than ship.
- [ ] **Step 7: Run the full core + pure suite, the full QGIS suite, lint and types.**
- [ ] **Step 8: Commit and push:**
  `git commit -m "feat(cuts): minimum curvature solved near the cut behind a kriging preview; the guide (cut spec §4.7, §7)"`

---

## After Task 6 (coordinator)

These are the manual checkpoints from spec §8. Track them and report them; never pass them silently.

1. **Whole-branch review** (most capable model), then a fix wave if needed.
2. **Build and walkthrough.** Deploy to a fresh QGIS profile (`ns_geo_cuts`). Hold the walkthrough on Sunnyside Grid 1 at its remembered settings as an Artifact with a results db:
   - draw a cut along the lower line, through to the higher line;
   - watch it go from kriging to minimum curvature;
   - read its depth against the bowl;
   - check it against a slice at the line's depth where they cross;
   - pick it;
   - redraw it as a new cut, delete the old one, and confirm the old picks stay on the map;
   - also: the cuts-layer switch over the 0.5 m lines; Whole site scope with "not normalised"; a grid edit moving a cut and its picks; closing with an unsaved cut;
   - with time zero (#97) in Grid 1's preset: the cut's axis starts at 0 ns, the slice band sits on the same reflection in the cut and in a crossing line, and a cut pick made before time zero was turned on is left out and counted.
3. **The help-pages ledger.** Note the new **Cut** tool in the `nsgeo-help-pages` ledger (spec §7). The help-pages branch itself is not edited.
4. **README roadmap.** Move M15 to Done on merge, per the roadmap upkeep rule.
5. **File the deferred follow-ups** from review.
