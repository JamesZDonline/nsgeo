### Task 3: Measure in Edit lines

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/destagger_job.py`, `packages/nsgeo-qgis/tests/pure/test_pure_destagger_job.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_edit_lines_measure.py`
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/edit_lines_dialog.py`
  - `.github/workflows/ci.yml` (mypy list)
  - `docs/guide/getting-started.md` (a paragraph after the destagger paragraphs: what Measure does, that it fills the selected rows and the box, that nothing changes until OK, and that it is a starting point to adjust)
  - `README.md` (the features bullet: "…and destaggered along its direction of travel, by an amount typed or measured from the data.")

**Interfaces:**
- Consumes: Task 1's `envelope_bins`, `MeasureLine`, `measure_destagger`, `DestaggerResult`, `LineStatus` and `MeasureStopped`; `nsgeo_qgis.refine.Refiner`.
- Produces, in `destagger_job.py`:

```python
@dataclass(frozen=True)
class JobLine:
    key: str
    label: str
    path: Path
    header: DztHeader
    placement: GridPlacement     # LineEdit.placed(frames) at press time

class MeasureJob:                # a RefineJob
    def __init__(self, lines: Sequence[JobLine], cached: Mapping[str, EnvelopeBins]) -> None: ...
    prepared: dict[str, EnvelopeBins]    # cached plus newly read
    unreadable: dict[str, str]           # key -> str(error)
    result: DestaggerResult | None
    stopped: bool
    progress: tuple[int, int]            # (lines read, lines to read); written by the worker
    def run(self, should_stop: Callable[[], bool]) -> None: ...

def box_value(result: DestaggerResult) -> float | None: ...   # the axis with more lines_used (C11); None if it failed
def measure_summary(result: DestaggerResult, filled: Sequence[str],
                    unreadable: Mapping[str, str], labels: Mapping[str, str]) -> str: ...
```

`run`:
- Reads only the lines missing from `prepared`, with `read_samples(path, header)[0]` then `envelope_bins` (P4).
- Catches `OSError`, `DztError` and `ValueError` per line into `unreadable`.
- Checks `should_stop()` before each read.
- Then calls `measure_destagger` on the prepared lines. On `MeasureStopped`, or on a stop between reads, it sets `stopped = True` and returns normally.

**Dialog changes:**
- `measure_button` sits after `set_destagger_button`, with tooltip `MEASURE_TIP`.
- `self._measurer = Refiner(self)`; a `QTimer` at `MEASURE_PROGRESS_MS = 200` shows progress.
- `self._bins: dict[str, EnvelopeBins]` caches prepared lines for the dialog's life (C8).
- `measure()` starts or stops a run.
- On land, check in this order: the session's `site` is still the object captured at press; then the snapshot. The snapshot is every on-grid row's `dataclasses.replace(placed, travel_shift=0.0, label=None)`, keyed by row key; the run's must equal the current one. Only then fill the targets (P5, P6) and the box, and `_refresh(summary)`.
- `_update_panel` enables the bulk panel when there is a selection or `self._measurer.busy` (P8).
- `done(r)` is overridden to `self._measurer.shutdown()` before `super().done(r)`. Every slot added is guarded.

- [ ] **Step 1: Write the failing pure tests** in `test_pure_destagger_job.py`, with synthetic DZTs from `plugin_testing.synthetic_dzt` and constructed `DestaggerResult`s:
  - `test_the_job_reads_only_lines_it_has_not_prepared`: one key cached, so one file is read. Check by monkeypatching `read_samples` with a counting wrapper.
  - `test_an_unreadable_file_is_recorded_not_raised`: a deleted path appears in `unreadable`, and the rest are measured.
  - `test_a_stop_between_reads_ends_the_job_quietly`: `stopped` is True, `result` is None, and nothing raises.
  - `test_a_multi_channel_file_is_measured_on_its_first_channel`: written with `n_channels=2`. The job's prepared bins equal `envelope_bins` of channel 0.
  - `test_box_value_takes_the_axis_with_more_lines`, and None when that axis failed.
  - `test_summary_words`: the exact strings from Global Constraints for one axis OK; two axes; one failed axis; own, changes, no-match and not-measured groups; an unreadable file; and more than 6 names (P12).
- [ ] **Step 2: Write the failing QGIS tests** in `test_plugin_edit_lines_measure.py`.
  - The fixture site is built like `test_plugin_edit_lines_dialog.py`'s `_site`, with 6 synthetic lines.
  - UI-plumbing tests monkeypatch `nsgeo_qgis.destagger_job.measure_destagger` with a canned function. It can block on a `threading.Event` the test sets, and it records the `MeasureLine`s it was given.
  - Tests wait with `spin_until(lambda: not dialog._measurer.busy)`.

  The tests:
  - `test_measure_fills_the_selected_rows_and_the_box`: rows 0–3 are selected. They get their canned values (one OWN), shaded `CHANGED`. Rows 4–5 are untouched. The box shows the grid value, and the status equals `measure_summary(...)`.
  - `test_measure_uses_the_tables_pending_placement`: with Fit to grid edges pending on the selection, the `MeasureLine` placements carry the fitted scale.
  - `test_an_edit_while_measuring_discards_the_results`: while the canned function blocks, change one row's Start. Then release it. No Destagger cell changes, and the status is the Discarded copy.
  - `test_a_destagger_edit_while_measuring_does_not_discard`: change a Destagger cell during the run. The results land.
  - `test_stop_changes_nothing`: press Measure, then press it again (it reads `Stop`). Nothing changes, the status is the Stopped copy, and the button reads `Measure` again.
  - `test_closing_the_dialog_stops_the_measure`: `reject()` during the run. Afterwards no result lands, and no `nsgeo-refine` thread is left alive.
  - `test_stop_stays_reachable_when_the_selection_is_cleared` (Review Focus 1).
  - `test_a_site_closed_while_measuring_is_not_written_to` (Review Focus 2): call `session.close_site()` during the run. The status is the Site-changed copy, and nothing raises.
  - `test_an_unreadable_line_is_named_and_the_rest_are_measured` (Review Focus 3): uses the real `measure_destagger`. Delete one synthetic file after opening; the summary names it with `could not be read:`.
  - `test_a_row_moved_to_another_grid_is_left_out` (Review Focus 4): the canned function did not receive that key, and the row is not filled.
  - `test_measuring_twice_reads_each_file_once_and_gives_the_same_values` (C8; count reads as in the pure test).
  - `test_a_one_way_grid_says_there_is_nothing_to_measure`: the real `measure_destagger` on all-forward synthetic lines. The status is `Could not measure: every line was walked the same way, so there is no stagger to measure. Nothing was changed.`
  - `test_two_axes_fill_each_row_from_its_own_axis` (C11, canned).
  - `test_measure_on_the_real_survey` (real data, skip without `GPS_LINES`): 60 lines unfitted on a 30 m grid. Ctrl+A, then Measure. The box is within 0.02 of +0.15, and every row's Destagger cell is filled. Allow 120 s.
- [ ] **Step 3: Run both files and see them fail.**
- [ ] **Step 4: Implement** `destagger_job.py` and the dialog changes. Update `ci.yml`, the guide and the README.
- [ ] **Step 5: Run** the two new files, `test_plugin_edit_lines_dialog.py` and the pure tier, then lint and types. Leave the full QGIS tier to the coordinator.
- [ ] **Step 6: Commit and push:** `feat(plugin): Measure the destagger in Edit lines (#159)`.

---

