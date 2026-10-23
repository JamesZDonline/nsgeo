# Global Constraints for every M12 task (from the plan, verbatim)

## Global Constraints

Every task's requirements implicitly include this section.

- **Python floor 3.9.** Every module starts `from __future__ import annotations`. Annotate with
  `tuple`/`dict`/`list` and `X | Y`, never `typing.Tuple`/`Dict`/`Union`. `ruff` selects `UP` and
  rejects the old forms.
- **`ruff.toml`:** line length 100, target py39, lint select `["E", "F", "I", "UP", "B", "SIM"]`.
  `ruff check .` and `ruff format --check .` must both pass.
- **Core is numpy-only.** No Qt, no QGIS, no GDAL, no scipy anywhere under
  `packages/nsgeo-core/src/nsgeo/`. CRS transforms are the plugin's job.
- **The plugin does no signal processing.** `tests/pure/test_plugin_boundary.py` enforces the
  import rules. Importing from `nsgeo.slices`, `nsgeo.render`, `nsgeo.project`, `nsgeo.model`,
  `nsgeo.geometry` and `nsgeo.velocity` is unrestricted. Use `qgis.PyQt.*` for all Qt.
- **Every new `pyqtSignal` must have a `connect`** (`tests/pure/test_no_orphan_signals.py`).
  Declare a signal in the task that also connects it.
- **Commit trailer:** a `Co-Authored-By:` line naming the model that wrote the commit.
- **Push each commit** to `origin/nsgeo-m12` as it is made.
- **Every test that pins a numeric or structural claim must be shown to discriminate.** Build the
  plausible wrong implementation the test exists to catch and run the test against it. Record in
  the task report that the test FAILS on the wrong version and PASSES on the real code. Each task
  names the mutants it must be proven against. Set `PYTHONDONTWRITEBYTECODE=1` while doing this,
  because stale `.pyc` files fake survivors.
- **Real data first.** Tests marked as needing the real files must run, not skip. A skip there
  means the symlinks are missing, so stop and fix them.
- **Units.** Times are two-way nanoseconds. Lengths, cells and radii are metres in the frame's
  CRS, never degrees.

### Test commands (from the worktree root)

```bash
./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py
```

