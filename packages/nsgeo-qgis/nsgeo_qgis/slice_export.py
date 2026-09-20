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
  access pattern: measured here at GDAL 3.8.4 on a 300x300, 19-band
  float32 file, reading one band costs a median 18.1 ms under the
  default PIXEL interleaving against 2.3 ms under BAND (see the task
  report for the full numbers, including a smaller file where the gap is
  even starker). This single option is the difference between a
  230-band export being unusable and being free.
* `1 ns -> 1 s`, from a 1970-01-01T00:00:00Z epoch, for the temporal axis.
  The obvious choice, ns -> ms, pairs two small units and looks right: at
  the native dz of 0.2165 ns it rounds to 0 ms, every band collapses into
  the same millisecond, and the failure is a layer whose Temporal
  Controller slider does nothing. The band DESCRIPTIONS carry the true ns
  and m ranges regardless, so they remain the authority and the temporal
  encoding is only navigation.

Two decisions this task owns, recorded here rather than only in the task
report because a future reader of this file needs them as much as a
reviewer of this task does:

* **North-up pitch is the frame's own cell size, not a finer one (Ruling
  AE, Task 6 fix round 1, corrects this bullet's own first draft).**
  `to_north_up` (Task 1) drops 15-18% of frame cells at rotated azimuths
  under nearest-neighbour resampling, which is a real, measured gap, and
  the loss is UNCONDITIONAL: `fill` never puts a dropped cell into the
  output at all, at any radius -- it only makes that cell's value
  recoverable from a surviving neighbour before this module ever sees the
  array. Radius only changes how much the loss matters, never whether it
  happens, and radius 0 (spec 6.4's own honest unfilled truth,
  `radius_spin`'s construction default, and a value `export_geotiff`
  passes straight through with no refusal) is not a debugging-only case
  this module gets to assume away. This writer does not compensate with a
  finer output pitch anyway, for reasons that hold regardless: (1) a
  finer pitch is a MITIGATION, not a fix -- nearest-neighbour at half
  pitch still drops cells, it only lowers the probability that a given
  cell is sampled by no output pixel at all; the actual fix is forward
  scatter-mapping inside `to_north_up` itself, which is Task 1 work, not
  this module's; (2) it multiplies the pixel count (4x at half-cell),
  which multiplies the per-band write cost `INTERLEAVE=BAND` exists to
  keep small, for a partial mitigation of a problem it does not solve --
  the wrong trade twice over; (3) implementing even that partial
  mitigation needs `to_north_up`'s own resample loop, and that function
  is already the single source both `SliceLayer` and this module read --
  duplicating its arithmetic here would let the two drift, which is
  exactly the failure `window_label` being shared between the dock and
  this module already avoids for the text labels. What this module does
  instead: say so, on both the file (`NSGEO_FILL_RADIUS_CELLS`/
  `NSGEO_FRAME_AZIMUTH_DEG` dataset metadata, `GeoTiffSliceWriter.write`)
  and the message bar (`plugin.export_geotiff`, at radius 0).
* **The per-band `cell_index` solve is not hoisted out of the export
  loop.** Task 1's review measured ~1.4 s of repeated solving across 39
  bands of a 400x300x400 cube, because `to_north_up`'s resample grid does
  not depend on the values being resampled. Hoisting it needs either a
  new `to_north_up` entry point that accepts precomputed indices (a
  change to a shipped Task 1 API, and to `SliceLayer`'s only other
  caller) or reimplementing the resample here -- the same duplication
  cost the pitch decision above already rejects. 1.4 s is paid once, on
  an explicit "Export GeoTIFF..." click, not on every tick of a slider
  the way `SliceLayer.update` is; that is a cost this module accepts
  rather than a latency it needs to hide.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from nsgeo.project import line_key
from nsgeo.slices import (
    CubeFrame,
    Provenance,
    SliceWindow,
    ZAxis,
    fill,
    plan_windows,
    save_cube,
    to_north_up,
    window_label,
    window_times_ns,
)
from nsgeo.slices.store import _npz_path
from nsgeo.velocity import VelocityModel
from osgeo import gdal
from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsDateTimeRange, QgsRasterLayer
from qgis.PyQt.QtCore import QDate, QDateTime, Qt, QTime

from nsgeo_qgis.slices_engine import SliceEngine
from nsgeo_qgis.slices_plan import SourceChoice


