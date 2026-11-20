"""The CRS rule both dialogs share (M17a Task 4, P10)."""

from __future__ import annotations

from nsgeo_qgis.crs_rule import CRS_SCALE_REFUSE, choose_crs, crs_check, usable_at
from qgis.core import QgsCoordinateReferenceSystem, QgsPointXY

HERE = QgsPointXY(10.5, 45.2)  # a made-up place in UTM zone 32


def crs(authid: str) -> QgsCoordinateReferenceSystem:
    return QgsCoordinateReferenceSystem(authid)


def test_a_metre_project_crs_usable_here_is_kept(qgis_app):
    chosen, note = choose_crs(None, crs("EPSG:32632"), HERE)
    assert chosen.authid() == "EPSG:32632" and note == ""


def test_a_geographic_project_gets_the_utm_zone_with_a_note(qgis_app):
    chosen, note = choose_crs(None, crs("EPSG:4326"), HERE)
    assert chosen.authid() == "EPSG:32632"
    assert note.startswith("picked for you:") and "degrees" in note


def test_a_project_crs_off_by_too_much_is_replaced_with_its_reason(qgis_app):
    chosen, note = choose_crs(None, crs("EPSG:3857"), HERE)  # Web Mercator at 45 N
    assert chosen.authid() == "EPSG:32632"
    assert "EPSG:3857" in note and "off by" in note


def test_the_site_crs_wins_when_usable(qgis_app):
    chosen, note = choose_crs(crs("EPSG:32632"), crs("EPSG:4326"), HERE)
    assert chosen.authid() == "EPSG:32632"
    assert note == "picked for you: the CRS the site's other grids use"


def test_the_site_crs_of_a_gridless_site_is_called_the_sites_crs(qgis_app):
    chosen, note = choose_crs(crs("EPSG:32632"), crs("EPSG:4326"), HERE, site_has_grids=False)
    assert chosen.authid() == "EPSG:32632"
    assert note == "picked for you: the site's CRS"


def test_the_site_crs_needs_no_note_when_it_is_the_projects(qgis_app):
    assert choose_crs(crs("EPSG:32632"), crs("EPSG:32632"), HERE)[1] == ""
    assert choose_crs(crs("EPSG:32632"), crs("EPSG:32632"), HERE, site_has_grids=False)[1] == ""


def test_a_site_crs_that_cannot_place_the_spot_is_passed_over(qgis_app):
    far = crs("EPSG:32610")  # zone 10 at 10.5 E: well off a ground metre
    assert usable_at(far, HERE)[0] is not None
    chosen, _ = choose_crs(far, crs("EPSG:32632"), HERE)
    assert chosen.authid() == "EPSG:32632"


def test_usable_at_names_why_a_crs_is_not(qgis_app):
    assert usable_at(QgsCoordinateReferenceSystem(), HERE)[0] == "none"
    assert usable_at(crs("EPSG:4326"), HERE)[0] == "units"
    kind, error = usable_at(crs("EPSG:3857"), HERE)
    assert kind == "scale" and error is not None and error > CRS_SCALE_REFUSE
    assert usable_at(crs("EPSG:32632"), HERE)[0] is None


def test_crs_check_without_a_point_makes_no_scale_check(qgis_app):
    assert crs_check(crs("EPSG:3857"), None) == (None, None)
    assert crs_check(crs("EPSG:4326"), None) == ("units", None)


def test_the_grid_dialog_names_a_pinned_crs_the_sites_not_other_grids(qgis_app, tmp_path):
    from nsgeo.geometry import Grid
    from nsgeo_qgis.session import SiteSession
    from nsgeo_qgis.ui.grid_dialog import GridDialog
    from qgis.core import QgsProject

    project = QgsProject.instance()
    old = project.crs()
    project.setCrs(crs("EPSG:4326"))
    try:
        session = SiteSession()
        session.new_site(tmp_path)
        session.set_site_crs("EPSG:32632")  # what the first GPS import does
        dialog = GridDialog(session)
        chosen, note = dialog._choose_crs(HERE)
        assert chosen.authid() == "EPSG:32632"
        assert note == "picked for you: the site's CRS"
        dialog.reject()

        # a site with a grid keeps the old wording
        (tmp_path / "two").mkdir()
        session2 = SiteSession()
        session2.new_site(tmp_path / "two")
        session2.add_grid(Grid("B", (600_000.0, 5_000_000.0), 0.0, 10.0, 10.0, "EPSG:32632", 0.5))
        dialog2 = GridDialog(session2)
        assert dialog2._choose_crs(HERE)[1] == "picked for you: the CRS the site's other grids use"
        dialog2.reject()
    finally:
        project.setCrs(old)
