"""Time and depth slices: binning survey lines into a volume and cutting it.

Nothing here runs automatically. A cube is built from an explicitly chosen
preset, the same rule the step stack follows.
"""

from __future__ import annotations

from nsgeo.slices.binning import (  # noqa: F401
    CoverageError,
    LinePlan,
    PreparedLine,
    build_cube,
    plan_line,
    stream_slice,
)
from nsgeo.slices.cube import Provenance, SliceCube  # noqa: F401
from nsgeo.slices.fill import disc_kernel, fill  # noqa: F401
from nsgeo.slices.frame import CubeFrame, ZAxis  # noqa: F401
