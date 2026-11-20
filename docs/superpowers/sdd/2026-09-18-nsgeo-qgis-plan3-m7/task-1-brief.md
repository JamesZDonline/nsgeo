## Task 1: The session's preview key

The load-bearing task. `current_key` is what `replace_step`, `apply_to_grid`, preset application and step removal all resolve their target through. If hovering the map moved `current_key`, moving the pointer would silently repoint every destructive operation in the plugin — spec §3.3, and defect class C2 from Plan 2's fix round. This task adds a second notion that can never do that.

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py` (signals block ~line 52-63, `__init__` ~line 65-79, properties ~line 128-137, `close_site` ~line 345, `open_line` ~line 577)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `SiteSession.preview_changed = pyqtSignal(str, int)` — `(key, trace)`; `("", -1)` when cleared.
  - `SiteSession.preview_key -> str | None`
  - `SiteSession.preview_trace -> int` (`-1` when none)
  - `SiteSession.display_key -> str | None` — `preview_key or current_key`
  - `SiteSession.set_preview(key: str | None, trace: int = -1) -> None`
  - `SiteSession.clear_preview() -> None`

- [ ] **Step 1: Write the failing tests**

Append to `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py`. Read the top of that file first and reuse its existing fixture for an open session with lines; the fixture below is written out in full in case no suitable one exists.

```python
# ---- preview key (M7, spec §3.3) --------------------------------------------


@pytest.fixture
def previewable(qgis_app, tmp_path):
    """A session with two lines placed on one grid."""
    from nsgeo.geometry.grid import Grid
    from nsgeo.geometry.placement import GridPlacement
    from nsgeo.model.survey import Line
    from plugin_testing import synthetic_dzt

    session = SiteSession()
    session.new_site(tmp_path)
    grid = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)
    session.add_grid(grid)
    lines = []
    for i in range(2):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", i * 0.5, 0.0, 1, p.stem)))
    session.add_lines(lines)
    keys = session.keys()
    session.open_line(keys[0])
    return session, keys


def test_set_preview_records_the_key_and_trace_and_emits_once(previewable):
    session, keys = previewable
    seen = []
    session.preview_changed.connect(lambda k, t: seen.append((k, t)))

    session.set_preview(keys[1], 12)

    assert session.preview_key == keys[1]
    assert session.preview_trace == 12
    assert seen == [(keys[1], 12)]


def test_preview_never_moves_the_working_line(previewable):
    """The C2 guard. current_key is what every write resolves through."""
    session, keys = previewable
    opened = []
    session.line_opened.connect(opened.append)

    session.set_preview(keys[1], 12)

    assert session.current_key == keys[0]
    assert session.current_trace == -1
    assert opened == []


def test_preview_never_dirties_the_session(previewable):
    session, keys = previewable
    session.save()
    assert not session.dirty

    session.set_preview(keys[1], 12)
    session.clear_preview()

    assert not session.dirty


def test_repeating_the_same_preview_emits_nothing(previewable):
    session, keys = previewable
    session.set_preview(keys[1], 12)
    seen = []
    session.preview_changed.connect(lambda k, t: seen.append((k, t)))

    session.set_preview(keys[1], 12)

    assert seen == []


def test_clear_preview_emits_the_cleared_sentinel_once(previewable):
    session, keys = previewable
    session.set_preview(keys[1], 12)
    seen = []
    session.preview_changed.connect(lambda k, t: seen.append((k, t)))

    session.clear_preview()
    session.clear_preview()

    assert seen == [("", -1)]
    assert session.preview_key is None
    assert session.preview_trace == -1


def test_display_key_is_the_preview_while_previewing(previewable):
    session, keys = previewable
    assert session.display_key == keys[0]

    session.set_preview(keys[1], 3)
    assert session.display_key == keys[1]

    session.clear_preview()
    assert session.display_key == keys[0]


def test_preview_trace_is_clamped_to_the_previewed_line(previewable):
    session, keys = previewable
    n = session.line_for_key(keys[1]).n_traces

    session.set_preview(keys[1], 10_000)
    assert session.preview_trace == n - 1

    session.set_preview(keys[1], -5)
    assert session.preview_trace == -1


def test_preview_of_an_unknown_key_raises_and_changes_nothing(previewable):
    session, keys = previewable
    session.set_preview(keys[1], 4)

    with pytest.raises(KeyError):
        session.set_preview("no/such/line", 0)

    assert session.preview_key == keys[1]
    assert session.preview_trace == 4


def test_set_trace_still_refuses_a_previewed_line(previewable):
    """set_trace is keyed to the WORKING line; a preview is not one."""
    session, keys = previewable
    session.set_preview(keys[1], 12)
    seen = []
    session.trace_changed.connect(lambda k, i: seen.append((k, i)))

    session.set_trace(keys[1], 20)

    assert seen == []
    assert session.current_trace == -1


def test_open_line_ends_the_preview_without_a_second_emission(previewable):
    """Promotion is one render, not two: line_opened drives it."""
    session, keys = previewable
    session.set_preview(keys[1], 12)
    seen = []
    session.preview_changed.connect(lambda k, t: seen.append((k, t)))

    session.open_line(keys[1])

    assert session.preview_key is None
    assert session.current_key == keys[1]
    assert seen == []


