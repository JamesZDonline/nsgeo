### Task 2: GPS lines in grids: the session, the map and the Survey panel

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/line_edit.py` (add `TrackEdit`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py` (`edit_lines`, `move_lines`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/layers.py` (GPS lines' `grid_id` field; `_hide_when_lines_crowd`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/survey_dock.py` (menus)
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_line_edit.py` (or the existing pure line-edit test file), `tests/qgis/test_plugin_session_gps_grids.py` (new), `tests/qgis/test_plugin_layers_gps.py`, `tests/qgis/test_plugin_survey_dock.py`

**Interfaces:**
- Consumes: `measure_spacing` (Task 1).
- Produces, in `line_edit.py`:

```python
@dataclass(frozen=True)
class TrackEdit:
    """A GPS line's requested change against the placement the table saw. None: unchanged.
    Only the grid, label and destagger can change; the track never moves (C3)."""
    key: str
    seen: TrackPlacement
    label: str | None = None
    grid_id: str | None = None
    travel_shift: float | None = None

    def placed(self, frames: Mapping[str, Grid]) -> TrackPlacement: ...   # KeyError for a grid not in frames
    def moved_to(self, grid_id: str, frames: Mapping[str, Grid]) -> TrackEdit: ...
    def changes(self, frames: Mapping[str, Grid]) -> bool: ...
```

- `SiteSession.edit_lines(edits: Sequence[LineEdit | TrackEdit], *, grid_id=None, order=None) -> EditOutcome` — unchanged contract; a `TrackEdit` is checked against a `TrackPlacement` the same way (`REMOVED`, `CHANGED_ELSEWHERE`, a new grid gone). A GPS line that changes grid leaves the old grid's remembered slice lines and joins the end of the survey order, as a tape line does.
- `SiteSession.move_lines(keys, grid_id)` moves GPS lines too (a `TrackEdit` with only `grid_id`), including GPS lines in no grid.
- `SurveyDock.fit_tracks_requested = pyqtSignal(list)` (keys) — connected in Task 6; until then connect it in `plugin.py` to a stub that does nothing but log, so `test_no_orphan_signals` passes. Task 6 replaces the stub.

- [ ] **Step 1: Write the failing tests.**
  - Pure: `TrackEdit(key, seen).placed(frames) == seen`; `grid_id="B"` gives `seen` with `grid_id="B"` and identical fixes; a grid missing from `frames` raises `KeyError`; `travel_shift=0.3` and `label="x"` apply; `changes` is False for an empty edit.
  - Session (`test_plugin_session_gps_grids.py`, built with `plugin_testing.gps_line` / `open_gps(..., grid_id=…)`):
    - `move_lines([gps_key], "B")` moves a GPS line from grid A to B, and a GPS line in no grid into B: `grid_id` changes, `trace_coords` are byte-identical before and after, one `lines_changed`, dirty, and A's remembered slice `lines` no longer names it.
    - A mixed `move_lines` (one tape, one GPS) moves both in one change.
    - `edit_lines([TrackEdit(...)])` after the line's destagger changed elsewhere skips it as `CHANGED_ELSEWHERE`, and a tape edit in the same call still applies.
    - `replace_grid` with a moved and resized grid leaves a GPS line's `trace_coords` unchanged (C13).
    - `remove_grid(…, with_lines=True)` takes the grid's GPS lines with it.
    - A GPS line with `grid_id="A"` is in `keys_on_grid("A")`, sits under grid A in the Survey panel's tree, and is in the line keys of grid A's default slice source (`export.source_choice("A", export.defaults("A")).line_keys`, with `export` a `ParaViewExport` built as the existing ParaView export tests build it; the source the 3-D view and the export read).
    - Profiles stay in distance walked until M17d: `ProfileDock._ruler_for` returns None for a GPS line in grid A, and the ruler of a tape line on grid A is built without the GPS line.
  - Layers: a GPS line with `grid_id="A"` writes `grid_id = "A"` in the `lines` table (so it takes grid A's colour); one with none still writes `""`. Lines layer zoom-out hiding: a site with only GPS lines in no grid, walked 0.5 m apart, gets scale-based visibility at `HIDE_LINES_BEYOND_SCALE_PER_M * measure_spacing(...)` (#222); a GPS line in a grid uses the grid's `default_spacing`.
  - Survey panel: a GPS line's menu reads `Open`, `Set velocity override…`, `Set destagger…`, `Move to grid ▸`, `Fit a grid to this track…`, separator, `Remove line from site`; a GPS-only selection adds `Move {phrase} to grid ▸` and `Fit a grid to these {n} tracks…`; a mixed selection on one grid gets `Edit {phrase}…` and `Move {phrase} to grid ▸`; the grid menu reads `Add GPR data…` where `Import DZT files…` was. Choosing a grid in the GPS line's Move menu moves it (through `session.move_lines`).
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.** `TrackEdit` in `line_edit.py` (pure, on the mypy list already). In `session.edit_lines`, branch on the edit type; `applied` holds either placement kind; the "moved" bookkeeping reads `grid_id` from either (a GPS line may come from `None`). `move_lines` builds a `TrackEdit` for a `TrackPlacement` whose `grid_id` differs. In `layers.py`, `f["grid_id"] = p.grid_id or ""` for GPS lines; `_hide_when_lines_crowd` adds `measure_spacing` of the GPS lines in no grid (their `trace_coords({})`) when there are two or more, and ignores it when None. In `survey_dock.py`, follow the copy above; the GPS-only and mixed branches reuse `_add_move_menu`; `Fit a grid…` emits `fit_tracks_requested(keys)`. Move to grid ▸ for a GPS line in no grid enables every grid (none is "already on").
- [ ] **Step 4: Run the tests to pass**, plus `test_plugin_layers.py`, `test_plugin_layers_gps.py`, `test_plugin_survey_dock.py`, `test_plugin_line_selection.py`, `test_plugin_session*.py` and the pure tier.
- [ ] **Step 5: Commit and push** (`feat(m17b): GPS lines move between grids and take their grid's colour; Survey panel menus (#134, #222)`).

---

