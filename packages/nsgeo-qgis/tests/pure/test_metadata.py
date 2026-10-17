"""The plugin's metadata.txt promises, pinned (spec 5.2)."""

from __future__ import annotations

import configparser
from pathlib import Path

METADATA = Path(__file__).resolve().parents[2] / "nsgeo_qgis" / "metadata.txt"


def _general() -> configparser.SectionProxy:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(METADATA, encoding="utf-8")
    return parser["general"]


def test_metadata_admits_qgis_3_40_through_4():
    g = _general()
    assert g["qgisMinimumVersion"] == "3.40"
    assert g["qgisMaximumVersion"] == "4.99"


def test_qt6_builds_of_qgis_3_still_accept_the_plugin():
    # QGIS 3.44 installer_data.py:832 rejects a Qt6 build without it.
    assert _general()["supportsQt6"] == "True"


def test_release_is_marked_experimental():
    assert _general()["experimental"] == "True"
