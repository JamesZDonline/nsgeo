from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import nsgeo_qgis.layers as layers_module
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.io.dzx import read_dzx
from nsgeo.model.survey import Line
from nsgeo_qgis.layers import _PICKS_BACKUP, _PICKS_REBUILD, DERIVED, TABLES, SiteLayers
from nsgeo_qgis.lookup import ImportOptions, plan_import, rows_to_lines
from nsgeo_qgis.session import GPKG_FILE, SURVEY_FILE, Pick, SiteSession
from nsgeo_qgis.ui.profile_view import PICK_COLOUR
from plugin_testing import REAL_DZT, needs_real_data, synthetic_dzt
from qgis.core import (
    NULL,
    Qgis,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsProviderRegistry,
    QgsSingleSymbolRenderer,
    QgsSymbol,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QMetaType, Qt
from qgis.PyQt.QtGui import QColor

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)

DZX = """<?xml version="1.0" encoding="UTF-8"?>
<DZX xmlns="www.geophysical.com/DZX/1.02"><File><name>FILE__002.DZT</name>
<Profile><WayPt><scan>30</scan><mark>User</mark><name>Mark1</name></WayPt></Profile></File></DZX>"""


@pytest.fixture
def populated(qgis_app, tmp_path):
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    session.add_grid(GRID)
    lines = []
    for i in range(3):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", i * 0.5, 0.0, 1, p.stem)))
    (tmp_path / "raw" / "FILE__002.DZX").write_text(DZX)
    session.add_lines(lines)
    yield session, layers, project
    layers.detach()
    project.clear()


def test_tables_exist_with_the_declared_fields_and_flags(populated):
    session, layers, project = populated
    assert session.gpkg_path.is_file()
    for name, (_, fields) in TABLES.items():
        lyr = QgsVectorLayer(f"{session.gpkg_path}|layername={name}", name, "ogr")
        assert lyr.isValid(), name
        assert [f.name() for f in lyr.fields() if f.name() != "fid"] == [f for f, _ in fields]
    assert set(layers.layers) == set(TABLES)
    for name in TABLES:
        assert layers.layers[name].readOnly() is (name in DERIVED)
    assert layers.crs().authid() == "EPSG:32616"
    assert layers.layers["lines"].crs().authid() == "EPSG:32616"


def test_derived_tables_mirror_the_session(populated):
    session, layers, _ = populated
    assert layers.feature_count("grids") == 1
    assert layers.feature_count("lines") == 3
    assert layers.feature_count("marks") == 1
    feat = next(layers.layers["lines"].getFeatures())
    assert feat["line_key"] == "raw/FILE__001.DZT"
    assert feat["n_traces"] == 60
    assert feat["length_m"] == pytest.approx(1.0)
    assert feat.geometry().length() == pytest.approx(59 / 60, abs=1e-6)
    session.remove_line("raw/FILE__003.DZT")
    assert layers.feature_count("lines") == 2


def test_layers_are_grouped_in_the_project_under_the_site_name(populated):
    session, layers, project = populated
    group = project.layerTreeRoot().findGroup(f"nsgeo · {session.site_name}")
    assert group is not None
    assert len(group.findLayers()) == 4


def test_refill_never_touches_the_picks_table(populated):
    session, layers, _ = populated
    picks = layers.layers["picks"]
    f = QgsFeature(picks.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    f["line_key"] = "raw/FILE__001.DZT"
    f["time_ns"] = 43.1
    assert picks.dataProvider().addFeatures([f])[0]
    session.remove_line("raw/FILE__002.DZT")
    session.add_grid(Grid("B", (600.0, 700.0), 0.0, 2.0, 2.0, "EPSG:32616", 0.5))
    assert layers.feature_count("picks") == 1
    assert layers.feature_count("grids") == 2


def test_reopening_a_site_reuses_the_existing_package(populated, tmp_path):
    session, layers, project = populated
    session.save()
    layers.detach()
    again = SiteSession()
    layers2 = SiteLayers(again, project=project)
    again.open_site(tmp_path / "survey.nsgeo.json")
    assert layers2.feature_count("lines") == 3
    layers2.detach()


def test_grid_in_another_crs_is_transformed_into_the_package_crs(populated):
    session, layers, _ = populated
    session.add_grid(Grid("B", (-86.8, 36.4), 0.0, 0.001, 0.001, "EPSG:4326", 0.5))
    feats = {f["grid_id"]: f for f in layers.layers["grids"].getFeatures()}
    x = feats["B"].geometry().centroid().asPoint().x()
    assert 100_000 < x < 900_000  # UTM easting, not a longitude


def test_grids_layer_renders_as_dashed_outline_with_no_fill(populated):
    """The grid polygon is a reference frame drawn over imagery: an opaque
    fill would hide the ground the user is judging placement against. This
    asserts on the renderer actually installed, not on a call being made --
    deleting `_style_grids()` leaves the default single-symbol renderer and
    fails the `isinstance` check below."""
    session, layers, _ = populated
    session.add_grid(Grid("B", (600.0, 700.0), 0.0, 2.0, 2.0, "EPSG:32616", 0.5))

    renderer = layers.layers["grids"].renderer()
    assert isinstance(renderer, QgsCategorizedSymbolRenderer)
    assert renderer.classAttribute() == "grid_id"

    # `.categories()` hands back a list of value-type QgsRendererCategory
    # objects that own their symbol; `.symbol()` only borrows from that
    # owner. Keep the list itself alive for as long as the borrowed symbols
    # are in use, or the category can be garbage-collected out from under
    # them (PyQGIS won't keep it alive on your behalf).
    grid_cats = list(renderer.categories())
    by_grid = {str(cat.value()): cat.symbol() for cat in grid_cats}
    assert set(by_grid) == {"A", "B"}
    for symbol in by_grid.values():
        outline = symbol.symbolLayer(0)
        assert outline.brushStyle() == Qt.BrushStyle.NoBrush
        assert outline.strokeStyle() == Qt.PenStyle.DashLine

    # M5 follow-up (Finding 2): a grid's outline colour must now DIFFER
    # from the colour of its own lines (they used to share a palette
    # index, which was useless with the single-grid case). Both sides
    # below are read off the renderers QGIS actually installed -- not
    # recomputed from GRID_COLOURS or the offset `_style_grids()` uses --
    # so this fails for any offset that leaves the two equal, including
    # zero, rather than being a tautology that passes no matter what the
    # offset is.
    lines_renderer = layers.layers["lines"].renderer()
    line_cats = list(lines_renderer.categories())
    lines_colours = {str(cat.value()): cat.symbol().color().name() for cat in line_cats}
    for grid_id, symbol in by_grid.items():
        assert symbol.symbolLayer(0).strokeColor().name() != lines_colours[grid_id]


# --- M8 acceptance walkthrough, Finding B: style `picks` ONCE, at table
# creation, never on refresh. Unlike `grids`/`lines` above (fully
# regenerated every refill, so restyling every time costs nothing), `picks`
# is user-editable -- reapplying a style on every refresh would silently
# discard the user's own symbology every time they opened the site. The
# reviewer's argument the author accepted: QGIS's own default random
# symbol "on a busy basemap can be a near-invisible dot in an arbitrary
# colour -- the difference between renders and renders findably." ---


def test_a_freshly_created_picks_table_is_styled_with_the_pick_colour(populated):
    """Asserts on the renderer QGIS actually installed, the same
    discipline `test_grids_layer_renders_as_dashed_outline_with_no_fill`
    above uses -- deleting `_style_picks` leaves the default single
    symbol (a random colour) and fails the `isinstance`/colour checks
    below."""
    session, layers, _ = populated
    renderer = layers.layers["picks"].renderer()
    assert isinstance(renderer, QgsSingleSymbolRenderer)
    symbol = renderer.symbol()
    assert symbol.color().name() == PICK_COLOUR.name()
    marker = symbol.symbolLayer(0)
    assert marker.strokeColor().name() == "#ffffff"


def test_the_style_is_saved_to_the_geopackage_not_just_the_in_memory_layer(populated):
    """The whole point of Finding B is durability beyond this one
    in-memory `QgsVectorLayer` -- a plain `setRenderer()` alone would not
    survive a new plugin session. A brand new `QgsVectorLayer` opened
    directly against the package, bypassing `layers` entirely, must come
    up styled on its own via the GeoPackage's own saved style."""
    session, layers, _ = populated
    fresh = QgsVectorLayer(f"{session.gpkg_path}|layername=picks", "picks", "ogr")
    assert fresh.isValid()
    renderer = fresh.renderer()
    assert isinstance(renderer, QgsSingleSymbolRenderer)
    assert renderer.symbol().color().name() == PICK_COLOUR.name()


def test_ensure_tables_called_again_does_not_restyle_an_up_to_date_table(populated):
    """`_ensure_table`'s up-to-date short-circuit must be what protects a
    user's own restyle, not luck: calling `ensure_tables()` again with
    nothing else changed must not touch a renderer set since the table
    was created."""
    session, layers, _ = populated
    picks = layers.layers["picks"]
    custom = QgsSymbol.defaultSymbol(QgsWkbTypes.GeometryType.PointGeometry)
    custom.setColor(QColor("#00ff00"))
    picks.setRenderer(QgsSingleSymbolRenderer(custom))

    layers.ensure_tables()

    assert layers.layers["picks"].renderer().symbol().color().name() == "#00ff00"


def test_reopening_the_package_does_not_reapply_style_over_a_user_change(populated, tmp_path):
    """A second site open must not stomp a style the user saved
    themselves through QGIS's own "Save as Default" -- `_style_picks`
    only ever runs from the create/migrate paths inside `_ensure_table`,
    never from an ordinary open of an already-current table."""
    session, layers, project = populated
    picks = layers.layers["picks"]
    custom = QgsSymbol.defaultSymbol(QgsWkbTypes.GeometryType.PointGeometry)
    custom.setColor(QColor("#00ff00"))
    picks.setRenderer(QgsSingleSymbolRenderer(custom))
    err = picks.saveStyleToDatabase("default", "the user's own style", True, "")
    assert not err

    session.save()
    session.close_site()
    session.open_site(tmp_path / SURVEY_FILE)

    reopened = layers.layers["picks"].renderer()
    assert reopened.symbol().color().name() == "#00ff00"


def test_a_migrated_picks_table_comes_out_styled(qgis_app, tmp_path):
    """`_rebuild_picks` also creates a table (`_PICKS_REBUILD`) and
    renames it into place. A migrated (pre-M8-schema) package has no
    DURABLE style to preserve -- nothing before this fix ever called
    `saveStyleToDatabase` for `picks`, so every open until now showed
    QGIS's own fresh-random default regardless of what came before.
    Styled the same as a brand new table, rather than left permanently
    unstyled: this migration runs once, exactly when the schema changes,
    so a package old enough to still need it is exactly the package that
    most needs this fix.
    """
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    session.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT", n_traces=60)
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0, 0.0, 1, p.stem))])
    session.save()
    package = session.gpkg_path
    layers.detach()
    project.clear()

    old_spec = [
        (name, kind) for name, kind in TABLES["picks"][1] if name not in ("feature_id", "seq")
    ]
    old_fields = QgsFields()
    kinds = {
        "str": QMetaType.Type.QString,
        "int": QMetaType.Type.Int,
        "float": QMetaType.Type.Double,
    }
    for name, kind in old_spec:
        old_fields.append(QgsField(name, kinds[kind]))
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.layerName = "picks"
    opts.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
    writer = QgsVectorFileWriter.create(
        str(package),
        old_fields,
        QgsWkbTypes.Type.Point,
        QgsCoordinateReferenceSystem("EPSG:32616"),
        project.transformContext(),
        opts,
    )
    assert writer.hasError() == QgsVectorFileWriter.WriterError.NoError
    del writer

    again = SiteSession()
    layers2 = SiteLayers(again, project=project)
    again.open_site(tmp_path / SURVEY_FILE)

    renderer = layers2.layers["picks"].renderer()
    assert isinstance(renderer, QgsSingleSymbolRenderer)
    assert renderer.symbol().color().name() == PICK_COLOUR.name()
    layers2.detach()


