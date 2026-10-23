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
from nsgeo.slices.site import (
    AXIS_SNAP_CELLS,
    BACKGROUND_FRACTION,
    MIN_SEAM_CELLS,
    NORMALISATION_METHODS,
    SEAM_WIDTH_SPACINGS,
    Footprint,
    Seam,
    SiteLattice,
    background_level,
    compose,
    compose_footprints,
    edge_match_solve,
    find_seams,
    footprint,
    grid_axis,
    lattice_pixel,
    normalise,
    seam_masks,
    site_axis,
    snap_azimuth,
    window_on,
)
from nsgeo.slices.store import CubeStoreError, load_cube, npz_path, save_cube

__all__ = [
    "AXIS_SNAP_CELLS",
    "BACKGROUND_FRACTION",
    "CoverageError",
    "CubeFrame",
    "CubeStoreError",
    "Footprint",
    "LinePlan",
    "MIN_SEAM_CELLS",
    "NORMALISATION_METHODS",
    "PreparedLine",
    "Provenance",
    "SEAM_WIDTH_SPACINGS",
    "Seam",
    "SiteLattice",
    "SliceCube",
    "SliceWindow",
    "ZAxis",
    "background_level",
    "build_cube",
    "clear_kernel_cache",
    "compose",
    "compose_footprints",
    "disc_kernel",
    "edge_match_solve",
    "fill",
    "find_seams",
    "footprint",
    "grid_axis",
    "lattice_pixel",
    "limit_over_slices",
    "load_cube",
    "normalise",
    "npz_path",
    "plan_line",
    "plan_windows",
    "save_cube",
    "seam_masks",
    "shared_limit",
    "site_axis",
    "slice_extent",
    "snap_azimuth",
    "stream_slice",
    "to_north_up",
    "window_depths_m",
    "window_label",
    "window_on",
    "window_times_ns",
]
