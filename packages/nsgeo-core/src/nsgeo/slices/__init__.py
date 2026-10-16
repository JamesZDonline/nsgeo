"""Time and depth slices: binning survey lines into a volume and cutting it.

Nothing here runs automatically. A cube is built from an explicitly chosen
preset, the same rule the step stack follows.
"""

from __future__ import annotations

from nsgeo.slices.binning import (
    CoverageError,
    LinePlan,
    PreparedLine,
    build_cube,
    plan_line,
    stream_slice,
)
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
from nsgeo.slices.fill import clear_kernel_cache, disc_kernel, fill
from nsgeo.slices.frame import CubeFrame, ZAxis, slice_extent
from nsgeo.slices.store import CubeStoreError, load_cube, npz_path, save_cube

__all__ = [
    "CoverageError",
    "CubeFrame",
    "CubeStoreError",
    "LinePlan",
    "PreparedLine",
    "Provenance",
    "SliceCube",
    "SliceWindow",
    "ZAxis",
    "build_cube",
    "clear_kernel_cache",
    "disc_kernel",
    "fill",
    "limit_over_slices",
    "load_cube",
    "npz_path",
    "plan_line",
    "plan_windows",
    "save_cube",
    "shared_limit",
    "slice_extent",
    "stream_slice",
    "to_north_up",
    "window_depths_m",
    "window_label",
    "window_times_ns",
]
