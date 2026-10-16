"""Where the shipped help pages live. Pure: no Qt, so tests import it anywhere."""

from __future__ import annotations

from pathlib import Path

HELP_DIR = Path(__file__).parent / "help"


def page_path(step_name: str) -> Path | None:
    """The help page for `step_name`, or None when that file isn't there.

    Reads `HELP_DIR` at call time so a test can point it elsewhere.
    """
    path = HELP_DIR / f"{step_name}.html"
    return path if path.is_file() else None