@dataclass(frozen=True)
class SliceBand:
    """One band of an export: the window it averages, and its label.

    `description` is `window_label(z, window, velocity)` -- the same
    function the dock's readout calls -- so the file on disk and the
    screen the user was looking at when they exported it cannot disagree.
    """

    window: SliceWindow
    description: str


@dataclass(frozen=True)
class ExportPlan:
    """Everything an export needs to know before the first pixel is written.

    `crs` sits beside `frame` (which already carries one) so a writer
    never has to reach into the frame for it; `provenance` is the whole
    recipe, carried through for a future writer (the netCDF one the
    module docstring names) that would want to record it in the file
    itself, the way `save_cube_npz` already does for the `.npz`.

    `radius_cells` is `None` for a plan that carries no fill radius at
    all (`write_coverage`'s companion raster is never filled -- coverage
    counts are exact, and smearing a count is not a display decision the
    way smearing an amplitude is). `GeoTiffSliceWriter.write` records it,
    and the frame's azimuth, as dataset-level metadata -- see Ruling AE
    (Task 6 fix round 1) for why: the export is a lossy resample at any
    fill radius, radius 0 included, and a reader five years from now with
    only the `.tif` in hand needs a way to see that from the file itself.
    """

    frame: CubeFrame
    z: ZAxis
    crs: str
    bands: tuple[SliceBand, ...]
    provenance: Provenance
    radius_cells: int | None = None


def plan_export(
    engine: SliceEngine,
    thickness_levels: int,
    step_levels: int,
    velocity: VelocityModel | None,
    radius_cells: int | None = None,
) -> ExportPlan:
    """The band list a GeoTIFF export would write, without writing anything.

    `plan_windows` is spec 9.4's band-count formula by construction (see
    its own docstring), so `len(plan.bands)` and the dock's slice count
    are never two agreeing implementations, only one.

    `radius_cells` is carried through onto the plan only -- it changes no
    band here, only what `GeoTiffSliceWriter.write` later records as
    metadata. Optional and keyword-compatible with every existing caller
    (`export_slices` is the only one that has a real value to pass).
    """
    frame, z = engine.frame, engine.z
    if frame is None or z is None:
        raise RuntimeError("no slice geometry: choose a source and a resolution first")
    windows = plan_windows(z, thickness_levels, step_levels)
    bands = tuple(SliceBand(window=w, description=window_label(z, w, velocity)) for w in windows)
    return ExportPlan(
        frame=frame,
        z=z,
        crs=frame.crs,
        bands=bands,
        provenance=engine.provenance(),
        radius_cells=radius_cells,
    )


class SliceWriter(Protocol):
    """What `export_slices`/`write_coverage` need from a writer (spec 9.6).

    A structural interface, not a base class: `GeoTiffSliceWriter` below
    satisfies it with no inheritance, and a future netCDF writer (the
    module docstring's own example of why this exists at all) would too.
    Declaring the seam here -- rather than only in prose -- is what makes
    substituting one an addition instead of a refactor to two call sites
    (Ruling AG, Task 6 fix round 1): before this, `export_slices` and
    `write_coverage` each named `GeoTiffSliceWriter` directly, so a second
    implementation would have had to edit both.
    """

    OPTIONS: list[str]

    def write(self, path: str | Path, plan: ExportPlan, slices: Iterable[np.ndarray]) -> None: ...


