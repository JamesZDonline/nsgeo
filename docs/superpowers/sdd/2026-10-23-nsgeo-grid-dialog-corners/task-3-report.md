# Task 3 report: Fill from a polygon

Status: DONE. Commit: see `git log` (subject per brief), pushed.

Implemented: polygon row in GridDialog (divider label, layer_combo, feature_picker, pick_polygon_button, fill_button), signal pick_polygon_requested, fill_from_polygon, set_polygon_feature, chosen_polygon. Fill reads asMultiPolygon()[0][0] / asPolygon()[0], transforms layer CRS -> corners_crs (project transform context) before writing anything, uses (lon*cos(mean lat), lat) for roles/compass when geographic, maps indices back to true points, writes via set_corner with `v{i} {compass}`. Errors go straight to fit_status (not _fit_line). Never fits. Deleted corners_from_polygon, PolygonCorners and all 4 pure tests that used them (the brief's "four" tests were spread over 4 functions). Added pick_polygon_requested to KNOWN_UNCONSUMED. Recovered _select_sole_feature (R9).

Tests: 12 new qgis tests (brief's 8 + multi/unsupported cases: transform failure leaves rows alone, set_polygon_feature/chosen_polygon, pick button emit, a 245-degree-vertex cos(phi) test). RED: 11 of 13 selected failed (missing layer_combo/fill_from_polygon/pick_polygon_requested). GREEN: grid file 59 passed. Mutation: forcing scale=1.0 makes the 245-degree test fail (the brief's compass test alone does not discriminate the rule, so I added that one).
Full qgis tier 939 passed (927+12). Core+pure 748 passed, 3 skipped (-4 from deletions... net 752-4). ruff check/format clean; mypy clean.
Excepthook/unraisablehook check (temporary plugin, uncommitted): grid file 59 passed, nothing fired.

Concerns: compass centre is the mean of the four vertices (spec says centroid; identical for a parallelogram). Fill on set_corner emits corners_changed four times.
