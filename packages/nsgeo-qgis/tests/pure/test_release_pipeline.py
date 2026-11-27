"""The smoke test and CI around the release zip (.github/workflows/ci.yml).

Most of this runs only on GitHub, so these are the closest local checks: the
smoke job's one-zip guard is run for real under bash, the rest read the
workflow and smoke_install.sh.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
CI = ROOT / ".github/workflows/ci.yml"
SMOKE_INSTALL = ROOT / "packages/nsgeo-qgis/scripts/smoke_install.sh"


def _job(name: str) -> str:
    """The text of one top-level job in ci.yml, up to the next job."""
    text = CI.read_text(encoding="utf-8")
    m = re.search(rf"^  {re.escape(name)}:\n(.*?)(?=^  \S|\Z)", text, re.M | re.S)
    assert m, f"no job {name!r} in ci.yml"
    return m.group(1)


def _step_script(job: str, step: str) -> str:
    """The `run: |` block of the named step, dedented."""
    lines = _job(job).splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip() == f"- name: {step}")
    run = next(i for i in range(start, len(lines)) if lines[i].strip() == "run: |")
    indent = len(lines[run + 1]) - len(lines[run + 1].lstrip())
    body = []
    for ln in lines[run + 1 :]:
        if ln.strip() and len(ln) - len(ln.lstrip()) < indent:
            break
        body.append(ln[indent:])
    return "\n".join(body) + "\n"


@pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None, reason="needs a POSIX bash"
)
@pytest.mark.parametrize("zips", [0, 2])
def test_the_smoke_one_zip_guard_counts_the_zips(tmp_path, zips):
    (tmp_path / "dist").mkdir()
    for i in range(zips):
        (tmp_path / "dist" / f"nsgeo_qgis-{i}.zip").write_bytes(b"")
    script = _step_script("smoke", "install the zip into QGIS and probe it")
    r = subprocess.run(
        ["bash", "-c", script], cwd=tmp_path, capture_output=True, text=True, timeout=30
    )
    assert r.returncode == 1
    assert f"found {zips}" in r.stderr


def test_the_smoke_job_has_a_hard_time_limit():
    assert re.search(r"^    timeout-minutes: \d+$", _job("smoke"), re.M)


def test_smoke_install_kills_a_qgis_that_ignores_sigterm():
    text = SMOKE_INSTALL.read_text(encoding="utf-8")
    assert re.search(r"\btimeout -k \d+ \d+ xvfb-run\b", text)


def test_smoke_install_gives_qt_a_utf8_locale_and_a_runtime_dir():
    text = SMOKE_INSTALL.read_text(encoding="utf-8")
    assert re.search(r"^export LANG=C\.UTF-8$", text, re.M)
    assert re.search(r"^\s*export XDG_RUNTIME_DIR=", text, re.M)


# The first major of each action that runs on Node 24 rather than Node 20.
NODE24_MAJOR = {
    "actions/checkout": 5,
    "actions/setup-python": 6,
    "actions/upload-artifact": 6,
    "actions/download-artifact": 7,
}


def test_actions_are_on_node24_majors():
    uses = re.findall(r"uses: (actions/[\w-]+)@v(\d+)", CI.read_text(encoding="utf-8"))
    assert uses
    old = [f"{a}@v{v}" for a, v in uses if int(v) < NODE24_MAJOR.get(a, 0)]
    assert not old, f"still on Node 20: {old}"


def test_actionlint_is_pinned_by_digest():
    # It runs as a docker image over the repo, so pin the exact image (#53).
    # GitHub's own actions stay on major tags, QGIS images float within a minor.
    ref = re.search(r"uses: docker://rhysd/actionlint(\S*)", CI.read_text(encoding="utf-8"))
    assert ref, "actionlint step not found"
    assert re.fullmatch(r"@sha256:[0-9a-f]{64}", ref.group(1)), ref.group(1)
