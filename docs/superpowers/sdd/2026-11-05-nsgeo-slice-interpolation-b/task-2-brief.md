### Task 2: The background worker

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/refine.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`: add `REFINE_POLL_MS = 20`.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_refine.py`, new. It is in the QGIS tier because `QTimer` needs a Qt event loop.

**Interfaces:**
- Consumes: Task 1's `SolveStopped`, and `plan_curvature` for the responsiveness test.
- Produces, in `refine.py`:
  ```python
  class RefineJob(Protocol):
      def run(self, should_stop: Callable[[], bool]) -> None: ...   # worker thread; keeps its own result

  class Refiner:
      def __init__(self, parent: QObject) -> None: ...   # the poll QTimer is parented to `parent`
      def start(
          self,
          jobs: Sequence[RefineJob],
          on_landed: Callable[[RefineJob], None],
          on_error: Callable[[str], None],
      ) -> None: ...
          # cancels whatever is running, then runs `jobs` in order on the worker thread;
          # on_landed(job) runs on the GUI thread after each job finishes, in order
      def cancel(self) -> None: ...    # the running job stops at its next iteration; nothing more of that list lands
      @property
      def busy(self) -> bool: ...      # a started list has jobs that have not landed; False before the LAST job's on_landed runs
      def shutdown(self) -> None: ...  # cancel, then join the worker; safe to call twice
  ```

- [ ] **Step 1: Write the failing tests** in `test_plugin_refine.py`. They use small fake jobs: a `threading.Event`-driven job, a job that records `threading.get_ident()`, a job that raises, and a job that loops until `should_stop()`. Add one helper, `_pump_until(predicate, timeout_s)`, which calls `QCoreApplication.processEvents()` until the predicate holds and fails the test at the timeout.
  - `test_jobs_land_in_order_on_the_gui_thread`
    - Three jobs land in list order.
    - Each `run` ran on a thread whose name starts with `nsgeo-refine`.
    - Each `on_landed` ran on `threading.main_thread()`.
  - `test_busy_is_false_when_the_last_job_lands`
    - `busy` is True right after `start`.
    - Inside the last `on_landed`, `busy` is already False.
  - `test_cancel_stops_the_running_job_and_drops_the_rest`
    - A list of a looping job then a recording job.
    - After `cancel()`, the looping job returns within 1 s, `busy` is False, nothing lands, and the recording job never ran.
  - `test_a_new_start_supersedes_the_old_one`
    - Start list A with a job that blocks on an Event, then start list B. Release A's Event.
    - Only B's jobs land.
  - `test_only_one_job_runs_at_a_time`
    - Five rapid `start` calls of jobs that increment and decrement a shared counter under a lock, recording the maximum.
    - The maximum is 1.
  - `test_a_job_error_is_reported_not_raised`
    - A list of a raising job then a recording job.
    - `on_error` receives the exception's message, the recording job never runs, and `busy` ends False.
    - No `sys.excepthook` or `sys.unraisablehook` call is recorded.
  - `test_a_raising_on_landed_is_contained`
    - `on_landed` raises. The next job still lands.
    - The error goes to `_log`, not to `sys.excepthook`.
  - `test_shutdown_joins_the_worker`
    - Shut down while a looping job runs.
    - Afterwards, within 2 s, no thread named `nsgeo-refine*` is alive, and a second `shutdown()` is harmless.
  - `test_the_gui_thread_keeps_running_during_a_solve`
    - Run a real solve as a job: `plan_curvature` on a 500 × 500 synthetic at 0.1 m (lines 0.5 m apart), taking about 0.5 s.
    - A 10 ms `QTimer` on the GUI thread fires at least 10 times before the job lands.
    - **If this is flaky, report it. Do not loosen it silently.**

- [ ] **Step 2: Run it and see it fail.** Run `test_plugin_refine.py` with the QGIS command. Expected: FAIL, because `nsgeo_qgis.refine` does not exist.

- [ ] **Step 3: Implement `Refiner`** (plan call 6).
  - The module docstring says why this is a thread and not a `QgsTask`, and that the worker touches only its job.
  - The poll slot guards its body. `on_landed` and `on_error` exceptions go to `_log` (`from nsgeo_qgis.log import log as _log`, as `slice_layer.py` does).

  The parts the tests don't fully determine:

  ```text
  start(jobs, on_landed, on_error):
      cancel(); generation += 1; stop = threading.Event(); remaining = len(jobs)
      executor.submit(run_list, generation, jobs, stop)   # one worker: a cancelled list ends its iteration first
      poll.start(REFINE_POLL_MS)
  run_list (worker):
      for job in jobs:
          if stop.is_set(): return
          try: job.run(stop.is_set)
          except SolveStopped: return
          except Exception as exc: done.put((generation, None, str(exc))); return
          done.put((generation, job, None))
  poll (GUI thread):
      drain `done` (a queue.SimpleQueue); skip entries from an older generation
      error → remaining = 0, on_error(message);  job → remaining -= 1, then on_landed(job)
      stop the timer once nothing is running and the queue is empty
  cancel(): stop.set(); generation += 1; remaining = 0
  shutdown(): cancel(); executor.shutdown(wait=True, cancel_futures=True); poll.stop()
  ```

- [ ] **Step 4: Run the tests and see them pass**, then the full QGIS command and lint. Expected: all pass.

- [ ] **Step 5: Commit and push.**
  ```bash
  git commit -m "feat(slices): a background worker for minimum-curvature solves (interpolation spec §7)"
  git push origin nsgeo-slice-interpolation-b
  ```

---

