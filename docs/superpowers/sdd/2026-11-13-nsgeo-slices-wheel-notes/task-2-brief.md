### Task 2: A Warnings section, and refusals that stay (#163 item 1, #157 items 4 and 5)

Spec §6.1. Replaces `site_note`.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/ui/warnings_panel.py`
- Modify: `nsgeo_qgis/ui/slices_dock.py` (remove `site_note` at ~464; add the panel after
  `position_group`; `_apply_resolution` frame-cap branch; `restore_cube`; `_seed_resolution_defaults`;
  `_on_source_changed`; `set_scope`)
- Modify: `nsgeo_qgis/ui/site_scope.py` (`show_scope_widgets`, `apply_resolution`, `refresh_slice`;
  `show_note` becomes `warnings`)
- Modify: `nsgeo_qgis/site_engine.py` (`_rebuild_geometry`, `_rebuild_geometry_reporting`, `clear`)
- Modify: `nsgeo_qgis/slices_plan.py` (`preview_note`)
- Test: new `tests/qgis/test_plugin_warnings_panel.py`; `tests/qgis/test_plugin_slices_dock.py`;
  `tests/qgis/test_plugin_site_scope.py`; `tests/qgis/test_plugin_site_engine.py`;
  `tests/pure/test_pure_slices_plan.py`

**Interfaces:**
- Produces, in `ui/warnings_panel.py`:
  - **Kinds:** `REFUSAL = "refusal"`, `WARNING = "warning"`, `NOTE = "note"`.
  - **Icons:** `ICONS = {REFUSAL: "⛔", WARNING: "⚠", NOTE: "ⓘ"}`.
  - **`Entry`:** `@dataclass(frozen=True) class Entry: kind: str; text: str`.
  - **`WarningsPanel(QGroupBox)`:** titled "Warnings".
    - `set_entries(entries: Iterable[Entry]) -> None` shows one word-wrapped `QLabel` per
      non-empty entry, reading `f"{ICONS[kind]} {text}"`. Order is refusals, then warnings, then
      notes, stable within a kind. The panel hides itself when there are none.
    - `entries() -> tuple[Entry, ...]` returns what is shown, in order.
- Produces `SlicesDock.warnings_panel` and `SlicesDock.show_warnings() -> None` (guarded). It asks
  `self._site.warnings()` in Whole site; in This grid it shows `self._grid_refusal`.
- Produces `SlicesDock._grid_refusal: str | None`, This grid's standing refusal. `_apply_resolution`
  sets it on a refusal and clears it on success. A grid change (`_on_source_changed`) and a scope
  switch (`set_scope`) clear it too.
- Produces `SiteScope.warnings() -> list[Entry]` from `self.drawn: bool`, which `refresh_slice` sets
  where it called `show_note`:
  - while drawn, `NOTE` with `engine.preview_note`;
  - while not drawn, `REFUSAL` with `f"Not drawn: {self.problem or engine.geometry_problem}"`;
  - `WARNING` with `mixed_clock_note(radar)` when the clocks are mixed (today's rule).
- Produces `SiteEngine.geometry_problem -> str | None` (a property):
  - `_rebuild_geometry` sets it to `str(exc)` when it raises, then re-raises;
  - a rebuild that completes sets it to `None`, and so does `clear()`;
  - `_rebuild_geometry_reporting` no longer calls `_report`, and logs instead.
- Produces `SlicesDock._set_cell_floor(grid_id: str) -> None`, the floor half of
  `_seed_resolution_defaults`, which now calls it. `restore_cube` calls it for the cube's grid
  before setting the cell.

- [ ] **Step 1: Write the failing tests.**

`test_plugin_warnings_panel.py`:

```python
def test_entries_show_in_full_in_kind_order_and_the_panel_hides_when_empty(qgis_app):
    panel = WarningsPanel()
    panel.set_entries([Entry(NOTE, "n"), Entry(REFUSAL, "r"), Entry(WARNING, "w"), Entry(NOTE, "")])
    assert [e.kind for e in panel.entries()] == [REFUSAL, WARNING, NOTE]
    assert [lbl.text() for lbl in panel.findChildren(QLabel)] == ["⛔ r", "⚠ w", "ⓘ n"]
    assert all(lbl.wordWrap() for lbl in panel.findChildren(QLabel))
    assert not panel.isHidden()
    panel.set_entries([])
    assert panel.isHidden() and panel.entries() == ()
