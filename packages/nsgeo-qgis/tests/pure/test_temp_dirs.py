"""temp_dirs.py, end to end: a throwaway suite run under its own temp root."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parents[1]  # packages/nsgeo-qgis/tests


def _run(tmp_path: Path, body: str, *args: str) -> list[Path]:
    """Runs a one-test suite whose test writes `kept.txt` to its tmp_path, then
    `body`; returns the `kept.txt` files left under the run's temp root."""
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "pytest.ini").write_text("[pytest]\n")
    (suite / "conftest.py").write_text(
        textwrap.dedent(
            f"""
            import sys
            sys.path.insert(0, {str(TESTS_DIR)!r})
            from temp_dirs import _drop_temp_folders_after_a_passing_run  # noqa: F401
            """
        )
    )
    (suite / "test_one.py").write_text(
        f"def test_one(tmp_path):\n    (tmp_path / 'kept.txt').write_text('x')\n    {body}\n"
    )
    root = tmp_path / "root"
    root.mkdir()
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p", "no:xonsh", "-q"]
        + [*args, str(suite)],
        cwd=suite,
        env={**os.environ, "PYTEST_DEBUG_TEMPROOT": str(root)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert "1 passed" in run.stdout or "1 failed" in run.stdout, run.stdout + run.stderr
    return sorted(tmp_path.rglob("kept.txt"))


def test_a_passing_run_leaves_no_folders(tmp_path):
    assert _run(tmp_path, "pass") == []


def test_a_failing_run_keeps_its_folders(tmp_path):
    assert len(_run(tmp_path, "assert False")) == 1


def test_a_run_given_a_basetemp_keeps_it(tmp_path):
    assert len(_run(tmp_path, "pass", f"--basetemp={tmp_path / 'given'}")) == 1
