# Whole site never stuck — Plan A (the engine) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Whole site always finishes preparing, or a timed-out wait names what holds it. Clear #75's
Site engine, Site export and Whole site UI items, and #157 items 1 and 3.

**Architecture:**
- `SiteEngine` gains a plain-text busy report that every site test wait prints when it times out.
- A loop of the site-scope tests under load runs in the background from Task 1's commit while the
  independent tasks (2–5) are built. Task 6 then fixes the dispatch suspects and whatever the loop
  named, each pinned by a deterministic test.
- The CRS, outline and gather helpers move out of `site_engine.py` into `site_geometry.py`. The CRS
  transform there becomes one C++ call.

**Tech Stack:** Python 3.12 (core also 3.9), numpy, PyQGIS 3.44/4.2, pytest.

**Spec:** `docs/superpowers/specs/2026-11-18-nsgeo-site-never-stuck-design.md` (Parts 1–4). Part 5,
the background fill, is Plan B. It is written after this plan is built, once the costs after the
fill lands have been measured.

## Global Constraints

**Paths:**
- `P` = `packages/nsgeo-qgis/nsgeo_qgis`, `T` = `packages/nsgeo-qgis/tests`,
  `C` = `packages/nsgeo-core/src/nsgeo`, `CT` = `packages/nsgeo-core/tests`.
- The worktree is `.worktrees/nsgeo-site-never-stuck`. Every command runs from its root.

**Tests:**
- **Core and pure:** use the worktree's own `.venv` (already built, nsgeo editable from this
  worktree):
  - `./.venv/bin/python -m pytest packages/nsgeo-core/tests -q -p no:xonsh`
  - `./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q -p no:xonsh`

  Never use the main checkout's `.venv`: it imports main's core.
- **QGIS tier:** `packages/nsgeo-qgis/scripts/qgis_tests.sh <file or -k ...>`. It uses main's
  `.venv-qgis`, and conftest puts this tree's sources first. Before pushing, run the touched QGIS
  files and `qgis_tests.sh packages/nsgeo-qgis/tests/qgis -m real_data`. Never run the whole QGIS
  tier locally: CI runs it on 3.44 and 4.2.
- **Fail first:** every new test must fail before its fix. Run it and see it fail for the stated
  reason.
- **Tests that dodge the hazard are bug reports.** A test may not avoid the input that breaks the
  code.

**Code rules:**
- Every Qt slot and timer callback guards its whole body (`except Exception` → `_log` or
  `_report`), and never raises.
- No Qt off the GUI thread.
- Core stays numpy-only and Python 3.9-compatible: no `zip(strict=)`, no `match`.
- Run `ruff check .` and `ruff format --check .` with `./.venv/bin/ruff`. CI's mypy command is in
  `.github/workflows/` (the `mypy --config-file packages/nsgeo-core/pyproject.toml …` step). Run it
  the same way when a task adds a file to that list.
- User-facing strings are plain sentences in the plugin's register: no jargon, no "error code".

