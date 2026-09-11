from __future__ import annotations

from pathlib import Path

import nsgeo_qgis.layers as layers_module
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.io.dzx import read_dzx
from nsgeo.model.survey import Line
from nsgeo_qgis.layers import _PICKS_BACKUP, _PICKS_REBUILD, DERIVED, TABLES, SiteLayers
from nsgeo_qgis.lookup import ImportOptions, plan_import, rows_to_lines
from nsgeo_qgis.session import SiteSession
from plugin_testing import REAL_DZT, needs_real_data, synthetic_dzt
from qgis.core import (
    QgsApplication,
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
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QMetaType, Qt

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


@pytest.fixture
def message_log(qgis_app):
    """Captured `QgsMessageLog` messages, for the life of this test only.

    `QgsApplication.messageLog()` is a session-scoped singleton: a
    connection left dangling would keep accumulating every later test's
    messages into this test's own list for the rest of the (also
    session-scoped) `qgis_app` fixture. Disconnected on teardown.
    """
    log = QgsApplication.messageLog()
    messages: list[str] = []

    def _on_message(msg: str, tag: str, level: int) -> None:
        messages.append(msg)

    log.messageReceived.connect(_on_message)
    yield messages
    log.messageReceived.disconnect(_on_message)


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

    # A grid's outline colour matches the colour of its own lines: both
    # `_style_grids()` and `_style_lines()` index GRID_COLOURS by the
    # grid's position in `site.grids`, not by its id.
    lines_renderer = layers.layers["lines"].renderer()
    line_cats = list(lines_renderer.categories())
    lines_colours = {str(cat.value()): cat.symbol().color().name() for cat in line_cats}
    for grid_id, symbol in by_grid.items():
        assert symbol.symbolLayer(0).strokeColor().name() == lines_colours[grid_id]


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