class GeoTiffSliceWriter:
    """Writes an `ExportPlan`'s slices to a multi-band GeoTIFF, band by band.

    `OPTIONS` is spec 9.5's set, verbatim, and deliberately NOT
    `slice_layer.py`'s (plan Ruling 3): that file is an uncompressed
    scratch preview rewritten every tick; this one is the durable
    artefact a reader keeps, so it pays compression's write cost once for
    a much smaller file forever after. Satisfies `SliceWriter` structurally.
    """

    OPTIONS = [
        "INTERLEAVE=BAND",
        "TILED=NO",
        "COMPRESS=DEFLATE",
        "PREDICTOR=3",
        "BIGTIFF=IF_SAFER",
    ]

    def write(self, path: str | Path, plan: ExportPlan, slices: Iterable[np.ndarray]) -> None:
        """Create `path` from `plan.bands[0]`'s north-up shape, then fill it in.

        Every array is resampled through `to_north_up` here, never
        earlier: `slices` carries grid-local arrays (whatever residency
        `export_slices` pulled them in), and this is the one place they
        become the raster grid the file is actually written on. Every
        band must land on that same grid -- raised, not merely asserted,
        because `assert` can be compiled away and a silently truncated
        band is exactly the failure this guards against (spec 9.4: a
        rotated frame's bounding box can differ, in principle, from one
        slice to the next only if the frame itself changed mid-export,
        which would itself be a bug worth surfacing loudly).

        `zip(plan.bands, slices)` is deliberately NOT `strict=True` (Task
        6 fix round 1, Important 3): `strict=` needs Python 3.10+, and
        this package's floor is `>=3.9` -- a QGIS 3.40 build running
        Python 3.9 would raise `TypeError: zip() takes no keyword
        arguments` the first time this ran, and nothing in either venv or
        in CI would have caught it (both venvs here are 3.12; the 3.9 CI
        job never imports this module). The `written != len(plan.bands)`
        check plus the explicit `next(iterator, None)` probe after the
        loop together keep the same guarantee `strict=True` bought, in
        plain Python -- BOTH directions of it (Task 6 fix round 2,
        Minor 1): `zip` stops at the shorter iterable, so `written` alone
        can only ever detect too FEW slices (it never exceeds
        `len(plan.bands)`); a `slices` iterable with a surplus past
        `plan.bands` would otherwise have that surplus silently dropped,
        the exact case `strict=True` used to raise
        `ValueError: zip() argument 2 is longer than argument 1` for. The
        probe is what makes an iterator (not a list) the right type for
        this parameter: consuming one further item from `slices` after
        the loop is answering "is there more?", which a plain `len()`
        check could not do without the caller pre-materialising it.

        `plan.radius_cells`/`plan.frame.azimuth` are written as dataset
        metadata once the dataset exists (Ruling AE, same fix round): the
        export is a lossy resample at ANY fill radius including 0 (see
        `ExportPlan`'s own docstring), and a reader with only the `.tif`
        needs a way to see that without this module's source in hand.
        """
        if not plan.bands:
            raise ValueError("an export plan needs at least one band")
        with warnings.catch_warnings():
            # See slice_layer.py's `_write` for the full account of why
            # both halves are needed: `ExceptionMgr` makes a failed
            # Create()/WriteArray() raise, scoped to this block only, and
            # this filter separately silences GDAL's one-time "neither
            # UseExceptions() nor DontUseExceptions() has been called"
            # FutureWarning, which `ExceptionMgr` does not touch.
            warnings.simplefilter("ignore", FutureWarning)
            with gdal.ExceptionMgr(useExceptions=True):
                driver = gdal.GetDriverByName("GTiff")
                dataset = None
                try:
                    shape: tuple[int, int] | None = None
                    written = 0
                    iterator = iter(slices)
                    for index, (band_plan, values) in enumerate(zip(plan.bands, iterator)):
                        array, geotransform = to_north_up(values, plan.frame)
                        if dataset is None:
                            height, width = array.shape
                            shape = array.shape
                            dataset = driver.Create(
                                str(path),
                                width,
                                height,
                                len(plan.bands),
                                gdal.GDT_Float32,
                                options=self.OPTIONS,
                            )
                            dataset.SetGeoTransform(geotransform)
                            dataset.SetProjection(QgsCoordinateReferenceSystem(plan.crs).toWkt())
                            if plan.radius_cells is not None:
                                dataset.SetMetadataItem(
                                    "NSGEO_FILL_RADIUS_CELLS", str(plan.radius_cells)
                                )
                            dataset.SetMetadataItem(
                                "NSGEO_FRAME_AZIMUTH_DEG", str(plan.frame.azimuth)
                            )
                        elif array.shape != shape:
                            raise ValueError(
                                f"band {index + 1} resampled to {array.shape}, but the first "
                                f"band resampled to {shape}; every band must land on the same "
                                f"grid, or this band would be written truncated"
                            )
                        band = dataset.GetRasterBand(index + 1)
                        band.SetNoDataValue(float("nan"))
                        band.SetDescription(band_plan.description)
                        band.WriteArray(array)
                        written += 1
                    if written != len(plan.bands):
                        # Covers an empty `slices` too: `plan.bands` is
                        # non-empty (checked above), so `written == 0`
                        # trips this before `dataset` (never created)
                        # could be tested separately.
                        raise ValueError(
                            f"expected {len(plan.bands)} slices (one per planned band), got "
                            f"{written}"
                        )
                    if next(iterator, None) is not None:
                        # The other direction `strict=True` used to catch:
                        # `zip` above stopped consuming `iterator` the
                        # moment `plan.bands` was exhausted, so a surplus
                        # item is still sitting unread here -- `written`
                        # alone cannot see it, since it can never exceed
                        # `len(plan.bands)`.
                        raise ValueError(f"more slices than the plan's {len(plan.bands)} bands")
                finally:
                    # Hold the dataset in a local and set it to None
                    # explicitly (see slice_layer.py's own `_write` for the
                    # spike this bit): a dataset collected mid-expression
                    # is a real trap. `Close()` -- an improvement over that
                    # file's shape, available here at GDAL >= 3.7 (this
                    # build is 3.8.4) -- surfaces a write error that would
                    # otherwise only materialise at garbage collection,
                    # where a SWIG destructor cannot raise and the failure
                    # would be silent.
                    if dataset is not None:
                        dataset.Close()
                    dataset = None


