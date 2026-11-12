### Task 2: Per-line values in nsgeo-core

Adds C4 and C13 (spec §7.4): own values, *changes partway along* and *no clear match*. This is the research-heavy task, so it gets an opus implementer.

**Start from the prototype.** `docs/superpowers/notes/2026-11-11-destagger-measure-spike/per_line_block.py`, and the note's **Per-line prototype** section, say what it gets right and wrong. The caches it needs can be rebuilt by `destagger_spike.py` (spike note, "Running the scripts"). The method is the builder's (spec §11), but the behaviour is fixed:
- **A line gets its own value only if it is clear and repeatable.** At least one pair of independent halves (shallow/deep bins, or first/second half along) has clear peaks that agree.
- **A half without a clear peak neither confirms nor counts against the line** (C13).
- **Changes partway along:** both along halves are clear and disagree by much more than noise. The line keeps the grid value.
- **No clear match:** the whole-record peak is not clear. The line keeps the grid value.
- **A bad line does not drag its neighbours.** A run of adjacent off lines is solved jointly. A skew (a shift that grows steadily across the lines) produces no own values.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/destagger/per_line.py`, `packages/nsgeo-core/tests/test_destagger_lines.py`
- Modify: `measure.py` (calls the per-line solve after the grid value; per-line results replace Task 1's all-GRID statuses), `test_destagger_grid.py` (remove `test_every_measured_line_gets_the_grid_value`)

**Interfaces:**
- Consumes: Task 1's types and `profiles.py`.
- Produces: no new public names. `LineResult.status` may now be OWN (with `destagger` = grid value + its own correction), CHANGES or NO_MATCH (with `destagger` = the grid value). Sign: a line whose features sit `r` metres ahead along its travel, relative to its corrected neighbours, gets `grid − r`.

- [ ] **Step 1: Write the failing tests** in `test_destagger_lines.py`. They are real data only, and `moved` is 0-based. `FILE__031` is index 30.
  - Module-scoped fixtures share the base results (Grid 1 unfitted and fitted, Grid 2 unfitted and fitted), so each 60-line measurement runs once.
  - `test_a_line_moved_forward_is_recovered`: Grid 1 unfitted, `moved={30: 0.30}`. `FILE__031`'s value is within 0.05 of (its base value − 0.30). `FILE__030` and `FILE__032` keep their base status, and their values stay within 0.02.
  - `test_a_line_moved_back_is_recovered`: the same with `moved={30: -0.50}`, so the target is the base value + 0.50, within 0.05. The prototype is 7 cm off here (P11).
  - `test_two_adjacent_moved_lines_are_both_recovered`: `moved={30: 0.30, 31: 0.30}`. Both are within 0.05 of base − 0.30 (P10).
  - `test_a_skew_creates_no_own_values` (P9): `skew=0.02`, on Grid 1 unfitted and fitted.
  - `test_most_grid1_lines_keep_the_grid_value`: unfitted and fitted, at least 80% of lines are not OWN, or the builder's pinned share, never lower than 75%.
  - `test_unfitted_file_011_gets_no_own_value`: status in {CHANGES, NO_MATCH}.
  - `test_grid2_clearly_off_lines_get_own_values`:
    - Unfitted: `FILE__045`, `FILE__027` and `FILE__028` are OWN with `destagger > grid + 0.25`.
    - Fitted: `FILE__051` is OWN with `destagger > grid + 0.10`, and `FILE__059` is OWN with `destagger < grid − 0.10`.
    - Size tolerances are pinned around the measured values. The prototype gave +0.881, +0.665 and +0.687 unfitted, and +0.147 and −0.287 fitted.
  - `test_grid2_fitted_file_050_gets_no_own_value`: status in {CHANGES, NO_MATCH}.
  - `test_most_grid2_lines_keep_the_grid_value`: at least 70%, or the builder's pinned share if higher.
  - `test_per_line_results_are_deterministic`: Grid 2 fitted, measured twice, gives equal results.
- [ ] **Step 2: Run them and see them fail.** Every line is GRID, so the own-value and status tests fail.
- [ ] **Step 3: Implement `per_line.py`.** Tune the thresholds on Grids 1 and 2, then name each one as a module constant with a comment saying what it was tuned on.
- [ ] **Step 4: Run** the two destagger test files, then the full core+pure, lint and types. All green. If a spec tolerance cannot be met, leave that test failing with a short comment, and report `DONE_WITH_CONCERNS` with the numbers. Do not loosen the test (P11).
- [ ] **Step 5: Write a results table** into the spike note, as a new section **Per-line results (built)**. For each grid and placement, give: the grid value; how many lines are OWN, CHANGES, NO_MATCH and NOT_MEASURED; each OWN line's value; and the injected-error results. Use file names and metres only.
- [ ] **Step 6: Commit and push:** `feat(core): per-line destagger values where a line is clearly off (#159)`.

---

### Checkpoint C14 (coordinator and author; a human gate)

Stop here and ask the author. Dialog work does not start until they answer.

- [ ] Write the line-strip pictures to the session scratchpad, never to the repository: Grids 1 and 2, unfitted and fitted, at 14.9–19.7 ns. Adapt the spike's `destagger_panels.py` to call `nsgeo.destagger` and draw three panels per case: no destagger; the grid value on every line; the grid value plus per-line values.
- [ ] Send the author the pictures and Task 2's results table. Include anything Task 2 reported as a concern (the −0.50 case, the Grid 2 own-value share), and ask:
  - whether the per-line values look better than the grid value alone;
  - whether any own value looks wrong;
  - whether the tolerances are acceptable.
- [ ] Record the answer in the ledger. "Worse overall" sends the plan back to Task 2 (spec C14). Agreed tolerance changes go into the tests, with the author's words cited in a comment.

---

