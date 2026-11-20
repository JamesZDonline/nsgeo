### Task 3: The shared stretch as a job, equal to today's

**Files:**
- Create: `P/stretch_jobs.py` (`StretchJob`, `WindowSource`).
- Modify:
  - `P/slices_engine.py`: `window_source`, `stretch_job`.
  - `P/site_engine.py`: `stretch_job`.
  - `P/ui/refine_flow.py`: `held_stretch`, `land_stretch`.
- Test: `T/qgis/test_plugin_stretch_jobs.py` (new), `T/qgis/test_plugin_refine_flow.py`.

**Interfaces:**
- **Consumes:** Task 2's `FillJob` (its `fill` and `preview`, read in `run`, after the fill jobs ahead of it on the same worker have run).
- **Produces `SliceEngine.window_source() -> WindowSource`.** It is a frozen snapshot taken on the GUI thread, after `_ensure_plans()` (and `cube()` in resident mode). It holds the frame, the z axis, and either the cube or the `(lines, plans)` lists.
  - `WindowSource.slice(window) -> (values, coverage)` is pure numpy, as `SliceEngine._slice`.
  - Read `binning.stream_slice` and `SliceCube.slice_levels`, and confirm neither writes its inputs. If one does, the snapshot copies what it writes. Say which in the report.
- **Produces `SliceEngine.stretch_job(thickness_levels: int, clip, finish: SliceFinish, *, fill: FillJob | None = None) -> StretchJob`.**
- **Produces `SiteEngine.stretch_job(thickness_ns: float, clip, *, finish, method, manual, fills: Mapping[str, FillJob] | None = None) -> StretchJob`.** It captures, on the GUI thread:
  - each ready grid's `WindowSource`;
  - its grid windows at `_limit_windows_ns`;
  - its `FinishSettings`;
  - its held fill and preview, or the grid's `FillJob` when one is given;
  - a copy of its solved cache;
  - the seams for `method == "edge"`, and the method, the manual gains and the clip.
- **Produces `StretchJob`:**
  - Attributes: `limit: float | None`, `final: bool`, `fraction: float`.
  - `run(should_stop)` measures exactly what `stretch_limit` measures today:
    - the same windows;
    - `normalise` on the binned values;
    - `a * draw + b`;
    - `limit_over_slices`.

    The draw is decided by method:
    - **Not minimum curvature:** `finish_slice` with the grid's fill. Final.
    - **Minimum curvature:** if every window's `solve_key` is in the captured solves, they are smoothed. Final.
    - **Minimum curvature, any window unsolved:** the kriging preview is used. Provisional, `final = False`.

    A window whose `coverage > 0` differs from the fill's `populated` gets a fill built inside the job, with `should_stop`, and never installed.
  - `land() -> bool` returns True. The scope stores the result.
- **Produces, on `RefineFlow`:**
  - `held_stretch(key) -> float | None`: the held limit for `key`. It arms the rest for a provisional stretch exactly as `stretch_limit` does today.
  - `land_stretch(key, limit, final) -> None`.

  `stretch_limit(key, measure)` stays for the callers out of scope.

- [ ] **Step 1: Write the failing tests.** In `test_plugin_stretch_jobs.py`, each compares `job.limit` and `job.final` with today's synchronous `stretch_limit`. `limit` is compared with `==` and must be bit-equal.
  - `test_this_grids_stretch_job_equals_stretch_limit`, parametrised over:
    - IDW resident;
    - kriging streaming;
    - `min_curvature` with nothing solved, which gives `final is False` and equals `shared_limit(..., preview=True)`;
    - `min_curvature` with every window solved through `stretch_solves`, which gives `final is True`.
  - `test_the_sites_stretch_job_equals_stretch_limit`, parametrised over normalisation `none` / `background` / `edge`, with manual gains `{"B": 2.5}`, and over IDW and `min_curvature` unsolved.
  - `test_a_window_with_other_covered_cells_gets_its_own_fill`: a streaming fixture where one line ends early, so the last window's coverage differs. Equal to `stretch_limit`, and afterwards the engine still holds the same fill object as before (`engine._weights[1] is held`).
  - `test_a_stretch_job_reads_its_fill_jobs_results`: a site with B's fill dropped. Run `[fill_job_B, stretch_job(fills={"B": fill_job_B})]` in order and get the same limit as the synchronous measure after B's fill is held.
  - `test_a_stopped_stretch_job_raises`.
- [ ] **Step 2: In `test_plugin_refine_flow.py`, write** `test_a_landed_stretch_is_held_for_its_key_only` and `test_a_provisional_landed_stretch_arms_the_rest`.
- [ ] **Step 3: Run them and see them fail.** Expected: AttributeError.
- [ ] **Step 4: Implement.** Factor the per-window measurement so today's `_measure` and `shared_limit` and the job share one pure function. A second copy would drift. Today's synchronous paths keep their results.
- [ ] **Step 5: Run** the two files, `test_plugin_site_engine.py`, `test_plugin_slices_engine.py`, `-m real_data` and ruff. Expected: all pass.
- [ ] **Step 6: Commit:** `feat(slices): the shared stretch measured by a job, equal to today's (#193)`.

---

