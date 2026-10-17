"""User-ordered processing steps. Nothing here runs automatically.

Importing this package registers every built-in step, so `build_step` and
`available_steps` work without the caller importing each module.
"""

from __future__ import annotations

from nsgeo.processing import (  # noqa: F401  (registers the built-in steps)
    amplitude,
    background,
    bandpass,
    dewow,
    gain,
    timezero,
)
from nsgeo.processing.base import (
    REQUIRED,
    ParamSpec,
    Radargram,
    Step,
    available_steps,
    build_step,
    default_params,
    get_step,
    is_unipolar,
    nyquist_mhz,
    register,  # noqa: F401  (importable, not public)
    required_params,
)
from nsgeo.processing.stack import StepStack

__all__ = [
    "ParamSpec",
    "REQUIRED",
    "Radargram",
    "Step",
    "StepStack",
    "available_steps",
    "build_step",
    "default_params",
    "get_step",
    "is_unipolar",
    "nyquist_mhz",
    "required_params",
]
