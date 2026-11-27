"""in_qgis_docker.sh: which real-data folders it mounts into the container (#223).

The script is copied into a throwaway tree with its own
``packages/nsgeo-core/tests/data/local`` of symlinks, and ``docker`` on PATH is
a stub that prints its arguments, so no Docker or survey data is needed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "in_qgis_docker.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or os.name == "nt", reason="needs bash and symlinks"
)


def run_and_list_mounts(tmp_path: Path) -> list[str]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    stub = bindir / "docker"
    stub.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@"\n')
    stub.chmod(0o755)
    scripts = tmp_path / "root" / "packages" / "nsgeo-qgis" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(SCRIPT, scripts / SCRIPT.name)
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
    out = subprocess.run(
        ["bash", str(scripts / SCRIPT.name), "img", "true"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return [out[i + 1] for i, arg in enumerate(out) if arg == "-v"]


def test_links_inside_a_real_survey_folder_have_their_targets_mounted(tmp_path):
    drive_a = tmp_path / "driveA" / "survey1"
    drive_b = tmp_path / "driveB" / "raw"
    drive_a.mkdir(parents=True)
    drive_b.mkdir(parents=True)
    (drive_b / "FILE__001.DZT").write_bytes(b"")
    (drive_b / "FILE__001.DZG").write_bytes(b"")
    local = tmp_path / "root" / "packages" / "nsgeo-core" / "tests" / "data" / "local"
    survey2 = local / "survey2"
    survey2.mkdir(parents=True)
    (local / "survey1").symlink_to(drive_a)
    (survey2 / "FILE__001.DZT").symlink_to(drive_b / "FILE__001.DZT")
    (survey2 / "FILE__001.DZG").symlink_to(drive_b / "FILE__001.DZG")

    mounts = run_and_list_mounts(tmp_path)

    a, b = drive_a.parent.resolve(), drive_b.resolve()
    assert f"{a}:{a}:ro" in mounts
    assert f"{b}:{b}:ro" in mounts
    assert len(mounts) == len(set(mounts)), "each folder is mounted once"
