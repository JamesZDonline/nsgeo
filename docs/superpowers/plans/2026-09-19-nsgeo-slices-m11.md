# nsgeo time and depth slices, M11 — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put a slice in front of an archaeologist — choose the lines and the recipe, drag a
depth slider and watch the map redraw, see where there is no data, see the window drawn on the
radargram, and export a multi-band GeoTIFF anyone can open.

**Architecture:** Seven tasks over three layers, in the order they must be built. Core (`nsgeo.slices.display`)
gains the pure arithmetic a viewer needs and that M10 deliberately deferred for want of a caller:
window planning, the window's true time and depth labels, the shared display stretch, the frame's
world extent, and the north-up resample. A Qt-side engine (`slices_engine.py`, with its numeric
half in the Qt-free `slices_plan.py`) owns line preparation on a `QgsTask`, the `LinePlan` cache
and its invalidation, the residency choice and the per-tick slice. The UI — a `SlicesDock`
tabified with Processing, a line-choice dialog, a live raster layer, a band on the radargram and
a GeoTIFF exporter — consumes both and computes nothing.

**Tech Stack:** Python 3.9+, numpy (core, and the plugin's Qt-free modules), `qgis.PyQt` (never
`PyQt5`/`PyQt6` directly), QGIS 3.40+ API, GDAL 3.8 via `osgeo.gdal`, pytest.

**Spec:** `docs/superpowers/specs/2026-09-18-nsgeo-slices-design.md` — binding. §13 scopes this
milestone; §9 is the UX in detail; §9.4–§9.5 the layers and export. Read §6.6, §7.4, §8, §9.1–§9.5
before starting. The previous milestone's plan
(`docs/superpowers/plans/2026-09-18-nsgeo-slices-m10.md`) and decision record
(`docs/superpowers/sdd/2026-09-18-nsgeo-slices-m10/`) explain why the core looks the way it does.

---

## Global Constraints

Every task's requirements implicitly include this section.

- **Python floor 3.9.** Every module starts `from __future__ import annotations`. Annotate with
  `tuple`/`dict`/`list` and `X | Y`, never `typing.Tuple`/`Dict`/`Union` — `ruff` selects `UP`
  and will reject the old forms (M10 Ruling A).
- **`ruff.toml`:** line length 100, target py39, lint select `["E", "F", "I", "UP", "B", "SIM"]`.
  `ruff check .` and `ruff format --check .` must both pass.
- **Core is numpy-only.** No Qt, no QGIS, no scipy, no matplotlib anywhere under
  `packages/nsgeo-core/src/nsgeo/`.
- **The plugin does no signal processing.** `packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py`
  parses every plugin module's AST and fails on: any import of `PyQt5`/`PyQt6`/`PySide2`/`PySide6`/
  `matplotlib`/`scipy`; any import from `nsgeo.processing.<submodule>`; and any name imported from
  `nsgeo.processing` outside `{StepStack, Step, build_step, available_steps, get_step, Radargram,
  ParamSpec, REQUIRED, default_params, required_params, nyquist_mhz}`. Importing from
  `nsgeo.slices`, `nsgeo.render`, `nsgeo.project`, `nsgeo.model`, `nsgeo.geometry` and
  `nsgeo.velocity` is unrestricted. Use `qgis.PyQt.*` for all Qt.
- **Every new pyqtSignal must have a `connect`.** `tests/pure/test_no_orphan_signals.py` greps for
  it. A signal declared in one task and connected in a later one fails the suite in between, so
  declare a signal in the task that also connects it.
- **Commit trailer**, every commit:
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`
- **Push each commit** to `origin/nsgeo-m11` as it is made.
- **Every test that pins a numeric or structural claim must be shown to discriminate.** Build the
  plausible wrong implementation the test exists to catch, run the test against it, record in the
  task report that it FAILS there and PASSES against the real code. Each task below names the
  mutants it must be proven against; finding more is welcome. A test that only passes against
  correct code is not evidence — M10 shipped six wrong things that passed their own green tests.

### Test commands (from the worktree root)

```bash
./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py
```

`-p no:xonsh` is required: a system-site-packages xonsh pytest plugin uses the removed `path`
hookimpl argument and aborts collection otherwise.

**Baseline at the start of this plan:** 502 core+pure passed / 2 skipped (both deliberate schema
skips), 470 QGIS passed. Report both tiers every time; there are two boundary-test files
(`packages/nsgeo-core/tests/test_boundary.py`, 2 tests, and
`packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py`, 4) and reporting only one is a
misreport.

**The `slices_plan.py` entry in the mypy command above is new.** Task 2 adds it to
`.github/workflows/ci.yml` (the `lint` job's literal file list) at the same time as the module.

### A green local QGIS suite does not imply a green CI `plugin-qgis` job

An exception raised inside a slot Qt invoked from C++ cannot propagate back to the emitter. Under
local PyQt 5.15.10 it goes to `sys.excepthook`, prints to stderr, and the test reports **PASSED**;
in the `qgis/qgis:ltr` container the same exception reaches `qFatal()` and aborts the whole job,
taking every later test down unrun. That hid two broken tests for nine consecutive CI runs on this
repo. `tests/qgis/conftest.py`'s autouse `_no_swallowed_slot_exceptions` fixture snapshots
`sys.excepthook` and `sys.unraisablehook` and fails any test that grew them — **do not disable or
work around it**, and never add an opt-out. A test that means to provoke an exception in a slot
asserts on the observable consequence instead.

### Established traps in this codebase (all measured here, none theoretical)

1. **Never reuse a `LinePlan` across a frame or z-axis change.** Every Resolution-group control
   (dz, cell size, z range) invalidates *every* plan. `build_cube`/`stream_slice` now raise on a
   stale one, but only because M10 added the guard: before it, a 1.0 m-cell plan used against a
   0.5 m-cell frame binned into the wrong cells silently, with plausible coverage.
2. **The shared display stretch is a property of `(cube, thickness)`, not of the cube.**
   `UnipolarClip().limit(cube.mean)` measured 2.59 where the correct limit for the displayed
   10-level slice was 0.87. A window mean has far lower variance than the levels it averages, so a
   limit taken over raw levels renders every slice at about a third of its intended brightness —
   identically at every depth, so it reads as "dim data" rather than as a bug. Task 1 builds
   `shared_limit` precisely to stop this.
3. **Derive every depth/time readout from the `(k0, k1)` `ZAxis.level_range` returns**, never from
   the `(top_ns, thickness_ns)` you asked for. At either end of the axis the returned window is
   genuinely thinner than requested, and §6.6 requires the readout to show what was actually
   averaged.
4. **`QgsApplication.taskManager().addTask()` keeps no strong reference** to a
   `QgsTask.fromFunction()` task. Without your own reference it is garbage-collected silently,
   with `on_finished` never called. `loader.py` is the worked pattern: a `_pending` set that is
   not tied to which site the task was requested against. `addTask()` returning 0 means the task
   was never added and `on_finished` will never run — undo your bookkeeping in that branch.
   `QgsTaskWrapper.finished()` swallows any exception an `on_finished` callback raises, with no
   traceback anywhere, so guard its body with `except`, not merely `finally`.
5. **`QDialog.exec()` is forbidden in this plugin.** Its event loop terminates the instant the
   dialog is hidden from *any* cause. Every dialog here is modeless: `show()`, lifecycle on
   `finished`, a single tracking slot on the plugin so a second one is not opened on top of the
   first, and `reject()` (never `close()` — `closeEvent` only calls `reject()` on a *visible*
   dialog) in `unload()`. `plugin.py:open_grid_dialog` / `open_import_dialog` are the pattern. The
   qgis-tier conftest forbids `QDialog.exec`, `QMenu.exec`, `QMessageBox.question/warning/
   information`, `QFileDialog.get*`, `QInputDialog.getText` and `QTest.mouseDClick` outright;
   opt in for one expected call with the `answer_modal` or `drive_dialog` fixture.
6. **CRS units are metres** for every frame here; cell sizes, radii and extents are metres and
   must never be mixed with degrees. A `Grid` carries its own `crs`.
7. **Do not re-plan `mypy` coverage by guesswork.** CI's list is literal; the local command above
   is CI's, extended by exactly the one new file.

---

## File Structure

**Created**

| File | Responsibility |
|---|---|
| `packages/nsgeo-core/src/nsgeo/slices/display.py` | Pure arithmetic a slice viewer and exporter need: window plans, true window labels, the shared stretch, the north-up resample |
| `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py` | Qt-free plugin arithmetic: source/resolution value objects, the transform registry query, the preset conflict rule, memory estimation and the residency choice, status text |
| `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py` | `SliceEngine`: prepares lines on a `QgsTask`, owns the `LinePlan` cache and its invalidation, serves one slice per tick, builds a cube on demand |
| `packages/nsgeo-qgis/nsgeo_qgis/slice_layer.py` | The live slice raster: GDAL write, `QgsRasterLayer` lifecycle, the pseudocolor renderer built from a core LUT |
| `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py` | The writer interface and its GeoTIFF implementation: multi-band export, band descriptions, temporal properties, the `.npz` and the `Site.cubes` record |
| `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` | The Slices dock: Source, Position, Resolution and Display groups; owns no numerics |
| `packages/nsgeo-qgis/nsgeo_qgis/ui/line_choice_dialog.py` | The contributing-lines table (§9.1's one dialog) |

**Modified**

| File | Change |
|---|---|
| `packages/nsgeo-core/src/nsgeo/slices/frame.py` | `slice_extent(frame)` — M10 Ruling B's deferred helper, now with a caller |
| `packages/nsgeo-core/src/nsgeo/slices/fill.py` | Smooth-size FFT padding and a cached kernel spectrum |
| `packages/nsgeo-core/src/nsgeo/slices/__init__.py` | Re-export the new public names |
| `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py` | Paint the active slice's time window as a band |
| `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` | Relay the band to the view |
| `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` | Construct, tabify, wire and tear down the dock, engine and layer |
| `packages/nsgeo-core/src/nsgeo/model/survey.py` | The `Site.cubes` docstring: the full record shape (Task 7) |
| `.github/workflows/ci.yml` | Add `slices_plan.py` to the mypy file list |

---

## Rulings taken before execution

**Ruling 1 — the residency UI is scoped to the two tiers that exist; the on-disk spike does not
run in M11.** §7.4 describes three tiers and flags the third (memory-mapped on-disk lines) as
unmeasured, with a spike owed before anything commits to it. M10 implemented two — resident and
streaming — and never needed the third, so the spike never ran. Scoping to two rather than running
it now, because: §9.2 already settles the user-facing question ("Residency is not a user-facing
choice" — the dock *reports* what is held, and the single override is a settings toggle worded
*"keep the whole volume in memory for faster dragging (uses N MB)"*), so the third tier adds no
control the spec asks for; memory-mapping is core work, and §13's M11 line lists six UI
deliverables and no core residency work; and a spike's product is a number, which would consume
one of six tasks without moving the milestone. **Do not ship a control for a mode that does not
exist**: the settings override is binary (automatic, or always resident), and the status line
reports only what is actually held. The spec's §7.4 keeps its third row as designed-for-not-built.

**Ruling 2 — the amplitude transform is appended by the engine and is never part of a preset.**
M10's `StepStack.output_unipolar` reports the last *enabled* step, so a gain after an amplitude
transform reports `False` though AGC preserves unipolarity — and putting unipolar data on a
bipolar table is the exact failure §8 exists to prevent. Rather than add a per-step
`preserves_unipolar` (a core protocol change in a UI milestone), M11 makes the ordering
structurally impossible: the engine builds `StepStack.from_dicts(preset_steps)` and *appends* the
chosen transform, so the transform is always last and `output_unipolar` is exact. The Source group
therefore **refuses a preset that itself contains an `amp_*` step**, naming the step and telling
the user to remove it from the preset or choose it in the Transform combo. `transform = ""` (none)
stays legitimate — §6.2 and GPRSLICE's `xfrm_method=NONE` both allow it — and yields bipolar
slices on a bipolar table, which is consistent. Cost if wrong: a user with an amplitude transform
baked into a saved preset must lift it out once; the message says so.

**Ruling 3 — the live raster and the export use different GDAL creation options.** Measured here,
GDAL 3.8.4, float32: `COMPRESS=DEFLATE, PREDICTOR=3` costs **8.8 ms** to write a 300×300 band and
**25.2 ms** at 600×600, against **1.0 ms** and **1.3 ms** uncompressed. §9.5's option set is
argued for the *export*, where file size and one-band read cost dominate, and it stands there
unchanged. The live layer rewrites a scratch file on every tick and is latency-bound, so it writes
uncompressed. Both share `INTERLEAVE=BAND`, `TILED=NO`, `BIGTIFF=IF_SAFER`.

**Ruling 4 — `to_north_up` lives in core, not the plugin.** §9.4 puts the north-up resample under
"The plugin", but it is pure numpy geometry over a `CubeFrame`, and frame geometry is core's. Core
keeps the arithmetic and mypy/pure-test coverage; the plugin keeps only GDAL. Cost if wrong: one
function moves packages, with its tests.

**Ruling 5 — work in a manually created worktree** (`.worktrees/nsgeo-m11`, branch `nsgeo-m11`
from `main` at `ee0fdea`), following M10's Ruling D and this repo's `.worktrees/` convention rather
than the harness's `.claude/worktrees/`. It has its own `.venv` and `.venv-qgis` — the main
checkout's `.venv` has `nsgeo` installed against the *main* checkout's source and would silently
test the wrong tree — and the ten real DZT files are symlinked into
`packages/nsgeo-core/tests/data/local/`, without which every real-data test skips and hands back a
green suite that validated nothing. **Already done**: both venvs built, `nsgeo` verified to resolve
to the worktree's own source, baseline 502/2 reproduced.

---

**Confirmed in review, 2026-09-20.** The user reviewed this plan before execution and confirmed
Ruling 1 (scope to the two residency tiers that exist) and the spec-following preparation trigger
(every grid/preset/transform change re-prepares, no debounce). They also asked for one addition:
*"a way to save/load the settings used for creating a cube/slice set to the nsgeo json so it
could easily be reproduced later"* — which the five-key record could not do. That is **Task 7**,
and it is why Task 6's record grew `lines`, `z` and `view`. The plan therefore runs to seven
tasks rather than the standing 3–6 preference; see Task 7's own note for why growing Task 6
instead would have been worse.

## Measured figures this plan relies on

All taken in this worktree, on this machine, before writing the plan. Reproduce rather than trust
if a decision turns on one.

| Quantity | Measured |
|---|---|
| `fill`, 600×600, r=10, as M10 ships it | 44.8 ms |
| `fill`, 600×600, r=10, smooth-padded + cached kernel | 31.9 ms (1.4×) |
| `fill`, 1021×1019, r=10, as shipped | 361.4 ms |
| `fill`, 1021×1019, r=10, padded + cached | 114.0 ms (3.2×) |
| GeoTIFF write, 300×300 float32, uncompressed | 1.0 ms |
| GeoTIFF write, 600×600 float32, uncompressed | 1.3 ms |
| GeoTIFF write, 300×300, DEFLATE+PREDICTOR=3 | 8.8 ms |
| `QgsRasterDataProvider.reloadData()` after an in-place rewrite | ~1.5 ms, and pixel values genuinely refresh |
| Shape change (300×300 → 600×600) across `reloadData()` | layer `width()`/`height()` follow; no need to recreate the layer |
| Read one band of a 19-band `INTERLEAVE=BAND` file | 0.141 ms |
| Band descriptions | round-trip through GDAL and appear in `QgsRasterLayer.bandName(n)` |
| `Qgis.RasterTemporalMode.FixedRangePerBand` and `setFixedRangePerBand` | present in QGIS 3.44.7 |
| NaN nodata under a pseudocolor renderer | `renderer.block(...).color(row, col)` has **alpha 0**; `block.isNoData()` is **False** (the rendered block is ARGB, so alpha carries nodata — asserting `isNoData` is a false pass) |

Even padded and cached, the fill is 32 ms at 600×600 — twice a 16 ms frame budget — so the radius
slider still needs debouncing. Both halves of that are required; neither alone is enough.

---

### Task 1: Core — the arithmetic a viewer and an exporter need

Everything M10 deferred for want of a caller, plus the fill speedup its own review asked for.
Pure numpy; no Qt, no GDAL, no QGIS.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/slices/display.py`
- Modify: `packages/nsgeo-core/src/nsgeo/slices/frame.py` (append `slice_extent`)
- Modify: `packages/nsgeo-core/src/nsgeo/slices/fill.py` (padding + kernel cache)
- Modify: `packages/nsgeo-core/src/nsgeo/slices/__init__.py` (re-exports)
- Test: `packages/nsgeo-core/tests/test_slices_display.py` (new)
- Test: `packages/nsgeo-core/tests/test_slices_fill.py` (append)
- Test: `packages/nsgeo-core/tests/test_slices_frame.py` (append)
- Test: `packages/nsgeo-core/tests/test_real_files.py` (append one test)

**Interfaces:**

- Consumes: `CubeFrame` (`origin`, `azimuth`, `cell`, `nx`, `ny`, `crs`, `axes()`, `cell_index()`,
  `n_cells`), `ZAxis` (`t0_ns`, `dz_ns`, `nz`, `times_ns()`, `level_range()`), `SliceCube`
  (`frame`, `z`, `mean`, `count`, `slice_levels(k0, k1) -> (ny, nx)`, `coverage()`),
  `VelocityModel.depth_at(times_ns)`, `nsgeo.render.Normalizer` (a Protocol with
  `limit(data) -> float`), `nsgeo.slices.fill.disc_kernel`.
- Produces, all importable from `nsgeo.slices`:
  - `SliceWindow(k0: int, k1: int)` — frozen; `.n_levels -> int`; rejects `k1 <= k0` or `k0 < 0`.
  - `plan_windows(z: ZAxis, thickness_levels: int, step_levels: int) -> tuple[SliceWindow, ...]`
  - `window_times_ns(z: ZAxis, window: SliceWindow) -> tuple[float, float]`
  - `window_depths_m(z: ZAxis, window: SliceWindow, velocity: VelocityModel) -> tuple[float, float]`
  - `window_label(z: ZAxis, window: SliceWindow, velocity: VelocityModel | None = None) -> str`
  - `limit_over_slices(slices: Iterable[np.ndarray], clip: Normalizer) -> float`
  - `shared_limit(cube: SliceCube, thickness_levels: int, clip: Normalizer) -> float`
  - `to_north_up(values: np.ndarray, frame: CubeFrame) -> tuple[np.ndarray, tuple[float, float, float, float, float, float]]`
  - `slice_extent(frame: CubeFrame) -> tuple[float, float, float, float]` (in `frame.py`)
  - `clear_kernel_cache() -> None` (in `fill.py`)

---

- [ ] **Step 1: Write the failing tests for `slice_extent`**

Append to `packages/nsgeo-core/tests/test_slices_frame.py`:

```python
def test_slice_extent_of_an_axis_aligned_frame_is_its_own_box():
    frame = CubeFrame(origin=(100.0, 200.0), azimuth=0.0, cell=0.5, nx=40, ny=20, crs="EPSG:32633")
    assert slice_extent(frame) == pytest.approx((100.0, 200.0, 120.0, 210.0))


def test_slice_extent_covers_all_four_corners_of_a_rotated_frame():
    """The mutant this exists to catch takes only the origin and the far
    corner, which is correct at azimuth 0 and wrong at every other angle:
    a rotated rectangle's bounding box is decided by the two corners the
    diagonal misses."""
    frame = CubeFrame(origin=(0.0, 0.0), azimuth=30.0, cell=1.0, nx=10, ny=4, crs="EPSG:32633")
    xmin, ymin, xmax, ymax = slice_extent(frame)
    x_hat, y_hat = frame.axes()
    corners = np.array(
        [
            [0.0, 0.0],
            10.0 * x_hat,
            4.0 * y_hat,
            10.0 * x_hat + 4.0 * y_hat,
        ]
    )
    assert xmin == pytest.approx(corners[:, 0].min())
    assert ymin == pytest.approx(corners[:, 1].min())
    assert xmax == pytest.approx(corners[:, 0].max())
    assert ymax == pytest.approx(corners[:, 1].max())
    # The two-corner mutant would miss by this much, so the test is not vacuous.
    two_corner_ymin = min(0.0, float((10.0 * x_hat + 4.0 * y_hat)[1]))
    assert abs(two_corner_ymin - ymin) > 1.0


def test_slice_extent_is_wider_than_the_frame_when_rotated():
    frame = CubeFrame(origin=(0.0, 0.0), azimuth=45.0, cell=1.0, nx=10, ny=10, crs="EPSG:32633")
    xmin, ymin, xmax, ymax = slice_extent(frame)
    assert xmax - xmin == pytest.approx(math.hypot(10.0, 10.0), rel=1e-9)
    assert ymax - ymin == pytest.approx(math.hypot(10.0, 10.0), rel=1e-9)
```

Add `import math` and `from nsgeo.slices.frame import slice_extent` to that file's imports (it
already imports `numpy as np`, `pytest`, and `CubeFrame`).

- [ ] **Step 2: Run them and watch them fail**

Run: `./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_frame.py -q`
Expected: 3 errors — `ImportError: cannot import name 'slice_extent'`.

- [ ] **Step 3: Implement `slice_extent`**

Append to `packages/nsgeo-core/src/nsgeo/slices/frame.py`, after the `ZAxis` class:

```python
def slice_extent(frame: CubeFrame) -> tuple[float, float, float, float]:
    """The axis-aligned world bounding box of `frame`, as (xmin, ymin, xmax, ymax).

    All four corners, never two. A rotated rectangle's bounding box is set
    by the corners the origin-to-far-corner diagonal does not touch, so the
    cheap two-corner form is right only at azimuth 0 -- and silently wrong,
    by up to the frame's own width, at every other angle.

    This is what a north-up export resamples into: the box is in world
    units and is generally larger than `nx * cell` by `ny * cell`, because
    a rotated frame does not fill its own bounding box.
    """
    x_hat, y_hat = frame.axes()
    origin = np.asarray(frame.origin, dtype=float)
    span_x = frame.nx * frame.cell * x_hat
    span_y = frame.ny * frame.cell * y_hat
    corners = np.array([origin, origin + span_x, origin + span_y, origin + span_x + span_y])
    return (
        float(corners[:, 0].min()),
        float(corners[:, 1].min()),
        float(corners[:, 0].max()),
        float(corners[:, 1].max()),
    )
```

- [ ] **Step 4: Run them and watch them pass**

Run: `./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_frame.py -q`
Expected: PASS, and the file's pre-existing tests still pass.

- [ ] **Step 5: Prove the test discriminates**

Temporarily replace the `corners` array with the two-corner form
(`np.array([origin, origin + span_x + span_y])`), re-run, and confirm
`test_slice_extent_covers_all_four_corners_of_a_rotated_frame` and
`test_slice_extent_is_wider_than_the_frame_when_rotated` FAIL while the axis-aligned one still
passes. Revert. Record both numbers in the task report.

- [ ] **Step 6: Commit**

```bash
git add packages/nsgeo-core/src/nsgeo/slices/frame.py packages/nsgeo-core/tests/test_slices_frame.py
git commit -m "feat(slices): slice_extent, a frame's world bounding box

M10 Ruling B dropped it as dead code, to return with its caller. The
north-up GeoTIFF resample in display.py is that caller.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 7: Write the failing tests for the window plan and its labels**

Create `packages/nsgeo-core/tests/test_slices_display.py`:

```python
"""Windows, labels, the shared stretch, and the north-up resample."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.render import PercentileClip, UnipolarClip
from nsgeo.slices.cube import Provenance, SliceCube
from nsgeo.slices.display import (
    SliceWindow,
    limit_over_slices,
    plan_windows,
    shared_limit,
    to_north_up,
    window_depths_m,
    window_label,
    window_times_ns,
)
from nsgeo.slices.frame import CubeFrame, ZAxis
from nsgeo.velocity import VelocityModel


def _axis(nz: int = 100, dz: float = 0.5, t0: float = 0.0) -> ZAxis:
    return ZAxis(t0_ns=t0, dz_ns=dz, nz=nz)


def test_a_window_rejects_an_empty_or_reversed_range():
    with pytest.raises(ValueError):
        SliceWindow(5, 5)
    with pytest.raises(ValueError):
        SliceWindow(5, 4)
    with pytest.raises(ValueError):
        SliceWindow(-1, 3)


def test_abutting_windows_tile_the_axis_without_gaps_or_overlap():
    windows = plan_windows(_axis(nz=100), thickness_levels=10, step_levels=10)
    assert len(windows) == 10
    assert windows[0] == SliceWindow(0, 10)
    assert windows[-1] == SliceWindow(90, 100)
    for a, b in zip(windows, windows[1:]):
        assert b.k0 == a.k1


def test_overlapping_windows_match_the_specs_band_count_formula():
    """Spec 9.4: n_bands = (z_range - thickness) / step + 1. In levels,
    that is (nz - thickness) // step + 1 -- the count a GeoTIFF export
    turns into bands, so an off-by-one here is an off-by-one file."""
    nz, thickness, step = 100, 10, 5
    windows = plan_windows(_axis(nz=nz), thickness, step)
    assert len(windows) == (nz - thickness) // step + 1 == 19
    assert windows[1].k0 == 5  # 50% overlap: the second window starts mid-first
    assert windows[1].k1 == 15
    assert windows[-1].k1 == nz  # the last window still ends on the axis


def test_a_window_thicker_than_the_axis_becomes_the_whole_axis():
    assert plan_windows(_axis(nz=8), thickness_levels=20, step_levels=1) == (SliceWindow(0, 8),)


def test_plan_windows_rejects_a_non_positive_thickness_or_step():
    with pytest.raises(ValueError):
        plan_windows(_axis(), 0, 5)
    with pytest.raises(ValueError):
        plan_windows(_axis(), 5, 0)


def test_a_windows_time_span_is_n_minus_one_sample_intervals():
    """Levels are POINT samples -- plan_line resamples at each level's
    exact time by linear interpolation, it does not integrate a bin -- so
    n levels span (n - 1) * dz, not n * dz. The plausible wrong version
    (k1 * dz, i.e. n * dz) is off by one interval at every thickness, and
    at thickness 1 it reports a 0.5 ns window where the truth is a single
    sample."""
    z = _axis(nz=100, dz=0.5, t0=2.0)
    assert window_times_ns(z, SliceWindow(10, 20)) == pytest.approx((7.0, 11.5))
    assert window_times_ns(z, SliceWindow(10, 11)) == pytest.approx((7.0, 7.0))


def test_the_label_reports_what_level_range_actually_returned_not_what_was_asked_for():
    """Spec 6.6 and ZAxis.level_range's own docstring: at either end of the
    axis the returned window is genuinely thinner than requested. A label
    derived from (top_ns, thickness_ns) instead of from (k0, k1) claims a
    window that was never averaged."""
    z = _axis(nz=100, dz=0.5, t0=0.0)  # axis covers 0.0 .. 49.5 ns
    k0, k1 = z.level_range(top_ns=48.0, thickness_ns=8.0)  # asks for 8 ns, cannot have it
    assert (k0, k1) == (96, 100)
    lo, hi = window_times_ns(z, SliceWindow(k0, k1))
    assert (lo, hi) == pytest.approx((48.0, 49.5))
    assert hi - lo < 8.0  # the point: what was asked for is not what happened
    assert "48.0" in window_label(z, SliceWindow(k0, k1))
    assert "49.5" in window_label(z, SliceWindow(k0, k1))
    assert "56.0" not in window_label(z, SliceWindow(k0, k1))  # 48 + 8, the wrong answer


def test_the_label_carries_both_units_when_a_velocity_is_given():
    z = _axis(nz=100, dz=0.5, t0=0.0)
    v = VelocityModel.constant(0.08)  # m/ns; depth = v/2 * t
    lo_m, hi_m = window_depths_m(z, SliceWindow(30, 40), v)
    assert (lo_m, hi_m) == pytest.approx((0.6, 0.78))
    label = window_label(z, SliceWindow(30, 40), v)
    assert "ns" in label and "m" in label
    assert "15.0" in label and "19.5" in label  # the ns range
    # Without a velocity the depth half is simply absent, never invented.
    assert "m" not in window_label(z, SliceWindow(30, 40)).replace("ns", "")
```

- [ ] **Step 8: Run them and watch them fail**

Run: `./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_display.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'nsgeo.slices.display'`.

- [ ] **Step 9: Implement the window half of `display.py`**

Create `packages/nsgeo-core/src/nsgeo/slices/display.py`:

```python
"""What a slice viewer and a slice exporter need, and nothing a binner does.

