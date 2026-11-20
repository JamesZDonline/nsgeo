# Final fix report (Plan A, session F)

All findings fixed. Pre-commit runs: five QGIS files 397 passed; real_data 54 passed; pure 421 passed, 4 skipped; ruff check clean; ruff format clean (302 files). The release-docs pure test (which pins guide text) is in the pure run and passes.

## I1 (b908f70)
- Change: profile_dock.py builds the Fit menu, then sets each action as default in turn, takes the widest sizeHint width and sets it as fit_button minimum width, ending on Fit.
- Tests: new test_picking_a_fit_does_not_move_the_buttons_after_it; worst-case toolbar test now triggers fit_height first and replaces the vacuous text() assert with `QLabel.text(velocity_label) == full or toolTip() == full`; stale docstring of test_fit_button_restores_the_full_extent_after_a_zoom fixed.
- RED (`qgis_tests.sh .../test_plugin_profile_dock.py -q -k does_not_move_the_buttons`): `assert (97, 579, 625) == (48, 530, 576)`. GREEN: passes after the fix. (The reworked worst-case test passes before and after: the label assert is a guard that can now fail.)
- Toolbar minimum width measured 684 -> 740 px (offscreen font); test bound tightened 690 -> 740, docstring updated.

## I2 (b036c03)
- Change: set_axes assigns self._distance before the ruler block and computes the bounds as `sorted(float(self.trace_units_at_metres(m)) for m in (ruler.lo_m, ruler.hi_m))` inside the errstate; the non-finite/degenerate check is kept; ViewTransform.fit gets those bounds. bounds_on only converted the two ends and sorted them (ui/ruler.py), so no extra logic was lost; its import is dropped from profile_view.py (the function stays in ruler.py).
- Test: test_the_metre_helpers_decide_the_outputs_not_just_the_calls patches the pair to scale metres by 2 and checks trace_bounds, tick labels (on the unpatched window) and window_m follow.
- RED (current code): `assert (-59.5.., 300.5..) == approx((90.5.., 270.5..))` on trace_bounds. GREEN: passes.

## m1 (commit "a same-line take-down then render keeps the radar window")
- Change: _set_axes_holding records `_clock_carried` when the clock rule fires; _take_down_picture sets `_axes_from_header = not self._clock_carried`.
- Test: test_a_same_line_take_down_then_render_keeps_the_radar_window (the probe's sequence).
- RED: `assert (47.7478.., 57.7478..) == approx((45.84.., 55.84..))`. GREEN: passes; the unloaded-line-samples test stays green (full dock file 157 passed).

## Guards (in 9884a90)
Three view tests: strip press in velocity mode (menu requested, no velocity point, no box), right-click in the image in velocity mode (discards a point, no menu), strip press in pick mode (menu, no pick). They passed on the unchanged code, as expected: guards, no production change.

## m2 (9884a90)
- Change: readout_text returns "" when self._image is None.
- Test: test_the_readout_is_empty_while_there_is_no_image. RED: `assert '1.67 m along (trace 100) ... 0.80 m deep' == ''`. GREEN: passes. The existing read-out tests had no image; they now use a new `_imaged` helper (or set_image).

## m5 (9884a90)
profile_view.py module docstring now mentions per-axis units, the strip-press menu and the read-out.

## m3 (commit "a flat stretch gets its own greyed 1:1 tooltip")
- Change: TRUE_SCALE_FLAT_TIP in profile_dock.py; new ProfileView.true_scale_window_is_flat(); _sync_true_scale_button picks among the three tips.
- Test: the flat-run test asserts the new tip. RED was an AttributeError (the constant did not exist) rather than an assertion mismatch; GREEN passes.

## R14 (commit "docs(guide)")
docs/guide/getting-started.md paragraph rewritten for Fit menu, true-scale 1:1, Slice band, axis units, read-out. No headings added.

## Files changed
packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py, profile_view.py; tests/qgis/test_plugin_profile_dock.py, test_plugin_profile_view.py; docs/guide/getting-started.md.

## Concerns
- Minimum toolbar width is now 740 px (+56) because Fit holds its widest label, as the finding specified; fine at 1361.
- Unchanged signatures: carry_time_window, _set_axes_holding, _axes_zero, the helper pair.
