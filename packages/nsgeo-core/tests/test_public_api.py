"""The core's supported surface is exactly what its `__all__` lists name."""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import nsgeo
import pytest

from tests.public_modules import public_modules

# From this file, not `nsgeo.__file__`, so the README is found whether the
# core is installed editable, installed normally, or put on sys.path.
README = Path(__file__).resolve().parents[1] / "README.md"
EXPECTED_PUBLIC = {
    "destagger",
    "io",
    "model",
    "geometry",
    "hyperbola_trace",
    "processing",
    "slices",
    "project",
    "render",
    "velocity",
    "velocity_fit",
    "velocity_source",
    "vtkxml",
}


def test_the_public_modules_are_exactly_the_named_ones() -> None:
    # The same discovery the plugin's import-boundary test uses.
    assert set(public_modules(Path(nsgeo.__file__).parent)) == EXPECTED_PUBLIC


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


def readme_sections(text: str) -> dict[str, str]:
    """Module name -> the README text under its `nsgeo.<name>` heading (level
    3), up to the next heading of level 3 or above."""
    sections: dict[str, str] = {}
    current: str | None = None
    for line in text.splitlines():
        heading = re.match(r"#{1,3} ", line)
        if heading:
            m = re.fullmatch(r"### `nsgeo\.(\w+)`\s*", line)
            current = m.group(1) if m else None
            if current is not None:
                assert current not in sections, f"two sections for nsgeo.{current}"
                sections[current] = ""
        elif current is not None:
            sections[current] += line + "\n"
    return sections


def test_readme_sections_stop_at_the_next_heading() -> None:
    text = "### `nsgeo.a`\n`x`\n#### detail\n`y`\n### `nsgeo.b`\n`z`\n## Other\n`w`\n"
    assert readme_sections(text) == {"a": "`x`\n#### detail\n`y`\n", "b": "`z`\n"}


def test_the_readme_names_every_public_name_in_its_own_module_table() -> None:
    sections = readme_sections(README.read_text(encoding="utf-8"))
    assert set(sections) == EXPECTED_PUBLIC
    missing = [
        f"{m}.{n}"
        for m in sorted(EXPECTED_PUBLIC)
        for n in importlib.import_module(f"nsgeo.{m}").__all__
        if f"`{n}`" not in sections[m]
    ]
    assert not missing, missing