def export_slices(
    engine: SliceEngine,
    path: str | Path,
    thickness_levels: int,
    step_levels: int,
    velocity: VelocityModel | None,
    radius_cells: int,
    *,
    writer: SliceWriter | None = None,
) -> ExportPlan:
    """Plan, then write, one band at a time -- never a resident cube.

    Spec 9.4 and 7.4 together (see the module docstring): the generator
    below pulls exactly one `engine.slice_at(window)` at a time, in
    whatever mode the engine is already in, and hands it straight to the
    writer. A caller with `engine.mode == "streaming"` never sees this
    function build a cube behind their back.

    `writer` defaults to a fresh `GeoTiffSliceWriter()` -- NOT a mutable
    default argument (Ruling AG, Task 6 fix round 1): a `None` sentinel
    with the real default constructed inside the body, so every call gets
    its own writer instance rather than one shared (and, worse, capable
    of accumulating state) across every call this process ever makes. A
    test substitutes a stub here to observe the streaming property
    without touching GDAL at all.
    """
    plan = plan_export(engine, thickness_levels, step_levels, velocity, radius_cells=radius_cells)
    writer = writer if writer is not None else GeoTiffSliceWriter()

    def _filled_slices() -> Iterable[np.ndarray]:
        for band in plan.bands:
            values, coverage = engine.slice_at(band.window)
            yield fill(values, coverage, radius_cells)

    writer.write(path, plan, _filled_slices())
    return plan


def band_time_range(lo_ns: float, hi_ns: float) -> QgsDateTimeRange:
    """One band's temporal range: `1 ns -> 1 s`, from the Unix epoch.

    See the module docstring for why this is milliseconds-from-`ns *
    1000`, not milliseconds-from-`ns` directly: the latter is spec 9.5's
    named trap, and at the native dz of 0.2165 ns it collapses every band
    into the same millisecond.
    """
    epoch = QDateTime(QDate(1970, 1, 1), QTime(0, 0, 0), Qt.TimeSpec.UTC)
    lo = epoch.addMSecs(round(lo_ns * 1000.0))
    hi = epoch.addMSecs(round(hi_ns * 1000.0))
    return QgsDateTimeRange(lo, hi)


def apply_temporal_properties(layer: QgsRasterLayer, plan: ExportPlan) -> None:
    """Wire the Temporal Controller's slider to `plan`'s bands, one-to-one.

    Order matters (verified directly against this QGIS build, 3.44.7):
    the ranges must be set before the mode is switched to
    `FixedRangePerBand`, and the mode before the properties are activated
    -- `metadata.txt`'s `qgisMinimumVersion=3.40` already guarantees the
    3.38+ this needs, so there is no fallback path to write for an older
    QGIS.
    """
    props = layer.temporalProperties()
    ranges = {
        index + 1: band_time_range(*window_times_ns(plan.z, band.window))
        for index, band in enumerate(plan.bands)
    }
    props.setFixedRangePerBand(ranges)
    props.setMode(Qgis.RasterTemporalMode.FixedRangePerBand)
    props.setIsActive(True)


