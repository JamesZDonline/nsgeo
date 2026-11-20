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

