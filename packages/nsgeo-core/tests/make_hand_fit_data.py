"""Copy saved site files into tests/data/local/hand-fits/ for the hand-fit tests.

Usage: python tests/make_hand_fit_data.py SITE.nsgeo.json [...]

The copies are gitignored and named site-1.nsgeo.json, site-2.nsgeo.json, ...
A relative line path in a copy is rewritten to an absolute one, resolved against
the original file's folder, because the copy lives elsewhere. Empty rulings.json
and pending.json are created when absent. Nothing from a site is committed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(__file__).parent / "data" / "local" / "hand-fits"


def copy_site(src: Path, dest: Path) -> int:
    """Write `src` to `dest` with absolute line paths; return the saved-fit count."""
    doc = json.loads(src.read_text(encoding="utf-8"))
    root = src.resolve().parent
    fits = 0
    for entry in doc.get("lines", []):
        path = Path(entry["path"])
        if not path.is_absolute():
            entry["path"] = str(root / path)
        fits += len(entry.get("velocity_fits", {}))
    dest.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return fits


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ("rulings.json", "pending.json"):
        if not (OUT / name).exists():
            (OUT / name).write_text("{}\n", encoding="utf-8")
    for i, arg in enumerate(argv, start=1):
        n = copy_site(Path(arg).expanduser(), OUT / f"site-{i}.nsgeo.json")
        print(f"site-{i}.nsgeo.json: {n} saved fits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
