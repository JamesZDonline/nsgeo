# Line Editing Implementation Plan (#35, #64, #29)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every code task is written test-first with superpowers:test-driven-development: the failing test is run and seen to fail before any production code is written.

**Goal:** After import, a line's placement can be fixed in a table of its grid's lines, several lines can be changed at once, and lines can be moved to another grid. A grid that gets shorter or longer takes its reversed lines with the far edge. Through all of it, every pick stays on its line, and its depth follows the line's current velocity.

**Architecture:**
- **Picks.** `SiteLayers.follow_lines()` runs on every refresh and after a picks-layer commit. It works out each pick's position, `distance_m`, `depth_m` and `velocity_m_ns` again from its `line_key`, `trace` and `time_ns`, using the same path `add_pick` uses, and writes only the rows that changed, through the provider.
- **Placement rules.** A new Qt-free module, `nsgeo_qgis/line_edit.py`, holds the edge-inset rules, the `LineEdit` value the table builds, and the outcome and report types.
- **Session.** `SiteSession.edit_lines()` applies a batch of `LineEdit`s and a new order as one change. `replace_grid()` moves reversed lines when the grid's length changes, and returns a report.
- **Slices.** `SliceEngine` remembers the placements it prepared from and re-prepares (or hands the work over) when a held line moves.
- **UI.** `EditLinesDialog` is a modeless sibling of the import dialog. The Survey panel gains Edit lines…, Edit line…, Edit N lines… and a reused Move to grid submenu.

**Tech Stack:** Python 3, numpy; PyQt via `qgis.PyQt`; pytest on two tiers (core+pure in `.venv`, QGIS in `.venv-qgis`).

**Spec:** `docs/superpowers/specs/2026-10-30-nsgeo-line-editing-design.md` (approved 2026-11-05). Executors read the spec and this plan. The spec's decisions (§3) and behaviour (§4) are requirements. Where this plan settles something the spec leaves to the builder (§9), this plan wins.

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
- **Do not touch `.worktrees/nsgeo-slice-interpolation-b`.** It is being built and changes the same slices files as Task 3. Whichever branch merges second resolves the overlap (spec call 13).

## Before Task 1 (coordinator)

Run these from the worktree root `.worktrees/nsgeo-line-editing`:

1. Create the two virtualenvs:
   - `python3 -m venv .venv && .venv/bin/pip install -e "packages/nsgeo-core[dev]" ruff==0.17.1 mypy==2.4.0`
   - `python3 -m venv --system-site-packages .venv-qgis && .venv-qgis/bin/pip install -e packages/nsgeo-core pytest`
   - Match any extra test packages to `pip freeze` in `../nsgeo-slice-interpolation/.venv-qgis`.
2. Copy the real data:
   - `cp -r ../nsgeo-slice-interpolation/packages/nsgeo-core/tests/data/local packages/nsgeo-core/tests/data/`
   - `cp ~/nsgeo-m4-check/Sunnyside/survey.nsgeo.json packages/nsgeo-core/tests/data/local/sunnyside.nsgeo.json`
   - The directory is git-ignored. Never `git add -f` anything from it.
3. Run the verification commands below and record the baseline pass and skip counts in the ledger. A real-data test that skips has validated nothing, so the skip count must not rise in any task.

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

---

### Task 1: Picks follow their line (#35)

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py`: add `derived_pick_fields`; `add_pick` builds its derived fields through it.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/layers.py`:
  - add `follow_lines` and `_on_picks_committed`;
  - `refresh()` calls `follow_lines` after the three refills, and reports once on site open;
  - `on_info` replaces `on_warning`;
  - delete `_warn_if_a_placed_grid_moved`, `_grid_placements` and `_last_grid_placements`, with every docstring and comment that cites them (`__init__`, `detach`, `_pick_point`);
  - rewrite `_pick_point`'s docstring, since it is now called on every refresh.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` around line 186: build `SiteLayers(self.session, on_info=lambda msg: self.message(msg, Qgis.MessageLevel.Info))`, and replace the Finding C comment with one line about `on_info`.
- Modify: `packages/nsgeo-qgis/README.md`, the Picking section.
- Modify: `docs/guide/getting-started.md`, §4 *Where your data lives*: replace the "A pick's map position is fixed" bullet.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py`

**Interfaces:**
- Produces:
  - `SiteSession.derived_pick_fields(self, key: str, trace: int, time_ns: float) -> tuple[float | None, float, float]` returns `(distance_m, depth_m, velocity_m_ns)`:
    - `distance_m` is `self._pick_distance(line, trace)`;
    - the other two are `resolved_velocity(key).depth_at([time_ns])[0]` and `.velocity_at([time_ns])[0]`, as floats.
    - `KeyError` for an unknown key. No clamping: `add_pick` clamps before calling it.
  - `SiteLayers.__init__(self, session, project=None, on_info: Callable[[str], None] | None = None, parent=None)`.
  - `SiteLayers.follow_lines(self) -> int` returns the number of rows written.
  - `SiteLayers._on_picks_committed(self) -> None`: connected to the picks layer's `afterCommitChanges` inside `_bind_picks_signals`, and disconnected inside `_unbind_picks_signals`, beside the six existing bindings.

- [ ] **Step 1: Write the failing tests.**
  - **Delete** the four `on_warning` tests in `test_plugin_layers.py` (`test_on_warning_receives_the_moved_grid_warning` through `test_a_raising_on_warning_does_not_escape_or_break_the_refresh`) and the comment block above them. Keep `_MOVED_GRID`.
  - **Change** `test_picks_survive_multiple_refills_with_attributes_intact`: its last geometry assertion becomes `assert (pt.x(), pt.y()) == pytest.approx(_line_point(session, "raw/FILE__001.DZT", 12), abs=1e-9)`. The pick now follows its line. Every attribute assertion stays.
  - **Add** these to `test_plugin_layers.py`, with the imports they need (`VelocityModel` from `nsgeo.velocity`, `StoredFit` from `nsgeo.velocity_fit`):

```python
def _line_point(session, key, trace):
    x, y = session.line_for_key(key).trace_coords(session.site.frames)[trace]
    return (float(x), float(y))


def _rows(layers):
    return {f["line_key"]: f for f in layers.layers["picks"].getFeatures()}


def test_a_pick_follows_its_line_when_the_grid_moves(populated):
    session, layers, _ = populated
    layers.write_pick(_a_pick(trace=30, note="the wall"))
    session.replace_grid(_MOVED_GRID)
    f = _rows(layers)["raw/FILE__001.DZT"]
    pt = f.geometry().asPoint()
    assert (pt.x(), pt.y()) == pytest.approx(_line_point(session, "raw/FILE__001.DZT", 30), abs=1e-9)
    assert f["distance_m"] == pytest.approx(0.5)  # trace 30 at 60 traces per metre
    assert (f["trace"], f["note"], f["created"]) == (30, "the wall", "2026-09-19T10:00:00+00:00")
    assert f["time_ns"] == pytest.approx(12.5) and "dewow" in f["stack_json"]


def test_a_pick_follows_its_line_through_remove_and_re_import(populated):
    session, layers, _ = populated
    key = "raw/FILE__003.DZT"
    layers.write_pick(_a_pick(key=key, trace=10))
    path = session.line_for_key(key).path
    before = _rows(layers)[key].geometry().asPoint()
    session.remove_line(key)
    assert _rows(layers)[key].geometry().asPoint() == before  # no line: left exactly as it is
    session.add_lines([Line.open(path, GridPlacement("A", "y", 2.0, 0.0, 1, path.stem))])
    pt = _rows(layers)[key].geometry().asPoint()
    assert (pt.x(), pt.y()) == pytest.approx(_line_point(session, key, 10), abs=1e-9)


def test_a_pick_on_a_key_that_is_not_a_site_line_is_left_exactly_as_it_is(populated):
    session, layers, _ = populated
    layers.write_pick(_a_pick(trace=4))
    picks = layers.layers["picks"]
    f = QgsFeature(picks.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(1.0, 2.0)))
    for name, value in (("line_key", "cut:7"), ("trace", 3), ("time_ns", 5.0),
                        ("distance_m", 9.0), ("depth_m", 0.7), ("velocity_m_ns", 0.1)):
        f[name] = value
    assert picks.dataProvider().addFeatures([f])[0]
    session.replace_grid(_MOVED_GRID)
    cut = _rows(layers)["cut:7"]
    assert (cut.geometry().asPoint().x(), cut.geometry().asPoint().y()) == (1.0, 2.0)
    assert (cut["distance_m"], cut["depth_m"], cut["velocity_m_ns"]) == (9.0, 0.7, 0.1)
