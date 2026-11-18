"""The `real_data` mark: the QGIS-tier tests that CI cannot run.

The real surveys in nsgeo-core/tests/data/local are gitignored, so on CI every
test that needs them skips. Locally, `pytest -m real_data` runs exactly those
tests. A session can then run the files it touched plus these, and leave the
rest of the tier to CI, which runs all of it on QGIS 3.44 and 4.2.

A test is marked by itself when it carries a skipif whose reason names
tests/data/local (`needs_real_data`, `needs_sunnyside`, the Grid 1 and Grid 2
guards). Anything else that needs the data takes `@pytest.mark.real_data` by
hand. So the selection cannot quietly miss a test, a test that skips for want
of the data without the mark fails instead: on CI, which has no data, every
such test is caught on its first run.

tests/qgis/conftest.py imports these hooks; tests/pure/test_real_data_marks.py
drives them over a throwaway suite.
"""

from __future__ import annotations

import pytest

MARK = "real_data"
#: Every real-data skip reason in this tier names the folder the data lives in.
DATA_FOLDER = "tests/data/local"
#: What pytest says when a test is parametrized over a list of real files that
#: is empty because the folder is missing.
EMPTY_LIST = "got empty parameter set"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        f"{MARK}: needs the gitignored surveys in nsgeo-core/{DATA_FOLDER}, so skips on CI",
    )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        reasons = (str(m.kwargs.get("reason", "")) for m in item.iter_markers("skipif"))
        if any(DATA_FOLDER in reason for reason in reasons):
            item.add_marker(MARK)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    report = yield
    if report.skipped and item.get_closest_marker(MARK) is None:
        reason = str(report.longrepr)
        if DATA_FOLDER in reason or EMPTY_LIST in reason:
            report.outcome = "failed"
            report.longrepr = (
                f"{item.nodeid} skipped for want of the real data but is not marked "
                f"{MARK}, so `pytest -m {MARK}` would never run it. Mark it "
                f"@pytest.mark.{MARK}, or guard it with a skipif whose reason names "
                f"{DATA_FOLDER}.\nThe skip: {reason}"
            )
    return report
