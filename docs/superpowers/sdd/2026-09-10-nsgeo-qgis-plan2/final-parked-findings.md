# Parked findings for the whole-branch review

Every item below was found during a task review, judged real, and deliberately deferred to this
review rather than fixed in its own task. They are grouped by area. For each: say whether it
still stands against the final code, and if so how severe it actually is now that the branch is
complete. Several may have been fixed incidentally by later tasks -- check, do not assume.

## A -- nsgeo-core

1. Task 13 nice_ticks polish: `np.round` magnitude safety (M1), infinite bounds (M2), uncapped
   target (M3), untested epsilon (M4), untested reversed-range guard (M5), docstring wording
   (M8). Judged unreachable with the values Task 14 actually passes (target is always 6; time
   bounds are always finite because time_hi = t0 + n_samples*dt). Confirm that is still true.

## B -- plugin, non-UI

2. `SiteSession.close_site` tears down `_site` BEFORE emitting `line_opened("")`, so every
   `line_opened` slot that reads the session during a close sees a closed site. `ProfileDock._open`
   is the first such slot; Plan 3 will add more. An ordering decision in the session, not a dock
   bug -- it wants deciding once rather than worked around in each new subscriber.
3. `plugin.py`'s module docstring asks that "every slot below that does real work" carry a broad
   try/except + `message()` guard. `_sync_gain_strip`, `_resync_gain_strip` and `_on_gain_points`
   do not. Pre-existing for two of the three. The right fix is a sweep against the stated policy,
   not three point patches -- and the policy itself may need restating if it is not being followed.
4. Task 12's four parked minors, including: `loading_changed` has no consumer; and a
   `_loading` dict that gets `[(key, True)]` with no closing `(key, False)`.

## C -- plugin UI

5. `ui/import_dialog.py:122,356,399,402` still uses the set/clear boolean `_updating` shape that
   was replaced with a depth counter in `processing_dock.py` (and later in `param_form.py`) --
   the same latent reentrancy hazard. Worth a sweep for the pattern rather than a point fix.
6. `ui/import_dialog.py:418` still does `float(item.text().replace(",", "."))` -- the exact
   conversion removed from `ParamForm` on the grounds that "1,000" is ambiguous and silently
   becomes 1.0. The plugin now has TWO conventions for the same user input.
7. `processing_dock.py` is ~480+ lines carrying list management, the parameter form, drag/drop,
   apply-to-grid, the difference toggle and presets. Each block has a banner comment and nothing
   is wrong today; flagged as the file to watch. Say whether it has crossed the line.
8. Task 14 m6: the profile view's QRect right/bottom axis line sits 1px inside.
9. Task 13/14 minors: guard-ordering error quality; "pin which quantities the guard checks";
   two contract-details-only-in-comments minors.
10. INFORMATIONAL, not a defect -- recorded so it is not misread as a regression: the identity
    guard costs one extra transient form rebuild on `move_selected` (the post-move rebuild emits
    `step_selected` for the source index, where a different step now sits, before the trailing
    `setCurrentRow` rebuilds for the moved one). End state identical.
11. INFORMATIONAL: each mid-drag `replace_step` makes a new step object, so `_show_form`'s
    identity guard misses and rebuilds the parameter form at mouse-move rate. Harmless for
    `gain_curve` (one static label); would discard uncommitted text for a future step with a
    curve PLUS numeric fields. No such step exists.

## D -- tests

12. A bare "something changed" selection-render probe.
13. A dt_ns test pinning only `== 0`.
14. A distance-tick probe hard-coding Qt truncation with no +/-1 window.
15. `ProfileDock._clear` does not reset `_difference_index` while `_open` does; the fix was
    applied but deliberately NOT tested, on the stated grounds that it has no reachable-today
    precondition (mirroring the file's own `_refresh_velocity` precedent). Judge whether that
    reasoning holds.
16. The plugin package has no mypy coverage: CI scopes mypy to `nsgeo-core/src/nsgeo` plus
    exactly `lookup.py` and `ui/view_transform.py`, because the venv has no QGIS stubs. Every
    other plugin module is unchecked. This is the single largest coverage gap on the branch.
