### Task 2: W1, the "Show slice band" checkbox

**Files:** `profile_dock.py` (toolbar); tests in `test_plugin_profile_dock.py`.

**What changes:**
- `slice_band_button` becomes a `QCheckBox("Show slice band")`, placed right after `colormap_combo`, before the Difference label.
- Keep the attribute name, the `QSettings` key, the greyed rule and its tooltips, and the `toggled` wiring.
- The `_FitButton`/1:1 group is untouched.

**Tests:**
- Existing band tests pass unchanged.
- New: `isinstance(dock.slice_band_button, QCheckBox)` and its text is `"Show slice band"`.
- New: it sits left of `fit_button` (`x` order) and is not in the Fit group.
- The toolbar-width test (any-font form) stays green.

