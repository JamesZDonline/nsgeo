"""M16 B Task 2: the `features` table and pick membership, on a real package."""

from __future__ import annotations

import sqlite3

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.cut import CUT_KEY_PREFIX
from nsgeo.model.survey import Line
from nsgeo.slices import SurfaceSettings
from nsgeo_qgis.layers import FEATURES, TABLES, SiteLayers
from nsgeo_qgis.session import Pick, SiteSession
from nsgeo_qgis.surfaces import Surfaces
from plugin_testing import synthetic_dzt
from qgis.core import (
    NULL,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
)

GRID_A = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)
GRID_B = Grid("B", (600.0, 700.0), 0.0, 5.0, 11.0, "EPSG:32616", 0.5)
KEYS_A = ["raw/FILE__001.DZT", "raw/FILE__002.DZT", "raw/FILE__003.DZT"]
KEY_B = "raw/FILE__004.DZT"


def _pick(key: str, trace: int, time_ns: float = 20.0) -> Pick:
    return Pick(
        line_key=key,
        trace=trace,
        time_ns=time_ns,
        distance_m=None,
        depth_m=None,
        velocity_m_ns=None,
        stack_json="",
        note="",
        created="2026-11-13T00:00:00+00:00",
    )


@pytest.fixture
def site(qgis_app, tmp_path):
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    session.add_grid(GRID_A)
    session.add_grid(GRID_B)
    lines = []
    for i in range(3):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", i * 0.5, 0.0, 1, p.stem)))
    p = synthetic_dzt(tmp_path / "raw", "FILE__004.DZT", n_traces=60)
    lines.append(Line.open(p, GridPlacement("B", "y", 0.0, 0.0, 1, p.stem)))
    session.add_lines(lines)
    surfaces = Surfaces(session, layers)
    yield session, layers, surfaces, tmp_path
    layers.detach()
    project.clear()


def _fids(layers: SiteLayers) -> list[int]:
    return sorted(f.id() for f in layers.layers["picks"].dataProvider().getFeatures())


def _bowl_picks(layers: SiteLayers, n: int = 6) -> list[int]:
    """`n` picks over the three lines of grid A, spread so they span an area."""
    before = set(_fids(layers))
    for i in range(n):
        layers.write_pick(_pick(KEYS_A[i % 3], 5 + 8 * i))
    return sorted(set(_fids(layers)) - before)


def _times(layers: SiteLayers) -> list[float]:
    return sorted(f["time_ns"] for f in layers.layers["picks"].dataProvider().getFeatures())


def _feature_ids(layers: SiteLayers) -> dict[int, str | None]:
    out = {}
    for f in layers.layers["picks"].dataProvider().getFeatures():
        out[f.id()] = None if f["feature_id"] == NULL else f["feature_id"]
    return out


def test_the_features_table_is_created_once_and_survives_a_crs_change(site):
    session, layers, surfaces, _ = site
    path = str(session.gpkg_path)
    disk = QgsVectorLayer(f"{path}|layername={FEATURES}", FEATURES, "ogr")
    assert disk.isValid()
    assert [f.name() for f in disk.fields() if f.name() != "fid"] == [
        "feature_id",
        "name",
        "grid_id",
        "kind",
        "settings_json",
        "created",
    ]
    assert FEATURES not in TABLES and FEATURES not in layers.layers
    assert all(lyr.name() != FEATURES for lyr in QgsProject.instance().mapLayers().values())
    fids = _bowl_picks(layers)
    record = surfaces.create("Bowl", fids)
    row_fid = layers._feature_fid(record.feature_id)
    session.replace_grid(Grid("A", (-86.8, 36.4), 12.0, 0.001, 0.001, "EPSG:4326", 0.5))
    assert [r.name for r in surfaces.records()] == ["Bowl"]
    assert layers._feature_fid(record.feature_id) == row_fid
    assert len(surfaces.members(record.feature_id)) == len(fids)
    assert FEATURES not in layers.layers


def test_a_package_without_the_features_table_gains_it_with_picks_intact(site):
    session, layers, surfaces, tmp_path = site
    fids = _bowl_picks(layers)
    layers.detach()
    with sqlite3.connect(session.gpkg_path) as db:
        db.execute(f"DROP TABLE {FEATURES}")
        db.execute("DELETE FROM gpkg_contents WHERE table_name = ?", (FEATURES,))
        db.execute("DELETE FROM gpkg_ogr_contents WHERE table_name = ?", (FEATURES,))
        db.commit()
    layers.refresh()
    assert layers._features_layer() is not None
    assert surfaces.records() == []
    assert _fids(layers) == fids
    assert layers.feature_count("picks") == len(fids)


