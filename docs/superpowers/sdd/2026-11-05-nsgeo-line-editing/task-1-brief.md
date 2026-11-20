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

