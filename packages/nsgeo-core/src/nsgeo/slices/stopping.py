"""The one exception a plan or solve raises when asked to stop.

Here, not in `curvature.py`: `interpolate.py` raises it too, and `curvature.py`
imports `interpolate.py`.
"""

from __future__ import annotations


class SolveStopped(Exception):
    """A plan or solve gave up because `should_stop` asked it to."""
