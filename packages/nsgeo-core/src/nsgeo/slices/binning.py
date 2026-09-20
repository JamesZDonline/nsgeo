"""Turning prepared lines into a cube.

Two things are precomputed per line, because each changes only when its own
input changes: the source (index, weight) pair per target level, which
depends on the z axis and the line's own dt and t0; and the trace ordering
by cell, which depends on the cell size. With both in hand a rebuild is two
gathers, one `reduceat` and a scatter -- no Python loop over cells or
levels.

The inputs are already-prepared lines: loaded, run through a preset, and
transformed. That tier is the expensive one and the caller caches it; it is
deliberately not this module's business.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from nsgeo.slices.cube import Provenance, SliceCube
from nsgeo.slices.frame import CubeFrame, ZAxis


class CoverageError(Exception):
    """A line cannot contribute to the requested cube."""


@dataclass(frozen=True)
class PreparedLine:
    """One line, already processed and transformed, ready to bin.

    `data` is (n_samples, n_traces); `coords` is (n_traces, 2) in the
    frame's CRS. Trace index is the join between them, which is the same
    invariant the profile viewer relies on.
    """

    key: str
    data: np.ndarray
    dt_ns: float
    t0_ns: float
    coords: np.ndarray

    def __post_init__(self) -> None:
        if self.data.ndim != 2:
            raise ValueError(f"data must be 2-D, got {self.data.shape}")
        if self.coords.shape != (self.data.shape[1], 2):
            raise ValueError(
                f"line {self.key!r}: {self.data.shape[1]} traces but "
                f"{self.coords.shape} coordinates"
            )


@dataclass(frozen=True)
class LinePlan:
    """Everything about one line that does not change when the window moves.

    `frame` and `z` are the two inputs the plan was built against, carried
    along purely so `build_cube` and `stream_slice` can catch a stale plan.
    Neither is used for anything else here -- the arrays above are already
    the fully-resolved result of resampling against `z` and binning against
    `frame`, so recomputing from these fields would be redundant, not an
    alternative source of truth.
    """

    z_index: np.ndarray
    z_weight: np.ndarray
    order: np.ndarray
    starts: np.ndarray
    cells: np.ndarray
    counts: np.ndarray
    frame: CubeFrame
    z: ZAxis


def plan_line(line: PreparedLine, frame: CubeFrame, z: ZAxis) -> LinePlan:
    """Precompute the resampling and grouping for one line.

    Raises CoverageError rather than zero-padding a line whose recording
    window is shorter than the cube's: a padded level would be counted as
    data and read as a dead zone at that depth.
    """
    n_samples = line.data.shape[0]
    if n_samples < 2:
        raise CoverageError(f"line {line.key!r} has {n_samples} samples; need at least 2")
    line_end = line.t0_ns + (n_samples - 1) * line.dt_ns
    tol = 1e-9
    if z.t0_ns < line.t0_ns - tol or z.t_end_ns > line_end + tol:
        raise CoverageError(
            f"line {line.key!r} spans {line.t0_ns:.3f}..{line_end:.3f} ns, which does "
            f"not cover the cube's {z.t0_ns:.3f}..{z.t_end_ns:.3f} ns; shrink the z "
            f"range or exclude the line"
        )

    position = (z.times_ns() - line.t0_ns) / line.dt_ns
    z_index = np.clip(np.floor(position).astype(np.intp), 0, n_samples - 2)
    z_weight = (position - z_index).astype(np.float32)[:, None]

    ids = frame.cell_index(line.coords)
    keep = np.flatnonzero(ids >= 0)
    if keep.size == 0:
        raise CoverageError(f"line {line.key!r} has no traces inside the cube frame")
    order = keep[np.argsort(ids[keep], kind="stable")]
    sorted_ids = ids[order]
    starts = np.flatnonzero(np.concatenate([[True], sorted_ids[1:] != sorted_ids[:-1]]))
    run_ends = np.concatenate([starts[1:], [sorted_ids.size]])
    return LinePlan(
        z_index=z_index,
        z_weight=z_weight,
        order=order,
        starts=starts,
        cells=sorted_ids[starts],
        counts=(run_ends - starts).astype(np.int32),
        frame=frame,
        z=z,
    )


def resample_window(line: PreparedLine, plan: LinePlan, k0: int, k1: int) -> np.ndarray:
    """(k1 - k0, n_kept) float32: the line's levels, in cell-sorted order."""
    index = plan.z_index[k0:k1]
    weight = plan.z_weight[k0:k1]
    lower = line.data[index][:, plan.order]
    upper = line.data[index + 1][:, plan.order]
    return (lower * (1.0 - weight) + upper * weight).astype(np.float32, copy=False)


