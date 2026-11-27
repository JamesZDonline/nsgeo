"""`dev_link.profile_plugins_dir` picks the QGIS major's profile folder on each platform."""

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


def test_windows_profiles_live_under_appdata(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert dev_link.profile_plugins_dir("ns_geo", major=4) == (
        tmp_path / "Roaming" / "QGIS" / "QGIS4" / "profiles" / "ns_geo" / "python" / "plugins"
    )


def test_macos_profiles_live_under_application_support(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert dev_link.profile_plugins_dir("ns_geo", major=3) == (
        tmp_path / "Library/Application Support/QGIS/QGIS3/profiles/ns_geo/python/plugins"
    )
