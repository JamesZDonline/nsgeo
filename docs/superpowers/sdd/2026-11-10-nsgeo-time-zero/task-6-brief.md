### Task 6: Mixed clocks in a site, and the time base in every GeoTIFF

**Files:**
- Modify:
  - `packages/nsgeo-qgis/nsgeo_qgis/slices_plan.py` (`mixed_clock_note`)
  - `packages/nsgeo-qgis/nsgeo_qgis/ui/site_scope.py`: `grid_time_bases` and `show_note`.
  - `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py`: the `GeoTiffSliceWriter.write` metadata.
  - `packages/nsgeo-qgis/nsgeo_qgis/site_export.py`: `SiteGridRecord`, `plan_site_export`, the
    dataset metadata, and the module docstring.
- Test:
  - `packages/nsgeo-qgis/tests/pure/` (the `slices_plan` tests)
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_site_scope.py`
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export.py`
  - `packages/nsgeo-qgis/tests/qgis/test_plugin_site_export.py`

**Interfaces:**
- Consumes: from Task 1, `sets_time_zero`, `time_base_of` and the two constants.
- Produces:
  - **`slices_plan.mixed_clock_note(radar_grids: Sequence[str]) -> str`.** It returns `""` for an
    empty sequence. For one grid it returns
    `"Grid A has no Time zero step, so its times are from the radar's own zero and will not line up with the other grids."`.
    For several it returns `"Grids A, C have no Time zero step, so their times are …"`.
  - **`site_scope.grid_time_bases(session, source: SiteSource) -> dict[str, str]`:** grid id to
    `time_base_of(session.site.presets.get(choice.preset, []))`.
  - **`show_note`** appends `mixed_clock_note([...radar grids])` to the note and its hint.
    This happens only when the bases are **mixed**. When every grid is on the radar clock, they
    still line up, so it shows nothing.
  - **Per-grid GeoTIFF:** the dataset item `NSGEO_TIME_BASE` =
    `time_base_of(plan.provenance.steps)`. The coverage companion gets it too, because it shares
    the writer.
  - **Site GeoTIFF:**
    - `SiteGridRecord.time_base: str` is a new field, filled from each grid engine's
      `provenance().steps`.
    - The dataset item `NSGEO_SITE_TIME_BASE` is `"time_zero"`, `"radar"` or `"mixed"`.
    - The module docstring lists it.

- [ ] **Step 1: Write the failing tests**

In the pure tests:

```python
def test_mixed_clock_note_names_the_radar_grids():
    assert mixed_clock_note([]) == ""
    assert mixed_clock_note(["A"]).startswith("Grid A has no Time zero step")
    assert mixed_clock_note(["A", "C"]).startswith("Grids A, C have no Time zero step")
```

In `test_plugin_site_scope.py`:

```python
def test_the_site_note_warns_when_grids_are_on_different_clocks(...):
    # Grid A's preset has time_zero; grid B's does not.
    # site_note.text() contains mixed_clock_note(["B"]).
    ...


def test_the_site_note_says_nothing_when_every_grid_is_on_the_radar_clock(...):
    ...
```

In `test_plugin_slice_export.py`, test that an exported GeoTIFF's dataset metadata has
`NSGEO_TIME_BASE == "time_zero"` for a time_zero preset, and `"radar"` without one.

In `test_plugin_site_export.py`, test that a two-grid export with mixed presets writes
`NSGEO_SITE_TIME_BASE == "mixed"`, and that each `NSGEO_SITE_GRIDS` entry carries its own
`time_base`.

- [ ] **Step 2: Run them to make sure they fail**

Run the core command on the pure tests, and the QGIS command on the three QGIS files.
Expected: FAIL.

- [ ] **Step 3: Implement the Interfaces items**

- [ ] **Step 4: Run the full suites and lint**

Run the core + pure suite, the whole QGIS suite, and all three lint commands.
Expected: everything passes, and the counts are at least the baseline plus the new tests. Report
the counts.

- [ ] **Step 5: Commit and push**

```bash
git commit -am "feat(site): warn on mixed clocks; every GeoTIFF records its time base (#97)"
git push
```

---

## After Task 6 (coordinator)

1. **Final review** of the whole branch (opus).
2. **Deploy** to a new QGIS profile `ns_geo_time_zero`: `cp -a` from `ns_geo`, plus a `dev_link`
   to this worktree. Confirm that the branch code loads.
3. **Walkthrough** on real data (spec §10, eight checks). Record it on an Artifact page with a
   `results` db. The user runs it. Do not merge until it is done, or until the user waives it.
4. **At the PR:**
   - In the README roadmap, move time zero from In progress to Done ("next release"), and remove
     item 4 of Next.
   - Post a comment on #97 recording the decision and the PR.
   - Note on M15's branch that its plan needs the check described in spec §13.
