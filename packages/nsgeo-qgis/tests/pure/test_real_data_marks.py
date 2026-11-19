"""The `real_data` mark, end to end, in a pytest run of its own.

The QGIS tier's conftest takes its hooks from `real_data_marks`. This file
drives the same hooks over a small throwaway suite with no real data, as CI
has none, and reads each test's outcome from the JUnit report.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parents[1]  # packages/nsgeo-qgis/tests

SUITE = """
import pytest

needs_data = pytest.mark.skipif(True, reason="no real DZT files in tests/data/local")


@needs_data
def test_guarded():
    pass


@pytest.mark.real_data
def test_marked_by_hand():
    pytest.skip("FILE__007.DZT is not in tests/data/local")


def test_unmarked_runtime_skip():
    pytest.skip("FILE__007.DZT is not in tests/data/local")


@pytest.mark.parametrize("path", [])
def test_unmarked_empty_list(path):
    pass


@pytest.mark.skipif(True, reason="needs a display")
def test_other_skip():
    pass


def test_plain():
    pass
"""


def _run(tmp_path: Path, *args: str) -> dict[str, str]:
    """Runs the throwaway suite; returns {test name: passed|skipped|failed}."""
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "conftest.py").write_text(
        textwrap.dedent(
            f"""
            import sys
            sys.path.insert(0, {str(TESTS_DIR)!r})
            from real_data_marks import (  # noqa: F401
                pytest_collection_modifyitems,
                pytest_configure,
                pytest_runtest_makereport,
            )
            """
        )
    )
    (tmp_path / "test_suite.py").write_text(SUITE)
    report = tmp_path / "report.xml"
    run = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-p", "no:xonsh", "-q"]
        + [f"--junitxml={report}", *args, str(tmp_path / "test_suite.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert report.exists(), run.stdout + run.stderr
    outcomes = {}
    for case in ET.parse(report).iter("testcase"):
        name = case.get("name", "").split("[")[0]
        kinds = {child.tag for child in case}
        if kinds & {"failure", "error"}:
            outcomes[name] = "failed"
        else:
            outcomes[name] = "skipped" if "skipped" in kinds else "passed"
    return outcomes


def test_a_data_skip_without_the_mark_fails_and_every_other_outcome_stands(tmp_path):
    assert _run(tmp_path) == {
        "test_guarded": "skipped",
        "test_marked_by_hand": "skipped",
        "test_unmarked_runtime_skip": "failed",
        "test_unmarked_empty_list": "failed",
        "test_other_skip": "skipped",
        "test_plain": "passed",
    }


def test_the_mark_selects_the_guarded_and_the_hand_marked_tests_only(tmp_path):
    assert set(_run(tmp_path, "-m", "real_data")) == {"test_guarded", "test_marked_by_hand"}
