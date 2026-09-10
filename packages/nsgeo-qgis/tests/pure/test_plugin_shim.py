from __future__ import annotations

from pathlib import Path

import nsgeo_qgis
import pytest
from nsgeo_qgis import _find_core, plugin_version


def test_core_path_points_at_a_real_nsgeo_package():
    assert (nsgeo_qgis.CORE_PATH / "nsgeo" / "__init__.py").is_file()
    import nsgeo

    assert Path(nsgeo.__file__).resolve().parent == (nsgeo_qgis.CORE_PATH / "nsgeo").resolve()


def test_vendored_core_wins_when_present(tmp_path):
    pkg = tmp_path / "packages" / "nsgeo-qgis" / "nsgeo_qgis"
    (pkg / "_vendor" / "nsgeo").mkdir(parents=True)
    (pkg / "_vendor" / "nsgeo" / "__init__.py").write_text("")
    assert _find_core(pkg) == pkg / "_vendor"


def test_sibling_source_tree_is_the_development_fallback(tmp_path):
    pkg = tmp_path / "packages" / "nsgeo-qgis" / "nsgeo_qgis"
    pkg.mkdir(parents=True)
    src = tmp_path / "packages" / "nsgeo-core" / "src"
    (src / "nsgeo").mkdir(parents=True)
    (src / "nsgeo" / "__init__.py").write_text("")
    assert _find_core(pkg) == src


def test_missing_core_names_both_places_it_looked(tmp_path):
    pkg = tmp_path / "packages" / "nsgeo-qgis" / "nsgeo_qgis"
    pkg.mkdir(parents=True)
    with pytest.raises(ImportError) as exc:
        _find_core(pkg)
    msg = str(exc.value)
    assert "_vendor" in msg and "nsgeo-core" in msg


def test_plugin_version_comes_from_metadata():
    v = plugin_version()
    assert v and v[0].isdigit()