Three jobs, each deferred out of M10 because it had no caller there and
this plan gives it one:

* planning the set of windows a stack of slices is cut at, which is the
  one place spec 6.6's independent `(thickness, step)` pair becomes a
  finite list -- the dock's navigation and the exporter's bands are the
  same plan read at different steps;
* saying, in both units, what a window ACTUALLY averaged, derived from
  `(k0, k1)` and never from the `(top_ns, thickness_ns)` that produced
  them;
* the display stretch shared across a cube, and the north-up resample an
  export writes through.

Pure numpy, like the rest of the core.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from nsgeo.render import Normalizer
from nsgeo.slices.cube import SliceCube
from nsgeo.slices.frame import CubeFrame, ZAxis, slice_extent
from nsgeo.velocity import VelocityModel


@dataclass(frozen=True)
class SliceWindow:
    """A half-open level range `[k0, k1)`, the unit a slice is cut from.

    Levels, not nanoseconds: the conversion belongs to one `ZAxis`, and
    carrying times here would let a window outlive the axis that gave it
    meaning -- which is precisely the stale-plan hazard the binner's own
    guard exists for.
    """

    k0: int
    k1: int

    def __post_init__(self) -> None:
        if self.k0 < 0:
            raise ValueError(f"k0 must be >= 0, got {self.k0}")
        if self.k1 <= self.k0:
            raise ValueError(f"a window must hold at least one level, got {self.k0}..{self.k1}")

    @property
    def n_levels(self) -> int:
        return self.k1 - self.k0


def plan_windows(z: ZAxis, thickness_levels: int, step_levels: int) -> tuple[SliceWindow, ...]:
    """Every window of `thickness_levels`, starting every `step_levels`.

    Spec 6.6: thickness and step are independent and nothing assumes
    slices tile. `step == thickness` gives abutting windows; `step <
    thickness` gives the overlapping stack that is the standard practice
    and the default. The count is spec 9.4's band formula exactly --
    `(nz - thickness) // step + 1` -- so a GeoTIFF's band count and the
    dock's slice count are the same number by construction rather than by
    two agreeing implementations.

    Only whole windows: a trailing partial window would be thinner than
    every other band in the same file, and a reader comparing bands has no
    way to see that from the pixels.
    """
    if thickness_levels < 1:
        raise ValueError(f"thickness_levels must be >= 1, got {thickness_levels}")
    if step_levels < 1:
        raise ValueError(f"step_levels must be >= 1, got {step_levels}")
    if thickness_levels >= z.nz:
        return (SliceWindow(0, z.nz),)
    tops = range(0, z.nz - thickness_levels + 1, step_levels)
    return tuple(SliceWindow(k, k + thickness_levels) for k in tops)


def window_times_ns(z: ZAxis, window: SliceWindow) -> tuple[float, float]:
    """(first, last) two-way time of the levels the window averages.

    `(n_levels - 1) * dz` wide, not `n_levels * dz`: a level is a point
    sample, not a bin. `plan_line` resamples each level at its exact time
    by linear interpolation between the two nearest recorded samples, so
    averaging n of them averages n points spanning n-1 intervals. The
    off-by-one version overstates every window by one sample interval and,
    at thickness 1, claims a range where there is a single sample.
    """
    if window.k1 > z.nz:
        raise ValueError(f"window {window.k0}..{window.k1} exceeds the axis ({z.nz} levels)")
    return (z.t0_ns + window.k0 * z.dz_ns, z.t0_ns + (window.k1 - 1) * z.dz_ns)


def window_depths_m(z: ZAxis, window: SliceWindow, velocity: VelocityModel) -> tuple[float, float]:
    """The same window in metres, through the velocity model."""
    lo, hi = window_times_ns(z, window)
    depths = velocity.depth_at(np.array([lo, hi], dtype=float))
    return (float(depths[0]), float(depths[1]))


def window_label(z: ZAxis, window: SliceWindow, velocity: VelocityModel | None = None) -> str:
    """`12.0-16.0 ns / 0.60-0.80 m`, or the ns half alone with no velocity.

    Always the window's full range, never its centre: spec 6.6's reason is
    that with overlapping slices the extent of what is being averaged is
    the thing a reader would otherwise mistake for vertical resolution.
    Derived from `window`, which is what `ZAxis.level_range` returned --
    a label rebuilt from the requested top and thickness would claim a
    window the axis refused to give.
    """
    lo, hi = window_times_ns(z, window)
    text = f"{lo:.1f}-{hi:.1f} ns"
    if velocity is not None:
        lo_m, hi_m = window_depths_m(z, window, velocity)
        text += f" / {lo_m:.2f}-{hi_m:.2f} m"
    return text
```

- [ ] **Step 10: Run the window tests and watch them pass**

Run: `./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_display.py -q`
Expected: 8 passed.

- [ ] **Step 11: Prove the window tests discriminate**

Two mutants, each applied alone, re-run, then reverted:

1. In `window_times_ns`, `(window.k1 - 1)` → `window.k1`. Expect
   `test_a_windows_time_span_is_n_minus_one_sample_intervals` and
   `test_the_label_reports_what_level_range_actually_returned_not_what_was_asked_for` to FAIL.
2. In `plan_windows`, `range(0, z.nz - thickness_levels + 1, step_levels)` →
   `range(0, z.nz, step_levels)`. Expect
   `test_overlapping_windows_match_the_specs_band_count_formula` to FAIL (20 windows where 19
   are right).
   (Amended during execution: this plan originally also predicted
   `test_abutting_windows_tile_the_axis_without_gaps_or_overlap` would fail here. It does not,
   and cannot: with `thickness == step` both `range` forms floor to the same last multiple --
   `range(0, 91, 10)` and `range(0, 100, 10)` are both `0..90` -- so that test cannot
   discriminate this mutant. The band-count test is the one that does.)

Record the observed failure counts and messages in the task report.

- [ ] **Step 12: Commit**

```bash
git add packages/nsgeo-core/src/nsgeo/slices/display.py packages/nsgeo-core/tests/test_slices_display.py
git commit -m "feat(slices): window plans and window labels

(thickness, step) becomes a finite list in one place, so the dock's slice
count and a GeoTIFF's band count are the same number by construction. The
label is derived from (k0, k1), never from the requested top and
thickness -- spec 6.6.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 13: Write the failing tests for the shared stretch**

Append to `packages/nsgeo-core/tests/test_slices_display.py`:

```python
def _cube_with_varying_levels(seed: int = 0) -> SliceCube:
    """A cube whose LEVELS have much more spread than their window means.

    That gap is the whole subject: averaging 10 levels pulls the extremes
    in hard, so a limit measured on raw levels is far too large for the
    slices actually displayed. Built deliberately rather than sampled from
    real data so the effect is unambiguous.
    """
    rng = np.random.default_rng(seed)
    frame = CubeFrame(origin=(0.0, 0.0), azimuth=0.0, cell=1.0, nx=20, ny=20, crs="EPSG:32633")
    z = ZAxis(t0_ns=0.0, dz_ns=0.5, nz=40)
    count = np.ones(frame.n_cells, dtype=np.int32)
    mean = np.abs(rng.standard_normal((z.nz, frame.n_cells))).astype(np.float32)
    prov = Provenance(
        line_keys=("a",),
        preset_name="p",
        steps=(),
        transform="amp_abs",
        velocity=None,
        built_utc="2026-09-19T00:00:00Z",
        core_version="0.1.0.dev0",
    )
    return SliceCube(frame=frame, z=z, mean=mean, count=count, provenance=prov)


def test_the_shared_limit_is_measured_over_displayed_slices_not_raw_levels():
    """The M10 final review's Important 3, now a test. A window mean has
    far lower variance than the levels it averages, so UnipolarClip().
    limit(cube.mean) is systematically too high -- and because the bias is
    uniform across depth, every slice renders dim IDENTICALLY at every
    depth, which reads as 'the data is dim' rather than as a bug. That is
    exactly why it needs a test rather than an eye."""
    cube = _cube_with_varying_levels()
    clip = UnipolarClip()
    over_levels = clip.limit(cube.mean)
    over_slices = shared_limit(cube, thickness_levels=10, clip=clip)
    assert over_slices < over_levels
    assert over_slices / over_levels < 0.8  # measured ~0.55 on this fixture
    # And it really is the limit of what gets shown: every displayed slice
    # sits at or below it apart from the percentile's own tail.
    windows = plan_windows(cube.z, 10, 10)
    shown = np.concatenate([cube.slice_levels(w.k0, w.k1).ravel() for w in windows])
    assert over_slices == pytest.approx(float(np.percentile(shown, clip.percentile)), rel=1e-6)


def test_the_shared_limit_covers_every_level_exactly_once():
    """Abutting windows, so no depth is weighted twice in the percentile.
    A step-1 implementation would weight the middle of the axis ~10x more
    than its ends and shift the limit."""
    cube = _cube_with_varying_levels()
    windows = plan_windows(cube.z, 10, 10)
    assert sum(w.n_levels for w in windows) == cube.z.nz
    assert [w.k0 for w in windows] == [0, 10, 20, 30]


def test_limit_over_slices_ignores_nodata_and_survives_an_all_nodata_slice():
    clip = PercentileClip(percentile=100.0)
    a = np.array([[1.0, np.nan], [np.nan, 3.0]])
    b = np.full((2, 2), np.nan)
    assert limit_over_slices([a, b], clip) == pytest.approx(3.0)
    assert limit_over_slices([b], clip) == 1.0  # the documented empty fallback, never 0 or NaN


def test_limit_over_slices_refuses_an_empty_sequence():
    with pytest.raises(ValueError):
        limit_over_slices([], PercentileClip())
```

- [ ] **Step 14: Run them and watch them fail**

Run: `./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_display.py -q -k "limit or shared"`
Expected: FAIL — `ImportError` for `limit_over_slices` / `shared_limit`.

- [ ] **Step 15: Implement the stretch half**

Append to `display.py`:

```python
def limit_over_slices(slices: Iterable[np.ndarray], clip: Normalizer) -> float:
    """`clip`'s limit measured over every finite value in `slices`.

    Nodata is dropped HERE rather than left to the normaliser, because
    `PercentileClip` and `UnipolarClip` both subsample with a plain stride
    BEFORE filtering non-finite values. On a slice that is ~80% nodata --
    the ordinary case at 0.5 m line spacing and 0.10 m cells, spec 6.4 --
    that would spend four fifths of the sampling budget on NaN and measure
    the percentile from what little survived.
    """
    finite: list[np.ndarray] = []
    for item in slices:
        flat = np.asarray(item, dtype=float).ravel()
        finite.append(flat[np.isfinite(flat)])
    if not finite:
        raise ValueError("limit_over_slices needs at least one slice")
    if all(part.size == 0 for part in finite):
        return clip.limit(np.array([], dtype=float))
    return clip.limit(np.concatenate(finite))


def shared_limit(cube: SliceCube, thickness_levels: int, clip: Normalizer) -> float:
    """One display limit for the whole cube, at the thickness being shown.

    Spec 8: shared across the cube by default so depths stay comparable.
    The thickness is an argument and not a detail, because the stretch is
    a property of `(cube, thickness)` and NOT of the cube: a window mean
    has far lower variance than the levels it averages, so measuring over
    `cube.mean` gives a limit that is systematically too high. On one
    realistic cube `UnipolarClip().limit(cube.mean)` returned 2.59 where
    the correct limit for the displayed 10-level slice was 0.87 -- every
    slice then renders at about a third of its intended brightness,
    identically at every depth, so it reads as dim data rather than as a
    wrong limit. M10 recorded this on `UnipolarClip` and shipped no
    helper, for want of a caller; this is the helper, and the caller is
    the Slices dock.

    Windows abut (`step == thickness`), so every level contributes exactly
    once and no depth is weighted more heavily than another.
    """
    windows = plan_windows(cube.z, thickness_levels, thickness_levels)
    return limit_over_slices((cube.slice_levels(w.k0, w.k1) for w in windows), clip)
```

- [ ] **Step 16: Run and watch them pass**

Run: `./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_display.py -q`
Expected: 12 passed.

- [ ] **Step 17: Prove the stretch tests discriminate**

Mutate `shared_limit` to `return clip.limit(cube.mean)` — the exact wrong implementation M10's
review measured. Confirm `test_the_shared_limit_is_measured_over_displayed_slices_not_raw_levels`
FAILS. Then mutate `plan_windows(cube.z, thickness_levels, thickness_levels)` to
`plan_windows(cube.z, thickness_levels, 1)` and confirm
`test_the_shared_limit_covers_every_level_exactly_once` FAILS. Revert both; record the measured
ratio `over_slices / over_levels` in the task report.

(Amended during execution: this plan originally also predicted
`test_the_shared_limit_covers_every_level_exactly_once` would fail against the second mutant. It
cannot — that test never calls `shared_limit`; it calls `plan_windows(cube.z, 10, 10)` directly
with literal arguments, so a mutation inside `shared_limit`'s own body is invisible to it. The
mutant *is* caught, by the percentile cross-check inside
`test_the_shared_limit_is_measured_over_displayed_slices_not_raw_levels`: the step-1 windows
over-weight the axis's middle and shift the measured percentile away from the abutting-window
value the test independently recomputes.)

- [ ] **Step 18: Commit**

```bash
git add packages/nsgeo-core/src/nsgeo/slices/display.py packages/nsgeo-core/tests/test_slices_display.py
git commit -m "feat(slices): shared_limit, the stretch for a cube at a thickness

M10's Important 3 as code: a limit taken over raw levels renders every
slice at ~1/3 brightness, identically at every depth, so it reads as dim
data rather than as a bug.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 19: Write the failing tests for the north-up resample**

Append to `packages/nsgeo-core/tests/test_slices_display.py`:

```python
def _ramp_frame(azimuth: float = 0.0) -> tuple[CubeFrame, np.ndarray]:
    """A frame and a values array whose rows are all different, so a
    vertical flip is visible. `values[0]` is frame-local y index 0."""
    frame = CubeFrame(origin=(0.0, 0.0), azimuth=azimuth, cell=1.0, nx=4, ny=3, crs="EPSG:32633")
    values = np.array([[1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0], [9.0, 10.0, 11.0, 12.0]])
    return frame, values


def test_north_up_puts_frame_row_zero_at_the_BOTTOM_of_the_raster():
    """The single most likely defect in this function, and invisible in
    any symmetric test fixture. A raster's row 0 is its NORTHERN edge --
    the geotransform's y pixel size is negative -- while a CubeFrame's
    y index 0 is its SOUTHERN edge, because frame-local +Y points north
    at azimuth 0. Getting this wrong mirrors every exported slice
    vertically: the anomalies are all still there, in the wrong place,
    and nothing about the image says so."""
    frame, values = _ramp_frame()
    out, gt = to_north_up(values, frame)
    assert out.shape == (3, 4)
    np.testing.assert_allclose(out[0], [9.0, 10.0, 11.0, 12.0])  # north = frame's LAST row
    np.testing.assert_allclose(out[-1], [1.0, 2.0, 3.0, 4.0])
    np.testing.assert_allclose(out, values[::-1])


def test_north_up_geotransform_is_north_up_and_anchored_at_the_top_left():
    frame, values = _ramp_frame()
    _, gt = to_north_up(values, frame)
    origin_x, px_w, rot_x, origin_y, rot_y, px_h = gt
    assert (origin_x, origin_y) == pytest.approx((0.0, 3.0))  # top-left = (xmin, ymax)
    assert px_w == pytest.approx(1.0)
    assert px_h == pytest.approx(-1.0)  # negative: rows run south
    assert (rot_x, rot_y) == (0.0, 0.0)  # no rotation terms: that is the point of resampling


def test_north_up_of_a_rotated_frame_fills_a_larger_box_and_masks_the_corners():
    """A rotated rectangle does not fill its own bounding box, so the
    corners must come back as nodata rather than as the nearest in-frame
    value -- clamping there would smear a real edge across empty ground."""
    frame, values = _ramp_frame(azimuth=45.0)
    out, _ = to_north_up(values, frame)
    assert out.shape[0] > 3 and out.shape[1] > 4  # the box grew
    assert np.isnan(out[0, 0])  # a corner of the box the frame never reaches
    finite = out[np.isfinite(out)]
    assert finite.size > 0
    assert set(np.unique(finite)) <= set(values.ravel())  # only real cell values, never blended


def test_north_up_never_invents_a_value_outside_the_frame():
    frame, values = _ramp_frame(azimuth=30.0)
    out, _ = to_north_up(values, frame)
    assert np.isnan(out).any()  # there ARE outside cells at this azimuth
    assert np.isfinite(out).any()


def test_north_up_rejects_values_that_do_not_match_the_frame():
    frame, _ = _ramp_frame()
    with pytest.raises(ValueError):
        to_north_up(np.zeros((2, 2)), frame)


def test_north_up_carries_nodata_through_unchanged():
    frame, values = _ramp_frame()
    values = values.copy()
    values[1, 1] = np.nan
    out, _ = to_north_up(values, frame)
    assert np.isnan(out[1, 1])  # row 1 of 3 is its own mirror image
    assert np.isfinite(out[0]).all()
```

- [ ] **Step 20: Run them and watch them fail**

Run: `./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_display.py -q -k north_up`
Expected: FAIL — `ImportError: cannot import name 'to_north_up'`.

- [ ] **Step 21: Implement `to_north_up`**

Append to `display.py`:

```python
def to_north_up(
    values: np.ndarray, frame: CubeFrame
) -> tuple[np.ndarray, tuple[float, float, float, float, float, float]]:
    """Resample a grid-local slice into a north-up raster and its geotransform.

    Spec 3 keeps cells grid-local so a cell column draws from a consistent
    set of traces, and resamples north-up only on the way out, because
    rotated GeoTIFFs are second-class in GDAL and QGIS. This is that one
    resample.

    Returns `(array, geotransform)` where `array` is (h, w) float32 with
    NaN outside the frame, and `geotransform` is GDAL's six-tuple
    `(origin_x, pixel_w, 0, origin_y, 0, -pixel_h)` anchored at the box's
    TOP-LEFT corner.

    Two things to get right, in the order they bite:

    * **Row 0 is north.** A raster's rows run south (the geotransform's
      y pixel size is negative) while a `CubeFrame`'s y index 0 is its
      southern edge, because frame-local +Y is north at azimuth 0. The
      output is therefore the frame's rows reversed, exactly, for an
      axis-aligned frame. Getting this wrong mirrors every slice
      vertically and produces an image that looks entirely plausible.
    * **Outside is nodata, never the nearest cell.** A rotated frame does
      not fill its own bounding box; clamping the corners to the nearest
      in-frame value would smear a real edge out across ground that was
      never surveyed.

    Nearest neighbour, not bilinear: these values are already cell means
    over real traces, and `fill` (spec 6.4) is the one place smoothing is
    a decision the user makes with a radius they can see. Interpolating
    again here would invent structure below the cell size and do it
    invisibly.
    """
    values = np.asarray(values, dtype=float)
    if values.shape != (frame.ny, frame.nx):
        raise ValueError(
            f"values must be {(frame.ny, frame.nx)} to match the frame, got {values.shape}"
        )
    xmin, ymin, xmax, ymax = slice_extent(frame)
    cell = frame.cell
    width = max(1, int(math.ceil((xmax - xmin) / cell)))
    height = max(1, int(math.ceil((ymax - ymin) / cell)))

    # Cell CENTRES, so a sample lands in the middle of its output pixel
    # rather than on a boundary where round-off decides which cell it
    # reads -- the same reason `cell_index` has its own edge tolerance.
    xs = xmin + (np.arange(width, dtype=float) + 0.5) * cell
    ys = ymax - (np.arange(height, dtype=float) + 0.5) * cell  # row 0 is north
    grid_x, grid_y = np.meshgrid(xs, ys)
    world = np.column_stack([grid_x.ravel(), grid_y.ravel()])

    ids = frame.cell_index(world)
    flat = values.reshape(-1)
    # `ids` is -1 outside; clip only so the gather is in-bounds, and let
    # `where` discard those rows. Indexing with a raw -1 would silently
    # read the frame's LAST cell instead.
    gathered = flat[np.clip(ids, 0, flat.size - 1)]
    out = np.where(ids >= 0, gathered, np.nan).reshape(height, width)
    return out.astype(np.float32), (xmin, cell, 0.0, ymax, 0.0, -cell)
```

- [ ] **Step 22: Run and watch them pass**

Run: `./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_display.py -q`
Expected: 18 passed.

- [ ] **Step 23: Prove the north-up tests discriminate**

Three mutants, one at a time:

1. `ys = ymax - (...)` → `ys = ymin + (...)` (the no-flip version). Expect
   `test_north_up_puts_frame_row_zero_at_the_BOTTOM_of_the_raster` to FAIL.
2. `np.where(ids >= 0, gathered, np.nan)` → `gathered` (clamp instead of mask). Expect
   `test_north_up_of_a_rotated_frame_fills_a_larger_box_and_masks_the_corners` and
   `test_north_up_never_invents_a_value_outside_the_frame` to FAIL.
3. `-cell` → `cell` in the returned geotransform. Expect
   `test_north_up_geotransform_is_north_up_and_anchored_at_the_top_left` to FAIL.

Record all three in the task report.

- [ ] **Step 24: Export the new names and commit**

In `packages/nsgeo-core/src/nsgeo/slices/__init__.py`, add to the existing imports (keeping the
`# noqa: F401` convention and alphabetical order within each line):

```python
from nsgeo.slices.display import (  # noqa: F401
    SliceWindow,
    limit_over_slices,
    plan_windows,
    shared_limit,
    to_north_up,
    window_depths_m,
    window_label,
    window_times_ns,
)
from nsgeo.slices.frame import CubeFrame, ZAxis, slice_extent  # noqa: F401
```

Run the whole core suite, `ruff`, and `mypy` before committing.

```bash
git add packages/nsgeo-core/src/nsgeo packages/nsgeo-core/tests/test_slices_display.py
git commit -m "feat(slices): to_north_up, the one resample out of the grid-local frame

Row 0 is north and outside is nodata; both are the defects a symmetric
fixture cannot see.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 25: Write the failing tests for the fill speedup**

Append to `packages/nsgeo-core/tests/test_slices_fill.py`:

```python
def test_smooth_size_is_never_smaller_than_asked_and_is_five_smooth():
    from nsgeo.slices.fill import _smooth_size

    for n in range(1, 400):
        m = _smooth_size(n)
        assert m >= n, f"_smooth_size({n}) = {m} would WRAP the convolution"
        rest = m
        for p in (2, 3, 5):
            while rest % p == 0:
                rest //= p
        assert rest == 1, f"_smooth_size({n}) = {m} is not 5-smooth"
    assert _smooth_size(1041) == 1080


def _unpadded_fill(values, counts, radius_cells, min_count=0.5):
    """M10's exact formula, at the exact minimum FFT size. The reference
    the padded implementation must agree with -- written out here rather
    than imported, so a change to the shipped one cannot quietly change
    the thing it is checked against."""
    import numpy as np
    from nsgeo.slices.fill import disc_kernel

    values = np.asarray(values, dtype=float)
    counts = np.asarray(counts, dtype=float)
    r = int(radius_cells)
    ny, nx = values.shape
    kernel = disc_kernel(r)
    finite = np.isfinite(values)
    numerator = np.where(finite, values, 0.0) * counts
    denominator = np.where(finite, counts, 0.0)
    shape = (ny + 2 * r, nx + 2 * r)
    spectrum = np.fft.rfft2(kernel, s=shape)
    num = np.fft.irfft2(np.fft.rfft2(numerator, s=shape) * spectrum, s=shape)[r : r + ny, r : r + nx]
    den = np.fft.irfft2(np.fft.rfft2(denominator, s=shape) * spectrum, s=shape)[
        r : r + ny, r : r + nx
    ]
    return np.divide(num, den, out=np.full((ny, nx), np.nan), where=den >= min_count).astype(
        np.float32
    )


