from __future__ import annotations

from pathlib import Path

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.io.dzx import read_dzx
from nsgeo.model.survey import Line
from nsgeo_qgis.layers import DERIVED, TABLES, SiteLayers
from nsgeo_qgis.lookup import ImportOptions, plan_import, rows_to_lines
from nsgeo_qgis.session import SiteSession
from plugin_testing import REAL_DZT, needs_real_data, synthetic_dzt
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QMetaType

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