```

  - **Add** the rest by name, with these assertions:
    - `test_a_pick_on_a_line_with_no_distance_axis_is_left_as_it_is`:
      - add `FILE__099.DZT` with `traces_per_metre=0.0`, the way `test_an_unplaceable_line_is_skipped_not_fatal` does;
      - write one pick on it and one on `FILE__001`, then call `replace_grid(_MOVED_GRID)`;
      - the `FILE__099` row still has an empty geometry and `depth_m == 0.25`;
      - the `FILE__001` row sits at `_line_point(..., 5)`.
    - `test_a_picks_depth_and_velocity_follow_the_lines_velocity`, parametrised over `"grid"`, `"override"` and `"fit"`:
      - `"grid"`: `set_grid_velocity("A", VelocityModel.constant(0.07))`;
      - `"override"`: `set_line_velocity(key, VelocityModel.constant(0.11))`;
      - `"fit"`: `add_velocity_fit(key, StoredFit(20.0, 0.09, 0.004, 0.2, 30, ((30, 20.0), (15, 21.0)), "t"))`, then `set_line_velocity(key, VelocityModel.constant(0.09))` and `set_velocity_from_fit(key, fit_id)`, which is the profile dock's apply path;
      - each time, the row's `depth_m` and `velocity_m_ns` equal `session.derived_pick_fields(key, 7, 12.5)[1:]` to `abs=1e-12`, and `velocity_m_ns` is 0.07, 0.11 or 0.09.
    - `test_a_pick_dragged_on_the_map_goes_back_to_its_line_when_the_edit_is_saved`:
      - `startEditing`, `changeGeometry(fid, QgsPointXY(510.0, 720.0))`, `changeAttributeValue(fid, note, "moved by hand")`, `commitChanges`;
      - the point equals `_line_point(..., 20)` and the note is `"moved by hand"`.
    - `test_a_note_typed_in_editing_mode_survives_a_refresh_that_moves_its_pick`:
      - `startEditing`, `changeAttributeValue(fid, note, "typed, not saved")`, then `replace_grid(_MOVED_GRID)`;
      - the layer `isEditable()` and `isModified()` still;
      - `commitChanges()` is True, the note survives, and the point is on the moved line.
    - `test_follow_lines_writes_only_the_picks_whose_fields_change`:
      - write picks on `FILE__001` and `FILE__002`; the first `layers.follow_lines()` returns 2 and the second returns 0;
      - then wrap the method: `real = layers.follow_lines; counts = []; monkeypatch.setattr(layers, "follow_lines", lambda: counts.append(real()) or counts[-1])`;
      - `set_line_velocity("raw/FILE__002.DZT", VelocityModel.constant(0.12))` leaves `counts == [1]`.
    - `test_opening_a_site_reports_once_how_many_picks_it_put_back_on_their_lines`:
      - add a row through the provider at `QgsPointXY(0.0, 0.0)` with `line_key="raw/FILE__001.DZT"`, `trace=12`, `time_ns=30.0`;
      - `session.save()`, `layers.detach()`, then open the site again under `SiteLayers(again, project=project, on_info=told.append)`;
      - `told == ["updated 1 pick(s) to sit on their lines, at the current velocity"]`;
      - a following `again.replace_grid(_MOVED_GRID)` adds nothing to `told`;
      - detach `layers2` at the end.
    - `test_a_raising_on_info_does_not_break_the_refresh`: the same reopen with an `on_info` that raises. The lines table still holds 3 features, and `message_log` has an entry containing `on_info callback raised`.
    - `test_a_pick_past_the_end_of_its_line_sits_on_the_last_trace_with_no_distance`: `write_pick(_a_pick(trace=500))` on the 60-trace `FILE__001`, then `follow_lines()`. The point is `_line_point(..., 59)` and `distance_m == NULL`.
    - `test_a_hand_digitised_row_with_no_trace_is_left_alone_and_the_rest_still_follow`:
      - add a provider row on `FILE__001` with `time_ns=5.0`, no `trace`, at `(1.0, 2.0)`; also `write_pick(_a_pick(key="raw/FILE__002.DZT", trace=8))`;
      - after `replace_grid(_MOVED_GRID)`, the first row is still at `(1.0, 2.0)` and the second is on its moved line.
  - **Add** to `test_plugin_session.py`: `test_derived_pick_fields_are_what_add_pick_records`.
    - Attach a stub pick store (`write_pick` records its pick), open the first line and `add_pick(key, 7, 12.5)`.
    - `session.derived_pick_fields(key, 7, pick.time_ns) == (pick.distance_m, pick.depth_m, pick.velocity_m_ns)`.
    - An unknown key raises `KeyError`.

- [ ] **Step 2: Run them and see them fail.** Run `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py packages/nsgeo-qgis/tests/qgis/test_plugin_session.py -q -p no:cacheprovider -p no:xonsh`. Expected: the new tests FAIL, with `AttributeError` for `derived_pick_fields`/`follow_lines`, `TypeError` for `on_info`, and position mismatches in the follow tests.

- [ ] **Step 3: Implement `derived_pick_fields` and route `add_pick` through it.** Use it for the three derived fields of the `Pick` that `add_pick` builds. `add_pick` behaves exactly as before.

- [ ] **Step 4: Implement `follow_lines` and wire it in.**
  - `follow_lines` returns 0 when no picks layer or no site is open, or when the layer's CRS isn't the package CRS (log it, like `write_pick`'s guard).
  - It iterates `layer.dataProvider().getFeatures()`, so it sees committed rows only. It skips a row:
    - whose `line_key` is not in `session.keys()`;
    - whose `trace` or `time_ns` is NULL;
    - whose line has no grid, or whose `_line_points` is `None`.
  - It computes each line's points once per call, not once per pick. A line whose `derived_pick_fields` raises is logged once and its picks are skipped.
  - The position is `coords[clamp(trace)]`. That is `_pick_point`'s clamp, so share the helper.
  - It compares against the stored values: geometry with `QgsPointXY.compare(point, 1e-9)`, numbers within `1e-9` with NULL equal only to `None`. It collects only the differences.
  - It writes with one `provider.changeGeometryValues({fid: geometry})` and one `provider.changeAttributeValues({fid: {provider.fieldNameIndex(name): value}})`. Either returning False raises `RuntimeError` with the provider's error. If anything was written, it calls `layer.triggerRepaint()`.
  - `refresh()` calls it after the three refills inside its own `try`, logging Critical on failure.
  - `_on_site_opened` sets `self._report_follow = True` around its `refresh()` and clears it in a `finally`. While it is set, a nonzero count goes to `on_info` with the copy above. That call is guarded the way the old `on_warning` call was, and logs `the on_info callback raised: …`.
  - `_on_picks_committed` calls `follow_lines()` inside a guard that logs Critical. It emits nothing (see "Calls" above).

- [ ] **Step 5: Delete the moved-grid warning** and everything that cites it (see Files). Update the plugin's `SiteLayers(...)` call.

- [ ] **Step 6: Update the docs.**
  - **README, Picking paragraph:**
    - A pick is a trace and a time on its line, and it follows the line. Editing the grid or the line, or moving the line to another grid, moves its picks too.
    - Its depth and velocity follow the line's current velocity.
    - Notes and other attributes are edited with the ordinary tools.
    - A pick dragged on the map goes back onto its line when the layer's edits are saved. To move a pick along its line, delete it and pick again.
    - Delete the "Do not drag a pick" sentences.
  - **Guide §4:** replace the "A pick's map position is fixed" bullet with one bullet. A pick follows its line, so editing a grid or a line moves its picks too, and dragging a pick on the map does not move it.

- [ ] **Step 7: Run the two files again, then the whole QGIS tier.** Expected: all pass. Any other test that pinned "a pick is never re-placed" or the old warning is updated to the new ruling. Each such change is listed in the task report, with its reason.

- [ ] **Step 8: Lint, types, commit and push.**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/session.py packages/nsgeo-qgis/nsgeo_qgis/layers.py packages/nsgeo-qgis/nsgeo_qgis/plugin.py packages/nsgeo-qgis/README.md docs/guide/getting-started.md packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py packages/nsgeo-qgis/tests/qgis/test_plugin_session.py
git commit -m "feat(picks): a pick follows its line, and its depth the line's velocity (#35)"
git push origin nsgeo-line-editing
```