def test_create_sets_feature_id_on_exactly_the_selected_picks(site):
    _, layers, surfaces, _ = site
    fids = _bowl_picks(layers, 8)
    chosen = fids[:6]
    record = surfaces.create("  Bowl  ", chosen, SurfaceSettings(join="idw"))
    assert record.name == "Bowl" and record.grid_id == "A" and record.kind == "surface"
    assert surfaces.records() == [record]
    assert surfaces.records()[0].settings.join == "idw"
    owners = _feature_ids(layers)
    assert {f for f, o in owners.items() if o == record.feature_id} == set(chosen)
    assert all(owners[f] is None for f in fids[6:])
    assert all(f["seq"] == NULL for f in layers.layers["picks"].dataProvider().getFeatures())
    assert sorted(r.fid for r in surfaces.members(record.feature_id)) == sorted(chosen)


def test_picks_already_in_a_surface_move_and_the_check_says_so(site):
    _, layers, surfaces, _ = site
    fids = _bowl_picks(layers, 8)
    bowl = surfaces.create("Bowl", fids[:6])
    found = surfaces.check(fids[2:8])
    assert found.refusal == "" and found.moving == {"Bowl": 4} and found.n == 6
    assert found.left == {"Bowl": 2}
    other = surfaces.create("Higher", fids[2:8])
    owners = _feature_ids(layers)
    assert {f for f, o in owners.items() if o == other.feature_id} == set(fids[2:8])
    assert {f for f, o in owners.items() if o == bowl.feature_id} == set(fids[:2])
    assert surfaces.check(fids[2:8], into=other.feature_id).moving == {}


def test_delete_clears_membership_and_keeps_every_pick(site):
    _, layers, surfaces, _ = site
    fids = _bowl_picks(layers, 7)
    times = _times(layers)
    record = surfaces.create("Bowl", fids)
    surfaces.delete(record.feature_id)
    assert surfaces.records() == []
    assert _fids(layers) == fids and _times(layers) == times
    assert set(_feature_ids(layers).values()) == {None}


def test_picks_from_two_grids_are_refused(site):
    _, layers, surfaces, _ = site
    fids = _bowl_picks(layers, 4)
    layers.write_pick(_pick(KEY_B, 10))
    mixed = [*fids, max(_fids(layers))]
    found = surfaces.check(mixed)
    assert "Grid A and Grid B" in found.refusal
    with pytest.raises(ValueError, match="one grid"):
        surfaces.create("Mixed", mixed)
    assert surfaces.records() == []
    assert set(_feature_ids(layers).values()) == {None}


def test_fewer_than_three_or_collinear_picks_are_refused(site):
    _, layers, surfaces, _ = site
    for i in range(5):
        layers.write_pick(_pick(KEYS_A[0], 5 + 10 * i))  # one line: collinear
    layers.write_pick(_pick(KEYS_A[1], 5))
    layers.write_pick(_pick(KEYS_A[2], 30))
    fids = _fids(layers)
    two = surfaces.check(fids[:2])
    assert "at least 3" in two.refusal and "(2 selected)" in two.refusal
    line = surfaces.check(fids[:5])
    assert "straight line" in line.refusal
    assert surfaces.check(fids[3:7]).refusal == ""
    with pytest.raises(ValueError, match="straight line"):
        surfaces.create("Line", fids[:5])
    assert surfaces.check([]).refusal.startswith("Select picks")


def test_picks_on_a_cut_are_refused(site):
    _, layers, surfaces, _ = site
    fids = _bowl_picks(layers, 4)
    cut = QgsFeature(layers.layers["picks"].fields())
    cut.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(501.0, 701.0)))
    cut["line_key"] = CUT_KEY_PREFIX + "c1"
    cut["trace"] = 1
    cut["time_ns"] = 10.0
    assert layers.layers["picks"].dataProvider().addFeatures([cut])[0]
    on_cut = max(_fids(layers))
    found = surfaces.check([*fids, on_cut])
    assert found.refusal.startswith("1 of these picks is on a cut")
    with pytest.raises(ValueError, match="on a cut"):
        surfaces.create("Cut", [*fids, on_cut])