`-p no:xonsh` is required. A system xonsh pytest plugin aborts collection otherwise. Report both
test tiers every time. **Reproduce and record the baseline before Task 1**, because `main` has
moved since M11 (#7's fix).

### A green local QGIS suite does not imply a green CI `plugin-qgis` job

An exception raised in a slot that Qt invoked from C++ shows up differently in each environment:

- Locally, it prints to stderr and the test **passes**.
- In CI's `qgis/qgis:ltr` container, it aborts the whole job.

`tests/qgis/conftest.py`'s autouse `_no_swallowed_slot_exceptions` fails any test that leaks one.
**Never disable it or work around it.** A test that means to provoke an exception asserts on its
observable consequence instead. Every slot added here guards its body with
`except Exception` and reports, like every slot already in `slices_dock.py`.

### Established traps (all measured in this codebase)

1. **At most one line-preparation `QgsTask` may run at a time.** Two at once segfaulted M11
   reproducibly (`faulthandler` showed two workers inside `dewow.apply` and `read_header`).
   `SliceEngine.set_source` cancels and waits for its *own* previous task. Nothing yet stops
   *two engines* overlapping. Task 3 owns that, and its invariant test is the most important
   test in this plan.
2. **`addTask()` keeps no strong reference.** It needs a `_pending` set. Also:
   - `addTask()` returning 0 means the task never ran, so undo the bookkeeping;
   - `QgsTaskWrapper.finished()` swallows exceptions silently.

   `SliceEngine` already handles all of this. Compose it rather than re-implementing it.
3. **Never reuse a `LinePlan` across a frame or z-axis change.** `SliceEngine.set_resolution`
   drops plans, and `stream_slice` raises on a stale one.
4. **The shared stretch is measured over filled windows at the displayed thickness**, never over
   raw levels (`SliceEngine.shared_limit`). A limit taken over raw levels renders every slice about
   a third as bright and looks like dim data.
5. **Derive every readout from the window actually used**, `(k0, k1)`, never from the requested
   top and thickness.
6. **`QDialog.exec()` is forbidden.** Every dialog is modeless. The qgis-tier conftest forbids
   modals outright; use `answer_modal` or `drive_dialog` to opt in for one expected call.
7. **Spin boxes need a useful `singleStep`.** M11 shipped `QDoubleSpinBox`es that stepped by
   1.0 m. One arrow click set the cell size to 0.001 m and crashed QGIS (walkthrough W7).
8. **A `QComboBox` refill emits `currentTextChanged`.** Guard refills the way
   `SlicesDock._updating` does, or a refill reads as a user choice and re-prepares.


## Rulings taken before execution (from the plan, verbatim)

**Ruling 1: the site composes its own `SliceEngine`s; preparation is serialised by `SiteEngine`.**
`SiteEngine` owns one `SliceEngine` per included grid. These are separate from the dock's
*This grid* engine, which M11's code and tests construct and own. `SiteEngine` dispatches one
grid at a time. Before every dispatch it checks that none of its own engines, and none of the
`exclusive_with` peers, is running. If one is, it re-tries on a 50 ms `QTimer`. It never blocks.
The dock passes its *This grid* engine as that peer. Going back to *This grid* calls
`SiteEngine.cancel()`, which uses the new public `SliceEngine.cancel_preparation()`.
*Cost if wrong:* one grid's prepared lines can be held twice (tens of MB at real sizes). Sharing
one engine pool between scopes would avoid that, but would rewrite how M11's dock owns its engine.

**Ruling 2: the rotated-cell loss is fixed for the site by the lattice pitch.** This is the
re-examination spec §4.7 asks for. A backward nearest-neighbour gather loses cells only when a
frame is rotated against the lattice:

- **Axis-aligned frame, pixel = cell.** Each frame cell contains exactly one pixel centre,
  whatever the offset.
- **Rotated frame, pixel = cell / 2.** A square of side `c` at any angle contains a disc of
  diameter `c`, and any disc wider than `(c/2)·√2 ≈ 0.71c` contains a point of a `c/2` lattice.
  So no cell is lost.

`lattice_pixel(cell, azimuths)` therefore returns `cell` when every included frame's azimuth is a
multiple of 90°, and `cell / 2` otherwise. Task 1 proves both claims with tests.
*Cost:* a site with a rotated grid has four times the lattice pixels. The fill runs on grid-local
arrays, so it is unaffected. Only the gather, the preview write and the export grow.

**Ruling 3: seams.** The seam width is `SEAM_WIDTH_SPACINGS = 1.5` × the larger line spacing of
the pair. That guarantees at least one line on each side whenever lines start within 1.5 spacings
of the edge. A seam needs `MIN_SEAM_CELLS = 20` populated cells on **each** side. Seams are only
sought between frames in the same CRS. A grid with no same-CRS neighbour takes the background-level
gain (spec §4.6, isolated grids).

**Ruling 4: the site stretch is measured over at most `SITE_LIMIT_WINDOWS = 12` windows**,
evenly spread over the site axis and always including the first and last. Each window is fully
binned, filled, normalised and adjusted. For ten grids, measuring every window would cost seconds
per change, and a display percentile does not need every window. The window list is
`slices_plan.limit_windows`, so it is Qt-free and tested.

**Ruling 5: persistence.**
- `Site.slice_sources[grid_id]` is `{"preset": str, "lines": [keys] | null, "gain": float}`. Every
  key is optional. `lines: null` means "every line on the grid", so newly imported lines are
  picked up.
- `Site.site_view` is `{"grids": [ids], "transform": str, "normalisation": str}`.
- Both are saved only when non-empty and load tolerantly. A missing key is the default. An entry
  for an unknown grid is dropped on load. A wrong top-level type raises `ProjectError`, as `cubes`
  does.
- A source is remembered **only when the user chooses it**: a combo change, or accepting the line
  chooser. It is never remembered by the automatic first preparation, so opening a site never
  marks it dirty.
- The scope itself is not persisted. The dock always opens in *This grid*.

**Ruling 6: metadata key names** for the site GeoTIFF are fixed in Task 4, not left open.

**Ruling 7: coverage in site scope** is composed like values (the mean where grids overlap,
which only happens at a rotated corner). It is a display, and the export's companion is the same.

**Ruling 8: worktree.** Work in `.worktrees/nsgeo-m12`, on branch `nsgeo-m12`, created from
`docs/m12-site-design` after merging `origin/main` into it.
- It has its own `.venv` and `.venv-qgis`. Verify that `nsgeo` resolves to the worktree's own
  source.
- The ten real DZT files are symlinked into `packages/nsgeo-core/tests/data/local/` from the main
  checkout, as M11's worktree did.

