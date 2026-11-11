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

* **North-up pitch is the cell, read bilinearly (whole-site fine-cells
  spec §3).** `to_north_up` samples every frame at its own cell, so no
  frame cell is dropped, and this writer just takes the pitch from the
  geotransform it returns. A coverage plan (`finish=None`) passes
  `counts=True`, so a count is never blended. History: Ruling AE wrote
  the frame's own cell size with a nearest-cell gather and recorded a
  15-18% loss at rotated azimuths; half the cell replaced it until the
  bilinear rule.
* **The per-band `cell_index` solve is planned once per frame.**
  `to_north_up`'s resample grid does not depend on the values being
  resampled, so the core keeps it per frame (`display._north_up_plan`) and
  every band after the first is one gather. Before that it was solved for
  every band: measured on a 400x300 frame at cell 0.05, 0.019 s
  axis-aligned, 0.112 s at 10.497 degrees (half-pitch sampling), about
  4.4 s over 39 bands on a rotated frame. The same plan serves
  `SliceLayer.update`'s ticks, so an export of the frame on screen starts
  with it already built.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from nsgeo.project import line_key
from nsgeo.slices import (
    CubeFrame,
    FinishSettings,
    Provenance,
    SliceWindow,
    ZAxis,
    npz_path,
    plan_windows,
    save_cube,
    to_north_up,
    window_label,
    window_times_ns,
)
from nsgeo.velocity import VelocityModel
from osgeo import gdal
from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsDateTimeRange, QgsRasterLayer
from qgis.PyQt.QtCore import QDate, QDateTime, Qt, QTime

