"""User-ordered processing steps. Nothing here runs automatically.

Importing this package registers every built-in step, so `build_step` and
`available_steps` work without the caller importing each module.
"""

from __future__ import annotations

from nsgeo.processing import (  # noqa: F401
    background,
    bandpass,
    dewow,
    gain,
    timezero,
)
from nsgeo.processing.base import (  # noqa: F401
    REQUIRED,
    ParamSpec,
    Radargram,
    Step,
    available_steps,
    build_step,
    default_params,
    get_step,
    register,
    required_params,
)
from nsgeo.processing.stack import StepStack  # noqa: F401