@pytest.mark.parametrize(("ny", "nx", "radius"), [(37, 41, 3), (100, 100, 8), (213, 209, 10)])
def test_padding_to_a_smooth_size_does_not_change_the_answer(ny, nx, radius):
    """Zero-padding a linear convolution further can only add zeros past
    the end; the crop window is unmoved. If this ever fails, the crop
    offset is wrong, not the padding."""
    rng = np.random.default_rng(7)
    counts = (rng.random((ny, nx)) < 0.2).astype(float)
    values = np.where(counts > 0, rng.random((ny, nx)) * 10.0, np.nan)
    got = fill(values, counts, radius)
    want = _unpadded_fill(values, counts, radius)
    np.testing.assert_array_equal(np.isfinite(got), np.isfinite(want))  # identical nodata mask
    both = np.isfinite(got)
    np.testing.assert_allclose(got[both], want[both], rtol=1e-5, atol=1e-6)


def test_the_kernel_spectrum_cache_returns_the_same_answer_on_a_second_call():
    """A cached array handed out by reference would be corrupted by any
    caller that wrote into it. Nothing in `fill` does -- it only
    multiplies -- and this pins that: two identical fills either side of a
    different one must agree exactly."""
    rng = np.random.default_rng(11)
    counts = (rng.random((60, 60)) < 0.3).astype(float)
    values = np.where(counts > 0, rng.random((60, 60)), np.nan)
    first = fill(values, counts, 5)
    fill(values, counts, 7)  # a different radius, same shape family
    second = fill(values, counts, 5)
    np.testing.assert_array_equal(np.isfinite(first), np.isfinite(second))
    np.testing.assert_array_equal(first[np.isfinite(first)], second[np.isfinite(second)])


def test_clearing_the_kernel_cache_does_not_change_results():
    from nsgeo.slices.fill import clear_kernel_cache

    rng = np.random.default_rng(13)
    counts = (rng.random((50, 50)) < 0.3).astype(float)
    values = np.where(counts > 0, rng.random((50, 50)), np.nan)
    warm = fill(values, counts, 4)
    clear_kernel_cache()
    cold = fill(values, counts, 4)
    np.testing.assert_array_equal(warm[np.isfinite(warm)], cold[np.isfinite(cold)])
```

- [ ] **Step 26: Run them and watch them fail**

Run: `./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_slices_fill.py -q`
Expected: 3 FAIL on `ImportError` for `_smooth_size` / `clear_kernel_cache`;
`test_padding_to_a_smooth_size_does_not_change_the_answer` PASSES already (the shipped fill *is*
the reference today) — that is expected and correct, it becomes the regression guard once padding
lands.

- [ ] **Step 27: Implement the padding and the cache**

In `packages/nsgeo-core/src/nsgeo/slices/fill.py`, add `from functools import lru_cache` to the
imports, and insert after `disc_kernel`:

```python
def _smooth_size(n: int) -> int:
    """The smallest integer >= n whose only prime factors are 2, 3 and 5.

    numpy's FFT is fastest at such lengths and slowest at large primes.
    Because a linear convolution padded further only gains trailing zeros,
    rounding the transform size up is free of any effect on the cropped
    result -- measured 1.1x to 3.2x faster across the sizes a slice
    actually reaches, with the worst case (1021x1019 at r=10) falling from
    361 ms to 114 ms.

    Must never return less than `n`: a short transform would WRAP the
    convolution and corrupt the edges of the slice, silently.
    """
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    candidate = n
    while True:
        rest = candidate
        for prime in (2, 3, 5):
            while rest % prime == 0:
                rest //= prime
        if rest == 1:
            return candidate
        candidate += 1


@lru_cache(maxsize=4)
def _kernel_spectrum(radius_cells: int, shape: tuple[int, int]) -> np.ndarray:
    """The disc's transform at a padded size, cached across calls.

    The radius is a live slider (spec 9.2), so the same kernel is
    transformed again on every tick at an unchanged slice shape. Bounded
    at four entries because each is a complex128 array of roughly
    `shape[0] * (shape[1] // 2 + 1) * 16` bytes -- 9.3 MB at the largest
    size measured here, so ~37 MB worst case, released by
    `clear_kernel_cache()`.

    The returned array is SHARED. `fill` only multiplies with it and never
    writes into it; any future caller must do the same or take a copy.
    """
    return np.fft.rfft2(disc_kernel(radius_cells), s=shape)


def clear_kernel_cache() -> None:
    """Drop the cached kernel spectra. Called when a slice source is
    closed, so a large cube's spectra do not outlive the session that
    needed them."""
    _kernel_spectrum.cache_clear()
```

Then in `fill`, replace the three lines

```python
    shape = (ny + 2 * r, nx + 2 * r)
    spectrum = np.fft.rfft2(kernel, s=shape)
```

with

```python
    shape = (_smooth_size(ny + 2 * r), _smooth_size(nx + 2 * r))
    spectrum = _kernel_spectrum(r, shape)
```

and delete the now-unused local `kernel = disc_kernel(r)` binding (`_kernel_spectrum` builds it).

- [ ] **Step 28: Run, and measure**

Run: `./.venv/bin/python -m pytest packages/nsgeo-core/tests -q`
Expected: the full core suite passes, with the four new fill tests.

Then time it and put the numbers in the task report:

```bash
./.venv/bin/python - <<'EOF'
import time
import numpy as np
from nsgeo.slices.fill import fill
rng = np.random.default_rng(0)
for ny, nx in ((300, 300), (600, 600), (1021, 1019)):
    counts = (rng.random((ny, nx)) < 0.2).astype(float)
    values = np.where(counts > 0, rng.random((ny, nx)) * 10, np.nan)
    fill(values, counts, 10)
    t = time.perf_counter()
    for _ in range(5):
        fill(values, counts, 10)
    print(f"{ny}x{nx} r=10: {(time.perf_counter() - t) / 5 * 1e3:.1f} ms")
EOF
```

Expected, on this machine: about 6 / 32 / 114 ms, against M10's 7 / 45 / 361 ms. Report what you
actually get; the point is the shape of the improvement, not the absolute numbers.

- [ ] **Step 29: Prove the fill tests discriminate**

Mutate `_smooth_size` to `return n - 1 if n > 1 else 1` — the wrap-the-convolution defect it
exists to prevent. Confirm `test_smooth_size_is_never_smaller_than_asked_and_is_five_smooth`
FAILS. Revert and record.

(Amended during execution: this plan originally also predicted
`test_padding_to_a_smooth_size_does_not_change_the_answer` would fail here, calling it
"genuinely load-bearing" against this mutant. **It does not, and the reason is worth keeping.**
An FFT size exactly one short of the safe linear-convolution length wraps its aliasing onto
index 0 mod M in each dimension — which sits *outside* the crop window `[r : r+ny, r : r+nx]`
for every `r >= 1`, since the crop starts at `r`. Measured: max absolute difference 2.74e-14,
i.e. bit-identical. A larger undersizing would be caught; this particular off-by-one is
invisible. The wrap invariant is therefore enforced by `_smooth_size`'s own `m >= n` assertion
and by nothing else — do not delete that test on the grounds that the agreement test covers it.)

- [ ] **Step 30: Add the real-data test**

Append to `packages/nsgeo-core/tests/test_real_files.py`:

```python
def test_the_shared_stretch_on_a_real_cube_uses_most_of_the_colour_table():
    """The M10 measurement, against real GSSI data rather than a fixture.

    Real files are this project's primary validation (spec 11), and this
    is the one place the stretch a user actually sees is checked against
    data that came off an instrument.

    The SIZE of the reduction is a property of the data, not of the code.
    Adjacent levels in this real `amp_envelope` cube correlate at
    0.95-0.99, because envelope detection is itself a smoothing operation,
    so a window mean barely differs from the levels it averages. Measured
    on this corpus, `shared_limit` falls from 2.724 at thickness 1 to
    2.166 at 20 and 1.265 at 90 -- smooth and monotonic, exactly as
    specified. A synthetic fixture with i.i.d. levels shows a far larger
    reduction (~0.55) at the same thickness, which is why the magnitude
    claim lives on that fixture in `test_slices_display.py` and only the
    direction and the mechanism are asserted here.

    **Do not re-add a magnitude threshold to this test.** Any value that
    passes on this corpus is a fact about this antenna and this
    processing, not about `shared_limit`. An earlier draft asserted a
    `1.5x` bar carried over from an M10 measurement on different data; it
    failed at 1.08x and was removed (M11 ledger, Ruling D)."""
    from nsgeo.processing import build_step
    from nsgeo.render import UnipolarClip, to_index8_unipolar
    from nsgeo.slices.binning import PreparedLine, build_cube, plan_line
    from nsgeo.slices.cube import Provenance
    from nsgeo.slices.display import plan_windows, shared_limit
    from nsgeo.slices.frame import CubeFrame, ZAxis

    prepared = []
    for i, path in enumerate(FILES[:4]):
        header = read_header(path)
        rg = Radargram(
            data=np.asarray(read_samples(path, header)[0], dtype=float),
            dt_ns=header.dt_ns,
            t0_ns=header.position_ns,
        )
        for name in ("time_zero", "dewow", "background_mean", "gain_agc", "amp_envelope"):
            rg = build_step(name).apply(rg)
        n_traces = rg.data.shape[1]
        coords = np.column_stack(
            [np.linspace(0.0, 19.99, n_traces), np.full(n_traces, 0.25 + i * 0.5)]
        )
        prepared.append(
            PreparedLine(
                key=path.name,
                data=rg.data.astype(np.float32),
                dt_ns=rg.dt_ns,
                t0_ns=rg.t0_ns,
                coords=coords,
            )
        )
    frame = CubeFrame(origin=(0.0, 0.0), azimuth=0.0, cell=0.2, nx=100, ny=12, crs="EPSG:32633")
    z = ZAxis.from_range(1.0, 40.0, 0.2165)
    plans = [plan_line(p, frame, z) for p in prepared]
    prov = Provenance(
        line_keys=tuple(p.key for p in prepared),
        preset_name="test",
        steps=(),
        transform="amp_envelope",
        velocity=None,
        built_utc="2026-09-19T00:00:00Z",
        core_version="0.1.0.dev0",
    )
    cube = build_cube(prepared, plans, frame, z, prov)

    clip = UnipolarClip()
    # 23 levels is about 5.0 ns at this dz, which satisfies spec 6.6's own
    # rule that a thickness be at least one pulse width (~2.9 ns at 350
    # MHz). An earlier draft of this test used 10 levels -- 2.2 ns, SHORTER
    # than one pulse width -- and so exercised a thickness no user should
    # choose. (Amended during execution; see the M11 ledger's Ruling D.)
    thickness = 23
    correct = shared_limit(cube, thickness, clip)
    over_raw_levels = clip.limit(cube.mean)
    assert correct < over_raw_levels  # the direction M10 measured, on real data

    # The exact mechanism, on real data: the shared limit IS the percentile
    # over the slices actually displayed at this thickness. This is what
    # dies against the `clip.limit(cube.mean)` implementation M10 measured,
    # and against a windows-overlap mutant that weights mid-depths twice.
    windows = plan_windows(z, thickness, thickness)
    shown = np.concatenate([cube.slice_levels(w.k0, w.k1).ravel() for w in windows])
    shown = shown[np.isfinite(shown)]
    assert correct == pytest.approx(float(np.percentile(shown, clip.percentile)), rel=1e-6)

    # And what it means on screen: at the correct limit the displayed slices
    # sit higher in the 0-255 table than at the raw-level limit. The
    # DIRECTION is the claim; the magnitude is a property of how much the
    # data decorrelates with depth, not of this code -- see the docstring.
    assert np.median(to_index8_unipolar(shown, correct)) > np.median(
        to_index8_unipolar(shown, over_raw_levels)
    )
```

- [ ] **Step 31: Run the real-data test and confirm it is not skipping**

Run: `./.venv/bin/python -m pytest packages/nsgeo-core/tests/test_real_files.py -q -k shared_stretch -v`
Expected: **1 passed, 0 skipped.** A skip here means the symlinked DZT files are missing and the
test validated nothing — stop and fix the symlink rather than proceeding.

Record the two measured limits and the two median indices in the task report, and confirm the
amended test still kills both the `clip.limit(cube.mean)` mutant and a `plan_windows(cube.z,
thickness_levels, 1)` mutant inside `shared_limit`.

- [ ] **Step 32: Full verification and commit**

```bash
./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure packages/nsgeo-core/tests -q
./.venv/bin/ruff check . && ./.venv/bin/ruff format --check .
./.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
git add -A packages/nsgeo-core
git commit -m "perf(slices): smooth-size FFT padding and a cached kernel spectrum

The radius is a live slider in M11 and M10's fill built three uncached
FFTs per call at arbitrary padded sizes: 1021x1019 at r=10 falls from 361
ms to 114 ms, bit-comparable to the unpadded result. Still 32 ms at
600x600, so the slider debounces as well.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push origin nsgeo-m11
```

**Task 1 is done when:** the core suite is green with ~22 new tests, `ruff` and `mypy` are clean,
every named mutant has been shown to fail its own test, the real-data test ran rather than
skipped, and the fill timings are recorded.

---

### Task 2: The slice engine — preparation, plan cache, residency, one slice per tick

Everything between "the user chose a grid, a preset and a transform" and "here is a slice",
with no widgets in it. Its numeric half is Qt-free so it runs on the normal CI matrix and under
mypy.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`
- Create: `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`
- Modify: `.github/workflows/ci.yml` (add `slices_plan.py` to the mypy list)
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py` (new)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py` (new)

**Interfaces:**

- Consumes: Task 1's `SliceWindow`, `plan_windows`, `limit_over_slices`, `shared_limit`,
  `clear_kernel_cache`; M10's `CubeFrame.for_grid`, `ZAxis.from_range`, `PreparedLine`,
  `LinePlan`, `plan_line`, `build_cube`, `stream_slice`, `CoverageError`, `SliceCube`,
  `Provenance`; `SiteSession` (`site`, `is_open`, `keys()`, `line_for_key`, `grid`,
  `grid_for_line`, `resolved_velocity`, `site.presets`, `site_closed`); `nsgeo.processing`'s
  `StepStack`, `build_step`, `available_steps`, `get_step`, `Radargram`.
- Produces:
  - `slices_plan.SourceChoice(grid_id: str, preset: str, transform: str, line_keys: tuple[str, ...])`
  - `slices_plan.Resolution(cell: float, dz_ns: float, t0_ns: float, t1_ns: float)`
  - `slices_plan.MemoryEstimate(lines_bytes: int, cube_bytes: int)` with `.total_bytes`
  - `slices_plan.transform_names() -> list[str]`
  - `slices_plan.preset_transform_conflict(steps) -> str | None`
  - `slices_plan.estimate_memory(prepared_samples: int, n_cells: int, nz: int) -> MemoryEstimate`
  - `slices_plan.choose_residency(estimate, n_lines, budget_bytes, always_resident=False) -> str`
    returning `"resident"` or `"streaming"`
  - `slices_plan.format_bytes(n: int) -> str`, `slices_plan.format_status(...) -> str`
  - `slices_plan.DEFAULT_BUDGET_BYTES`, `STREAM_MS_PER_LINE`, `FRAME_BUDGET_MS`, `NO_TRANSFORM`
  - `slices_engine.SliceEngine(session, on_prepared=None, on_error=None, on_progress=None,
    parent=None)` with `set_source`, `set_resolution`, `clear`, `dispose`, `is_prepared`,
    `frame`, `z`, `mode`, `line_count`, `estimate`, `choice`, `has_cube`,
    `slice_at(window) -> (values, coverage)`,
    `shared_limit(thickness_levels, clip) -> float`, `cube() -> SliceCube`,
    `provenance() -> Provenance`, `status_text() -> str`, `wait_for_preparation(timeout_ms)`.

**`SliceEngine` deliberately declares no `pyqtSignal`.** The orphan-signal test
(`tests/pure/test_no_orphan_signals.py`) requires a `connect` in the *package* for every declared
signal, and this task has no consumer to connect one to — the dock arrives in Task 3. Constructor
callbacks are the existing pattern for exactly this (`LineLoader(session, on_error=...)`), and
they keep the rule honest rather than inviting a placeholder `connect` that satisfies a grep and
consumes nothing.

---

- [ ] **Step 1: Write the failing pure tests**

Create `packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py`:

```python
"""The Qt-free arithmetic behind the Slices dock."""

from __future__ import annotations

import pytest
from nsgeo_qgis.slices_plan import (
    DEFAULT_BUDGET_BYTES,
    FRAME_BUDGET_MS,
    MemoryEstimate,
    Resolution,
    SourceChoice,
    STREAM_MS_PER_LINE,
    choose_residency,
    estimate_memory,
    format_bytes,
    format_status,
    preset_transform_conflict,
    transform_names,
)


def test_transform_names_come_from_the_registry_not_a_hardcoded_list():
    """Adding an amplitude transform to the core registry must offer it
    here with no edit. The mutant is a literal list, which passes a
    membership assertion and silently omits anything added later."""
    from nsgeo.processing import available_steps, get_step

    names = transform_names()
    expected = [n for n in available_steps() if getattr(get_step(n), "unipolar", False)]
    assert names == expected
    assert set(names) == {"amp_abs", "amp_square", "amp_envelope"}
    assert "gain_agc" not in names and "dewow" not in names


def test_a_preset_carrying_an_amplitude_transform_is_a_conflict():
    """Ruling 2: the transform is appended by the engine and is never part
    of a preset, so that the transform is always the LAST enabled step and
    StepStack.output_unipolar is exact. A preset that already holds one
    breaks that, and the failure it produces -- unipolar data on a bipolar
    table -- is the one spec 8 exists to prevent."""
    assert preset_transform_conflict([{"step": "dewow", "params": {}}]) is None
    assert preset_transform_conflict([]) is None
    assert (
        preset_transform_conflict(
            [{"step": "time_zero"}, {"step": "amp_abs"}, {"step": "gain_agc"}]
        )
        == "amp_abs"
    )
    # Found wherever it sits, not only last -- gain-after-transform is
    # precisely the ordering that makes output_unipolar report False.
    assert preset_transform_conflict([{"step": "amp_envelope"}]) == "amp_envelope"
    # A disabled transform still conflicts: enabling it later would break
    # the invariant with no further warning.
    assert preset_transform_conflict([{"step": "amp_square", "enabled": False}]) == "amp_square"
    # An unknown step name is not this function's business to reject.
    assert preset_transform_conflict([{"step": "not_a_step"}]) is None


def test_memory_estimate_counts_the_lines_and_the_cube_separately():
    """Spec 7.4's inversion: by 120 lines the cached LINES cost more than
    the cube. A policy that only attacks the cube does nothing for a large
    site, so the two are reported apart."""
    est = estimate_memory(prepared_samples=10_000_000, n_cells=90_000, nz=230)
    assert est.lines_bytes == 10_000_000 * 4
    assert est.cube_bytes == 230 * 90_000 * 4 + 90_000 * 4
    assert est.total_bytes == est.lines_bytes + est.cube_bytes


def test_streaming_stays_the_default_while_nobody_could_perceive_the_difference():
    """Spec 9.2: a resident cube redraws in 0.56 ms against streaming's
    3.6 ms and nobody can perceive that. Holding the cube below the frame
    budget buys nothing and costs memory, so it is not done even when
    there is room."""
    small = MemoryEstimate(lines_bytes=28_000_000, cube_bytes=83_000_000)
    assert choose_residency(small, n_lines=24, budget_bytes=DEFAULT_BUDGET_BYTES) == "streaming"
    assert 24 * STREAM_MS_PER_LINE < FRAME_BUDGET_MS  # why


def test_a_large_site_is_promoted_to_a_resident_cube_when_it_fits():
    est = MemoryEstimate(lines_bytes=140_000_000, cube_bytes=83_000_000)
    n_lines = 200  # 200 * 0.14 ms = 28 ms per tick, past a 16 ms frame
    assert n_lines * STREAM_MS_PER_LINE > FRAME_BUDGET_MS
    assert choose_residency(est, n_lines, budget_bytes=DEFAULT_BUDGET_BYTES) == "resident"


def test_a_large_site_that_does_not_fit_degrades_to_streaming_rather_than_failing():
    """Spec 7.4: an over-budget cube degrades to streaming instead of
    failing, and the source dialog warns rather than hard-caps."""
    est = MemoryEstimate(lines_bytes=140_000_000, cube_bytes=4_000_000_000)
    assert choose_residency(est, n_lines=200, budget_bytes=DEFAULT_BUDGET_BYTES) == "streaming"


def test_the_settings_override_wins_in_both_directions():
    small = MemoryEstimate(lines_bytes=1_000, cube_bytes=1_000)
    assert choose_residency(small, 2, DEFAULT_BUDGET_BYTES, always_resident=True) == "resident"
    huge = MemoryEstimate(lines_bytes=1, cube_bytes=10**12)
    # The user asked for it and spec 7.4 never hard-caps; the dock warns.
    assert choose_residency(huge, 2, DEFAULT_BUDGET_BYTES, always_resident=True) == "resident"


def test_format_bytes_reads_like_the_spec_status_line():
    assert format_bytes(28_000_000) == "28 MB"
    assert format_bytes(1_500_000_000) == "1.5 GB"
    assert format_bytes(900) == "1 MB"  # never "0 MB": a held line is not nothing


def test_the_status_line_says_what_is_held_and_how_fast_it_redraws():
    """Spec 9.2's wording, near-verbatim: memory, not time, is the binding
    constraint, and a constraint the user cannot see is one they cannot
    act on."""
    est = MemoryEstimate(lines_bytes=28_000_000, cube_bytes=83_000_000)
    streaming = format_status("streaming", n_lines=24, estimate=est, redraw_ms=3.6)
    assert streaming == "24 lines held in memory, 28 MB · slices redraw in 4 ms"
    resident = format_status("resident", n_lines=24, estimate=est, redraw_ms=0.56)
    assert "whole volume" in resident
    assert "111 MB" in resident  # lines AND cube, because both are held
    assert format_status("streaming", 1, est, 3.6).startswith("1 line held")  # not "1 lines"
    assert "redraw in —" in format_status("streaming", 24, est, redraw_ms=None)


def test_the_value_objects_validate_themselves():
    with pytest.raises(ValueError):
        Resolution(cell=0.0, dz_ns=0.5, t0_ns=0.0, t1_ns=50.0)
    with pytest.raises(ValueError):
        Resolution(cell=0.1, dz_ns=-1.0, t0_ns=0.0, t1_ns=50.0)
    with pytest.raises(ValueError):
        Resolution(cell=0.1, dz_ns=0.5, t0_ns=50.0, t1_ns=0.0)
    ok = Resolution(cell=0.1, dz_ns=0.5, t0_ns=0.0, t1_ns=50.0)
    assert ok.cell == 0.1
    choice = SourceChoice(grid_id="A", preset="p", transform="amp_abs", line_keys=("a", "b"))
    assert choice.line_keys == ("a", "b")
```

- [ ] **Step 2: Run them and watch them fail**

Run: `./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py -q`
Expected: collection error — no module `nsgeo_qgis.slices_plan`.

- [ ] **Step 3: Implement `slices_plan.py`**

Create `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py`:

