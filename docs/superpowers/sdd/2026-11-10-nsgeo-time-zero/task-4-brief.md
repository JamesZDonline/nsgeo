### Task 4: Pick rows follow their line's zero

**Files:**
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/session.py`: `Pick`, `add_pick`.
  - `packages/nsgeo-qgis/nsgeo_qgis/layers.py`: `TABLES["picks"]`, `write_pick`, `_row_to_pick`,
    the new `follow_zero`, and the wiring.
  - `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`: `_on_pick_requested`.
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`: `_refresh_picks`.
- Test:
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py`
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py`

**Interfaces:**
- Consumes:
  - from Task 1: `retime_ns`;
  - from Task 2: `ProfileDock.shown_zero_ns`;
  - from Task 3: `SiteSession.line_zero`.
- Produces:
  - **`Pick.zero_ns: float | None = None`,** the last field. None means the radar clock.
  - **`Pick.radar_ns`,** a property: `time_ns + (zero_ns or 0.0)`.
  - **The picks table gets a `("zero_ns", "float")` column,** listed right after `("time_ns", "float")`.
    `_ensure_table` sees the changed field set and routes it through `_rebuild_picks`. That
    migrates rows by field name, so every existing row keeps its values with `zero_ns` NULL.
  - **`SiteSession.add_pick(key, trace, time_ns, *, zero_ns: float = 0.0) -> Pick`.**
    - `time_ns` is measured from `zero_ns`, so its radar time is `time_ns + zero_ns`.
    - It clamps the **radar** time into the header window, as today.
    - It then stores the time measured from `line_zero(key)`, with that zero.
    - When `line_zero(key)` is None, it stores the radar time with `zero_ns=None`.
    - `derived_pick_fields` gets the stored time.
  - **`SiteLayers.follow_zero(key: str, zero_ns: float) -> int`.**
    - It rewrites the rows of `key` whose stored zero (NULL counts as 0.0) differs from `zero_ns`.
    - For each row:
      - `time_ns` becomes `retime_ns(time_ns, old, zero_ns)`;
      - `zero_ns` becomes `zero_ns`;
      - `depth_m` and `velocity_m_ns` come from `derived_pick_fields`.
    - It writes through the data provider only, as `follow_lines` does. It returns the number of
      rows written.
    - It skips rows with a NULL trace or time.
  - **`SiteLayers._on_line_clock_changed(key: str)`,** connected to `session.stack_changed` and
    `session.line_loaded`.
    - It returns at once:
      - for a preview-only key (`key == session.preview_key != session.current_key`);
      - when the key has no pick rows;
      - when `session.line_zero(key, load=True)` is None.
    - Otherwise it calls `follow_zero`.
    - The body is guarded, and a failure is logged Critical.

- [ ] **Step 1: Write the failing tests**

In `test_plugin_layers.py`, next to the pre-M8 migration test:

```python
def test_a_pre_time_zero_picks_table_migrates_with_its_rows_intact(qgis_app, tmp_path, message_log):
    # As test_a_package_with_the_pre_m8_picks_schema_..., with old_spec = TABLES["picks"][1]
    # minus "zero_ns" and two authored rows. After reopening: same rows, same time_ns,
    # zero_ns NULL; picks_for() gives Pick.zero_ns None; session.dirty is False.
    ...


def test_adding_time_zero_moves_a_rows_time_but_not_its_sample(...):
    # Pick at (30, 20.0) on the radar clock, line loaded; append time_zero(sample=51).
    row = picks_row(...)
    assert row["zero_ns"] == pytest.approx(zero)
    assert row["time_ns"] == pytest.approx(20.0 - zero)
    assert row["time_ns"] + row["zero_ns"] == pytest.approx(20.0)
    assert row["depth_m"] == pytest.approx(model.depth_at([20.0 - zero])[0])


def test_changing_the_threshold_keeps_picks_on_their_sample(...):
    # replace_step with another sample; the radar time is unchanged, the row follows.
    ...


def test_applying_a_stack_to_the_grid_moves_picks_on_lines_not_open(...):
    # A row written on line 2 (never loaded) with zero_ns None; apply line 1's stack (time_zero)
    # to the grid. Line 2's row now carries line 2's zero (it was loaded to find it).
    ...


def test_a_hover_load_never_rewrites_picks(...):
    # Line 2 has a time_zero stack and a row with zero_ns None. Only previewing it and loading
    # its profiles (set_preview, set_profiles) leaves the row byte-for-byte unchanged.
    ...


def test_a_channel_switch_moves_picks_to_the_new_channels_zero(...):   # Review Focus 4
    # set_profiles(key, [p0, dataclasses.replace(p0, data=np.roll(p0.data, 10, axis=0))]) with a
    # first_break time_zero stack; pick; set_channel(key, 1). The row's zero moves by 10 * dt, and
    # its radar time is unchanged.
    ...


def test_a_line_that_cannot_be_read_leaves_its_picks_alone(...):   # Review Focus 2
    # time_zero stack on an unloaded line whose file was renamed away; apply_stack_to_grid.
    # The row is unchanged, and nothing escapes the slot.
    ...


@needs_real_data
def test_on_a_real_line_adding_time_zero_moves_a_pick_by_its_first_break(...):
    # REAL_DZT[0], default time_zero: the row's time_ns grows by 0.4764 ns (spec §2), and its
    # depth follows.
    ...
```

In `test_plugin_session.py`:

```python
def test_a_pick_made_on_a_relabelled_view_is_stored_from_the_lines_zero(...):
    # time_zero(sample=51), line loaded. add_pick(key, 30, 5.0, zero_ns=zero) stores time_ns 5.0
    # and zero_ns zero. The same pick given on the radar clock, add_pick(key, 30, 5.0 + zero),
    # stores the same row.
    ...
```

- [ ] **Step 2: Run them to make sure they fail**

Run the QGIS command on the two files.
Expected: FAIL. There is no `zero_ns` column, `add_pick` takes no `zero_ns`, and nothing follows
a stack change.

- [ ] **Step 3: Implement**

- **The Interfaces items above.**
- **`write_pick`** writes `("zero_ns", pick.zero_ns)`.
- **`_row_to_pick`** reads `_as_float(_attr(feature, "zero_ns"))`.
- **`plugin._on_pick_requested`** calls
  `add_pick(key, trace, time_ns, zero_ns=self.profile_dock.shown_zero_ns())`.
- **`ProfileDock._refresh_picks`** draws `retime_ns(p.radar_ns, 0.0, self.shown_zero_ns())`.
- **The `follow_lines` docstring** says that `time_ns` is measured from the row's `zero_ns`, and
  that `follow_zero` is the only writer of the time.

- [ ] **Step 4: Run them, then every picks file**

Run the QGIS command on `test_plugin_layers.py test_plugin_session.py test_plugin_profile_dock.py test_plugin_map_link.py test_plugin_profile_view.py test_plugin_loads.py`.
Expected: all pass, including every existing picks migration test.

- [ ] **Step 5: Lint, then commit and push**

```bash
git commit -am "feat(picks): a pick row keeps its zero and follows its line's time zero (#97)"
git push
```

---

