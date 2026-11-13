### Task 3: The background task

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/export_task.py`.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_export_task.py` (new).

**Interfaces:**
- Consumes: Task 1's `ExportSpec`, `run_export` and `ExportCancelled`; Task 2's writers,
  `partial_path`, `commit_partial` and `discard_partial`.
- Produces:
  - `class ExportTask(QgsTask)`:
    - constructed with `(description, spec, writer_plan, target: Path, coverage_spec: ExportSpec | None, coverage_target: Path | None, on_done: Callable[[ExportResult], None])`;
    - `run()` writes the file, then the coverage companion, each to its partial path and then
      committed;
    - `setProgress` across both, and `setDescription(f"Exporting {what}: band {k} of {n} · {grid}")`;
    - checks `isCanceled()` through `should_stop`.
  - `finished(ok)` is guarded. It calls `on_done(ExportResult(ok, cancelled, error, target, coverage_target, limit))`
    on the GUI thread in every case, including cancellation while still queued.
  - `start_export(task) -> bool` keeps the task in a module-level holder until `finished`, handles
    `addTask()` returning 0 (calls `on_done` with an error), and refuses a second export while one
    is held (returns False).

- [ ] **Step 1: Write the failing tests.**
  - It runs to completion: the target exists, `on_done` is called once with `ok`, and the holder
    is empty.
  - Cancel mid-run (cancel from a progress callback): no partial and no target, `cancelled=True`.
  - Cancel while queued: `on_done` is called synchronously.
  - An exception in `run` gives `on_done(error=…)`, with no swallowed exception.
  - An exception in `on_done` does not escape `finished`.
  - A second `start_export` while one is held returns False.
  - The live engines are untouched: a spy on a live `SliceEngine` and `SiteEngine` sees no call
    while the task runs.
  - The live panel stays usable: a slice redraw during the task succeeds.
- [ ] **Step 2: Run and see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** and lint.
- [ ] **Step 5: Commit:** `feat(export): run exports in QGIS's background-task list`.

---

