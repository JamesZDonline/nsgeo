"""Build the QGIS-installable release zip, with the nsgeo core vendored inside.

Usage: python packages/nsgeo-qgis/scripts/build_zip.py
           [--out DIR] [--allow-dirty] [--tag TAG]

The zip is built from `git ls-files` only, so an untracked survey file can
never ship, and from nothing outside the allowlist. Two builds of one commit
are byte-identical.
"""

from __future__ import annotations

import argparse
import ast
import configparser
import subprocess
import sys
import time
import zipfile
from pathlib import Path

QGIS_SRC = "packages/nsgeo-qgis/nsgeo_qgis"
CORE_SRC = "packages/nsgeo-core/src/nsgeo"
ARC_ROOT = "nsgeo_qgis"
ARC_VENDOR = f"{ARC_ROOT}/_vendor"
EXTRA_FILES = {
    "packages/nsgeo-qgis/LICENSE": f"{ARC_ROOT}/LICENSE",
    "packages/nsgeo-core/LICENSE": f"{ARC_VENDOR}/nsgeo/LICENSE",
}
ALLOWED_SUFFIXES = {".py", ".txt", ".md"}
HELP_SUFFIXES = {".html", ".css", ".png"}


class BuildError(Exception):
    pass


def _git(repo: Path, *args: str) -> str:
    try:
        r = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            encoding="utf-8",
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise BuildError(f"git {' '.join(args)} failed: {detail.strip()}") from exc
    return r.stdout


def read_versions(repo: Path) -> tuple[str, str]:
    """(plugin_version, core_version), the core's parsed with ast, never imported."""
    cfg = configparser.ConfigParser()
    cfg.read(repo / QGIS_SRC / "metadata.txt", encoding="utf-8")
    plugin = cfg["general"]["version"]
    tree = ast.parse((repo / CORE_SRC / "__init__.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets
        ):
            return plugin, ast.literal_eval(node.value)
    raise BuildError(f"no __version__ in {CORE_SRC}/__init__.py")


def check_tag(tag: str, repo: Path) -> str:
    plugin, core = read_versions(repo)
    if tag != f"v{plugin}" or plugin != core:
        raise BuildError(
            f"tag {tag!r} does not match: plugin version is {plugin}, core version is "
            f"{core} (the tag must be v{plugin} and both versions must agree)"
        )
    notes = f"docs/releases/{plugin}.md"
    if not (repo / notes).is_file():
        raise BuildError(f"tag {tag!r} needs release notes at {notes}, which does not exist")
    return plugin


def _allowed(arcname: str) -> bool:
    parts = arcname.split("/")
    if "__pycache__" in parts:
        return False
    name = parts[-1]
    if name.startswith("LICENSE") or name == "VERSION":
        return True
    suffix = Path(name).suffix.lower()
    if suffix in ALLOWED_SUFFIXES:
        return True
    return suffix in HELP_SUFFIXES and arcname.startswith(f"{ARC_ROOT}/help/")


def _tracked(repo: Path, pathspec: str) -> list[str]:
    out = _git(repo, "ls-files", "-z", "--", pathspec)
    return [p for p in out.split("\0") if p]


def zip_plan(repo: Path) -> list[tuple[str, Path]]:
    plan: list[tuple[str, Path]] = []
    for src, dst in ((QGIS_SRC, ARC_ROOT), (CORE_SRC, f"{ARC_VENDOR}/nsgeo")):
        for rel in _tracked(repo, src):
            plan.append((dst + rel[len(src) :], repo / rel))
    tracked_extra = set(_tracked(repo, "packages"))
    for rel, arc in EXTRA_FILES.items():
        if rel in tracked_extra:
            plan.append((arc, repo / rel))
    refused = sorted(arc for arc, _ in plan if not _allowed(arc))
    if refused:
        raise BuildError("tracked files outside the zip allowlist: " + ", ".join(refused))
    return sorted(plan, key=lambda item: item[0])


def _entry(arcname: str, when: time.struct_time) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(arcname, date_time=tuple(when)[:6])
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    info.create_system = 3
    return info


def build_zip(
    repo: Path, out_dir: Path, *, allow_dirty: bool = False, tag: str | None = None
) -> Path:
    if tag is not None:
        check_tag(tag, repo)
    if not allow_dirty and _git(repo, "status", "--porcelain", "--untracked-files=no").strip():
        raise BuildError(
            "the working tree has uncommitted changes to tracked files; "
            "commit them or pass --allow-dirty"
        )
    plugin, core = read_versions(repo)
    head = _git(repo, "rev-parse", "HEAD").strip()
    when = time.gmtime(int(_git(repo, "log", "-1", "--format=%ct").strip()))
    version_text = f"core={core}\ncommit={head}\n"

    entries: list[tuple[str, bytes]] = [(arc, src.read_bytes()) for arc, src in zip_plan(repo)]
    entries.append((f"{ARC_VENDOR}/VERSION", version_text.encode("utf-8")))
    entries.sort(key=lambda e: e[0])

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"nsgeo_qgis-{plugin}.zip"
    with zipfile.ZipFile(target, "w") as z:
        for arc, data in entries:
            z.writestr(_entry(arc, when), data)
    return target


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out", type=Path, default=None, help="output directory (default: <repo>/dist)"
    )
    ap.add_argument("--allow-dirty", action="store_true")
    ap.add_argument("--tag", default=None)
    args = ap.parse_args(argv)
    try:
        repo = Path(_git(Path(__file__).resolve().parent, "rev-parse", "--show-toplevel").strip())
        out = args.out if args.out is not None else repo / "dist"
        target = build_zip(repo, out, allow_dirty=args.allow_dirty, tag=args.tag)
    except BuildError as exc:
        print(f"build_zip: {exc}", file=sys.stderr)
        return 1
    print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
