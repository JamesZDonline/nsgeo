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
    migration,
    timecutoff,
    timezero,
    trace_stack,
)
from nsgeo.processing.base import (
    REQUIRED,
    STEP_GROUPS,
    ParamSpec,
    Radargram,
    Step,
    available_steps,
    build_step,
    default_params,
    get_step,
    grouped_steps,
    is_unipolar,
    nyquist_mhz,
    register,  # noqa: F401  (importable, not public)
    required_params,
    retime_ns,
    step_title,
)
from nsgeo.processing.stack import StepStack
from nsgeo.processing.timezero import (
    TIME_BASE_RADAR,
    TIME_BASE_TIME_ZERO,
    first_break_ns,
    sets_time_zero,
    time_base_of,
)

__all__ = [
    "ParamSpec",
    "REQUIRED",
    "Radargram",
    "STEP_GROUPS",
    "Step",
    "StepStack",
    "TIME_BASE_RADAR",
    "TIME_BASE_TIME_ZERO",
    "available_steps",
    "build_step",
    "default_params",
    "first_break_ns",
    "get_step",
    "grouped_steps",
    "is_unipolar",
    "nyquist_mhz",
    "required_params",
    "retime_ns",
    "sets_time_zero",
    "step_title",
    "time_base_of",
]
