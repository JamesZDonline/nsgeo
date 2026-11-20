### Task 2: The gain strip widget (#49, #8, #9)

Spec §4.1–§4.4 (the strip's half). It is all in `GainStrip`, plus one relay signal and one
docstring in `ProfileDock`.

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/gain_strip.py` (`_db_range`, `mouseMoveEvent`,
  `mouseDoubleClickEvent`, `handle_at`, `paintEvent`, new button, the module docstring)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (relay signal in `__init__`;
  `show_gain_strip`'s docstring, #25 item 3)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py` (strip-level, on the `strip`
  fixture: transform `fit(100, 200, 0.0, 0.5, 600, 300)`, so the record is 0–100 ns)

**Interfaces:**
- Produces:
  - `gain_strip.DB_LIMIT = 120.0`;
  - `GainStrip.reset_requested = pyqtSignal()` and `GainStrip.reset_button: QToolButton`;
  - `GainStrip.caption_texts() -> tuple[str, str | None, str]`, the (low, "dB" or None, high)
    the paint draws;
  - `ProfileDock.gain_reset_requested = pyqtSignal()`, relayed from the strip.
- The record's extent is read from the strip's own transform: `transform.t0_ns` to
  `transform.t_end`. No new setter.

- [ ] **Step 1: Write the failing tests:**
  - `test_db_limit_matches_the_core`: `DB_LIMIT` equals both bounds of `gain_curve`'s `points`
    schema (`get_step("gain_curve").schema()`, min −120 and max 120).
  - `test_the_range_never_passes_the_limit`:
    - `set_points([[0, 0], [50, 118]])`: `_db_range()[1] == 120.0`;
    - `[[0, 0], [50, -118]]`: `_db_range()[0] == -120.0`.
  - `test_a_drag_to_the_edge_stops_at_120_db`:
    - the issue's repro: points `[[0, 0], [50, 118]]`;
    - drag handle 1 well past the right edge;
    - the emitted point's dB is exactly 120.0, and `strip.points()[1][1] == 120.0`.
  - `test_a_double_click_at_the_edge_adds_at_most_120`: points `[[0, 0], [50, 118]]`. A
    double-click (`plugin_testing.send_double_click`) in empty strip at the right edge adds a point
    of exactly 120.0 dB. Today the range's high end is 124, so it adds 124.
  - `test_a_point_before_the_record_is_pinned_and_reachable`:
    - `set_points([[-11.0, 0.0], [50.0, 12.0], [100.0, 0.0]], "o")`;
    - `handle_at` at `(x_of_db(0.0), y_of_time(0.0))` is 0;
    - a press there, a move to `y_of_time(20.0)` and a release leave point 0 at time ≈ 20 (within
      one pixel's time).
  - `test_a_pinned_point_can_be_right_clicked_away`: same points; a right-click at the pinned
    handle leaves 2 points, with the −11 point gone.
  - `test_a_point_after_the_record_is_pinned_to_the_bottom`: `[[0, 0], [50, 6], [130, 0]]`;
    `handle_at` at `(x_of_db(0.0), y_of_time(100.0))` is 2.
  - Review Focus 5, `test_a_point_outside_a_zoomed_window_is_not_pinned`:
    - `set_time_mapping(t.with_window(0, 100, 20.0, 60.0), MARGIN_TOP)`, points `[[0, 0], [40, 6],
      [80, 0]]`;
    - `handle_at` at the window's bottom edge with point 2's dB x finds nothing.
  - `test_the_caption_fits_at_the_test_font` and `..._at_a_large_font` (`strip.setFont` with point
    size 16):
    - the low and high texts are always present and whole;
    - their `QFontMetrics.horizontalAdvance` widths, plus the middle text's when it is not None,
      fit in `strip.width() - 4`;
    - at the large font, with points at ±120, the middle is None.
  - `test_reset_emits_reset_requested`: `reset_button.click()` emits once;
    `reset_button.isVisible()` while the strip is shown with a transform.
  - `test_profile_dock_relays_reset`: on a `ProfileDock`, clicking `gain_strip.reset_button`
    emits `gain_reset_requested` once.
- [ ] **Step 2: Run them.** Expected: FAIL (an import of `DB_LIMIT`; `_db_range` gives 124; the
  edge handle is not found; the caption doesn't fit).
- [ ] **Step 3: Implement it** in `gain_strip.py`.
  - **`_db_range` and the writes:** `_db_range` caps at ±`DB_LIMIT` (spec §4.1). The frozen range
    during a drag is unchanged. `mouseMoveEvent` and `mouseDoubleClickEvent` clamp the dB they
    write to ±`DB_LIMIT`.
  - **Pinned points:** one private helper gives each point its drawn position. A point earlier
    than `transform.t0_ns` sits at `y_of_time(t0_ns)`, a point later than `transform.t_end` at
    `y_of_time(t_end)`, each at its own dB x.
    - `handle_at` and the handle painting use the helper. The polyline still uses the true
      positions (spec §4.2).
    - An off-record handle draws as a triangle (▲ at the top edge, ▼ at the bottom), with the
      same pen and fill as a round handle.
  - **The caption:** `caption_texts()` picks the texts with `QFontMetrics(self.font())` (spec
    §4.3). `paintEvent` draws the low text left-aligned from x = 2, the high text right-aligned
    to `width() - 2` and the middle text centred, all in the caption row (y 0–14).
  - **Reset:**
    - `self.reset_button = QToolButton(self)` with text `"Reset"`, tooltip `"Reset the gain curve
      to a flat 0 dB"`, emitting `reset_requested`;
    - laid out, in `resizeEvent` and `set_time_mapping`, centred in the band from `self._top +
      transform.height` to `self.height()`;
    - hidden when there is no transform, or when that band is shorter than the button's
      `sizeHint().height()`.
  - Add a fifth paragraph to the module docstring for the limit and the pinned handles.
- [ ] **Step 4: Relay and docstring** in `profile_dock.py`.
  - `gain_reset_requested = pyqtSignal()`, connected next to the `points_changed` relay.
  - Correct `show_gain_strip`'s sentence about a `None` owner (spec §5, #25 item 3). A `None`
    owner with real points ends a gesture only when the strip shows a real owner, and callers
    always pass a real token. Leave the signature as it is.
- [ ] **Step 5: Run the strip tests and the four whole files.** Expected: PASS. The existing
  `test_drag_overshoot_is_clamped_and_the_range_does_not_ratchet` still holds (its range is −6 to
  26).
- [ ] **Step 6: Commit** `fix(gain-strip): stop at ±120 dB, reach off-record points, fit the caption, add Reset (#49, #8, #9)`.