def write_coverage(
    engine: SliceEngine, path: str | Path, *, writer: SliceWriter | None = None
) -> None:
    """A single-band, north-up raster of traces-per-cell over the full axis.

    `SliceCube.coverage()`'s own invariant (a cell is covered at every
    level or none) makes any window's coverage the whole cube's coverage,
    so the full axis is used here only to have a window to ask for -- not
    because coverage varies with depth.

    `radius_cells=None` on the plan: a coverage raster is never filled
    (see `ExportPlan`'s own docstring) -- smearing a count is not a
    display decision the way smearing an amplitude is, so there is no
    fill radius to record here. `writer` mirrors `export_slices`'s own
    substitution seam (Ruling AG).
    """
    frame, z = engine.frame, engine.z
    if frame is None or z is None:
        raise RuntimeError("no slice geometry: choose a source and a resolution first")
    window = SliceWindow(0, z.nz)
    _, coverage = engine.slice_at(window)
    plan = ExportPlan(
        frame=frame,
        z=z,
        crs=frame.crs,
        bands=(SliceBand(window=window, description="coverage: traces per cell"),),
        provenance=engine.provenance(),
        radius_cells=None,
    )
    writer = writer if writer is not None else GeoTiffSliceWriter()
    writer.write(path, plan, [coverage])


def save_cube_npz(engine: SliceEngine, path: str | Path) -> Path:
    """Save the engine's resident cube (built here if not already) to `.npz`.

    Returns the path numpy actually wrote, not `path` itself:
    `np.savez_compressed` APPENDS `.npz` unless the name already ends
    with it, and `store._npz_path` is the one place that rule already
    lives -- see its own docstring for why `Path.with_suffix` would be
    the wrong tool here.
    """
    save_cube(engine.cube(), path)
    return _npz_path(path)


@dataclass(frozen=True)
class ViewSettings:
    """What the reader had on screen when a cube was saved.

    Changes nothing in the array: two records that agree above `view` in
    `cube_record`'s split name the same `.npz` regardless of what this
    half says. Kept anyway because a saved cube with no record of how it
    was being looked at -- what palette, what stretch, whether coverage
    was showing -- is a worse artefact to hand to someone else than one
    that carries it.
    """

    thickness_ns: float
    step_ns: float
    radius_m: float
    palette: str
    stretch: str
    coverage: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "thickness_ns": self.thickness_ns,
            "step_ns": self.step_ns,
            "radius_m": self.radius_m,
            "palette": self.palette,
            "stretch": self.stretch,
            "coverage": self.coverage,
        }

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> ViewSettings:
        return cls(
            thickness_ns=float(doc["thickness_ns"]),
            step_ns=float(doc["step_ns"]),
            radius_m=float(doc["radius_m"]),
            palette=str(doc["palette"]),
            stretch=str(doc["stretch"]),
            coverage=bool(doc["coverage"]),
        )


def cube_record(
    session: Any,
    choice: SourceChoice,
    frame: CubeFrame,
    z: ZAxis,
    view: ViewSettings,
    npz_path: Path,
    *,
    line_keys: Sequence[str],
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

    `line_keys` is a required, explicit keyword -- deliberately NOT
    `choice.line_keys` (Ruling AF, Task 6 fix round 1). `choice` is what
    was ASKED for; `engine.provenance().line_keys` is what the cube was
    ACTUALLY built from, and the two disagree exactly when a line fails
    during preparation (already surfaced separately through `on_error` at
    that moment). `Site.cubes`'s own docstring calls `lines` "the line
    keys actually binned" -- a caller MUST pass
    `engine.provenance().line_keys` here, not `choice.line_keys`, or the
    record lies about what the array contains. Task 7's restore path
    reads this field to know which lines to re-bin; a requested-but-never-
    prepared line in it would fail that restore for a reason this record
    was supposed to rule out.
    """
    root = Path(session.json_path).parent.resolve()
    return {
        # --- what the cube IS: change any of these and the array changes ---
        "grid_id": choice.grid_id,
        "preset": choice.preset,
        "transform": choice.transform or "none",
        "cell": float(frame.cell),
        "lines": list(line_keys),
        "z": {"t0_ns": z.t0_ns, "t1_ns": z.t_end_ns, "dz_ns": z.dz_ns},
        "array": line_key(npz_path, root),
        # --- how it was BEING READ: changes nothing in the array ---
        "view": view.to_dict(),
    }
