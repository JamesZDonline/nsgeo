### Task 2: The survey remembers each grid's slice source and the site view

The site view needs every grid's preset and line choice, and *This grid* scope reads and writes the
same record (spec §4.2, Ruling 5). After this task, *This grid* behaves differently: switching to a
grid and back restores what you chose for it instead of resetting to the defaults.

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/model/survey.py` (add the two fields, with a docstring
  giving the record shapes), `packages/nsgeo-core/src/nsgeo/project.py` (`save_site`, `load_site`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py`, `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`
- Test: `packages/nsgeo-core/tests/test_project.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`

**Interfaces:**
- Produces (core):
  - `Site.slice_sources: dict[str, dict[str, Any]]`, default `{}`;
  - `Site.site_view: dict[str, Any]`, default `{}`.

  Both have the shapes in Ruling 5.
- Produces (session; each mutator marks the site dirty, and is a no-op that leaves dirty untouched
  when nothing changes):
  - `slice_source(grid_id: str) -> dict[str, Any] | None`, which returns a copy;
  - `remember_slice_source(grid_id: str, *, preset: str, lines: tuple[str, ...] | None) -> None`;
  - `grid_gain(grid_id: str) -> float` (1.0 when unset) and
    `set_grid_gain(grid_id: str, gain: float) -> None`, which raises `ValueError` unless
    `0 < gain`;
  - `site_view() -> dict[str, Any]`, which returns a copy, and
    `set_site_view(*, grids: tuple[str, ...] | None = None, transform: str | None = None,
    normalisation: str | None = None) -> None`, which merges and validates `normalisation` against
    `NORMALISATION_METHODS`.
  - `remove_grid` also deletes `slice_sources[grid_id]` and removes the id from
    `site_view["grids"]`.
- No new signal. Consumers read these when they need them, so there is no orphan to connect.
- Dock (*This grid* scope):
  - On a real grid change (`_sync_included`'s grid-changed branch), if the grid has a remembered
    source:
    - select its preset, inside the `_updating` guard, if the preset still exists;
    - set `_included` from `lines`, filtered to keys still on the grid, with
      `_included_is_default = False`;
    - if `lines` is None, use the default and set `_included_is_default = True`.
  - `_on_source_changed`, a real user change, remembers the source. So does `set_included` when
    the set actually changed. Both remember `lines=None if self._included_is_default else
    self._included`.
  - The first-computation path in `rebuild_source` never remembers anything.

- [ ] **Step 1: Write the failing tests.**

```python
# core, test_project.py
def test_slice_sources_and_site_view_round_trip(tmp_path): ...
def test_a_survey_without_them_loads_with_empty_defaults(tmp_path): ...
def test_a_wrong_top_level_type_is_a_project_error(tmp_path): ...    # "slice_sources": []
def test_an_entry_for_an_unknown_grid_is_dropped_on_load(tmp_path): ...
def test_empty_ones_are_not_written(tmp_path): ...                   # keys absent from the JSON

# qgis, test_plugin_session.py
def test_remembering_an_unchanged_source_does_not_mark_dirty(...): ...
def test_set_grid_gain_refuses_zero_and_negative(...): ...
def test_set_site_view_refuses_an_unknown_method(...): ...
def test_removing_a_grid_prunes_its_source_and_its_site_view_entry(...): ...

# qgis, test_plugin_slices_dock.py
def test_switching_grid_away_and_back_restores_that_grids_preset_and_lines(docked_two_grids): ...
def test_a_default_line_choice_picks_up_a_line_imported_later(docked_two_grids): ...
def test_opening_a_site_does_not_mark_it_dirty(...): ...
def test_choosing_lines_remembers_them_for_that_grid_only(docked_two_grids): ...
```

  `docked_two_grids` is a new fixture in the dock test file. It is the existing `docked` setup
  plus a second grid `"B"` with its own synthetic lines.

- [ ] **Step 2: Run them; all fail.** Then run the existing dock tests. If any existing test
  asserted that returning to a grid **resets** its lines, update it to the spec's new behaviour
  and name each one in the report. Change nothing else about M11's dock.

- [ ] **Step 3: Implement.** In `load_site`, apply `cubes`' type check and then drop unknown-grid
  entries. Copy on read and copy on write: never hand out the stored dict.

- [ ] **Step 4: Both tiers green.**

- [ ] **Step 5: Mutants.** Each must fail at least one test:
  1. remembering in the first-computation path;
  2. not filtering remembered keys to the grid's current lines;
  3. `remove_grid` not pruning;
  4. `remember_slice_source` marking dirty when nothing changed.

- [ ] **Step 6: Commit and push.**
  `feat: remember each grid's slice source and the site view in the survey`

---