---

### Task 2: The placement rules, the session edit, and a grid's length

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/line_edit.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py`: add `edit_lines` and `move_lines`; `replace_grid` returns a `GridEditReport` and moves reversed lines.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`:
  - `_show_line` remembers `self._shown_placement = line.placement`;
  - `_on_geometry_changed` also shows the line again when the line's placement is not `self._shown_placement`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`, the grid dialog's `finished`:
  - `report = self.session.replace_grid(new_grid)`;
  - when `report.message()` is non-empty, pass it to `self.message`, at Warning when `report.outside` is set and Info otherwise.
- Modify: `.github/workflows/ci.yml`: add `packages/nsgeo-qgis/nsgeo_qgis/line_edit.py` to the mypy list.
- Modify: `packages/nsgeo-qgis/tests/plugin_testing.py`: add `SUNNYSIDE = LOCAL_DATA / "sunnyside.nsgeo.json"` and `needs_sunnyside = pytest.mark.skipif(not SUNNYSIDE.exists(), reason="no Sunnyside survey in tests/data/local")`.
- Test: create `packages/nsgeo-qgis/tests/pure/test_pure_line_edit.py`. Modify `tests/qgis/test_plugin_session.py`, `tests/qgis/test_plugin_layers.py`, `tests/qgis/test_plugin_profile_dock.py` and `tests/qgis/test_plugin_grid_dialog.py`.

**Interfaces:**
- Consumes: Task 1's `follow_lines` runs on the `lines_changed` that `edit_lines` emits.
- Produces, in `line_edit.py`:
  - Constants:
    - `START_TOLERANCE_M = 0.05` and `SAME_M = 1e-9`;
    - `REMOVED = "was removed from the site while the table was open"`;
    - `CHANGED_ELSEWHERE = "changed elsewhere while the table was open"`.
  - Geometry helpers:
    - `length_along(grid: Grid, axis: str) -> float` is `size_y` for `"y"` and `size_x` for `"x"`. `width_across` is the other size.
    - `edge_inset(placement: GridPlacement, length: float) -> float` is `start_along` for a forward line and `length - start_along` for a reversed one.
    - `start_at_inset(direction: int, inset: float, length: float) -> float` is its inverse.
    - `followed_length(placement, old_length, new_length) -> GridPlacement` keeps the inset. A forward line comes back unchanged.
    - `same_placement(a: GridPlacement, b: GridPlacement) -> bool` compares `grid_id`, `axis`, `direction` and `label` exactly, and `offset` and `start_along` within `SAME_M`.
  - `placement_note(placement: GridPlacement, grid: Grid) -> str`. It is `""` when nothing is off. Otherwise it is these parts, joined with `"; "`:
    - the edge is `"near"` for a forward line and `"far"` for a reversed one, and `d` is the inset;
    - `d < -START_TOLERANCE_M` gives `f"starts {-d:.2f} m past the {edge} edge"`;
    - `d > START_TOLERANCE_M` gives `f"starts {d:.2f} m inside the {edge} edge"`;
    - an offset below `-START_TOLERANCE_M` or above `W + START_TOLERANCE_M` gives `f"offset {offset:.2f} m is outside the grid's {W:.2f} m width"`.
  - `@dataclass(frozen=True) class Inset: inset: float`. This is a Start worked out when the edit is applied.
  - `@dataclass(frozen=True) class LineEdit`. Fields: `key: str`, `seen: GridPlacement`, `label: str | None = None`, `offset: float | None = None`, `direction: int | None = None`, `start_along: float | Inset | None = None`, `grid_id: str | None = None`. `None` means unchanged.
    - `placed(self, frames: Mapping[str, Grid]) -> GridPlacement` applies the set fields to `seen`. It raises `KeyError` for a grid not in `frames`. The Start is worked out by the algorithm below.
    - `flipped(self, frames) -> LineEdit` sets `direction=-p.direction` and `start_along=Inset(edge_inset(p, L_p))`, where `p = self.placed(frames)`.
    - `snapped(self) -> LineEdit` sets `start_along=Inset(0.0)`.
    - `moved_to(self, grid_id: str, frames) -> LineEdit` sets `grid_id` and `start_along=Inset(edge_inset(p, L_p))`.
    - `shifted(self, delta: float, frames) -> LineEdit` sets `offset=p.offset + delta`.
    - `changes(self, frames) -> bool` is `not same_placement(self.placed(frames), self.seen)`.
  - `@dataclass(frozen=True) class Skipped: key: str; label: str; reason: str`.
  - `@dataclass(frozen=True) class EditOutcome`. Fields: `changed: tuple[str, ...] = ()`, `reordered: bool = False`, `skipped: tuple[Skipped, ...] = ()`.
    - `message(self) -> str` gives `"nothing changed"`, `"changed {n} line(s)"`, `"reordered the lines"` or `"changed {n} line(s) and reordered the lines"`.
    - Each skipped line is appended as `f"; {label} {reason}, so it was left as it is"`.
  - `@dataclass(frozen=True) class GridEditReport`. Fields: `grid_id: str`, `moved: tuple[tuple[str, float, int], ...] = ()` (axis, new length, reversed lines moved), `outside: tuple[str, ...] = ()` (labels).
    - `message(self) -> str` is `""` when both are empty.
    - Otherwise it is these sentences, joined with a space:
      - one per `moved` entry: `f"{grid_id} is now {L:.2f} m along {axis}; its {n} reversed line(s) moved with the far edge."`;
      - if `outside` is set: `f"{len(outside)} line(s) on {grid_id} now lie outside its width: {', '.join(outside)}."`.
- Produces, in `SiteSession`:
  - `edit_lines(self, edits: Sequence[LineEdit], *, grid_id: str | None = None, order: Sequence[str] | None = None) -> EditOutcome`. `order` needs `grid_id`, or it raises `ValueError`. A key edited twice raises `ValueError`. An unknown `grid_id` raises `KeyError` before anything changes.
  - `move_lines(self, keys: Iterable[str], grid_id: str) -> EditOutcome`:
    - `KeyError` for an unknown grid;
    - an unknown key becomes `Skipped(key, Path(key).stem, REMOVED)`;
    - lines already on `grid_id` are left out;
    - the rest get `LineEdit(key, seen=line.placement, grid_id=grid_id)`.
  - `replace_grid(self, grid: Grid) -> GridEditReport`. `set_grid_velocity` ignores the result.

`LineEdit.placed` works out the Start like this. With `p = seen`, `g = grid_id or p.grid_id`, `dirn = direction or p.direction`, and `L(x)` the length along `p.axis` of `frames[x]`:

```text
start_along is Inset(d)                    -> start_at_inset(dirn, d, L(g))
start_along is a float s                   -> s
g != p.grid_id or dirn != p.direction      -> start_at_inset(dirn, edge_inset(p, L(p.grid_id)), L(g))
otherwise                                  -> p.start_along
```

`edit_lines` runs these steps in order:
1. Take `frames = site.frames` once.
2. For each edit, skip it in any of these cases:
   - the key is gone: `REMOVED`;
   - the line's placement is not a `GridPlacement`, or is not `== edit.seen`: `CHANGED_ELSEWHERE`;
   - `placed` raises `KeyError`: `f"its new grid {g!r} no longer exists"`.
   The label is `edit.seen.label or Path(key).stem`. An edit whose new placement is `same_placement` as the current one is dropped silently.
3. Replace each remaining line with `dataclasses.replace(line, placement=new)` in both `site.lines` and `_lines_by_key`.
4. For a line whose grid changed, drop its key from `site.slice_sources[old]["lines"]` when that is a list, then move the line to the end of `site.lines`. Moved lines keep their relative order.
5. With `order` given, let `on = keys_on_grid(grid_id)` and `want = [k for k in order if k in on] + [k for k in on if k not in order]`. If `want != on`, put the wanted lines into the grid's own slots in `site.lines` and set `reordered`.
6. Rebuild `_lines_by_key` in `site.lines` order. Map `id(line) → key` before reordering. Never recompute a key.
7. If anything changed or was reordered, call `_set_dirty(True)` and emit `lines_changed` once.

