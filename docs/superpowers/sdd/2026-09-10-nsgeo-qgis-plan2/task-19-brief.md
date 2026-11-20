### Task 19: Difference view, presets, and the M6 checkpoint

The difference view shows what a step removed, presets are named stacks saved in the survey JSON, and the root README stops saying nothing works. Ends M6: real data processable.

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/model/survey.py` (`Site.presets`)
- Modify: `packages/nsgeo-core/src/nsgeo/project.py` (serialise presets)
- Create: `packages/nsgeo-core/tests/test_presets.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py` (preset methods, `presets_changed`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/processing_dock.py` (difference toggle, presets menu)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (`difference_cleared`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py`
- Modify: `README.md`
- Create: `packages/nsgeo-qgis/tests/qgis/test_plugin_difference_presets.py`

**Interfaces:**
- Consumes: `StepStack.difference`, `StepStack.to_dicts/from_dicts`
- Produces: `Site.presets: dict[str, list[dict[str, Any]]]`; JSON key `"presets"`; `SiteSession.preset_names()`, `save_preset(name, key)`, `apply_preset(name, key)`, `delete_preset(name)`, signal `presets_changed()`; `ProcessingDock.diff_button: QToolButton` (checkable), signal `difference_toggled(int)`, `presets_button`, `presets_menu`, `save_preset_named(name)`, `apply_preset_named(name)`; `ProfileDock.difference_cleared` signal

- [ ] **Step 1: Write the failing core test**

Create `packages/nsgeo-core/tests/test_presets.py`:

```python
from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line, Site
from nsgeo.processing import StepStack, build_step
from nsgeo.project import ProjectError, load_site, save_site

from tests.synthetic import write_dzt


def _site(tmp_path):
    p = tmp_path / "L0.DZT"
    write_dzt(p, np.zeros((512, 20), dtype=np.int32))
    grid = Grid("G", (0.0, 0.0), 0.0, 10.0, 10.0, "EPSG:32616", 0.5)
    return Site(grids=[grid], lines=[Line.open(p, GridPlacement("G", "y", 0.0))])


def test_presets_round_trip_and_are_omitted_when_empty(tmp_path):
    site = _site(tmp_path)
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    assert "presets" not in out.read_text()
    stack = StepStack()
    stack.append(build_step("dewow", window_ns=6.0))
    stack.append(build_step("background_mean"))
    site.presets["campus"] = stack.to_dicts()
    save_site(site, out)
    back = load_site(out)
    assert back.presets == {"campus": stack.to_dicts()}
    assert StepStack.from_dicts(back.presets["campus"]).to_dicts() == stack.to_dicts()


def test_invalid_preset_is_a_project_error(tmp_path):
    site = _site(tmp_path)
    out = tmp_path / "survey.nsgeo.json"
    site.presets["bad"] = [{"step": "no_such_step", "params": {}}]
    save_site(site, out)
    with pytest.raises(ProjectError, match="bad"):
        load_site(out)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest packages/nsgeo-core/tests/test_presets.py -q`
Expected: FAIL — `AttributeError: 'Site' object has no attribute 'presets'`

- [ ] **Step 3: Add presets to the core**

`model/survey.py`, in `Site`: add `presets: dict[str, list[dict[str, Any]]] = field(default_factory=dict)` after `stacks`.

`project.py`, in `save_site` before writing: `if site.presets: doc["presets"] = site.presets`. In `load_site`, after `site.stacks = stacks`:

```python
    presets = doc.get("presets", {})
    for name, dicts in presets.items():
        try:
            StepStack.from_dicts(dicts)
        except (KeyError, TypeError, ValueError) as exc:
            raise ProjectError(f"invalid preset {name!r}: {exc}") from exc
    site.presets = dict(presets)
```

Run: `.venv/bin/python -m pytest packages/nsgeo-core/tests -q` — all PASS.

- [ ] **Step 4: Write the failing plugin test**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_difference_presets.py`:

```python
from __future__ import annotations

import numpy as np
import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo.processing import build_step
from plugin_testing import synthetic_dzt

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


@pytest.fixture
def plugin(fake_iface, tmp_path):
    import nsgeo_qgis

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    s = plugin.session
    s.new_site(tmp_path)
    s.add_grid(GRID)
    lines = []
    for i in range(2):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT")
        lines.append(Line.open(p, GridPlacement("A", "y", i * 0.5)))
    s.add_lines(lines)
    key = s.keys()[0]
    s.set_profiles(key, lines[0].load())
    s.open_line(key)
    yield plugin, s, key
    plugin.unload()


def test_difference_view_shows_what_a_step_removed(plugin):
    plugin, s, key = plugin
    pd, prd = plugin.processing_dock, plugin.profile_dock
    pd.add_step("dewow")
    pd.add_step("background_mean")
    pd.list.setCurrentRow(1)
    pd.diff_button.setChecked(True)
    assert "background_mean" in prd.difference_label.text()
    diff = prd.current_radargram()
    result = s.stack_for(key).result()
    assert diff is not result
    np.testing.assert_allclose(diff.data, s.stack_for(key).intermediate(0).data - result.data)
    pd.diff_button.setChecked(False)
    assert prd.difference_label.text() == ""


def test_difference_view_declines_sample_count_changing_steps(plugin):
    plugin, s, key = plugin
    pd, prd = plugin.processing_dock, plugin.profile_dock
    s.append_step(key, build_step("time_zero", mode="sample", sample=40))  # deterministic crop
    pd.list.setCurrentRow(0)
    messages = []
    prd.error.connect(messages.append)
    pd.diff_button.setChecked(True)
    assert messages and "sample count" in messages[0]
    assert not pd.diff_button.isChecked()
    assert prd.difference_label.text() == ""


def test_presets_save_apply_and_persist(plugin, tmp_path):
    plugin, s, key = plugin
    pd = plugin.processing_dock
    pd.add_step("dewow")
    pd.add_step("gain_agc")
    pd.save_preset_named("campus")
    assert s.preset_names() == ["campus"]
    other = s.keys()[1]
    s.open_line(other)
    assert pd.list.count() == 0
    pd.apply_preset_named("campus")
    assert [i.text() for i in (pd.list.item(r) for r in range(pd.list.count()))] == ["dewow", "gain_agc"]
    assert [a.text() for a in pd.presets_menu.actions() if a.text() == "campus"]
    s.save()
    assert '"presets"' in (tmp_path / "survey.nsgeo.json").read_text()
    s.delete_preset("campus")
    assert s.preset_names() == []
```

- [ ] **Step 5: Implement**

`session.py`: add `presets_changed = pyqtSignal()` and

```python
    # ---- presets ----------------------------------------------------------
    def preset_names(self) -> list[str]:
        return sorted(self._require_site().presets)

    def save_preset(self, name: str, key: str) -> None:
        name = name.strip()
        if not name:
            raise ValueError("a preset needs a name")
        self._require_site().presets[name] = self.stack_for(key).to_dicts()
        self._set_dirty(True)
        self.presets_changed.emit()

    def apply_preset(self, name: str, key: str) -> None:
        site = self._require_site()
        fresh = StepStack.from_dicts(site.presets[name])
        self._attach_source(key, fresh)
        site.stacks[key] = fresh
        self._touch_stack(key)

    def delete_preset(self, name: str) -> None:
        self._require_site().presets.pop(name, None)
        self._set_dirty(True)
        self.presets_changed.emit()
```

`processing_dock.py`: add `difference_toggled = pyqtSignal(int)`; in the top button row add

```python
        self.diff_button = QToolButton()
        self.diff_button.setText("Difference")
        self.diff_button.setCheckable(True)
        self.diff_button.setToolTip("Show what the selected step removed instead of the result")
        row.addWidget(self.diff_button)
        self.diff_button.toggled.connect(self._emit_difference)
```

and in the bottom row

```python
        self.presets_button = QToolButton()
        self.presets_button.setText("Presets")
        self.presets_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.presets_menu = QMenu(self.presets_button)
        self.presets_button.setMenu(self.presets_menu)
        bottom.addWidget(self.presets_button)
        session.presets_changed.connect(self._rebuild_presets_menu)
        session.site_opened.connect(self._rebuild_presets_menu)
        self._rebuild_presets_menu()
```

with methods:

```python
    def _emit_difference(self, checked: bool) -> None:
        self.difference_toggled.emit(self.list.currentRow() if checked else -1)

    def _rebuild_presets_menu(self) -> None:
        self.presets_menu.clear()
        self.presets_menu.addAction("Save current stack as…", self._save_preset_prompt)
        names = self.session.preset_names() if self.session.is_open else []
        if names:
            self.presets_menu.addSeparator()
            for name in names:
                self.presets_menu.addAction(name, lambda n=name: self.apply_preset_named(n))
            delete = self.presets_menu.addMenu("Delete")
            for name in names:
                delete.addAction(name, lambda n=name: self.session.delete_preset(n))

    def _save_preset_prompt(self) -> None:
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:")
        if ok and name.strip():
            self.save_preset_named(name)

    def save_preset_named(self, name: str) -> None:
        key = self.key()
        if key is not None:
            self.session.save_preset(name, key)

    def apply_preset_named(self, name: str) -> None:
        key = self.key()
        if key is not None:
            self.session.apply_preset(name, key)
```

(`QInputDialog` joins the widgets import.) In `_on_current_row`, after emitting `step_selected`, add `if self.diff_button.isChecked(): self._emit_difference(True)` so moving the selection moves the difference view.

`profile_dock.py`: add `difference_cleared = pyqtSignal()`; in `current_radargram`'s `except ValueError` branch, emit it when reverting `_difference_index`.

`plugin.py` `initGui`:

```python
        self.processing_dock.difference_toggled.connect(self.profile_dock.set_difference_index)
        self.profile_dock.difference_cleared.connect(lambda: self.processing_dock.diff_button.setChecked(False))
```

`README.md`: replace the status blockquote with

```markdown
> **Status: early development.** The core library (DZT reader, survey model,
> processing) is complete and tested. The QGIS plugin loads sites, imports
> lines onto the map, and shows and processes profiles. Map↔profile cursor
> sync, picking, and a release zip are next.
```

- [ ] **Step 6: Run everything, lint, mypy, commit**

Run the full verification set from Global Constraints, plus `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`.
Expected: all PASS, clean.

```bash
git add packages/nsgeo-core packages/nsgeo-qgis README.md
git commit -m "feat: difference view and named presets

The difference view shows what the selected step removed, using the
stack's cached intermediates; steps that change the sample count are
declined with the core's message. Presets are named stacks stored in
the survey JSON, validated on load, and applied through the session."
```

**M6 checkpoint (manual, 15 minutes).** Reload the plugin, open the M4 site, click FILE__001.

1. Processing dock ▸ Add step ▸ `dewow`: the profile brightens slightly (low-frequency drift gone). Add `background_mean`: the direct-wave band disappears and reflectors appear, matching the processed render in the Lavish mock. Add `gain_agc`: deeper reflectors come up.
2. Select `background_mean`, press Difference: the profile shows horizontal bands only, the mean trace. Press again to return. Select a step and drag it to another position: the image updates and the list order follows. Untick `dewow`: image changes; tick again.
3. Select `gain_agc`: the form shows window 20, target 1, eps 1e-12. Change window to 10 and press Enter: image updates. Type `abc`: an orange message appears under the form, nothing changes.
4. Add step ▸ `bandpass (needs values)`: the modal opens with blank orange fields and the header line reading antenna HS350US, Nyquist 2309 MHz. Enter 100 and 5000: OK stays disabled with a Nyquist message. Enter 100 and 600: OK enables; add. Add step ▸ `time_zero`, drag it to the top: the depth axis now starts at 0 and the time axis at 0. Select it and press Difference: a message bar warning says the sample count changes; the button unchecks.
5. Add step ▸ `gain_curve`: it appends with no dialog and the strip appears beside the image with a flat 0 dB line. Drag the lower point right: the lower half of the image brightens live. Double-click to add a middle point; right-click it to remove.
6. Presets ▸ Save current stack as… ▸ `campus`. Click FILE__002 (empty stack) ▸ Presets ▸ `campus`: the same stack appears and the image is processed. Apply to grid… ▸ Yes: click FILE__003 through FILE__010, each shows the processed image. Save site; confirm `presets` and per-line `stack` blocks in the JSON.
7. Display gain slider and colormap combo still work on the processed image and appear nowhere in the JSON.

Anything that fails here is fixed before Plan 3 is written.

---

## Handoff to Plan 3 (M7–M9)

Not in this plan, by design (spec §10):

- `MapLink` (trace cursor marker, selection rubber band), the trace map tool (hover snaps, click opens), and `lookup.nearest_trace` wired to canvas-CRS coordinates cached per line.
- Pick tool and picks-layer writes: `ProfileDock.pick_requested(key, trace, time_ns)` and `ProfileView.set_pick_mode` already exist; `SiteLayers` already creates the `picks` table.
- `build_zip.py`, the CI zip job, release notes, and promoting the core's `__init__` exports from the list of names the plugin actually imported.
- Hover readout (trace, distance, time, depth) in the viewer toolbar.
- Reading DZX marks into a hover tooltip; relocating missing files on open; a target-layer picker for picks.

Before Plan 3 is written, execute this plan and run the M6 checkpoint; Plan 3's design of `MapLink` should read the session and viewer as they actually turned out.
