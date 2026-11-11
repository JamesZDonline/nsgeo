### Task 4: Fit at import, and the documentation

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/lookup.py`
  - `ImportOptions` gains `fit_to_grid: bool = False`.
  - `ImportRow` gains `scale: float = 1.0`.
  - `recompute_offsets` sets `row.scale` and the note.
  - `rows_to_lines` passes `scale=row.scale`.
  - `fit_scale` and `span_m` are imported from `nsgeo_qgis.line_edit`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/import_dialog.py`
  - Add `self.fit_to_grid = QCheckBox("Stretch or compress each line to the grid's length")` on a form row labelled `Line length`, after `Start along`. It is unchecked by default, carries the import tooltip, and `toggled` re-plans the rows the way the other option widgets do.
  - `options()` passes `fit_to_grid`.
- Modify: `docs/guide/getting-started.md`
  - **Step 3** gains one sentence on the checkbox.
  - **"Fixing lines after import"** gains a short paragraph. Cover **Scale**, **Destagger (m)** and **Fit to grid edges**: what each is for, in the user's terms (wheel or terrain error; stagger between lines walked out and back), and that a fitted line stays fitted when the grid's length changes. Also say that the Note flags a scale more than 20% from 1, and that the destagger moves every line forward along its own direction of travel, so setting it on every line is the usual first step.
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_lookup.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_import_dialog.py`

**Interfaces:**
- Consumes: Task 2's `fit_scale(span, length)` and `span_m(n_traces, traces_per_metre)`. Task 1's `GridPlacement(..., scale=)`.
- Produces: `ImportOptions.fit_to_grid` and `ImportRow.scale`.

- [ ] **Step 1: Write the failing tests.**
  - **Pure (`test_pure_lookup.py`), `test_real_campus_lines_fitted_to_a_10_m_grid_end_on_its_far_edge`:**
    - **Setup:** plan the ten `CAMPUS_LINES` (import `REAL_DZT` from `plugin_testing`; skip when empty) with `ImportOptions(grid_id="G", axis="y", spacing=0.5, grid_size_along=10.0, fit_to_grid=True)`.
    - **Action:** `recompute_offsets`, then `rows_to_lines`.
    - **Assert:**
      - Every line's `distance_along()` starts on its edge and ends on the other one (abs 1e-9).
      - FILE__008's row scale is about `10 / 11.08` (rel 1e-3).
      - Every note contains `fitted to the grid's 10.00 m` and none contains `exceeds grid size`.
  - **`test_fit_off_leaves_scale_one_and_keeps_the_exceeds_note`:** the same lines with the default options. Every scale is `1.0`, and FILE__008's note contains `exceeds grid size along y`.
  - **`test_fit_without_a_grid_length_says_so`:** `grid_size_along=None` with `fit_to_grid=True`. The scale stays `1.0`, and the note contains `cannot be fitted without a known grid length`.
  - **QGIS (`test_plugin_import_dialog.py`), `test_the_fit_checkbox_imports_fitted_lines_and_is_off_by_default`:**
    - **Assert:** the box starts unchecked.
    - **Action:** check it.
    - **Assert:** the Note column shows the fitted text.
    - **Action:** import.
    - **Assert:** the session's lines carry the row scales.
    - Follow the file's existing import-flow helpers.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
  - The note uses `_merge_note`, with a new marker `"fitted to the grid's"`. Turning fitting on clears the `exceeds grid size along` component, and turning it off clears the fitted one.
  - A row that is not placeable keeps scale 1.
- [ ] **Step 4: Run core + pure and the import dialog file. All pass, and the skip count has not risen.** Then run lint and types.
- [ ] **Step 5: Update the guide**, then commit `feat: fit lines to the grid at import; guide for Scale, Destagger and Fit (#3, #47)`, then push.

---

## After Task 4 (coordinator)

1. **Run the full QGIS tier and record the counts.** Compare them with the baseline.
2. **Run a whole-branch review on opus**, from a scratch copy.
3. **Deploy to a new profile, `ns_geo_placement`** (a copy of `ns_geo`, `dev_link` to this worktree).
4. **Build the walkthrough** as a claude.ai Artifact with `db`. **Stop for the user's results.**
   - Run it on the user's own grids. One check is the campus ten fitted to a 10 m grid.
   - Another check runs on the 60-line `with-dzg` survey placed by tape: fit, then a hand-typed destagger around 0.15 m per line. The strongest feature at 22–28 ns should tighten from a sawtooth.
   - Copy any site folder before it is used.
5. **The README roadmap:** In progress names this branch from its first commit. At merge, the row moves to Done.
6. **Then the user decides** whether to merge chunk A on its own or carry on to chunk B (Measure) on this branch first.