The current and preview keys are untouched, because a key is the file path. Stacks, profiles, velocity, fits and channels stay attached.

`replace_grid` does its work before it emits anything:
- For each line on the grid whose axis's length changed (by more than `SAME_M`), replace every reversed line's placement with `followed_length`. Count them per axis into `moved`.
- For each axis whose width changed, collect into `outside` the labels of lines on that axis whose offset lies outside the new width by more than `START_TOLERANCE_M`.
- Then dirty, `grids_changed` and `lines_changed`, as today.

- [ ] **Step 1: Write the failing pure tests** in `test_pure_line_edit.py`:

```python
GRID = Grid("A", (0.0, 0.0), 0.0, 10.0, 15.0, "EPSG:32616", 0.5)  # 10 m in x, 15 m in y
GB = Grid("B", (50.0, 0.0), 0.0, 8.0, 9.0, "EPSG:32616", 0.5)
FRAMES = {"A": GRID, "B": GB}
FWD = GridPlacement("A", "y", 0.25, 0.0, 1, "line 1")
REV = GridPlacement("A", "y", 0.75, 15.0, -1, "line 2")
STALE = GridPlacement("A", "y", 3.75, 16.0, -1, "line 8")  # Grid 5's case
XREV = GridPlacement("A", "x", 2.0, 9.5, -1, "x 1")


def test_the_inset_is_measured_from_the_edge_the_line_starts_at():
    assert edge_inset(FWD, 15.0) == 0.0 and edge_inset(REV, 15.0) == 0.0
    assert edge_inset(STALE, 15.0) == pytest.approx(-1.0)
    assert start_at_inset(-1, 0.2, 15.0) == pytest.approx(14.8)
    assert (length_along(GRID, "y"), width_across(GRID, "y")) == (15.0, 10.0)
    assert (length_along(GRID, "x"), width_across(GRID, "x")) == (10.0, 15.0)


def test_a_length_change_moves_reversed_lines_with_the_far_edge_only():
    at16 = dataclasses.replace(REV, start_along=16.0)
    assert followed_length(at16, 16.0, 15.0).start_along == pytest.approx(15.0)
    assert followed_length(FWD, 16.0, 15.0) == FWD
    assert followed_length(STALE, 15.0, 14.0).start_along == pytest.approx(15.0)  # keeps its 1 m


def test_flip_sends_start_to_the_other_edge_keeping_the_inset():
    p = LineEdit("k", dataclasses.replace(FWD, start_along=0.2)).flipped(FRAMES).placed(FRAMES)
    assert (p.direction, p.start_along) == (-1, pytest.approx(14.8))
    q = LineEdit("k", XREV).flipped(FRAMES).placed(FRAMES)
    assert (q.direction, q.start_along) == (1, pytest.approx(0.5))  # x lines use size_x


def test_flipping_twice_is_no_change_at_all():
    seen = dataclasses.replace(FWD, start_along=0.3)
    e = LineEdit("k", seen).flipped(FRAMES).flipped(FRAMES)
    assert not e.changes(FRAMES) and same_placement(e.placed(FRAMES), seen)
    assert not LineEdit("k", REV).moved_to("B", FRAMES).moved_to("A", FRAMES).changes(FRAMES)


def test_snap_puts_each_line_at_its_own_edge():
    assert LineEdit("k", STALE).snapped().placed(FRAMES).start_along == 15.0
    assert LineEdit("k", dataclasses.replace(FWD, start_along=0.4)).snapped().placed(FRAMES).start_along == 0.0
    assert LineEdit("k", XREV).snapped().placed(FRAMES).start_along == 10.0


def test_a_move_keeps_the_inset_against_the_new_grids_length():
    assert LineEdit("k", REV, grid_id="B").placed(FRAMES) == GridPlacement("B", "y", 0.75, 9.0, -1, "line 2")
    assert LineEdit("k", REV, start_along=14.5).moved_to("B", FRAMES).placed(FRAMES).start_along == pytest.approx(8.5)


def test_an_inset_start_is_worked_out_against_the_length_when_applied():
    e = LineEdit("k", FWD).flipped(FRAMES)
    assert e.placed({"A": dataclasses.replace(GRID, size_y=20.0)}).start_along == 20.0


def test_shift_moves_the_offset_and_placed_names_a_missing_grid():
    assert LineEdit("k", REV).shifted(0.5, FRAMES).placed(FRAMES).offset == pytest.approx(1.25)
    with pytest.raises(KeyError):
        LineEdit("k", REV, grid_id="Z").placed(FRAMES)


def test_the_note_judges_only_the_start_and_the_offset():
    assert placement_note(STALE, GRID) == "starts 1.00 m past the far edge"
    assert placement_note(dataclasses.replace(FWD, start_along=0.4), GRID) == "starts 0.40 m inside the near edge"
    assert placement_note(dataclasses.replace(FWD, start_along=0.04), GRID) == ""
    assert placement_note(dataclasses.replace(REV, offset=10.3), GRID) == "offset 10.30 m is outside the grid's 10.00 m width"
    assert placement_note(REV, GRID) == ""


def test_the_messages_say_what_changed_and_name_what_was_left_alone():
    out = EditOutcome(changed=("a", "b"), skipped=(Skipped("c", "line 8", CHANGED_ELSEWHERE),))
    assert out.message() == "changed 2 line(s); line 8 changed elsewhere while the table was open, so it was left as it is"
    assert EditOutcome().message() == "nothing changed"
    assert EditOutcome(changed=("a",), reordered=True).message() == "changed 1 line(s) and reordered the lines"
    assert GridEditReport("Grid5", moved=(("y", 15.0, 15),)).message() == (
        "Grid5 is now 15.00 m along y; its 15 reversed line(s) moved with the far edge.")
    assert GridEditReport("A").message() == ""
```

  - **Add** `test_on_sunnyside_the_note_flags_exactly_grid5s_reversed_lines`, marked `@needs_sunnyside`:
    - read `SUNNYSIDE` with `json`;
    - build each `Grid` from its `id`, `origin` (as a tuple), `azimuth`, `size_x`, `size_y`, `crs` and `default_spacing`;
    - build each `GridPlacement(**{k: v for k, v in placement.items() if k != "type"})`;
    - collect `(grid_id, label, placement_note(...))` for every line;
    - assert 210 lines, that exactly 15 carry a note, that all 15 are on `"Grid5"`, and that every note is `"starts 1.00 m past the far edge"`.

- [ ] **Step 2: Run them and see them fail.** Run `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_line_edit.py -q -p no:cacheprovider`. Expected: FAIL with `ModuleNotFoundError: No module named 'nsgeo_qgis.line_edit'`.

- [ ] **Step 3: Write `line_edit.py`** to the interface above. Give it a module docstring stating the edge-inset rule and why it is one rule (spec call 1). Run the command again. Expected: all pass, with the Sunnyside test run, not skipped.

