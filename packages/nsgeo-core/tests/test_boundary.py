"""The core must never import QGIS, Qt, matplotlib, or scipy at module level.

This is what makes a single repository safe: the rule fails the build rather
than relying on vigilance. It also catches scipy becoming a hard dependency
and matplotlib appearing at all, neither of which a repo split would catch.
"""

from __future__ import annotations

import ast
import pathlib

import nsgeo

SRC = pathlib.Path(nsgeo.__file__).parent

FORBIDDEN = {"qgis", "PyQt5", "PyQt6", "PySide2", "PySide6", "matplotlib", "scipy"}


def _module_level_imports(tree: ast.Module) -> set[str]:
    """Top-level import names only. Imports inside functions are allowed,
    which is how scipy may be used as an optional accelerator."""
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_no_forbidden_module_level_imports() -> None:
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        bad = _module_level_imports(tree) & FORBIDDEN
        if bad:
            offenders.append(f"{path.relative_to(SRC)}: {sorted(bad)}")
    assert not offenders, "forbidden module-level imports:\n" + "\n".join(offenders)


def test_src_tree_is_actually_being_scanned() -> None:
    """Guards against the test silently passing because it found no files."""
    assert len(list(SRC.rglob("*.py"))) >= 1
