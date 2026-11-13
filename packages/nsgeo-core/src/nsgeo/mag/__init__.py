"""Magnetometer data: Bartington Grad601 files, their setup, and traverses placed in a grid."""

from __future__ import annotations

from nsgeo.mag.file import MagFile, clear_mag_cache
from nsgeo.mag.grad601 import MISSING_RUN, MagFileError, mark_missing, missing_summary, read_grad601
from nsgeo.mag.setup import MagSetup, fit_problems
from nsgeo.mag.traverses import Traverse, traverses, walked_direction

__all__ = [
    "MISSING_RUN",
    "MagFile",
    "MagFileError",
    "MagSetup",
    "Traverse",
    "clear_mag_cache",
    "fit_problems",
    "mark_missing",
    "missing_summary",
    "read_grad601",
    "traverses",
    "walked_direction",
]