# --- fix round 1: the package CRS is the *first* grid's, and that grid's
# own CRS can be edited later (replace_grid, which Task 9's dock exposes).
# Every already-created table was written in the old CRS and must be
# rebuilt in the new one -- transformed for authored picks, simply
# refilled anew for the derived tables. --------------------------------


def test_package_crs_follows_the_first_grid_and_transforms_existing_picks(populated):
    session, layers, project = populated
    assert layers.crs().authid() == "EPSG:32616"

    # A pick recorded under the original CRS -- authored data that must
    # survive the rebuild, not just "the table still has one row".
    picks = layers.layers["picks"]
    original_point = QgsPointXY(500.0, 700.0)
    f = QgsFeature(picks.fields())
    f.setGeometry(QgsGeometry.fromPointXY(original_point))
    f["line_key"] = "raw/FILE__001.DZT"
    f["time_ns"] = 12.0
    f["note"] = "hello"
    assert picks.dataProvider().addFeatures([f])[0]

    session.replace_grid(Grid("A", (-86.8, 36.4), 0.0, 0.001, 0.001, "EPSG:4326", 0.5))

    assert layers.crs().authid() == "EPSG:4326"
    # Every table *on disk* actually carries the new CRS, not just
    # crs()'s own opinion of what it should be.
    for name in TABLES:
        on_disk = QgsVectorLayer(f"{session.gpkg_path}|layername={name}", name, "ogr")
        assert on_disk.crs().authid() == "EPSG:4326", name

    # The pick's geometry matches an independently hand-built transform,
    # not merely "some point, somewhere in the new CRS" -- and its
    # attributes are untouched.
    hand_built = QgsCoordinateTransform(
        QgsCoordinateReferenceSystem("EPSG:32616"),
        QgsCoordinateReferenceSystem("EPSG:4326"),
        project,
    )
    expected = hand_built.transform(original_point)
    assert layers.feature_count("picks") == 1
    # Re-fetch: the CRS change dropped and reopened every table, so the
    # `picks` object captured before the mutation is now a deleted C++
    # object underneath its Python wrapper.
    survivor = next(layers.layers["picks"].getFeatures())
    pt = survivor.geometry().asPoint()
    assert (pt.x(), pt.y()) == pytest.approx((expected.x(), expected.y()), abs=1e-9)
    assert survivor["line_key"] == "raw/FILE__001.DZT"
    assert survivor["time_ns"] == pytest.approx(12.0)
    assert survivor["note"] == "hello"


# --- fix round 1: a table's provider feature count can be left at the
# GPKG driver's -1 "not yet counted" sentinel, which is truthy -- most
# reliably reproduced by reopening a previously-saved site. -------------


