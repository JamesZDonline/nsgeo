### Task 7: Reproducing a saved cube

A recipe you can only write is half a feature. This task closes the loop: pick a saved cube from
the Source group and the dock comes back to exactly the state that produced it.

**Why it is its own task rather than folded into Task 6.** The record's *writer* and its *reader*
fail differently — a writer bug loses information, a reader bug silently reconstructs the wrong
thing — and the reader's test is a round trip that can only exist once the writer is finished.
This also deliberately takes the plan to **seven** tasks rather than growing Task 6, which already
carries the GeoTIFF, the temporal axis, the `.npz` and two file dialogs. The standing preference
is for 3–6 tasks, and the reason behind it is smaller chunks; seven right-sized tasks serve that
better than six with one oversized one. **Flag the deviation when reporting.**

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/slice_export.py` (the reader half)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` (the Source group's cube combo)
- Modify: `packages/nsgeo-core/src/nsgeo/model/survey.py` (the `Site.cubes` docstring)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export.py` (append)

**Interfaces:**

- Produces:
  - `slice_export.CubeRecipe(choice: SourceChoice, resolution: Resolution, view: ViewSettings)`
  - `slice_export.recipe_from_record(record: dict[str, Any]) -> CubeRecipe`
  - `SlicesDock.cube_combo`, `SlicesDock.restore_cube(cube_id: str)`,
    `SlicesDock.view_settings() -> ViewSettings`, `SlicesDock.apply_view(view: ViewSettings)`

---

- [ ] **Step 1: Write the round-trip test first — it is the whole point of the task**

Append to `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_export.py`:

```python
def test_a_restored_recipe_reproduces_the_identical_slice(exportable_with_session):
    """The only definition of "reproducible" worth having.

    Not "the fields came back" -- a recipe that restores every field and
    still produces a different picture has failed at the one thing it is
    for. So: slice, save, wipe the engine, restore from the record alone,
    slice again, and demand the same numbers.

    This is also the test that catches a field quietly dropped from the
    record, which is otherwise invisible: a missing z range just means
    the restored cube silently uses whatever the dock happened to have.
    """
    engine, session = exportable_with_session
    window = SliceWindow(6, 18)
    before, coverage_before = engine.slice_at(window)

    npz = save_cube_npz(engine, session.root / "slices" / "A__first.npz")
    view = ViewSettings(
        thickness_ns=5.0, step_ns=2.5, radius_m=0.75,
        palette="amp_heat", stretch="shared", coverage=False,
    )
    record = cube_record(session, engine.choice, engine.frame, engine.z, view, npz)
    session.site.cubes["A__first"] = record
    session.save()

    # Everything the dock held is gone; the record is all that is left.
    engine.clear()
    assert not engine.is_prepared

    recipe = recipe_from_record(load_site(session.json_path).cubes["A__first"])
    engine.set_source(recipe.choice)
    assert engine.wait_for_preparation(20_000)
    engine.set_resolution(recipe.resolution)
    after, coverage_after = engine.slice_at(window)

    np.testing.assert_array_equal(coverage_before, coverage_after)
    np.testing.assert_array_equal(np.isfinite(before), np.isfinite(after))
    both = np.isfinite(before)
    np.testing.assert_allclose(before[both], after[both], rtol=1e-6, atol=1e-7)
    assert recipe.view == view


def test_a_recipe_restores_the_exact_line_set_not_the_whole_grid(exportable_with_session):
    """A cube built from 22 of 26 lines is not the same cube as one built
    from all 26, and the difference is invisible in a picture. The record
    carries the line keys for exactly this reason."""
    engine, session = exportable_with_session
    subset = tuple(session.keys())[:2]
    engine.set_source(SourceChoice("A", "p", "amp_envelope", subset))
    assert engine.wait_for_preparation(20_000)
    engine.set_resolution(Resolution(cell=0.25, dz_ns=0.5, t0_ns=2.0, t1_ns=30.0))
    npz = save_cube_npz(engine, session.root / "slices" / "A__subset.npz")
    record = cube_record(session, engine.choice, engine.frame, engine.z, _VIEW, npz)

    recipe = recipe_from_record(record)
    assert recipe.choice.line_keys == subset
    assert len(recipe.choice.line_keys) < len(session.keys())


def test_a_record_written_by_an_older_build_still_loads(exportable_with_session):
    """The five-key record `Site.cubes`'s docstring described before this
    milestone must not become unreadable. `load_site` stores records
    opaquely, so an old one arrives here intact and the reader -- not the
    schema -- is what has to tolerate it."""
    old = {
        "grid_id": "A", "preset": "p", "transform": "amp_envelope",
        "cell": 0.25, "array": "slices/A__old.npz",
    }
    recipe = recipe_from_record(old)
    assert recipe.choice.grid_id == "A"
    assert recipe.choice.line_keys == ()  # unknown, not invented
    assert recipe.resolution is None  # unknown: the dock keeps what it has
    assert recipe.view is None


def test_a_record_with_a_broken_field_is_refused_by_name(exportable_with_session):
    bad = {
        "grid_id": "A", "preset": "p", "transform": "amp_envelope", "cell": 0.25,
        "array": "slices/x.npz", "lines": [], "view": {},
        "z": {"t0_ns": 30.0, "t1_ns": 2.0, "dz_ns": 0.5},  # reversed
    }
    with pytest.raises(ValueError, match="z"):
        recipe_from_record(bad)
```

Define `_VIEW` once at module scope beside the other constants.

- [ ] **Step 2: Run and watch them fail.** Expected: `ImportError` for `recipe_from_record` /
`ViewSettings`.

- [ ] **Step 3: Implement the reader half**

In `slice_export.py`:

```python
@dataclass(frozen=True)
class ViewSettings:
    """How a cube was being read, as opposed to what it was binned from.

    Changing any of these changes no pixel in the `.npz` -- which is why
    they live in their own object and under their own key in the record.
    A reader restoring a cube wants both halves, but only the other half
    decides whether two records name the same array.
    """

    thickness_ns: float
    step_ns: float
    radius_m: float
    palette: str
    stretch: str
    coverage: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "thickness_ns": float(self.thickness_ns),
            "step_ns": float(self.step_ns),
            "radius_m": float(self.radius_m),
            "palette": str(self.palette),
            "stretch": str(self.stretch),
            "coverage": bool(self.coverage),
        }

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> ViewSettings:
        return cls(
            thickness_ns=float(doc["thickness_ns"]),
            step_ns=float(doc["step_ns"]),
            radius_m=float(doc["radius_m"]),
            palette=str(doc["palette"]),
            stretch=str(doc["stretch"]),
            coverage=bool(doc.get("coverage", False)),
        )


