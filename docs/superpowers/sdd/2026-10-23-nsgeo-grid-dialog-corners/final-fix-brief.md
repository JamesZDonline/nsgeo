# Final review fix wave — grid dialog (21e0b5c..bd668a1)

The final whole-branch review (opus) said "Ready to merge: with fixes". This is the complete list to fix in ONE wave. Exact messages and constants below are the controller's rulings; use them verbatim. Probe scripts the reviewer used (read-only, they show the reproductions): /tmp/claude-1000/-home-jameszd-Documents-Github-archaeo-geophysics/6ba2127d-204a-4280-854f-09059451e8b4/scratchpad/probes/probe1.py, probe2.py, probe3.py (run with `PYTHONPATH=packages/nsgeo-core/src:packages/nsgeo-qgis`).

## F1 (Important) — degrees typed as metres fit perfectly ("RMS 0.000", OK enabled)

Reviewer: Project in UTM 16N, "Corners in" left on 32616, the four site corners typed as lon/lat → Fit gives `rigid fit RMS 0.000 m from 4 corners`, origin (−86.798, 36.151) in EPSG:32616, OK enabled whenever sizes count as typed (an existing grid's always do) → OK would move the grid ~4000 km. Same from Fill with a layer that has no CRS (a transform from an invalid CRS is identity). Location: grid_dialog.py:820-842 (Fit) and :751-757 (Fill).

Ruling R15:
- Add a named module constant `MIN_MEASURED_SIZE = 0.1` (metres). In Fit, after `corner_frame` succeeds, if any measured size (size_x or size_y that is not None) is below it, refuse with exactly:
  `f"the corners are only {d:.4f} m apart in {authid}: check that Corners in is the CRS they were measured in"`
  where `d` is the smallest measured size and `authid` is the Corners-in CRS's authid. Nothing changes (see F4 for the CRS).
- In `_fill_from_polygon`, refuse a layer whose CRS is not valid with exactly:
  `f"{layer.name()} has no CRS: set one in its Layer Properties"`
  (rows unchanged; written to the status label per R6).
- Tests: (a) the reviewer's case — Corners in UTM16, SITE corners typed as lon/lat numbers, Fit → refused with the message, origin/azimuth/sizes unchanged; (b) the same while editing an existing grid (sizes typed) → refused, `result_grid()` equals the original grid; (c) Fill from a memory polygon layer with an invalid CRS → refused with the message, rows unchanged.

## F2 (Important) — a row whose text did not parse is dropped from Fit silently

Reviewer: type the origin with comma decimals ("518204,112") and the other three rows correctly; the "not a number" message shows, the next good edit replaces it (R6), and Fit reports `rigid fit RMS 0.000 m from 3 corners` while the origin cells still show the user's numbers. Location: grid_dialog.py:847-853.

Ruling R16: generalise `_half_filled_row` so Fit refuses when any row has text in either coordinate cell but no parsed point. Messages (first such row in role order):
- one cell empty, the other filled (existing): `f"{role} has only one coordinate: fill both or clear it"`
- any cell holding text that does not parse: `f"{role}: {text!r} is not a number: fix it or clear the row"`
Test: comma-decimal origin + three good rows → Fit refuses with the second message, origin unchanged.

## F3 (Minor, user docs) — guide inaccuracies in docs/guide/getting-started.md

- :140 "To choose it yourself, set the project's CRS first" → say to pick it in the grid window's CRS box, and that the site's existing grids' CRS comes before the project's.
- :168 "and then to a vertex" → "or, failing that, to a vertex".
- :173 do not bold **Layer** / **Feature** (those controls have no labels) — describe them as the layer list and the feature list.
- :178 Rotate: it moves the roles one corner round however the rows were filled, and the two Size boxes swap with them.
- :188 a large RMS no longer can mean "two of the rows are swapped" (with three or more corners every swap is refused); say it means the corners aren't quite square and to look at "off by" for which corner.
Check every other sentence of Step 2 against the code while you are there.

## F4 (Minor) — a refused Fit still switches an automatic grid CRS; `_apply_auto_crs` discards the conversion error

Ruling R17: if Fit refuses for any reason after the automatic CRS was switched in that same Fit, undo the switch — restore the previous grid CRS, origin, azimuth and anchor exactly as they were — so a refused Fit changes nothing. And `_apply_auto_crs` must not discard `_convert_grid`'s error: record it as `_crs_message` (shown in the CRS hint). Also clear a stale `_crs_message` from an earlier failed hand pick when the automatic CRS is successfully applied. Tests: mirrored corners near lon −70 in an automatic UTM16 dialog → Fit refuses and the grid CRS is still EPSG:32616 with origin/azimuth unchanged; a stale hand-pick failure message is cleared by a later successful automatic switch.

## F5 (Minor) — `_project_reason` has no "outside" branch

`grid_dialog.py:1061-1070`: when `_usable_at` returns "outside", the hint reads "is off by 0.0% here". Add a branch: `f"picked for you: the project CRS ({authid}) does not reach this location"`. Test it if constructible (say so if not).

## F6 (Minor) — metres typed under lon/lat

`_lonlat` should return None when |lat| > 90 or |lon| > 180 (not a geographic position), so Fit with metres typed while Corners in is EPSG:4326 refuses with exactly `f"these are not longitudes and latitudes: check that Corners in is the CRS they were measured in"` instead of "set a metric CRS" plus "no UTM zone covers this latitude", and the automatic CRS is not flipped. Test with SITE_CORNERS' UTM numbers typed under Corners in = WGS84.

## F7 (Minor) — misleading "picked for you: the CRS the site's other grids use"

Show that note only when the site's CRS differs from the project's CRS. Test: site grid in EPSG:32616, project EPSG:32616 → no note.

## F8 (Minor) — stale comments and one-liners

- grid_dialog.py:152-155 says a non-metric hand edit "drops" the anchor; R11 re-derives only the edited part.
- `_convert_grid` docstring (:1124-1125) "100 m along +Y" → the chord rule (100 source units, or 0.001° in a geographic CRS).
- lookup.py `_signed_area`: centre on `world.mean(axis=0)` before the shoelace sum (rounding noise at UTM magnitudes); comment why. The existing pure tests must still pass; add a pure test with three exactly collinear points at UTM magnitudes (e.g. northing ~4e6) → "lie in a line".

## F9 (Minor) — test hygiene

- Vacuous steps that retype identical text (no itemChanged): test_plugin_grid_dialog.py:~1500 and ~2302 — type a value that differs so the step really edits, and assert what R6/R14 say happens.
- The "ok" case of `test_overlay_leaves_nothing_behind` never unloads its plugin — unload it the file's usual way (`answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard); plugin.unload()`).
- Remove the unused `LOCAL` constant.

## Not in this wave (ruled; do not change)

Double-click in Pick all, overlay message recorded-when-written, nsgeo's own layers taking part in picks, dialog activation after a pick, snapping index latency, overlay colours, Rotate on a non-square grid — these go to the walkthrough or to issues.
