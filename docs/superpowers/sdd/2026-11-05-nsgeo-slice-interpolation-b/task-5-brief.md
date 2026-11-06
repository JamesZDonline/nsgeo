### Task 5: Exports with progress and cancel; the guide

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py`: `ExportCancelled(Exception)`, and an `export_slices(..., progress=None)` parameter.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/site_export.py`: an `export_site(..., progress=None)` parameter.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`:
  - one `_export_progress(title: str, total: int)` helper that returns `(callback, dialog)`;
  - both exports use it;
  - both exports call `self.slices_dock.refiner.cancel()` first;
  - cancel and This grid failure remove the partial file (plan call 11).
- Modify: `docs/guide/getting-started.md`, step 4, Method bullet: add **Minimum curvature**.
- Modify: `packages/nsgeo-qgis/tests/qgis/conftest.py` only if the modal guard needs to know about `QProgressDialog`. It is shown, not `exec()`'d, so it should not.
- Test: `tests/qgis/test_plugin_slice_export.py`, `tests/qgis/test_plugin_site_export.py`, `tests/qgis/test_plugin_site_scope.py` (the plugin-level site export tests live there) and `tests/qgis/test_plugin_slice_export_dialogs.py`.

**Interfaces:**
- Produces:
  ```python
  class ExportCancelled(Exception): ...   # slice_export.py; site_export imports it

  def export_slices(engine, path, thickness_levels, step_levels, velocity, finish, *,
                    writer=None, progress: Callable[[int, int], bool] | None = None) -> ExportPlan
  def export_site(site_engine, path, thickness_levels, step_levels, *, ..., writer=None, left_out=None,
                  progress: Callable[[int, int], bool] | None = None) -> SiteExportPlan
  ```
  - `progress(done, total)` is called before each band, with `done` = bands written so far, and once more as `(total, total)` at the end.
  - A False return raises `ExportCancelled` before the next band is computed.

- [ ] **Step 1: Write the failing tests.**
  - **`test_export_reports_progress_for_every_band`**
    - A recording callback sees `(0, n), (1, n), …, (n, n)` for an n-band This grid export, and likewise for the site.
  - **`test_a_cancelled_export_leaves_no_file_and_adds_no_layer`** (Review Focus 5; This grid and Whole site)
    - Patch `plugin._export_progress` to return a callback that returns False at `done == 1`.
    - The target file does not exist afterwards, no layer is added, and the message bar says `export cancelled` at Info.
    - A file the dialog chose to replace, and that the export never reached, is left untouched (the existing mtime rule).
  - **`test_a_failed_slice_export_leaves_no_file`**
    - A writer that raises after the first band: no file, and the existing Critical message.
  - **`test_a_minimum_curvature_export_records_its_method_and_never_writes_a_preview`**
    - With `min_curvature` and `engine._last_solve_ms` forced to 500, the This grid export has `NSGEO_INTERPOLATION == "min_curvature"`.
    - Every band equals the engine's `finish` of that band's window after `to_north_up`, not its `preview`.
  - **`test_an_export_cancels_a_running_refine`**
    - With a looping job running in `dock.refiner`, starting an export leaves `dock.refiner.busy` False before the first band.
  - **`test_the_progress_dialog_is_cancellable_and_window_modal`**
    - `_export_progress("Export GeoTIFF", 5)` returns a dialog with `windowModality() == Qt.WindowModality.WindowModal`, `minimumDuration() == 500` and a maximum of 5.
    - Calling `dialog.cancel()` makes the callback return False.

- [ ] **Step 2: Run them and see them fail.** Run the four files with the QGIS command. Expected: FAIL. The `progress` parameter, `ExportCancelled` and `_export_progress` don't exist.

- [ ] **Step 3: Implement.**
  - **The core of the exporters.** The `progress` call sits in each exporter's band generator, so the writers stay unchanged.
  - **The plugin.** It:
    - cancels the refiner;
    - catches `ExportCancelled` separately from other exceptions;
    - removes the partial file by the site export's mtime rule, now shared by both exports;
    - reports `export cancelled` at Info;
    - always closes the dialog, in a `finally`.
  - **The guide paragraph**, in the step 4 Method bullet, after the IDW sentence: *"Pick **Minimum curvature** for the smoothest surface through the lines, the method Surfer users often know. It can overshoot a little beside a strong contrast, which shows as a faint ring of the opposite sign between lines. It is solved for each slice, so it is slower. At a fine cell you see kriging while the depth moves, and minimum curvature replaces it a moment after the depth rests. The colour stretch can shift once more when minimum curvature has measured it. An export always uses minimum curvature, shows its progress, and can be cancelled."*

- [ ] **Step 4: Run the tests and see them pass**, then all four verification commands. Expected:
  - core + pure: passes, with 3 skipped;
  - QGIS: passes;
  - lint and types clean.

- [ ] **Step 5: Commit and push.**
  ```bash
  git commit -m "feat(export): progress and cancel for both exports; minimum curvature in the guide"
  git push origin nsgeo-slice-interpolation-b
  ```

---

## After Task 5 (coordinator)

These are the manual checkpoints from spec §10. Track them and report them; never pass them silently.

1. **Build and walkthrough.** Deploy to a fresh QGIS profile, then hold the walkthrough on the user's real grids (Sunnyside) as an Artifact with a results db. Cover:
   - minimum curvature at defaults: no holes, and a skipped line blank;
   - the overshoot ring, judged acceptable or not (tension is the first follow-up if not);
   - live dragging at 0.2 m;
   - at a fine cell (0.05 m):
     - the kriging preview while dragging;
     - the refine landing after a pause;
     - moving on mid-refine;
     - the stretch settling;
   - Whole site, the same at a fine cell;
   - an export with progress and a cancel;
   - closing QGIS mid-refine;
   - a saved cube.
2. **Surfer comparison (spec §10.2).** The user compares nsgeo's kriging and minimum curvature, at defaults, against their Surfer grids. The question is "same ballpark". This gate is required for B.
3. **File the deferred follow-ups** from review. Note that the faster solver (multigrid) is already filed as #111.
