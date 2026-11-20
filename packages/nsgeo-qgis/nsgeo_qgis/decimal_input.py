"""One rule for a typed decimal number, shared by every field that parses one.

No Qt or QGIS import: the pure tier tests it directly.
"""

from __future__ import annotations

import math


def parse_decimal(text: str) -> float:
    """`float(text.strip())`, refusing what a survey field must not guess at.

    A comma anywhere is refused: "1,000" and "1,5" cannot be told apart from
    the text alone (thousands separator vs. a European decimal comma), and
    silently picking one reading is a guess. NaN and the infinities parse in
    Python but are not values for a physical parameter. Raises ValueError;
    callers word their own messages.
    """
    if "," in text:
        raise ValueError(f"{text!r} has a comma")
    value = float(text.strip())
    if not math.isfinite(value):
        raise ValueError(f"{text!r} is not finite")
    return value
