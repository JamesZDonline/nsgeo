# Shared context for every task (extracted from the plan; the plan file itself is not yours to read)

Spec (binding authority): docs/superpowers/specs/2026-10-30-nsgeo-line-editing-design.md

## Calls made while writing this plan (check these)

- **A dragged pick goes back to its line when the layer's edits are saved** (spec §9, the first option). Re-deriving runs after `afterCommitChanges`. While the layer is still in editing mode, the dragged point shows where it was dropped. Attributes stay editable, and nothing is refused at commit.
- **Following never reads or touches the edit buffer.** It reads and writes committed rows through the provider. A row added in editing mode follows once it is saved. A buffered attribute edit is committed field by field, so it survives a provider write to other fields (pinned by a test).
- **Following emits no `picks_changed`.** The profile draws picks by trace and time, which following never changes, and the refresh that runs it is already driven by `lines_changed`/`grids_changed`.
- **A label-only edit does not re-prepare a slice source.** The engine compares placements without their label.
- **A moved line joins its new grid at the end of the survey order,** the way an imported line does.
- **`SliceEngine.set_source` leaves out a key whose line now sits on another grid,** and reports it by name. This guards the one path that could still hand an engine a stale choice: a Whole site engine re-queued from a source the dock has not resent yet.
- **The Edit lines table does not re-read the site while it is open.** OK re-checks everything (spec call 14). There is no live refresh of rows.
- **When OK skips a line, it still applies the rest and closes.** The message bar names each skipped line. That is how "the dialog names it" (call 14) reaches the user once the dialog has closed.
- **Copy:**
  - The report when a site opens: `updated {n} pick(s) to sit on their lines, at the current velocity`.
  - A grid length change: `{grid} is now {L:.2f} m along {axis}; its {n} reversed line(s) moved with the far edge.` This is the spec's example with the axis named, because a grid can hold lines on both axes.

## Global Constraints

- `nsgeo_qgis/line_edit.py` imports no Qt and no `qgis`. It joins the mypy list in `.github/workflows/ci.yml` and the types command below.
- The plugin imports Qt only through `qgis.PyQt`. `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py` and `test_no_orphan_signals.py` stay green. Every new signal has a `connect`.
- Every slot connected to a signal, and every Qt-invoked override, guards its own body and reports through `_log` or `status`. It never raises. Read the module docstrings of `layers.py`, `session.py`, `slices_engine.py`, `ui/slices_dock.py` and `ui/import_dialog.py` before touching them.
- **`picks` is authored data.** It is written only through the loaded layer's data provider, never through a second OGR handle. Following never truncates, rebuilds or re-creates the table, and never changes `trace`, `time_ns`, `stack_json`, `note`, `created`, `feature_id` or `seq`.
- **One change is one dirty mark and one `lines_changed`,** however many lines it touches (the `remove_lines` pattern).
- **Dialogs are modeless:** `show()` plus `finished`, never `exec()`. OK re-checks the site's identity and the grid before writing.
- **Numbers:**
  - `START_TOLERANCE_M = 0.05`. This is the Note's "a few centimetres".
  - `SAME_M = 1e-9`. Two placements whose floats differ by no more than this are the same placement.
- **Comments and docstrings** follow the file they are in. They say why, and cite the spec as `(line editing spec §4.4)`.
- **Shared-worktree safety.** Reviewers and any mutation testing work on a scratch copy, never this worktree. Set `PYTHONDONTWRITEBYTECODE=1` for every test run.
- **Tool versions:** ruff 0.17.1 and mypy 2.4.0, as pinned in CI.
- **Commits:**
  - End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  - Push each commit to `origin nsgeo-line-editing` as it is made.
- **Milestone B has merged** (main 61c2336, merged into this branch at ac4e203). The line above about `.worktrees/nsgeo-slice-interpolation-b` no longer applies: build on the slices code as it is in this worktree.
- **Do not touch `.worktrees/nsgeo-slice-interpolation-b`.** It is being built and changes the same slices files as Task 3. Whichever branch merges second resolves the overlap (spec call 13).

## Verification commands (exactly these, from the worktree root)

- **core + pure:** `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider`
- **qgis:** `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:cacheprovider -p no:xonsh`
  - This takes about 11 minutes. Run single files while iterating.
- **lint:** `.venv/bin/ruff check . && .venv/bin/ruff format --check .`
- **types:** `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py packages/nsgeo-qgis/nsgeo_qgis/line_edit.py`

## Review Focus

These are the inputs most likely to hurt a user that the spec's own tests don't cover. Each is pinned by a test in the task named.

1. **Flipping a line twice, or moving it away and back.** Float arithmetic gives `15 - (15 - 0.3) = 0.3000000000000007`. The row must read as unchanged: no highlight, not counted and not written. Pinned by Task 2 `test_flipping_twice_is_no_change_at_all` and Task 4 `test_flip_sends_start_to_the_other_edge_and_back`.
2. **Grids interleaved in the survey order.** This happens when Grid B was imported between two batches of Grid A. Reordering A must keep B's lines in their own slots. Pinned by Task 2 `test_order_reorders_only_the_grids_own_slots`.
3. **A picks row the spec never mentions.** Two kinds: a row digitised by hand with no trace, and a pick whose trace lies past the end of its line. The first is left alone. The second sits on the last trace with no distance. Neither stops the other picks following. Pinned by Task 1 `test_a_hand_digitised_row_with_no_trace_is_left_alone_and_the_rest_still_follow` and `test_a_pick_past_the_end_of_its_line_sits_on_the_last_trace_with_no_distance`.
4. **Text typed into a number cell.** `abc` in Offset or Start, or `0` in Dir, is reverted and named on the status line. No edit is recorded. Pinned by Task 4 `test_a_cell_that_is_not_a_number_is_reverted_and_says_so`.
5. **A line with no distance axis on the grid being edited** (a time-triggered file). The table lists it with a blank Length, its edits still apply, and its picks are left as they are. Pinned by Task 4 `test_a_line_with_no_distance_axis_is_listed_and_editable` and Task 1 `test_a_pick_on_a_line_with_no_distance_axis_is_left_as_it_is`.