**Process:**
- Commit after each task with a `type(scope): … (#issue)` message, ending with the attribution line
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`, and push to
  `origin nsgeo-site-never-stuck` at once.
- Reviewers never edit files in this worktree.
- **#75 is split with session N.** Touch only the Site engine, Site export and Whole site UI
  sections. Check each item against the code before fixing it, and record items already gone
  (with the commit or file:line that shows it) in the task report. If an item turns out bigger
  than #75 makes it look, stop and report it rather than growing the task.
- **#196 is not #166.** `test_a_site_refine_for_a_window_left_behind_never_draws` and its This
  grid twin fail under load at `assert finished_late.is_set()`. Note such failures and move on.

## Review Focus

1. **A grid in another CRS than the site** (a mixed-CRS site): its extent, gathers and export must
   come out the same after the transform becomes one call. Task 5 pins equality against the
   per-point path on `site3_factory(crs=…)`.
2. **A grid removed while its task outlives the cancel wait:** the queue continues, with no second
   wait and no extra "no longer exists" report. Pinned in Task 6.
3. **The coverage view on an axis-aligned This grid** reads an exact north-up plan with no `ids` or
   `weights`. Lean taps must give the same counts and values as full ones. Pinned in Task 2.
4. **A preview whose lattice phase puts a pixel centre just outside a grid's first or last cell
   column or row.** Pinned in Task 2 by the phase sweep.
5. **The busy report on a disposed or half-torn-down site:** it is used inside failure messages, so
   it must never raise. Pinned in Task 1.

---

### Task 1: The busy report, and every site wait prints it (#166 part 1)

**Files:**
- Modify: `P/site_engine.py` (add `busy_report`)
- Modify: `P/slices_engine.py` (add `pending_tasks`)
- Modify: `T/plugin_testing.py` (add `wait_for_site`)
- Modify: `T/qgis/test_plugin_site_engine.py`, `T/qgis/test_plugin_site_scope.py`,
  `T/qgis/test_plugin_site_export.py` (use `wait_for_site`)
- Test: `T/qgis/test_plugin_site_engine.py`

**Interfaces:**
- **Produces `SliceEngine.pending_tasks -> int`,** a property: how many of this engine's tasks have
  not run `finished` yet (`len(self._pending)`).
- **Produces `SiteEngine.busy_report() -> str`.** It never raises: on any exception it returns
  `f"could not describe the site: {exc}"`. The lines, in this order, use exactly these spellings
  (tests pin them):
  ```
  active: True · preparing: 'A' · queue: ['B']
  retry timer: on · reaper timer: off · in dispatch: False
  engine A: running True · live task True · pending tasks 1
  engine B: running False · live task False · pending tasks 0
  retiring engine 1: running False · live task True · pending tasks 1
  exclusive peer 1: live task False
  grid A: preparing (0 of 4)
  grid B: queued
  ```
  - `preparing:` shows `None` when nothing prepares. When the preparing grid's registration no
    longer equals `_preparing_fp`, append ` (moved since dispatch)`.
  - The `retiring engine` and `exclusive peer` lines appear only when there are any. They are
    numbered from 1.
  - The `grid` lines come in source order, then any other grid in `_states`. The `(done of total)`
    part comes from `_progress`, only while it is set.
- **Produces `wait_for_site(site, timeout_ms: int = 60_000) -> None`** in `T/plugin_testing.py`.
  It returns once `site.wait_until_idle(timeout_ms)` is true. Otherwise it raises
  `AssertionError(f"the site did not finish preparing in {timeout_ms} ms\n{site.busy_report()}")`.

- [ ] **Step 1: Write the failing tests** in `T/qgis/test_plugin_site_engine.py`

```python
def test_a_timed_out_wait_names_what_holds_the_site(site3, make_site, monkeypatch):
    release = threading.Event()
    real_load = Line.load  # from nsgeo.model.survey import Line

    def held_load(self):
        release.wait(30)
        return real_load(self)

    monkeypatch.setattr(Line, "load", held_load)
    site = make_site(site3.session)
    site.set_source(site3.source(grids="AB"))
    try:
        with pytest.raises(AssertionError) as caught:
            wait_for_site(site, 300)
    finally:
        release.set()
    message = str(caught.value)
    assert "the site did not finish preparing in 300 ms" in message
    assert "active: True · preparing: 'A' · queue: ['B']" in message
    assert "engine A: running True · live task True" in message
    assert "grid A: preparing (0 of 4)" in message
    assert "grid B: queued" in message
    wait_for_site(site)  # released: it finishes


def test_the_busy_report_never_raises_on_a_disposed_site(site3, make_site):
    site = make_site(site3.session)
    site.set_source(site3.source(grids="A"))
    wait_for_site(site)
    site.dispose()
    report = site.busy_report()
    assert report.startswith("active: False · preparing: None · queue: []")
