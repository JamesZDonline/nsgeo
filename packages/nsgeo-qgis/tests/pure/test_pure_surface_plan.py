from __future__ import annotations

from nsgeo.slices import SurfaceSettings
from nsgeo_qgis.surface_plan import (
    KIND_SURFACE,
    FeatureRecord,
    clean_name,
    delete_question,
    move_note,
    name_refusal,
    remove_refusal,
    selection_refusal,
)


def test_record_round_trips_and_bad_settings_read_as_defaults():
    rec = FeatureRecord(
        "abc",
        "Bowl",
        "A",
        KIND_SURFACE,
        SurfaceSettings(join="idw", window_m=0.05, strength=0.5, smoothing_m=0.1),
        "2026-11-13T10:00:00+00:00",
    )
    row = rec.to_row()
    assert set(row) == {"feature_id", "name", "grid_id", "kind", "settings_json", "created"}
    assert FeatureRecord.from_row(row) == rec
    for bad in ("", "not json", "[1, 2]", "null", None):
        got = FeatureRecord.from_row({**row, "settings_json": bad})
        assert got.settings == SurfaceSettings()
        assert got.name == "Bowl"


def test_names_are_trimmed_and_unique_case_folded():
    assert clean_name("  Bowl   north \t") == "Bowl north"
    assert name_refusal("  Bowl  ", []) == ""
    assert name_refusal("bowl", ["Bowl"])  # taken, whatever the case
    assert name_refusal(" BOWL ", ["Bowl", "Ditch"])
    assert name_refusal("Bowl", ["Bowl"], own="Bowl") == ""  # renaming to its own name
    assert name_refusal("bowl", ["Bowl"], own="Bowl") == ""  # or its own, re-cased
    assert name_refusal("Ditch", ["Bowl", "Ditch"], own="Bowl")  # someone else's
    assert name_refusal("", [])
    assert name_refusal("   ", [])
    assert name_refusal("x" * 80, []) == ""
    assert "80" in name_refusal("x" * 81, [])


def test_selection_refusals_come_in_order():
    ok = {"n": 5, "unsaved": 0, "on_cuts": 0, "grids": {"A"}, "spans_area": True}
    assert selection_refusal(**ok) == ""
    everything = {"n": 2, "unsaved": 2, "on_cuts": 5, "grids": {"A", "B"}, "spans_area": False}
    assert selection_refusal(**{**everything, "n": 0}).startswith("Select picks")
    assert selection_refusal(**everything) == (
        "Save the picks layer's edits first; 2 of these picks are not saved yet."
    )
    everything["unsaved"] = 0
    assert selection_refusal(**everything) == (
        "5 of these picks are on a cut. Picks on cuts can join surfaces in a later version."
    )
    everything["on_cuts"] = 0
    assert selection_refusal(**everything) == (
        "These picks are on Grid A and Grid B. "
        "A surface comes from one grid; select picks on one grid only."
    )
    everything["grids"] = {"A"}
    assert selection_refusal(**everything) == (
        "A surface needs at least 3 picks that are not in a straight line (2 selected)."
    )
    assert "straight line" in selection_refusal(**{**ok, "spans_area": False})
    assert "straight line" in selection_refusal(**{**ok, "n": 2})
    # a pick that cannot be placed comes before the grids check
    assert "not on a line of a grid" in selection_refusal(**{**everything, "no_grid": 1})
    # adding to a surface needs no area of its own
    assert selection_refusal(**{**ok, "n": 1, "spans_area": True, "minimum": 1}) == ""


def test_move_note_names_each_surface_once():
    assert move_note({"Bowl": 4}, 30) == (
        "4 of them are in “Bowl”; they will move to this surface, and “Bowl” will need a rebuild."
    )
    two = move_note({"Bowl": 4, "Ditch": 2}, 30)
    assert two.count("“Bowl”") == 2 and two.count("“Ditch”") == 2
    assert "4 of them are in “Bowl”" in two and "2 in “Ditch”" in two
    assert move_note({}, 30) == ""
    assert move_note({"Bowl": 0}, 30) == ""


def test_remove_and_delete_wording():
    assert remove_refusal(3) == ""
    assert remove_refusal(2) and "2" in remove_refusal(2)
    q = delete_question("Bowl", 88)
    assert q.startswith("Delete “Bowl”? Its 88 picks stay")