def test_a_pick_with_no_line_or_no_position_is_refused_plainly(site):
    _, layers, surfaces, _ = site
    fids = _bowl_picks(layers, 4)
    stray = QgsFeature(layers.layers["picks"].fields())
    stray["line_key"] = "raw/GONE.DZT"
    stray["trace"] = 1
    stray["time_ns"] = 10.0
    assert layers.layers["picks"].dataProvider().addFeatures([stray])[0]
    found = surfaces.check([*fids, max(_fids(layers))])
    assert "not on a line of a grid" in found.refusal


def test_unsaved_picks_are_refused_until_saved(site):
    _, layers, surfaces, _ = site
    fids = _bowl_picks(layers, 5)
    picks = layers.layers["picks"]
    assert picks.startEditing()
    try:
        extra = QgsFeature(picks.fields())
        extra.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.2, 700.1)))
        extra["line_key"] = KEYS_A[1]
        extra["trace"] = 12
        extra["time_ns"] = 30.0
        assert picks.addFeature(extra)
        picks.selectByIds([*fids[:4], extra.id()])
        chosen = layers.selected_pick_ids()
        assert len(chosen) == 5 and min(chosen) < 0
        found = surfaces.check(chosen)
        assert (
            found.refusal
            == "Save the picks layer's edits first; 1 of these picks is not saved yet."
        )
        with pytest.raises(ValueError, match="Save the picks layer"):
            surfaces.create("Bowl", chosen)
        assert surfaces.records() == []
        assert picks.commitChanges()
    except BaseException:
        picks.rollBack()
        raise
    saved = [f for f in _fids(layers) if f not in fids]
    assert len(saved) == 1
    assert surfaces.check([*fids[:4], saved[0]]).refusal == ""


def test_removing_below_three_picks_is_refused(site):
    _, layers, surfaces, _ = site
    fids = _bowl_picks(layers, 5)
    record = surfaces.create("Bowl", fids)
    surfaces.remove_picks(record.feature_id, fids[:2])
    assert sorted(r.fid for r in surfaces.members(record.feature_id)) == fids[2:]
    with pytest.raises(ValueError, match="at least 3"):
        surfaces.remove_picks(record.feature_id, fids[2:3])
    assert len(surfaces.members(record.feature_id)) == 3
    surfaces.add_picks(record.feature_id, fids[:1])
    assert len(surfaces.members(record.feature_id)) == 4


def test_names_are_unique_trimmed_and_never_used_in_paths(site):
    session, layers, surfaces, _ = site
    fids = _bowl_picks(layers, 8)
    name = 'Bowl "north" / é'
    record = surfaces.create(f"  {name}  ", fids[:4])
    assert surfaces.records()[0].name == name
    with pytest.raises(ValueError, match="already exists"):
        surfaces.create(name.upper() + " ", fids[4:])
    second = surfaces.create("Other", fids[4:])
    with pytest.raises(ValueError, match="already exists"):
        surfaces.rename(second.feature_id, " " + name.lower())
    surfaces.rename(record.feature_id, name)  # its own name is fine
    surfaces.rename(second.feature_id, "x" * 80)
    with pytest.raises(ValueError, match="80"):
        surfaces.rename(second.feature_id, "x" * 81)
    # Files are named by feature id: no path under the site holds any of it.
    root = session.gpkg_path.parent
    for path in root.rglob("*"):
        parts = path.relative_to(root).parts
        assert not any("Bowl" in part or "north" in part for part in parts), path


def test_a_feature_and_its_picks_survive_closing_without_save(site):
    session, layers, surfaces, tmp_path = site
    fids = _bowl_picks(layers, 6)
    session.save()
    record = surfaces.create("Bowl", fids)
    surfaces.rename(record.feature_id, "Basin")
    surfaces.set_settings(record.feature_id, SurfaceSettings(window_m=0.05))
    assert session.dirty is False
    layers.detach()
    again = SiteSession()
    layers2 = SiteLayers(again, project=QgsProject.instance())
    try:
        again.open_site(tmp_path / "survey.nsgeo.json")
        reopened = Surfaces(again, layers2)
        (got,) = reopened.records()
        assert got.name == "Basin" and got.feature_id == record.feature_id
        assert got.settings.window_m == 0.05
        assert sorted(r.fid for r in reopened.members(got.feature_id)) == fids
    finally:
        layers2.detach()