```

- [ ] **Step 2: Run them and see them fail**

Run: `packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis/test_plugin_site_engine.py -k "busy_report or names_what_holds" -q`

Expected: FAIL, with an ImportError for `wait_for_site` or an AttributeError for `busy_report`.

- [ ] **Step 3: Implement** `SliceEngine.pending_tasks`, `SiteEngine.busy_report()` and
  `wait_for_site`, as the Interfaces block gives them.

- [ ] **Step 4: Run the two tests and see them pass.** Same command as Step 2. Expected: PASS.

- [ ] **Step 5: Make every asserting site wait use `wait_for_site`**
  - In the three test files, replace each `assert <x>.wait_until_idle(N)` (with or without a
    message) with `wait_for_site(<x>, N)`. That includes `settle()` in
    `test_plugin_site_scope.py` (~line 116) and `prepared()` in `test_plugin_site_engine.py`
    (~line 81).
  - Leave the waits that don't assert alone. Those are the teardown ones (`make_site`'s
    `engine.wait_until_idle(20_000)`, `finally:` blocks).
  - Check with: `grep -n "assert .*wait_until_idle" packages/nsgeo-qgis/tests/qgis/test_plugin_site_{engine,scope,export}.py`.
    Expected: no output.

- [ ] **Step 6: Run the three files.**

Run: `packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis/test_plugin_site_engine.py packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py packages/nsgeo-qgis/tests/qgis/test_plugin_site_export.py -q`

Expected: all pass, except a #196 flake if any. Note it and move on.

- [ ] **Step 7: Commit and push:** `test(site): a timed-out site wait names what holds it (#166)`.

> **Controller, after Task 1 lands:** start the "before" loop, as described under **The #166
> loop** at the end of this plan. Do it in a detached worktree at Task 1's commit, in the
> background, and carry on with Task 2.

---

### Task 2: #157 items 1 and 3, the coverage edge line and north-up plan memory

**Files:**
- Modify: `C/slices/site.py` (`compose_footprints`, ~line 287)
- Modify: `C/slices/resample.py` (`Taps.lean`, `Taps.take`, `sample_counts`)
- Modify: `C/slices/display.py` (the north-up plan cache, ~lines 262–275, `north_up_plans_nbytes`,
  `clear_north_up_plans`)
- Modify: `C/slices/__init__.py` (export the two new functions)
- Modify: `P/slices_plan.py` (`format_status(..., extra_bytes=0)`)
- Modify: `P/slices_engine.py` (`status_text` counts the plans)
- Test: `CT/test_slices_site.py`, `CT/test_slices_resample.py`, `CT/test_slices_display.py`,
  `T/pure/test_pure_slices_plan.py`, `T/qgis/test_plugin_slices_engine.py`

**Interfaces:**
- **Produces `Taps.lean() -> Taps`.**
  - When not `exact`, it returns `self`.
  - When `exact`, it returns taps with the same `nearest`, `nx`, `ny` and `exact=True`, but `ids`
    and `weights` of shape `(4, 0)`.
  - `take()` on lean taps returns lean taps.
  - `sample` already returns before reading `ids` when exact. `sample_counts` gains an exact path
    that reads `nearest` only: the count at the nearest cell, NaN where outside or not finite and
    positive. Exact means each point sits on one cell centre, so this equals today's largest
    positive-weight corner.
  - Only the north-up plan uses `lean()`. Cut sections (`C/slices/section.py`) read `ids` and
    `weights` and keep full taps.
- **Produces `north_up_plans_nbytes() -> int` and `clear_north_up_plans() -> None`** in
  `C/slices/display.py`, both exported from `nsgeo.slices`.
  - The `functools.lru_cache` on `_north_up_plan` is replaced by an explicit two-slot LRU (an
    `OrderedDict` behind a `threading.Lock`, since exports call `to_north_up` on a worker thread).
  - `north_up_plans_nbytes()` sums `taps.nbytes` over the plans held.
  - `_build_north_up_plan` stores `taps.lean()`.
- **Produces `format_status(mode, n_lines, estimate, redraw_ms, *, extra_bytes: int = 0) -> str`.**
  `extra_bytes` is added to the held figure.
- **Produces a change to `SliceEngine.status_text()`:** it passes
  `extra_bytes=north_up_plans_nbytes()`, so This grid's status line counts the cached plans.

- [ ] **Step 1: Write the failing tests**

```python
# CT/test_slices_site.py: the phase sweep (#157 item 1)
@pytest.mark.parametrize("ratio", [8, 16])
def test_a_coarse_preview_never_misses_a_grids_edge_line(ratio):
    cell, n = 0.05, 400
    pixel = cell * ratio
    misses = []
    for k in range(64):  # the lattice phase, across one whole pixel
        offset = k * pixel / 64
        frame = CubeFrame((offset, offset), 0.0, cell, n, n, CRS)
        lat = SiteLattice.covering([slice_extent(frame)], pixel, CRS)
        where = footprint(bilinear_taps(frame, lat.pixel_centres()), lat.height, lat.width)
        for axis, index in (("col", 0), ("col", n - 1), ("row", 0), ("row", n - 1)):
            one = np.full((n, n), np.nan, dtype=np.float32)
            if axis == "col":
                one[:, index] = 1.0
            else:
                one[index, :] = 1.0
            out = compose_footprints(lat, [(where, one)], counts=True, cells_per_pixel=ratio)
            if not np.isfinite(out).any():
                misses.append((k, axis, index))
    assert misses == []
```

- **`CT/test_slices_resample.py`:**
  - `test_lean_taps_drop_ids_and_weights_and_sample_the_same`. On an axis-aligned frame whose
    points are its cell centres, `taps.exact` holds. `lean = taps.lean()` has
    `lean.ids.size == 0 and lean.weights.size == 0`.
    - `sample(v, lean)` equals `sample(v, taps)`, NaNs included. The values hold NaN and inf.
    - `sample_counts(c, lean)` equals `sample_counts(c, taps)`. The counts hold 0, NaN and positive
      values.
    - `lean.take(idx)` is lean and samples the same as `taps.take(idx)`.
  - `test_lean_on_inexact_taps_is_the_same_object`. On a rotated frame, `taps.lean() is taps`.
- **`CT/test_slices_display.py`:**
  - `test_the_north_up_cache_reports_what_it_holds`:
    1. `clear_north_up_plans()`, then `north_up_plans_nbytes() == 0`.
    2. `to_north_up` on a rotated frame F1 and an axis-aligned frame F2 makes `north_up_plans_nbytes()`
       equal `_north_up_plan(F1)[0].nbytes + _north_up_plan(F2)[0].nbytes`.
    3. F2's cached taps hold `ids.size == 0`.
    4. A third frame F3 evicts F1, so the total equals F2's plus F3's.
  - `test_an_exact_north_up_plan_holds_no_ids_or_weights` covers point 3 alone, on an 800 × 1000
    axis-aligned frame. Its `nbytes` is under 4 MB (`nearest` only: 3.2 MB).
- **`T/pure/test_pure_slices_plan.py`:**
  - `test_format_status_counts_extra_bytes`. `format_status(…, extra_bytes=50 * 2**20)` names 50 MB
    more than the same call without it. Use the existing test's estimate and compare through
    `format_bytes`.
- **`T/qgis/test_plugin_slices_engine.py`:**
  - `test_this_grids_status_counts_the_cached_north_up_plans`. A prepared engine, after a
    `to_north_up` on a rotated frame, has `north_up_plans_nbytes() > 0`. Its `status_text()` equals
    `format_status(engine.mode, engine.line_count, engine.estimate, engine._redraw_ms,
    extra_bytes=north_up_plans_nbytes())`.

- [ ] **Step 2: Run them and see them fail**
  - Core: `./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_site.py packages/nsgeo-core/tests/test_slices_resample.py packages/nsgeo-core/tests/test_slices_display.py -q -p no:xonsh -k "edge_line or lean or north_up"`
  - Pure: `./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py -q -p no:xonsh -k extra_bytes`
  - QGIS: `packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py -k north_up -q`

  **Expected:**
  - the sweep fails with misses (#157 measured 8 of 64 phases at 8× and 20 of 64 at 16× for first
    or last lines);
  - the others fail with ImportError, AttributeError or TypeError.

- [ ] **Step 3: Implement**
  - The reach in `compose_footprints` becomes
    `max(math.ceil(cells_per_pixel / math.sqrt(2.0)), cells_per_pixel - 1)`. Keep the
    `counts and cells_per_pixel > 1` condition.
  - Fix the docstring sentence about the reach.
  - Then add the Interfaces block's `lean`, `take`, `sample_counts` path, cache, functions,
    `format_status` and `status_text` changes.
  - The comment above `_NORTH_UP_PLANS` says "about 52 bytes a point". Make it say an exact plan
    holds 4.

- [ ] **Step 4: Run the Step 2 commands, then the whole core and pure suites.** Expected: all pass.
  The existing `test_a_preview_shows_every_one_cell_line_of_coverage` still passes.

- [ ] **Step 5: Commit and push:** `fix(slices): a coarse preview keeps a grid's edge line; north-up plans count and shed what they don't read (#157)`.

---

### Task 3: #75 Site export

**Already gone, verified while planning (at 3104edb):**
- **The writer duplicates M11:** `GeoTiffSiteWriter` now calls `slice_export.write_north_up`, and
  `apply_site_temporal_properties` calls `apply_band_windows`.
- **`NSGEO_SITE_CELL_M` can be the lattice pixel:** `_tag_dataset` writes `plan.cell_m`, the export
  cell, always.
- **The docstring lists the fill-radius key as always present:** the module docstring now names the
  four interpolation keys as absent on the coverage companion.

Confirm each, and list it in the report.

**Files:**
- Modify: `P/site_export.py` (`plan_site_export`, `site_export_job`: the transform from the
  engines; type fixes)
- Modify: `P/plugin.py` (`_export_site`, ~line 1683: stop passing `transform=`)
- Modify: `.github/workflows/<the lint workflow>` (add `site_export.py` to the mypy list)
- Modify: `T/qgis/conftest.py` (receive `make_site`), `T/qgis/test_plugin_site_engine.py`,
  `T/qgis/test_plugin_site_export.py`
- Test: `T/qgis/test_plugin_site_export.py`

**Interfaces:**
- **Produces `plan_site_export(site_engine, thickness_levels, step_levels, *, cell, lattice,
  method, finish, gains, velocities, left_out=None) -> SiteExportPlan`**, with no `transform`
  parameter.
  - `plan.transform` is the ready engines' common `choice.transform`.
  - It raises `RuntimeError("the grids were prepared with different transforms: …")` naming each
    grid and transform, if they differ.
  - `site_export_job` loses `transform` the same way.
- **Produces a `make_site` fixture moved to `T/qgis/conftest.py`,** unchanged, for both the engine
  and the export tests.

- [ ] **Step 1: Write the failing tests** in `test_plugin_site_export.py`
  - `test_the_file_records_the_transform_the_grids_were_prepared_with`. The site is prepared from
    `site3.source(transform="amp_abs")`. `export_site(...)` is called without `transform=`, so `KW`
    loses its `transform` key. The file's `NSGEO_SITE_TRANSFORM == "amp_abs"`.
  - `test_a_grid_with_no_velocity_exports_null_depths`. `velocities` omits C. Every band's
    `NSGEO_GRID_DEPTHS_M["C"]` is `None`, and its description holds no depth text for C, while A's
    depths are set.
  - **Fix these existing tests in place:**
    - the no-resident-cube test (~line 340) asserts `not site.engine_for(g).has_cube` instead of
      `mode != "resident"`;
    - the CRS assertion (~line 152) compares
      `QgsCoordinateReferenceSystem.fromWkt(ds.GetProjection()).authid()` with the site's CRS;
    - `test_a_ready_grid_with_no_site_axis_exports_as_absent` uses its `make_site` fixture instead
      of building and disposing a `SiteEngine` by hand.

- [ ] **Step 2: Run them and see them fail**

Run: `packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis/test_plugin_site_export.py -q`

Expected: the transform test fails with a TypeError (a missing `transform` argument). The no-velocity
test passes or fails on what it shows. If it passes at once, note that and keep it: it is a missing
test, not a missing fix.

- [ ] **Step 3: Implement**
  - Derive the transform as above, and update `P/plugin.py`'s `_export_site` and every test caller.
    Find them with `grep -rn "transform=" packages/nsgeo-qgis/tests/qgis/test_plugin_site_export.py`
    and `grep -rn "site_export_job\|plan_site_export" packages/nsgeo-qgis`.
  - Move `make_site` to `T/qgis/conftest.py` and drop both copies.
  - Add `packages/nsgeo-qgis/nsgeo_qgis/site_export.py` to the CI mypy list. Run that mypy command
    locally (`./.venv/bin/python -m pip install mypy==2.4.0` if it is missing) and fix what it
    reports. #75 expects an `arg-type` at the `slice_at` call and `union-attr` where `engine_for()`
    returns an Optional; see #18.

- [ ] **Step 4: Run** the export and engine test files, the pure suite, `ruff`, and the mypy command.
  Expected: all pass.

- [ ] **Step 5: Commit and push:** `fix(site-export): record the grids' own transform; type-check the site export; test gaps (#75)`.

---

### Task 4: #75 Whole site UI

**Already gone, verified while planning (at 3104edb):**
- **The unguarded `_note_z_edit` slot:** the method no longer exists, and its replacement is cited
  at `P/ui/slices_dock.py:~2649`.
- **dz seeded from the first ready grid:** `site_scope.py:~503` seeds from the finest sample
  interval among the included grids.
- **The self-compared velocity assertion:** `test_plugin_site_scope.py:~1005` compares C's own
  resolved velocity.

Confirm each, and list it in the report.

**Files:**
- Modify: `P/slices_plan.py` (add `snap_inside`, `window_levels`)
- Modify: `P/ui/slices_dock.py` (drop `_snap_inside`; `_step_levels` / `thickness_step_levels`
  use `window_levels`; expose `finish_debounce_ms`)
- Modify: `P/ui/site_scope.py` (a `SlicesDockView` Protocol for `dock`; no lazy import; `levels`
  uses `window_levels`; no `dock._…` reads)
- Modify: `P/plugin.py` (`_export_site` refuses while the site is busy)
- Test: `T/pure/test_pure_slices_plan.py`, `T/qgis/test_plugin_site_scope.py`

**Interfaces:**
- **Produces `snap_inside(value: float, decimals: int, *, upper: bool) -> float`** in
  `P/slices_plan.py`. It is today's `_snap_inside`, moved verbatim with its docstring.
- **Produces `window_levels(thickness_ns: float, step_ns: float, dz_ns: float) -> tuple[int, int]`**
  in `P/slices_plan.py`, returning `(max(1, round(thickness/dz)), max(1, round(step/dz)))`.
  `site_scope.levels(z, …)` and the dock's This grid rounding both call it.
- **Produces `SlicesDockView`,** a `typing.Protocol` in `P/ui/site_scope.py` naming every dock
  attribute `site_scope.py` reads, typed as precisely as the imports allow.
  - `SiteScope.__init__(self, dock: SlicesDockView)`, and the module-level functions that take
    `dock: Any` take `SlicesDockView`.
  - The one private read left, `dock._finish_debounce.interval()`, becomes a public
    `SlicesDock.finish_debounce_ms` property.
- **Produces the busy refusal in `QgisPlugin._export_site`.** While `site.is_running`, it shows
  `"wait until the site's grids finish preparing, then export."` (Warning, lowercase like the
  method's other refusal) and opens no dialog.

- [ ] **Step 1: Write the failing tests**
  - **Pure:**
    - `test_snap_inside_never_escapes_its_bound`: the cases of today's dock test, if any, moved,
      plus `snap_inside(2.00049, 3, upper=False) == 2.001` and
      `snap_inside(5.9996, 3, upper=True) == 5.999`;
    - `test_window_levels_rounds_and_floors_at_one`: `window_levels(1.0, 0.25, 0.5) == (2, 1)` and
      `window_levels(0.1, 0.1, 0.5) == (1, 1)`.
  - **QGIS, `test_plugin_site_scope.py`:**
    - `test_site_export_refuses_while_a_grid_prepares`. Hold a grid's `Line.load` behind an
      `Event`, as in Task 1. Call `plugin._export_site()` directly. The message log gets the
      refusal, and no export dialog opened (the `answer_modal` / dialog-driver guard sees none).
      Then release.
    - **The seeding rules #75 says are untested.** First grep for existing tests that cover each.
      Write only the missing ones, named for the rule:
      - the cell comes from the finest-spaced included grid;
      - the default inclusion is every grid with lines;
      - seeding happens only when the included set changes, not on every tick or a re-send of the
        same set.

- [ ] **Step 2: Run them and see them fail.** Pure: ImportError. QGIS: the export test fails (a
  dialog opens, or there is no message). Seeding tests that pass at once are recorded as "was
  untested, now pinned".

- [ ] **Step 3: Implement** the Interfaces block. `site_scope.py` then imports `snap_inside` at the
  top, and `grep -n "dock\._" packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py` prints only comments.

- [ ] **Step 4: Run** the pure suite, `test_plugin_site_scope.py`, `test_plugin_slices_dock.py` and
  ruff. Expected: all pass, except a #196 flake (note it).

- [ ] **Step 5: Commit and push:** `refactor(site-scope): a typed dock view, one level rounding, export refuses while preparing (#75)`.

---

### Task 5: #75 Site engine, the rest: mixed CRS, test gaps, the module split

**Already gone, verified while planning (at 3104edb):**
- **`_azimuth_in`'s cross-CRS result is untested:** `_azimuth_in` was removed in 0776c4d (fine
  cells A: bilinear at the cell size).
- **F-9:** `SlicesDock._resume_grid` hands the hook back from a `finally`.

**Changed by M17a:** the site CRS is now `session.site_crs()`, the site's own CRS once set, else the
first grid's (`P/site_engine.py:_site_crs`). Check what is left of "the site CRS follows the first
grid only as of the last rebuild":
- for a site with its own CRS, nothing;
- for an older site, a removed first grid already rebuilds through `_on_grids_changed`.

Then document or fix, and record which in the report.

**Files:**
- Create: `P/site_geometry.py`
- Modify: `P/site_engine.py` (use it; remove the moved code)
- Modify: `P/site_export.py` (`world_to_frame` uses `transform_points`)
- Test: `T/qgis/test_plugin_site_geometry.py` (new), `T/qgis/test_plugin_site_engine.py`,
  `T/qgis/test_plugin_slices_engine.py`

**Interfaces:**
- **Produces, in `P/site_geometry.py`:**
  - `EDGE_POINTS = 8`, moved from `_EDGE_POINTS`.
  - `transform_points(points: np.ndarray, source: str, target: str, context: QgsCoordinateTransformContext) -> np.ndarray`.
    It takes (n, 2) points to (n, 2) and raises `RuntimeError(f"no coordinate transform from {source} to {target}")`
    when the transform isn't valid.
    - **One C++ call.** Pack the points as a little-endian WKB LineString with numpy
      (`struct.pack("<BII", 1, 2, n)` + the float64 pairs), `QgsGeometry.fromWkb`,
      `geometry.transform(ct)`, then read back with `np.frombuffer(bytes(g.asWkb()), "<f8",
      offset=9)`.
    - n = 0 returns an empty (0, 2) array, and n = 1 pads to two points.
    - Measured while planning: 200 k points took 0.92 s one at a time and 0.10 s this way, with
      identical results.
  - `extent_in(frame: CubeFrame, crs: str, context) -> tuple[float, float, float, float]`, moved
    from `SiteEngine._extent_in`.
  - `gather_footprint(frame: CubeFrame, lattice: SiteLattice, context) -> Footprint`: the body of
    `SiteEngine._gather` after its cache check, moved.
- `SiteEngine._gather` keeps its cache and calls `gather_footprint(frame, lattice,
  QgsProject.instance().transformContext())`. `SiteEngine._transform` and `_extent_in` are removed;
  their callers use the module.
- `site_export.world_to_frame` keeps its signature and thread-safety: a fresh transform on each
  call, through `transform_points`.

- [ ] **Step 1: Write the failing tests**
  - **`T/qgis/test_plugin_site_geometry.py`:**
    - `test_transform_points_matches_one_point_at_a_time`. 1,000 points, EPSG:32616 → EPSG:32617
      and → EPSG:4326, each equal to a per-point `QgsCoordinateTransform.transform` to 1e-9.
    - `test_transform_points_handles_none_and_one_point`. Shapes are (0, 2) and (1, 2), and the
      value is right.
    - `test_transform_points_refuses_a_missing_transform`. An invalid CRS string raises
      RuntimeError with "no coordinate transform from".
    - `test_transform_points_is_one_call_not_one_per_point`. Time 100 k points through
      `transform_points` and through a per-point loop in the test itself, on the same machine. The
      first is at least 3× faster. This is relative, so load slows both.
  - **`T/qgis/test_plugin_site_engine.py`:**
    - `test_a_mixed_crs_site_gathers_the_same_after_the_move`. Build a site with C in a
      neighbouring UTM zone through `site3_factory`'s `crs` option (see its docstring for the
      form). C's gather (`site._gather("C", site.lattice)`) has taps equal to
      `bilinear_taps(frame, centres)`, where the test moves the same window's pixel centres one
      point at a time with `QgsCoordinateTransform.transform`.
    - `test_a_preparation_that_reads_no_line_fails_with_the_first_error` (the asynchronous failure
      path). `Line.load` raises `OSError("disk gone")` for grid B's lines only. B reads
      `failed: …disk gone…`, and A and C are ready.
  - **`T/qgis/test_plugin_slices_engine.py`:** `test_the_hook_can_be_given_to_the_constructor`
    disposes its second engine as well, in `finally`. That's an edit, not a new test.

