"""`tests/conftest.py` puts the dev scripts on sys.path behind the standard library.

Ahead of it, a script named like a stdlib module (a `json.py`, say) would be
imported in place of the real module by every test.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def test_scripts_come_after_the_standard_library_on_sys_path():
    entries = [os.path.realpath(p) for p in sys.path]
    stdlib = os.path.realpath(os.path.dirname(os.__file__))
    scripts = os.path.realpath(SCRIPTS)
    assert scripts in entries, "conftest no longer puts scripts/ on sys.path"
    assert entries.index(scripts) > entries.index(stdlib)