def test_features_changed_follows_each_write(site):
    session, layers, surfaces, _ = site
    seen: list[tuple[str, int]] = []
    session.features_changed.connect(lambda: seen.append(("changed", len(surfaces.records()))))
    fids = _bowl_picks(layers, 6)
    record = surfaces.create("Bowl", fids)
    surfaces.rename(record.feature_id, "Basin")
    surfaces.set_settings(record.feature_id, SurfaceSettings(strength=0.5))
    surfaces.remove_picks(record.feature_id, fids[:1])
    surfaces.add_picks(record.feature_id, fids[:1])
    surfaces.delete(record.feature_id)
    # The signal fires after the write: the first create already shows its row,
    # the delete already shows none.
    assert seen == [("changed", 1)] * 5 + [("changed", 0)]
    with pytest.raises(ValueError):
        surfaces.create("", fids)
    assert len(seen) == 6  # a refused change emits nothing


def _blank_row(layers: SiteLayers, **extra) -> int:
    """A saved row with no trace or time, as a hand-digitised point leaves it."""
    row = QgsFeature(layers.layers["picks"].fields())
    row.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.3, 700.2)))
    row["line_key"] = KEYS_A[0]
    for name, value in extra.items():
        row[name] = value
    assert layers.layers["picks"].dataProvider().addFeatures([row])[0]
    return max(_fids(layers))


def test_a_saved_pick_with_blank_attributes_is_named_as_such_not_as_unsaved(site):
    _, layers, surfaces, _ = site
    fids = _bowl_picks(layers, 4)
    blank = _blank_row(layers)
    found = surfaces.check([*fids, blank])
    assert found.refusal == (
        "1 of these picks has no trace or time; edit or delete it in the picks layer."
    )
    assert "Save" not in found.refusal
    with pytest.raises(ValueError, match="no trace or time"):
        surfaces.create("Bowl", [*fids, blank])
    assert surfaces.check(fids).refusal == ""


def test_checking_a_blank_row_writes_no_log_line(site):
    from plugin_testing import connect_message_log

    _, layers, surfaces, _ = site
    fids = _bowl_picks(layers, 4)
    blank = _blank_row(layers)
    seen: list[str] = []
    disconnect = connect_message_log(lambda msg, tag, level: seen.append(msg))
    try:
        surfaces.check([*fids, blank])
        surfaces.members("nothing")
    finally:
        disconnect()
    assert not [m for m in seen if "no trace or time" in m]


def test_delete_clears_a_member_whose_time_was_blanked_after_it_joined(site):
    _, layers, surfaces, _ = site
    fids = _bowl_picks(layers, 5)
    record = surfaces.create("Bowl", fids)
    picks = layers.layers["picks"].dataProvider()
    assert picks.changeAttributeValues({fids[0]: {picks.fieldNameIndex("time_ns"): NULL}})
    assert len(surfaces.members(record.feature_id)) == 4  # the blank one reads as absent
    surfaces.delete(record.feature_id)
    assert set(_feature_ids(layers).values()) == {None}


def test_moving_every_pick_of_a_surface_says_it_is_left_too_small(site):
    from nsgeo_qgis.surface_plan import move_note

    _, layers, surfaces, _ = site
    fids = _bowl_picks(layers, 6)
    surfaces.create("Bowl", fids)
    found = surfaces.check(fids)
    assert found.refusal == "" and found.moving == {"Bowl": 6} and found.left == {"Bowl": 0}
    note = move_note(found.moving, found.n, found.left)
    assert "“Bowl” is left with 0 picks, too few to rebuild" in note
    surfaces.create("Higher", fids)  # allowed
    assert surfaces.members(surfaces.records()[0].feature_id) == []


def test_picks_with_pending_edits_in_the_layer_are_unsaved(site):
    _, layers, surfaces, _ = site
    fids = _bowl_picks(layers, 5)
    picks = layers.layers["picks"]
    assert picks.startEditing()
    try:
        assert picks.changeAttributeValue(fids[0], picks.fields().indexOf("note"), "edited")
        found = surfaces.check(fids)
        assert found.refusal == (
            "Save the picks layer's edits first; 1 of these picks is not saved yet."
        )
        assert surfaces.check(fids[1:]).refusal == ""
        assert picks.changeGeometry(fids[1], QgsGeometry.fromPointXY(QgsPointXY(1, 1)))
        assert "2 of these picks are not saved yet" in surfaces.check(fids).refusal
        picks.deleteFeature(fids[2])
        assert "3 of these picks are not saved yet" in surfaces.check(fids).refusal
        assert picks.commitChanges()
    except BaseException:
        picks.rollBack()
        raise