def test_feature_count_is_correct_for_picks_on_a_reopened_site(populated, tmp_path):
    session, layers, project = populated
    picks = layers.layers["picks"]
    f = QgsFeature(picks.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    f["line_key"] = "raw/FILE__001.DZT"
    f["time_ns"] = 5.0
    assert picks.dataProvider().addFeatures([f])[0]
    session.save()
    layers.detach()

    again = SiteSession()
    layers2 = SiteLayers(again, project=project)
    again.open_site(tmp_path / "survey.nsgeo.json")

    count = layers2.feature_count("picks")
    assert count == 1  # not -1 (truthy!) and not 0
    layers2.detach()


# --- fix round 1: refresh() runs inside a Qt signal slot, and PyQt5 never
# propagates a slot's exception back to the emitter -- it prints it to
# stderr and moves on. Left unguarded, one bad table silently cancels the
# other two refills for that whole cycle. -------------------------------


def test_a_failing_table_refill_does_not_cancel_the_other_two(populated, monkeypatch):
    session, layers, _ = populated

    def boom() -> None:
        raise RuntimeError("simulated failure")

    # refresh() calls refill_grids() first, then refill_lines(), then
    # refill_marks(): breaking the *first* of the three is what actually
    # distinguishes "each refill is contained" from "a whole refresh()
    # cycle aborts on its first failure" -- breaking the last one would
    # pass either way, since the first two would already have run by
    # then regardless of containment.
    monkeypatch.setattr(layers, "refill_grids", boom)
    extra = synthetic_dzt(session.root / "raw", "FILE__004.DZT", n_traces=60)
    session.add_lines([Line.open(extra, GridPlacement("A", "y", 2.0, 0.0, 1, extra.stem))])

    # grids always raises now; lines (and marks, transitively, since it
    # runs after lines) must still reflect the new state, proving
    # refresh() didn't abandon them just because grids blew up earlier
    # in the same cycle.
    assert layers.feature_count("lines") == 4


def test_a_stale_table_schema_is_rebuilt_not_crashed_on(populated, tmp_path):
    session, layers, project = populated
    session.save()
    layers.detach()

    # Simulate an older package whose "lines" table predates several of
    # TABLES's current fields.
    stale_fields = QgsFields()
    stale_fields.append(QgsField("line_key", QMetaType.Type.QString))
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.layerName = "lines"
    opts.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
    writer = QgsVectorFileWriter.create(
        str(session.gpkg_path),
        stale_fields,
        QgsWkbTypes.Type.LineString,
        QgsCoordinateReferenceSystem("EPSG:32616"),
        project.transformContext(),
        opts,
    )
    assert writer.hasError() == QgsVectorFileWriter.WriterError.NoError
    del writer

    again = SiteSession()
    layers2 = SiteLayers(again, project=project)
    again.open_site(tmp_path / "survey.nsgeo.json")  # must not raise a KeyError

    assert layers2.feature_count("lines") == 3
    assert [f.name() for f in layers2.layers["lines"].fields() if f.name() != "fid"] == [
        name for name, _ in TABLES["lines"][1]
    ]
    layers2.detach()


# --- fix round 1: the four layers sit in a visible group, so removing one
# by hand (right-click "Remove Layer") is one click away -- must not
# break the next refresh or site close. ---------------------------------


def test_a_layer_removed_from_the_project_is_reopened_not_crashed_on(populated):
    session, layers, project = populated
    project.removeMapLayer(layers.layers["lines"].id())

    session.add_grid(Grid("B", (600.0, 700.0), 0.0, 2.0, 2.0, "EPSG:32616", 0.5))

    # Self-healed: "lines" is back, reopened fresh, and fully refilled --
    # not merely "no exception happened".
    assert layers.layers["lines"].isValid()
    assert layers.feature_count("lines") == 3

    layers.detach()  # site close / plugin unload must not raise either


# --- fix round 1: removing the last grid must not leave the previous
# grid's stale features sitting on the map. ------------------------------


def test_removing_the_last_grid_clears_the_derived_tables(populated):
    session, layers, _ = populated
    for key in list(session.keys()):
        session.remove_line(key)
    session.remove_grid("A")

    assert layers.feature_count("grids") == 0
    assert layers.feature_count("lines") == 0
    assert layers.feature_count("marks") == 0
    # Rule 1: regenerate per table, never delete the file -- the package
    # and this session's registry of its tables are still there, just
    # empty.
    assert session.gpkg_path.is_file()
    assert set(layers.layers) == set(TABLES)


# --- fix round 2: ensure_tables() sat outside refresh()'s own signal-slot
# containment, and was the largest new failure surface added by round 1
# (a schema probe, a picks migration, a create). A failing table's setup
# must be logged and must not prevent the others from being prepared. ---


def test_ensure_tables_contains_a_failing_table_and_logs_it(populated, monkeypatch, message_log):
    session, layers, _ = populated
    real_create_table = layers._create_table

    def flaky_create_table(path, name, wkb, spec, crs):
        if name == "grids":
            raise RuntimeError("simulated disk failure")
        return real_create_table(path, name, wkb, spec, crs)

    monkeypatch.setattr(layers, "_create_table", flaky_create_table)

    original_grid_feature = next(layers.layers["grids"].getFeatures())
    original_grid_wkt = original_grid_feature.geometry().asWkt()

    # A CRS change forces every table, including "grids", to need a
    # rebuild -- replace_grid, exactly as in the round-1 CRS-freeze fix.
    session.replace_grid(Grid("A", (-86.8, 36.4), 0.0, 0.001, 0.001, "EPSG:4326", 0.5))

    # "grids"'s rebuild failed and was logged -- not merely a stderr
    # traceback -- but the other three tables still got rebuilt.
    assert any("grids" in msg for msg in message_log)
    assert layers.layers["lines"].crs().authid() == "EPSG:4326"
    assert layers.layers["marks"].crs().authid() == "EPSG:4326"
    assert layers.layers["picks"].crs().authid() == "EPSG:4326"
    # And "grids" itself was neither silently rebuilt (its schema never
    # changed) nor refilled with new (4326-degree) geometry into a table
    # still declared 32616 -- it must stay exactly, byte-for-byte, as it
    # was. Stale-and-self-consistent is recoverable next refresh;
    # mislabelled-and-wrong looks correct and isn't.
    assert layers.layers["grids"].crs().authid() == "EPSG:32616"
    survivor = next(layers.layers["grids"].getFeatures())
    assert survivor.geometry().asWkt() == original_grid_wkt


# --- fix round 2: a picks rebuild must never destroy the on-disk rows
# before a verified copy exists elsewhere -- picks has no other source of
# truth, unlike grids/lines/marks which are about to be fully refilled
# from survey.nsgeo.json regardless. Each test injects a failure at a
# different point in the rebuild and asserts the picks are still on disk
# afterwards, read back independently of `layers` (which may itself be
# left in a stale state by the same failure). --------------------------


def test_picks_survive_a_failure_while_building_the_temporary_table(populated, monkeypatch):
    session, layers, _ = populated
    picks = layers.layers["picks"]
    f = QgsFeature(picks.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    f["line_key"] = "raw/FILE__001.DZT"
    f["time_ns"] = 7.0
    assert picks.dataProvider().addFeatures([f])[0]

    real_create_table = layers._create_table

    def flaky_create_table(path, name, wkb, spec, crs):
        if name == _PICKS_REBUILD:
            raise RuntimeError("simulated failure while building the temporary table")
        return real_create_table(path, name, wkb, spec, crs)

    monkeypatch.setattr(layers, "_create_table", flaky_create_table)

    session.replace_grid(Grid("A", (-86.8, 36.4), 0.0, 0.001, 0.001, "EPSG:4326", 0.5))

    # The failure happened before the real "picks" table was ever
    # touched: `layers.layers["picks"]` was never dropped...
    assert layers.feature_count("picks") == 1
    survivor = next(layers.layers["picks"].getFeatures())
    assert survivor["line_key"] == "raw/FILE__001.DZT"
    assert survivor["time_ns"] == pytest.approx(7.0)
    # ...and reading it back with a brand-new QgsVectorLayer -- not
    # through `layers`, in case a failed rebuild left its registry stale
    # -- confirms the same thing directly from disk.
    on_disk = QgsVectorLayer(f"{session.gpkg_path}|layername=picks", "picks", "ogr")
    assert on_disk.isValid()
    assert on_disk.crs().authid() == "EPSG:32616"  # unchanged: never rebuilt
    assert on_disk.featureCount() == 1 or sum(1 for _ in on_disk.getFeatures()) == 1
    # The other three tables, unaffected by picks's failure, did rebuild.
    assert layers.layers["lines"].crs().authid() == "EPSG:4326"


def test_picks_survive_a_failure_during_the_swap(populated, monkeypatch):
    session, layers, _ = populated
    picks = layers.layers["picks"]
    f = QgsFeature(picks.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    f["line_key"] = "raw/FILE__001.DZT"
    f["time_ns"] = 9.0
    assert picks.dataProvider().addFeatures([f])[0]

    real_registry = layers_module.QgsProviderRegistry

    class FlakyConnection:
        def __init__(self, real_conn):
            self._real = real_conn

        def renameVectorTable(self, schema, name, new_name):
            if name == _PICKS_REBUILD and new_name == "picks":
                raise RuntimeError("simulated failure during the swap")
            return self._real.renameVectorTable(schema, name, new_name)

        def dropVectorTable(self, schema, name):
            return self._real.dropVectorTable(schema, name)

    class FlakyMetadata:
        def __init__(self, real_md):
            self._real = real_md

        def createConnection(self, uri, options):
            return FlakyConnection(self._real.createConnection(uri, options))

    class FlakyWrapper:
        def __init__(self, real_instance):
            self._real = real_instance

        def providerMetadata(self, name):
            return FlakyMetadata(self._real.providerMetadata(name))

    class FlakyRegistry:
        @staticmethod
        def instance():
            return FlakyWrapper(real_registry.instance())

    monkeypatch.setattr(layers_module, "QgsProviderRegistry", FlakyRegistry)

    session.replace_grid(Grid("A", (-86.8, 36.4), 0.0, 0.001, 0.001, "EPSG:4326", 0.5))

    # The migrated data was verified in the temporary table, but the
    # rename-in step failed: the *original* picks table must have been
    # renamed back into place, not left missing.
    on_disk = QgsVectorLayer(f"{session.gpkg_path}|layername=picks", "picks", "ogr")
    assert on_disk.isValid()
    assert on_disk.crs().authid() == "EPSG:32616"  # the restored original, not the migrated copy
    survivor = next(on_disk.getFeatures())
    assert survivor["line_key"] == "raw/FILE__001.DZT"
    assert survivor["time_ns"] == pytest.approx(9.0)
    # No leftover backup table from the restore.
    backup = QgsVectorLayer(f"{session.gpkg_path}|layername={_PICKS_BACKUP}", _PICKS_BACKUP, "ogr")
    assert not backup.isValid()
    # `layers` itself recovers too: ensure_tables()'s reopen loop picks
    # the restored table back up.
    assert layers.feature_count("picks") == 1


# --- final review, C3: the migration's own verification step. The three
# tests above all inject a failure that *raises*; nothing covered the one
# failure mode that does not -- a migration that reports success while
# having written fewer rows than it was given. With the row-count gate
# disabled the whole qgis tier stayed green (356 passed), and in the field
# that silence runs straight on into renameVectorTable + dropVectorTable
# on the original: authored picks, permanently gone. ---------------------


class ShortWritingProvider:
    """A data provider that drops the last feature it is handed and still
    reports success -- the `addFeatures` returning `ok=True` after a short
    write that C3 is about.

    Wrapping the one layer rather than patching
    `QgsVectorDataProvider.addFeatures` on the class: measured directly,
    calling the unbound `QgsVectorDataProvider.addFeatures(provider, ...)`
    from a class-level patch does *not* reach the OGR provider's override
    -- it runs the base-class implementation, which returns False for
    every provider in the package, so the rebuild would have failed at
    the `if not ok` branch above the gate and never reached it at all.
    """

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def addFeatures(self, features, *args):
        return self._real.addFeatures(list(features)[:-1], *args)


class ShortWritingLayer:
    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def dataProvider(self):
        return ShortWritingProvider(self._real.dataProvider())


def test_a_short_migration_refuses_the_swap_rather_than_losing_picks(
    populated, monkeypatch, message_log
):
    """A migration that writes fewer rows than it was handed must be
    caught by the row-count check, not by whatever raises next.

    `addFeatures` is made to genuinely drop a row and still report
    success, rather than `featureCount` being made to lie: the count then
    under-reports because the temporary table really is short, which is
    the failure the guard exists for and the one that costs data. Faking
    the count instead would leave a complete migrated table on disk, so
    the swap it prevents would have been harmless and the test would
    prove nothing about the consequence.
    """
    session, layers, _ = populated
    picks = layers.layers["picks"]
    feats = []
    for i, time_ns in enumerate((11.0, 12.0)):
        f = QgsFeature(picks.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0 + i, 700.0 + i)))
        f["line_key"] = f"raw/FILE__00{i + 1}.DZT"
        f["time_ns"] = time_ns
        feats.append(f)
    assert picks.dataProvider().addFeatures(feats)[0]

    real_layer_class = layers_module.QgsVectorLayer

    def only_the_rebuild_table_writes_short(uri, name, provider):
        layer = real_layer_class(uri, name, provider)
        return ShortWritingLayer(layer) if name == _PICKS_REBUILD else layer

    monkeypatch.setattr(layers_module, "QgsVectorLayer", only_the_rebuild_table_writes_short)

    session.replace_grid(Grid("A", (-86.8, 36.4), 0.0, 0.001, 0.001, "EPSG:4326", 0.5))

    # ensure_tables() contains a per-table failure (see its own comment),
    # so the RuntimeError is reported through the log rather than raised
    # out of the signal -- the count it names is the whole point.
    assert any("picks migration wrote 1 of 2 rows" in m for m in message_log), message_log

    # The original table was never touched: read it back with a brand-new
    # QgsVectorLayer rather than through `layers`, in case a failed
    # rebuild left its registry stale (the same reason
    # test_picks_survive_a_failure_while_building_the_temporary_table
    # does it this way).
    on_disk = QgsVectorLayer(f"{session.gpkg_path}|layername=picks", "picks", "ogr")
    assert on_disk.isValid()
    assert on_disk.crs().authid() == "EPSG:32616"  # unchanged: never rebuilt
    rows = sorted((f["line_key"], f["time_ns"]) for f in on_disk.getFeatures())
    assert rows == [
        ("raw/FILE__001.DZT", pytest.approx(11.0)),
        ("raw/FILE__002.DZT", pytest.approx(12.0)),
    ]
    # The swap never began, so there is no renamed-out original either.
    backup = QgsVectorLayer(f"{session.gpkg_path}|layername={_PICKS_BACKUP}", _PICKS_BACKUP, "ogr")
    assert not backup.isValid()


# --- final review, Important 1: two related holes in the migration's
# safety net, both found on the whole-branch review rather than any
# per-task review, and both of which silently destroy every authored
# pick while reporting a successful migration.
#
# (a) `_read_picks_rows` used to return `[]` when the on-disk table
# would not open at all -- indistinguishable from "opened and genuinely
# has zero rows". The swap's own row-count gate then compares the
# migrated count against `len(old_rows)`, i.e. 0 == 0, passes trivially,
# and the real (never actually read) table is renamed out and dropped
# while an empty one takes its place.
#
# (b) `_table_schema` used to return the identical `(None, [])` for
# "no table by this name exists yet" and "a table by this name exists
# but will not open" -- so `_ensure_table` could not tell a
# present-but-broken `picks` table apart from a brand-new site, and
# routed it into `_create_table`'s `CreateOrOverwriteLayer`, the same
# path a genuinely fresh package takes. ----------------------------------


def test_picks_survive_a_failure_to_open_the_table_before_a_migration(
    populated, monkeypatch, message_log
):
    """Important 1a. `_read_picks_rows` is only ever called from
    `_rebuild_picks`, itself only reached once `_table_schema` has just
    opened `picks` successfully in this same `_ensure_table` call -- so
    a SECOND open of that same table failing means something changed in
    between (a lock, a permissions change, momentary corruption), not an
    empty table.

    Simulated by making `_read_picks_rows`'s OWN construction of the
    `picks` `QgsVectorLayer` come back invalid, identified by inspecting
    the immediate caller's frame rather than by call order or count.
    `_table_schema`'s own probe inside `_ensure_table` builds the
    textually identical `QgsVectorLayer(path, "picks", "ogr")` call, so
    the two cannot be told apart by their arguments at all -- and
    `replace_grid` below drives TWO refreshes (`grids_changed` then
    `lines_changed`, both connected to `SiteLayers.refresh`), so a fault
    keyed on call order or count would have to land on a different call
    each time and would either mis-fire or stop firing on the second
    refresh. A fault keyed on the caller's function name fires
    identically and persistently on every attempt regardless -- the same
    property the two sibling tests above rely on by keying their own
    injected faults on a stable name (`_PICKS_REBUILD`, a rename's own
    arguments) rather than a count. Monkeypatching `QgsVectorLayer.isValid`
    on the class instead was ruled out for the same reason those two
    call sites cannot be told apart by arguments: it would blind
    `_table_schema`'s probe too, and `_rebuild_picks` would never be
    reached at all -- the very path this hole is in.
    """
    session, layers, _ = populated
    picks = layers.layers["picks"]
    f = QgsFeature(picks.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    f["line_key"] = "raw/FILE__001.DZT"
    f["time_ns"] = 5.0
    assert picks.dataProvider().addFeatures([f])[0]

    real_layer_class = layers_module.QgsVectorLayer

    class Unopenable:
        def isValid(self):
            return False

        def __getattr__(self, attr):
            raise AssertionError(f"_read_picks_rows touched {attr!r} on a layer that never opened")

    def picks_wont_open_for_read_picks_rows(uri, name, provider):
        caller = sys._getframe(1).f_code.co_name
        if name == "picks" and provider == "ogr" and caller == "_read_picks_rows":
            return Unopenable()
        return real_layer_class(uri, name, provider)

    monkeypatch.setattr(layers_module, "QgsVectorLayer", picks_wont_open_for_read_picks_rows)

    session.replace_grid(Grid("A", (-86.8, 36.4), 0.0, 0.001, 0.001, "EPSG:4326", 0.5))

    # ensure_tables() contains a per-table failure, the same as the two
    # sibling failure-injection tests above: the RuntimeError is logged,
    # not raised out of the signal.
    assert any("picks" in m and "untouched" in m for m in message_log), message_log

    # Nothing was ever migrated or swapped: read the ORIGINAL table back
    # with a brand-new, unpatched QgsVectorLayer -- not through `layers`,
    # in case a failed rebuild left its registry stale, the same reason
    # the sibling tests above do it this way.
    on_disk = QgsVectorLayer(f"{session.gpkg_path}|layername=picks", "picks", "ogr")
    assert on_disk.isValid()
    assert on_disk.crs().authid() == "EPSG:32616"  # unchanged: never rebuilt
    survivor = next(on_disk.getFeatures())
    assert survivor["line_key"] == "raw/FILE__001.DZT"
    assert survivor["time_ns"] == pytest.approx(5.0)


def test_an_unopenable_picks_table_is_refused_not_overwritten(populated, monkeypatch, message_log):
    """Important 1b. Before this fix, a `picks` table that is present on
    disk but will not open through `QgsVectorLayer` right now (a lock, a
    permissions problem, anything short-lived) was indistinguishable
    from a table that has never existed at all -- `_ensure_table` would
    route it straight into `_create_table`'s `CreateOrOverwriteLayer`
    and destroy it, the same path a genuinely new site takes.

    Simulated by making EVERY construction of the `picks`
    `QgsVectorLayer` come back invalid, unconditionally -- no call-order
    tricks are needed here, because this test drives exactly ONE
    `refresh()` by calling it directly rather than through a signal, so
    there is only ever one attempt to open `picks` per table probe.
    `_table_schema`'s presence check goes through
    `QgsProviderRegistry`'s own connection instead of `QgsVectorLayer`
    (see its docstring), which this test never touches, so it genuinely
    finds the real table sitting there. No grid or schema change is
    involved -- this is deliberately a plain `refresh()`, because the
    defect is that `_ensure_table` could not tell "broken" from
    "absent" even when NOTHING about the table's own required shape had
    changed.
    """
    session, layers, _ = populated
    picks = layers.layers["picks"]
    f = QgsFeature(picks.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    f["line_key"] = "raw/FILE__001.DZT"
    f["time_ns"] = 6.0
    assert picks.dataProvider().addFeatures([f])[0]

    real_layer_class = layers_module.QgsVectorLayer

    class Unopenable:
        def isValid(self):
            return False

        def __getattr__(self, attr):
            raise AssertionError(f"an unopenable picks layer should not be asked for {attr!r}")

    def picks_wont_open(uri, name, provider):
        if name == "picks" and provider == "ogr":
            return Unopenable()
        return real_layer_class(uri, name, provider)

    monkeypatch.setattr(layers_module, "QgsVectorLayer", picks_wont_open)

    layers.refresh()

    assert any("picks" in m and "could not" in m for m in message_log), message_log

    # The real table -- seeded row included -- was never touched: read
    # it back with a brand-new, unpatched QgsVectorLayer, not through
    # `layers` (whose registry may not even still hold "picks").
    on_disk = QgsVectorLayer(f"{session.gpkg_path}|layername=picks", "picks", "ogr")
    assert on_disk.isValid()
    assert on_disk.crs().authid() == "EPSG:32616"
    survivor = next(on_disk.getFeatures())
    assert survivor["line_key"] == "raw/FILE__001.DZT"
    assert survivor["time_ns"] == pytest.approx(6.0)


# --- fix round 2: an untransformable CRS pair (measured with a projected
# CRS on Earth and a geographic one on Mars) leaves QgsCoordinateTransform
# invalid and short-circuited -- both the point- and geometry-based
# transform() calls then silently return their input unchanged while
# reporting success. Unchecked, that relabels a pick into the wrong CRS
# rather than transforming it: the rebuild must refuse instead. ---------


def test_an_untransformable_crs_pair_refuses_rather_than_relabelling_a_pick(populated):
    session, layers, _ = populated
    picks = layers.layers["picks"]
    f = QgsFeature(picks.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    f["line_key"] = "raw/FILE__001.DZT"
    f["time_ns"] = 3.0
    assert picks.dataProvider().addFeatures([f])[0]

    mars = Grid("A", (0.0, 0.0), 0.0, 0.001, 0.001, "ESRI:104905", 0.5)  # GCS_Mars_2000
    session.replace_grid(mars)

    # The rebuild refused rather than silently relabelling the pick into
    # a CRS PROJ has no path to: the original table, CRS, and geometry
    # are exactly as they were.
    on_disk = QgsVectorLayer(f"{session.gpkg_path}|layername=picks", "picks", "ogr")
    assert on_disk.isValid()
    assert on_disk.crs().authid() == "EPSG:32616"
    survivor = next(on_disk.getFeatures())
    pt = survivor.geometry().asPoint()
    assert (pt.x(), pt.y()) == pytest.approx((500.0, 700.0))
    assert survivor["line_key"] == "raw/FILE__001.DZT"


# --- fix round 3: a leftover _PICKS_BACKUP is not cosmetic -- nothing
# ever cleaned it up, so it wedged every future rebuild permanently
# (picks frozen at its old CRS *and* old field set forever, even though
# the data itself was safe and the failure logged loudly). -------------


def test_a_stale_rebuild_backup_is_cleared_not_wedged_forever(populated):
    session, layers, _ = populated

    # Plant a leftover backup, as if a previous rebuild's final cleanup
    # step (dropping the backup once the swap had already succeeded) had
    # failed: rename the current "picks" out, then recreate a fresh one
    # in its place -- exactly what a completed-but-not-cleaned-up rebuild
    # leaves behind on disk.
    conn = (
        QgsProviderRegistry.instance()
        .providerMetadata("ogr")
        .createConnection(str(session.gpkg_path), {})
    )
    layers._drop_loaded_layer("picks")
    conn.renameVectorTable("", "picks", _PICKS_BACKUP)
    layers._create_table(
        str(session.gpkg_path),
        "picks",
        QgsWkbTypes.Type.Point,
        TABLES["picks"][1],
        QgsCoordinateReferenceSystem("EPSG:32616"),
    )

    # A later, unrelated rebuild (a real CRS change) must not be wedged
    # by the leftover: without clearing it first, the rename this
    # rebuild needs ("picks" -> the same backup name) fails with "table
    # already exists" -- and would keep failing on every subsequent
    # refresh too, freezing "picks" at its old CRS forever even though
    # the data itself is never actually at risk.
    session.replace_grid(Grid("A", (-86.8, 36.4), 0.0, 0.001, 0.001, "EPSG:4326", 0.5))

    assert layers.layers["picks"].crs().authid() == "EPSG:4326"


# --- fix round 3: process death between the two renames in
# _rebuild_picks left the authored rows on disk but invisible to the
# plugin -- and, unrecovered, triggered the round-3 Finding 2 wedge on
# every later attempt. The recovery the docstring already claimed must
# actually happen. ------------------------------------------------------


def test_reopening_after_a_crash_between_the_two_renames_recovers_picks(populated, tmp_path):
    session, layers, project = populated
    picks = layers.layers["picks"]
    f = QgsFeature(picks.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    f["line_key"] = "raw/FILE__001.DZT"
    f["time_ns"] = 42.0
    assert picks.dataProvider().addFeatures([f])[0]
    session.save()

    # Simulate a crash exactly between the two renames in _rebuild_picks:
    # the original "picks" has been renamed to its backup name, and
    # nothing else has happened -- as if the process died right there.
    layers.detach()
    project.clear()
    conn = (
        QgsProviderRegistry.instance()
        .providerMetadata("ogr")
        .createConnection(str(session.gpkg_path), {})
    )
    conn.renameVectorTable("", "picks", _PICKS_BACKUP)

    again = SiteSession()
    layers2 = SiteLayers(again, project=project)
    again.open_site(tmp_path / "survey.nsgeo.json")

    assert layers2.feature_count("picks") == 1
    survivor = next(layers2.layers["picks"].getFeatures())
    assert survivor["line_key"] == "raw/FILE__001.DZT"
    assert survivor["time_ns"] == pytest.approx(42.0)
    # No leftover backup once recovered -- otherwise this is exactly the
    # round-3 Finding 2 wedge, reintroduced.
    backup = QgsVectorLayer(f"{session.gpkg_path}|layername={_PICKS_BACKUP}", _PICKS_BACKUP, "ogr")
    assert not backup.isValid()

    layers2.detach()


# --- strengthened proof: picks survive attributes and geometry intact,
# across several different refill-triggering mutations, not merely "the
# table still has a row" ------------------------------------------------


def test_picks_survive_multiple_refills_with_attributes_intact(populated):
    session, layers, _ = populated
    picks = layers.layers["picks"]
    f = QgsFeature(picks.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(501.0, 705.0)))
    f["line_key"] = "raw/FILE__001.DZT"
    f["trace"] = 12
    f["time_ns"] = 43.1
    f["note"] = "a hand-picked reflector"
    assert picks.dataProvider().addFeatures([f])[0]

    # Three separate mutations, each of which refills grids/lines/marks
    # through a different signal (grids_changed, lines_changed twice).
    session.add_grid(Grid("B", (600.0, 700.0), 0.0, 2.0, 2.0, "EPSG:32616", 0.5))
    session.remove_line("raw/FILE__002.DZT")
    extra = synthetic_dzt(session.root / "raw", "FILE__004.DZT", n_traces=60)
    session.add_lines([Line.open(extra, GridPlacement("A", "y", 2.0, 0.0, 1, extra.stem))])

    assert layers.feature_count("picks") == 1
    survivor = next(picks.getFeatures())
    assert survivor["line_key"] == "raw/FILE__001.DZT"
    assert survivor["trace"] == 12
    assert survivor["time_ns"] == pytest.approx(43.1)
    assert survivor["note"] == "a hand-picked reflector"
    pt = survivor.geometry().asPoint()
    assert (pt.x(), pt.y()) == pytest.approx((501.0, 705.0))

    # And prove the three mutations actually landed in the derived tables
    # -- a silently aborted refresh (see the "refill containment" tests
    # below) would leave picks untouched too, so that assertion alone
    # cannot tell "picks correctly ignored" apart from "nothing ran".
    assert layers.feature_count("grids") == 2  # A, B
    assert layers.feature_count("lines") == 3  # 001, 003, 004 (002 removed)


# --- a single unplaceable line must degrade, not abort the whole build --
# (see Line.trace_coords / GridPlacement.distance_along, which raise
# ValueError for a time-triggered acquisition: traces_per_metre <= 0)
#
# These tests add the bad line *and* a good new line in the same
# add_lines() call, with the bad one first in iteration order. That
# ordering matters: PyQt5 swallows an exception raised inside a directly
# connected slot (prints it to stderr, does not re-raise to the caller),
# so a version that lets the ValueError escape refill_lines() partway
# through would silently abort the whole rebuild -- the *good* new line
# would never be written either, and feature_count would sit at its
# stale pre-mutation value. Asserting only "count unchanged, bad key
# absent" cannot tell that apart from correct per-line degradation;
# asserting the good new line *is* present can. -------------------------


def test_an_unplaceable_line_is_skipped_not_fatal(populated):
    session, layers, _ = populated
    bad = synthetic_dzt(session.root / "raw", "FILE__099.DZT", n_traces=40, traces_per_metre=0.0)
    good = synthetic_dzt(session.root / "raw", "FILE__100.DZT", n_traces=60)
    session.add_lines(
        [
            Line.open(bad, GridPlacement("A", "y", 10.0, 0.0, 1, "FILE__099")),
            Line.open(good, GridPlacement("A", "y", 1.5, 0.0, 1, "FILE__100")),
        ]
    )
    assert layers.feature_count("lines") == 4  # 3 original + the good new one
    keys = {f["line_key"] for f in layers.layers["lines"].getFeatures()}
    assert "raw/FILE__099.DZT" not in keys
    assert "raw/FILE__100.DZT" in keys  # proves refill_lines kept going past the bad one


def test_an_unplaceable_line_with_a_sidecar_does_not_break_marks(populated):
    session, layers, _ = populated
    bad = synthetic_dzt(session.root / "raw", "FILE__098.DZT", n_traces=40, traces_per_metre=0.0)
    (session.root / "raw" / "FILE__098.DZX").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<DZX xmlns="www.geophysical.com/DZX/1.02"><File><name>FILE__098.DZT</name>
<Profile><WayPt><scan>5</scan><mark>User</mark><name>BadMark</name></WayPt></Profile></File></DZX>"""
    )
    good = synthetic_dzt(session.root / "raw", "FILE__101.DZT", n_traces=60)
    (session.root / "raw" / "FILE__101.DZX").write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<DZX xmlns="www.geophysical.com/DZX/1.02"><File><name>FILE__101.DZT</name>
<Profile><WayPt><scan>10</scan><mark>User</mark><name>GoodMark</name></WayPt></Profile></File></DZX>"""
    )
    session.add_lines(
        [
            Line.open(bad, GridPlacement("A", "y", 10.0, 0.0, 1, "FILE__098")),
            Line.open(good, GridPlacement("A", "y", 2.0, 0.0, 1, "FILE__101")),
        ]
    )
    # FILE__002's original mark plus FILE__101's new one; FILE__098's line
    # (and so its mark) is degraded rather than crashing refill_marks for
    # everyone, and FILE__101 -- iterated after the bad line -- still gets
    # written.
    assert layers.feature_count("marks") == 2
    keys = {f["line_key"] for f in layers.layers["marks"].getFeatures()}
    assert keys == {"raw/FILE__002.DZT", "raw/FILE__101.DZT"}


# --- real files: known trace counts, real sidecars, plausible geometry --


@needs_real_data
def test_real_files_build_plausible_lines_and_marks(qgis_app, tmp_path):
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    session.add_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5))
    opts = ImportOptions(grid_id="A", axis="y", spacing=0.5, grid_size_along=11.0)
    rows = plan_import(REAL_DZT, opts)
    lines = rows_to_lines(rows, opts)
    session.add_lines(lines)

    try:
        assert len(lines) == 10
        assert layers.feature_count("lines") == 10
        built_traces = sorted(int(f["n_traces"]) for f in layers.layers["lines"].getFeatures())
        assert built_traces == [606, 608, 608, 613, 625, 629, 635, 653, 658, 666]
        for feat in layers.layers["lines"].getFeatures():
            assert 9.0 < feat.geometry().length() < 13.2  # known real-file length range

        expected_marks = 0
        for path in REAL_DZT:
            info = read_dzx(path)
            if info is not None:
                expected_marks += len(info.marks)
        assert expected_marks > 0
        assert layers.feature_count("marks") == expected_marks

        all_keys = session.keys()
        key_007 = next(k for k in all_keys if Path(k).stem == "FILE__007")
        marks_007 = [f for f in layers.layers["marks"].getFeatures() if f["line_key"] == key_007]
        assert len(marks_007) == 1  # matches task 7's known fact about FILE__007
    finally:
        layers.detach()
        project.clear()


def test_renaming_the_site_folder_does_not_orphan_authored_picks(qgis_app, tmp_path, message_log):
    """Final review, I5, end to end: the pick has to come back.

    The session-level tests pin the path and the adoption; this one is
    the reason both exist. Author a pick in Site1/, rename the folder to
    Kavusan2026/ once the fieldwork has a name, reopen -- and read the
    picks table straight off disk with a fresh QgsVectorLayer rather than
    through `layers`, so a stale registry could not fake the result.
    Before the fix `gpkg_path` resolved to a file that did not exist,
    ensure_tables() created a fresh empty package, and the pick was
    orphaned under the old filename with no message at all.
    """
    project = QgsProject.instance()
    project.clear()
    old = tmp_path / "Site1"
    old.mkdir()
    session = SiteSession()
    session.new_site(old)
    layers = SiteLayers(session, project=project)
    session.add_grid(GRID)
    line = Line.open(
        synthetic_dzt(old / "raw", "FILE__001.DZT", n_traces=60),
        GridPlacement("A", "y", 0.0, 0.0, 1, "FILE__001"),
    )
    session.add_lines([line])
    session.save()

    picks = layers.layers["picks"]
    feat = QgsFeature(picks.fields())
    feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    feat.setAttribute("line_key", "raw/FILE__001.DZT")
    feat.setAttribute("note", "an hour of depth picks")
    ok, _ = picks.dataProvider().addFeatures([feat])
    assert ok
    assert layers.feature_count("picks") == 1
    old_package = session.gpkg_path
    assert old_package.is_file()

    layers.detach()
    session.close_site()
    project.clear()

    new = tmp_path / "Kavusan2026"
    old.rename(new)

    session2 = SiteSession()
    layers2 = SiteLayers(session2, project=project)
    session2.open_site(new / SURVEY_FILE)

    on_disk = QgsVectorLayer(f"{session2.gpkg_path}|layername=picks", "picks", "ogr")
    assert on_disk.isValid()
    rows = list(on_disk.getFeatures())
    assert len(rows) == 1
    assert rows[0]["note"] == "an hour of depth picks"

    layers2.detach()
    project.clear()


def test_a_package_written_under_the_old_name_is_adopted_with_its_picks(
    qgis_app, tmp_path, message_log
):
    """Final review, I5, the migration, with a real GeoPackage.

    Every package already written in the field carries the folder name it
    was created under, which no rule can re-derive once the folder is
    renamed -- so a site directory holding only `Site1.nsgeo.gpkg` must
    not come up with an empty picks layer. Simulated exactly: author a
    pick, rename the package to the pre-fix spelling, rename the folder,
    reopen. Read back off disk with a fresh QgsVectorLayer, not through
    `layers`.
    """
    project = QgsProject.instance()
    project.clear()
    old = tmp_path / "Site1"
    old.mkdir()
    session = SiteSession()
    session.new_site(old)
    layers = SiteLayers(session, project=project)
    session.add_grid(GRID)
    session.save()

    picks = layers.layers["picks"]
    feat = QgsFeature(picks.fields())
    feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    feat.setAttribute("note", "authored before the fix")
    ok, _ = picks.dataProvider().addFeatures([feat])
    assert ok
    package = session.gpkg_path
    layers.detach()
    session.close_site()
    project.clear()

    legacy = old / "Site1.nsgeo.gpkg"  # what a pre-fix package is called
    package.rename(legacy)
    new = tmp_path / "Kavusan2026"
    old.rename(new)

    session2 = SiteSession()
    layers2 = SiteLayers(session2, project=project)
    session2.open_site(new / SURVEY_FILE)

    assert not (new / "Site1.nsgeo.gpkg").exists()  # adopted, not copied
    assert any("Site1.nsgeo.gpkg" in m for m in message_log), message_log
    on_disk = QgsVectorLayer(f"{session2.gpkg_path}|layername=picks", "picks", "ogr")
    assert on_disk.isValid()
    rows = list(on_disk.getFeatures())
    assert len(rows) == 1
    assert rows[0]["note"] == "authored before the fix"

    layers2.detach()
    project.clear()


# --- final review, I6: detach() runs on site_closed -- i.e. on every "Open
# site..." and on unload() -- and called removeMapLayers() unconditionally.
# `picks` is deliberately writable (setReadOnly(name in DERIVED)), so a
# layer with isEditable() and isModified() true was destroyed with no
# prompt, no signal and no exception. QGIS's own unsaved-edits prompt lives
# in the application's layer-removal *action*, not in
# QgsProject::removeMapLayers. ---


def _buffer_a_pick(layers, note="an hour of depth picks"):
    picks = layers.layers["picks"]
    assert picks.startEditing()
    feat = QgsFeature(picks.fields())
    feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    feat.setAttribute("line_key", "raw/FILE__001.DZT")
    feat.setAttribute("note", note)
    assert picks.addFeature(feat)
    assert picks.isEditable() and picks.isModified()
    return picks


def test_detach_saves_buffered_pick_edits_rather_than_destroying_them(populated, message_log):
    session, layers, project = populated
    _buffer_a_pick(layers)
    path = session.gpkg_path

    layers.detach()

    # Read back off disk with a fresh layer, not through `layers`: the
    # registry entry is exactly what detach() just removed, so anything
    # going through it would prove nothing about the file.
    on_disk = QgsVectorLayer(f"{path}|layername=picks", "picks", "ogr")
    assert on_disk.isValid()
    rows = list(on_disk.getFeatures())
    assert len(rows) == 1
    assert rows[0]["note"] == "an hour of depth picks"
    assert any("picks" in m for m in message_log)


def test_closing_the_site_saves_buffered_pick_edits(populated):
    # The reported path, through the real signal: toggle editing,
    # digitise picks for an hour, forget "Save Layer Edits", click "Open
    # site..." -- which closes the current site, which is what reaches
    # detach(). Driven through session.close_site() so the wiring
    # (site_closed -> detach) is part of what is pinned.
    session, layers, project = populated
    _buffer_a_pick(layers, note="closed without saving")
    path = session.gpkg_path

    session.close_site()

    assert layers.layers == {}  # the site really did close
    on_disk = QgsVectorLayer(f"{path}|layername=picks", "picks", "ogr")
    assert on_disk.isValid()
    rows = list(on_disk.getFeatures())
    assert len(rows) == 1
    assert rows[0]["note"] == "closed without saving"


def test_pick_edits_that_cannot_be_saved_are_reported_at_critical(populated, monkeypatch, qgis_app):
    # If the commit itself fails there is nothing left to do -- the site
    # is closing either way, exactly as unload()'s own prompt has no
    # Cancel -- so the one thing that must not happen is silence.
    from qgis.core import QgsApplication

    session, layers, project = populated
    _buffer_a_pick(layers)
    monkeypatch.setattr(QgsVectorLayer, "commitChanges", lambda self, *a, **kw: False)

    seen: list[tuple[str, int]] = []
    log = QgsApplication.messageLog()

    def _on_message(msg, tag, level):
        seen.append((msg, int(level)))

    log.messageReceived.connect(_on_message)
    try:
        layers.detach()
    finally:
        log.messageReceived.disconnect(_on_message)

    critical = int(Qgis.MessageLevel.Critical)
    assert any("picks" in msg and "1" in msg and level == critical for msg, level in seen), seen
    assert layers.layers == {}  # still torn down; the site is closing regardless


# --- M8 acceptance walkthrough, Finding A: the author's own words --
# "if I selected a point and deleted it and hit save, the pick stayed
# visible in the profile until I made another pick in the profile, at
# which time the deleted ones would disappear." The cause: nothing
# watched the `picks` layer's OWN editing signals, so `session.picks_
# changed` -- emitted only from `SiteSession.add_pick` -- never fired for
# an ordinary QGIS delete/move/add/rollback. These tests pin the
# SiteLayers-level wiring, driven through REAL edit-buffer operations
# (`startEditing`/`deleteFeature`/`commitChanges`), not by emitting the
# signal by hand -- see test_plugin_profile_dock.py for the end-to-end
# (dock + real layer) versions asserting on `dock.view._picks` itself. ---


def test_a_buffered_delete_notifies_picks_changed_before_any_commit(populated):
    """The responsiveness the author asked for ("could we make that link
    more responsive somehow"): visible from the edit buffer alone, before
    `commitChanges()` ever runs."""
    session, layers, _ = populated
    layers.write_pick(_a_pick())
    picks = layers.layers["picks"]
    fid = next(picks.getFeatures()).id()
    seen: list[int] = []
    session.picks_changed.connect(lambda: seen.append(1))

    assert picks.startEditing()
    assert picks.deleteFeature(fid)

    assert seen == [1]
    picks.rollBack()


def test_a_committed_add_through_the_edit_buffer_notifies_picks_changed(populated):
    """Measured directly (a probe script, not assumed): committing a plain
    `addFeature` fires THREE of our six bound signals, not one --
    `featureAdded` and `featuresDeleted` fire again internally as QGIS's
    edit buffer swaps the buffered feature's temporary negative fid for
    the real one the provider assigned, in addition to
    `afterCommitChanges` itself. `picks_changed` therefore fires four
    times total for one add-then-save (one live, three from the commit),
    not two -- documented here exactly, not loosened to "at least
    twice", so a change to that internal replay is caught rather than
    quietly tolerated. Harmless: each `_refresh_picks()` read is
    idempotent and cheap for the handful-to-low-thousands of rows this
    table ever holds (see `picks_for`'s own docstring) -- redundant
    reads triggered by an explicit save are not a cost worth chasing
    away with de-duplication state that only Finding A would ever use.
    """
    session, layers, _ = populated
    picks = layers.layers["picks"]
    seen: list[int] = []
    session.picks_changed.connect(lambda: seen.append(1))

    assert picks.startEditing()
    f = QgsFeature(picks.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    f.setAttribute("line_key", "raw/FILE__001.DZT")
    f.setAttribute("trace", 3)
    f.setAttribute("time_ns", 9.0)
    assert picks.addFeature(f)
    assert seen == [1]  # live, from featureAdded, before any commit

    assert picks.commitChanges()
    assert seen == [1, 1, 1, 1]  # afterCommitChanges + the fid-swap replay above


def test_a_geometry_move_through_the_edit_buffer_notifies_picks_changed(populated):
    """A geometry-only edit doesn't change `(trace, time_ns)`, so this
    counts emissions of `picks_changed` rather than reading rendered
    content -- proving `geometryChanged` alone drives a notification, not
    merely that unrelated content happens to still match. Committed
    (not rolled back), matching the brief's own required minimum: "a
    delete... followed by a commit... the same for an add and for a
    geometry move". A geometry commit is clean (measured): only
    `afterCommitChanges` fires in addition to the live `geometryChanged`,
    unlike the add/delete cases above and below.
    """
    session, layers, _ = populated
    layers.write_pick(_a_pick())
    picks = layers.layers["picks"]
    fid = next(picks.getFeatures()).id()
    seen: list[int] = []
    session.picks_changed.connect(lambda: seen.append(1))

    assert picks.startEditing()
    assert picks.changeGeometry(fid, QgsGeometry.fromPointXY(QgsPointXY(501.0, 707.0)))
    assert seen == [1]  # live, before any commit

    assert picks.commitChanges()
    assert seen == [1, 1]  # afterCommitChanges only -- a geometry commit is clean


def test_an_attribute_change_through_the_edit_buffer_notifies_picks_changed(populated):
    session, layers, _ = populated
    layers.write_pick(_a_pick())
    picks = layers.layers["picks"]
    fid = next(picks.getFeatures()).id()
    idx = picks.fields().indexOf("note")
    seen: list[int] = []
    session.picks_changed.connect(lambda: seen.append(1))

    assert picks.startEditing()
    assert picks.changeAttributeValue(fid, idx, "edited by hand")
    assert seen == [1]  # live, before any commit

    assert picks.commitChanges()
    assert seen == [1, 1]  # afterCommitChanges only -- an attribute commit is clean too


def test_a_rollback_notifies_picks_changed_too(populated):
    """A rollback restores the on-disk view -- the profile must be told
    that changed just as it is told about a commit. Measured: undoing a
    `deleteFeature` replays as a `featureAdded` (the row comes back)
    ahead of `afterRollBack` itself, so this fires twice, not once --
    the rollback mirror image of the add-then-commit fid-swap above.
    Harmless for the same reason: a second, idempotent read.
    """
    session, layers, _ = populated
    layers.write_pick(_a_pick())
    picks = layers.layers["picks"]
    fid = next(picks.getFeatures()).id()
    assert picks.startEditing()
    assert picks.deleteFeature(fid)

    seen: list[int] = []
    session.picks_changed.connect(lambda: seen.append(1))
    assert picks.rollBack()

    assert seen == [1, 1]


def test_write_pick_does_not_double_emit_picks_changed(populated):
    """Hazard 3 from the brief: `write_pick` goes through the data
    provider directly, bypassing the edit buffer, and `SiteSession.
    add_pick` already emits `picks_changed` itself once the write
    returns -- none of the six edit-buffer/commit/rollback signals bound
    here may ALSO fire for an authored pick."""
    session, layers, _ = populated
    seen: list[int] = []
    session.picks_changed.connect(lambda: seen.append(1))

    layers.write_pick(_a_pick())

    assert seen == []  # write_pick itself never emits; add_pick does that


def test_repeated_ensure_tables_calls_do_not_accumulate_duplicate_bindings(populated):
    """`_bind_picks_signals` runs at the end of every `ensure_tables()`
    call, unconditionally. It must unbind before rebinding, or a picks
    edit after several refreshes would fire `picks_changed` once per
    accumulated (duplicate) connection instead of once."""
    session, layers, _ = populated
    layers.ensure_tables()
    layers.ensure_tables()
    layers.ensure_tables()
    picks = layers.layers["picks"]
    seen: list[int] = []
    session.picks_changed.connect(lambda: seen.append(1))

    assert picks.startEditing()
    f = QgsFeature(picks.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    f.setAttribute("line_key", "raw/FILE__001.DZT")
    assert picks.addFeature(f)

    assert seen == [1]


def test_detach_does_not_emit_picks_changed_from_its_own_commit(populated, message_log):
    """Hazard 2 from the brief: `_commit_pending_edits()` runs inside
    `detach()`, which would otherwise fire `afterCommitChanges` for a
    buffered edit while the layer is on its way out, for a site the
    session has already forgotten. Unbinding first (see `detach()`'s own
    comment) means that final commit stays silent -- proven here by
    asserting the signal never fires at all, not merely that nothing
    crashes."""
    session, layers, _ = populated
    _buffer_a_pick(layers)
    seen: list[int] = []
    session.picks_changed.connect(lambda: seen.append(1))

    layers.detach()

    assert seen == []
    assert any("picks" in m for m in message_log)  # the edit was still saved, just quietly


def test_the_picks_binding_survives_a_site_close_and_reopen(populated, tmp_path):
    """Hazard 1 from the brief: a site reopen replaces the `picks` layer
    OBJECT outright (`detach()` empties the registry, `ensure_tables()`
    opens a fresh one) -- a connection made once at construction and
    never renewed would point at a dead wrapper after the reopen and
    silently stop working, the exact defect `MapLink._rebind_layer`
    exists to prevent for its own three layers."""
    session, layers, project = populated
    session.save()

    session.close_site()
    session.open_site(tmp_path / SURVEY_FILE)

    picks = layers.layers["picks"]
    seen: list[int] = []
    session.picks_changed.connect(lambda: seen.append(1))
    assert picks.startEditing()
    f = QgsFeature(picks.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    f.setAttribute("line_key", "raw/FILE__001.DZT")
    assert picks.addFeature(f)

    assert seen == [1]


# --- controller review of I5: _adopt_legacy_package() renamed the .gpkg
# alone. A SQLite database left by a process that did not close cleanly --
# a QGIS crash or kill, which is not rare -- keeps a hot `-wal`/`-shm`
# beside it, and SQLite finds those by the database's *current* name.
# Renaming the database out from under them silently discards every commit
# since the last checkpoint. The migration runs automatically on the first
# open after upgrade, so the upgrade itself could destroy the picks it
# exists to rescue. ---

_LEAVE_A_HOT_WAL = """
import os, sqlite3, sys
con = sqlite3.connect(sys.argv[1])
con.execute("PRAGMA journal_mode=WAL")
con.execute("CREATE TABLE uncheckpointed (note TEXT)")
con.execute("INSERT INTO uncheckpointed VALUES ('the last hour of picks')")
con.commit()
os._exit(0)  # killed: no close(), so no checkpoint and the sidecars stay
"""


def _leave_a_hot_wal(package):
    """Put a real, committed-but-uncheckpointed write into `package`.

    A subprocess, because a hot WAL is by definition what a process that
    never closed leaves behind: `os._exit` skips SQLite's own cleanup
    exactly as a `kill -9` does. Plain `sqlite3`, not OGR, so the state is
    deterministic -- OGR's SyncToDisk checkpoints, and whether sidecars
    survive a given write path is a driver detail no test should depend on.
    The write is its own table rather than a row in `picks` only because
    GeoPackage's rtree triggers need spatialite functions that stock
    `sqlite3` does not have; what it stands for is the picks authored in
    the minutes before QGIS was killed.
    """
    import subprocess
    import sys

    subprocess.run([sys.executable, "-c", _LEAVE_A_HOT_WAL, str(package)], check=True)
    assert package.with_name(package.name + "-wal").exists()
    assert package.with_name(package.name + "-shm").exists()


def _wal_only_rows(package):
    con = sqlite3.connect(package)
    try:
        return [row[0] for row in con.execute("SELECT note FROM uncheckpointed")]
    except sqlite3.DatabaseError as exc:
        return f"GONE -- {exc}"
    finally:
        # A clean close checkpoints and removes the sidecars, which is
        # precisely the recovery the refusal below tells the user to do.
        con.close()


def test_a_legacy_package_with_a_hot_journal_is_used_where_it_is_and_adopted_later(
    qgis_app, tmp_path, message_log
):
    """The whole loop, with SiteLayers attached as it always is in production.

    Controller re-review of I5, Important 1. The first version of this
    test drove a bare SiteSession with no SiteLayers, so nothing ever
    created GPKG_FILE and it passed for the wrong reason. In the real
    plugin `site_opened` reaches `SiteLayers.refresh()` -> `ensure_tables()`
    seconds later, which creates an empty `site.nsgeo.gpkg`; from then on
    the "a package by the right name already exists" branch fires forever
    and the legacy package could never be adopted -- so refusing to adopt
    made the loss permanent and the advice we printed impossible to act on.

    What this pins now: the picks are visible on the very first open, no
    competing package is created, the journal is cleared by the ordinary
    clean close, and the next open adopts.
    """
    project = QgsProject.instance()
    project.clear()
    root = tmp_path / "Site1"
    root.mkdir()
    session = SiteSession()
    session.new_site(root)
    layers = SiteLayers(session, project=project)
    session.add_grid(GRID)
    session.save()
    picks = layers.layers["picks"]
    feat = QgsFeature(picks.fields())
    feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    feat.setAttribute("note", "checkpointed pick")
    ok, _ = picks.dataProvider().addFeatures([feat])
    assert ok
    package = session.gpkg_path
    layers.detach()
    session.close_site()
    project.clear()

    legacy = root / "Site1.nsgeo.gpkg"  # a package written before I5 ...
    package.rename(legacy)
    _leave_a_hot_wal(legacy)  # ... whose QGIS was then killed

    # --- first open: used where it is, nothing renamed, nothing created ---
    session2 = SiteSession()
    layers2 = SiteLayers(session2, project=project)
    session2.open_site(root / SURVEY_FILE)

    # The point of the whole branch: the user's pick is on screen now, not
    # after a manual remedy -- opening a database with a hot journal is
    # what SQLite recovery is for. It was renaming it that was unsafe.
    assert session2.gpkg_path == legacy
    assert layers2.feature_count("picks") == 1
    # ... and no empty competing package appeared beside it, which is what
    # would wedge the adoption shut for good.
    assert not (root / GPKG_FILE).exists()
    assert legacy.is_file()
    assert _wal_only_rows(legacy) == ["the last hour of picks"]
    assert any("Site1.nsgeo.gpkg" in m and "-wal" in m for m in message_log), message_log

    # --- an ordinary clean close checkpoints the journal away ---
    layers2.detach()
    session2.close_site()
    project.clear()
    assert not legacy.with_name(legacy.name + "-wal").exists()
    assert not legacy.with_name(legacy.name + "-shm").exists()

    # --- so the next open adopts, with the pick intact ---
    session3 = SiteSession()
    layers3 = SiteLayers(session3, project=project)
    session3.open_site(root / SURVEY_FILE)

    assert session3.gpkg_path == root / GPKG_FILE
    assert not legacy.exists()
    assert layers3.feature_count("picks") == 1
    on_disk = QgsVectorLayer(f"{session3.gpkg_path}|layername=picks", "picks", "ogr")
    assert on_disk.isValid()
    assert [f["note"] for f in on_disk.getFeatures()] == ["checkpointed pick"]
    del on_disk

    layers3.detach()
    project.clear()


def test_discarding_the_site_still_saves_pick_edits_and_the_log_says_why(
    fake_iface, tmp_path, monkeypatch, answer_modal, message_log
):
    """One prompt, two stores -- flagged by the review of I6 vs C4.

    "Save the site before continuing?" is about the survey JSON. Buffered
    layer edits live in the GeoPackage, and `detach()` commits them
    (I6) whichever button was pressed -- so a user who answers Discard
    still gets their picks written. That reads as a contradiction.

    The behaviour is deliberate and unchanged: I6 commits rather than
    discards because an unwanted pick is visible and deletable while a
    discarded one is gone, and `detach()` has no user in it to ask. What
    was missing is that nothing said so. This pins that the log now does.
    """
    import nsgeo_qgis
    from qgis.PyQt.QtWidgets import QFileDialog, QMessageBox

    project = QgsProject.instance()
    project.clear()
    first = tmp_path / "first"
    first.mkdir()
    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(first)
    plugin.session.add_grid(GRID)  # dirty, and enough for the tables to exist
    assert plugin.session.dirty
    package = plugin.session.gpkg_path

    picks = plugin.layers.layers["picks"]
    assert picks.startEditing()
    feat = QgsFeature(picks.fields())
    feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    feat.setAttribute("note", "an hour of depth picks")
    assert picks.addFeature(feat)

    second = tmp_path / "second"
    second.mkdir()
    other = SiteSession()
    other.new_site(second)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *a, **k: (str(second / SURVEY_FILE), "")),
    )
    calls = answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)

    plugin.open_site()

    assert len(calls) == 1  # the site prompt really was answered Discard
    on_disk = QgsVectorLayer(f"{package}|layername=picks", "picks", "ogr")
    assert on_disk.isValid()
    assert [f["note"] for f in on_disk.getFeatures()] == ["an hour of depth picks"]
    del on_disk
    assert any("picks" in m and "save prompt does not cover" in m for m in message_log), message_log

    plugin.unload()
    project.clear()


# ---- picks: the store (M8, spec §4.1, §4.2) --------------------------------


def _a_pick(key="raw/FILE__001.DZT", trace=7, time_ns=12.5, **kw):
    """A fully-populated Pick, so a test that cares about one field does
    not have to spell out the other ten."""
    fields = dict(
        line_key=key,
        trace=trace,
        time_ns=time_ns,
        distance_m=0.117,
        depth_m=0.25,
        velocity_m_ns=0.04,
        stack_json='[{"step": "dewow", "params": {}, "enabled": true}]',
        note="",
        created="2026-09-19T10:00:00+00:00",
    )
    fields.update(kw)
    return Pick(**fields)


def test_the_picks_table_carries_the_two_grouping_fields(populated):
    """Spec §4.2: `feature_id` and `seq` exist from M8 and are written
    null, so a horizon later is an ordered run of existing picks and
    needs no migration of an authored table."""
    session, layers, _ = populated
    names = [f.name() for f in layers.layers["picks"].fields() if f.name() != "fid"]
    assert names[-2:] == ["feature_id", "seq"]


def test_write_pick_stores_every_field_and_places_it_on_the_line(populated):
    session, layers, _ = populated
    layers.write_pick(_a_pick(trace=0))

    assert layers.feature_count("picks") == 1
    feat = next(layers.layers["picks"].getFeatures())
    assert feat["line_key"] == "raw/FILE__001.DZT"
    assert feat["trace"] == 0
    assert feat["time_ns"] == pytest.approx(12.5)
    assert feat["distance_m"] == pytest.approx(0.117)
    assert feat["depth_m"] == pytest.approx(0.25)
    assert feat["velocity_m_ns"] == pytest.approx(0.04)
    assert "dewow" in feat["stack_json"]
    assert feat["created"] == "2026-09-19T10:00:00+00:00"
    assert feat["feature_id"] == NULL
    assert feat["seq"] == NULL
    # Trace 0 of the first line sits at the grid origin, in the package CRS.
    point = feat.geometry().asPoint()
    assert (point.x(), point.y()) == pytest.approx((500.0, 700.0), abs=1e-6)


def test_write_pick_places_a_later_trace_further_along_the_line(populated):
    """The geometry is the trace's own world position, not the line's
    start: a pick's whole value on the map is where along the line it
    is."""
    session, layers, _ = populated
    layers.write_pick(_a_pick(trace=0))
    layers.write_pick(_a_pick(trace=59))

    points = [f.geometry().asPoint() for f in layers.layers["picks"].getFeatures()]
    a, b = sorted(points, key=lambda p: (p.x(), p.y()))
    assert a.distance(b) == pytest.approx(59 / 60, abs=1e-6)


def test_write_pick_refuses_rather_than_dropping_the_pick_when_the_table_is_gone(populated):
    session, layers, _ = populated
    layers.detach()
    with pytest.raises(RuntimeError, match="picks"):
        layers.write_pick(_a_pick())


def test_a_pick_on_an_unplaceable_line_is_stored_without_geometry(populated, tmp_path, message_log):
    """A time-triggered acquisition has no geometry (`trace_coords`
    raises), so the pick cannot be drawn -- but time is the truth and the
    pick is authored data with no other source. It is stored with a null
    geometry and the log says why, rather than being refused."""
    session, layers, _ = populated
    p = synthetic_dzt(tmp_path / "raw", "FILE__004.DZT", n_traces=40, traces_per_metre=0.0)
    session.add_lines([Line.open(p, GridPlacement("A", "y", 1.5, 0.0, 1, p.stem))])

    layers.write_pick(_a_pick(key="raw/FILE__004.DZT", trace=3))

    feat = next(layers.layers["picks"].getFeatures())
    assert feat["line_key"] == "raw/FILE__004.DZT"
    assert feat.geometry().isNull()
    assert any("cannot be placed" in m for m in message_log)


def test_picks_for_returns_only_that_lines_picks_in_trace_order(populated):
    session, layers, _ = populated
    layers.write_pick(_a_pick(trace=40, time_ns=30.0))
    layers.write_pick(_a_pick(trace=5, time_ns=10.0))
    layers.write_pick(_a_pick(key="raw/FILE__002.DZT", trace=9, time_ns=20.0))

    got = layers.picks_for("raw/FILE__001.DZT")

    assert [(p.trace, p.time_ns) for p in got] == [(5, 10.0), (40, 30.0)]
    assert all(p.line_key == "raw/FILE__001.DZT" for p in got)
    assert got[0].feature_id is None
    assert got[0].seq is None
    assert got[0].note == ""


def test_picks_for_is_empty_rather_than_raising_with_no_site_open(populated):
    session, layers, _ = populated
    layers.detach()
    assert layers.picks_for("raw/FILE__001.DZT") == []


def test_picks_for_skips_a_hand_edited_row_with_no_trace_or_time(populated, message_log):
    """The `picks` layer is deliberately editable in QGIS, so a user can
    digitise a point into it with the ordinary tools and leave the
    attributes blank. `float(NULL)` inside a slot would abort the CI
    container; such a row is skipped and named instead."""
    session, layers, _ = populated
    layer = layers.layers["picks"]
    f = QgsFeature(layer.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    f["line_key"] = "raw/FILE__001.DZT"
    assert layer.dataProvider().addFeatures([f])[0]
    layers.write_pick(_a_pick(trace=2, time_ns=8.0))

    got = layers.picks_for("raw/FILE__001.DZT")

    assert [(p.trace, p.time_ns) for p in got] == [(2, 8.0)]
    assert any("no trace or time" in m for m in message_log)


def test_a_package_with_the_pre_m8_picks_schema_migrates_with_its_rows_intact(
    qgis_app, tmp_path, message_log
):
    """The one migration in M8. `picks` is the only table that cannot be
    regenerated, and this project has already had to repair its storage
    twice -- so the rows, their attributes and their geometry must all
    survive the two new columns arriving, with the new columns null.
    """
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    session.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT", n_traces=60)
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0, 0.0, 1, p.stem))])
    session.save()
    package = session.gpkg_path
    layers.detach()
    project.clear()

    # Rewrite `picks` with the pre-M8 field set and put two authored rows
    # in it, exactly as a site created before this milestone would have.
    old_spec = [
        (name, kind) for name, kind in TABLES["picks"][1] if name not in ("feature_id", "seq")
    ]
    old_fields = QgsFields()
    kinds = {
        "str": QMetaType.Type.QString,
        "int": QMetaType.Type.Int,
        "float": QMetaType.Type.Double,
    }
    for name, kind in old_spec:
        old_fields.append(QgsField(name, kinds[kind]))
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.layerName = "picks"
    opts.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
    writer = QgsVectorFileWriter.create(
        str(package),
        old_fields,
        QgsWkbTypes.Type.Point,
        QgsCoordinateReferenceSystem("EPSG:32616"),
        project.transformContext(),
        opts,
    )
    assert writer.hasError() == QgsVectorFileWriter.WriterError.NoError
    del writer
    old = QgsVectorLayer(f"{package}|layername=picks", "picks", "ogr")
    rows = []
    for i, (trace, time_ns) in enumerate([(4, 11.0), (33, 26.5)]):
        f = QgsFeature(old.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0 + i, 700.0 + i)))
        f["line_key"] = "raw/FILE__001.DZT"
        f["trace"] = trace
        f["time_ns"] = time_ns
        f["note"] = f"note {i}"
        rows.append(f)
    assert old.dataProvider().addFeatures(rows)[0]
    del old

    again = SiteSession()
    layers2 = SiteLayers(again, project=project)
    again.open_site(tmp_path / SURVEY_FILE)

    names = [f.name() for f in layers2.layers["picks"].fields() if f.name() != "fid"]
    assert names == [name for name, _ in TABLES["picks"][1]]
    assert layers2.feature_count("picks") == 2
    got = sorted(layers2.layers["picks"].getFeatures(), key=lambda f: f["trace"])
    assert [(f["trace"], f["time_ns"], f["note"]) for f in got] == [
        (4, 11.0, "note 0"),
        (33, 26.5, "note 1"),
    ]
    assert [f["feature_id"] for f in got] == [NULL, NULL]
    assert [f["seq"] for f in got] == [NULL, NULL]
    assert not got[0].geometry().isNull()
    layers2.detach()


