# Line Placement Corrections Implementation Plan (#3, #47 chunk A)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every code task is written test-first with superpowers:test-driven-development: the failing test is run and seen to fail before any production code is written.

**Goal:** A line can be stretched or compressed to fit its grid (#3), and moved along its direction of travel to remove the stagger between lines walked out and back (#47). Neither change touches what the line recorded. Both show everywhere a trace is positioned, and both can be undone.

**Architecture:** Two new fields on `GridPlacement` in nsgeo-core, `scale` and `travel_shift`, enter the one formula every position comes from (`distance_along`). The map, the profile, the map link, picks, velocity fitting and slice binning all read that formula, so they follow without new code. The survey file writes the two fields only when they are set. The plugin's Qt-free placement rules (`line_edit.py`) gain a Fit marker that is worked out at OK, and a grid length change keeps fitted lines fitted. The Edit lines table gains two columns and two bulk rows, the Survey panel shows the corrections, and the import dialog gains an opt-in fit.

**Tech Stack:** Python 3, numpy; PyQt via `qgis.PyQt`; pytest on two tiers (core+pure, QGIS).

**Spec:** There is no separate spec. On 2026-11-10 the user asked to work #3 and #47 together, then chose to skip design questions ("start building"). The **Design** section below is therefore the requirements: the user's own words from the two issues, and Claude's calls, numbered so they can be checked. Before starting, read issues #3 and #47 with their comments (`gh issue view 3 --comments`, `gh issue view 47 --comments`). Also read the line editing spec, `docs/superpowers/specs/2026-10-30-nsgeo-line-editing-design.md`. Edit lines, picks following their line, and slices re-preparing on a placement change all come from it, and this plan builds on all three.

## Scope: this plan is chunk A

- **In:**
  - #3: a per-line scale, set by **Fit to grid edges** or typed. Available in Edit lines, as an import option, and shown in the Survey panel.
  - #47's stagger correction, typed by hand for a line or a selection.
- **Next (chunk B, its own plan after this walkthrough):** **Measure**, #47's suggested shift. It ports the method in the stagger spike (`docs/superpowers/notes/2026-11-06-stagger-spike.md`, on branch `nsgeo-m17-gps`). Each line is correlated with its opposite-direction neighbours, and the shift is offered to the user.
- **Out:**
  - Direction balancing, the second half of #47. It stays on the README wishlist.
  - Corrections in the GeoTIFF export metadata. `site_export.py` is being rewritten on `nsgeo-whole-site-fine-cells`.
  - Processing at the corrected spacing. See Known limits.

## Design

### The user's words

- **#3, from the M4 checkpoint:** *"Often lines will appear slightly longer than the grid size due to terrain modulations making the terrain distance greater than the linear distance. In these cases its better to compress the line to fit the grid. On the other hand if we intentionally run a line longer or shorter, we don't want it auto-compressing or stretching."*
- **#47 and #3, 2026-11-06:** *"Destagger is becoming more important. I found some grids that are clearly suffering from stagger (feature across 4 lines that looks wiggly in the slice due to stagger). This may also be helped by working with Issue #3 (which should include lines that are too long OR too short) If I could say stretch(compress) the lines to the edges of the grid for example, that would help smooth out the stagger across the whole line, but I want it to be configurable."*
- **#47's design from M12:**
  - A grid-wide shift is the starting point, then it can be adjusted line by line.
  - It applies everywhere a trace is positioned.
  - It is stored separately from the line's recorded start.
  - Picks follow it.

### The model (Claude's calls 1–4)

1. **The formula:** `distance_along[i] = start_along + direction × (scale × i / traces_per_metre + travel_shift)`.
   - **`scale`** defaults to 1.0. It is grid metres per metre the wheel recorded. The header stays untouched, so the change can be undone. This is the shape #3's comment suggested.
   - **`travel_shift`** defaults to 0.0, in metres. It moves every trace forward along the line's own direction of travel, and it is not scaled.
   - A positive shift is the usual fix. On the spike's survey, the positions as logged sat about 24 cm behind the radar.
2. **The shift applies to every line, each along its own direction of travel**, not to the reversed lines only. This is spike finding 2, and M17's decision 10 relies on it.
   - On a zigzag the two models differ only by a move of the whole grid along its axis.
   - Splitting the opposite-line disagreement half each way keeps features where they are.
3. **The shift is stored per line; there is no grid-level value.** "A grid-wide shift, then line by line" is done in Edit lines: select every row and press Set, then change the rows that need it. Lines imported later start at 0. The mount can sit differently from one survey to the next, so the shift is measured each time, not remembered (spike finding 3).
4. **Start, the Note's edge check and the edge-inset rules ignore `travel_shift`.** Start is where the line was recorded to begin. The shift corrects where its traces are drawn.

### Fit to grid edges (calls 5–8)

5. **Fit puts the line's first trace on the edge it starts at and its last trace on the other edge.**
   - In numbers: Start inset 0 and `scale = L / span`, where `span = (n_traces − 1) / traces_per_metre` and `L` is the grid's length along the line's axis.
   - Like Snap's inset, the scale is worked out at OK, against the grid's length at that moment.
   - A line with no distance axis, or with fewer than two traces, cannot be fitted. The table says so and leaves that line as it is.
6. **Fitting is opt-in everywhere.** It is offered in Edit lines (for a selection), and as an import checkbox that is off by default. There is no threshold and no automatic fitting. That is #3's "configurable".
7. **A fitted line stays fitted when its grid's length changes.** This extends line editing decision 4.
   - A line counts as fitted when its scale ≠ 1 (by more than `SAME_M`) and both its recorded ends lie within `START_TOLERANCE_M` of the grid's two edges. The ends are judged without `travel_shift`.
   - Such a line is fitted again to the new length: its Start follows the inset rule, and its scale becomes `fit_scale(span, new_length)`.
   - The message bar counts the lines refitted. A line that is not fitted keeps its scale. A reversed one still moves with the far edge, as today.
8. **The Note flags a scale more than 20% away from 1** (`SCALE_NOTE = 0.2`), for example "scale ×1.450 stretches it by 45%". A fit across a selection that includes a deliberately short line then stands out before OK.

### Where it shows (calls 9–12)

9. **Edit lines:**
   - Two editable columns go after Start: **Scale** and **Destagger (m)**.
   - Two bulk rows go after the Start row: **Scale [spin] Set · Fit to grid edges**, then **Destagger (m) [spin] Set**.
   - These use the existing look, so there is no lavish mock-up. The user chose this bulk panel for line editing, and the walkthrough judges the result.
10. **The Survey panel** adds ` · ×0.954` to a line's text when its scale ≠ 1, and ` · destagger +0.24 m` when its shift ≠ 0.
11. **Import** gains a checkbox, **Stretch or compress each line to the grid's length**, on a form row named **Line length**. A fitted row's Note reads `fitted to the grid's 10.00 m (scale ×0.9032)` instead of `exceeds grid size …`.
12. **Picks, the profile, the map, the map link, velocity fitting and slices get no new code.**
    - They all read `Line.distance_along()` or `trace_coords()`.
    - Edit lines' existing paths already cover a scale or shift change once `same_placement` compares the two new fields: picks follow on refresh, and a slice source re-prepares when a placement differs.
    - Tests pin this (Task 2).

### The survey file (call 13)

13. **`"scale"` and `"travel_shift"` are written only when they differ from their defaults.**
    - A site with no corrections saves exactly as it does today, so it still opens in nsgeo 0.3.0.
    - There is no schema bump. Presets, cubes and velocity fits were added the same way.
    - **Known hazard, not fixed:** 0.3.0 opening a corrected site draws its lines uncorrected, and drops the corrections on its next save.

### Known limits (recorded, not built)

- **Migration and velocity fitting use different spacings on a scaled line.** Migration takes its trace spacing from the header (`Radargram.dx_m`), while velocity fitting uses placed metres. On a line scaled ×0.95, migration sees a 5% longer spacing than the fit did. Processing at the true distance is M17b.
- **Profiles show the corrected distance.** The profile's ruler and its mirrored axis read `distance_along`, so a fitted line fills its grid's ruler exactly. This is intended.

## Global Constraints

- `nsgeo_qgis/line_edit.py` and `nsgeo_qgis/lookup.py` import no Qt and no `qgis`. Both are on CI's mypy list.
- The plugin imports Qt only through `qgis.PyQt`. `tests/pure/test_plugin_boundary.py` and `test_no_orphan_signals.py` stay green.
- Every Qt slot guards its own body and reports, never raises. In `EditLinesDialog`, a slot ends in `except Exception as exc: self._failed(exc)`, the pattern the dialog already uses.
- One change is one dirty mark and one `lines_changed`, however many lines it touches.
- **Numbers:**
  - Existing: `START_TOLERANCE_M = 0.05`, `SAME_M = 1e-9`.
  - New: `SCALE_NOTE = 0.2`.
  - The bulk Scale spin runs 0.5–2.0, with 4 decimals, step 0.001 and default 1.0. The bulk Destagger spin runs −5.0 to 5.0 m, with 3 decimals, step 0.01 and default 0.0.
- **Display:** the Scale cell is `f"{scale:.4f}"` and the Destagger cell is `f"{travel_shift:.2f}"`.
- **Copy, exactly:**
  - Note for a scale far from 1: `scale ×{s:.3f} stretches it by {abs(s-1):.0%}` when `s > 1`, and `scale ×{s:.3f} compresses it by {abs(s-1):.0%}` when `s < 1`.
  - A fit that skipped a row: `{label} has no recorded length to fit, so it was left as it is`. Several are joined with `; `.
  - A refused Scale cell: `{text!r} is not a scale above 0; unchanged`.
  - The grid length report:
    - Both kinds: `{grid} is now {L:.2f} m along {axis}; its {n} reversed line(s) moved with the far edge, and its {m} fitted line(s) were fitted to the new length.`
    - Fitted lines only: `{grid} is now {L:.2f} m along {axis}; its {m} fitted line(s) were fitted to the new length.`
    - Reversed lines only: unchanged from today.
  - Survey panel suffixes: ` · ×{scale:.3f}` and ` · destagger {travel_shift:+.2f} m`.
  - Import note: `fitted to the grid's {L:.2f} m (scale ×{s:.4f})`. With fitting on but no known grid length: `cannot be fitted without a known grid length`.
  - Tooltips (Edit lines column headers and bulk rows, and the import checkbox):
    - Scale: `Grid metres per metre the wheel recorded. Fit to grid edges sets it so the line's first and last traces sit on the grid's two edges. 1 leaves the line as recorded.`
    - Destagger: `Moves every trace of the line this far forward along its direction of travel, kept apart from Start. If features on lines walked one way sit behind the same features on lines walked the other way, increase it.`
    - Import checkbox: `For lines walked edge to edge whose wheel read long or short (terrain, calibration). Leave it off for lines run long or short on purpose. Edit lines… can fit or unfit any line later.`
- Comments and docstrings follow the file they are in. They cite this plan as `(placement corrections plan, call N)`.
- **Shared-worktree safety:** reviewers and any mutation probes work on a scratch copy, never this worktree. Set `PYTHONDONTWRITEBYTECODE=1` for every test run.
- **Commits:**
  - End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
  - Push each commit to `origin nsgeo-placement-corrections` as it is made.
- Touch no other worktree.

## Verification commands (exactly these, from the worktree root)

The worktree uses the main checkout's virtualenvs, with the worktree's core on `PYTHONPATH`, plus a local `.venv-tools` (git-excluded) holding the CI-pinned ruff 0.17.1 and mypy 2.4.0. Real data is linked file by file under `packages/nsgeo-core/tests/data/local/` (git-ignored; never `git add -f` from it). A real-data test that skips has validated nothing, so the skip count must not rise.

- **core + pure:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:cacheprovider`
  - The baseline at `b55b2f0` is 1150 passed, 5 skipped.
- **qgis:** `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen PYTHONPATH=$PWD/packages/nsgeo-core/src ../../.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis -q -p no:cacheprovider -p no:xonsh`
  - This takes 10+ minutes. Run single files while iterating; the coordinator runs the full tier.
- **lint:** `.venv-tools/bin/ruff check . && .venv-tools/bin/ruff format --check .`
- **types:** `.venv-tools/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/ui/ruler.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py packages/nsgeo-qgis/nsgeo_qgis/line_edit.py`

## Review Focus

1. **Fit on a line that cannot be fitted.** This covers a time-triggered line (no distance axis) and a line with one trace. The row is listed, left as it is and named on the status line. The other selected rows are still fitted. Pinned by Task 3, `test_fit_skips_a_line_that_cannot_be_fitted_and_says_so`.
2. **A typed scale of 0, a negative number, `nan` or `abc`.** The cell is refused and reverted, and no edit is recorded. Core refuses the same values too, so a hand-edited survey file cannot carry them in. Pinned by Task 3, `test_a_scale_that_is_not_above_zero_is_refused`, and Task 1, `test_a_bad_scale_in_the_file_is_a_project_error_naming_the_line`.
3. **A grid length edit while a Fit is pending in an open table.** At OK, forward rows are fitted to the length then. Reversed rows were moved by the grid edit, so they are skipped as changed elsewhere (the existing rule). Pinned by Task 3, `test_a_pending_fit_uses_the_grid_length_at_ok`.
4. **Flipping or moving a fitted or shifted line.**
   - A flip keeps the scale and the shift.
   - A move to a grid of another length, while a Fit is pending, fits to the new grid.
   - A typed scale stays as typed.
   Pinned by Task 2, `test_flip_and_move_keep_scale_and_shift_and_a_pending_fit_refits`.
5. **Setting a value a line already has.** Setting scale 1 on an unscaled row, or destagger 0 on an unshifted one, must read as no change: no highlight, not counted and not written. Pinned by Task 2, `test_setting_the_values_a_line_already_has_is_no_change`.

---

### Task 1: Scale and travel shift in the core and the survey file

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/geometry/placement.py`. Add the two fields after `label`, because positional construction up to `label` is used in tests. Add validation in `__post_init__`. Change the formula in `distance_along`, and explain both fields in the class docstring.
- Modify: `packages/nsgeo-core/src/nsgeo/project.py`, in `_placement_to_dict` and `_placement_from_dict`. In `load_site`, wrap the `_placement_from_dict` call: `(KeyError, TypeError, ValueError)` becomes `ProjectError(f"invalid placement for line {entry['path']!r}: {exc}")`. The `ProjectError` that `_placement_from_dict` raises for an unknown type must still pass through unwrapped (`test_rejects_unknown_placement_type`).
- Test: `packages/nsgeo-core/tests/test_placement.py`, `packages/nsgeo-core/tests/test_project.py`

**Interfaces:**
- Produces: `GridPlacement(grid_id, axis, offset, start_along=0.0, direction=1, label=None, scale=1.0, travel_shift=0.0)`. It is frozen. `ValueError` unless `scale` is finite and > 0 and `travel_shift` is finite.

- [ ] **Step 1: Write the failing tests** in `test_placement.py`, using its `header` (60 traces/m) and `frames` fixtures:

```python
def test_scale_stretches_the_recorded_distance_from_the_start(header):
    d = GridPlacement("G", "y", 0.5, 1.0, scale=0.9).distance_along(120, header)
    assert d[0] == pytest.approx(1.0) and d[60] == pytest.approx(1.9)


def test_a_reversed_line_scales_toward_its_start(header):
    d = GridPlacement("G", "y", 0.5, 20.0, -1, scale=1.1).distance_along(120, header)
    assert d[0] == pytest.approx(20.0) and d[60] == pytest.approx(18.9)


def test_travel_shift_moves_every_trace_forward_along_its_own_direction(header):
    fwd = GridPlacement("G", "y", 0.5, 0.0, 1, travel_shift=0.24).distance_along(120, header)
    rev = GridPlacement("G", "y", 1.0, 20.0, -1, travel_shift=0.24).distance_along(120, header)
    assert (fwd[0], fwd[60]) == (pytest.approx(0.24), pytest.approx(1.24))
    assert (rev[0], rev[60]) == (pytest.approx(19.76), pytest.approx(18.76))


def test_the_shift_is_not_scaled(header):
    d = GridPlacement("G", "y", 0.5, scale=2.0, travel_shift=0.1).distance_along(120, header)
    assert d[60] == pytest.approx(2.1)


def test_the_defaults_place_exactly_as_before(header):
    d = GridPlacement("G", "y", 0.5, 3.5, -1).distance_along(120, header)
    assert np.array_equal(d, 3.5 - np.arange(120, dtype=float) / 60.0)


@pytest.mark.parametrize(
    "kw",
    [
        {"scale": 0.0},
        {"scale": -1.0},
        {"scale": float("nan")},
        {"scale": float("inf")},
        {"travel_shift": float("nan")},
        {"travel_shift": float("inf")},
    ],
)
def test_a_scale_or_shift_that_cannot_place_a_line_is_refused(kw):
    with pytest.raises(ValueError):
        GridPlacement("G", "y", 0.5, **kw)


def test_trace_coords_use_the_corrected_distance(header, frames):
    pl = GridPlacement("G", "x", 2.0, 1.0, 1, scale=1.5, travel_shift=0.2)
    xy = pl.trace_coords(60, header, frames)
    assert xy[:, 0] == pytest.approx(pl.distance_along(60, header))


def test_a_real_line_fitted_to_its_grid_ends_on_both_edges():
    """FILE__008 is the campus line that runs 11.10 m on its 10 m grid (#3)."""
    path = next((p for p in CAMPUS_LINES if p.stem == "FILE__008"), None)
    if path is None:
        pytest.skip("real campus data not present")
    h = read_header(path)
    n = trace_count(path)
    scale = 10.0 / ((n - 1) / h.traces_per_metre)
    fwd = GridPlacement("G", "y", 0.25, 0.0, 1, scale=scale).distance_along(n, h)
    rev = GridPlacement("G", "y", 0.75, 10.0, -1, scale=scale).distance_along(n, h)
    assert (fwd[0], fwd[-1]) == (pytest.approx(0.0), pytest.approx(10.0, abs=1e-9))
    assert (rev[0], rev[-1]) == (pytest.approx(10.0), pytest.approx(0.0, abs=1e-9))
    assert h.traces_per_metre == pytest.approx(60.0)  # the header stays as recorded
```

  Imports to add: `from nsgeo.io import trace_count` and `from tests.real_data import CAMPUS_LINES`.

  Then, in `test_project.py`, using its `site` fixture:

```python
def test_scale_and_travel_shift_round_trip(tmp_path, site):
    site.lines[1] = dataclasses.replace(
        site.lines[1],
        placement=dataclasses.replace(site.lines[1].placement, scale=0.9542, travel_shift=0.24),
    )
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    back = load_site(out)
    assert back.lines[1].placement == site.lines[1].placement
    assert back.lines[0].placement.scale == 1.0 and back.lines[0].placement.travel_shift == 0.0


def test_a_line_without_corrections_writes_neither_key(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    for entry in json.loads(out.read_text())["lines"]:
        assert "scale" not in entry["placement"] and "travel_shift" not in entry["placement"]


@pytest.mark.parametrize("field,value", [("scale", 0), ("scale", "x"), ("travel_shift", None)])
def test_a_bad_scale_in_the_file_is_a_project_error_naming_the_line(tmp_path, site, field, value):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    doc = json.loads(out.read_text())
    doc["lines"][0]["placement"][field] = value
    out.write_text(json.dumps(doc))
    with pytest.raises(ProjectError, match="L0.DZT"):
        load_site(out)
```

- [ ] **Step 2: Run the two test files and see the new tests fail.** Only the new tests should fail, with `TypeError: unexpected keyword argument 'scale'`, an assertion, or `ValueError` not being a `ProjectError`.
- [ ] **Step 3: Implement.**
  - Write `scale` only when `!= 1.0` and `travel_shift` only when `!= 0.0`, compared exactly (call 13).
  - Read both with `float(doc.get(..., default))`. `float(None)` raises `TypeError`, which `load_site` wraps.
- [ ] **Step 4: Run core + pure. Everything passes, and the skip count is 5.** Then run lint and types.
- [ ] **Step 5: Commit** `feat(core): a placement's scale and travel shift (#3, #47)`, then push.

---

### Task 2: The placement rules, fitted lines that follow their grid, and proof that picks and slices follow

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/line_edit.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py`, in `replace_grid` only.
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_line_edit.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py`

**Interfaces:**
- Consumes: Task 1's `GridPlacement.scale` and `GridPlacement.travel_shift`.
- Produces (all in `line_edit.py`, and all added to `__all__`):
  - `SCALE_NOTE = 0.2`
  - `span_m(n_traces: int, traces_per_metre: float) -> float`: `(n_traces - 1) / traces_per_metre`. Returns `0.0` when `traces_per_metre <= 0` or `n_traces < 2`.
  - `fit_scale(span: float, length: float) -> float`: `length / span`. `ValueError` when either is `<= 0`.
  - `@dataclass(frozen=True) class Fit: span: float`. This is a scale worked out when the edit is applied, against the grid's length then (the twin of `Inset`).
  - `is_fitted(placement: GridPlacement, span: float, length: float) -> bool` (call 7).
  - `LineEdit` gains `scale: float | Fit | None = None` and `travel_shift: float | None = None`. `placed()` resolves `Fit` against `length_along(frames[g], axis)` of the target grid `g`, and carries `scale` and `travel_shift` into the returned placement.
  - `LineEdit.fitted(self, span: float) -> LineEdit` returns `replace(self, start_along=Inset(0.0), scale=Fit(span))`. `ValueError` when `span <= 0`.
  - `same_placement` also compares `scale` and `travel_shift` within `SAME_M`.
  - `placement_note` adds the scale part (call 8) after the existing parts, joined with `; ` as now.
  - `followed_length(placement, old_length, new_length, span: float = 0.0) -> GridPlacement`. With `span > 0` and `is_fitted(placement, span, old_length)`, it returns the line fitted to `new_length`: Start from the inset rule and `scale=fit_scale(span, new_length)`. Otherwise it behaves as today.
  - `GridEditReport` gains `refitted: tuple[tuple[str, float, int], ...] = ()`, holding `(axis, new length, fitted lines refitted)`. `message()` produces the copy in Global Constraints. The existing `moved` field and its message are unchanged.

- [ ] **Step 1: Write the failing pure tests** in `test_pure_line_edit.py`, alongside its `GRID` (15 m along y), `FRAMES`, `FWD` and `REV`:

```python
def test_fit_puts_both_ends_on_the_edges_whichever_way_the_line_runs():
    span = 15.5  # a line that read 0.5 m long on the 15 m grid
    for seen in (dataclasses.replace(FWD, start_along=0.3), REV):
        p = LineEdit("k", seen).fitted(span).placed(FRAMES)
        first, last = p.start_along, p.start_along + p.direction * p.scale * span
        assert sorted([first, last]) == [pytest.approx(0.0), pytest.approx(15.0)]
    assert span_m(931, 60.0) == pytest.approx(15.5) and span_m(1, 60.0) == 0.0
    assert span_m(100, 0.0) == 0.0
    with pytest.raises(ValueError):
        LineEdit("k", FWD).fitted(0.0)


def test_flip_and_move_keep_scale_and_shift_and_a_pending_fit_refits():
    seen = dataclasses.replace(FWD, scale=1.02, travel_shift=0.24)
    flipped = LineEdit("k", seen).flipped(FRAMES).placed(FRAMES)
    assert (flipped.scale, flipped.travel_shift) == (1.02, 0.24)
    typed = LineEdit("k", seen).moved_to("B", FRAMES).placed(FRAMES)  # GB is 9 m along y
    assert typed.scale == 1.02
    fitted = LineEdit("k", seen).fitted(15.5).moved_to("B", FRAMES).placed(FRAMES)
    assert fitted.scale == pytest.approx(9.0 / 15.5) and fitted.travel_shift == 0.24


def test_setting_the_values_a_line_already_has_is_no_change():
    e = LineEdit("k", REV, scale=1.0, travel_shift=0.0)
    assert not e.changes(FRAMES)
    assert LineEdit("k", REV, travel_shift=0.1).changes(FRAMES)
    assert not same_placement(REV, dataclasses.replace(REV, scale=1.001))


def test_a_scale_far_from_one_is_noted():
    assert placement_note(dataclasses.replace(FWD, scale=1.45), GRID) == (
        "scale ×1.450 stretches it by 45%"
    )
    assert placement_note(dataclasses.replace(FWD, scale=0.7), GRID) == (
        "scale ×0.700 compresses it by 30%"
    )
    assert placement_note(dataclasses.replace(FWD, scale=1.19), GRID) == ""
    assert placement_note(dataclasses.replace(FWD, travel_shift=3.0), GRID) == ""  # call 4


def test_a_fitted_line_is_fitted_again_when_its_grid_changes_length():
    span = 15.5
    fitted_rev = dataclasses.replace(REV, scale=15.0 / span)
    assert is_fitted(fitted_rev, span, 15.0)
    again = followed_length(fitted_rev, 15.0, 16.0, span)
    assert (again.start_along, again.scale) == (pytest.approx(16.0), pytest.approx(16.0 / span))
    typed = dataclasses.replace(FWD, scale=1.02)  # ends at 15.81, not on the edge
    assert not is_fitted(typed, span, 15.0) and followed_length(typed, 15.0, 16.0, span) == typed
    as_recorded = dataclasses.replace(FWD)  # scale 1 is never "fitted"
    assert not is_fitted(as_recorded, 15.0, 15.0)
    shifted = dataclasses.replace(fitted_rev, travel_shift=0.3)  # call 4: ends judged unshifted
    assert is_fitted(shifted, span, 15.0)


def test_the_length_report_counts_refitted_lines():
    both = GridEditReport("F", moved=(("y", 11.0, 1),), refitted=(("y", 11.0, 2),))
    assert both.message() == (
        "F is now 11.00 m along y; its 1 reversed line(s) moved with the far edge, "
        "and its 2 fitted line(s) were fitted to the new length."
    )
    assert GridEditReport("F", refitted=(("y", 11.0, 2),)).message() == (
        "F is now 11.00 m along y; its 2 fitted line(s) were fitted to the new length."
    )
```

- [ ] **Step 2: Run the pure file and see the new tests fail.**
- [ ] **Step 3: Implement the `line_edit.py` interfaces above.**
- [ ] **Step 4: Write the failing QGIS tests.**
  - **`test_plugin_session.py`:** a new test, `test_a_grid_length_change_keeps_fitted_lines_fitted`.
    - **Setup:** Grid `F` is 10.5 m along y, with lines from `synthetic_dzt(..., n_traces=601)` (span 10.0 m at 60/m):
      - a forward line fitted to the grid (`start_along=0.0`, `scale=1.05`);
      - a reversed line fitted to the grid (`start_along=10.5`, `scale=1.05`);
      - a forward line at scale 1.
    - **Action:** `replace_grid(replace(F, size_y=11.0))`.
    - **Assert:**
      - The first two lines have `scale == approx(1.1)`, and their recorded ends lie on 0 and 11.
      - The third line is unchanged.
      - `report.message()` is the "both kinds" copy with `n=1`, `m=2`.
      - There was one `grids_changed` and one `lines_changed`.
  - **`test_plugin_layers.py`:** a new test, `test_a_pick_follows_a_destagger_and_a_scale_edit`, using the `populated` fixture, `_a_pick` and `_rows`.
    - **Setup:** write a pick at trace 30 on `raw/FILE__001.DZT`.
    - **Action:** `session.edit_lines([LineEdit(key, placement, travel_shift=0.24, scale=0.95)])`.
    - **Assert:**
      - The row's `distance_m` equals `session.line_for_key(key).distance_along()[30]`.
      - Its point equals `_line_point(session, key, 30)` (abs 1e-9).
      - `trace` and `note` are unchanged.
  - **`test_plugin_slices_engine.py`:** a new test beside `test_a_placement_edit_to_a_prepared_line_re_prepares`, named `test_a_scale_or_destagger_edit_to_a_prepared_line_re_prepares`, using the same `sourced` fixture and the module's `_edit`.
    - **Action:** `_edit(session, key, scale=0.95)`.
    - **Assert:** one more preparation, with the prepared coords equal to `trace_coords`.
    - **Then:** the same for `_edit(session, key, travel_shift=0.2)`.
- [ ] **Step 5: Run those three files and see the session test fail.** The layers and slices tests should pass as soon as `same_placement` compares the new fields (call 12). If either fails, that is a finding: report it rather than adding code to the engine.
- [ ] **Step 6: Change `replace_grid`.**
  - Run every line on the changed axis, not only the reversed ones, through `followed_length(p, old_len, new_len, span_m(line.n_traces, line.header.traces_per_metre))`.
  - Count reversed lines moved into `moved`, as today. Count fitted lines refitted into `refitted`.
  - Replace a line only when its placement changed.
- [ ] **Step 7: Run core + pure, the four test files above, `test_plugin_edit_lines_dialog.py` and `test_plugin_grid_dialog.py`. All of them pass.** Then run lint and types.
- [ ] **Step 8: Commit** `feat: fit and destagger rules; a fitted line stays fitted when its grid changes length (#3, #47)`, then push.

---

### Task 3: Edit lines (Scale, Destagger, Fit to grid edges) and the Survey panel

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/edit_lines_dialog.py`
  - Columns become Label, Offset (m), Dir, Start (m), **Scale**, **Destagger (m)**, Grid, Along, Traces, Length (m), Picks, Note, with `COL_SCALE` and `COL_DESTAGGER` added to the constants.
  - `EDITABLE` gains both.
  - Add the two bulk rows (call 9) and the header tooltips.
  - Add cell parsing for both columns.
  - Change the dialog width to `resize(1100, 560)`.
  - Update the module docstring.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/survey_dock.py`, in `_line_item`, for the suffixes (call 10). Use `getattr(p, "scale", 1.0)` and `getattr(p, "travel_shift", 0.0)` as the existing code does for `direction`.
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_edit_lines_dialog.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_survey_dock.py`

**Interfaces:**
- Consumes: Task 2's `LineEdit.scale`, `LineEdit.travel_shift`, `LineEdit.fitted(span)` and `span_m`.
- Produces:
  - Widgets: `scale_spin`, `set_scale_button`, `fit_button`, `destagger_spin`, `set_destagger_button`.
  - Methods, each a guarded slot like `flip`:
    - `set_scale(value: float) -> None`
    - `fit_to_edges() -> None`
    - `set_destagger(value: float) -> None`
  - `set_scale` and `set_destagger` go through the existing `_apply`. `fit_to_edges` skips any row whose `span_m(...)` is `0.0` and names it, using the Global Constraints copy, on the status line. It still fits the others.
  - **Watch the name clash:** the existing `shift_button`, `offset_spin` and `shift_offset` move offsets *across* the grid. Leave them exactly as they are.

- [ ] **Step 1: Write the failing tests** in `test_plugin_edit_lines_dialog.py`, using the `table` fixture (Grid5 is 15 m; six 60-trace lines, so span is 59/60 m).
  - **`test_fit_to_grid_edges_puts_both_ends_of_every_selected_line_on_the_edges`**
    - **Action:** select all, then `fit_to_edges()`.
    - **Assert before OK:**
      - Every Scale cell reads `f"{15.0 / (59 / 60):.4f}"` and is highlighted (`CHANGED`).
      - Start reads `0.00` on forward rows and `15.00` on reversed rows.
      - The Note on every row carries the "stretches it by" text, because this scale is far from 1.
    - **Action:** `dialog.accept()`.
    - **Assert after OK:** each line's `distance_along()` has ends on 0 and 15 (abs 1e-9).
  - **`test_fit_skips_a_line_that_cannot_be_fitted_and_says_so`**
    - **Setup:** reuse the setup of `test_a_line_with_no_distance_axis_is_listed_and_editable` (a time-triggered line).
    - **Action:** select it and a normal row, then fit.
    - **Assert:**
      - The status line contains `has no recorded length to fit, so it was left as it is`.
      - The normal row's Scale changed and the time-triggered row's did not.
  - **`test_typing_a_scale_and_a_destagger_edits_only_that_row`**
    - **Action:** type `0.95` into row 2's Scale cell and `0.24` into its Destagger cell.
    - **Assert:**
      - Only row 2 is highlighted in those columns.
      - The cells read `0.9500` and `0.24`.
    - **Action:** OK.
    - **Assert:** the line's placement has `scale == 0.95` and `travel_shift == 0.24`.
  - **`test_a_scale_that_is_not_above_zero_is_refused`**
    - **Action:** parametrize `"0"`, `"-1"`, `"abc"` and `"nan"` into a Scale cell.
    - **Assert:**
      - The status line contains `is not a scale above 0; unchanged` (`abc` may give the existing "is not a number" text instead; pin whichever the code gives, but nothing is recorded).
      - The cell reverts.
  - **`test_set_scale_and_set_destagger_change_every_selected_row`**
    - **Action:** select rows 0 and 1. Set the scale spin to 0.97 and press Set. Set the destagger spin to 0.3 and press Set.
    - **Assert:**
      - Both rows show the values, and the other rows are untouched.
      - The status line counts 2 lines changed.
  - **`test_a_pending_fit_uses_the_grid_length_at_ok`**
    - **Action:** select the forward rows (0, 2, 4) and fit. Then `session.replace_grid(replace(GRID5, size_y=14.0))`, then OK.
    - **Assert:** the forward lines' last traces sit at 14.0.
  - **Extend** `test_every_slot_reports_an_unexpected_failure_and_does_not_raise` with a `"fit"` case: patch `_frames` to raise, then call `fit_to_edges()`.
  - **`test_plugin_survey_dock.py`, `test_a_corrected_line_shows_its_scale_and_destagger`:**
    - **Action:** edit a line to `scale=0.954` and `travel_shift=0.24` through `session.edit_lines`.
    - **Assert:**
      - Its item text contains `· ×0.954` and `· destagger +0.24 m`.
      - An uncorrected line's text contains neither `×` nor `destagger`.
- [ ] **Step 2: Run the two files and see the new tests fail.**
- [ ] **Step 3: Implement.** Highlighting: COL_SCALE and COL_DESTAGGER differ when the placed value is more than `SAME_M` away from `seen`'s.
- [ ] **Step 4: Run both files and the rest of the Edit lines and Survey tests; all pass.** Then run lint.
- [ ] **Step 5: Render the dialog offscreen to a PNG**, with a fitted, highlighted table and the panel enabled, and look at it. Check that no column is cut off, the bulk rows line up with the existing rows, and nothing overlaps. Write the PNG to the scratchpad, not the repo, and attach its path in the report.
- [ ] **Step 6: Commit** `feat(plugin): Scale, Destagger and Fit to grid edges in Edit lines; the Survey panel shows them (#3, #47)`, then push.

---

### Task 4: Fit at import, and the documentation

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/lookup.py`
  - `ImportOptions` gains `fit_to_grid: bool = False`.
  - `ImportRow` gains `scale: float = 1.0`.
  - `recompute_offsets` sets `row.scale` and the note.
  - `rows_to_lines` passes `scale=row.scale`.
  - `fit_scale` and `span_m` are imported from `nsgeo_qgis.line_edit`.
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/import_dialog.py`
  - Add `self.fit_to_grid = QCheckBox("Stretch or compress each line to the grid's length")` on a form row labelled `Line length`, after `Start along`. It is unchecked by default, carries the import tooltip, and `toggled` re-plans the rows the way the other option widgets do.
  - `options()` passes `fit_to_grid`.
- Modify: `docs/guide/getting-started.md`
  - **Step 3** gains one sentence on the checkbox.
  - **"Fixing lines after import"** gains a short paragraph. Cover **Scale**, **Destagger (m)** and **Fit to grid edges**: what each is for, in the user's terms (wheel or terrain error; stagger between lines walked out and back), and that a fitted line stays fitted when the grid's length changes. Also say that the Note flags a scale more than 20% from 1, and that the destagger moves every line forward along its own direction of travel, so setting it on every line is the usual first step.
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_lookup.py`, `packages/nsgeo-qgis/tests/qgis/test_plugin_import_dialog.py`

**Interfaces:**
- Consumes: Task 2's `fit_scale(span, length)` and `span_m(n_traces, traces_per_metre)`. Task 1's `GridPlacement(..., scale=)`.
- Produces: `ImportOptions.fit_to_grid` and `ImportRow.scale`.

- [ ] **Step 1: Write the failing tests.**
  - **Pure (`test_pure_lookup.py`), `test_real_campus_lines_fitted_to_a_10_m_grid_end_on_its_far_edge`:**
    - **Setup:** plan the ten `CAMPUS_LINES` (import `REAL_DZT` from `plugin_testing`; skip when empty) with `ImportOptions(grid_id="G", axis="y", spacing=0.5, grid_size_along=10.0, fit_to_grid=True)`.
    - **Action:** `recompute_offsets`, then `rows_to_lines`.
    - **Assert:**
      - Every line's `distance_along()` starts on its edge and ends on the other one (abs 1e-9).
      - FILE__008's row scale is about `10 / 11.08` (rel 1e-3).
      - Every note contains `fitted to the grid's 10.00 m` and none contains `exceeds grid size`.
  - **`test_fit_off_leaves_scale_one_and_keeps_the_exceeds_note`:** the same lines with the default options. Every scale is `1.0`, and FILE__008's note contains `exceeds grid size along y`.
  - **`test_fit_without_a_grid_length_says_so`:** `grid_size_along=None` with `fit_to_grid=True`. The scale stays `1.0`, and the note contains `cannot be fitted without a known grid length`.
  - **QGIS (`test_plugin_import_dialog.py`), `test_the_fit_checkbox_imports_fitted_lines_and_is_off_by_default`:**
    - **Assert:** the box starts unchecked.
    - **Action:** check it.
    - **Assert:** the Note column shows the fitted text.
    - **Action:** import.
    - **Assert:** the session's lines carry the row scales.
    - Follow the file's existing import-flow helpers.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
  - The note uses `_merge_note`, with a new marker `"fitted to the grid's"`. Turning fitting on clears the `exceeds grid size along` component, and turning it off clears the fitted one.
  - A row that is not placeable keeps scale 1.
- [ ] **Step 4: Run core + pure and the import dialog file. All pass, and the skip count has not risen.** Then run lint and types.
- [ ] **Step 5: Update the guide**, then commit `feat: fit lines to the grid at import; guide for Scale, Destagger and Fit (#3, #47)`, then push.

---

## After Task 4 (coordinator)

1. **Run the full QGIS tier and record the counts.** Compare them with the baseline.
2. **Run a whole-branch review on opus**, from a scratch copy.
3. **Deploy to a new profile, `ns_geo_placement`** (a copy of `ns_geo`, `dev_link` to this worktree).
4. **Build the walkthrough** as a claude.ai Artifact with `db`. **Stop for the user's results.**
   - Run it on the user's own grids. One check is the campus ten fitted to a 10 m grid.
   - Another check runs on the 60-line `with-dzg` survey placed by tape: fit, then a hand-typed destagger around 0.15 m per line. The strongest feature at 22–28 ns should tighten from a sawtooth.
   - Copy any site folder before it is used.
5. **The README roadmap:** In progress names this branch from its first commit. At merge, the row moves to Done.
6. **Then the user decides** whether to merge chunk A on its own or carry on to chunk B (Measure) on this branch first.
