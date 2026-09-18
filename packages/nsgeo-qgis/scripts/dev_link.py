"""Symlink nsgeo_qgis/ into the active QGIS profile's plugin directory.

Usage: python packages/nsgeo-qgis/scripts/dev_link.py [--profile NAME] [--remove]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PLUGIN_SRC = Path(__file__).resolve().parent.parent / "nsgeo_qgis"


def profile_plugins_dir(profile: str) -> Path:
    home = Path.home()
    if sys.platform.startswith("win"):
        base = Path(os.environ["APPDATA"]) / "QGIS" / "QGIS3"
    elif sys.platform == "darwin":
        base = home / "Library" / "Application Support" / "QGIS" / "QGIS3"
    else:
        base = home / ".local" / "share" / "QGIS" / "QGIS3"
    return base / "profiles" / profile / "python" / "plugins"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", default="default")
    ap.add_argument("--remove", action="store_true")
    args = ap.parse_args()

    target = profile_plugins_dir(args.profile) / "nsgeo_qgis"
    if args.remove:
        if target.is_symlink():
            target.unlink()
            print(f"removed {target}")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not target.is_symlink():
        print(f"refusing: {target} exists and is not a symlink", file=sys.stderr)
        return 1
    if target.is_symlink():
        target.unlink()
    os.symlink(PLUGIN_SRC, target, target_is_directory=True)
    print(f"{target} -> {PLUGIN_SRC}")
    print("Enable 'nsgeo' in QGIS: Plugins > Manage and Install Plugins > Installed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