```python
"""Qt-free arithmetic behind the Slices dock.

Everything here is a pure function of plain values, so it runs on the
normal CI matrix (no QGIS) and under mypy, the same bargain `lookup.py`
makes. The dock reads it; the engine reads it; neither of them computes
any of it.

Two rules live here rather than in a widget, because both are decisions
with reasons rather than layout:

* **A preset never carries an amplitude transform.** The engine appends
  the chosen transform after the preset's steps, so the transform is
  always the last enabled step and `StepStack.output_unipolar` is exact.
  Were a preset to carry one with a gain after it, `output_unipolar`
  would report False -- it is deliberately conservative, reporting only
  the last enabled step -- and a unipolar slice would be drawn on a
  bipolar table, which is the configuration error spec 8 exists to name.
* **Residency is chosen, not asked about.** Spec 9.2: a resident cube
  redraws a slice in 0.56 ms against streaming's 3.6 ms, and nobody can
  perceive that. It only begins to matter on a large site during a
  continuous drag. Asking a user to understand the word "residency" to
  make that call is asking them to do the plugin's job.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from nsgeo.processing import available_steps, get_step

#: The Transform combo's "no transform" entry. Spec 6.2 and GPRSLICE's own
#: `xfrm_method=NONE` both allow it: the slice is then a signed mean, drawn
#: on a bipolar table, and the two stay consistent because the transform
#: being absent is exactly what `output_unipolar` reports.
NO_TRANSFORM = ""

#: Measured, spec 7.4: streaming costs ~0.14 ms per line per tick.
STREAM_MS_PER_LINE = 0.14

#: One 60 Hz frame. Below this, streaming is imperceptible.
FRAME_BUDGET_MS = 16.0

#: What the plugin will hold before it stops promoting to a resident cube.
#: A default, never a cap -- spec 7.4 warns and degrades, it does not block.
DEFAULT_BUDGET_BYTES = 1_500_000_000


@dataclass(frozen=True)
class SourceChoice:
    """What goes into a cube: spec 9.1's four decisions, as one value.

    `transform` is `NO_TRANSFORM` or a name from `transform_names()`.
    `line_keys` is the included subset, in survey order -- the thing the
    `Choose...` dialog edits.
    """

    grid_id: str
    preset: str
    transform: str
    line_keys: tuple[str, ...]


@dataclass(frozen=True)
class Resolution:
    """The Resolution group's geometry: what a cube is binned at.

    Every field here invalidates every `LinePlan`. That is why they are
    one value rather than four setters -- there is no such thing as
    changing the cell size and keeping the plans, and M10 measured what
    happens when someone tries: a 1.0 m-cell plan used against a 0.5 m-cell
    frame bins every trace into the wrong cell, with no exception and
    plausible-looking coverage.

    The fill radius is NOT here: it is a display parameter applied after
    binning (spec 6.4), so it changes no plan.
    """

    cell: float
    dz_ns: float
    t0_ns: float
    t1_ns: float

    def __post_init__(self) -> None:
        if not self.cell > 0.0:
            raise ValueError(f"cell must be positive, got {self.cell}")
        if not self.dz_ns > 0.0:
            raise ValueError(f"dz_ns must be positive, got {self.dz_ns}")
        if not self.t1_ns > self.t0_ns:
            raise ValueError(f"t1_ns must exceed t0_ns, got {self.t0_ns}..{self.t1_ns}")


@dataclass(frozen=True)
class MemoryEstimate:
    """Held bytes, split the way spec 7.4 splits them.

    Separately, because they grow in opposite directions: cube memory
    grows with resolution and not with line count, cache memory the
    reverse. By 120 lines the cached lines cost more than the cube, so a
    single total would hide which one to act on.
    """

    lines_bytes: int
    cube_bytes: int

    @property
    def total_bytes(self) -> int:
        return self.lines_bytes + self.cube_bytes


def transform_names() -> list[str]:
    """Registered steps whose output is unipolar, in registry order.

    From the registry, never a literal: the plugin's rule everywhere is
    that steps come from `available_steps()`, and a hardcoded list would
    silently omit any transform added to the core later.
    """
    return [name for name in available_steps() if getattr(get_step(name), "unipolar", False)]


def preset_transform_conflict(steps: Sequence[Mapping[str, Any]]) -> str | None:
    """The name of the first amplitude transform in a preset, or None.

    Anywhere in the stack, and regardless of `enabled`: a disabled
    transform is one click from breaking the same invariant, with nothing
    to warn about it a second time.
    """
    for entry in steps:
        name = str(entry.get("step", ""))
        try:
            cls = get_step(name)
        except (KeyError, ValueError):
            continue  # not a step we know; not this function's business
        if getattr(cls, "unipolar", False):
            return name
    return None


def estimate_memory(prepared_samples: int, n_cells: int, nz: int) -> MemoryEstimate:
    """Bytes held by the prepared lines, and by a cube of this shape.

    `prepared_samples` is the total float32 sample count across every
    prepared line (`sum(n_samples * n_traces)`). The cube is float32
    `mean` plus int32 `count`, which is what `SliceCube` stores.
    """
    return MemoryEstimate(
        lines_bytes=int(prepared_samples) * 4,
        cube_bytes=int(nz) * int(n_cells) * 4 + int(n_cells) * 4,
    )


def choose_residency(
    estimate: MemoryEstimate,
    n_lines: int,
    budget_bytes: int = DEFAULT_BUDGET_BYTES,
    always_resident: bool = False,
) -> str:
    """`"resident"` or `"streaming"`, from the line count and the budget.

    Three tiers are described in spec 7.4; two exist. The third -- one
    line at a time, memory-mapped off disk -- is unmeasured there, was
    never built, and M11 deliberately ships no control for it (plan
    Ruling 1). This function therefore returns one of two values, and
    nothing downstream should branch on a third.
    """
    if always_resident:
        return "resident"
    if n_lines * STREAM_MS_PER_LINE <= FRAME_BUDGET_MS:
        # Imperceptible. Holding a cube here would spend memory to buy
        # nothing a person can see.
        return "streaming"
    if estimate.total_bytes <= budget_bytes:
        return "resident"
    return "streaming"


def format_bytes(n: int) -> str:
    """Megabytes, or gigabytes past a thousand of them. Never `0 MB`."""
    mb = n / 1_000_000.0
    if mb >= 1000.0:
        return f"{mb / 1000.0:.1f} GB"
    return f"{max(1, round(mb))} MB"


def format_status(
    mode: str,
    n_lines: int,
    estimate: MemoryEstimate,
    redraw_ms: float | None,
) -> str:
    """Spec 9.2's status line: what is held, and how fast slices redraw.

    Memory first, because spec 7.2 found memory and not time to be the
    binding constraint -- halving the cell doubles the time and
    quadruples the cube.
    """
    held = estimate.lines_bytes
    noun = "line" if n_lines == 1 else "lines"
    if mode == "resident":
        held += estimate.cube_bytes
        what = f"{n_lines} {noun} and the whole volume held in memory"
    else:
        what = f"{n_lines} {noun} held in memory"
    speed = "—" if redraw_ms is None else f"{max(1, round(redraw_ms))} ms"
    return f"{what}, {format_bytes(held)} · slices redraw in {speed}"
```

- [ ] **Step 4: Run and watch them pass; add the module to CI's mypy list**

Run: `./.venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q`
Expected: the new file's 10 tests pass alongside the existing pure tier.

Then in `.github/workflows/ci.yml`, extend the `lint` job's mypy invocation to:

```yaml
      - run: |
          mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
            packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
            packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py \
            packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py
```

and run the same command locally. Expected: `Success`.

- [ ] **Step 5: Prove the pure tests discriminate**

Three mutants, one at a time:

1. `transform_names` → `return ["amp_abs", "amp_square", "amp_envelope"]`. Expect
   `test_transform_names_come_from_the_registry_not_a_hardcoded_list` to FAIL — and note in the
   report *why* the equality against a recomputed list is what catches it, where a membership
   assertion would not.
2. `preset_transform_conflict` → only inspect `steps[-1]`. Expect the gain-after-transform case
   to FAIL.
3. `choose_residency` → drop the `n_lines * STREAM_MS_PER_LINE <= FRAME_BUDGET_MS` branch. Expect
   `test_streaming_stays_the_default_while_nobody_could_perceive_the_difference` to FAIL.

- [ ] **Step 6: Commit**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py \
        packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py .github/workflows/ci.yml
git commit -m "feat(slices): the Qt-free arithmetic behind the Slices dock

Registry-driven transforms, the preset-conflict rule that keeps
output_unipolar exact, the memory estimate and the two-tier residency
choice. Added to CI's mypy list.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 7: Write the failing engine tests**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py`:

```python
"""SliceEngine: preparation, the plan cache, residency, one slice per tick."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.render import UnipolarClip
from nsgeo.slices import CoverageError, SliceWindow
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.slices_engine import SliceEngine
from nsgeo_qgis.slices_plan import NO_TRANSFORM, Resolution, SourceChoice
from plugin_testing import synthetic_dzt

GRID = Grid("A", (500.0, 700.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5)
PRESET = [
    {"step": "time_zero", "params": {}, "enabled": True},
    {"step": "dewow", "params": {}, "enabled": True},
    {"step": "gain_agc", "params": {}, "enabled": True},
]


@pytest.fixture
def sourced(qgis_app, tmp_path):
    """A session with four parallel lines in one grid, and an engine on it."""
    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    lines = []
    for i in range(4):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", 1.0 + i * 1.0, 0.0, 1, p.stem)))
    session.add_lines(lines)
    session.site.presets["p"] = list(PRESET)
    errors: list[tuple[str, str]] = []
    prepared: list[int] = []
    engine = SliceEngine(
        session,
        on_prepared=lambda: prepared.append(1),
        on_error=lambda msg: errors.append(("error", msg)),
    )
    yield engine, session, errors, prepared
    engine.dispose()


def _prepare(engine, session, transform="amp_envelope", preset="p"):
    engine.set_source(
        SourceChoice(
            grid_id="A", preset=preset, transform=transform, line_keys=tuple(session.keys())
        )
    )
    assert engine.wait_for_preparation(20_000), "preparation did not finish"
    engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))


def test_preparation_applies_the_preset_and_appends_the_transform(sourced):
    engine, session, errors, prepared = sourced
    _prepare(engine, session)
    assert errors == []
    assert prepared == [1]
    assert engine.is_prepared
    assert engine.line_count == 4
    assert engine.output_unipolar is True
    values, coverage = engine.slice_at(SliceWindow(4, 14))
    covered = values[coverage > 0]
    assert covered.size > 0
    assert np.isfinite(covered).all()
    assert (covered >= 0.0).all(), "an envelope is unipolar; a negative means it was not applied"


def test_no_transform_leaves_the_data_bipolar_and_says_so(sourced):
    engine, session, errors, _ = sourced
    _prepare(engine, session, transform=NO_TRANSFORM)
    assert engine.output_unipolar is False
    values, coverage = engine.slice_at(SliceWindow(4, 14))
    covered = values[coverage > 0]
    assert (covered < 0.0).any(), "a signed mean of a signed radargram should reach below zero"


def test_a_preset_that_already_carries_a_transform_is_refused_by_name(sourced):
    """Ruling 2. The refusal must name the step, because the user's fix is
    to remove that specific step from that specific preset."""
    engine, session, errors, _ = sourced
    session.site.presets["bad"] = [
        {"step": "amp_abs", "params": {}, "enabled": True},
        {"step": "gain_agc", "params": {}, "enabled": True},
    ]
    with pytest.raises(ValueError, match="amp_abs"):
        engine.set_source(
            SourceChoice(grid_id="A", preset="bad", transform="amp_square", line_keys=("x",))
        )
    assert not engine.is_prepared


def test_changing_the_cell_size_re_plans_every_line(sourced):
    """The defect M10's final review called M11's first bug. A LinePlan is
    a function of (line, frame, z) and every Resolution control changes
    one of them; reusing a plan across that change bins every trace into
    the wrong cell. Before M10's guard existed it did so SILENTLY, with
    plausible coverage. The engine must drop its plans, not rely on the
    guard to raise."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    coarse, _ = engine.slice_at(SliceWindow(4, 14))
    assert coarse.shape == (24, 24)  # 6 m / 0.25 m

    engine.set_resolution(Resolution(cell=0.5, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
    fine, _ = engine.slice_at(SliceWindow(4, 14))  # must NOT raise
    assert fine.shape == (12, 12)

    # And a z-axis change, which the same plans would also survive by
    # length alone if nz happened to match.
    engine.set_resolution(Resolution(cell=0.5, dz_ns=0.25, t0_ns=2.0, t1_ns=16.0))
    again, _ = engine.slice_at(SliceWindow(4, 14))
    assert again.shape == (12, 12)


def test_streaming_and_a_resident_cube_give_the_same_slice(sourced):
    """Spec 11's property, in the form a user could notice: the mode they
    are in must not change what they see."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    engine.set_always_resident(False)
    assert engine.mode == "streaming"
    streamed, cov_s = engine.slice_at(SliceWindow(6, 18))

    engine.set_always_resident(True)
    assert engine.mode == "resident"
    resident, cov_r = engine.slice_at(SliceWindow(6, 18))

    np.testing.assert_array_equal(cov_s, cov_r)
    both = np.isfinite(streamed) & np.isfinite(resident)
    assert both.any()
    np.testing.assert_allclose(streamed[both], resident[both], rtol=1e-5, atol=1e-6)
    np.testing.assert_array_equal(np.isfinite(streamed), np.isfinite(resident))


def test_the_shared_limit_agrees_between_the_two_modes(sourced):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    clip = UnipolarClip()
    engine.set_always_resident(False)
    streamed = engine.shared_limit(10, clip)
    engine.set_always_resident(True)
    resident = engine.shared_limit(10, clip)
    assert streamed == pytest.approx(resident, rel=1e-4)
    assert streamed > 0.0


def test_provenance_names_the_lines_that_were_actually_prepared(sourced):
    """Not the lines that were asked for. A line that failed to prepare is
    not in the cube and must not be claimed by its provenance -- that
    record is what a reader trusts the thing by."""
    engine, session, _, _ = sourced
    _prepare(engine, session)
    prov = engine.provenance()
    assert prov.line_keys == tuple(session.keys())
    assert prov.preset_name == "p"
    assert prov.transform == "amp_envelope"
    assert len(prov.steps) == len(PRESET)
    assert prov.core_version
    assert prov.built_utc.endswith("Z")


def test_a_z_range_the_lines_do_not_cover_is_reported_with_the_line_named(sourced):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    engine.set_resolution(Resolution(cell=0.5, dz_ns=0.5, t0_ns=0.0, t1_ns=400.0))
    with pytest.raises(CoverageError, match="FILE__001"):
        engine.slice_at(SliceWindow(0, 4))


def test_the_status_line_follows_the_mode_and_the_line_count(sourced):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    engine.slice_at(SliceWindow(4, 14))
    text = engine.status_text()
    assert text.startswith("4 lines held in memory")
    assert "slices redraw in" in text
    engine.set_always_resident(True)
    engine.slice_at(SliceWindow(4, 14))
    assert "whole volume" in engine.status_text()


def test_closing_the_site_releases_everything(sourced):
    engine, session, _, _ = sourced
    _prepare(engine, session)
    assert engine.is_prepared
    session.close_site()
    assert not engine.is_prepared
    assert engine.line_count == 0
    assert engine.frame is None


def test_a_line_that_cannot_be_prepared_is_reported_by_name(sourced, tmp_path):
    engine, session, errors, _ = sourced
    key = session.keys()[0]
    session.line_for_key(key).path.unlink()  # the file goes away under us
    engine.set_source(
        SourceChoice(
            grid_id="A", preset="p", transform="amp_abs", line_keys=tuple(session.keys())
        )
    )
    assert engine.wait_for_preparation(20_000)
    assert any(key in msg for _, msg in errors), f"no error named {key}: {errors}"
```

- [ ] **Step 8: Run them and watch them fail**

Run: `QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py -q -p no:xonsh`
Expected: collection error — no module `nsgeo_qgis.slices_engine`.

- [ ] **Step 9: Implement `slices_engine.py`**

Create `packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py`:

```python
"""Preparing lines, holding plans, and handing over one slice per tick.

Spec 6.1's three tiers, owned in one place. Tier 1 -- load, preset,
transform -- is the only expensive step (about 0.9 s for 24 lines) and
depends on the preset and the transform and on nothing else, so it is
cached here and every geometric parameter stays cheap. Tier 2, the
resample-and-bin plan, depends on the cell size, dz and the z range, and
is dropped wholesale whenever any of them moves. Tier 3 is a slice, which
is what `slice_at` returns.

**No `pyqtSignal`.** `tests/pure/test_no_orphan_signals.py` requires a
`connect` in the package for every declared signal, and this module's
consumer (the Slices dock) does not exist yet. Constructor callbacks are
the pattern `LineLoader` already uses for exactly this, and they keep that
rule honest instead of inviting a `connect` that satisfies a grep and
consumes nothing.

Four hazards, all of them recorded elsewhere in this codebase and all of
them live here:

* `QgsApplication.taskManager().addTask()` keeps no strong reference to a
  `QgsTask.fromFunction()` task. `_pending` is the keep-alive; without it
  the task is collected silently and `on_finished` never runs. `addTask()`
  returning 0 means it was never added at all, so the bookkeeping has to
  be undone in that branch.
* `QgsTaskWrapper.finished()` swallows any exception an `on_finished`
  callback raises, with no traceback anywhere -- worse than the ordinary
  slot hazard, which at least reaches stderr. `_finished` guards its own
  body with `except`, not merely `finally`.
* The site can be closed, or a different site opened, while a preparation
  is in flight. `_generation` and the captured site identity together
  decide whether a result may be kept: keys are relative paths, so the
  same string can name a line in two different sites.
* **A `LinePlan` must never outlive the frame or z axis it was built
  against.** Every `Resolution` field invalidates every plan.
  `_rebuild_geometry` drops them by setting `_plans = None`, and
  `build_cube`/`stream_slice` carry M10's own guard underneath as a second
  line of defence. Do not "optimise" this into a partial update: M10
  measured the silent version binning every trace into the wrong cell with
  entirely plausible coverage.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any

import nsgeo
import numpy as np
from nsgeo.processing import Radargram, StepStack, build_step
from nsgeo.slices import (
    CubeFrame,
    LinePlan,
    PreparedLine,
    Provenance,
    SliceCube,
    SliceWindow,
    ZAxis,
    build_cube,
    limit_over_slices,
    plan_line,
    plan_windows,
    stream_slice,
)
from nsgeo.slices import shared_limit as cube_shared_limit
from nsgeo.slices.fill import clear_kernel_cache
from qgis.core import QgsApplication, QgsTask
from qgis.PyQt.QtCore import QEventLoop, QObject, QTimer

from nsgeo_qgis.slices_plan import (
    DEFAULT_BUDGET_BYTES,
    NO_TRANSFORM,
    MemoryEstimate,
    Resolution,
    SourceChoice,
    choose_residency,
    estimate_memory,
    format_status,
    preset_transform_conflict,
)

#: How much of the previous redraw timing survives into the reported one.
#: A plain last-value readout flickers between 2 ms and 9 ms on a drag and
#: is unreadable; this smooths it without hiding a real change.
_REDRAW_SMOOTHING = 0.7


class SliceEngine(QObject):
    """Everything between a chosen source and a slice. Owns no widgets."""

    def __init__(
        self,
        session: Any,
        on_prepared: Callable[[], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.on_prepared = on_prepared
        self.on_error = on_error
        self.on_progress = on_progress
        self._choice: SourceChoice | None = None
        self._resolution: Resolution | None = None
        self._lines: list[PreparedLine] = []
        self._plans: list[LinePlan] | None = None
        self._frame: CubeFrame | None = None
        self._z: ZAxis | None = None
        self._cube: SliceCube | None = None
        self._mode = "streaming"
        self._always_resident = False
        self._budget_bytes = DEFAULT_BUDGET_BYTES
        self._redraw_ms: float | None = None
        self._generation = 0
        self._running = False
        # See the module docstring: addTask() keeps no reference of its
        # own, so a task with no Python reference is collected silently
        # and its on_finished never runs.
        self._pending: set[QgsTask] = set()
        session.site_closed.connect(self.clear)

    # ---- state ------------------------------------------------------------
    @property
    def is_prepared(self) -> bool:
        return bool(self._lines)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def line_count(self) -> int:
        return len(self._lines)

    @property
    def frame(self) -> CubeFrame | None:
        return self._frame

    @property
    def z(self) -> ZAxis | None:
        return self._z

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def choice(self) -> SourceChoice | None:
        """What this engine was last pointed at. The exporter needs it to
        write a recipe; nothing may reach past this for `_choice`."""
        return self._choice

    @property
    def has_cube(self) -> bool:
        """Whether a resident cube is currently held.

        Public because "did this operation quietly build a cube?" is a
        contract, not an implementation detail: spec 7.4 makes a resident
        cube a latency optimisation and never a capability, and export is
        the operation most tempted to forget that.
        """
        return self._cube is not None

    @property
    def output_unipolar(self) -> bool:
        """Whether a slice from this source has no negative side.

        Exactly `transform != NO_TRANSFORM`, and that is a structural fact
        rather than a guess: the transform is appended AFTER the preset's
        steps, so it is always the last enabled step. `_build_stack`
        asserts the two agree, so a future edit that reorders them fails
        loudly instead of putting unipolar data on a bipolar table.
        """
        return self._choice is not None and self._choice.transform != NO_TRANSFORM

    @property
    def estimate(self) -> MemoryEstimate:
        samples = sum(int(line.data.size) for line in self._lines)
        n_cells = self._frame.n_cells if self._frame is not None else 0
        nz = self._z.nz if self._z is not None else 0
        return estimate_memory(samples, n_cells, nz)

    def set_always_resident(self, flag: bool) -> None:
        """The settings override of spec 9.2, worded there for what it
        buys: *keep the whole volume in memory for faster dragging*."""
        self._always_resident = bool(flag)
        self._choose_mode()

    def set_budget_bytes(self, budget: int) -> None:
        self._budget_bytes = int(budget)
        self._choose_mode()

    def _choose_mode(self) -> None:
        self._mode = choose_residency(
            self.estimate, len(self._lines), self._budget_bytes, self._always_resident
        )

    # ---- source -----------------------------------------------------------
    def set_source(self, choice: SourceChoice | None) -> None:
        """Choose what goes into the cube and start preparing it.

        Raises ValueError, synchronously and before any work starts, if
        the preset carries an amplitude transform (plan Ruling 2) -- the
        caller is a dialog, and a refusal it can show is worth more than
        an error that arrives a second later through a callback.
        """
        self._generation += 1
        self._lines = []
        self._plans = None
        self._cube = None
        self._redraw_ms = None
        self._choice = choice
        if choice is None or not self.session.is_open:
            self._rebuild_geometry()
            return

        site = self.session.site
        steps = list(site.presets.get(choice.preset, []))
        conflict = preset_transform_conflict(steps)
        if conflict is not None:
            self._choice = None
            raise ValueError(
                f"the preset {choice.preset!r} already contains the amplitude transform "
                f"{conflict!r}. A cube's transform is chosen here and applied last, so "
                f"remove {conflict!r} from the preset or choose it in Transform, not both"
            )

        jobs: list[tuple[str, Any, np.ndarray]] = []
        frames = site.frames
        for key in choice.line_keys:
            try:
                line = self.session.line_for_key(key)
                jobs.append((key, line, line.trace_coords(frames)))
            except Exception as exc:  # noqa: BLE001 -- a missing grid or a stale key
                self._report(f"{key}: {exc}")
        if not jobs:
            self._rebuild_geometry()
            self._finish_preparation()
            return
        self._start_task(jobs, steps, choice.transform, self._generation)

    def _build_stack(self, steps: Sequence[dict[str, Any]], transform: str) -> StepStack:
        """The preset, then the transform. Order is the whole point.

        `StepStack.output_unipolar` reports the LAST ENABLED step and is
        deliberately conservative: `[amp_abs, gain_agc]` reports False
        though AGC preserves unipolarity. Appending the transform makes
        that conservatism irrelevant, because the transform is always
        last. The assert is cheap and pins the property for whoever edits
        this next.
        """
        stack = StepStack.from_dicts([dict(s) for s in steps])
        if transform != NO_TRANSFORM:
            stack.append(build_step(transform))
        if stack.output_unipolar != (transform != NO_TRANSFORM):
            raise ValueError(
                "the built stack's polarity disagrees with the chosen transform; "
                "the transform must be the last enabled step"
            )
        return stack

    def _start_task(
        self,
        jobs: list[tuple[str, Any, np.ndarray]],
        steps: Sequence[dict[str, Any]],
        transform: str,
        generation: int,
    ) -> None:
        # Validated on the main thread, before the task runs, so a bad
        # preset cannot surface from a worker thread.
        self._build_stack(steps, transform)
        requested_against = self.session.site
        total = len(jobs)
        failures: list[str] = []

        def work(task: QgsTask) -> Any:
            out: list[PreparedLine] = []
            for index, (key, line, coords) in enumerate(jobs):
                if task.isCanceled():
                    return None
                try:
                    profiles = line.load()
                    radargram = Radargram.from_profile(profiles[0])
                    stack = self._build_stack(steps, transform)
                    stack.source = radargram
                    result = stack.result()
                    out.append(
                        PreparedLine(
                            key=key,
                            data=np.asarray(result.data, dtype=np.float32),
                            dt_ns=result.dt_ns,
                            t0_ns=result.t0_ns,
                            coords=coords,
                        )
                    )
                except Exception as exc:  # noqa: BLE001 -- one bad line must not
                    # abandon the other twenty-three; it is named and skipped.
                    failures.append(f"{key}: {exc}")
                task.setProgress(100.0 * (index + 1) / total)
            return out

        def finished(exception: BaseException | None, result: Any = None) -> None:
            self._pending.discard(task)
            try:
                if generation != self._generation:
                    return  # a newer source was chosen; this result is stale
                if self.session.site is not requested_against:
                    return  # the site was closed or replaced under us
                self._running = False
                for message in failures:
                    self._report(message)
                if exception is not None:
                    self._report(str(exception))
                    return
                self._lines = list(result or [])
                self._rebuild_geometry()
                self._finish_preparation()
            except Exception as exc:  # noqa: BLE001 -- see the module docstring:
                # QgsTaskWrapper swallows this with no traceback anywhere.
                self._running = False
                self._report(f"could not finish preparing the slice source: {exc}")

        task = QgsTask.fromFunction("nsgeo: prepare slice source", work, on_finished=finished)
        task.progressChanged.connect(lambda pct: self._emit_progress(pct, total))
        self._pending.add(task)
        self._running = True
        if not QgsApplication.taskManager().addTask(task):
            # Never added, so on_finished will never run and nothing else
            # holds a reference either: undo everything here.
            self._pending.discard(task)
            self._running = False
            self._report("could not schedule the slice source preparation")

    def _emit_progress(self, percent: float, total: int) -> None:
        if self.on_progress is None:
            return
        try:
            self.on_progress(int(round(percent / 100.0 * total)), total)
        except Exception as exc:  # noqa: BLE001 -- a slot on a Qt signal
            self._report(f"could not report progress: {exc}")

    def _finish_preparation(self) -> None:
        if self.on_prepared is None:
            return
        self.on_prepared()

    def _report(self, message: str) -> None:
        if self.on_error is not None:
            self.on_error(message)

    # ---- geometry ---------------------------------------------------------
    def set_resolution(self, resolution: Resolution | None) -> None:
        """Set the binning geometry. Drops every plan; see the module docstring."""
        self._resolution = resolution
        self._rebuild_geometry()

    def _rebuild_geometry(self) -> None:
        # Unconditional, and wholesale. There is no such thing as keeping
        # a plan across a geometry change.
        self._plans = None
        self._cube = None
        self._frame = None
        self._z = None
        self._redraw_ms = None
        if self._choice is None or self._resolution is None or not self.session.is_open:
            self._choose_mode()
            return
        grid = self.session.grid(self._choice.grid_id)
        res = self._resolution
        self._frame = CubeFrame.for_grid(grid, res.cell)
        self._z = ZAxis.from_range(res.t0_ns, res.t1_ns, res.dz_ns)
        self._choose_mode()

    def _require_geometry(self) -> tuple[CubeFrame, ZAxis]:
        if self._frame is None or self._z is None:
            raise RuntimeError("no slice geometry: choose a source and a resolution first")
        return self._frame, self._z

    def _ensure_plans(self) -> list[LinePlan]:
        """Plan every line against the CURRENT frame and axis.

        Lets `CoverageError` propagate rather than caching a failure: a
        line whose recording window does not cover the z range names
        itself in the message, and spec 9.1 wants the user to act on that
        (shrink the range, or exclude the line) rather than see a slice
        with a line silently missing from it.
        """
        if self._plans is None:
            frame, z = self._require_geometry()
            self._plans = [plan_line(line, frame, z) for line in self._lines]
        return self._plans

    # ---- slices -----------------------------------------------------------
    def _slice(self, window: SliceWindow) -> tuple[np.ndarray, np.ndarray]:
        """One slice, untimed. Used where a redraw timing would be a lie --
        the shared-limit pass takes tens of windows and is not a redraw."""
        frame, z = self._require_geometry()
        if not self._lines:
            raise RuntimeError("no lines are prepared")
        plans = self._ensure_plans()
        if self._mode == "resident":
            cube = self.cube()
            return cube.slice_levels(window.k0, window.k1), cube.coverage()
        return stream_slice(self._lines, plans, frame, z, window.k0, window.k1)

    def slice_at(self, window: SliceWindow) -> tuple[np.ndarray, np.ndarray]:
        """One slice and its coverage, both (ny, nx) in the grid-local frame.

        `values` is NaN where `coverage` is zero -- unfilled, which is
        what the coverage view shows and what `fill` consumes.
        """
        if self._mode == "resident":
            self.cube()  # built outside the timer: a build is not a redraw
        started = time.perf_counter()
        result = self._slice(window)
        self._record_redraw((time.perf_counter() - started) * 1000.0)
        return result

    def _record_redraw(self, ms: float) -> None:
        if self._redraw_ms is None:
            self._redraw_ms = ms
        else:
            self._redraw_ms = _REDRAW_SMOOTHING * self._redraw_ms + (1.0 - _REDRAW_SMOOTHING) * ms

    def shared_limit(self, thickness_levels: int, clip: Any) -> float:
        """One display limit for the whole source, at this thickness.

        Spec 8's shared stretch. Measured over slices at the thickness
        being displayed and never over the raw levels -- see
        `nsgeo.slices.display.shared_limit` for the measurement that makes
        the difference a bug rather than a nuance.
        """
        _, z = self._require_geometry()
        if self._mode == "resident":
            return cube_shared_limit(self.cube(), thickness_levels, clip)
        windows = plan_windows(z, thickness_levels, thickness_levels)
        return limit_over_slices((self._slice(w)[0] for w in windows), clip)

    def cube(self) -> SliceCube:
        """The resident cube, built on first use and cached.

        A latency optimisation, never a capability (spec 7.4) -- every
        caller here works without one. The exporter and the `.npz` writer
        use it because they want the whole volume anyway.
        """
        if self._cube is None:
            frame, z = self._require_geometry()
            plans = self._ensure_plans()
            self._cube = build_cube(self._lines, plans, frame, z, self.provenance())
        return self._cube

    def provenance(self) -> Provenance:
        """What a reader needs to trust the cube.

        `line_keys` comes from the lines that were actually PREPARED, not
        from the lines that were asked for: a line that failed is not in
        the cube, and a provenance that claims it is misleads exactly the
        reader it exists for.
        """
        if self._choice is None:
            raise RuntimeError("no source is chosen")
        site = self.session.site
        steps = tuple(dict(s) for s in site.presets.get(self._choice.preset, []))
        velocity = None
        if self._lines:
            velocity = self.session.resolved_velocity(self._lines[0].key).to_dict()
        return Provenance(
            line_keys=tuple(line.key for line in self._lines),
            preset_name=self._choice.preset,
            steps=steps,
            transform=self._choice.transform or "none",
            velocity=velocity,
            built_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            core_version=nsgeo.__version__,
        )

    def status_text(self) -> str:
        return format_status(self._mode, len(self._lines), self.estimate, self._redraw_ms)

    # ---- lifecycle --------------------------------------------------------
    def clear(self) -> None:
        """Drop the source and everything derived from it."""
        self._generation += 1
        self._choice = None
        self._resolution = None
        self._lines = []
        self._plans = None
        self._frame = None
        self._z = None
        self._cube = None
        self._redraw_ms = None
        self._running = False
        # A large cube's kernel spectra are tens of megabytes and have no
        # reason to outlive the source that needed them.
        clear_kernel_cache()

    def dispose(self) -> None:
        try:
            self.session.site_closed.disconnect(self.clear)
        except (TypeError, RuntimeError):
            pass  # already disconnected, or the C++ side is gone
        self.clear()
        self.on_prepared = None
        self.on_error = None
        self.on_progress = None

    def wait_for_preparation(self, timeout_ms: int = 20_000) -> bool:
        """Spin the event loop until preparation finishes. For tests.

        Returns whether it actually finished while this waited, not merely
        whether nothing is running afterwards -- a bare timeout would
        otherwise read as success.
        """
        if not self._running:
            return True
        loop = QEventLoop()
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        finished = False
        previous = self.on_prepared

        def done() -> None:
            nonlocal finished
            finished = True
            if previous is not None:
                previous()
            loop.quit()

        self.on_prepared = done
        timer.start(timeout_ms)
        loop.exec()
        self.on_prepared = previous
        return finished and not self._running
```