```

`test_plugin_slices_dock.py`:
- **Rewrite `test_a_restored_cell_size_too_fine_to_draw_is_refused_not_attempted`** to cover the
  frame-cap backstop. Keep its setup.
  - `dock.warnings_panel.entries()` holds exactly one `REFUSAL`. Its text contains "too many to
    draw", "0.15" and "Still showing".
  - `errors == []`.
  - `dock.engine.frame is before`.
  - Then `cell_spin.setValue(0.25)` and a flush: the entries are empty.
- **`test_a_restored_cube_below_its_grids_floor_comes_back_at_the_floor(qgis_app, tmp_path)`:**
  - **Setup:** grids "A" (6 × 6 m) and "Big" (300 × 300 m), one synthetic line each. Prepare Big,
    `_save_cube` it, and set that record's `"cell"` to 0.05. Switch to A and let it prepare.
  - **Action:** `restore_cube`, then wait and flush.
  - **Asserts:**
    - `cell_spin.value() == pytest.approx(smallest_safe_cell(300.0, 300.0), abs=1e-3)`;
    - no entries;
    - `errors == []`;
    - the record's `"cell"` is still 0.05.
- **`test_a_warning_coming_and_going_keeps_the_box_you_type_in(docked)`** (Review Focus 3):
  - `_short_and_active`, with the scroll bar at its maximum;
  - dz focused, value set to 0.75;
  - `dock.warnings_panel.set_entries([Entry(REFUSAL, "x " * 200)])`, events pumped, then
    `set_entries([])`;
  - dz still has focus and reads 0.75.
- **`test_a_long_warning_never_widens_the_panel(docked)`:** the content's
  `minimumSizeHint().width()` is unchanged after a 400-character entry.

`test_plugin_site_scope.py`: rewrite every `dock.site_note` test (from ~3484 to ~3705) onto
`dock.warnings_panel.entries()`, keeping their names' intent:
- **The preview** is one `NOTE` equal to `engine.preview_note`. It clears when the site fits, and
  in This grid.
- **A failed resolution** is one `REFUSAL` starting `"Not drawn: "`, and
  **no** error carries its text (the old "the toast stays" assertion inverts).
- **A good resolution** clears it.
- **The clock warning** is its own `WARNING` entry, listed after the `REFUSAL` and before the `NOTE`
  (replacing `test_the_clock_warning_is_its_own_sentence_after_a_preview_or_a_reason`).
- **Width:** `test_the_site_note_never_widens_the_dock` becomes `test_a_long_warning_never_widens_the_site_panel`.
- **A geometry failure on an engine callback:**

```python
def test_a_geometry_failure_on_an_engine_callback_shows_in_warnings_not_a_toast(plugin, monkeypatch):
    dock = whole_site(plugin)
    errors = []
    dock.error.connect(errors.append)
    real = site_engine_module.SiteEngine._rebuild_geometry
    def boom(self):
        raise RuntimeError("the lattice could not be built")
    monkeypatch.setattr(site_engine_module.SiteEngine, "_rebuild_geometry", boom)
    dock.site_engine._rebuild_geometry_reporting()
    dock._site.refresh_slice()
    assert dock.site_engine.geometry_problem == "the lattice could not be built"
    assert [e.text for e in dock.warnings_panel.entries() if e.kind == REFUSAL] == [
        "Not drawn: the lattice could not be built"]
    assert not any("lattice" in e for e in errors)
    monkeypatch.setattr(site_engine_module.SiteEngine, "_rebuild_geometry", real)
    _nudge_cell(dock)
    assert dock.site_engine.geometry_problem is None
    assert not [e for e in dock.warnings_panel.entries() if e.kind == REFUSAL]
```

`test_pure_slices_plan.py::test_preview_note_is_exact_copy` gets new expectations:

```python
base = ("Preview at 0.4 m pixels: the site (1234 × 568 m) is too big to draw at 0.05 m. "
        "It draws in full at a 0.12 m cell or coarser.")
assert preview_note(0.4, 0.05, 1234.4, 567.6, 0.12, []) == base
assert preview_note(0.4, 0.05, 1234.4, 567.6, 0.12, ["C"]) == base[:-1] + ", or without grid C."
assert preview_note(0.4, 0.05, 1234.4, 567.6, 0.12, ["C", "D"]) == base[:-1] + ", or without grids C and D."
```

In `test_plugin_site_engine.py:1057`, replace `"Leaving out C"` with `"without grid C"`.

- [ ] **Step 2: Run them; expect failures.**
  - The `warnings_panel` import fails.
  - The site tests fail on the attribute.
  - The pure test fails on the old copy.

- [ ] **Step 3: Implement.**
  - **`WarningsPanel`:** must not raise the panel's minimum width; word-wrapped labels only.
  - **Placing the panel:** add it after `position_group` and delete `site_note`.
    `show_scope_widgets` stops touching `site_note`, and `set_scope` ends by calling
    `show_warnings()`.
  - **Frame-cap refusal copy:** "Cell {cell:g} m refused: grid {id} would be {cells:,} cells, too
    many to draw. Still showing {old:g} m. Use {safe:g} m or coarser." Here `old` is
    `self.engine.frame.cell`. Drop the "Still showing" sentence when there is no frame.
  - **`SiteScope.apply_resolution`:** stops emitting `error` in its engine-refusal branch. Its
    `Resolution` `ValueError` branch keeps the toast.
  - **The preview note:** the new copy. The site's `W × H` stays `:.0f`.

- [ ] **Step 4: Run the four test files and the pure tier; all green.**

- [ ] **Step 5: Commit and push.** Message:
  `feat(slices): a Warnings section for refusals, the clock warning and the preview note (#163, #157)`.

---