- [ ] **Step 2: Run them and see them fail.** The geometry tests fail with ImportError. The failure
  path test, if it passes at once, is recorded as "was untested, now pinned" (#75's test gap).

- [ ] **Step 3: Implement** the module and the moves. The rest of the engine's items:
  - **The geometry rebuild inside the `grids_changed` emission:** either document the assumption in
    `_on_grids_changed`'s docstring, or defer the rebuild with `QTimer.singleShot(0, …)` behind a
    guarded slot. Record the choice and the reason in the report. Deferring changes when
    `geometry_problem` is set, so if you defer, show that no test reads it inside the same
    emission.
  - Afterwards, `wc -l packages/nsgeo-qgis/nsgeo_qgis/site_engine.py` is smaller by the moved code.
    Record the number.

- [ ] **Step 4: Run** the geometry, engine, export and site-scope test files, `-m real_data`, and
  ruff. Expected: all pass, except a #196 flake (note it).

- [ ] **Step 5: Commit and push:** `refactor(site): CRS, outline and gather helpers in site_geometry; one-call transforms; failure-path test (#75)`.

---

### Task 6: #166, the lost wakeup, and #75's dispatch suspects

**Before starting:** read the "before" loop's results (see **The #166 loop**). Record in the report:
- the batches run;
- the hangs, each with the busy report it printed;
- any #196 flakes.

If a hang's report names a cause these items don't cover, find its root cause with
superpowers:systematic-debugging. Add a deterministic test that drives that interleaving, and fix
it in this task as item (f).

**Files:**
- Modify: `P/site_engine.py` (`_start_next`, `_on_engine_prepared`, `_on_engine_progress`,
  `_retire`, `_drop_engine`, `_reap_retired`)
- Modify: `P/slices_engine.py` (add `detach`)
- Test: `T/qgis/test_plugin_site_engine.py`

**Interfaces:**
- **Produces `SliceEngine.detach() -> None`.** It disconnects the engine from `session.site_closed`,
  `grids_changed` and `lines_changed`, and sets `on_error`, `on_prepared` and `on_progress` to
  `None`, with `on_grid_moved = _ignore`. It does NOT cancel, clear or touch `_pending`: a running
  task still ends, and `has_live_task` still turns False when its `finished` runs. It is safe to
  call twice. `SiteEngine._retire` calls it in place of its own three assignments.
- **Produces the deferred deletion of disposed engines.** Wherever `SiteEngine` calls
  `engine.dispose()` (`_drop_engine`, `_reap_retired`, `dispose`), it then calls
  `engine.deleteLater()`.

**The items, each with its test:**

- **(a) The gate is re-run after the progress notify, and the registration is re-captured after it.**
  - The fix: in `_start_next`, after `_notify_changed()`, set `_preparing_fp` again. If
    `_anything_live()` is now true, undo the dispatch:
    - the grid goes back to the head of the queue, as `"queued"`, with no progress;
    - `_preparing` is set to `None`;
    - `_retry.start()`, then return.
  - Test `test_a_peer_that_starts_during_the_preparing_notify_holds_the_dispatch`:
    - A fake peer object with a settable `has_live_task` is passed to `add_exclusive`. The site's
      `on_changed`, on the first notify where A reads `"preparing"`, sets
      `peer.has_live_task = True`.
    - Assert that A's engine's `set_source` (wrapped to count) is not called while the peer is
      live, over about 300 ms of pumping.
    - Then set the peer to `False`. `wait_for_site(site, 20_000)` returns, and A is ready.
- **(b) A move inside the preparing notify still finishes.**
  - Test `test_a_grid_moved_during_the_preparing_notify_still_prepares`. The site's `on_changed`, on
    the first notify where A reads `"preparing"`, moves A with `site3.session.replace_grid(
    dataclasses.replace(grid_a, origin=(x + 1.0, y)))`. `wait_for_site(site, 20_000)` returns, A is
    ready, and its engine's frame is at the new origin.
  - **By reading, this hangs today.** A's engine has no choice yet when the move arrives, so it
    never hands the move over. `_preparing_fp` holds the old place, so `_on_engine_prepared` returns
    early forever with `_preparing` set. Confirm it fails before (a)'s fix. The recapture in (a) is
    its fix. It is a real lost wakeup; whether it is the one CI hit is for the loop to say.
- **(c) The progress total never shifts.**
  - The fix: `_on_engine_progress` records `(done + max(0, n_keys - total), n_keys)`, where
    `n_keys = len(choice.line_keys)` is stored at dispatch. A key the engine skipped counts as done.
  - Test `test_the_progress_total_never_shifts`. A's choice carries A's four keys plus one of B's
    line keys. Record every `site.grid_progress("A")` seen in `on_changed`. Every total is 5, and
    the done values never decrease.
- **(d) A retiring engine neither reports nor waits again.**
  - Test `test_a_retiring_engine_neither_reports_nor_waits_again`:
    1. Hold A's `Line.load` behind an `Event`, ignoring cancel, so the cancel wait runs out and the
       engine retires.
    2. `site3.session.remove_grid("A")`.
    3. Assert the site's `on_error` got exactly one "did not stop in time" message (one bounded
       wait, not two) and no "no longer exists" message. Today the retiring engine keeps its
       `on_error` and its session connections, so its own `_on_grids_changed` waits a second time
       and reports both.
    4. Release. `wait_for_site` returns, B and C are ready, and the retiring engine is gone after
       the reaper.