- [ ] **Step 10: Run the engine tests and watch them pass**

Run: `QT_QPA_PLATFORM=offscreen ./.venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py -q -p no:xonsh`
Expected: 11 passed. Then the whole QGIS tier, to confirm nothing regressed: 470 + 11 = 481.

- [ ] **Step 11: Prove the engine tests discriminate**

Three mutants, one at a time, each reverted after:

1. In `_rebuild_geometry`, delete `self._plans = None`. Expect
   `test_changing_the_cell_size_re_plans_every_line` to FAIL (M10's guard raises from
   `stream_slice`). **Record the exact error message** — it is the evidence that the core guard
   and the engine's own invalidation are two independent defences, not one.
2. In `_build_stack`, insert the transform first (`stack.insert(0, build_step(transform))` before
   the preset steps rather than appending). Expect the polarity assert to fire, and
   `test_preparation_applies_the_preset_and_appends_the_transform` to FAIL.
3. In `provenance`, use `self._choice.line_keys` instead of the prepared lines. Confirm
   `test_provenance_names_the_lines_that_were_actually_prepared` still passes (all four prepared)
   — then extend that test with a fifth, deliberately broken line and confirm the mutant FAILS.
   If the extension is awkward, say so in the report and record the mutant as unverified rather
   than claiming a check you did not make.

- [ ] **Step 12: Full verification and commit**

Run all four commands from the Test commands block. Expected: 512+ core+pure / 2 skipped,
481 QGIS, ruff clean, mypy `Success`.

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/slices_engine.py \
        packages/nsgeo-qgis/tests/qgis/test_plugin_slices_engine.py
git commit -m "feat(slices): SliceEngine — preparation, plan cache, residency

Tier 1 on a QgsTask with loader.py's four recorded hazards handled; every
Resolution change drops every LinePlan, which is the defect M10's final
review named as M11's first bug.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push origin nsgeo-m11
```

**Task 2 is done when:** both tiers are green, mypy covers `slices_plan.py` locally and in CI,
and the three engine mutants are recorded.

---

### Task 3: The Slices dock and its Source group

The dock exists, is tabified with Processing, and can choose a grid, a preset, a transform and a
set of lines and prepare them. Nothing displays a slice yet — that is Task 4.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py`
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/line_choice_dialog.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py` (new)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_line_choice_dialog.py` (new)

**Interfaces:**

- Consumes: Task 2's `SliceEngine`, `SourceChoice`, `Resolution`, `transform_names`,
  `preset_transform_conflict`, `estimate_memory`, `format_bytes`, `NO_TRANSFORM`.
- Produces:
  - `SlicesDock(session, parent=None)` — a `QgsDockWidget`, object name `nsgeoSlicesDock`, title
    `nsgeo Slices`. Public: `engine`, `grid_combo`, `preset_combo`, `transform_combo`,
    `choose_button`, `included_label`, `source_status`, `source_choice() -> SourceChoice | None`,
    `set_included(keys)`, `included_keys() -> tuple[str, ...]`, `prepare()`,
    `rebuild_source()`.
  - Signals (both connected in `plugin.py` in this task): `choose_lines_requested = pyqtSignal()`,
    `error = pyqtSignal(str)`.
  - `LineChoiceDialog(session, included, parent=None)` — modeless. Public: `table`,
    `included_keys() -> tuple[str, ...]`, `set_included(key, flag)`, `select_all()`,
    `select_none()`.
  - `plugin.NsgeoPlugin.slices_dock`, `plugin.NsgeoPlugin.open_line_choice_dialog()`.

- [ ] **Step 1: Write the failing dialog tests**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_line_choice_dialog.py`:

```python
"""The contributing-lines table: spec 9.1's one dialog."""

from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.line_choice_dialog import LineChoiceDialog
from plugin_testing import synthetic_dzt

GRID = Grid("A", (500.0, 700.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5)


@pytest.fixture
def peopled(qgis_app, tmp_path):
    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    lines = [
        Line.open(
            synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60),
            GridPlacement("A", "y", 1.0 + i, 0.0, 1, f"L{i}"),
        )
        for i in range(3)
    ]
    session.add_lines(lines)
    return session


def test_every_line_in_the_grid_is_listed_and_included_by_default(peopled):
    dialog = LineChoiceDialog(peopled, included=tuple(peopled.keys()))
    assert dialog.table.rowCount() == 3
    assert dialog.included_keys() == tuple(peopled.keys())


def test_a_line_carrying_its_own_stack_is_marked_as_using_the_preset_instead(peopled):
    """Spec 9.1: a cube built from mixed recipes has no comparable
    amplitudes, and the user should watch that decision being made rather
    than discover it later. The marking is the watching."""
    from nsgeo.processing import build_step

    key = peopled.keys()[1]
    peopled.append_step(key, build_step("dewow"))
    dialog = LineChoiceDialog(peopled, included=tuple(peopled.keys()))
    texts = [
        dialog.table.item(row, dialog.STACK_COLUMN).text() for row in range(dialog.table.rowCount())
    ]
    assert texts[0] == ""
    assert "preset" in texts[1].lower(), texts
    assert texts[2] == ""


def test_excluding_a_line_removes_it_from_the_result_and_keeps_the_order(peopled):
    keys = tuple(peopled.keys())
    dialog = LineChoiceDialog(peopled, included=keys)
    dialog.set_included(keys[1], False)
    assert dialog.included_keys() == (keys[0], keys[2])
    dialog.set_included(keys[1], True)
    assert dialog.included_keys() == keys  # back in survey order, not appended last


def test_select_all_and_none_are_available_because_a_grid_can_hold_forty_lines(peopled):
    dialog = LineChoiceDialog(peopled, included=())
    assert dialog.included_keys() == ()
    dialog.select_all()
    assert len(dialog.included_keys()) == 3
    dialog.select_none()
    assert dialog.included_keys() == ()


def test_the_dialog_is_modeless(peopled):
    """Trap 5: QDialog.exec()'s loop ends the instant the dialog is hidden
    from any cause, so this plugin uses show() plus finished everywhere.
    The qgis-tier conftest forbids exec() outright, so a regression here
    fails rather than hanging the suite."""
    dialog = LineChoiceDialog(peopled, included=())
    assert not dialog.isModal()
```

- [ ] **Step 2: Run and watch them fail.** Expected: no module `line_choice_dialog`.

- [ ] **Step 3: Implement `line_choice_dialog.py`**

```python
"""Which lines go into the cube, and which of them carry their own stack.

Spec 9.1 kept exactly one dialog out of the dock: the contributing lines,
because they need a table and a table does not fit a narrow panel. Grid,
preset and transform are combo boxes in the dock instead -- an earlier
draft put all four behind one `Edit...` button, and review rejected it
because a control named for the act of editing rather than for what it
edits leaves the user to guess its scope.

Modeless, like every dialog in this plugin: `show()` plus `finished`,
never `exec()`. See `plugin.py`'s module docstring for why.
"""

from __future__ import annotations

from typing import Any

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

HEADERS = ("", "Line", "Traces", "Length (m)", "Own stack")