def accumulate(
    total: np.ndarray,
    count: np.ndarray,
    line: PreparedLine,
    plan: LinePlan,
) -> None:
    """Add one line's contribution over the whole axis, in place.

    Takes the level count from `total.shape[0]` rather than a caller-given
    (k0, k1): `build_cube` is the only caller and always covers the full
    axis, and a partial window here would silently double-count `count` if
    ever called more than once per line. A parameter that produces a wrong
    count when used as its name suggests is worse than no parameter, so
    there is none -- `resample_window` still takes an explicit window for
    the caller that legitimately wants one.
    """
    block = resample_window(line, plan, 0, total.shape[0])
    total[:, plan.cells] += np.add.reduceat(block, plan.starts, axis=1)
    count[plan.cells] += plan.counts


def _check_plans_current(
    lines: Sequence[PreparedLine],
    plans: Sequence[LinePlan],
    frame: CubeFrame,
    z: ZAxis,
) -> None:
    """Reject any plan not built against this exact (frame, z).

    Compares `frame` and `z` individually rather than the whole `LinePlan`:
    a `LinePlan` carries ndarrays, and comparing those with `==` raises
    "truth value of an array is ambiguous" instead of a clean answer.
    `CubeFrame` and `ZAxis` are frozen, all-scalar dataclasses, so `!=` on
    either is cheap, total, and exactly the comparison that matters -- a
    plan's arrays are a function of these two objects and nothing else, so
    if both still match, the arrays are still correct.

    This is the only guard against a live cell-size or z-range slider in
    the plugin reusing a plan computed for the frame or axis before the
    drag: a stale `cell` silently rebins every trace into the wrong cell
    (never raising, because a stale-but-in-bounds id looks like a real
    one), and a stale `t0_ns` silently mislabels every returned time.
    """
    for line, plan in zip(lines, plans):
        if plan.frame != frame or plan.z != z:
            mismatches = []
            if plan.frame != frame:
                mismatches.append(f"frame {plan.frame!r} != current {frame!r}")
            if plan.z != z:
                mismatches.append(f"z {plan.z!r} != current {z!r}")
            raise ValueError(
                f"line {line.key!r}: plan is stale ({'; '.join(mismatches)}) -- "
                f"call plan_line() again against the current frame and z axis "
                f"before binning"
            )


def build_cube(
    lines: Sequence[PreparedLine],
    plans: Sequence[LinePlan],
    frame: CubeFrame,
    z: ZAxis,
    provenance: Provenance,
) -> SliceCube:
    """Bin every line into a resident cube."""
    if len(lines) != len(plans):
        raise ValueError(f"got {len(lines)} lines and {len(plans)} plans")
    _check_plans_current(lines, plans, frame, z)
    total = np.zeros((z.nz, frame.n_cells), dtype=np.float32)
    count = np.zeros(frame.n_cells, dtype=np.int32)
    for line, plan in zip(lines, plans):
        accumulate(total, count, line, plan)
    mean = np.divide(total, count, out=np.full_like(total, np.nan), where=count > 0)
    return SliceCube(frame=frame, z=z, mean=mean, count=count, provenance=provenance)


def stream_slice(
    lines: Sequence[PreparedLine],
    plans: Sequence[LinePlan],
    frame: CubeFrame,
    z: ZAxis,
    k0: int,
    k1: int,
) -> tuple[np.ndarray, np.ndarray]:
    """One slice, binned straight from the lines, holding no cube.

    This is the default residency. It is the same algorithm as `build_cube`
    restricted to the levels in the window, and a property test asserts the
    two agree -- if they ever diverge, the mode a user is in would change
    what they see.

    Returns (values, coverage), both shaped (ny, nx); values is NaN where
    coverage is zero.
    """
    if len(lines) != len(plans):
        raise ValueError(f"got {len(lines)} lines and {len(plans)} plans")
    _check_plans_current(lines, plans, frame, z)
    if not 0 <= k0 < k1 <= z.nz:
        raise ValueError(f"level window must satisfy 0 <= k0 < k1 <= {z.nz}, got {k0}..{k1}")
    n_levels = k1 - k0
    total = np.zeros(frame.n_cells, dtype=np.float32)
    count = np.zeros(frame.n_cells, dtype=np.int64)
    for line, plan in zip(lines, plans):
        block = resample_window(line, plan, k0, k1)
        total[plan.cells] += np.add.reduceat(block, plan.starts, axis=1).sum(axis=0)
        count[plan.cells] += plan.counts.astype(np.int64) * n_levels
    values = np.divide(
        total, count, out=np.full(frame.n_cells, np.nan, dtype=np.float32), where=count > 0
    )
    coverage = (count // n_levels).astype(np.int32)
    return (
        values.reshape(frame.ny, frame.nx),
        coverage.reshape(frame.ny, frame.nx),
    )