def test_the_layers_register_themselves_as_the_sessions_pick_store(populated):
    """Spec §4.1 names `session.add_pick`, but the session holds no
    layers and the parent spec forbids a second OGR handle on a package
    QGIS already has open -- so the write is delegated. The registration
    must happen in the constructor, before any site_opened could fire."""
    session, layers, _ = populated
    assert session.pick_store is layers


# ---- picks: fix round 1 (review findings) ----------------------------------


def test_write_pick_reports_an_unknown_line_key_as_a_runtime_error(populated):
    """`_pick_point` calls `session.line_for_key`, which raises
    `KeyError` for a key that names no line. `write_pick`'s own contract
    is `RuntimeError` on any failure to write; it must not depend on
    `add_pick`'s WORKING-line guard (a later task) to keep that promise.
    """
    session, layers, _ = populated
    with pytest.raises(RuntimeError, match="raw/FILE__999.DZT"):
        layers.write_pick(_a_pick(key="raw/FILE__999.DZT"))


def test_picks_for_reads_a_hand_edited_row_with_blank_optional_fields(populated):
    """`_as_float`/`_as_str`'s NULL branches are otherwise never
    exercised: every pick `_a_pick()` writes has every optional field
    filled in, and the one hand-edited row the sibling test covers is
    discarded by the trace/time gate before any converter runs. A row
    with a trace and a time but a blank `distance_m` and `note` must
    still come back as a `Pick`, not raise -- the trap Fact 3 in the
    brief names: `float(NULL)` raises, and `value is not None` would not
    have caught it."""
    session, layers, _ = populated
    layer = layers.layers["picks"]
    f = QgsFeature(layer.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    f["line_key"] = "raw/FILE__001.DZT"
    f["trace"] = 12
    f["time_ns"] = 15.0
    assert layer.dataProvider().addFeatures([f])[0]

    got = layers.picks_for("raw/FILE__001.DZT")

    assert len(got) == 1
    assert got[0].distance_m is None
    assert got[0].note == ""


def test_picks_for_survives_a_failed_rebuild_leaving_pre_m8_fields_missing(
    qgis_app, tmp_path, monkeypatch, message_log
):
    """`_ensure_table` routes a schema-mismatched `picks` table through
    `_rebuild_picks`; if that raises -- any of the five ways its own
    docstring names it can (an invalid temp layer, a provider
    `addFeatures` failure, the row-count gate, a bad transform, a locked
    rename) -- `ensure_tables` catches it, Critical-logs it, and
    *continues* (layers.py's per-table containment). The loop right
    after opens the still-pre-M8 table straight into
    `self.layers["picks"]`, with no `feature_id`/`seq` fields at all.
    `picks_for` must not then raise `KeyError` reading them -- proven
    here by making the rebuild actually fail, not merely asserted from
    the guard's presence.
    """
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    session.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT", n_traces=60)
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0, 0.0, 1, p.stem))])
    session.save()
    package = session.gpkg_path
    layers.detach()
    project.clear()

    # Rewrite `picks` with the pre-M8 field set and one authored row,
    # exactly as the migration test does.
    old_spec = [
        (name, kind) for name, kind in TABLES["picks"][1] if name not in ("feature_id", "seq")
    ]
    old_fields = QgsFields()
    kinds = {
        "str": QMetaType.Type.QString,
        "int": QMetaType.Type.Int,
        "float": QMetaType.Type.Double,
    }
    for name, kind in old_spec:
        old_fields.append(QgsField(name, kinds[kind]))
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.layerName = "picks"
    opts.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
    writer = QgsVectorFileWriter.create(
        str(package),
        old_fields,
        QgsWkbTypes.Type.Point,
        QgsCoordinateReferenceSystem("EPSG:32616"),
        project.transformContext(),
        opts,
    )
    assert writer.hasError() == QgsVectorFileWriter.WriterError.NoError
    del writer
    old = QgsVectorLayer(f"{package}|layername=picks", "picks", "ogr")
    f = QgsFeature(old.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    f["line_key"] = "raw/FILE__001.DZT"
    f["trace"] = 4
    f["time_ns"] = 11.0
    assert old.dataProvider().addFeatures([f])[0]
    del old

    # Force the migration to fail; ensure_tables catches it, logs
    # Critical, and moves on -- the disk table stays pre-M8.
    monkeypatch.setattr(
        SiteLayers,
        "_rebuild_picks",
        lambda self, *a, **kw: (_ for _ in ()).throw(RuntimeError("simulated rebuild failure")),
    )

    again = SiteSession()
    layers2 = SiteLayers(again, project=project)
    again.open_site(tmp_path / SURVEY_FILE)

    assert any("could not prepare table 'picks'" in m for m in message_log)
    names = [f.name() for f in layers2.layers["picks"].fields() if f.name() != "fid"]
    assert "feature_id" not in names  # proves the rebuild really did not run

    got = layers2.picks_for("raw/FILE__001.DZT")

    assert [(p.trace, p.time_ns) for p in got] == [(4, 11.0)]
    assert got[0].feature_id is None
    assert got[0].seq is None
    layers2.detach()


def test_write_pick_refuses_when_the_picks_layer_predates_a_grid_crs_change(populated, monkeypatch):
    """`_ensure_table`'s own docstring names this exact scenario: a
    grid's CRS changing (`replace_grid`) means every table should be
    rebuilt, but if `_rebuild_picks` fails, `ensure_tables` logs
    Critical and moves on *without* reloading the already-open `picks`
    layer -- so it keeps declaring its old CRS while `self.crs()` (the
    package CRS, taken from the first grid) now returns the new one.
    `_pick_point` computes a point in the new CRS via the same
    `_line_points` -> `_points` path `_refill` already guards for the
    derived tables; `picks` needs the identical guard, not a milder one,
    because unlike them it is never regenerated on the next refresh.
    """
    session, layers, _ = populated
    monkeypatch.setattr(
        SiteLayers,
        "_rebuild_picks",
        lambda self, *a, **kw: (_ for _ in ()).throw(RuntimeError("simulated rebuild failure")),
    )

    session.replace_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32615", 0.5))

    assert layers.layers["picks"].crs().authid() == "EPSG:32616"
    assert layers.crs().authid() == "EPSG:32615"
    with pytest.raises(RuntimeError, match="picks"):
        layers.write_pick(_a_pick())
    assert layers.feature_count("picks") == 0  # refused, not written