def test_close_site_clears_the_preview(previewable):
    session, keys = previewable
    session.set_preview(keys[1], 12)

    session.close_site()

    assert session.preview_key is None
    assert session.preview_trace == -1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_session.py -q -p no:xonsh -k preview`

Expected: FAIL — `AttributeError: 'SiteSession' object has no attribute 'preview_changed'` (or `set_preview`).

- [ ] **Step 3: Add the signal and the state**

In `session.py`, add to the signal block (after `selection_changed`, so the cursor-ish signals stay together):

```python
    # Spec §3.3: the WEAK notion of "what the pointer is over". It drives
    # the profile view and the trace cursor and nothing else, ever. It is
    # never a write target and never dirties the session -- see
    # set_preview() for why that distinction is load bearing.
    preview_changed = pyqtSignal(str, int)  # ("", -1) when cleared
```

In `__init__`, after `self._selection`:

```python
        self._preview_key: str | None = None
        self._preview_trace = -1
```

- [ ] **Step 4: Add the properties and the mutators**

After the `selection` property (~line 136), add:

```python
    @property
    def preview_key(self) -> str | None:
        return self._preview_key

    @property
    def preview_trace(self) -> int:
        return self._preview_trace

    @property
    def display_key(self) -> str | None:
        """The line the profile should be SHOWING -- the preview when there
        is one, otherwise the working line.

        Deliberately distinct from `current_key`, which is the line every
        write resolves through. A caller that is about to change data wants
        `current_key`; a caller that is about to draw wants this. Getting
        those two confused is exactly the C2 defect class (a write target
        resolved from a different source than the thing the user believes
        they are editing), so they do not share a name.
        """
        return self._preview_key or self._current_key
```

In the "current line, samples, cursor" section, after `clear_selection` (~line 632), add:

```python
    # ---- preview (spec §3.3) ----------------------------------------------
    def set_preview(self, key: str | None, trace: int = -1) -> None:
        """Set what the pointer is over. NOT a write target, ever.

        `current_key` is not merely what is displayed: `replace_step`,
        `apply_to_grid`, `apply_preset` and `remove_step` all resolve
        their target through it, and the processing dock binds to it. If
        hovering the map moved `current_key`, moving the pointer would
        silently repoint every destructive operation in the plugin -- edit
        a parameter, and it lands on a line the user only passed over,
        with no error and no cue. That is C2's defect class exactly, and
        C2 is already on this codebase's record. Hence a second, weaker
        notion that cannot reach any of those paths.

        Never sets dirty: a preview is a view state, not an edit. Never
        touches `_current_key`, `_current_trace` or `_selection`.
        """
        if key is None:
            self.clear_preview()
            return
        line = self.line_for_key(key)  # raises KeyError before anything changes
        index = -1 if trace < 0 else max(0, min(int(trace), line.n_traces - 1))
        if (key, index) == (self._preview_key, self._preview_trace):
            return  # loop guard: a marker update that round-trips is a no-op
        self._preview_key, self._preview_trace = key, index
        self.preview_changed.emit(key, index)

    def clear_preview(self) -> None:
        if self._preview_key is None and self._preview_trace == -1:
            return
        self._preview_key, self._preview_trace = None, -1
        self.preview_changed.emit("", -1)
```

- [ ] **Step 5: Make `open_line` and `close_site` forget the preview**

In `open_line`, insert the reset immediately before `self.line_opened.emit(key)`:

```python
        # Promotion ends the preview. Reset WITHOUT emitting
        # preview_changed: a listener told "preview cleared" would snap the
        # view back to the OLD working line, and be told to render the new
        # one an instant later by line_opened -- two renders and a visible
        # flash for one user gesture. line_opened is the single signal that
        # drives that render, and ProfileDock clears its own preview on it.
        self._preview_key = None
        self._preview_trace = -1
        self.line_opened.emit(key)
```

Note that the early return at the top of `open_line` (`if key == self._current_key: return`) is reached when promoting the line that is *already* the working line. That is the case ProfileDock treats as "not a preview at all" (Task 2), so nothing is left stale.

In `close_site`, alongside the other state resets, add:

```python
        self._preview_key = None
        self._preview_trace = -1
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_session.py -q -p no:xonsh`

Expected: PASS, and no pre-existing session test broken.

- [ ] **Step 7: Run both tiers and the linters**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Expected: pure `363 passed, 2 skipped`; QGIS `383 passed` (372 + 11 new); ruff clean.

- [ ] **Step 8: Commit**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis/session.py packages/nsgeo-qgis/tests/qgis/test_plugin_session.py
git commit -m "feat: give the session a preview key that is never a write target

Hovering the map must show a line without repointing the operations that
edit one. current_key is what replace_step, apply_to_grid, apply_preset
and remove_step all resolve through, so the pointer must not move it --
that is C2's defect class. preview_key drives the view and nothing else.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

