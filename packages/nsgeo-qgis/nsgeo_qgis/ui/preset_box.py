"""The preset box's helpers: the sentence that says what a Migration step carries."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

MIGRATION_STEP = "migrate_fk"
MIGRATION_TITLE = "Migration (Stolt f-k)"


def migration_note(dicts: Sequence[dict[str, Any]], *, saved: bool) -> str | None:
    """The sentence for a preset or stack with an enabled Migration step, or None.

    Reads the first enabled `migrate_fk` entry's velocity. `saved` says the
    velocity is one the step was saved with, not one a line will resolve to.
    """
    for entry in dicts:
        if entry.get("step") == MIGRATION_STEP and entry.get("enabled", True):
            v = float(entry["params"]["velocity_m_ns"])
            tail = ", the velocity it was saved with" if saved else ""
            return f"Its {MIGRATION_TITLE} step uses {v:.3f} m/ns{tail}."
    return None