@dataclass(frozen=True)
class CubeRecipe:
    """A `Site.cubes` record, read back as the three things the dock sets.

    `resolution` and `view` are optional because a record written before
    this milestone carries neither. Absent means UNKNOWN, and the dock
    keeps whatever it already had rather than inventing a default that
    would look like a restored setting.
    """

    choice: SourceChoice
    resolution: Resolution | None
    view: ViewSettings | None


def recipe_from_record(record: Mapping[str, Any]) -> CubeRecipe:
    """Read a cube record back into the three values the dock sets.

    Tolerant of a record written by an earlier build -- `load_site`
    stores records opaquely, so old ones arrive here unchanged and it is
    this function, not the schema, that has to cope. Strict about a
    field that is PRESENT and wrong: a reversed z range restored silently
    would produce a different cube under the same name, which is the one
    failure a reproducibility feature must not have.
    """
    try:
        choice = SourceChoice(
            grid_id=str(record["grid_id"]),
            preset=str(record["preset"]),
            transform="" if record.get("transform", "none") == "none" else str(record["transform"]),
            line_keys=tuple(str(k) for k in record.get("lines", ())),
        )
    except (KeyError, TypeError) as exc:
        raise ValueError(f"cube record is missing {exc}") from exc

    resolution = None
    if "z" in record:
        z_doc = record["z"]
        try:
            resolution = Resolution(
                cell=float(record["cell"]),
                dz_ns=float(z_doc["dz_ns"]),
                t0_ns=float(z_doc["t0_ns"]),
                t1_ns=float(z_doc["t1_ns"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"cube record has an invalid z range: {exc}") from exc

    view = None
    if record.get("view"):
        try:
            view = ViewSettings.from_dict(dict(record["view"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"cube record has invalid view settings: {exc}") from exc

    return CubeRecipe(choice=choice, resolution=resolution, view=view)
```

Note the `transform` mapping: the record stores `"none"` where a `SourceChoice` holds
`NO_TRANSFORM` (`""`), because `"none"` is what reads correctly in a file someone opens in a text
editor. This is the only place the two spellings meet, and it must round-trip — the first
round-trip test above covers it through `recipe.view == view` and the identical-slice assertion.

- [ ] **Step 4: Add the cube combo to the Source group**

At the **top** of the Source group, above `Grid` — it is the control that sets all the others, so
it reads first:

```
Cube      [ (unsaved)                 ▾ ]
```

- `cube_combo` is refilled from `sorted(session.site.cubes)` with `"(unsaved)"` first, on
  `session.site_opened` and whenever a cube is saved. It joins `rebuild_source`'s existing
  session-signal connections.
- Selecting a saved cube calls `restore_cube(cube_id)`: `recipe_from_record` the record, apply
  `recipe.view` to the Display and Position widgets **with signals blocked** (so restoring does
  not fire four separate refreshes), set the inclusion set from `recipe.choice.line_keys`, set the
  three source combos, set the Resolution widgets, then `flush_debounce()` and one `prepare()`.
  Guard the whole body and report a `ValueError` from the reader through `error` and
  `source_status`, exactly as a conflicting preset is reported.
- Selecting `"(unsaved)"` changes nothing: it is a label for "these settings match no saved
  cube", not an action. Set it automatically whenever any Source or Resolution widget moves away
  from the restored values, so the combo never claims a cube the dock is no longer showing.
- `view_settings()` reads the six values off the widgets; `apply_view(view)` writes them back.
  Task 6's save handler calls `view_settings()` so the record carries what was on screen at the
  moment of saving.

- [ ] **Step 5: Update the `Site.cubes` docstring**

In `packages/nsgeo-core/src/nsgeo/model/survey.py`, replace the paragraph beginning *"Unlike every
line path elsewhere in a Site..."* — M11 has now discharged it — and describe the full shape:
the five original keys, plus `lines` (the included line keys), `z` (`t0_ns`, `t1_ns`, `dz_ns`) and
`view` (thickness, step, radius, palette, stretch, coverage). State the split explicitly: every
key except `view` decides what the array contains, and `view` decides only how it was last being
read. Note that `array` is routed through `project.line_key` by the plugin's `cube_record`, since
`save_site` still writes the record verbatim.

- [ ] **Step 6: Verify and prove discrimination**

Mutants, one at a time:

1. `cube_record` → drop the `"lines"` key. Expect
   `test_a_recipe_restores_the_exact_line_set_not_the_whole_grid` to FAIL, **and** confirm whether
   `test_a_restored_recipe_reproduces_the_identical_slice` also catches it — it should not, since
   that fixture includes every line, which is exactly why the second test exists. Record both
   results: a test that passes against this mutant is the reason the other one was written.
2. `cube_record` → drop the `"z"` key. Expect the identical-slice test to FAIL (the restored
   engine gets no resolution, so `slice_at` raises).
3. `recipe_from_record` → map `"none"` to `"none"` rather than `""`. Expect the identical-slice
   test to FAIL — the restored source would append a step named `none`, which is not in the
   registry.
4. `recipe_from_record` → wrap the z read in a bare `except: pass`. Expect
   `test_a_record_with_a_broken_field_is_refused_by_name` to FAIL.

- [ ] **Step 7: Commit and push**

```bash
git add packages/nsgeo-qgis packages/nsgeo-core/src/nsgeo/model/survey.py
git commit -m "feat(slices): save and restore a cube recipe through the survey JSON

The record now carries the lines, the z range and the view settings
alongside the five keys it already had, and the Source group can restore
one. Pinned by a round trip that demands the same slice back, not merely
the same fields.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push origin nsgeo-m11
```

**Task 7 is done when:** a cube saved, a site closed and reopened, and the cube selected from the
combo produces the identical slice — and both tiers are green.

---

## After Task 7: the manual walkthrough gate

**This is a human checkpoint, not a task.** It must be surfaced to the user and passed by them —
never silently — and no merge decision is made before it. M10 was core-only and the gate was a
formality; M11 is entirely UI, so it is the only thing that actually tests what this milestone
claims to deliver.

Deploy:

```bash
.venv/bin/python packages/nsgeo-qgis/scripts/dev_link.py --profile ns_geo
```

(the profile is `ns_geo`, with an underscore), then in QGIS with the real data:

1. Open a site with a grid of real DZT lines. The **Slices** dock is tabified behind Processing.
2. Choose the grid, a preset, and `amp_envelope`. `Choose…` lists every line, marks any that
   carries its own stack as *using the preset instead*, and the summary reads `n of m included`
   with an approximate memory figure. Press **Prepare** and watch per-line progress.
3. Drag the depth slider. The map raster redraws live; the readout beneath the slider states the
   window in ns and m and tracks what was actually averaged — **push the slider to both ends and
   confirm the range shrinks there rather than reporting the requested thickness**.
4. Change the thickness. The stretch stays shared and the picture stays comparable across depth.
   Switch to *this slice* and confirm a deep slice becomes legible.
5. Move the fill radius. The picture smooths; drag it continuously and confirm the UI stays
   responsive (the debounce doing its job). Set it to 0 and confirm the honest, gappy bins.
6. Tick **Show coverage**. Empty cells are visibly distinct from zero-amplitude cells.
7. Change the cell size and dz. Everything re-bins, the layer resizes in place, **and nothing
   raises** — this is the stale-plan hazard in its live form.
8. Open a line in the profile view. The slice's time window is drawn as a band across the
   radargram, and it follows the depth slider.
9. Shift + scroll on the map canvas steps depth. Plain scroll still zooms the map.
10. **Save cube…**, then **Export GeoTIFF…**. Open the GeoTIFF fresh in QGIS: the band names read
    as ns and m ranges, and the Temporal Controller steps through the bands.
11. Save the survey, close it, reopen it: the `cubes` record is there and its path is relative.
    Pick the cube from the **Cube** combo — every control comes back where it was, and the slice
    on screen is the one you saved. Open the survey JSON in an editor and confirm the record reads
    as a recipe a person could follow.
12. Unload the plugin with the Slices dock open and a line chooser open. Nothing leaks, nothing
    raises.

Report what actually happened at each step, including anything that looked wrong. Then ask before
merging.

## Spec amendments to make when the milestone lands

Following the M10 precedent of annotating the spec where execution diverged, rather than leaving
it to be read as history:

- **§7.4** — note that the third residency tier (on-disk, memory-mapped lines) is still unbuilt
  and unmeasured, that its spike did not run in M11, and that M11 deliberately ships no control
  for it (plan Ruling 1). The table's third row stands as designed-for-not-built.
- **§9.2** — note that the residency override is binary (automatic, or always resident) for the
  same reason.
- **§6.2 / §8** — record Ruling 2: the transform is appended by the engine after the preset's
  steps, so `output_unipolar` is exact by construction and a preset carrying an amplitude
  transform is refused. This is the alternative to the per-step `preserves_unipolar` that §8's
  problem would otherwise need.
- **§9.4** — record Ruling 4: the north-up resample lives in `nsgeo.slices.display`, not the
  plugin, because it is pure frame geometry; the plugin keeps only GDAL.
- **§9.5** — record Ruling 3: the option set is the export's. The live preview layer writes
  uncompressed, because `COMPRESS=DEFLATE, PREDICTOR=3` costs 8.8–25.2 ms per write against
  1.0–1.3 ms, and it is rewritten on every tick.
- **§5.4** — record that a `cubes` record carries the full recipe, not only the five keys first
  sketched there: `lines`, `z` and `view` join them so a cube can be reproduced from the survey
  file alone. No `SCHEMA_VERSION` bump, because `load_site` stores each record opaquely.
- **§6.4** — record that `fill` now rounds its FFT to a 5-smooth size and caches the kernel
  spectrum, with the measured figures, and that the radius slider debounces regardless because
  even the improved fill is 32 ms at 600×600.

Commit the decision record under `docs/superpowers/sdd/2026-09-19-nsgeo-slices-m11/`, following
Plan 2, M7 and M10: a `progress.md` ledger carrying every ruling with its reason and its cost if
wrong, a brief and a report per task, and a `deferred-minors.md` triaged before merge.

## Self-review against the spec

| Spec section | Where it lands |
|---|---|
| §5–§6 (data model, processing) | M10; unchanged here except `fill`'s padding (Task 1) |
| §6.4 fill radius as a slider | Task 4 (metres, debounced), Task 1 (the speedup) |
| §6.6 thickness/step independent; readout shows the full range | Task 1 (`plan_windows`, `window_label`), Task 4 (the readout) |
| §7.4 residency | Task 2 (`choose_residency`), two tiers by Ruling 1 |
| §8 unipolar rendering, shared stretch, per-slice override | Task 1 (`shared_limit`), Task 4 (palette, stretch combo, shader) |
| §9.1 source dialog, `Choose…`, preparation as a task, memory reported | Task 3 |
| §9.2 dock tabified, four groups, live sliders, fused readout, status line, shift+scroll | Tasks 3, 4, 5 |
| §9.3 the profile band | Task 5 |
| §9.4 multi-band GeoTIFF, band descriptions, coverage companion, layer group | Task 6 |
| §9.5 creation options, temporal properties, the ns→ms trap | Task 6 |
| §11 testing: two tiers, real data primary, properties, no orphans | Throughout; real data in Task 1, the streaming/resident property in Task 2 |
| §5.4 the survey JSON records the recipe | Tasks 6 and 7 (write, then read back) |
| §10, §12 site mosaic, de-striping, netCDF, elevation axis | M12 and beyond; out of scope here |
