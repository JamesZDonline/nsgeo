"""The core's supported surface is exactly what its `__all__` lists name."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import nsgeo
import pytest

CORE = Path(nsgeo.__file__).parents[2]
EXPECTED_PUBLIC = {
    "io",
    "model",
    "geometry",
    "processing",
    "slices",
    "project",
    "render",
    "velocity",
}


def _declares_all(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return any(
        isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets)
        for node in tree.body
    )


def public_modules() -> set[str]:
    """Names one level below `nsgeo` (`x/__init__.py` or `x.py`) that declare `__all__`."""
    root = Path(nsgeo.__file__).parent
    found = set()
    for child in root.iterdir():
        if child.name.startswith("_"):
            continue
        source = child / "__init__.py" if child.is_dir() else child
        if source.suffix == ".py" and source.is_file() and _declares_all(source):
            found.add(child.stem)
    return found


def test_the_public_modules_are_exactly_the_named_ones() -> None:
    assert public_modules() == EXPECTED_PUBLIC


@pytest.mark.parametrize("name", sorted(EXPECTED_PUBLIC))
def test_every_public_name_resolves_and_none_is_private(name: str) -> None:
    mod = importlib.import_module(f"nsgeo.{name}")
    assert mod.__all__ == sorted(mod.__all__)
    for n in mod.__all__:
        assert not n.startswith("_") and hasattr(mod, n), n


def test_top_level_exports_only_the_version() -> None:
    assert nsgeo.__all__ == ["__version__"]


def test_register_is_not_public() -> None:
    processing = importlib.import_module("nsgeo.processing")
    assert "register" not in processing.__all__


def test_the_readme_names_every_public_name() -> None:
    text = (CORE / "README.md").read_text(encoding="utf-8")
    missing = [
        f"{m}.{n}"
        for m in sorted(EXPECTED_PUBLIC)
        for n in importlib.import_module(f"nsgeo.{m}").__all__
        if f"`{n}`" not in text
    ]
    assert not missing, missing