def test_a_duplicate_fid_is_not_unsaved_and_re_adding_members_changes_nothing(site):
    session, layers, surfaces, _ = site
    fids = _bowl_picks(layers, 5)
    assert surfaces.check([*fids, fids[0]]).refusal == ""
    record = surfaces.create("Bowl", fids)
    seen: list[int] = []
    session.features_changed.connect(lambda: seen.append(1))
    surfaces.add_picks(record.feature_id, fids[:2])
    assert seen == []


def test_an_older_features_table_gains_missing_fields_and_reads_correctly(site):
    session, layers, surfaces, _ = site
    fids = _bowl_picks(layers, 6)
    record = surfaces.create("Bowl", fids, SurfaceSettings(join="idw"))
    layers.detach()
    with sqlite3.connect(session.gpkg_path) as db:
        db.execute(f"ALTER TABLE {FEATURES} DROP COLUMN created")
        db.execute(f"ALTER TABLE {FEATURES} DROP COLUMN kind")
        db.commit()
    layers.refresh()
    disk = QgsVectorLayer(f"{session.gpkg_path}|layername={FEATURES}", FEATURES, "ogr")
    names = {f.name() for f in disk.fields()}
    assert {"created", "kind"} <= names
    (got,) = surfaces.records() if surfaces.records() else [None]
    assert got is not None
    assert got.name == "Bowl" and got.feature_id == record.feature_id
    assert got.settings.join == "idw" and got.kind == "surface"  # a missing kind reads as surface
    surfaces.rename(record.feature_id, "Basin")
    assert surfaces.records()[0].name == "Basin"
    assert len(surfaces.members(record.feature_id)) == 6


@pytest.fixture
def grouped_transactions(site):
    """The picks layer in editing mode under the project's automatic transaction groups, the
    state in which a write to the package lands inside the user's open transaction."""
    from qgis.core import Qgis

    project = QgsProject.instance()
    _, layers, surfaces, _ = site
    fids = _bowl_picks(layers, 5)
    record = surfaces.create("Bowl", fids)
    project.setTransactionMode(Qgis.TransactionMode.AutomaticGroups)
    picks = layers.layers["picks"]
    assert picks.startEditing()
    try:
        yield layers, surfaces, record, fids
    finally:
        picks.rollBack()
        project.setTransactionMode(Qgis.TransactionMode.Disabled)


def test_membership_writes_are_refused_inside_the_users_transaction(grouped_transactions):
    layers, surfaces, record, fids = grouped_transactions
    assert layers.picks_in_open_transaction()
    held = sorted(r.fid for r in surfaces.members(record.feature_id))
    with pytest.raises(ValueError, match="editing mode"):
        surfaces.create("Other", fids[:3])
    with pytest.raises(ValueError, match="editing mode"):
        surfaces.add_picks(record.feature_id, fids[:1])
    with pytest.raises(ValueError, match="editing mode"):
        surfaces.remove_picks(record.feature_id, fids[:1])
    with pytest.raises(ValueError, match="editing mode"):
        surfaces.delete(record.feature_id)
    assert sorted(r.fid for r in surfaces.members(record.feature_id)) == held
    assert [r.name for r in surfaces.records()] == ["Bowl"]


def test_editing_mode_alone_or_grouping_alone_is_no_hazard(site):
    from qgis.core import Qgis

    _, layers, surfaces, _ = site
    fids = _bowl_picks(layers, 5)
    record = surfaces.create("Bowl", fids)
    project = QgsProject.instance()
    picks = layers.layers["picks"]
    assert not layers.picks_in_open_transaction()
    project.setTransactionMode(Qgis.TransactionMode.AutomaticGroups)
    try:
        assert not layers.picks_in_open_transaction()  # grouping on, not editing
    finally:
        project.setTransactionMode(Qgis.TransactionMode.Disabled)
    assert picks.startEditing()
    try:
        assert not layers.picks_in_open_transaction()  # editing, no grouping
    finally:
        picks.rollBack()
    assert surfaces.remove_picks(record.feature_id, fids[:1]) == 1
