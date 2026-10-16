"""build_zip.py: the release zip's contents, refusals and reproducibility.

The git-backed tests skip where git or a .git checkout is absent (the QGIS
Docker images); the version-agreement test needs neither.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import build_zip
import pytest

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")

QGIS_PKG = "packages/nsgeo-qgis/nsgeo_qgis"
CORE_PKG = "packages/nsgeo-core/src/nsgeo"
ROOT = Path(__file__).resolve().parents[4]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def commit_all(repo: Path, message: str = "more") -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    root = tmp_path / "repo"
    files = {
        f"{QGIS_PKG}/__init__.py": "",
        f"{QGIS_PKG}/metadata.txt": "[general]\nversion=0.1.0\n",
        "packages/nsgeo-qgis/LICENSE": "qgis licence\n",
        f"{CORE_PKG}/__init__.py": '__version__ = "0.1.0"\n',
        "packages/nsgeo-core/LICENSE": "core licence\n",
        "docs/releases/0.1.0.md": "notes\n",
    }
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.org")
    git(root, "config", "user.name", "T")
    git(root, "config", "core.autocrlf", "false")
    commit_all(root, "first")
    return root


@pytest.fixture
def real_repo():
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    r = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=Path(__file__).resolve().parent,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        pytest.skip("not a git checkout")
    return Path(r.stdout.strip())


@needs_git
def test_the_zip_has_one_top_level_folder_and_vendors_the_core(repo, tmp_path):
    z = zipfile.ZipFile(build_zip.build_zip(repo, tmp_path / "out"))
    names = z.namelist()
    assert {n.split("/")[0] for n in names} == {"nsgeo_qgis"}
    assert "nsgeo_qgis/_vendor/nsgeo/__init__.py" in names
    assert "nsgeo_qgis/LICENSE" in names and "nsgeo_qgis/_vendor/nsgeo/LICENSE" in names
    assert all("\\" not in n for n in names)


@needs_git
def test_version_file_records_core_version_and_commit(repo, tmp_path):
    z = zipfile.ZipFile(build_zip.build_zip(repo, tmp_path / "out"))
    head = git(repo, "rev-parse", "HEAD")
    assert z.read("nsgeo_qgis/_vendor/VERSION").decode() == f"core=0.1.0\ncommit={head}\n"


@needs_git
def test_untracked_survey_file_never_ships(repo, tmp_path):
    (repo / QGIS_PKG / "FILE__001.DZT").write_bytes(b"x")
    names = zipfile.ZipFile(build_zip.build_zip(repo, tmp_path / "o")).namelist()
    assert not any(n.lower().endswith(".dzt") for n in names)


@needs_git
def test_pycache_never_ships(repo, tmp_path):
    (repo / QGIS_PKG / "__pycache__").mkdir()
    (repo / QGIS_PKG / "__pycache__" / "x.pyc").write_bytes(b"x")
    names = zipfile.ZipFile(build_zip.build_zip(repo, tmp_path / "o")).namelist()
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)


@needs_git
def test_a_tracked_file_outside_the_allowlist_is_refused(repo, tmp_path):
    (repo / QGIS_PKG / "map.png").write_bytes(b"x")
    commit_all(repo)
    with pytest.raises(build_zip.BuildError, match="nsgeo_qgis/map.png"):
        build_zip.build_zip(repo, tmp_path / "o")


@needs_git
def test_help_pages_are_allowed_only_under_help(repo, tmp_path):
    for rel in ("help/dewow.html", "help/style.css", "help/fig/a.png"):
        p = repo / QGIS_PKG / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    commit_all(repo)
    names = zipfile.ZipFile(build_zip.build_zip(repo, tmp_path / "o")).namelist()
    for rel in ("help/dewow.html", "help/style.css", "help/fig/a.png"):
        assert f"nsgeo_qgis/{rel}" in names
    (repo / CORE_PKG / "page.html").write_bytes(b"x")
    commit_all(repo)
    with pytest.raises(build_zip.BuildError, match="_vendor/nsgeo/page.html"):
        build_zip.build_zip(repo, tmp_path / "o2")


@needs_git
def test_a_dirty_tree_is_refused_unless_allowed(repo, tmp_path):
    (repo / QGIS_PKG / "__init__.py").write_text("# edited\n")
    with pytest.raises(build_zip.BuildError, match="uncommitted"):
        build_zip.build_zip(repo, tmp_path / "o")
    assert build_zip.build_zip(repo, tmp_path / "o", allow_dirty=True).is_file()


@needs_git
@pytest.mark.parametrize("tag", ["v0.1", "0.1.0", "v0.1.0-rc1", "v0.1.1"])
def test_a_tag_that_does_not_match_is_refused(repo, tag):
    with pytest.raises(build_zip.BuildError, match="0.1.0") as exc:
        build_zip.check_tag(tag, repo)
    assert tag in str(exc.value)


def test_matching_tag_needs_release_notes(tmp_path):
    (tmp_path / QGIS_PKG).mkdir(parents=True)
    (tmp_path / QGIS_PKG / "metadata.txt").write_text("[general]\nversion=0.1.0\n")
    (tmp_path / CORE_PKG).mkdir(parents=True)
    (tmp_path / CORE_PKG / "__init__.py").write_text('__version__ = "0.1.0"\n')
    (tmp_path / "docs/releases").mkdir(parents=True)
    notes = tmp_path / "docs/releases/0.1.0.md"
    notes.write_text("notes\n")
    assert build_zip.check_tag("v0.1.0", tmp_path) == "0.1.0"
    notes.unlink()
    with pytest.raises(build_zip.BuildError, match="docs/releases/0.1.0.md"):
        build_zip.check_tag("v0.1.0", tmp_path)


@needs_git
def test_plugin_and_core_versions_must_agree_for_a_tag(repo):
    (repo / CORE_PKG / "__init__.py").write_text('__version__ = "0.1.1"\n')
    with pytest.raises(build_zip.BuildError, match="0.1.1"):
        build_zip.check_tag("v0.1.0", repo)


@needs_git
def test_two_builds_of_one_commit_are_identical(repo, tmp_path):
    a = build_zip.build_zip(repo, tmp_path / "a").read_bytes()
    (repo / QGIS_PKG / "__init__.py").chmod(0o755)
    b = build_zip.build_zip(repo, tmp_path / "b", allow_dirty=True).read_bytes()
    assert a == b


@needs_git
def test_main_builds_from_any_cwd_and_reports_errors(repo, tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert build_zip.main(["--out", str(tmp_path / "o"), "--tag", "v9.9.9"]) == 1
    assert "v9.9.9" in capsys.readouterr().err


@needs_git
def test_the_real_zip_loads_its_bundled_core_from_an_awkward_path(real_repo, tmp_path):
    z = build_zip.build_zip(real_repo, tmp_path / "out", allow_dirty=True)
    dest = tmp_path / "Prof ile José Müller" / "plugins"
    zipfile.ZipFile(z).extractall(dest)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    env.pop("PYTHONPATH", None)
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); import nsgeo_qgis, nsgeo; "
            "print(nsgeo.__file__); print(nsgeo_qgis.build_label())",
            str(dest),
        ],
        capture_output=True,
        encoding="utf-8",
        env=env,
        check=True,
    ).stdout.splitlines()
    assert (dest / "nsgeo_qgis" / "_vendor").resolve() in Path(out[0]).resolve().parents
    assert out[1].startswith("build ") and len(out[1]) == len("build ") + 12


def test_versions_agree_across_metadata_core_and_pyproject():
    plugin, core = build_zip.read_versions(ROOT)
    text = (ROOT / "packages/nsgeo-core/pyproject.toml").read_text(encoding="utf-8")
    pyproject = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M).group(1)
    assert plugin == core == pyproject
