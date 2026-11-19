### Task 4: Tidy-ups in `import_dialog.py` (#16, #17)

**Files:**
- Create: `numbers.py` (`parse_decimal`)
- Modify: `ui/import_dialog.py` (`_updating`, `_following`, the Offset cell's parse)
- Modify: `ui/param_form.py` (the float branch of `_parse_number` calls `parse_decimal`;
  messages unchanged)
- Test: `packages/nsgeo-qgis/tests/pure/test_pure_numbers.py` (new),
  `packages/nsgeo-qgis/tests/qgis/test_plugin_import_dialog.py`,
  `packages/nsgeo-qgis/tests/qgis/test_plugin_param_form.py`

**Interfaces:**
- Produces: `parse_decimal(text: str) -> float` in `nsgeo_qgis/numbers.py` (no Qt import, so the
  pure tier can test it): `float(text.strip())`; `ValueError` for a comma anywhere, for anything
  `float` refuses, and for NaN or an infinity. Callers word their own messages.

- [ ] **Step 1: Write the failing tests:**
  - pure: `test_parse_decimal_reads_a_point_and_refuses_a_comma_nan_and_inf`
    (`"1.5"` → 1.5, `" 2 "` → 2.0; `"1,000"`, `"1,5"`, `"nan"`, `"inf"`, `"-inf"`, `""` raise).
  - qgis: `test_an_offset_typed_with_a_comma_is_refused_like_paramform`: typing `"1,000"` into the
    Offset cell leaves the offset unchanged and the status reads `"'1,000' is not a number;
    offset unchanged"`; `"nan"` the same.
  - qgis: `test_paramform_and_the_import_dialog_refuse_the_same_inputs`: for each of
    `["1,000", "1,5", "nan", "inf"]`, ParamForm's float field reports an error and the Offset cell
    is refused.
  - qgis: `test_a_reentrant_refresh_does_not_clear_the_guard_early`: from inside
    `_refresh_table`'s guarded block (patch a call it makes to run `_refresh_table` again), an
    `itemChanged` delivered after the inner call returns is still ignored; same shape for
    `_follow_spacing` / `_first_offset_changed`.
- [ ] **Step 2: Run; fail.**
- [ ] **Step 3: Implement `parse_decimal`; switch both callers; make `_updating` and
  `_following` depth counters.**
- [ ] **Step 4: Run the touched files and core+pure; all pass. Check `test_plugin_param_form.py`
  still passes unchanged.**
- [ ] **Step 5: Commit and push.**
  `git commit -m "fix(import): one rule for decimal input; guards as depth counters (#17, #16)"`

---

## After the tasks

- [ ] Whole-branch review (most capable model), then the local recipe and CI (3.44 and 4.2)
  green on the last pushed commit.
- [ ] Deploy to its own QGIS profile (`ns_geo_bulk`) and publish the walkthrough Artifact (db
  collection `checks`), covering spec §10: DZT import with a preset into a grid with lines; the
  first import into an empty grid with the Slices panel on it; GPS import with a preset; a
  rectangle selection on the map, trimmed in the panel, removed with Delete (the prompt names
  what goes, No is the default with fits); a preset, the open line's steps, a velocity and a
  cleared velocity on a selection, the selection staying through each. Wait for the author.
- [ ] PR body: closes #129 #16 #17 #57 #221, and #58 (presets and velocity; placement was #137);
  lists the set/clear flags left for other sessions' files (spec §6); notes the overlaps for
  M19a, H and G (spec §8). Merging asks first.
- [ ] README roadmap: session D's In progress entry updated at each stage (straight to main).
