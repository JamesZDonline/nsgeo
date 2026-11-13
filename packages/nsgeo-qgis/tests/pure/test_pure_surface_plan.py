from __future__ import annotations

import numpy as np
from nsgeo.slices import SurfaceSettings
from nsgeo_qgis.surface_plan import (
    INPUTS,
    KIND_SURFACE,
    STALE_REASONS,
    FeatureRecord,
    built_message,
    clean_name,
    delete_question,
    empty_message,
    fit_rows,
    mesh_2dm,
    mesh_dat,
    move_note,
    name_refusal,
    outlier_line,
    rebuild_refusal,
    remove_refusal,
    selection_refusal,
    stale_text,
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


def test_unreadable_picks_have_their_own_wording_and_come_after_unsaved():
    base = {"n": 5, "unsaved": 0, "on_cuts": 0, "grids": {"A"}, "spans_area": True}
    assert selection_refusal(**base, unreadable=1) == (
        "1 of these picks has no trace or time; edit or delete it in the picks layer."
    )
    assert "3 of these picks have no trace or time" in selection_refusal(**base, unreadable=3)
    assert selection_refusal(**{**base, "unsaved": 1}, unreadable=2).startswith("Save")
    assert "cut" not in selection_refusal(**{**base, "on_cuts": 2}, unreadable=1)


def test_move_note_says_when_a_surface_is_left_too_small():
    note = move_note({"Bowl": 4, "Ditch": 2}, 6, {"Bowl": 0, "Ditch": 5})
    assert note.endswith("“Bowl” is left with 0 picks, too few to rebuild.")
    assert "Ditch” is left" not in note
    assert "too few" not in move_note({"Bowl": 4}, 30, {"Bowl": 3})
    assert "left with 1 pick," in move_note({"Bowl": 4}, 30, {"Bowl": 1})


def test_stale_text_names_every_reason():
    assert set(STALE_REASONS) == {*INPUTS, "unavailable"}
    assert stale_text(n for n in ["picks", "fill"]).count("changed") == 2  # a generator is fine
    assert STALE_REASONS["picks"] == "its picks changed"
    assert STALE_REASONS["resolution"] == "the grid's 3-D cell or depth step changed"
    assert stale_text(()) == ""
    for name in INPUTS:
        assert STALE_REASONS[name] in stale_text([name])
    one = stale_text(["picks"])
    assert one.startswith("Stale: its picks changed since it was built.")
    assert "last build" in one
    # panel order, "and" before the last
    both = stale_text(["resolution", "picks"])
    assert "its picks changed and the grid's 3-D cell or depth step changed" in both


REPORT = {
    "fit": {
        "picks": 88,
        "within_2cm": 82,
        "within_5cm": 3,
        "further": 0,
        "at_edge": 0,
        "on_holes": 3,
    },
    "offset_m": 0.036,
    "offset_votes": 85,
    "offset_at_limit": 2,
    "offset_reliable": True,
    "cells": 5214,
    "region_cells": 6038,
    "resolution": {"cell": 0.05, "dz_ns": 0.1},
    "built_utc": "2026-11-13T10:42:07+00:00",
}


def test_fit_rows_match_the_mockup():
    rows = fit_rows(REPORT)
    assert [k for k, _ in rows] == ["Picks", "Offset", "Cover", "Built"]
    assert dict(rows) == {
        "Picks": "82 of 88 within 2 cm · 3 within 5 cm · 3 on holes",
        "Offset": "your picks sit 3.6 cm above the strongest swing",
        "Cover": "5,214 of 6,038 cells (86%); the rest are holes",
        "Built": "2026-11-13 10:42 UTC at 0.05 m, 0.1 ns",
    }


def test_fit_rows_show_edge_picks_and_say_when_the_offset_is_unreliable():
    report = {
        **REPORT,
        "fit": {**REPORT["fit"], "at_edge": 4, "further": 2},
        "offset_m": -0.02,
        "offset_at_limit": 60,
        "offset_reliable": False,
    }
    rows = dict(fit_rows(report))
    assert "4 at the window's edge" in rows["Picks"] and "2 further away" in rows["Picks"]
    assert "2.0 cm below the strongest swing" in rows["Offset"]
    assert "5 cm search limit" in rows["Offset"] and "check the picks" in rows["Offset"]
    assert "no pick had a swing" in dict(fit_rows({**REPORT, "offset_votes": 0}))["Offset"]
    assert dict(fit_rows({**REPORT, "cells": 36, "region_cells": 36}))["Cover"] == (
        "all 36 cells; no holes"
    )
    assert "no cell" in dict(fit_rows({**REPORT, "cells": 0, "region_cells": 0}))["Cover"]


def test_outlier_lines_and_the_messages():
    hole = {
        "line_key": "a/FILE__023.DZT",
        "label": "FILE__023",
        "distance_m": 4.15,
        "picked_m": 0.62,
        "surface_m": None,
        "reason": "hole",
    }
    far = {
        "line_key": "k",
        "label": "FILE__027",
        "distance_m": 1.35,
        "picked_m": 0.58,
        "surface_m": 0.55,
        "reason": "far",
    }
    assert outlier_line(hole) == "FILE__023 at 4.15 m · picked 0.62 m · on a hole"
    assert outlier_line(far) == "FILE__027 at 1.35 m · picked 0.58 m · surface 0.55 m (3.0 cm)"
    edge = {**far, "reason": "edge", "distance_m": None}
    assert outlier_line(edge).endswith("held at the window's edge")
    assert outlier_line(edge).startswith("FILE__027 · picked")
    assert built_message("Bowl", REPORT) == (
        "Built “Bowl”: 82 of 88 picks within 2 cm, 3 on holes. "
        "Your picks sit 3.6 cm above the strongest swing."
    )
    assert "“Bowl”" in empty_message("Bowl") and "strength" in empty_message("Bowl")
    assert rebuild_refusal("Bowl", 3) == ""
    assert "too few to rebuild" in rebuild_refusal("Bowl", 2)


def test_the_mesh_files():
    xy = np.array([[100.0, 200.0], [101.0, 200.0], [100.0, 201.0]])
    text = mesh_2dm(xy, np.array([-0.5, -0.6, -0.55]), np.array([[0, 1, 2]]))
    assert text.splitlines() == [
        "MESH2D",
        "ND 1 100.0000 200.0000 -0.50000",
        "ND 2 101.0000 200.0000 -0.60000",
        "ND 3 100.0000 201.0000 -0.55000",
        "E3T 1 1 2 3 1",
    ]
    dat = mesh_dat(np.array([0.5, 0.6, 0.55]), 1).splitlines()
    assert (
        dat[0] == "DATASET"
        and dat[-1] == "ENDDS"
        and dat[7:-1] == ["0.50000", "0.60000", "0.55000"]
    )
    assert mesh_2dm(np.empty((0, 2)), np.empty(0), np.empty((0, 3), dtype=int)) == "MESH2D\n"


def test_the_dialog_and_panel_wording():
    from nsgeo_qgis.surface_plan import (
        build_outcome,
        fit_short,
        selection_label,
        settings_summary,
        skipped_surfaces_text,
        state_text,
        write_failure_text,
    )

    assert selection_label(0, None, []) == "No picks selected."
    assert selection_label(1, "1", ["F__001"]) == "1 pick selected, on Grid 1 (line F__001)."
    assert selection_label(88, "1", ["F__020", "F__033", "F__025"]) == (
        "88 picks selected, all on Grid 1 (lines F__020 to F__033)."
    )
    assert selection_label(5, None, []) == "5 picks selected."
    assert settings_summary(SurfaceSettings()) == (
        "smooth join · window ±2 cm · strength 1.0 × typical · no smoothing"
    )
    assert settings_summary(SurfaceSettings(join="idw", window_m=0.035, smoothing_m=0.5)) == (
        "inverse-distance join · window ±3.5 cm · strength 1.0 × typical · smoothing 0.50 m"
    )
    assert state_text(False, ()) == "not built"
    assert state_text(True, ()) == ""
    assert state_text(True, ("picks",)) == "stale"
    assert fit_short(None) == ""
    assert fit_short({"fit": {"within_2cm": 80, "picks": 84}}) == "80/84"
    assert "database is locked" not in write_failure_text("could not write: database is locked")
    assert "Save the picks layer" in write_failure_text("could not write: database is locked")
    assert write_failure_text("disk full") == "disk full"
    assert skipped_surfaces_text([]) == ""
    assert "“Bowl”" in skipped_surfaces_text(["Bowl"]) and "left out" in skipped_surfaces_text(
        ["Bowl"]
    )
    good = {"fit": {"picks": 4, "within_2cm": 4, "on_holes": 0}, "offset_votes": 4, "cells": 9}
    text, warn = build_outcome("Bowl", good)
    assert text.startswith("Built “Bowl”") and not warn
    assert build_outcome("Bowl", {**good, "cells": 0}) == (empty_message("Bowl"), True)
    assert build_outcome("Bowl", {**good, "offset_reliable": False})[1]
    assert build_outcome("Bowl", {**good, "skipped": [{"why": "x"}]})[1]
    assert build_outcome("Bowl", {**good, "fit": {**good["fit"], "at_edge": 1}})[1]


def test_the_panel_build_and_dialog_wording_round_two():
    from nsgeo_qgis.surface_plan import (
        build_failure_text,
        build_title,
        not_built_text,
        outlier_header,
        resolution_hint,
    )

    assert not_built_text(1) == "Not built yet (1 pick). Rebuild to put it on the map."
    assert not_built_text(4).startswith("Not built yet (4 picks)")
    assert outlier_header(0.02, 0) == "More than 2 cm from the surface (0)"
    assert outlier_header(0.02, 6).endswith("(6); click one to select it on the map:")
    assert build_title(["Bowl"]) == "Building “Bowl”"
    assert build_title(["A", "B", "C"]) == "Building 3 surfaces"
    assert resolution_hint("1", 0.05, 0.1) == (
        "Built at Grid 1's 3-D resolution (0.05 m, 0.1 ns), the one its ParaView export uses."
    )
    assert resolution_hint(None).startswith("Built at the grid's 3-D resolution")
    assert build_failure_text(["A", "B"], OSError("No space left")) == (
        "Could not build “A” and “B”: No space left"
    )
    assert build_failure_text(["A"], ValueError("too few")) == "too few"
