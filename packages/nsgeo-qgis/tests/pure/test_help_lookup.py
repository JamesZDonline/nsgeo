from __future__ import annotations

from pathlib import Path

import nsgeo_qgis
from nsgeo_qgis import help_pages


def test_help_dir_ships_inside_the_plugin_package():
    assert help_pages.HELP_DIR.parent == Path(nsgeo_qgis.__file__).parent


def test_page_path_finds_existing_pages_only(tmp_path, monkeypatch):
    (tmp_path / "dewow.html").write_text("x", encoding="utf-8")
    monkeypatch.setattr(help_pages, "HELP_DIR", tmp_path)
    assert help_pages.page_path("dewow") == tmp_path / "dewow.html"
    assert help_pages.page_path("bandpass") is None