- [ ] **Step 4: Write the failing session, layers, profile and grid-dialog tests.**
  - **Session.** Add to `test_plugin_session.py` a helper `_zigzag(session, folder)`. It adds `Grid("A", (500.0, 700.0), 0.0, 5.0, 11.0, "EPSG:32616", 0.5)` with four lines along y, at offsets 0, 0.5, 1.0 and 1.5, forward at 0.0 and reversed at 11.0 alternately. It also adds `Grid("B", (600.0, 700.0), 0.0, 5.0, 9.0, "EPSG:32616", 0.5)` with two forward lines. Then add:
    - `test_edit_lines_applies_every_edit_as_one_change`: an offset edit and a label edit give one `lines_changed` (Spy), a dirty session, both placements written and `outcome.changed` naming both keys.
    - `test_an_edit_that_changes_nothing_emits_nothing`: after `session.save()`, an edit setting `offset` to its own value returns `changed == ()`. There is no emit, and the session is not dirty.
    - `test_a_line_changed_elsewhere_since_the_table_read_it_is_skipped_and_named`:
      - take `seen` for a reversed and a forward line, then `replace_grid` A with `size_y=12.0`;
      - flip both with edits built from the old `seen`;
      - the reversed one is skipped with `CHANGED_ELSEWHERE` and its label;
      - the forward one becomes reversed at `12.0`, worked out at OK against today's length.
    - `test_a_removed_line_is_skipped_not_raised`.
    - `test_moving_a_line_keeps_its_inset_and_joins_the_new_grid_at_the_end`:
      - before the move, give the reversed line a stack step, a velocity override, a fit and current-line status;
      - after `move_lines([key], "B")` it is at `("B", 9.0, -1)` and is the last key of `keys_on_grid("B")`;
      - the stack, override and fit are still attached, and `current_key == key`.
    - `test_a_moved_line_leaves_the_old_grids_remembered_slice_lines`: `remember_slice_source("A", preset="p", lines=(k1, k2))`, then move `k2`. `slice_source("A")["lines"] == [k1]`.
    - `test_order_reorders_only_the_grids_own_slots`:
      - add lines in the order A1, B1, A2, B2, A3;
      - `edit_lines([], grid_id="A", order=[A3, A1, A2])` gives `keys() == [A3, B1, A1, B2, A2]` and `reordered`;
      - save and reopen with a new `SiteSession`, and the order holds.
    - `test_lines_that_arrived_after_the_table_read_go_after_the_reordered_ones`.
    - `test_a_grid_length_change_takes_its_reversed_lines_with_the_far_edge`:
      - `replace_grid(dataclasses.replace(A, size_y=10.0))` puts the reversed starts at 10.0 and leaves the forward lines alone;
      - the report message is `"A is now 10.00 m along y; its 2 reversed line(s) moved with the far edge."`;
      - exactly one `grids_changed` and one `lines_changed`.
    - `test_a_width_change_moves_nothing_and_names_lines_left_outside`: `size_x=1.2` changes no placement. `report.outside` holds the label of the 1.5 m line.
    - `test_a_velocity_only_grid_edit_moves_no_line_and_reports_nothing`.
    - `test_both_axes_on_one_grid_follow_only_their_own_length`: add a reversed line along x at `start_along=5.0`, then change `size_x` only. The x line moves and the y lines do not.
    - `test_move_lines_leaves_lines_already_there_alone`.
  - **Layers.** Add to `test_plugin_layers.py` `test_a_pick_follows_a_line_edit_and_a_move_to_a_grid_with_another_velocity`:
    - add `Grid("B", (600.0, 700.0), 0.0, 5.0, 11.0, "EPSG:32616", 0.5, velocity=VelocityModel.constant(0.08))`;
    - after an offset edit on `FILE__001`, its pick is at the new `_line_point`;
    - after `move_lines` to B, the pick is on B's line and `velocity_m_ns == pytest.approx(0.08)`.
  - **Profile.** Add to `test_plugin_profile_dock.py` `test_a_line_edit_reaches_the_open_profile_even_when_its_ruler_is_unchanged`. `edit_lines([LineEdit(key, seen=line.placement, label="wall line")])` makes `"wall line"` appear in `dock.windowTitle()`.
  - **Grid dialog.** Add `test_a_grid_length_edit_says_its_reversed_lines_moved` to `test_plugin_grid_dialog.py`, shaped like `test_open_grid_dialog_edits_an_existing_grid`:
    - give grid A (`size_y=4.0`) a synthetic line along y, reversed, at `start_along=4.0`;
    - `dialog.size_y.setValue(5.0)`, then `dialog.accept()`;
    - the line's start becomes 5.0, and `message_log` holds `"A is now 5.00 m along y; its 1 reversed line(s) moved with the far edge."`.

- [ ] **Step 5: Run them and see them fail.** Run the four QGIS files. Expected: `AttributeError` for `edit_lines`/`move_lines`. The length-change tests fail on unmoved starts. The profile title test fails.

- [ ] **Step 6: Implement** `edit_lines`, `move_lines`, the `replace_grid` change, the profile follow and the plugin message, to the interfaces and steps above. Give `edit_lines` a docstring citing spec call 14 and naming its three skip reasons.

- [ ] **Step 7: Run the four files, then both tiers, lint and types.** Expected: all pass, with no new skips.

