### Task 6: GPS lines in the Survey panel, destagger and profiles (plugin + guide)

**Files:**
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/session.py`: `is_gps_line`, `set_travel_shift`;
  - `ui/survey_dock.py`: the row text, the menus and `destagger_requested`;
  - `plugin.py`: the destagger dialog;
  - `docs/guide/getting-started.md`: a new step after Step 3, *Import GPS lines*;
  - `packages/nsgeo-qgis/README.md`: one line naming the feature.
- Test: `tests/qgis/test_plugin_survey_dock.py`, `test_plugin_session.py` and `test_plugin_profile_dock.py` gain the tests below.

**Interfaces:**
- Consumes: Task 2's `TrackPlacement` and Task 4's `synthetic_gps_dzt`.
- Produces:

```python
# session.py
def is_gps_line(self, key: str) -> bool: ...          # isinstance(placement, TrackPlacement)
def set_travel_shift(self, keys: Iterable[str], metres: float) -> None: ...
# All or nothing: KeyError for an unknown key; ValueError(f"{name} is not a GPS line") for a tape line; ValueError for a non-finite value.
# One dirty mark and one lines_changed; a no-op when nothing would change.

# survey_dock.py
destagger_requested = pyqtSignal(list)                 # GPS line keys
```

- **The guide step** says:
  - what a DZG is;
  - that lines are placed along the walk with no grid;
  - what `Without RTK` and the `rtk_gaps` layer mean;
  - that the destagger can be measured later (M17c);
  - that a tape-placed line is switched by removing it and importing it again.

  It has no screenshots from real data.

- [ ] **Step 1: Write the failing tests.**
  - `test_plugin_session.py`:
    - `test_set_travel_shift_is_one_change`;
    - `test_set_travel_shift_refuses_a_tape_line_and_changes_nothing`;
    - `test_a_pick_on_a_gps_line_follows_its_destagger`: after `set_travel_shift(…, 0.5)`, the pick's map point moves 0.5 m along the track.
  - `test_plugin_survey_dock.py`:
    - `test_a_gps_line_row_reads_gps_length_and_gaps`: for a synthetic line with a 1.8 m bridge and a 29.8 m walk, the text is exactly `"… · GPS · 29.8 m · 1.8 m without RTK"`.
    - `test_a_destaggered_gps_line_row_names_it` (`" · destagger +0.24 m"`).
    - `test_a_gps_line_menu_offers_destagger_not_edit_or_move`.
    - `test_a_gps_only_selection_offers_destagger_for_all`.
    - `test_a_mixed_selection_offers_only_removal`.
    - `test_set_destagger_starts_at_the_shared_value_and_applies_to_all`: drive the dialog with a monkeypatched `QInputDialog.getDouble`, then check the message.
  - `test_plugin_profile_dock.py`:
    - `test_a_gps_line_opens_with_walked_distance_and_no_ruler`: the bottom axis runs from `travel_shift` to walked length plus `travel_shift`, and `_ruler_for` is None.
    - `test_the_velocity_fit_on_a_gps_line_uses_the_wheel_spacing` (P14).
- [ ] **Step 2: Run them and see each fail.**
- [ ] **Step 3: Implement** to P13/P14 and the Copy.
- [ ] **Step 4: Run core + pure, the three QGIS files, lint and types.** Then the coordinator runs the full QGIS tier.
- [ ] **Step 5: Commit** (`feat(plugin): GPS lines in the Survey panel, Set destagger…, guide (#134)`) and push.

---

### Checkpoint C2 (coordinator): build and walkthrough

- [ ] Deploy to a **new** QGIS profile, `ns_geo_gps` (a copy of `ns_geo`, symlinked to this worktree, via `dev_link.py --profile ns_geo_gps`). Check that it loads headless.
- [ ] Publish a walkthrough Artifact with a `db` collection, `checks`. The author runs it on their own copy of the real data:
  - **G1** Import all 60 lines of the first survey into a new site with no grid. Every line is drawn along its walk. The zigzag's turn-arounds are visible, and the coordinates note says which CRS was picked.
  - **G2** `FILE__011` is drawn at about 30 m, where the wheel says 26 m.
  - **G3** `FILE__016` and `FILE__028` stretch across their obstacle lifts, at the user marks.
  - **G4** Import the second survey's `FILE__039` and `FILE__042`. The messages name their stretches without RTK, and `rtk_gaps` draws them.
  - **G5** Open a GPS line. Its profile reads in distance walked. Hover follows the map, and a pick sits on the track.
  - **G6** Set destagger 0.24 on the first survey's lines. The rows say so, the map moves, and picks follow.
  - **G7** Save, close and reopen. Everything is where it was. Repeat with one DZG renamed away.
  - **G8** Add a grid to the GPS-only site. Its CRS is the site's.
  - **G9** The tape import on a file with a DZG still places by the tapes.
  - **G10** The Survey panel rows and menus read well. This settles C1's open points.
- [ ] Fold the results in. Fix rounds follow the usual review loop. Merging asks the author first ([[build-and-walkthrough-before-merge]]).
- [ ] At the PR: comment on #134 with what M17a delivered. Move the README roadmap row (M17a to Done, "next release"). Then write the M17b plan.