- **(e) Disposed engines don't pile up.**
  - Test `test_disposed_engines_do_not_pile_up_as_children`:
    1. Toggle B in and out of the source ten times, `wait_for_site` each time.
    2. Flush deferred deletes with `QCoreApplication.sendPostedEvents(None, <DeferredDelete>)`.
       Write the event type in a form PyQt5 and PyQt6 both accept, since CI runs both
       (`grep -rn DeferredDelete packages/nsgeo-qgis/tests` for the repo's form, if it has one).
    3. `len(site.findChildren(SliceEngine))` equals the number of grids with an engine.

- [ ] **Step 1: Write tests (a)–(e)** and any (f). Run each, and see (a), (c), (d) and (e) fail for
  their stated reasons. Record (b)'s result before the fix.

Run: `packages/nsgeo-qgis/scripts/qgis_tests.sh packages/nsgeo-qgis/tests/qgis/test_plugin_site_engine.py -k "notify or progress_total or retiring or pile_up" -q`

- [ ] **Step 2: Implement** (a)–(e), and (f) if any.

- [ ] **Step 3: Run** `test_plugin_site_engine.py`, `test_plugin_site_scope.py`,
  `test_plugin_site_export.py`, `test_plugin_slices_engine.py` and `-m real_data`. Expected: all
  pass, except a #196 flake (note it).

- [ ] **Step 4: Commit and push:** `fix(site): the dispatch gate after the notify, a steady progress total, retiring engines detached, disposed engines deleted (#166, #75)`.

> **Controller, after Task 6 lands:** run the "after" loop at the branch head, the same way, and
> record both loops' numbers in the decision record. **#166 closes at merge only if** the "before"
> loop hung, its report named a cause, the fix addressed it, and the "after" loop showed no hang.
> Otherwise #166 gets a comment with what the report now says, and stays open.

---

## The #166 loop (controller)

- **Where:** a detached worktree in the scratchpad at the commit under test:
  `git worktree add --detach "$SCRATCH/loop-<before|after>" <sha>`. It needs no venv of its own,
  since the QGIS tier runs from main's `.venv-qgis` with this tree's sources first.
- **What:** each round starts 12 copies of `test_plugin_site_scope.py` at once, each with its own
  `--basetemp` and log. Three rounds; this is #196's batch shape, on this 4-core machine:

  ```bash
  cd "$LOOP"
  for round in 1 2 3; do
    for i in $(seq 1 12); do
      QT_QPA_PLATFORM=offscreen /home/jameszd/Documents/Github/archaeo_geophysics/.venv-qgis/bin/python \
        -m pytest -p no:xonsh packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py -q \
        --basetemp="$SCRATCH/loop-tmp/r$round-$i" > "$SCRATCH/loop-logs/<tag>-r$round-$i.log" 2>&1 &
    done
    wait
  done
  ```

  Run it in the background, and read the logs when it ends.
- **What to look for:** a hang is a failure whose message starts "the site did not finish preparing
  in". Collect each one's busy report. Failures at `assert finished_late.is_set()` are #196: count
  them, and nothing more.
- **If the "before" loop shows no hang,** run one more round of 12 against the QGIS 4.2 Docker
  image if Docker is up (`DOCKER_CONTEXT=default` has no qgis images, so check Docker Desktop
  first). Otherwise record "not reproduced locally".
- **Cleanup:** `git worktree remove --force "$LOOP"` once the logs are kept.