- [ ] **Step 8: Commit and push.**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/line_edit.py packages/nsgeo-qgis/nsgeo_qgis/session.py packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py packages/nsgeo-qgis/nsgeo_qgis/plugin.py .github/workflows/ci.yml packages/nsgeo-qgis/tests/plugin_testing.py packages/nsgeo-qgis/tests/pure/test_pure_line_edit.py packages/nsgeo-qgis/tests/qgis/test_plugin_session.py packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py packages/nsgeo-qgis/tests/qgis/test_plugin_grid_dialog.py
git commit -m "feat(session): edit and move lines as one change; a grid's length takes its reversed lines (#29, #64)"
git push origin nsgeo-line-editing
```

---

### Task 3: Slices see the new positions

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`: `_sync_included`, `rebuild_source` and `restore_cube`.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py`, `test_plugin_slices_dock.py`, `test_plugin_site_scope.py`

**Interfaces:**
- Consumes: `SiteSession.edit_lines`, `move_lines` and `LineEdit` (Task 2).
- Produces, in `SliceEngine`:
  - `self._placements: dict[str, Any]` holds the placement of every site line, with `label` dropped (`dataclasses.replace(p, label=None)` for a `GridPlacement`). It is captured in `set_source` next to `_grid_fp`, and emptied wherever `_grid_fp` is reset (`set_source`'s reset, `clear()`).
  - `placements_changed(self, keys: Iterable[str]) -> bool`: True when any key that was a site line at the last `set_source` is still one and its label-free placement now differs.
  - `had_line(self, key: str) -> bool`: whether `key` was a site line at the last `set_source`.
  - `_on_lines_changed(self) -> None`: connected to `session.lines_changed` in `__init__`, right after `grids_changed`, and disconnected in `dispose()` beside it.
    - It returns when there is no choice, nothing captured or no site.
    - When `placements_changed(choice.line_keys)`, it works like `_on_grids_changed`'s move branch. With `on_grid_moved` set, it calls `_hand_over_the_move(grid_id)`. Otherwise it calls `set_source` with the choice narrowed to keys still on `choice.grid_id`, inside a guard that reports `could not re-prepare after a line moved: …`.
  - In `set_source`'s job loop, a key whose line is placed on another grid is not prepared. It is reported as `f"{key}: now on grid {other!r}, not {choice.grid_id!r}; left out of this source"`.
- Produces, in `SlicesDock`:
  - `_sync_included`'s explicit-choice prune keeps only the grid's own lines: `valid = set(self._default_included(grid_id))`.
  - `rebuild_source` gets a new `elif`, after the first-computation branch. When the scope is `"grid"`, `self._included_is_default` is set, `self.engine.choice` is not None and on the selected grid, and `any(self.engine.had_line(k) for k in self._included if k not in self.engine.choice.line_keys)` holds, it calls `self.prepare()`. That is a line moved onto a grid whose source takes every line. An imported line was never in the snapshot, so it keeps today's "stale" status.
  - `restore_cube`: a recipe key whose line is a site line on another grid is left out of `_included`. When any are, `self.error.emit(f"cube {cube_id!r}: {n} line(s) moved to another grid since it was saved and were left out: {labels}")`. A recipe left with nothing falls back to the default, as an empty one already does.

- [ ] **Step 1: Write the failing engine tests** in `test_plugin_slices_engine.py`, using `sourced` and `_prepare`:
  - `test_a_placement_edit_to_a_prepared_line_re_prepares`:
    - give the first key an offset of 1.5 with `edit_lines`, then `wait_for_preparation`;
    - `len(prepared) == count + 1`;
    - that key's `PreparedLine.coords` equal `session.line_for_key(k).trace_coords(session.site.frames)` to `abs=1e-9`.
  - `test_an_edit_to_a_line_outside_the_source_does_not_re_prepare`: prepare with the first three keys and edit the fourth. The count is unchanged and nothing is running.
  - `test_a_label_only_edit_does_not_re_prepare`.
  - `test_a_line_moved_to_another_grid_leaves_the_source`:
    - add `Grid("B", (600.0, 700.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5)` and `move_lines([k3], "B")`;
    - after the wait, `k3` is in neither `engine.choice.line_keys` nor `engine.prepared_lines`, and `errors == []`.
  - `test_with_a_grid_moved_hook_a_placement_edit_hands_over`: mirror `test_with_a_grid_moved_hook_a_move_clears_and_hands_over_instead_of_re_preparing`, with an offset edit in place of the grid move.
  - `test_a_grid_length_change_re_prepares_exactly_once`:
    - first add a reversed line at `start_along=6.0`;
    - `replace_grid` with `size_y=7.0` gives `len(prepared) == count + 1`, because the `lines_changed` that follows finds the snapshot already current.
  - `test_set_source_leaves_out_a_key_now_on_another_grid_and_says_so`: a choice naming a B line prepares the A lines only. `errors` holds `"now on grid 'B', not 'A'"`.
- [ ] **Step 2: Write the failing dock tests** in `test_plugin_slices_dock.py`, using `docked`:
  - `test_a_line_moved_off_the_grid_leaves_an_explicit_choice`: `set_included` the first two keys, wait, then move the second to a new grid B. `dock.included_keys()` is just the first key, and once the engine has waited, the status reads `prepared · 1 lines`.
  - `test_a_line_moved_onto_a_default_grid_re_prepares_it`:
    - add grid B with a line, wait for A;
    - `move_lines` that line onto A;
    - after the wait, it is in `engine.choice.line_keys` and the status is prepared.
  - `test_a_line_imported_onto_a_default_grid_still_shows_stale`: today's behaviour, pinned.
  - `test_restoring_a_cube_drops_a_line_now_on_another_grid_and_says_so`:
    - record a cube with every line, the way the existing restore tests do, then move one line to B and `restore_cube`;
    - `dock.included_keys()` lacks the moved line, and `error` carries `moved to another grid since it was saved`.
- [ ] **Step 3: Write the failing Whole site test** in `test_plugin_site_scope.py`: `test_a_placement_edit_re_prepares_only_that_grid_in_the_site_view`.
  - With `site3` showing in Whole site, edit one B line's offset.
  - B goes through `queued` and back to ready, and A and C are never re-queued. Record `dock.site_engine.grid_state(g)` for each grid from the site engine's `on_changed` notifications, the way that file's other re-queue tests do.
- [ ] **Step 4: Run all three files and see the new tests fail.** Expected: no re-preparation on a placement edit, `AttributeError` for `had_line`, and the moved key still in the choice.
- [ ] **Step 5: Implement** the engine and dock changes to the interfaces above. Each new slot body is guarded. Each new comment says why, citing `(line editing spec §4.5)`.
- [ ] **Step 6: Run the three files, then the whole QGIS tier.** Expected: all pass. The full slices dock and site scope files are the regression net for R-P5 and trap 1. Never let two preparations run at once.
- [ ] **Step 7: Lint, types, commit and push.**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py
git commit -m "feat(slices): a source re-prepares when a line it holds moves, and drops a line that left its grid (#29, #64)"
git push origin nsgeo-line-editing
```

---

### Task 4: The Edit lines table and its bulk panel

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/edit_lines_dialog.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`:
  - add `open_edit_lines_dialog` and `self._edit_lines_dialogs: dict[str, EditLinesDialog] = {}`;
  - `unload()` calls `reject()` on each open one, the way it does for `_import_dialog`, with the same comment shape.
- Test: create `packages/nsgeo-qgis/tests/qgis/test_plugin_edit_lines_dialog.py`

**Interfaces:**
- Consumes: `LineEdit`, `Inset`, `EditOutcome`, `placement_note`, `same_placement`, `length_along` and `width_across` from `line_edit.py`, and `SiteSession.edit_lines` (Task 2).
- Produces, in `ui/edit_lines_dialog.py`:
  - Column constants `COL_LABEL, COL_OFFSET, COL_DIR, COL_START, COL_GRID, COL_ALONG, COL_TRACES, COL_LENGTH, COL_PICKS, COL_NOTE = range(10)`.
  - `HEADERS = ["Label", "Offset (m)", "Dir", "Start (m)", "Grid", "Along", "Traces", "Length (m)", "Picks", "Note"]`.
  - `EDITABLE = {COL_LABEL, COL_OFFSET, COL_DIR, COL_START}`. Grid is a `QComboBox` cell widget listing every grid id.
  - `CHANGED = QColor(255, 236, 179)`, the background of every cell whose field differs from the line's `seen` placement.
  - `class EditLinesDialog(QDialog)`:
    - `__init__(self, session: SiteSession, grid_id: str, *, select: Sequence[str] = (), parent: QWidget | None = None)`. It reads the grid's keys, their placements as `seen` and their pick counts (`len(session.picks_for(key))`) once, and records `session.json_path`.
    - Attributes:
      - `grid_id`, `outcome: EditOutcome | None = None`;
      - `table`, `header_label`, `up_button` ("↑"), `down_button` ("↓");
      - `bulk: QGroupBox`;
      - `start_spin`, `set_start_button` ("Set"), `snap_button` ("Snap to grid edge");
      - `offset_spin`, `shift_button` ("Shift");
      - `flip_button` ("Flip");
      - `grid_combo`, `move_button` ("Move");
      - `status: QLabel`, `buttons` (OK | Cancel).
    - Methods:
      - `keys(self) -> list[str]` gives the table's row order;
      - `edit_for(self, key: str) -> LineEdit`;
      - `select_keys(self, keys: Iterable[str]) -> None` and `selected_keys(self) -> list[str]`;
      - `set_start(self, value: float) -> None`, `snap_to_edge(self) -> None`, `shift_offset(self, delta: float) -> None`, `flip(self) -> None` and `move_to(self, grid_id: str) -> None` each act on the selected rows;
      - `move_selected(self, delta: int) -> None` moves every selected row one place up (`-1`) or down (`+1`), keeping their order. It does nothing when one would leave the table;
      - `accept(self) -> None`.
- Produces, in the plugin: `open_edit_lines_dialog(self, grid_id: str, keys: Sequence[str] = ()) -> None`.
  - At most one dialog per grid. Opening it again calls `select_keys(keys)`, `show()`, `raise_()` and `activateWindow()`.
  - On `finished` with Accepted and an outcome: `self.message(f"Edit lines · {grid_id}: {dialog.outcome.message()}", Warning if dialog.outcome.skipped else Info)`.
  - It then calls `deleteLater()` and removes the dialog from the dict. A `destroyed` guard clears the entry only if it still names this dialog (the `open_import_dialog` pattern).

What the table shows and does:
- **Title and header.**
  - The title is `f"Edit lines · {grid_id}"`.
  - When every line runs along one axis `a`, the header reads `f"{grid_id} · {length_along(g, a):.2f} m along {a} × {width_across(g, a):.2f} m across · {n} lines"`. Otherwise it reads `f"{grid_id} · {g.size_x:.2f} m × {g.size_y:.2f} m · {n} lines"`.
- **Rows.** Each row shows `edit_for(key).placed(session.site.frames)`. Start and Offset show 2 decimals. Dir shows `"+1"` or `"−1"`. Along is the axis. Traces is `n_traces`. Length is `n_traces / traces_per_metre` to 2 decimals, blank when that is not positive. Picks is the count. Note is `placement_note(placed, frames[placed.grid_id])`.
- **Cell edits** (`itemChanged`, guarded by `_updating`):
  - Label: the text, or the file stem when the cell is empty.
  - Offset and Start: a float, with a comma accepted as the decimal mark. Anything else sets the status to `f"{text!r} is not a number; unchanged"` and refreshes the row.
  - Dir: parsed like `ImportDialog`. A leading minus means −1, and a positive number means +1. Anything else sets the status to `f"{text!r} is not recognised as a direction; unchanged"`. A direction that differs from the shown one is `flipped`.
  - The Grid combo calls `moved_to`.
  - Every edit refreshes the table and the status line.
- **Bulk panel.**
  - It is titled `f"Change the {n} selected lines"`, and greyed when no row is selected.
  - Set gives `start_along=start_spin.value()`. Snap gives `snapped()`. Shift gives `shifted(offset_spin.value(), frames)`. Flip gives `flipped`. Move gives `moved_to(grid_combo.currentText(), frames)`.
  - ↑ and ↓ are greyed when they could not move the selection.
- **Status line.** `n` counts the rows whose edit `changes(frames)`. `m` sums the pick counts of those rows whose label-free placement changed. The line is:
  - `""` when `n == 0`;
  - otherwise `f"{n} line{'s' if n != 1 else ''} changed · {m} pick{'s' if m != 1 else ''} will move with {'them' if n != 1 else 'it'}"`.
- **Guards.** Every method that reads the grid or the frames catches `KeyError` and `ProjectError`, then puts `f"grid {grid_id!r} no longer exists"` or `"no site is open"` on the status line instead of raising.
- **`accept()`:**
  1. With no site open, the status reads `"no site is open; nothing was changed"`.
  2. When `json_path` changed, it reads `"a different site was opened while the table was open; nothing was changed"`.
  3. When the grid is gone, it reads `f"grid {grid_id!r} no longer exists; nothing was changed"`.
  4. Otherwise `self.outcome = session.edit_lines([e for e in edits if e.changes(frames)], grid_id=self.grid_id, order=self.keys())` and `super().accept()`. A `KeyError`, `ValueError` or `ProjectError` from it goes to the status line and the dialog stays open.

- [ ] **Step 1: Write the failing tests.** The fixture `table(qgis_app, tmp_path)` builds:
  - `Grid("Grid5", (500.0, 700.0), 0.0, 15.0, 15.0, "EPSG:32616", 0.5)` with six 60-trace lines along y, labelled `line 1`–`line 6`, at offsets `0.25 + 0.5 * i`:
    - rows 0, 2 and 4 forward at 0.0;
    - rows 1 and 3 reversed at 16.0, the stale case;
    - row 5 reversed at 15.0;
  - `Grid("B", (600.0, 700.0), 0.0, 10.0, 9.0, "EPSG:32616", 0.5)`;
  - and yields `(session, EditLinesDialog(session, "Grid5"))`, hiding and `deleteLater()`-ing the dialog afterwards.

```python
def _cell(dialog, row, col):
    return dialog.table.item(row, col).text()


def test_snap_on_every_row_fixes_the_stale_reversed_lines_and_nothing_else(table):
    session, dialog = table
    keys = dialog.keys()
    changed = Spy(session.lines_changed)
    dialog.select_keys(keys)
    dialog.snap_to_edge()
    assert [_cell(dialog, r, COL_START) for r in range(6)] == ["0.00", "15.00", "0.00", "15.00", "0.00", "15.00"]
    assert [dialog.table.item(r, COL_START).background().color() == CHANGED for r in range(6)] == [
        False, True, False, True, False, False]
    assert dialog.status.text() == "2 lines changed · 0 picks will move with them"
    assert session.line_for_key(keys[1]).placement.start_along == 16.0  # nothing before OK
    dialog.accept()
    assert [session.line_for_key(k).placement.start_along for k in keys] == [0.0, 15.0, 0.0, 15.0, 0.0, 15.0]
    assert set(dialog.outcome.changed) == {keys[1], keys[3]} and len(changed.calls) == 1
```

  - **Add** the rest by name, with these assertions (`Spy` as in `test_plugin_session.py`):
    - `test_the_table_lists_the_grids_lines_in_survey_order_with_their_placements`:
      - labels, Start, Dir, the Grid combo's text, Along `"y"`, Traces `"60"` and Length `"1.00"`;
      - Note `"starts 1.00 m past the far edge"` on rows 1 and 3 and `""` elsewhere;
      - the header reads `"Grid5 · 15.00 m along y × 15.00 m across · 6 lines"` and the title `"Edit lines · Grid5"`.
    - `test_cancel_applies_nothing`: snap and shift, then `reject()`. No placement changed and no `lines_changed`.
    - `test_flip_sends_start_to_the_other_edge_and_back`: on row 0, the first flip shows `"−1"`/`"15.00"` highlighted. The second shows `"+1"`/`"0.00"` with no highlight, and the status is `""`.
    - `test_typing_in_a_cell_edits_only_that_row`: Label, Offset (`"0,40"`), Start and Dir typed on row 2 change only row 2's edit.
    - `test_a_cell_that_is_not_a_number_is_reverted_and_says_so`:
      - `"abc"` in Offset sets the status to `"'abc' is not a number; unchanged"`, the cell back to `"1.25"` and row 2's edit to blank;
      - `"0"` in Dir gives `"'0' is not recognised as a direction; unchanged"`.
    - `test_shift_moves_each_selected_offset_by_the_amount`: rows 0 and 1, `shift_offset(0.1)`, give 0.35 and 0.85.
    - `test_moving_rows_to_another_grid_keeps_them_listed_until_ok`:
      - row 5 `move_to("B")` shows Grid `"B"` and Start `"9.00"`, and the row stays in the table;
      - after OK it is the last key of `session.keys_on_grid("B")`.
    - `test_up_and_down_set_the_survey_order`:
      - with rows 1 and 2 selected, `move_selected(-1)` gives order `[k1, k2, k0, k3, k4, k5]`;
      - `up_button` is disabled with row 0 selected;
      - after OK, `session.keys_on_grid("Grid5")` matches the table.
    - `test_the_status_counts_the_picks_that_will_move`: with a stub pick store whose `picks_for` returns two picks for `keys[0]`, built before the dialog:
      - flipping row 0 gives `"1 line changed · 2 picks will move with it"`;
      - a label edit on row 2 then gives `"2 lines changed · 2 picks will move with them"`.
    - `test_the_bulk_panel_is_greyed_until_rows_are_selected_and_counts_them`.
    - `test_ok_skips_a_line_changed_elsewhere_and_names_it`: flip row 2 in the table, then `session.edit_lines` its offset directly. After `accept()`, `outcome.skipped[0].label == "line 3"`, and the offset edit made elsewhere stands.
    - `test_a_concurrent_length_edit_is_not_undone_by_ok`:
      - flip row 0 in the table;
      - `session.replace_grid` with `size_y=14.0`, which moves rows 1, 3 and 5 by −1 m;
      - after `accept()`, row 0 starts at `14.0`, rows 1 and 3 at `15.0` and row 5 at `14.0`.
    - `test_the_dialog_survives_its_grid_being_removed`:
      - after `session.remove_grid("Grid5", with_lines=True)`, `flip()`, `snap_to_edge()` and `accept()` raise nothing;
      - the status reads `"grid 'Grid5' no longer exists; nothing was changed"` and `result()` is not Accepted.
    - `test_a_site_closed_under_the_dialog_changes_nothing`.
    - `test_a_line_with_no_distance_axis_is_listed_and_editable`:
      - add a `traces_per_metre=0.0` line to Grid5 before building a dialog;
      - its Length is `""`;
      - an Offset edit on it applies on OK.
    - `test_open_edit_lines_dialog_opens_one_table_per_grid_and_reports_on_ok` (`fake_iface`, `message_log`, `answer_modal`):
      - `plugin.open_edit_lines_dialog("A", [k0])` selects `k0`, and opening again with `[k1]` reuses the same dialog, now with `k1` selected;
      - a snap and `accept()` put `"Edit lines · A: changed"` in `message_log` and empty `plugin._edit_lines_dialogs`;
      - one left open is rejected by `plugin.unload()` (answer the save prompt with Discard, as the grid dialog test does).
- [ ] **Step 2: Run the file and see it fail.** Run `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_edit_lines_dialog.py -q -p no:cacheprovider -p no:xonsh`. Expected: FAIL with `ModuleNotFoundError`.
- [ ] **Step 3: Write the dialog and the plugin opener** to the interfaces above. Follow `ImportDialog`'s module docstring and table code for the modeless and `_updating` rules. Write a module docstring saying what the dialog edits, why Start is editable here when it isn't in Import, and that OK re-checks the site (spec call 14).
- [ ] **Step 4: Run the file, then the whole QGIS tier.** Expected: all pass.
- [ ] **Step 5: Lint, types, commit and push.**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/ui/edit_lines_dialog.py packages/nsgeo-qgis/nsgeo_qgis/plugin.py packages/nsgeo-qgis/tests/qgis/test_plugin_edit_lines_dialog.py
git commit -m "feat(ui): Edit lines — a grid's lines in one table, changed one at a time or together (#29)"
git push origin nsgeo-line-editing
```

---

### Task 5: Survey panel entries, Move to grid, and the guide

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/survey_dock.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`:
  - connect `edit_lines_requested` to `open_edit_lines_dialog`;
  - connect `move_lines_requested` to a new `move_lines`.
- Modify: `docs/guide/getting-started.md`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py` for the menus, and `packages/nsgeo-qgis/tests/qgis/test_plugin_edit_lines_dialog.py` for the plugin's `move_lines`.

**Interfaces:**
- Consumes: `open_edit_lines_dialog` (Task 4) and `SiteSession.move_lines` (Task 2).
- Produces, in `SurveyDock`:
  - `edit_lines_requested = pyqtSignal(str, list)`, carrying the grid id and the keys to select;
  - `move_lines_requested = pyqtSignal(list, str)`, carrying the keys and the target grid id;
  - `self.move_menu = QMenu("Move to grid", self)`, made once in `__init__` and refilled on every right-click. It is added with `menu.addMenu(self.move_menu)`, so `context_menu.clear()` never leaves a submenu behind;
  - fix the `__init__` comment that says there are no submenus.
- Produces, in the plugin: `move_lines(self, keys: list[str], grid_id: str) -> None`.
  - It calls `session.move_lines(keys, grid_id)`.
  - `KeyError` or `ProjectError` go to the message bar at Critical.
  - Otherwise it sends `f"Move to {grid_id}: {outcome.message()}"`, at Warning when anything was skipped and Info otherwise.

The menus (texts exact; separators as today, before the destructive entry):
- **Grid:**
  - `["Edit grid…", "Edit lines…", "Import DZT files…", "Set velocity…", "Remove grid"]`;
  - "Edit lines…" is disabled when the grid has no lines, and emits `edit_lines_requested(gid, [])`.
- **One line:**
  - `["Open", "Edit line…", "Set velocity override…", "Move to grid", "Remove line from site"]`;
  - "Edit line…" emits `edit_lines_requested(<its grid>, [key])`.
- **A selection holding lines** (`_selected_targets` gives keys):
  - `"Edit {n} lines…"`, only when every key is on one grid, which emits `edit_lines_requested(grid, keys)`;
  - then `f"Move {n} lines to grid"` and `f"Remove {n} lines from site"`.
  - A selection of grids only keeps today's single Remove entry.
- **The submenu** lists every grid id in site order. Each entry emits `move_lines_requested(keys, gid)`. An entry is disabled when every selected line is already on that grid. The submenu's title is set on each refill, to "Move to grid" or `f"Move {n} lines to grid"`.

- [ ] **Step 1: Write the failing tests** in `test_plugin_survey_dock.py`, using `dock`, `answer_modal(QMenu, "exec", None)` and `_right_click`/`_texts`:
  - **Change** `test_the_context_menu_offers_the_right_actions_for_each_kind_of_item` to the grid and line lists above. Its separator checks stay.
  - `test_edit_lines_is_greyed_on_a_grid_with_no_lines`: add an empty grid B.
  - `test_edit_line_and_edit_n_lines_ask_for_the_table_with_those_rows`: one line gives `edit_lines_requested` `("A", [key])`. Two selected lines on A give `("A", [k0, k1])` from `"Edit 2 lines…"`.
  - `test_a_selection_spanning_grids_offers_move_but_no_edit`: add grid B with a line and select a line on each grid. The texts are `["Move 2 lines to grid", "Remove 2 lines from site"]`.
  - `test_the_move_submenu_lists_every_grid_and_greys_the_one_they_are_on`: entries `["A", "B"]`, with A disabled for a line on A. Triggering B emits `move_lines_requested([key], "B")`.
  - `test_the_move_submenu_leaves_nothing_behind`: `n = len(dock.findChildren(QMenu))`, then five right-clicks on a line, leave `len(dock.findChildren(QMenu)) == n` and `dock.context_menu.findChildren(QMenu) == []`.
  - `test_move_lines_moves_them_and_reports_on_the_bar`, in `test_plugin_edit_lines_dialog.py` (plugin, `fake_iface`):
    - `plugin.move_lines([k], "B")` puts the line on B, and `message_log` has `"Move to B: changed 1 line(s)"`;
    - an unknown grid logs at Critical without raising.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement** the menus, the reused submenu, the two signals and their plugin connections. Every lambda's work is guarded, as `_on_context_menu`'s comment requires.
- [ ] **Step 4: Update the guide.**
  - **The nsgeo Survey bullet in *The panels*:**
    - a grid's menu gains **Edit lines…**;
    - a line's menu gains **Edit line…** and **Move to grid**;
    - a selection of lines on one grid offers **Edit N lines…**, and any selection of lines offers **Move N lines to grid**.
  - **A new short subsection, *Fixing lines after import*,** after Step 3's import text:
    - **Edit lines…** opens a table of every line on the grid, in survey order. Label, Offset, Dir, Start and Grid can be changed.
    - ↑ and ↓ set the order the Survey panel shows.
    - The panel under the table changes every selected line at once: Set a Start, **Snap to grid edge**, Shift the offset, Flip the direction, or Move to another grid.
    - Note flags a line that starts off its edge, or that lies outside the grid's width.
    - Nothing changes until **OK**, and then everything changes as one step. Picks move with their lines.
    - Changing a grid's length in **Edit grid…** moves its reversed lines with the far edge, and the message bar says so.
- [ ] **Step 5: Run the survey dock file, then both tiers, lint and types.** Expected: all pass, with no new skips.
- [ ] **Step 6: Commit and push.**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/ui/survey_dock.py packages/nsgeo-qgis/nsgeo_qgis/plugin.py docs/guide/getting-started.md packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py packages/nsgeo-qgis/tests/qgis/test_plugin_edit_lines_dialog.py
git commit -m "feat(ui): Edit lines and Move to grid from the Survey panel; the guide (#29, #64)"
git push origin nsgeo-line-editing
```

---

### Task 6: Build and walkthrough (human gate, not a code task)

The user's rule: deploy and a manual walkthrough come before any merge decision. This task ends when the user reports back. It never ends by merging.

- [ ] **Step 1: Verify the branch head from clean.** Run both tiers, lint, types and the boundary tests, and record every count. Confirm that the Sunnyside and real-DZT tests ran and did not skip.
- [ ] **Step 2: Keep a copy of the Sunnyside site first.** `cp -a ~/nsgeo-m4-check/Sunnyside ~/nsgeo-m4-check/Sunnyside.before-line-editing`. The walkthrough edits it.
- [ ] **Step 3: Deploy to a new QGIS profile `ns_geo_lines`.**
  - Make it a copy of `ns_geo`, then run `.venv/bin/python packages/nsgeo-qgis/scripts/dev_link.py --profile ns_geo_lines` from this worktree. `ns_geo` and the other profiles stay untouched.
  - Check the symlink with `ls -la` on the profile's plugins directory, and do a headless smoke load.
- [ ] **Step 4: Publish a walkthrough page** as a claude.ai Artifact with the `db` capability, the same pattern as the earlier walkthrough pages. Each check has a pass/fail and notes:
  - **The user's own case.** On Sunnyside Grid 5: Edit lines…, select all 30 lines, **Snap to grid edge**, OK. The 15 reversed lines start at 15 m. The profile shows no overrun, and the slices show no stagger on alternate lines.
  - Note flags exactly those 15 lines before the snap, and nothing after it.
  - Make a pick on a Grid 5 line, then Edit grid… to move the grid by a metre. The pick moves with its line. Then try shortening and lengthening the grid: reversed lines follow the far edge and the message bar says so.
  - Drag a pick on the map in editing mode and save. It goes back onto its line, and a note typed in the same session is kept.
  - Set a grid velocity, and a line override. The pick's depth and velocity in its attribute table follow.
  - Flip one line, shift a few offsets, and reorder with ↑/↓. The Survey panel follows on OK, and Cancel leaves everything alone.
  - Move to grid ▸ from the Survey panel, on one line and on a selection. Lines land at the new grid's edge, the slices of both grids re-prepare, and the picks follow.
  - Edit line… on the open line keeps it open and shows it at its new place.
  - Leave Edit lines open while doing Edit grid… on the same grid, then OK. The grid edit is not undone.
  - Open a site saved before this build that has picks. The message bar says how many picks were updated, once.
- [ ] **Step 5: Report the walkthrough to the user and wait for their results.**
  - Fix rounds go back through Tasks 1–5's test-first discipline.
  - Merging is offered only afterwards, through superpowers:finishing-a-development-branch, and is asked, never assumed.
  - On the PR: close #35, #64 and #29, tick #55's third bullet as moot, and comment on #58 that its placement part is done.

## Follow-ups (not in this plan)

- **Slice interpolation milestone B** changes the same slices files as Task 3. Whichever branch merges second reconciles `_on_lines_changed` with B's refine machinery.
- **M15 cut picks** use keys that are not line keys, so `follow_lines` leaves them alone by construction (spec call 3). Note this on the M15 branch's spec when that work resumes.
