"""A run of the plugin tests that passes leaves no tmp_path folders behind.

pytest keeps every test's tmp_path from the last three runs, and one whole
QGIS-tier run leaves about 2.5 GB (cubes, ParaView exports, site packages).
pytest's own `tmp_path_retention_policy = "failed"` would clear them, but it
deletes each passing test's folder at that test's teardown, while a task the
test started can still be writing there in the background. So the folders stay
until the run ends, and go then only if nothing failed. A failing run keeps all
of them to look at, and a run given --basetemp keeps its folder as asked.

tests/conftest.py imports the fixture; tests/pure/test_temp_dirs.py checks it.
"""

from __future__ import annotations

import shutil

import pytest


@pytest.fixture(scope="session", autouse=True)
def _drop_temp_folders_after_a_passing_run(request, tmp_path_factory):
    basetemp = tmp_path_factory.getbasetemp()
    yield
    if request.session.testsfailed == 0 and request.config.option.basetemp is None:
        shutil.rmtree(basetemp, ignore_errors=True)
