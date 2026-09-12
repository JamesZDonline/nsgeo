"""The plugin must contain no signal processing and no direct PyQt imports.

Direct `PyQt5`/`PyQt6` imports break on the other Qt major version; the
`qgis.PyQt` shim works on both. Importing processing internals would let
maths creep into widgets, which is the boundary the whole design rests on.
"""

from __future__ import annotations

import ast
from pathlib import Path

import nsgeo_qgis

SRC = Path(nsgeo_qgis.__file__).parent

FORBIDDEN_ROOTS = {"PyQt5", "PyQt6", "PySide2", "PySide6", "matplotlib", "scipy"}
ALLOWED_FROM_PROCESSING = {
    "StepStack",
    "Step",
    "build_step",
    "available_steps",
    "get_step",
    "Radargram",
    "ParamSpec",
    "REQUIRED",
    "default_params",
    "required_params",
    # Pure arithmetic (Nyquist frequency from a sample interval), not signal
    # processing: shared so the plugin's "this file's Nyquist" fact and
    # Bandpass's own guard use one formula instead of two that can drift.
    "nyquist_mhz",
}


def _py_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "_vendor" not in p.parts)


def test_src_tree_is_actually_being_scanned() -> None:
    assert len(_py_files()) >= 2


def test_no_direct_qt_or_forbidden_imports() -> None:
    offenders = []
    for path in _py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module.split(".")[0]]
            bad = set(names) & FORBIDDEN_ROOTS
            if bad:
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}: {sorted(bad)}")
    assert not offenders, "forbidden imports:\n" + "\n".join(offenders)


def _processing_offenders(path: Path) -> list[tuple[int, str]]:
    """(lineno, message) for each disallowed use of nsgeo.processing in `path`.

    Standalone so it can be proven against a scratch file directly, not only
    through the package tree the test below scans.
    """
    offenders: list[tuple[int, str]] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "nsgeo.processing":
                bad = {a.name for a in node.names} - ALLOWED_FROM_PROCESSING
                if bad:
                    offenders.append((node.lineno, str(sorted(bad))))
            elif node.module.startswith("nsgeo.processing."):
                offenders.append((node.lineno, node.module))
            elif node.module == "nsgeo" and any(a.name == "processing" for a in node.names):
                # `from nsgeo import processing` (or `... as X`) reaches the
                # same internals as `import nsgeo.processing` — both forbidden.
                offenders.append((node.lineno, "from nsgeo import processing"))
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("nsgeo.processing"):
                    offenders.append((node.lineno, f"import {a.name}"))
    return offenders


def test_processing_is_used_only_through_its_public_surface() -> None:
    offenders = []
    for path in _py_files():
        for lineno, msg in _processing_offenders(path):
            offenders.append(f"{path.relative_to(SRC)}:{lineno}: {msg}")
    assert not offenders, "processing internals imported by the plugin:\n" + "\n".join(offenders)


def test_package_init_imports_no_qgis_at_module_level() -> None:
    """The pure test tier and the zip's shim both import the package without
    a QGIS runtime. classFactory imports qgis lazily."""
    tree = ast.parse((SRC / "__init__.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(a.name.split(".")[0] == "qgis" for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("qgis")
