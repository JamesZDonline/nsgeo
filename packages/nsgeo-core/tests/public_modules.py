"""Which `nsgeo` modules are public, read from the source.

Shared by the core's own API test (`test_public_api.py`) and the plugin's
import-boundary test (`packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py`),
so the two cannot disagree about what "public" means.

A public module is one level below `nsgeo` (`x/__init__.py` or `x.py`), not
named with a leading underscore, that assigns `__all__` a list or tuple
literal at top level.
"""

from __future__ import annotations

import ast
from pathlib import Path


def declared_all(path: Path) -> set[str] | None:
    """The names in a module's top-level `__all__` literal, or None if it has none."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets)
            and isinstance(node.value, (ast.List, ast.Tuple))
        ):
            return {
                e.value
                for e in node.value.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            }
    return None


def public_modules(package_dir: Path) -> dict[str, set[str]]:
    """Public module name (`"slices"`, not `"nsgeo.slices"`) -> its `__all__`."""
    found: dict[str, set[str]] = {}
    for child in sorted(package_dir.iterdir()):
        if child.name.startswith("_"):
            continue
        source = child / "__init__.py" if child.is_dir() else child
        if source.suffix != ".py" or not source.is_file():
            continue
        names = declared_all(source)
        if names is not None:
            found[child.stem] = names
    return found
