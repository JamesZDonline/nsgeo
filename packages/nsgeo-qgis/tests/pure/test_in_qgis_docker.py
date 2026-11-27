"""in_qgis_docker.sh: which real-data folders it mounts (#223), and what it
copies into the container's working tree (#54).

The script is copied into a throwaway tree with its own
``packages/nsgeo-core/tests/data/local`` of symlinks, and ``docker`` on PATH is
a stub, so no Docker or survey data is needed. The default stub prints its
arguments; ``RUN_INSIDE`` instead runs the script's in-container half on the
host, with ``/src`` and ``/work`` moved under the test's folder.
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


PRINT_ARGS = '#!/usr/bin/env bash\nprintf "%s\\n" "$@"\n'

# Runs `bash -c SCRIPT bash CMD...` from the docker arguments on the host, with
# /src a link to the mounted root and /work a fresh folder, both under $FAKE.
# A no-op python3 stands in for the image's (the script pip-installs pytest).
RUN_INSIDE = r"""#!/usr/bin/env bash
set -euo pipefail
while [ "$#" -gt 0 ]; do
    case $1 in
        -v) case $2 in *:/src:ro) ln -s "${2%:/src:ro}" "$FAKE/src" ;; esac; shift 2 ;;
        -e) shift 2 ;;
        -c) script=$2; shift 2; break ;;
        *) shift ;;
    esac
done
script=${script//\/src/$FAKE/src}
script=${script//\/work/$FAKE/work}
exec bash -c "$script" "$@"
"""


def run_script(tmp_path: Path, stub: str = PRINT_ARGS) -> subprocess.CompletedProcess[str]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (("docker", stub), ("python3", "#!/usr/bin/env bash\n")):
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)
    scripts = tmp_path / "root" / "packages" / "nsgeo-qgis" / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    shutil.copy(SCRIPT, scripts / SCRIPT.name)
    (tmp_path / "root" / "packages" / "nsgeo-core" / "tests" / "data" / "local").mkdir(
        parents=True, exist_ok=True
    )
    fake = tmp_path / "fake"
    fake.mkdir()
    env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "FAKE": str(fake),
    }
    return subprocess.run(
        ["bash", str(scripts / SCRIPT.name), "img", "true"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )


def run_and_list_mounts(tmp_path: Path) -> list[str]:
    out = run_script(tmp_path).stdout.splitlines()
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


def test_a_link_into_a_missing_folder_is_skipped_with_a_warning(tmp_path):
    """Neither a silent exit 1 nor a mount of a folder that is not there,
    which Docker would create on the host, owned by root."""
    local = tmp_path / "root" / "packages" / "nsgeo-core" / "tests" / "data" / "local"
    local.mkdir(parents=True)
    missing = tmp_path / "unplugged" / "drive" / "survey"
    (local / "survey").symlink_to(missing)
    (local / "one.DZT").symlink_to(missing / "FILE__001.DZT")
    present = tmp_path / "driveA"
    present.mkdir()
    (local / "kept").symlink_to(present)

    result = run_script(tmp_path)

    out = result.stdout.splitlines()
    mounts = [out[i + 1] for i, arg in enumerate(out) if arg == "-v"]
    assert not any("unplugged" in m for m in mounts), mounts
    assert f"{tmp_path.resolve()}:{tmp_path.resolve()}:ro" in mounts
    assert "survey" in result.stderr and "one.DZT" in result.stderr
    assert not (tmp_path / "unplugged").exists()


def test_virtualenvs_are_left_out_of_the_copy_at_any_depth(tmp_path):
    """Run from a main checkout, `.worktrees/*/` each hold their own `.venv`."""
    root = tmp_path / "root"
    for venv in (".venv", ".venv-qgis", ".worktrees/a/.venv", ".worktrees/a/.venv-qgis"):
        (root / venv).mkdir(parents=True)
        (root / venv / "pyvenv.cfg").write_text("")
    (root / ".worktrees" / "a" / "README.md").write_text("kept")
    (root / "README.md").write_text("kept")

    run_script(tmp_path, RUN_INSIDE)

    work = tmp_path / "fake" / "work"
    assert (work / "README.md").is_file()
    assert (work / ".worktrees" / "a" / "README.md").is_file()
    assert (work / "packages" / "nsgeo-qgis" / "scripts" / SCRIPT.name).is_file()
    left = sorted(str(p.relative_to(work)) for p in work.rglob(".venv*"))
    assert left == []
