"""`dev_link.profile_plugins_dir` picks the QGIS major's profile folder."""

from __future__ import annotations

import sys
from pathlib import Path

import dev_link
import pytest


@pytest.fixture
def linux_home(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def test_qgis4_profiles_live_under_QGIS4(linux_home):
    assert dev_link.profile_plugins_dir("ns_geo", major=4) == (
        linux_home / ".local/share/QGIS/QGIS4/profiles/ns_geo/python/plugins"
    )


def test_default_major_is_unchanged_for_existing_usage(linux_home):
    assert "QGIS3" in dev_link.profile_plugins_dir("ns_geo").parts
