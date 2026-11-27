"""The plugin imports no Qt binding directly, and only the core's named API.

Direct `PyQt5`/`PyQt6` imports break on the other Qt major version; the
`qgis.PyQt` shim works on both. matplotlib and scipy are not in the QGIS
images the plugin runs in.

The core's named API is what its public modules list in `__all__` (see
`packages/nsgeo-core/README.md`). Reaching past it, into a submodule or a
name it does not list, ties the plugin to the core's internals, which may
change without notice. Signal processing stays in the core: for example
`nsgeo.processing` lists `nyquist_mhz`, the Nyquist frequency of a sample
interval, so that the add-step dialog's "this file's Nyquist" figure and
Bandpass's own guard use one formula instead of two that can drift apart.
"""

from __future__ import annotations

import ast
from pathlib import Path

import nsgeo
import nsgeo_qgis
from tests.public_modules import public_modules

SRC = Path(nsgeo_qgis.__file__).parent

FORBIDDEN_ROOTS = {"PyQt5", "PyQt6", "PySide2", "PySide6", "matplotlib", "scipy"}


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


def _public_api() -> dict[str, set[str]]:
    """`"nsgeo.<x>"` -> its `__all__`, for each public module, plus `"nsgeo"`.

    Discovered from the source by the same helper the core's own API test
    uses, so the allowlist cannot drift from the core's declaration.
    """
    public: dict[str, set[str]] = {"nsgeo": {"__version__"}}
    for name, names in public_modules(Path(nsgeo.__file__).parent).items():
        public[f"nsgeo.{name}"] = names
    return public


def _core_import_offenders(path: Path, public: dict[str, set[str]]) -> list[tuple[int, str]]:
    """(lineno, message) for each use of the core outside its named API.

    Standalone so it can be proven against a scratch file directly, not only
    through the package tree the test below scans.
    """
    offenders: list[tuple[int, str]] = []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    # Every name the top-level package is bound to: `import nsgeo` (or
    # `import nsgeo.x`) binds `nsgeo`, `import nsgeo as n` binds `n`.
    aliases = {"nsgeo"} | {
        a.asname or a.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for a in node.names
        if a.name == "nsgeo"
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            if node.module.split(".")[0] != "nsgeo":
                continue
            if node.module not in public:
                offenders.append((node.lineno, f"from {node.module} import"))
                continue
            bad = {a.name for a in node.names} - public[node.module]
            if bad:
                offenders.append((node.lineno, f"{node.module}: {sorted(bad)}"))
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] == "nsgeo" and a.name != "nsgeo":
                    offenders.append((node.lineno, f"import {a.name}"))
        elif (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in aliases
            and node.attr not in public["nsgeo"]
        ):
            offenders.append((node.lineno, f"{node.value.id}.{node.attr}"))
    return offenders


def test_plugin_imports_only_the_named_core_api() -> None:
    public = _public_api()
    offenders = []
    for path in _py_files():
        for lineno, msg in _core_import_offenders(path, public):
            offenders.append(f"{path.relative_to(SRC)}:{lineno}: {msg}")
    assert not offenders, "core imported outside its named API:\n" + "\n".join(offenders)


def test_the_checker_flags_each_kind_of_offence(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch.py"
    scratch.write_text(
        "from nsgeo.slices.store import npz_path\n"
        "from nsgeo.processing import register\n"
        "import nsgeo.processing\n"
        "import nsgeo\n"
        "x = nsgeo.slices\n"
        "ok = nsgeo.__version__\n"
        "from nsgeo.geometry import Grid\n"
        "from nsgeo_qgis.layers import Whatever\n"
        "import nsgeo as n\n"
        "y = n.slices.store\n"
        "fine = n.__version__\n",
        encoding="utf-8",
    )
    # A fixed allowlist, not the core's real `__all__` lists: this tests the
    # checker alone, so a change to the core cannot make it pass or fail.
    public = {"nsgeo": {"__version__"}, "nsgeo.geometry": {"Grid"}, "nsgeo.processing": {"Step"}}
    found = _core_import_offenders(scratch, public)
    assert sorted(line for line, _ in found) == [1, 2, 3, 5, 10]


def test_package_init_imports_no_qgis_at_module_level() -> None:
    """The pure test tier and the zip's shim both import the package without
    a QGIS runtime. classFactory imports qgis lazily."""
    tree = ast.parse((SRC / "__init__.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(a.name.split(".")[0] == "qgis" for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("qgis")
