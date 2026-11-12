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
    covered_cells,
    plan_line,
    stream_slice,
)
from nsgeo.slices.cube import CubeBlock, Provenance, SliceCube
from nsgeo.slices.curvature import CurvaturePlan, SolveStopped, plan_curvature
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
from nsgeo.slices.finish import FinishSettings, finish_slice
from nsgeo.slices.frame import CubeFrame, ZAxis, slice_extent
from nsgeo.slices.interpolate import (
    METHODS,
    NEIGHBOURS_PER_QUADRANT,
    FillWeights,
    SliceFill,
    plan_fill,
)
from nsgeo.slices.resample import Taps, bilinear_taps, max_pool_counts, sample, sample_counts
from nsgeo.slices.site import (
    BACKGROUND_FRACTION,
    MIN_SEAM_CELLS,
    NORMALISATION_METHODS,
    SEAM_WIDTH_SPACINGS,
    Footprint,
    Seam,
    SiteLattice,
    background_level,
    compose_footprints,
    covered_pixels,
    edge_match_solve,
    find_seams,
    finest_fitting_cell,
    fitting_lattice,
    footprint,
    grid_axis,
    normalise,
    seam_masks,
    site_axis,
    stretching_grids,
    window_on,
)
from nsgeo.slices.smooth import smooth
from nsgeo.slices.store import CubeStoreError, load_cube, npz_path, save_cube
from nsgeo.slices.volume import (
    PreparedVolume,
    VolumeSettings,
    VolumeStopped,
    depth_axis,
    fill_levels,
    prepare_volume,
)

__all__ = [
    "BACKGROUND_FRACTION",
    "CoverageError",
    "CubeBlock",
    "CubeFrame",
    "CubeStoreError",
    "CurvaturePlan",
    "FillWeights",
    "FinishSettings",
    "Footprint",
    "LinePlan",
    "METHODS",
    "MIN_SEAM_CELLS",
    "NEIGHBOURS_PER_QUADRANT",
    "NORMALISATION_METHODS",
    "PreparedLine",
    "PreparedVolume",
    "Provenance",
    "SEAM_WIDTH_SPACINGS",
    "Seam",
    "SiteLattice",
    "SliceCube",
    "SliceFill",
    "SliceWindow",
    "SolveStopped",
    "Taps",
    "VolumeSettings",
    "VolumeStopped",
    "ZAxis",
    "background_level",
    "bilinear_taps",
    "build_cube",
    "compose_footprints",
    "covered_cells",
    "covered_pixels",
    "depth_axis",
    "edge_match_solve",
    "fill_levels",
    "find_seams",
    "finest_fitting_cell",
    "finish_slice",
    "fitting_lattice",
    "footprint",
    "grid_axis",
    "limit_over_slices",
    "load_cube",
    "max_pool_counts",
    "normalise",
    "npz_path",
    "plan_curvature",
    "plan_fill",
    "plan_line",
    "plan_windows",
    "prepare_volume",
    "sample",
    "sample_counts",
    "save_cube",
    "seam_masks",
    "shared_limit",
    "site_axis",
    "slice_extent",
    "smooth",
    "stream_slice",
    "stretching_grids",
    "to_north_up",
    "window_depths_m",
    "window_label",
    "window_on",
    "window_times_ns",
]
