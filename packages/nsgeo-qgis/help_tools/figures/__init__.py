"""Make the help pages' figures by running nsgeo's own steps on a real survey line.

Dev-only. One module per step in this package, named for a registry step; each has
`make(rg, header, out_dir) -> list[Path]` and optionally `measure(dt_ns) -> list[dict]`.
Run: `python -m help_tools.figures --step dewow --out DIR` from `packages/nsgeo-qgis`.
"""

from __future__ import annotations

import argparse
import importlib
import json
import pkgutil
from pathlib import Path
from types import ModuleType

import nsgeo_qgis  # noqa: F401  (runs the core path shim before any nsgeo import)
from nsgeo_qgis.help_pages import HELP_DIR

DEFAULT_DATA = (
    Path(__file__).resolve().parents[4]
    / "packages"
    / "nsgeo-core"
    / "tests"
    / "data"
    / "local"
    / "FILE__007.DZT"
)
DEFAULT_OUT = HELP_DIR / "img"


def recipes() -> dict[str, ModuleType]:
    """Every recipe module in this package (all but `common` and `__main__`), keyed by step name."""
    found = {}
    for info in pkgutil.iter_modules(__path__):
        if info.name != "common" and not info.name.startswith("_"):
            found[info.name] = importlib.import_module(f"{__name__}.{info.name}")
    return found


def make_figures(dzt: Path, out_dir: Path, steps: list[str] | None = None) -> list[Path]:
    """Run the recipes for `steps` (None: all) on `dzt`, writing PNGs into `out_dir`."""
    from help_tools.figures.common import load_radargram

    available = recipes()
    names = list(available) if steps is None else steps
    for name in names:
        if name not in available:
            raise KeyError(f"no figure recipe for step {name!r}")
    rg, header = load_radargram(dzt)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for name in names:
        paths += available[name].make(rg, header, out_dir)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m help_tools.figures")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="the DZT to draw from")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where the PNGs go")
    parser.add_argument("--step", action="append", help="a step to draw (repeatable)")
    parser.add_argument("--report", metavar="STEP", help="print STEP's measurements, write nothing")
    args = parser.parse_args(argv)
    if args.report:
        from help_tools.figures.common import load_radargram

        recipe = recipes().get(args.report)
        if recipe is None or not hasattr(recipe, "measure"):
            parser.error(f"no measurements for step {args.report!r}")
        rg, _ = load_radargram(args.data)
        print(json.dumps(recipe.measure(rg.dt_ns), indent=2))
        return 0
    for path in make_figures(args.data, args.out, args.step):
        print(path)
    return 0