class LineChoiceDialog(QDialog):
    INCLUDE_COLUMN = 0
    STACK_COLUMN = 4

    def __init__(self, session: Any, included: tuple[str, ...], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Lines in this cube")
        self.setModal(False)
        self.session = session
        self._keys: list[str] = list(session.keys()) if session.is_open else []
        self._included: set[str] = {k for k in included if k in set(self._keys)}

        layout = QVBoxLayout(self)
        note = QLabel(
            "Every line contributes through the same preset. A line with its own saved "
            "stack is listed here so the substitution is visible: amplitudes from mixed "
            "recipes are not comparable, which is the whole premise of a slice."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(list(HEADERS))
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

        row = QHBoxLayout()
        self.all_button = QPushButton("Select all")
        self.none_button = QPushButton("Select none")
        row.addWidget(self.all_button)
        row.addWidget(self.none_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        layout.addWidget(self.buttons)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.all_button.clicked.connect(lambda: self.select_all())
        self.none_button.clicked.connect(lambda: self.select_none())
        self.table.itemChanged.connect(self._on_item_changed)
        self._refresh()

    # ---- state ------------------------------------------------------------
    def included_keys(self) -> tuple[str, ...]:
        """The included subset, in survey order -- never in click order.

        Order matters downstream only for readability (provenance,
        progress), but an order that changes when a user unticks and
        re-ticks a row makes two otherwise identical cubes look different
        in their own records."""
        return tuple(k for k in self._keys if k in self._included)

    def set_included(self, key: str, flag: bool) -> None:
        if flag:
            self._included.add(key)
        else:
            self._included.discard(key)
        self._refresh()

    def select_all(self) -> None:
        self._included = set(self._keys)
        self._refresh()

    def select_none(self) -> None:
        self._included = set()
        self._refresh()

    # ---- table ------------------------------------------------------------
    def _refresh(self) -> None:
        self.table.blockSignals(True)
        try:
            self.table.setRowCount(len(self._keys))
            for row, key in enumerate(self._keys):
                line = self.session.line_for_key(key)
                tick = QTableWidgetItem("")
                tick.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                tick.setCheckState(
                    Qt.CheckState.Checked if key in self._included else Qt.CheckState.Unchecked
                )
                tick.setData(Qt.ItemDataRole.UserRole, key)
                self.table.setItem(row, self.INCLUDE_COLUMN, tick)
                label = line.placement.label or key
                length = line.n_traces / max(1e-9, line.header.traces_per_metre)
                has_stack = bool(self.session.site.stacks.get(key))
                for column, text in (
                    (1, str(label)),
                    (2, str(line.n_traces)),
                    (3, f"{length:.1f}"),
                    (4, "using the preset instead" if has_stack else ""),
                ):
                    self.table.setItem(row, column, QTableWidgetItem(text))
        finally:
            self.table.blockSignals(False)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        # A slot on a Qt signal: an exception here is swallowed by PyQt
        # locally and turns into qFatal() in the CI container.
        try:
            if item.column() != self.INCLUDE_COLUMN:
                return
            key = item.data(Qt.ItemDataRole.UserRole)
            if not key:
                return
            self.set_included(str(key), item.checkState() == Qt.CheckState.Checked)
        except Exception:  # noqa: BLE001 -- see above
            from nsgeo_qgis.log import log

            log("could not update the line selection")
```

- [ ] **Step 4: Run and watch them pass.** Expected: 5 passed.

- [ ] **Step 5: Write the failing dock tests**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`:

```python
"""The Slices dock's Source group."""

from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.slices_plan import transform_names
from nsgeo_qgis.ui.slices_dock import SlicesDock
from plugin_testing import synthetic_dzt

GRID = Grid("A", (500.0, 700.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5)
PRESET = [{"step": "dewow", "params": {}, "enabled": True}]


@pytest.fixture
def docked(qgis_app, tmp_path):
    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    lines = [
        Line.open(
            synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60),
            GridPlacement("A", "y", 1.0 + i, 0.0, 1, f"L{i}"),
        )
        for i in range(3)
    ]
    session.add_lines(lines)
    session.site.presets["p"] = list(PRESET)
    session.presets_changed.emit()
    dock = SlicesDock(session)
    yield dock, session
    dock.engine.dispose()
    dock.deleteLater()


def test_the_source_combos_are_filled_from_the_site_not_from_literals(docked):
    dock, session = docked
    assert [dock.grid_combo.itemText(i) for i in range(dock.grid_combo.count())] == ["A"]
    assert "p" in [dock.preset_combo.itemText(i) for i in range(dock.preset_combo.count())]
    offered = [dock.transform_combo.itemText(i) for i in range(dock.transform_combo.count())]
    assert offered[0] == "none"  # spec 6.2 and GPRSLICE's xfrm_method=NONE
    assert offered[1:] == transform_names()


def test_adding_a_preset_updates_the_combo_without_a_reopen(docked):
    dock, session = docked
    session.site.presets["second"] = list(PRESET)
    session.presets_changed.emit()
    assert "second" in [dock.preset_combo.itemText(i) for i in range(dock.preset_combo.count())]


def test_the_included_summary_reads_as_a_fraction_of_the_grid(docked):
    dock, session = docked
    assert dock.included_label.text().startswith("3 of 3 included")
    dock.set_included(tuple(session.keys())[:2])
    assert dock.included_label.text().startswith("2 of 3 included")


def test_the_dock_reports_the_memory_before_committing_to_preparing_it(docked):
    """Spec 9.1: before committing the ~0.9 s the dock reports what the
    resulting memory will be, because it is decided by the line count and
    the chosen resolution -- and spec 7.4 warns rather than hard-caps."""
    dock, _ = docked
    text = dock.included_label.text()
    assert "MB" in text or "GB" in text


def test_choosing_a_preset_that_carries_a_transform_is_refused_visibly(docked):
    """Ruling 2, surfaced. The engine raises; the dock must turn that into
    something the user can read and act on, not let it escape a slot."""
    dock, session = docked
    session.site.presets["bad"] = [{"step": "amp_abs", "params": {}, "enabled": True}]
    session.presets_changed.emit()
    seen: list[str] = []
    dock.error.connect(seen.append)
    dock.preset_combo.setCurrentText("bad")  # re-preparing is what refuses it
    assert any("amp_abs" in msg for msg in seen), seen
    assert "amp_abs" in dock.source_status.text()
    assert not dock.engine.is_prepared


def test_refilling_the_combos_does_not_re_prepare(docked):
    """Refilling a QComboBox emits currentTextChanged. Without the
    _updating guard the dock re-prepares on construction and on every
    grids_changed / lines_changed / presets_changed — ~0.9 s of work per
    unrelated session signal, which IS the "nothing runs automatically"
    the design forbids."""
    dock, session = docked
    dock.prepare()
    assert dock.engine.wait_for_preparation(20_000)
    prepared: list[int] = []
    dock.engine.on_prepared = lambda: prepared.append(1)
    session.site.presets["another"] = list(PRESET)
    session.presets_changed.emit()
    session.lines_changed.emit()
    assert dock.engine.wait_for_preparation(2_000)
    assert prepared == [], "refilling the combos must not have re-prepared"


def test_preparing_reports_progress_and_then_reports_prepared(docked):
    dock, session = docked
    dock.prepare()  # the dock prepares on construction too; this is the retry path
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.engine.is_prepared
    assert dock.engine.line_count == 3
    assert "prepared" in dock.source_status.text().lower()


def test_changing_the_source_re_prepares_it_rather_than_waiting_to_be_asked(docked):
    """Spec 9.1, explicitly: changing the grid, preset or transform
    re-runs the preparation as a QgsTask. That is not a violation of
    "nothing runs automatically" -- the user chose a preset, and
    preparation is the execution of that choice, not an inference about
    it. A prepared source left standing after one of its three inputs
    changed would tell the user the screen matches a choice it does not."""
    dock, session = docked
    dock.prepare()
    assert dock.engine.wait_for_preparation(20_000)
    assert dock.engine.line_count == 3

    session.add_grid(Grid("B", (0.0, 0.0), 0.0, 6.0, 6.0, "EPSG:32616", 0.5))
    dock.grid_combo.setCurrentText("B")  # no explicit prepare() call
    assert dock.engine.wait_for_preparation(20_000)
    # Grid B holds no lines, so the re-preparation really ran and really
    # used the new grid rather than leaving the old result in place.
    assert dock.engine.line_count == 0


def test_closing_the_site_empties_the_dock(docked):
    dock, session = docked
    dock.prepare()
    assert dock.engine.wait_for_preparation(20_000)
    session.close_site()
    assert dock.grid_combo.count() == 0
    assert not dock.engine.is_prepared
```

- [ ] **Step 6: Run and watch them fail.** Expected: no module `slices_dock`.

- [ ] **Step 7: Implement `slices_dock.py` (Source group only)**

The dock is a `QgsDockWidget` titled `nsgeo Slices`, object name `nsgeoSlicesDock`, allowed in the
left and right dock areas. Build it as a `QVBoxLayout` of `QGroupBox`es so Task 4 appends three
more without restructuring; this task creates the **Source** group only.

```python
"""The Slices dock: choosing a source, then navigating the slices it makes.

Tabified with the Processing dock rather than competing for screen space
(spec 9.2) -- a sub-ten-step stack leaves room below it. A separate widget
rather than a tab inside `processing_dock.py`, so it can be torn off to
see both at once, and because issue #21 already records that file as
overloaded.

Four groups, ordered by how often they are touched and what each costs:
Source (~0.9 s, a task), Position (0.6-4 ms), Resolution (44 ms) and
Display (free). This module builds them; it computes nothing. Every number
on screen comes from `slices_plan` or from the engine.
"""
```

Its `__init__` must, in this order:

1. Store `session`; build `self.engine = SliceEngine(session, on_prepared=self._on_prepared,
   on_error=self._on_engine_error, on_progress=self._on_progress)`.
2. Build the Source group: `grid_combo`, `preset_combo`, `transform_combo` (each a `QComboBox` in
   a `QFormLayout` labelled `Grid`, `Preset`, `Transform`), a row holding `included_label`
   (`QLabel`) and `choose_button` (`QPushButton("Choose…")`), and `source_status` (`QLabel`,
   `setWordWrap(True)`).
3. Fill `transform_combo` once with `["none", *transform_names()]`; the other two are rebuilt from
   the session.
4. Connect, in the dock: `choose_button.clicked` → `lambda: self.choose_lines_requested.emit()`
   (a lambda, not the signal's `emit` directly — `clicked` carries a `bool checked` that would be
   passed straight through); `grid_combo.currentTextChanged`, `preset_combo.currentTextChanged`
   and `transform_combo.currentTextChanged` → `self._on_source_changed`; and
   `session.site_opened`, `session.site_closed`, `session.grids_changed`, `session.lines_changed`,
   `session.presets_changed` → `self.rebuild_source`.
5. Call `self.rebuild_source()`.

Behaviour the tests above pin:

- `rebuild_source()` refills `grid_combo` from `session.site.grids` (ids) and `preset_combo` from
  `sorted(session.site.presets)`, preserving the current selection where it still exists, guarded
  by a `self._updating` **depth counter** — not a bool. `processing_dock.py` explains why at
  length: a slot can re-enter `rebuild` while the outer call is still on the stack, and a
  set/clear flag lets the inner call's `finally` clear the guard early.
- `_default_included()` is every line whose `placement.grid_id` is the selected grid, in
  `session.keys()` order. Changing the grid resets the inclusion set to that default, because an
  inclusion list from another grid means nothing here.
- `included_label` reads `f"{len(included)} of {total} included · about {format_bytes(...)}"`,
  the estimate coming from `estimate_memory(sum(line.n_traces * line.header.n_samples for
  included lines), n_cells, nz)` — with `n_cells`/`nz` from the engine's current frame and axis
  when there is one, and `0` before a resolution is set. Say **about**: the count is taken from
  the headers, before `time_zero` crops rows (512 samples against 463 after a four-step preset),
  so it overestimates by roughly a tenth. An honest approximation beats a precise-looking number
  that is wrong in the other direction.
- `_on_source_changed` returns immediately while `self._updating` is non-zero, and otherwise
  calls `self.prepare()`. **The guard is load-bearing, not defensive.** `rebuild_source` refills
  the grid and preset combos, and refilling a `QComboBox` emits `currentTextChanged`; without the
  guard the dock would re-prepare on its own construction and again on every `grids_changed`,
  `lines_changed` and `presets_changed` — roughly 0.9 s of work per unrelated session signal, and
  the one thing "nothing runs automatically" really does forbid. §9.1's auto-preparation is the
  execution of a choice *the user made*; the dock refilling its own combos is not one. Spec 9.1 is explicit that changing the grid, preset
  or transform re-runs the preparation as a `QgsTask`, and equally explicit that this is not the
  "nothing runs automatically" the design forbids: the user chose a preset, and preparation is the
  execution of that choice rather than an inference about it. **Do not add a `Prepare` button.**
  Three rapid combo changes are safe without debouncing because `SliceEngine._generation`
  discards every stale result; a button would be a second way to do the one thing the combos
  already do, and this project has rejected exactly that shape of control before (spec 9.1's
  `Edit…`). `prepare()` stays public as the retry path after a refusal — a fixed preset fires
  `presets_changed`, which `rebuild_source` is already connected to.
- `prepare()` builds a `SourceChoice` from the three combos and the inclusion set and calls
  `engine.set_source(...)` **inside a `try/except ValueError`**, putting the message into both
  `source_status` and the `error` signal. This is the one place Ruling 2's refusal becomes
  visible.
- `_on_progress(done, total)` writes `f"preparing… {done} of {total}"` into `source_status`;
  `_on_prepared()` writes `f"prepared · {engine.line_count} lines"`; `_on_engine_error(msg)`
  writes it and emits `error`.
- Every slot guards its own body with `except Exception` and reports through `error` or
  `nsgeo_qgis.log.log`. An exception escaping a slot passes locally and aborts the CI container.

- [ ] **Step 8: Run and watch them pass.** Expected: 8 passed.

- [ ] **Step 9: Wire the dock into `plugin.py`**

In `initGui`, after the `ProcessingDock` block:

```python
        self.slices_dock = SlicesDock(self.session, main)
        self.slices_dock.error.connect(lambda msg: self.message(msg, Qgis.MessageLevel.Warning))
        self.slices_dock.choose_lines_requested.connect(self.open_line_choice_dialog)
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.slices_dock)
        # Spec 9.2: tabified with Processing rather than a fourth dock
        # competing for screen space. Processing stays the raised tab --
        # this milestone adds a capability, it does not take the screen
        # away from the one people already use.
        main.tabifyDockWidget(self.processing_dock, self.slices_dock)
        self.processing_dock.raise_()
        self.docks.append(self.slices_dock)
```

Add `self.slices_dock: SlicesDock | None = None` and `self._line_choice_dialog: LineChoiceDialog
| None = None` to `__init__`, `self.slices_dock = None` to the dock-clearing block in `unload`,
and — in `unload`, beside the existing `reject()` calls and for the same reasons given there —
`if self._line_choice_dialog is not None: self._line_choice_dialog.reject()`.

Then the modeless opener, following `open_import_dialog` exactly:

```python
    def open_line_choice_dialog(self) -> None:
        """Spec 9.1's one dialog. Modeless, like every dialog here.

        A single tracking slot, so a second `Choose...` does not stack a
        dialog on top of the first; the result is committed on `finished`
        rather than after a blocking call, and the dock is re-read then
        rather than captured now, because the site can change while this
        is open.
        """
        try:
            if self.session is None or not self.session.is_open or self.slices_dock is None:
                return
            if self._line_choice_dialog is not None:
                self._line_choice_dialog.raise_()
                self._line_choice_dialog.activateWindow()
                return
            dock = self.slices_dock
            dialog = LineChoiceDialog(self.session, dock.included_keys(), self.iface.mainWindow())
            self._line_choice_dialog = dialog

            def finished(result: int) -> None:
                try:
                    if result == QDialog.DialogCode.Accepted and self.slices_dock is not None:
                        self.slices_dock.set_included(dialog.included_keys())
                except Exception as exc:  # noqa: BLE001 -- a slot on finished
                    self.message(f"could not apply the line choice: {exc}", Qgis.MessageLevel.Warning)
                finally:
                    self._line_choice_dialog = None
                    dialog.deleteLater()

            dialog.finished.connect(finished)
            dialog.show()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            self.message(f"could not open the line chooser: {exc}", Qgis.MessageLevel.Critical)
```

- [ ] **Step 10: Add the plugin-level tests**

Append to `packages/nsgeo-qgis/tests/qgis/test_plugin_loads.py` (which already builds and unloads
the whole plugin against `fake_iface`):

```python
def test_the_slices_dock_is_tabified_with_processing(fake_iface, qgis_app):
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    try:
        assert plugin.slices_dock is not None
        assert plugin.slices_dock.objectName() == "nsgeoSlicesDock"
        main = fake_iface.mainWindow()
        tabbed = main.tabifiedDockWidgets(plugin.processing_dock)
        assert plugin.slices_dock in tabbed
        # Processing stays the visible tab: M11 adds a capability, it does
        # not take the screen away from the dock people already use.
        assert plugin.processing_dock.visibleRegion is not None
    finally:
        plugin.unload()


def test_unloading_closes_an_open_line_chooser(fake_iface, qgis_app, tmp_path):
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    try:
        plugin.session.new_site(tmp_path)
        plugin.open_line_choice_dialog()
        assert plugin._line_choice_dialog is not None
        dialog = plugin._line_choice_dialog
        plugin.unload()
        # reject(), not close(): closeEvent only calls reject() on a
        # VISIBLE dialog, and this plugin hides dialogs deliberately.
        assert dialog.result() == QDialog.DialogCode.Rejected
    finally:
        if plugin.session is not None:
            plugin.unload()
```

Import `QDialog` from `qgis.PyQt.QtWidgets` in that test file if it is not already imported.

- [ ] **Step 11: Verify and prove discrimination**

Run both tiers. Expected: 481 + ~15 = ~496 QGIS passed; core+pure unchanged.

Mutants, one at a time:

1. In `prepare()`, remove the `try/except ValueError`. Expect
   `test_choosing_a_preset_that_carries_a_transform_is_refused_visibly` to FAIL — and note
   whether it fails as an assertion or via the `_no_swallowed_slot_exceptions` fixture, because
   the second is the fixture doing exactly the job it exists for.
2. In `included_keys()` of the dialog, return `tuple(self._included)` (set order) instead of
   survey order. Expect
   `test_excluding_a_line_removes_it_from_the_result_and_keeps_the_order` to FAIL.
3. Replace `rebuild_source`'s depth counter with a plain bool. Confirm whether any test catches
   it; if none does, say so plainly in the report rather than claiming coverage — the counter is
   defence carried over from `processing_dock.py`, and an honest "not pinned" is worth more than
   a test invented to look like one.

- [ ] **Step 12: Commit and push**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py \
        packages/nsgeo-qgis/nsgeo_qgis/ui/line_choice_dialog.py \
        packages/nsgeo-qgis/nsgeo_qgis/plugin.py packages/nsgeo-qgis/tests/qgis
git commit -m "feat(slices): the Slices dock and its Source group

Tabified with Processing (spec 9.2). Grid, preset and transform are
combos that name what they change; the one dialog is the contributing
lines, which need a table.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push origin nsgeo-m11
```

**Task 3 is done when:** the dock appears tabified with Processing, a source can be chosen and
prepared, a conflicting preset is refused visibly, and both tiers are green.

---

### Task 4: Live navigation — Position, Resolution and Display, and the slice on the map

The milestone's centre. After this task an archaeologist drags a slider and watches the map
redraw, sees the depth window they are actually averaging, sees where there is no data, and sees
what is being held and how fast it is going.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/slice_layer.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` (three more groups)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (own the layer, connect `slice_changed`)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_layer.py` (new)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py` (append)

**Interfaces:**

- Consumes: Task 1's `SliceWindow`, `plan_windows`, `window_label`, `to_north_up`, `fill`;
  Task 2's `SliceEngine`; `nsgeo.render`'s `colormap`, `colormap_names`, `UnipolarClip`,
  `PercentileClip`, `UNIPOLAR_COLORMAPS`; `SiteLayers.group`, `SiteLayers.crs()`.
- Produces:
  - `slice_layer.SliceLayer(session, layers, parent=None)` with `update(values, frame, *, limit,
    colormap_name, unipolar, subtitle)`, `clear()`, `dispose()`, `layer` (the `QgsRasterLayer` or
    `None`), `path` (the scratch GeoTIFF).
  - `slice_layer.build_shader(lut, limit, unipolar) -> QgsRasterShader`
  - `SlicesDock` gains: `slice_slider`, `readout`, `velocity_label`, `thickness_spin`,
    `step_spin`, `cell_spin`, `dz_spin`, `z0_spin`, `z1_spin`, `radius_spin`, `stretch_combo`,
    `palette_combo`, `coverage_check`, `legend_label`, `status_label`; methods `current_window()
    -> SliceWindow | None`, `current_values() -> np.ndarray | None`, `current_frame()`,
    `display_limit() -> float`, `refresh_slice()`, `step_slice(delta)`; signal
    `slice_changed = pyqtSignal()` (connected in `plugin.py` in this task).

---

- [ ] **Step 1: Write the failing `SliceLayer` tests**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_layer.py`:

```python
"""The active slice as a QGIS raster layer."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.render import colormap
from nsgeo.slices import CubeFrame
from nsgeo_qgis.layers import SiteLayers
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.slice_layer import SliceLayer, build_shader
from qgis.core import QgsProject
from qgis.PyQt.QtGui import qAlpha, qRed

FRAME = CubeFrame(origin=(500.0, 700.0), azimuth=0.0, cell=0.5, nx=12, ny=12, crs="EPSG:32616")


@pytest.fixture
def mapped(qgis_app, tmp_path):
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    sl = SliceLayer(session, layers)
    yield sl, session, layers, project
    sl.dispose()
    layers.detach()
    project.clear()


def _values(fill_value=5.0):
    values = np.full((FRAME.ny, FRAME.nx), fill_value, dtype=np.float32)
    values[0, :] = np.nan  # an unsurveyed row
    return values


def test_updating_creates_a_valid_layer_in_the_site_group(mapped):
    sl, _, layers, project = mapped
    sl.update(_values(), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="x")
    assert sl.layer is not None and sl.layer.isValid()
    assert sl.layer.width() == FRAME.nx and sl.layer.height() == FRAME.ny
    assert project.mapLayer(sl.layer.id()) is not None


def test_the_pixel_values_are_the_slice_values_not_a_rendered_picture(mapped):
    """A float raster, so a reader can query an amplitude rather than a
    colour. Spec 9.4 exports float32 with NaN nodata for the same reason."""
    sl, _, _, _ = mapped
    sl.update(_values(7.5), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="")
    provider = sl.layer.dataProvider()
    centre = sl.layer.extent().center()
    value, ok = provider.sample(centre, 1)
    assert ok and value == pytest.approx(7.5)


def test_a_second_update_refreshes_the_pixels_in_place(mapped):
    """The layer is rewritten and reloaded on every tick rather than
    rebuilt, so a drag does not churn the layer tree. Measured: the
    rewrite plus reloadData is ~2.8 ms at 300x300."""
    sl, _, _, _ = mapped
    sl.update(_values(1.0), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="")
    first_id = sl.layer.id()
    sl.update(_values(9.0), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="")
    assert sl.layer.id() == first_id, "the layer must be updated, not replaced"
    value, ok = sl.layer.dataProvider().sample(sl.layer.extent().center(), 1)
    assert ok and value == pytest.approx(9.0)


def test_a_cell_size_change_resizes_the_same_layer(mapped):
    """The cell slider changes nx and ny. Verified directly against this
    GDAL and QGIS: width() and height() follow a reloadData() across a
    shape change, so there is no need to tear the layer down."""
    sl, _, _, _ = mapped
    sl.update(_values(), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="")
    finer = CubeFrame(origin=(500.0, 700.0), azimuth=0.0, cell=0.25, nx=24, ny=24, crs="EPSG:32616")
    sl.update(
        np.full((24, 24), 3.0, np.float32),
        finer,
        limit=10.0,
        colormap_name="amp_heat",
        unipolar=True,
        subtitle="",
    )
    assert (sl.layer.width(), sl.layer.height()) == (24, 24)


def test_nodata_renders_transparent(mapped):
    """The check that actually works. `block.isNoData()` is False on a
    RENDERED block -- the renderer's output is ARGB, so nodata is carried
    by the ALPHA channel, and asserting isNoData here is a false pass
    (verified directly against this build)."""
    sl, _, _, _ = mapped
    sl.update(_values(), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="")
    block = sl.layer.renderer().block(1, sl.layer.extent(), FRAME.nx, FRAME.ny)
    assert qAlpha(block.color(0, 0)) == 0, "the unsurveyed row must be transparent"
    assert qAlpha(block.color(FRAME.ny - 1, 0)) == 255


def test_the_shader_spans_zero_to_limit_for_unipolar_data(mapped):
    """Spec 8: a unipolar table maps 0 to 0 and the limit to 255, instead
    of wasting half the table and putting the data floor at mid-grey."""
    lut = colormap("amp_black_high")
    shader = build_shader(lut, limit=4.0, unipolar=True)
    items = shader.rasterShaderFunction().colorRampItemList()
    assert items[0].value == pytest.approx(0.0)
    assert items[-1].value == pytest.approx(4.0)
    assert (qRed(items[0].color.rgb()), qRed(items[-1].color.rgb())) == (
        int(lut[0, 0]),
        int(lut[255, 0]),
    )


def test_the_shader_spans_minus_limit_to_plus_limit_for_bipolar_data(mapped):
    lut = colormap("seismic")
    shader = build_shader(lut, limit=4.0, unipolar=False)
    items = shader.rasterShaderFunction().colorRampItemList()
    assert items[0].value == pytest.approx(-4.0)
    assert items[-1].value == pytest.approx(4.0)
    middle = items[len(items) // 2]
    assert abs(middle.value) < 0.05  # zero sits in the middle of a bipolar table


def test_disposing_removes_the_layer_and_the_scratch_file(mapped):
    sl, _, _, project = mapped
    sl.update(_values(), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="")
    layer_id = sl.layer.id()
    path = sl.path
    sl.dispose()
    assert project.mapLayer(layer_id) is None
    assert not path.exists()
```

- [ ] **Step 2: Run and watch them fail.** Expected: no module `slice_layer`.

- [ ] **Step 3: Implement `slice_layer.py`**

```python
"""The active slice on the map: a float raster, restyled and reloaded in place.

A real float32 raster with NaN nodata, not a picture. A reader can then
query an amplitude, and the same values go out to the GeoTIFF unchanged --
spec 9.4's reason for exporting float rather than bytes applies just as
well to what is on screen.

Rewritten in place on every tick rather than rebuilt: verified against
this GDAL and QGIS, `reloadData()` refreshes the pixel values, and the
layer's `width()`/`height()` follow even when the cell slider changes the
shape, so a drag never churns the layer tree.

Uncompressed, unlike the export (plan Ruling 3). Measured here at GDAL
3.8.4: `COMPRESS=DEFLATE, PREDICTOR=3` costs 8.8 ms for a 300x300 float
band and 25.2 ms at 600x600, against 1.0 and 1.3 ms uncompressed. Spec
9.5's option set is argued for a file someone keeps; this one lives in a
scratch directory for the length of a session.

That scratch file is also why this layer is a PREVIEW and says so in its
name: it is deliberately outside the project tree, so it cannot be
committed by accident or mistaken for the artefact -- and a saved QGIS
project would find it gone. `slice_export.py` writes the durable one.
"""
```

Key content:

```python
_CREATION_OPTIONS = ["INTERLEAVE=BAND", "TILED=NO", "BIGTIFF=IF_SAFER"]
LAYER_NAME = "Slice (live preview)"


def build_shader(lut: np.ndarray, limit: float, unipolar: bool) -> QgsRasterShader:
    """A 256-stop ramp from a core colour table.

    The core's LUT is the authority on colour, here as in the profile
    view, so the map and the radargram cannot drift apart. All 256 stops
    rather than a subsample: it is rebuilt only when the palette or the
    limit changes, never per tick, and a subsampled ramp would
    interpolate across the non-linear stretch of `amp_heat`.
    """
    lo = 0.0 if unipolar else -float(limit)
    hi = float(limit)
    items = [
        QgsColorRampShader.ColorRampItem(
            lo + (hi - lo) * i / 255.0,
            QColor(int(lut[i, 0]), int(lut[i, 1]), int(lut[i, 2])),
            f"{lo + (hi - lo) * i / 255.0:.3f}",
        )
        for i in range(256)
    ]
    function = QgsColorRampShader()
    function.setColorRampType(QgsColorRampShader.Type.Interpolated)
    function.setColorRampItemList(items)
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(function)
    return shader
```

`SliceLayer.__init__` takes `(session, layers, parent=None)`, makes
`self._dir = Path(tempfile.mkdtemp(prefix="nsgeo-slice-"))` and `self.path = self._dir /
"slice.tif"`, and sets `self.layer = None`.

`update(values, frame, *, limit, colormap_name, unipolar, subtitle)` must:

1. `array, geotransform = to_north_up(values, frame)` — the one resample, from core.
2. Write `array` to `self.path` with `_CREATION_OPTIONS`, `gdal.GDT_Float32`, the geotransform,
   the frame's CRS as WKT (`QgsCoordinateReferenceSystem(frame.crs).toWkt()`), and
   `SetNoDataValue(float("nan"))`. **Hold the `gdal.Dataset` in a local and set it to `None`
   before returning** — GDAL flushes on destruction, and a dataset garbage-collected mid-expression
   is a real trap (it bit the spike that produced this plan's measurements).
3. If `self.layer is None`, create `QgsRasterLayer(str(self.path), LAYER_NAME, "gdal")`, add it to
   the project **without** adding it to the legend root
   (`project.addMapLayer(layer, addToLegend=False)`), then insert it into `layers.group` if that
   group exists, so it joins the site's layer group like every other layer here. Otherwise call
   `self.layer.dataProvider().reloadData()`.
4. Apply a `QgsSingleBandPseudoColorRenderer(provider, 1, build_shader(colormap(colormap_name),
   limit, unipolar))` with `setClassificationMin`/`Max` matching the shader's ends, but **only
   when `(colormap_name, limit, unipolar)` changed since the last update** — rebuilding 256 stops
   on every tick of the depth slider is waste, and the renderer is what makes the layer flicker
   if replaced needlessly.
5. `self.layer.setCustomProperty("nsgeo/window", subtitle)` and
   `self.layer.setAbstract(subtitle)`, so the window a layer shows is recorded on the layer
   itself rather than only in the dock.
6. `self.layer.triggerRepaint()`.

`clear()` removes the layer from the project and sets `self.layer = None`.
`dispose()` calls `clear()` then `shutil.rmtree(self._dir, ignore_errors=True)`.

Guard every public method body with `except Exception` reporting through `nsgeo_qgis.log.log` —
`update` is reached from a slider slot.

- [ ] **Step 4: Run and watch them pass.** Expected: 8 passed.

- [ ] **Step 5: Write the failing dock-navigation tests**

Append to `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`:

```python
def _ready(dock):
    dock.prepare()
    assert dock.engine.wait_for_preparation(20_000)
    dock.z0_spin.setValue(2.0)
    dock.z1_spin.setValue(30.0)
    dock.dz_spin.setValue(0.5)
    dock.cell_spin.setValue(0.25)
    dock.flush_debounce()  # applies the pending Resolution change immediately


def test_the_readout_states_the_window_that_was_actually_averaged(docked):
    """Spec 9.2: the control that moves the window and the statement of
    where the window now is are one unit, read together on every tick.
    Spec 6.6: always the full range, never the centre -- with overlapping
    slices, the extent of what is averaged is the thing a reader would
    otherwise mistake for vertical resolution."""
    dock, _ = docked
    _ready(dock)
    dock.thickness_spin.setValue(4.0)
    dock.slice_slider.setValue(10)
    text = dock.readout.text()
    window = dock.current_window()
    assert window is not None
    lo, hi = window_times_ns(dock.engine.z, window)
    assert f"{lo:.1f}" in text and f"{hi:.1f}" in text
    assert "ns" in text
    assert "/" in text and "slice" in text  # "slice 14 / 40"


def test_the_readout_shrinks_with_the_window_at_the_end_of_the_axis(docked):
    """Trap 3. At either end `ZAxis.level_range` returns a genuinely
    thinner window than asked for, and spec 6.6 requires the readout to
    show what was actually averaged. A readout rebuilt from the slider
    position plus the thickness spin box claims a window the axis
    refused."""
    dock, _ = docked
    _ready(dock)
    dock.thickness_spin.setValue(8.0)
    dock.slice_slider.setValue(dock.slice_slider.maximum())
    window = dock.current_window()
    lo, hi = window_times_ns(dock.engine.z, window)
    assert hi <= dock.engine.z.t_end_ns + 1e-9
    assert hi - lo < 8.0  # thinner than requested, and the readout says so
    assert f"{hi:.1f}" in dock.readout.text()


def test_moving_the_slider_emits_slice_changed_and_changes_the_values(docked):
    dock, _ = docked
    _ready(dock)
    seen: list[int] = []
    dock.slice_changed.connect(lambda: seen.append(1))
    dock.slice_slider.setValue(4)
    first = dock.current_values().copy()
    dock.slice_slider.setValue(30)
    second = dock.current_values()
    assert len(seen) >= 2
    both = np.isfinite(first) & np.isfinite(second)
    assert both.any()
    assert not np.allclose(first[both], second[both]), "a different depth must look different"


def test_the_fill_radius_is_metres_and_survives_a_cell_size_change(docked):
    """Spec 6.4's default is 1.5 x the line spacing -- a distance. The
    spin box is therefore in metres and the cell conversion happens
    underneath, so halving the cell size does not silently halve the
    smoothing."""
    dock, session = docked
    _ready(dock)
    assert dock.radius_spin.value() == pytest.approx(1.5 * GRID.default_spacing)
    before = dock.radius_cells()
    dock.cell_spin.setValue(0.125)
    dock.flush_debounce()
    assert dock.radius_spin.value() == pytest.approx(1.5 * GRID.default_spacing)
    assert dock.radius_cells() == pytest.approx(before * 2, abs=1)


def test_filling_reaches_between_the_lines_and_zero_radius_does_not(docked):
    """Spec 6.4: at realistic spacing about 80% of cells are empty, so the
    fill is most of the picture rather than a nicety."""
    dock, _ = docked
    _ready(dock)
    dock.radius_spin.setValue(0.0)
    dock.flush_debounce()
    unfilled = np.isfinite(dock.current_values()).sum()
    dock.radius_spin.setValue(1.0)
    dock.flush_debounce()
    filled = np.isfinite(dock.current_values()).sum()
    assert filled > unfilled


def test_the_coverage_toggle_shows_trace_counts_not_amplitudes(docked):
    """Spec 3: a zero that means 'no data' reading as 'no reflection' is
    the defect a count array exists to fix, and the coverage view is where
    a user sees it."""
    dock, _ = docked
    _ready(dock)
    dock.coverage_check.setChecked(True)
    coverage = dock.current_values()
    assert np.nanmax(coverage) >= 1.0
    assert np.allclose(coverage[np.isfinite(coverage)] % 1.0, 0.0), "counts are whole traces"
    dock.coverage_check.setChecked(False)
    assert not np.allclose(
        np.nan_to_num(dock.current_values()), np.nan_to_num(coverage)
    )


def test_a_shared_stretch_holds_one_limit_across_depth_and_per_slice_does_not(docked):
    """Spec 8: comparability by default, legibility on demand."""
    dock, _ = docked
    _ready(dock)
    dock.stretch_combo.setCurrentText("shared across the cube")
    dock.slice_slider.setValue(4)
    shallow = dock.display_limit()
    dock.slice_slider.setValue(40)
    deep = dock.display_limit()
    assert shallow == pytest.approx(deep)

    dock.stretch_combo.setCurrentText("this slice")
    dock.slice_slider.setValue(4)
    shallow_own = dock.display_limit()
    dock.slice_slider.setValue(40)
    deep_own = dock.display_limit()
    assert shallow_own != pytest.approx(deep_own)


def test_the_palette_offers_unipolar_tables_for_a_transformed_source(docked):
    """Spec 8's rule: a bipolar table on unipolar data is a configuration
    error, not a style choice. The combo is where that rule is enforced."""
    dock, _ = docked
    _ready(dock)
    offered = [dock.palette_combo.itemText(i) for i in range(dock.palette_combo.count())]
    assert set(offered) == set(colormap_names(unipolar=True))
    assert "seismic" not in offered

    dock.transform_combo.setCurrentText("none")  # re-prepares on its own (spec 9.1)
    assert dock.engine.wait_for_preparation(20_000)
    offered = [dock.palette_combo.itemText(i) for i in range(dock.palette_combo.count())]
    assert set(offered) == set(colormap_names(unipolar=False))
    assert "amp_heat" not in offered


def test_the_status_line_reports_what_is_held_and_how_fast(docked):
    dock, _ = docked
    _ready(dock)
    dock.slice_slider.setValue(8)
    text = dock.status_label.text()
    assert "lines held in memory" in text
    assert "slices redraw in" in text


def test_a_resolution_change_is_debounced_into_one_rebuild(docked):
    """Spec 7.2 and trap 4: a rebuild is 44 ms and even the improved fill
    is 32 ms at 600x600, so a slider emitting per-step would queue work
    faster than it can finish."""
    dock, _ = docked
    _ready(dock)
    rebuilds: list[int] = []
    dock.slice_changed.connect(lambda: rebuilds.append(1))
    for value in (0.2, 0.3, 0.4, 0.5):
        dock.cell_spin.setValue(value)
    assert rebuilds == [], "nothing should have rebuilt while the value was still moving"
    dock.flush_debounce()
    assert len(rebuilds) == 1
```

Add the imports these need at the top of the file: `numpy as np`,
`from nsgeo.render import colormap_names`, `from nsgeo.slices import window_times_ns`.

- [ ] **Step 6: Run and watch them fail.**

- [ ] **Step 7: Implement the three remaining groups**

Append to `slices_dock.py`. Requirements, in the order the tests pin them:

**Position group.** `slice_slider` is a horizontal `QSlider` over `0..nz-1` — it *is* the top of
the window, and there is no "Top" field (spec 9.2). Directly beneath it, in the same group and
with no other widget between, `readout` (a `QLabel`), then `velocity_label` in a smaller, dimmer
font — the velocity is provenance, not state. `thickness_spin` and `step_spin` are
`QDoubleSpinBox`es in nanoseconds, suffix `" ns"`, `thickness_spin` defaulting to `5.0` and
`step_spin` to half of it (spec 6.6's 50% overlap default, with its reason: a reflector on a
boundary is halved in both neighbours).

`current_window()` is:

```python
    def current_window(self) -> SliceWindow | None:
        z = self.engine.z
        if z is None:
            return None
        top_ns = z.t0_ns + self.slice_slider.value() * z.dz_ns
        k0, k1 = z.level_range(top_ns, max(z.dz_ns, self.thickness_spin.value()))
        return SliceWindow(k0, k1)
```

and `readout` is built from `window_label(z, window, velocity)` prefixed with
`f"slice {index + 1} / {total} · "`, where `index`/`total` come from
`plan_windows(z, window.n_levels, step_levels)`. **Never** rebuild the label from
`self.slice_slider.value()` and `self.thickness_spin.value()` — that is trap 3, and
`test_the_readout_shrinks_with_the_window_at_the_end_of_the_axis` exists to catch it.

**Resolution group.** `cell_spin` (m, 0.01–5.0, default `min(0.5, grid.default_spacing / 2)` —
spec 4's convention: no smaller than the trace spacing, no larger than half the line spacing),
`dz_spin` (ns, default the grid's first line's native `dt`), `z0_spin`/`z1_spin` (ns), and
`radius_spin` (**metres**, default `1.5 * grid.default_spacing`, spec 6.4). `radius_cells()` is
`max(0, int(round(radius_spin.value() / cell_spin.value())))`.

All five go through one debounce:

```python
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(120)
        self._debounce.timeout.connect(self._apply_resolution)
```

with every Resolution widget's `valueChanged` connected to `self._debounce.start` and a public
`flush_debounce()` that stops the timer and calls `_apply_resolution()` directly — tests use it,
and so does anything that needs the current geometry now. `_apply_resolution` builds a
`Resolution`, calls `engine.set_resolution(...)`, re-ranges `slice_slider` to `0..nz-1` keeping
the nearest equivalent time, invalidates the cached shared limit, and calls `refresh_slice()`.

**Display group.** `stretch_combo` with exactly `["shared across the cube", "this slice"]`;
`palette_combo` refilled from `colormap_names(unipolar=engine.output_unipolar)` whenever the
source is prepared, defaulting to `"amp_black_high"` when unipolar and to `DEFAULT_COLORMAP`
otherwise; `coverage_check` (`QCheckBox("Show coverage")`); `legend_label` reading
`f"0 – {limit:.3g}"` (or `f"−{limit:.3g} – {limit:.3g}"` when bipolar) with the transform's name,
so the number on screen has a stated meaning. Then `status_label` below the groups,
`setWordWrap(True)`, fed from `engine.status_text()`.

**`refresh_slice()`** is the one path everything funnels through:

```python
    def refresh_slice(self) -> None:
        try:
            window = self.current_window()
            if window is None or not self.engine.is_prepared:
                self._values = None
                return
            values, coverage = self.engine.slice_at(window)
            if self.coverage_check.isChecked():
                shown = coverage.astype(float)
                shown[coverage == 0] = np.nan
            else:
                shown = fill(values, coverage, self.radius_cells())
            self._values = shown
            self._window = window
            self._update_readout(window)
            self.status_label.setText(self.engine.status_text())
            self.slice_changed.emit()
        except Exception as exc:  # noqa: BLE001 -- reached from slider slots; an
            # escape passes locally and aborts the CI container.
            self.error.emit(str(exc))
```

**`display_limit()`** returns the cached shared limit when `stretch_combo` is on
`"shared across the cube"`, recomputing it through `engine.shared_limit(window.n_levels, clip)`
only when the thickness, the source or the mode changed; and `clip.limit(self._values)` when on
`"this slice"`. `clip` is `UnipolarClip()` when `engine.output_unipolar` and `PercentileClip()`
otherwise.

**`step_slice(delta)`** moves `slice_slider` by `delta * step_levels`, clamped — the unit that
makes a step a *step* rather than a level.

- [ ] **Step 8: Run and watch them pass.** Expected: ~10 more dock tests green.

- [ ] **Step 9: Wire the layer into `plugin.py`**

In `initGui`, after the Slices dock block:

```python
        self.slice_layer = SliceLayer(self.session, self.layers)
        self.slices_dock.slice_changed.connect(self._on_slice_changed)
```

and the handler, guarded like every other slot here:

```python
    def _on_slice_changed(self) -> None:
        try:
            dock, layer = self.slices_dock, self.slice_layer
            if dock is None or layer is None:
                return
            values, frame = dock.current_values(), dock.current_frame()
            if values is None or frame is None:
                layer.clear()
                return
            layer.update(
                values,
                frame,
                limit=dock.display_limit(),
                colormap_name=dock.palette_combo.currentText(),
                unipolar=dock.engine.output_unipolar,
                subtitle=dock.readout.text(),
            )
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            self.message(f"could not draw the slice: {exc}", Qgis.MessageLevel.Warning)
```

Add `self.slice_layer: SliceLayer | None = None` to `__init__`, and in `unload`, **before**
`self.layers.detach()`, `if self.slice_layer is not None: self.slice_layer.dispose();
self.slice_layer = None` — outside-in, the same ordering the existing `map_link.dispose()` call
documents.

- [ ] **Step 10: Verify and prove discrimination**

Run both tiers, ruff and mypy. Then four mutants, one at a time:

1. `current_window()` → build the label from `slice_slider.value()` and `thickness_spin.value()`
   instead of from `(k0, k1)`. Expect
   `test_the_readout_shrinks_with_the_window_at_the_end_of_the_axis` to FAIL.
2. `radius_cells()` → return `int(self.radius_spin.value())` (metres read as cells). Expect
   `test_the_fill_radius_is_metres_and_survives_a_cell_size_change` to FAIL.
3. `display_limit()` → always `clip.limit(self._values)` (per-slice, ignoring the combo). Expect
   `test_a_shared_stretch_holds_one_limit_across_depth_and_per_slice_does_not` to FAIL.
4. `build_shader` → `lo = -limit` unconditionally. Expect
   `test_the_shader_spans_zero_to_limit_for_unipolar_data` to FAIL — this is spec 8's wasted half
   table, the defect the whole unipolar path exists for.

Also record, by timing it, how long one `refresh_slice()` takes at the default resolution on the
synthetic fixture, and confirm it is in the single-digit milliseconds.

- [ ] **Step 11: Commit and push**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis packages/nsgeo-qgis/tests/qgis
git commit -m "feat(slices): live navigation and the slice on the map

Position, Resolution and Display; a float raster rewritten and reloaded
in place; coverage; the shared stretch. The readout is derived from the
level range that was actually averaged, never from the request.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push origin nsgeo-m11
```

**Task 4 is done when:** dragging the depth slider redraws the map layer, the readout tracks the
real window, coverage and fill both work, the status line is live, and both tiers are green.

---

### Task 5: Reading the slice — the band on the radargram, and shift + scroll

§9.3's one new thing, and the navigation gesture users of other packages already have. The band
is what answers *is this anomaly real, or is the fill inventing a feature between two lines?* —
by pointing at it.

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` (two signals, one method)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py` (`depth_scroll_delta`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (wire both)
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py` (append)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py` (append)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py` (append)

**Interfaces:**

- Produces:
  - `ProfileView.set_slice_band(lo_ns: float, hi_ns: float)`, `ProfileView.clear_slice_band()`,
    `ProfileView._slice_band_bounds(t) -> tuple[float, float] | None`
  - `ProfileDock.set_slice_band(lo_ns, hi_ns)`, `ProfileDock.clear_slice_band()`
  - `SlicesDock.window_changed = pyqtSignal(float, float)`,
    `SlicesDock.window_cleared = pyqtSignal()` (both connected in `plugin.py` here)
  - `slices_plan.depth_scroll_delta(angle_delta_y: int, shift_held: bool) -> int`
  - `slices_dock.CanvasDepthScroll(canvas, dock, parent=None)` with `dispose()`

---

- [ ] **Step 1: The pure scroll rule, test first**

Append to `packages/nsgeo-qgis/tests/pure/test_pure_slices_plan.py`:

```python
def test_shift_scroll_steps_deeper_downward_and_is_inert_without_shift():
    """Spec 9.2: shift + scroll on the canvas cycles depth, which is the
    convention users of other packages already have. The direction is the
    one the world uses -- scrolling down goes deeper -- and the rule is a
    plain function so it is pinned without synthesising a Qt event, whose
    constructor signature differs between Qt 5 and Qt 6."""
    from nsgeo_qgis.slices_plan import depth_scroll_delta

    assert depth_scroll_delta(-120, shift_held=True) == 1  # down: deeper
    assert depth_scroll_delta(120, shift_held=True) == -1  # up: shallower
    assert depth_scroll_delta(-120, shift_held=False) == 0  # plain scroll is a map zoom
    assert depth_scroll_delta(0, shift_held=True) == 0  # a horizontal-only wheel
```

Implement in `slices_plan.py`:

```python
def depth_scroll_delta(angle_delta_y: int, shift_held: bool) -> int:
    """-1, 0 or +1 slice steps for one wheel event.

    Kept here, away from Qt, for two reasons: the plugin's boundary rule
    keeps arithmetic out of widgets, and `QWheelEvent`'s constructor
    differs between Qt 5 and Qt 6, so a rule pinned only through a
    synthesised event would be pinned only on one of them.

    Without shift this returns 0 and the event is not consumed: plain
    scrolling stays the map's zoom, because spec 9.3 is explicit that the
    slice introduces no new tool and takes no gesture away.
    """
    if not shift_held or angle_delta_y == 0:
        return 0
    return 1 if angle_delta_y < 0 else -1
```

- [ ] **Step 2: Write the failing band tests**

Append to `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py` (matching its existing
fixtures for building a view with axes):

```python
def test_the_slice_band_spans_the_windows_time_range(qgis_app):
    view = ProfileView()
    view.resize(400, 300)
    view.set_axes(n_traces=100, n_samples=200, t0_ns=0.0, dt_ns=0.5)
    view.set_slice_band(20.0, 30.0)
    bounds = view._slice_band_bounds(view.transform)
    assert bounds is not None
    y0, y1 = bounds
    assert y0 == pytest.approx(view.transform.y_of_time(20.0))
    assert y1 == pytest.approx(view.transform.y_of_time(30.0))
    assert y1 > y0


def test_a_single_level_window_still_draws_a_visible_band(qgis_app):
    """A one-level window averages a single sample and so has zero time
    extent -- which is the truth, and a zero-height rectangle no user can
    see. The data stays honest; the PAINTER enforces a floor."""
    view = ProfileView()
    view.resize(400, 300)
    view.set_axes(n_traces=100, n_samples=200, t0_ns=0.0, dt_ns=0.5)
    view.set_slice_band(20.0, 20.0)
    y0, y1 = view._slice_band_bounds(view.transform)
    assert y1 - y0 >= 2.0


def test_clearing_the_band_removes_it(qgis_app):
    view = ProfileView()
    view.resize(400, 300)
    view.set_axes(n_traces=100, n_samples=200, t0_ns=0.0, dt_ns=0.5)
    view.set_slice_band(20.0, 30.0)
    view.clear_slice_band()
    assert view._slice_band_bounds(view.transform) is None


def test_painting_with_a_band_raises_nothing(qgis_app):
    """paintEvent is a Qt-invoked virtual: an escaping exception leaves
    the QPainter bound to the widget and the NEXT repaint segfaults the
    process -- measured, not theorised (see the module docstring's C1)."""
    view = ProfileView()
    view.resize(400, 300)
    view.set_axes(n_traces=100, n_samples=200, t0_ns=0.0, dt_ns=0.5)
    view.set_slice_band(-50.0, 500.0)  # a window entirely outside the view
    view.grab_image()
    view.set_slice_band(20.0, 30.0)
    view.grab_image()
```

- [ ] **Step 3: Implement the band in `profile_view.py`**

Add a module-level colour beside the existing ones:

```python
# Spec 9.3's one overlay. Distinct from SELECTION_COLOUR, which is a
# vertical trace range: these two can be on screen together and must not
# read as the same thing.
SLICE_BAND_COLOUR = QColor(80, 200, 255, 48)
SLICE_BAND_EDGE = QColor(80, 200, 255, 170)
MIN_BAND_PX = 2.0
```

In `__init__`, `self._slice_band: tuple[float, float] | None = None`. Then:

```python
    def set_slice_band(self, lo_ns: float, hi_ns: float) -> None:
        """Draw the active slice's time window across this radargram.

        Spec 9.3: the only new thing the slice adds to the profile view.
        It answers "is this anomaly real, or is the fill inventing a
        feature between two lines?" by pointing at the depths the slice
        averaged, on data that was never filled.
        """
        if not all(math.isfinite(v) for v in (lo_ns, hi_ns)):
            self._slice_band = None
        else:
            self._slice_band = (min(lo_ns, hi_ns), max(lo_ns, hi_ns))
        self.update()

    def clear_slice_band(self) -> None:
        self._slice_band = None
        self.update()

    def _slice_band_bounds(self, t: ViewTransform) -> tuple[float, float] | None:
        """Local (unoffset) y-bounds of the band, or None when there is
        none. Factored out the same way `_selection_bounds` is, and for
        the same reason: a plain pair a test can assert on without
        rendering a pixel.

        A one-level window has zero time extent -- it averages a single
        sample, and saying otherwise would overstate what was averaged --
        so the floor is applied HERE, in pixels, rather than by widening
        the window the readout reports.
        """
        if self._slice_band is None:
            return None
        y0 = t.y_of_time(self._slice_band[0])
        y1 = t.y_of_time(self._slice_band[1])
        if y1 - y0 < MIN_BAND_PX:
            centre = (y0 + y1) / 2.0
            y0, y1 = centre - MIN_BAND_PX / 2.0, centre + MIN_BAND_PX / 2.0
        return y0, y1

    def _paint_slice_band(self, p: QPainter, r: QRect, t: ViewTransform) -> None:
        bounds = self._slice_band_bounds(t)
        if bounds is None:
            return
        y0, y1 = r.top() + bounds[0], r.top() + bounds[1]
        p.fillRect(QRectF(r.left(), y0, r.width(), y1 - y0), SLICE_BAND_COLOUR)
        p.setPen(QPen(SLICE_BAND_EDGE, 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(r.left(), y0), QPointF(r.right(), y0))
        p.drawLine(QPointF(r.left(), y1), QPointF(r.right(), y1))
```

Call it in `paintEvent` inside the existing `setClipRect(r)` block, **before**
`_paint_selection` — the band is context and must sit under the selection and the picks, not over
them. Add `self._slice_band = None` to `clear()`.

In `profile_dock.py`, two relays, each guarded, and each calling straight through to the view:

```python
    def set_slice_band(self, lo_ns: float, hi_ns: float) -> None:
        self.view.set_slice_band(lo_ns, hi_ns)

    def clear_slice_band(self) -> None:
        self.view.clear_slice_band()
```

- [ ] **Step 4: Emit the window from the Slices dock and wire it**

In `slices_dock.py`, declare beside `slice_changed`:

```python
    window_changed = pyqtSignal(float, float)  # (lo_ns, hi_ns) of the averaged window
    window_cleared = pyqtSignal()
```

and in `refresh_slice()`, right after `self._update_readout(window)`:

```python
            lo_ns, hi_ns = window_times_ns(self.engine.z, window)
            self.window_changed.emit(lo_ns, hi_ns)
```

with `self.window_cleared.emit()` on the early-return branch where there is no window. Add
`CanvasDepthScroll` to the same module:

```python
class CanvasDepthScroll(QObject):
    """Shift + scroll on the map canvas cycles depth (spec 9.2).

    An event filter rather than a map tool: spec 9.3 is explicit that the
    slice introduces no new tool, and taking over the canvas would break
    the ambient hover and the Select-to-promote gesture M7 already built.
    Without shift the event is not consumed, so plain scrolling remains
    the map's zoom.

    `eventFilter` is a Qt-invoked virtual, the same hazard class as
    `paintEvent`: an exception escaping it is swallowed locally and
    reaches `qFatal()` in the CI container, so the body is guarded.
    """

    def __init__(self, canvas: Any, dock: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._canvas = canvas
        self._dock = dock
        canvas.viewport().installEventFilter(self)

    def eventFilter(self, obj: Any, event: Any) -> bool:  # noqa: N802
        try:
            if event.type() != QEvent.Type.Wheel:
                return False
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            delta = depth_scroll_delta(int(event.angleDelta().y()), shift)
            if delta == 0:
                return False
            self._dock.step_slice(delta)
            return True  # consumed: the map must not also zoom
        except Exception as exc:  # noqa: BLE001 -- see the class docstring
            _log(f"could not step the slice from the canvas: {exc}")
            return False

    def dispose(self) -> None:
        try:
            if self._canvas is not None and not sip.isdeleted(self._canvas):
                self._canvas.viewport().removeEventFilter(self)
        except (RuntimeError, AttributeError):
            pass
        self._canvas = None
        self._dock = None
```

In `plugin.py`'s `initGui`, after the slice layer:

```python
        self.slices_dock.window_changed.connect(self.profile_dock.set_slice_band)
        self.slices_dock.window_cleared.connect(self.profile_dock.clear_slice_band)
        self.depth_scroll = CanvasDepthScroll(self.iface.mapCanvas(), self.slices_dock)
```

with `self.depth_scroll: CanvasDepthScroll | None = None` in `__init__` and, in `unload`, before
the docks are removed: `if self.depth_scroll is not None: self.depth_scroll.dispose();
self.depth_scroll = None`.

- [ ] **Step 5: Write the failing wiring tests**

Append to `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`:

```python
def test_moving_the_slider_announces_the_window_it_averaged(docked):
    dock, _ = docked
    _ready(dock)
    seen: list[tuple[float, float]] = []
    dock.window_changed.connect(lambda lo, hi: seen.append((lo, hi)))
    dock.thickness_spin.setValue(4.0)
    dock.slice_slider.setValue(12)
    assert seen
    lo, hi = seen[-1]
    window = dock.current_window()
    assert (lo, hi) == pytest.approx(window_times_ns(dock.engine.z, window))


def test_step_slice_moves_by_the_step_not_by_one_level(docked):
    """Spec 6.6: thickness and step answer different questions. Stepping
    by one level would make shift+scroll take dozens of turns to cross a
    slice at native dz."""
    dock, _ = docked
    _ready(dock)
    dock.thickness_spin.setValue(5.0)
    dock.step_spin.setValue(2.5)
    start = dock.slice_slider.value()
    dock.step_slice(1)
    moved = dock.slice_slider.value() - start
    assert moved == round(2.5 / dock.engine.z.dz_ns)
    assert moved > 1
```

And to `test_plugin_loads.py`:

```python
def test_the_profile_band_follows_the_slice_window(fake_iface, qgis_app, tmp_path):
    """The one thing spec 9.3 adds to the profile view, end to end through
    the plugin's own wiring rather than by calling the dock directly."""
    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    try:
        plugin.slices_dock.window_changed.emit(12.0, 16.0)
        assert plugin.profile_dock.view._slice_band == (12.0, 16.0)
        plugin.slices_dock.window_cleared.emit()
        assert plugin.profile_dock.view._slice_band is None
    finally:
        plugin.unload()
```

- [ ] **Step 6: Run both tiers, and prove discrimination**

Mutants:

1. `_paint_slice_band` called AFTER `_paint_picks`. No test catches ordering — say so in the
   report rather than inventing one; it is a visual judgement, and the manual walkthrough is
   where it is checked.
2. `depth_scroll_delta` → `return 1 if angle_delta_y > 0 else -1` (inverted). Expect the pure
   test to FAIL.
3. `_slice_band_bounds` → drop the `MIN_BAND_PX` floor. Expect
   `test_a_single_level_window_still_draws_a_visible_band` to FAIL.
4. `set_slice_band` → do not guard against non-finite input. Feed it `float("nan")` in a scratch
   check and confirm `grab_image()` then logs rather than raising; if the guard is genuinely
   unreachable from the dock, record that and keep the guard, since `paintEvent` is the one place
   where an escape is a process hazard rather than a nuisance.

- [ ] **Step 7: Commit and push**

```bash
git add packages/nsgeo-qgis
git commit -m "feat(slices): the slice window drawn on the radargram, and shift+scroll

Spec 9.3's one overlay: what answers whether an anomaly is real or the
fill inventing a feature between two lines. The scroll rule is a pure
function, so it is pinned without a Qt-version-specific event.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push origin nsgeo-m11
```

---

### Task 6: Export — the multi-band GeoTIFF, the `.npz`, and the survey record

The milestone's last mile: what leaves the plugin and what a rebuild reads.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` (two buttons)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (the two file dialogs)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export.py` (new)
- Test: `packages/nsgeo-core/tests/test_project.py` (append: the `cubes` record shape)

**Interfaces:**

- Produces:
  - `SliceBand(window: SliceWindow, description: str)`
  - `ExportPlan(frame, z, crs, bands: tuple[SliceBand, ...], provenance)`
  - `plan_export(engine, thickness_levels, step_levels, velocity) -> ExportPlan`
  - `GeoTiffSliceWriter` with `OPTIONS` and
    `write(path, plan, slices: Iterable[np.ndarray]) -> None`
  - `band_time_range(lo_ns, hi_ns) -> QgsDateTimeRange`
  - `apply_temporal_properties(layer, plan) -> None`
  - `export_slices(engine, path, thickness_levels, step_levels, velocity, radius_cells) -> ExportPlan`
  - `write_coverage(engine, path) -> None`
  - `save_cube_npz(engine, path) -> Path`
  - `ViewSettings(thickness_ns, step_ns, radius_m, palette, stretch, coverage)` with
    `to_dict()` / `from_dict()`
  - `cube_record(session, choice, frame, z, view, npz_path) -> dict[str, Any]`
  - `SlicesDock.save_button`, `SlicesDock.export_button`, signals
    `save_cube_requested = pyqtSignal()` and `export_requested = pyqtSignal()` (connected in
    `plugin.py` here)

---

- [ ] **Step 1: Write the failing export tests**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export.py`. The fixture is Task 2's
`sourced` fixture, copied into this file (a prepared engine over four synthetic lines) plus a
resolution. The tests:

```python
def test_the_band_count_is_the_specs_formula(exportable):
    """Spec 9.4: n_bands = (z_range - thickness) / step + 1. Halving the
    step doubles the file, and that is the moment the (thickness, step)
    pair stops being continuous exploration and becomes a finite set."""
    engine = exportable
    plan = plan_export(engine, thickness_levels=10, step_levels=5, velocity=None)
    nz = engine.z.nz
    assert len(plan.bands) == (nz - 10) // 5 + 1


def test_every_band_describes_the_window_it_averages_in_both_units(exportable, tmp_path):
    """Spec 9.4: a reader opening the GeoTIFF in five years can see that
    band 7 is 15.0-20.0 ns and band 8 is 17.5-22.5 ns, and that they
    therefore share half their data. The description is the only place
    that survives outside this plugin."""
    from osgeo import gdal

    engine = exportable
    path = tmp_path / "cube.tif"
    velocity = VelocityModel.constant(0.08)
    plan = export_slices(engine, path, 10, 5, velocity, radius_cells=2)
    ds = gdal.Open(str(path))
    try:
        assert ds.RasterCount == len(plan.bands)
        seventh = ds.GetRasterBand(7).GetDescription()
        assert "ns" in seventh and "m" in seventh
        eighth = ds.GetRasterBand(8).GetDescription()
        assert seventh != eighth
    finally:
        ds = None


def test_the_creation_options_are_the_measured_ones(exportable, tmp_path):
    """Spec 9.5: INTERLEAVE=BAND is the difference between a 230-band
    export being unusable and being free -- pixel interleaving forces a
    read of every band to reach one of them, which is precisely a slice
    viewer's access pattern. TILED=NO because tiling a raster barely
    larger than one tile pads it to 512x512 and wastes 2.9x."""
    from osgeo import gdal

    engine = exportable
    path = tmp_path / "cube.tif"
    export_slices(engine, path, 10, 5, None, radius_cells=2)
    ds = gdal.Open(str(path))
    try:
        interleave = ds.GetMetadata("IMAGE_STRUCTURE").get("INTERLEAVE")
        assert interleave == "BAND"
        assert ds.GetRasterBand(1).GetBlockSize()[0] == ds.RasterXSize  # stripped, not tiled
        assert np.isnan(ds.GetRasterBand(1).GetNoDataValue())
        assert ds.GetRasterBand(1).DataType == gdal.GDT_Float32
    finally:
        ds = None


def test_the_export_is_north_up_and_carries_the_frames_crs(exportable, tmp_path):
    from osgeo import gdal

    engine = exportable
    path = tmp_path / "cube.tif"
    export_slices(engine, path, 10, 5, None, radius_cells=0)
    ds = gdal.Open(str(path))
    try:
        gt = ds.GetGeoTransform()
        assert gt[5] < 0.0 and gt[2] == 0.0 and gt[4] == 0.0
        assert "32616" in ds.GetProjection()
    finally:
        ds = None


def test_export_never_needs_a_resident_cube(exportable, tmp_path):
    """Spec 9.4: written band by band. A resident cube is a latency
    optimisation, never a capability (spec 7.4), and export is the
    operation most tempted to forget that."""
    engine = exportable
    engine.set_always_resident(False)
    assert engine.mode == "streaming"
    export_slices(engine, tmp_path / "cube.tif", 10, 5, None, radius_cells=0)
    assert not engine.has_cube, "export must not have built a cube behind the user's back"


def test_the_temporal_mapping_is_one_nanosecond_to_one_second(exportable, tmp_path):
    """Spec 9.5's named trap. ns -> ms pairs two small units and looks
    right, and silently collapses every band at native dz into the same
    millisecond: 0.2165 ns rounds to 0 ms, adjacent bands get identical
    ranges, and the Temporal Controller's slider does nothing."""
    engine = exportable
    path = tmp_path / "cube.tif"
    plan = export_slices(engine, path, 4, 1, None, radius_cells=0)
    layer = QgsRasterLayer(str(path), "cube", "gdal")
    apply_temporal_properties(layer, plan)
    props = layer.temporalProperties()
    assert props.mode() == Qgis.RasterTemporalMode.FixedRangePerBand
    assert props.isActive()
    ranges = props.fixedRangePerBand()
    assert len(ranges) == len(plan.bands)
    # Adjacent bands must be DISTINCT -- the whole point of 1 ns -> 1 s.
    assert ranges[1].begin() != ranges[2].begin()
    lo_ns, _ = window_times_ns(engine.z, plan.bands[0].window)
    epoch = QDateTime(QDate(1970, 1, 1), QTime(0, 0, 0), Qt.TimeSpec.UTC)
    assert ranges[1].begin() == epoch.addMSecs(int(round(lo_ns * 1000.0)))


def test_the_survey_record_keeps_the_cube_path_relative(exportable_with_session, tmp_path):
    """Trap 7, and the one M10 explicitly left for this milestone.
    `save_site` writes `site.cubes` VERBATIM and does not route `array`
    through `project.line_key`, which is what keeps every other path
    relative and inside the project tree. The first writer of a record is
    the one that has to do it."""
    engine, session = exportable_with_session
    npz = save_cube_npz(engine, session.root / "slices" / "A__default.npz")
    record = cube_record(engine.session, engine.choice, engine.frame, engine.z, _VIEW, npz)
    assert record["array"] == "slices/A__default.npz"
    assert not Path(record["array"]).is_absolute()
    assert set(record) == {"grid_id", "preset", "transform", "cell", "array", "lines", "z", "view"}
    assert record["z"] == {"t0_ns": 2.0, "t1_ns": 30.0, "dz_ns": 0.5}
    assert record["lines"] == list(engine.provenance().line_keys)


def test_a_cube_written_outside_the_project_tree_is_refused(exportable_with_session, tmp_path):
    """The portability guarantee, in the direction that matters: a survey
    file pointing at /home/someone/scratch opens nowhere else."""
    engine, session = exportable_with_session
    outside = tmp_path.parent / "elsewhere" / "cube.npz"
    outside.parent.mkdir(exist_ok=True)
    npz = save_cube_npz(engine, outside)
    with pytest.raises(ProjectError, match="portable"):
        cube_record(session, engine.choice, engine.frame, engine.z, _VIEW, npz)


def test_the_record_survives_a_save_and_reload_of_the_survey(exportable_with_session, tmp_path):
    engine, session = exportable_with_session
    npz = save_cube_npz(engine, session.root / "slices" / "A__default.npz")
    session.site.cubes["A__default"] = cube_record(session, engine.choice, engine.frame, engine.z, _VIEW, npz)
    session.save()
    reloaded = load_site(session.json_path)
    assert reloaded.cubes["A__default"]["array"] == "slices/A__default.npz"
    assert load_cube(session.root / reloaded.cubes["A__default"]["array"]).frame == engine.frame


def test_coverage_exports_as_a_companion_single_band_raster(exportable, tmp_path):
    from osgeo import gdal

    engine = exportable
    path = tmp_path / "coverage.tif"
    write_coverage(engine, path)
    ds = gdal.Open(str(path))
    try:
        assert ds.RasterCount == 1
        counts = ds.GetRasterBand(1).ReadAsArray()
        assert np.nanmax(counts) >= 1
    finally:
        ds = None
```

Fixtures: build one `exportable_with_session` fixture returning `(engine, session)` and derive
`exportable` from it, rather than duplicating the four-line setup.

- [ ] **Step 2: Run and watch them fail.**

- [ ] **Step 3: Implement `slice_export.py`**

```python
"""What leaves the plugin: a multi-band GeoTIFF, an .npz, and a survey record.

A writer INTERFACE rather than a function that knows about GeoTIFF (spec
9.6). More than one raster model may eventually be wanted -- netCDF
through GDAL's multidimensional API is designed for and not built, for
archival and for readers using xarray -- so adding one later should be a
new implementation rather than a refactor.

Written BAND BY BAND. Spec 9.4 and 7.4 together: a resident cube is a
latency optimisation and never a capability, and export is the operation
most tempted to forget that. `export_slices` pulls one window at a time
from the engine in whatever residency it is already in, and never
promotes it.

Two things here are not incidental, and both were measured:

* `INTERLEAVE=BAND`. Pixel interleaving -- GDAL's default -- forces a read
  of every band to reach one of them, which is exactly a slice viewer's
  access pattern: 105.7 ms to read one band of 95 against 0.45 ms. This
  single option is the difference between a 230-band export being
  unusable and being free.
* `1 ns -> 1 s`, from a 1970-01-01T00:00:00Z epoch, for the temporal axis.
  The obvious choice, ns -> ms, pairs two small units and looks right: at
  the native dz of 0.2165 ns it rounds to 0 ms, every band collapses into
  the same millisecond, and the failure is a layer whose Temporal
  Controller slider does nothing. The band DESCRIPTIONS carry the true ns
  and m ranges regardless, so they remain the authority and the temporal
  encoding is only navigation.
"""
```

Concrete requirements:

- `plan_export(engine, thickness_levels, step_levels, velocity)` builds `SliceBand`s from
  `plan_windows(engine.z, thickness_levels, step_levels)`, each description
  `window_label(engine.z, window, velocity)` — the same function the dock's readout uses, so the
  file and the screen cannot disagree.
- `GeoTiffSliceWriter.OPTIONS = ["INTERLEAVE=BAND", "TILED=NO", "COMPRESS=DEFLATE",
  "PREDICTOR=3", "BIGTIFF=IF_SAFER"]` — spec 9.5, verbatim, and **not** the live layer's set
  (plan Ruling 3).
- `write(path, plan, slices)` creates the dataset once from the first slice's north-up shape,
  then writes each band, sets its `NoDataValue(nan)` and its `Description`, and releases the
  dataset (`ds = None`) before returning. Every array goes through `to_north_up` first, and every
  band must therefore land on the same grid — assert that, because a mismatch would otherwise
  write a truncated band silently.
- `export_slices(engine, path, thickness_levels, step_levels, velocity, radius_cells)` is the
  caller: it plans, then for each band pulls `engine.slice_at(window)`, applies
  `fill(values, coverage, radius_cells)`, and hands it to the writer as a generator — so at most
  one slice is resident at a time. Returns the plan.
- `band_time_range(lo_ns, hi_ns)` returns a `QgsDateTimeRange` from
  `QDateTime(QDate(1970, 1, 1), QTime(0, 0, 0), Qt.TimeSpec.UTC).addMSecs(round(ns * 1000))`.
- `apply_temporal_properties(layer, plan)` sets `setFixedRangePerBand({i + 1: range})`, then
  `setMode(Qgis.RasterTemporalMode.FixedRangePerBand)`, then `setIsActive(True)` — in that
  order, and it needs QGIS 3.38+, which `metadata.txt`'s `qgisMinimumVersion=3.40` already
  guarantees, so there is no fallback path to write.
- `write_coverage(engine, path)` writes a single-band north-up raster of
  `engine.slice_at(window)[1]` for the full axis, with the same options.
- `save_cube_npz(engine, path)` calls `save_cube(engine.cube(), path)` and returns the path
  numpy actually wrote — `np.savez_compressed` APPENDS `.npz`, and M10's `store._npz_path` is a
  fixed point of that rule, so return `_npz_path(path)` rather than `path`.
- `cube_record(session, choice, frame, npz_path)`:

```python
def cube_record(
    session: Any,
    choice: SourceChoice,
    frame: CubeFrame,
    z: ZAxis,
    view: ViewSettings,
    npz_path: Path,
) -> dict[str, Any]:
    """One `Site.cubes` record: the whole recipe, with its path made portable.

    `save_site` writes `site.cubes` VERBATIM -- it does NOT route a
    record's `array` through `project.line_key`, which is what keeps every
    other path in a survey file relative and inside the project tree, and
    what refuses an absolute one. M10's `Site.cubes` docstring records
    that gap and says explicitly that routing it is M11's job, to be done
    by whoever writes the first real record. This is that writer.

    Raises ProjectError for a path outside the project directory, which is
    the behaviour worth having: a survey file pointing at somebody's
    scratch directory opens nowhere else, and it would round-trip through
    save and load without complaint.
    """
    root = Path(session.json_path).parent.resolve()
    return {
        # --- what the cube IS: change any of these and the array changes ---
        "grid_id": choice.grid_id,
        "preset": choice.preset,
        "transform": choice.transform or "none",
        "cell": float(frame.cell),
        "lines": list(choice.line_keys),
        "z": {"t0_ns": z.t0_ns, "t1_ns": z.t_end_ns, "dz_ns": z.dz_ns},
        "array": line_key(npz_path, root),
        # --- how it was BEING READ: changes nothing in the array ---
        "view": view.to_dict(),
    }
```

The first five keys are the ones `Site.cubes`'s docstring already declares normative, unchanged
and in place; `lines`, `z` and `view` extend it. **Do not bump `SCHEMA_VERSION`** — `load_site`
compares `version != SCHEMA_VERSION` exactly, so bumping would make every existing survey file
fail to load outright (M10 final review, Important 6). No bump is needed: `load_site` checks only
that `cubes` is a dict and then stores each record opaquely (`project.py:264-269`), so added keys
round-trip with no schema change in either direction. Update the `Site.cubes` docstring in
`model/survey.py` to describe the full shape, and delete its "routing `array` through `line_key`
is M11's job" note, which this task discharges.

The split between the two halves is the useful part and is worth keeping legible: everything
above `view` is what the `.npz` was binned from, so two records agreeing there name the same
array; `view` is what the reader had on screen, which changes no pixel in the cube.

- [ ] **Step 4: Add the two buttons and the two dialogs**

In `slices_dock.py`, below `status_label` (spec 9.2 puts the status line *above* the export
buttons): `save_button = QPushButton("Save cube…")` and
`export_button = QPushButton("Export GeoTIFF…")`, each connected with a lambda that drops
`clicked`'s `bool` and emits `save_cube_requested` / `export_requested`. Both disabled unless
`engine.is_prepared`.

In `plugin.py`, connect both to guarded handlers that use `QFileDialog.getSaveFileName`
(defaulting into `session.root / "slices"`), then call `save_cube_npz` + `cube_record` +
`session.site.cubes[...] = record` (the id being the `<grid_id>__<name>` the user chose) +
`session._set_dirty(True)` — or `export_slices` +
`apply_temporal_properties` + add the result to `layers.group` as a `QgsRasterLayer`. Report
every failure through `self.message(...)`; the tests drive the dialogs with the `answer_modal`
fixture, which is the only sanctioned way past the conftest's modal guard.

- [ ] **Step 5: Add the core-side record test**

Append to `packages/nsgeo-core/tests/test_project.py` a test that a `cubes` record with the five
keys round-trips through `save_site`/`load_site` unchanged, and that a record whose `array` is
absolute still round-trips **verbatim** — pinning that `save_site` does not sanitise it, which is
precisely why `cube_record` must.

- [ ] **Step 6: Verify and prove discrimination**

Mutants:

1. `OPTIONS` → drop `INTERLEAVE=BAND`. Expect `test_the_creation_options_are_the_measured_ones`
   to FAIL. Also time reading one band of a 19-band file both ways and record both numbers — the
   option's justification is a measurement, and the report should carry one.
2. `band_time_range` → `addMSecs(round(ns))` (the ns → ms trap). Expect
   `test_the_temporal_mapping_is_one_nanosecond_to_one_second` to FAIL on the
   adjacent-bands-distinct assertion. Confirm it fails at the *native* dz of 0.2165 ns as well as
   at the test's dz.
3. `cube_record` → `"array": str(npz_path)`. Expect
   `test_the_survey_record_keeps_the_cube_path_relative` and
   `test_a_cube_written_outside_the_project_tree_is_refused` to FAIL.
4. `export_slices` → call `engine.cube()` and slice it. Expect
   `test_export_never_needs_a_resident_cube` to FAIL.

- [ ] **Step 7: Full verification, commit, push**

Run all four test commands. Then:

```bash
git add packages/nsgeo-qgis packages/nsgeo-core/tests/test_project.py
git commit -m "feat(slices): multi-band GeoTIFF export, the .npz, and the survey record

Band by band, so export never needs a resident cube. INTERLEAVE=BAND and
1 ns -> 1 s are both measured choices, not defaults. The cubes record
routes its array through project.line_key, which M10 left for the first
writer of a record.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push origin nsgeo-m11
```

---

### Task 7: Reproducing a saved cube

A recipe you can only write is half a feature. This task closes the loop: pick a saved cube from
the Source group and the dock comes back to exactly the state that produced it.

**Why it is its own task rather than folded into Task 6.** The record's *writer* and its *reader*
fail differently — a writer bug loses information, a reader bug silently reconstructs the wrong
thing — and the reader's test is a round trip that can only exist once the writer is finished.
This also deliberately takes the plan to **seven** tasks rather than growing Task 6, which already
carries the GeoTIFF, the temporal axis, the `.npz` and two file dialogs. The standing preference
is for 3–6 tasks, and the reason behind it is smaller chunks; seven right-sized tasks serve that
better than six with one oversized one. **Flag the deviation when reporting.**

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py` (the reader half)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` (the Source group's cube combo)
- Modify: `packages/nsgeo-core/src/nsgeo/model/survey.py` (the `Site.cubes` docstring)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export.py` (append)

**Interfaces:**

- Produces:
  - `slice_export.CubeRecipe(choice: SourceChoice, resolution: Resolution, view: ViewSettings)`
  - `slice_export.recipe_from_record(record: dict[str, Any]) -> CubeRecipe`
  - `SlicesDock.cube_combo`, `SlicesDock.restore_cube(cube_id: str)`,
    `SlicesDock.view_settings() -> ViewSettings`, `SlicesDock.apply_view(view: ViewSettings)`

---

- [ ] **Step 1: Write the round-trip test first — it is the whole point of the task**

Append to `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export.py`:

```python
def test_a_restored_recipe_reproduces_the_identical_slice(exportable_with_session):
    """The only definition of "reproducible" worth having.

    Not "the fields came back" -- a recipe that restores every field and
    still produces a different picture has failed at the one thing it is
    for. So: slice, save, wipe the engine, restore from the record alone,
    slice again, and demand the same numbers.

    This is also the test that catches a field quietly dropped from the
    record, which is otherwise invisible: a missing z range just means
    the restored cube silently uses whatever the dock happened to have.
    """
    engine, session = exportable_with_session
    window = SliceWindow(6, 18)
    before, coverage_before = engine.slice_at(window)

    npz = save_cube_npz(engine, session.root / "slices" / "A__first.npz")
    view = ViewSettings(
        thickness_ns=5.0, step_ns=2.5, radius_m=0.75,
        palette="amp_heat", stretch="shared", coverage=False,
    )
    record = cube_record(session, engine.choice, engine.frame, engine.z, view, npz)
    session.site.cubes["A__first"] = record
    session.save()

    # Everything the dock held is gone; the record is all that is left.
    engine.clear()
    assert not engine.is_prepared

    recipe = recipe_from_record(load_site(session.json_path).cubes["A__first"])
    engine.set_source(recipe.choice)
    assert engine.wait_for_preparation(20_000)
    engine.set_resolution(recipe.resolution)
    after, coverage_after = engine.slice_at(window)

    np.testing.assert_array_equal(coverage_before, coverage_after)
    np.testing.assert_array_equal(np.isfinite(before), np.isfinite(after))
    both = np.isfinite(before)
    np.testing.assert_allclose(before[both], after[both], rtol=1e-6, atol=1e-7)
    assert recipe.view == view


def test_a_recipe_restores_the_exact_line_set_not_the_whole_grid(exportable_with_session):
    """A cube built from 22 of 26 lines is not the same cube as one built
    from all 26, and the difference is invisible in a picture. The record
    carries the line keys for exactly this reason."""
    engine, session = exportable_with_session
    subset = tuple(session.keys())[:2]
    engine.set_source(SourceChoice("A", "p", "amp_envelope", subset))
    assert engine.wait_for_preparation(20_000)
    engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
    npz = save_cube_npz(engine, session.root / "slices" / "A__subset.npz")
    record = cube_record(session, engine.choice, engine.frame, engine.z, _VIEW, npz)

    recipe = recipe_from_record(record)
    assert recipe.choice.line_keys == subset
    assert len(recipe.choice.line_keys) < len(session.keys())


def test_a_record_written_by_an_older_build_still_loads(exportable_with_session):
    """The five-key record `Site.cubes`'s docstring described before this
    milestone must not become unreadable. `load_site` stores records
    opaquely, so an old one arrives here intact and the reader -- not the
    schema -- is what has to tolerate it."""
    old = {
        "grid_id": "A", "preset": "p", "transform": "amp_envelope",
        "cell": 0.25, "array": "slices/A__old.npz",
    }
    recipe = recipe_from_record(old)
    assert recipe.choice.grid_id == "A"
    assert recipe.choice.line_keys == ()  # unknown, not invented
    assert recipe.resolution is None  # unknown: the dock keeps what it has
    assert recipe.view is None


def test_a_record_with_a_broken_field_is_refused_by_name(exportable_with_session):
    bad = {
        "grid_id": "A", "preset": "p", "transform": "amp_envelope", "cell": 0.25,
        "array": "slices/x.npz", "lines": [], "view": {},
        "z": {"t0_ns": 30.0, "t1_ns": 2.0, "dz_ns": 0.5},  # reversed
    }
    with pytest.raises(ValueError, match="z"):
        recipe_from_record(bad)
```

Define `_VIEW` once at module scope beside the other constants.

- [ ] **Step 2: Run and watch them fail.** Expected: `ImportError` for `recipe_from_record` /
`ViewSettings`.

- [ ] **Step 3: Implement the reader half**

In `slice_export.py`:

```python
@dataclass(frozen=True)
class ViewSettings:
    """How a cube was being read, as opposed to what it was binned from.

    Changing any of these changes no pixel in the `.npz` -- which is why
    they live in their own object and under their own key in the record.
    A reader restoring a cube wants both halves, but only the other half
    decides whether two records name the same array.
    """

    thickness_ns: float
    step_ns: float
    radius_m: float
    palette: str
    stretch: str
    coverage: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "thickness_ns": float(self.thickness_ns),
            "step_ns": float(self.step_ns),
            "radius_m": float(self.radius_m),
            "palette": str(self.palette),
            "stretch": str(self.stretch),
            "coverage": bool(self.coverage),
        }

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> ViewSettings:
        return cls(
            thickness_ns=float(doc["thickness_ns"]),
            step_ns=float(doc["step_ns"]),
            radius_m=float(doc["radius_m"]),
            palette=str(doc["palette"]),
            stretch=str(doc["stretch"]),
            coverage=bool(doc.get("coverage", False)),
        )


@dataclass(frozen=True)
class CubeRecipe:
    """A `Site.cubes` record, read back as the three things the dock sets.

    `resolution` and `view` are optional because a record written before
    this milestone carries neither. Absent means UNKNOWN, and the dock
    keeps whatever it already had rather than inventing a default that
    would look like a restored setting.
    """

    choice: SourceChoice
    resolution: Resolution | None
    view: ViewSettings | None


def recipe_from_record(record: Mapping[str, Any]) -> CubeRecipe:
    """Read a cube record back into the three values the dock sets.

    Tolerant of a record written by an earlier build -- `load_site`
    stores records opaquely, so old ones arrive here unchanged and it is
    this function, not the schema, that has to cope. Strict about a
    field that is PRESENT and wrong: a reversed z range restored silently
    would produce a different cube under the same name, which is the one
    failure a reproducibility feature must not have.
    """
    try:
        choice = SourceChoice(
            grid_id=str(record["grid_id"]),
            preset=str(record["preset"]),
            transform="" if record.get("transform", "none") == "none" else str(record["transform"]),
            line_keys=tuple(str(k) for k in record.get("lines", ())),
        )
    except (KeyError, TypeError) as exc:
        raise ValueError(f"cube record is missing {exc}") from exc

    resolution = None
    if "z" in record:
        z_doc = record["z"]
        try:
            resolution = Resolution(
                cell=float(record["cell"]),
                dz_ns=float(z_doc["dz_ns"]),
                t0_ns=float(z_doc["t0_ns"]),
                t1_ns=float(z_doc["t1_ns"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"cube record has an invalid z range: {exc}") from exc

    view = None
    if record.get("view"):
        try:
            view = ViewSettings.from_dict(dict(record["view"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"cube record has invalid view settings: {exc}") from exc

    return CubeRecipe(choice=choice, resolution=resolution, view=view)
```

Note the `transform` mapping: the record stores `"none"` where a `SourceChoice` holds
`NO_TRANSFORM` (`""`), because `"none"` is what reads correctly in a file someone opens in a text
editor. This is the only place the two spellings meet, and it must round-trip — the first
round-trip test above covers it through `recipe.view == view` and the identical-slice assertion.

- [ ] **Step 4: Add the cube combo to the Source group**

At the **top** of the Source group, above `Grid` — it is the control that sets all the others, so
it reads first:

```
Cube      [ (unsaved)                 ▾ ]
```

- `cube_combo` is refilled from `sorted(session.site.cubes)` with `"(unsaved)"` first, on
  `session.site_opened` and whenever a cube is saved. It joins `rebuild_source`'s existing
  session-signal connections.
- Selecting a saved cube calls `restore_cube(cube_id)`: `recipe_from_record` the record, apply
  `recipe.view` to the Display and Position widgets **with signals blocked** (so restoring does
  not fire four separate refreshes), set the inclusion set from `recipe.choice.line_keys`, set the
  three source combos, set the Resolution widgets, then `flush_debounce()` and one `prepare()`.
  Guard the whole body and report a `ValueError` from the reader through `error` and
  `source_status`, exactly as a conflicting preset is reported.
- Selecting `"(unsaved)"` changes nothing: it is a label for "these settings match no saved
  cube", not an action. Set it automatically whenever any Source or Resolution widget moves away
  from the restored values, so the combo never claims a cube the dock is no longer showing.
- `view_settings()` reads the six values off the widgets; `apply_view(view)` writes them back.
  Task 6's save handler calls `view_settings()` so the record carries what was on screen at the
  moment of saving.

- [ ] **Step 5: Update the `Site.cubes` docstring**

In `packages/nsgeo-core/src/nsgeo/model/survey.py`, replace the paragraph beginning *"Unlike every
line path elsewhere in a Site..."* — M11 has now discharged it — and describe the full shape:
the five original keys, plus `lines` (the included line keys), `z` (`t0_ns`, `t1_ns`, `dz_ns`) and
`view` (thickness, step, radius, palette, stretch, coverage). State the split explicitly: every
key except `view` decides what the array contains, and `view` decides only how it was last being
read. Note that `array` is routed through `project.line_key` by the plugin's `cube_record`, since
`save_site` still writes the record verbatim.

- [ ] **Step 6: Verify and prove discrimination**

Mutants, one at a time:

1. `cube_record` → drop the `"lines"` key. Expect
   `test_a_recipe_restores_the_exact_line_set_not_the_whole_grid` to FAIL, **and** confirm whether
   `test_a_restored_recipe_reproduces_the_identical_slice` also catches it — it should not, since
   that fixture includes every line, which is exactly why the second test exists. Record both
   results: a test that passes against this mutant is the reason the other one was written.
2. `cube_record` → drop the `"z"` key. Expect the identical-slice test to FAIL (the restored
   engine gets no resolution, so `slice_at` raises).
3. `recipe_from_record` → map `"none"` to `"none"` rather than `""`. Expect the identical-slice
   test to FAIL — the restored source would append a step named `none`, which is not in the
   registry.
4. `recipe_from_record` → wrap the z read in a bare `except: pass`. Expect
   `test_a_record_with_a_broken_field_is_refused_by_name` to FAIL.

- [ ] **Step 7: Commit and push**

```bash
git add packages/nsgeo-qgis packages/nsgeo-core/src/nsgeo/model/survey.py
git commit -m "feat(slices): save and restore a cube recipe through the survey JSON

The record now carries the lines, the z range and the view settings
alongside the five keys it already had, and the Source group can restore
one. Pinned by a round trip that demands the same slice back, not merely
the same fields.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push origin nsgeo-m11
```

**Task 7 is done when:** a cube saved, a site closed and reopened, and the cube selected from the
combo produces the identical slice — and both tiers are green.

---

## After Task 7: the manual walkthrough gate

**This is a human checkpoint, not a task.** It must be surfaced to the user and passed by them —
never silently — and no merge decision is made before it. M10 was core-only and the gate was a
formality; M11 is entirely UI, so it is the only thing that actually tests what this milestone
claims to deliver.

Deploy:

```bash
.venv/bin/python packages/nsgeo-qgis/scripts/dev_link.py --profile ns_geo
```

(the profile is `ns_geo`, with an underscore), then in QGIS with the real data:

1. Open a site with a grid of real DZT lines. The **Slices** dock is tabified behind Processing.
2. Choose the grid, a preset, and `amp_envelope`. `Choose…` lists every line, marks any that
   carries its own stack as *using the preset instead*, and the summary reads `n of m included`
   with an approximate memory figure. Press **Prepare** and watch per-line progress.
3. Drag the depth slider. The map raster redraws live; the readout beneath the slider states the
   window in ns and m and tracks what was actually averaged — **push the slider to both ends and
   confirm the range shrinks there rather than reporting the requested thickness**.
4. Change the thickness. The stretch stays shared and the picture stays comparable across depth.
   Switch to *this slice* and confirm a deep slice becomes legible.
5. Move the fill radius. The picture smooths; drag it continuously and confirm the UI stays
   responsive (the debounce doing its job). Set it to 0 and confirm the honest, gappy bins.
6. Tick **Show coverage**. Empty cells are visibly distinct from zero-amplitude cells.
7. Change the cell size and dz. Everything re-bins, the layer resizes in place, **and nothing
   raises** — this is the stale-plan hazard in its live form.
8. Open a line in the profile view. The slice's time window is drawn as a band across the
   radargram, and it follows the depth slider.
9. Shift + scroll on the map canvas steps depth. Plain scroll still zooms the map.
10. **Save cube…**, then **Export GeoTIFF…**. Open the GeoTIFF fresh in QGIS: the band names read
    as ns and m ranges, and the Temporal Controller steps through the bands.
11. Save the survey, close it, reopen it: the `cubes` record is there and its path is relative.
    Pick the cube from the **Cube** combo — every control comes back where it was, and the slice
    on screen is the one you saved. Open the survey JSON in an editor and confirm the record reads
    as a recipe a person could follow.
12. Unload the plugin with the Slices dock open and a line chooser open. Nothing leaks, nothing
    raises.

Report what actually happened at each step, including anything that looked wrong. Then ask before
merging.

## Spec amendments to make when the milestone lands

Following the M10 precedent of annotating the spec where execution diverged, rather than leaving
it to be read as history:

- **§7.4** — note that the third residency tier (on-disk, memory-mapped lines) is still unbuilt
  and unmeasured, that its spike did not run in M11, and that M11 deliberately ships no control
  for it (plan Ruling 1). The table's third row stands as designed-for-not-built.
- **§9.2** — note that the residency override is binary (automatic, or always resident) for the
  same reason.
- **§6.2 / §8** — record Ruling 2: the transform is appended by the engine after the preset's
  steps, so `output_unipolar` is exact by construction and a preset carrying an amplitude
  transform is refused. This is the alternative to the per-step `preserves_unipolar` that §8's
  problem would otherwise need.
- **§9.4** — record Ruling 4: the north-up resample lives in `nsgeo.slices.display`, not the
  plugin, because it is pure frame geometry; the plugin keeps only GDAL.
- **§9.5** — record Ruling 3: the option set is the export's. The live preview layer writes
  uncompressed, because `COMPRESS=DEFLATE, PREDICTOR=3` costs 8.8–25.2 ms per write against
  1.0–1.3 ms, and it is rewritten on every tick.
- **§5.4** — record that a `cubes` record carries the full recipe, not only the five keys first
  sketched there: `lines`, `z` and `view` join them so a cube can be reproduced from the survey
  file alone. No `SCHEMA_VERSION` bump, because `load_site` stores each record opaquely.
- **§6.4** — record that `fill` now rounds its FFT to a 5-smooth size and caches the kernel
  spectrum, with the measured figures, and that the radius slider debounces regardless because
  even the improved fill is 32 ms at 600×600.

Commit the decision record under `docs/superpowers/sdd/2026-09-19-nsgeo-slices-m11/`, following
Plan 2, M7 and M10: a `progress.md` ledger carrying every ruling with its reason and its cost if
wrong, a brief and a report per task, and a `deferred-minors.md` triaged before merge.

## Self-review against the spec

| Spec section | Where it lands |
|---|---|
| §5–§6 (data model, processing) | M10; unchanged here except `fill`'s padding (Task 1) |
| §6.4 fill radius as a slider | Task 4 (metres, debounced), Task 1 (the speedup) |
| §6.6 thickness/step independent; readout shows the full range | Task 1 (`plan_windows`, `window_label`), Task 4 (the readout) |
| §7.4 residency | Task 2 (`choose_residency`), two tiers by Ruling 1 |
| §8 unipolar rendering, shared stretch, per-slice override | Task 1 (`shared_limit`), Task 4 (palette, stretch combo, shader) |
| §9.1 source dialog, `Choose…`, preparation as a task, memory reported | Task 3 |
| §9.2 dock tabified, four groups, live sliders, fused readout, status line, shift+scroll | Tasks 3, 4, 5 |
| §9.3 the profile band | Task 5 |
| §9.4 multi-band GeoTIFF, band descriptions, coverage companion, layer group | Task 6 |
| §9.5 creation options, temporal properties, the ns→ms trap | Task 6 |
| §11 testing: two tiers, real data primary, properties, no orphans | Throughout; real data in Task 1, the streaming/resident property in Task 2 |
| §5.4 the survey JSON records the recipe | Tasks 6 and 7 (write, then read back) |
| §10, §12 site mosaic, de-striping, netCDF, elevation axis | M12 and beyond; out of scope here |