from nsgeo_qgis.slices_engine import SliceEngine
from nsgeo_qgis.slices_plan import (
    DEFAULT_MAX_DISTANCE_SPACINGS,
    DEFAULT_METHOD,
    Resolution,
    SliceFinish,
    SourceChoice,
)


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

    `finish` is `None` for a plan that carries no interpolation at all
    (`write_coverage`'s companion raster is never finished -- coverage
    counts are exact, and smearing a count is not a display decision the
    way smearing an amplitude is). `GeoTiffSliceWriter.write` records it,
    in metres, and the frame's azimuth, as dataset-level metadata -- see
    Ruling AE (Task 6 fix round 1) for why: a reader five years from now
    with only the `.tif` in hand needs to see how the values were made
    (interpolated and smoothed) and on which frame (a rotated frame is
    resampled to north-up at the cell, bilinear) from the file itself.
    """

    frame: CubeFrame
    z: ZAxis
    crs: str
    bands: tuple[SliceBand, ...]
    provenance: Provenance
    finish: FinishSettings | None = None


def plan_export(
    engine: SliceEngine,
    thickness_levels: int,
    step_levels: int,
    velocity: VelocityModel | None,
    finish: FinishSettings | None = None,
) -> ExportPlan:
    """The band list a GeoTIFF export would write, without writing anything.

    `plan_windows` is spec 9.4's band-count formula by construction (see
    its own docstring), so `len(plan.bands)` and the dock's slice count
    are never two agreeing implementations, only one.

    `finish` is carried through onto the plan only -- it changes no band
    here, only what `GeoTiffSliceWriter.write` later records as metadata.
    Optional and keyword-compatible with every existing caller
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
        finish=finish,
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

    # Cheap cluster (final review): `Sequence[str]`, not `list[str]` -- a
    # `Protocol` attribute typed as a mutable container is INVARIANT, so a
    # writer declaring `OPTIONS` as a `tuple[str, ...]` (or any other
    # `Sequence`) would fail a static conformance check it need not; this
    # is read only, via `self.OPTIONS` inside `write`, never written.
    OPTIONS: Sequence[str]

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

        `plan.finish`/`plan.frame.azimuth` are written as dataset metadata
        once the dataset exists (Ruling AE, same fix round): a reader with
        only the `.tif` needs a way to see how the values were finished,
        and that a rotated frame was resampled, without this module's
        source in hand (see `ExportPlan`'s own docstring).
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
                        array, geotransform = to_north_up(
                            values, plan.frame, counts=plan.finish is None
                        )
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
                            if plan.finish is not None:
                                for key, value in (
                                    ("NSGEO_INTERPOLATION", plan.finish.method),
                                    ("NSGEO_MAX_DISTANCE_M", str(plan.finish.max_distance_m)),
                                    ("NSGEO_SMOOTH_X_M", str(plan.finish.smooth_x_m)),
                                    ("NSGEO_SMOOTH_Y_M", str(plan.finish.smooth_y_m)),
                                ):
                                    dataset.SetMetadataItem(key, value)
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


class ExportCancelled(Exception):
    """The user cancelled an export between two bands (plan call 11).

    Raised by the exporters when their `progress` callback returns False, so a
    caller can tell a cancel from a failure and report each in its own words.
    """


def export_slices(
    engine: SliceEngine,
    path: str | Path,
    thickness_levels: int,
    step_levels: int,
    velocity: VelocityModel | None,
    finish: SliceFinish,
    *,
    writer: SliceWriter | None = None,
    progress: Callable[[int, int], bool] | None = None,
) -> ExportPlan:
    """Plan, then write, one band at a time -- never a resident cube.

    `progress(done, total)`, when given, is called before each band with the
    bands written so far, and once more as `(total, total)` at the end. A False
    return raises `ExportCancelled` before the next band is computed: the call
    sits in the band generator, so the writers stay as they are. Every band is
    `engine.finish`, the full result, never a preview (plan call 11).

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
    plan = plan_export(
        engine, thickness_levels, step_levels, velocity, finish=engine.finish_settings(finish)
    )
    writer = writer if writer is not None else GeoTiffSliceWriter()

    def _finished_slices() -> Iterable[np.ndarray]:
        total = len(plan.bands)
        for done, band in enumerate(plan.bands):
            if progress is not None and not progress(done, total):
                raise ExportCancelled()
            yield engine.finish(*engine.slice_at(band.window), finish)
        if progress is not None:
            progress(total, total)

    writer.write(path, plan, _finished_slices())
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

    `finish=None` on the plan: a coverage raster is never finished
    (see `ExportPlan`'s own docstring) -- smearing a count is not a
    display decision the way smearing an amplitude is, so there is no
    interpolation to record here. `writer` mirrors `export_slices`'s own
    substitution seam (Ruling AG).

    Final review, Minor 7: `engine._slice(window)`, not `engine.slice_at
    (window)` -- `slice_at` is the TIMED entry point, and `_REDRAW_SMOOTHING
    = 0.7` means one full-axis pass through it (this call spans the whole
    z axis, not one displayed window) then inflates the status line's
    reported redraw time for many subsequent ticks. `_slice` is the
    untimed entry point that exists for exactly this -- see its own
    docstring ("used where a redraw timing would be a lie").

    Final review, Minor 8: the written array is `NaN`, not `0`, wherever
    `coverage` is zero -- the same "count == 0 -> NaN" the dock's own
    coverage VIEW already applies (`refresh_slice`). Spec 3's "a zero
    that means no data reading as no reflection" applies to this file
    just as much as to the screen: an uncovered in-frame cell written as
    a literal `0.0` sits against this band's own `NaN` nodata tag, so a
    reader has no way to tell "surveyed, zero count" (impossible -- count
    is never negative, and 0 always means uncovered) from "surveyed,
    zero amplitude" without already knowing this is a coverage band.
    """
    frame, z = engine.frame, engine.z
    if frame is None or z is None:
        raise RuntimeError("no slice geometry: choose a source and a resolution first")
    window = SliceWindow(0, z.nz)
    _, coverage = engine._slice(window)  # the untimed entry point; see the docstring above
    shown = coverage.astype(np.float32)
    shown[coverage == 0] = np.nan
    plan = ExportPlan(
        frame=frame,
        z=z,
        crs=frame.crs,
        bands=(SliceBand(window=window, description="coverage: traces per cell"),),
        provenance=engine.provenance(),
        finish=None,
    )
    writer = writer if writer is not None else GeoTiffSliceWriter()
    writer.write(path, plan, [shown])


def save_cube_npz(engine: SliceEngine, path: str | Path) -> Path:
    """Save the engine's resident cube (built here if not already) to `.npz`.

    Returns the path numpy actually wrote, not `path` itself:
    `np.savez_compressed` APPENDS `.npz` unless the name already ends
    with it, and `store.npz_path` is the one place that rule already
    lives -- see its own docstring for why `Path.with_suffix` would be
    the wrong tool here.

    Final review, Important 4: a "streaming"-mode engine drops the cube
    `cube()` just built for this write, once the write is done --
    `engine()` caches it into `_cube`, and nothing in "streaming" mode
    ever reads that back (`_slice`'s streaming branch calls `stream_slice`
    directly), so it was pure dead weight: `_mode` stays "streaming"
    (only `set_source`/`clear` ever touch it), and `format_status`
    branches on `_mode`, not on whether a cube happens to be cached, so
    the process silently held the whole volume on top of the prepared
    lines while the status line went on reporting only the latter -- 111
    MB unreported at spec 7.2's own 24-line/native-dz row, 359 MB at cell
    0.05 m. A "resident" engine keeps its cube: it already wanted one for
    faster redraws, and dropping it here would only force an immediate,
    wasted rebuild on the very next slice. See `SliceEngine.drop_cube`'s
    own docstring.
    """
    save_cube(engine.cube(), path)
    written = npz_path(path)
    if engine.mode == "streaming":
        engine.drop_cube()
    return written


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
    # The finish (interpolation spec §8). `radius_m` stays and is still
    # written, because 0.2.0's reader requires it; this build ignores it.
    method: str = DEFAULT_METHOD
    max_distance_spacings: float = DEFAULT_MAX_DISTANCE_SPACINGS
    smooth_x_m: float = 0.0
    smooth_y_m: float = 0.0

    @property
    def finish(self) -> SliceFinish:
        return SliceFinish(
            self.method, self.max_distance_spacings, self.smooth_x_m, self.smooth_y_m
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "thickness_ns": self.thickness_ns,
            "step_ns": self.step_ns,
            "radius_m": self.radius_m,
            "palette": self.palette,
            "stretch": self.stretch,
            "coverage": self.coverage,
            "method": self.method,
            "max_distance_spacings": self.max_distance_spacings,
            "smooth_x_m": self.smooth_x_m,
            "smooth_y_m": self.smooth_y_m,
        }

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> ViewSettings:
        # A 0.2.0 record has no "method": it opens on the defaults, its
        # `radius_m` read for the record's sake and never mapped onto them.
        finish = SliceFinish().updated(doc) if "method" in doc else SliceFinish()
        return cls(
            thickness_ns=float(doc["thickness_ns"]),
            step_ns=float(doc["step_ns"]),
            radius_m=float(doc.get("radius_m", 0.0)),
            palette=str(doc["palette"]),
            stretch=str(doc["stretch"]),
            # `.get(..., False)`, not `doc["coverage"]` (Task 7): tolerant
            # of a `view` dict that carries the other five fields but not
            # this one -- the same reader-tolerance this module's `Task 7`
            # functions extend to the record as a whole.
            coverage=bool(doc.get("coverage", False)),
            method=finish.method,
            max_distance_spacings=finish.max_distance_spacings,
            smooth_x_m=finish.smooth_x_m,
            smooth_y_m=finish.smooth_y_m,
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

    Final review, Minor 10: `t1_ns` is `z.t_end_ns` for every `nz > 1`
    (unchanged -- Task 7's Ruling AJ carefully tuned `z1_spin`'s decimals
    around exactly this value, and that precision story is untouched
    here), but `z.t_end_ns = t0_ns + (nz - 1) * dz_ns` EQUALS `t0_ns`
    itself when `nz == 1` (reachable: any `0 < z1_requested - z0 < dz_ns`
    bins to a single level). `Resolution.__post_init__` requires `t1_ns`
    strictly greater than `t0_ns` -- so a record written for a genuine
    one-level cube had `t0_ns == t1_ns`, and `restore_cube` refused a
    record this same function had just written. `t0_ns + dz_ns * 0.5`
    sits strictly inside `(t0_ns, t0_ns + dz_ns)`, which is exactly the
    condition `ZAxis.from_range` needs to reconstruct `nz == 1` again --
    the exact VALUE within that interval does not matter (any span in
    `(0, 1)` levels does), so this is not sensitive to `z1_spin`'s decimal
    precision the way the `nz > 1` case is.
    """
    root = Path(session.json_path).parent.resolve()
    t1_ns = z.t_end_ns if z.nz > 1 else z.t0_ns + z.dz_ns * 0.5
    return {
        # --- what the cube IS: change any of these and the array changes ---
        "grid_id": choice.grid_id,
        "preset": choice.preset,
        "transform": choice.transform or "none",
        "cell": float(frame.cell),
        "lines": list(line_keys),
        "z": {"t0_ns": z.t0_ns, "t1_ns": t1_ns, "dz_ns": z.dz_ns},
        "array": line_key(npz_path, root),
        # --- how it was BEING READ: changes nothing in the array ---
        "view": view.to_dict(),
    }


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

    `transform`'s "none" <-> `NO_TRANSFORM` ("") mapping is the one place
    the record's spelling and `SourceChoice`'s meet -- see `cube_record`'s
    own docstring for why the record spells it "none" at all.

    `line_keys` reads back as `()` both when `record["lines"]` is an
    explicit empty list and when the key is absent entirely (an
    old-format record) -- this function cannot tell those two apart from
    the record alone, and does not try to; both mean "no line list to
    restore".
    """
    try:
        choice = SourceChoice(
            grid_id=str(record["grid_id"]),
            preset=str(record["preset"]),
            transform=(
                "" if record.get("transform", "none") == "none" else str(record["transform"])
            ),
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
