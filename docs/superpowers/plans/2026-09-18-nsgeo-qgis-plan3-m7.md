# M7 — the map ↔ profile link: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pointing at a line on the QGIS map shows you its radargram, and the profile's cursor and selection draw back onto the map — without taking the canvas away from QGIS's own tools.

**Architecture:** A new `MapLink(QObject)` owns two canvas items (a `QgsVertexMarker` for the trace cursor, a `QgsRubberBand` for the selected segment) and listens to `SiteSession` to draw them. In the other direction it connects `QgsMapCanvas.xyCoordinates`, which fires on mouse move regardless of the active map tool, so hover tracking costs no tool slot. Hovering sets a new, weaker session notion — `preview_key` — which drives the profile *view* and nothing else; the working line (`current_key`, the target of every write) changes only when the user selects the line feature with QGIS's own Select tool.

**Tech Stack:** Python 3.12 (3.9 floor), PyQt5, QGIS 3.44 LTR bindings, numpy, pytest. No new third-party dependencies.

**Spec:** `docs/superpowers/specs/2026-09-18-nsgeo-qgis-plan3-design.md` — §3 is M7. Parent spec: `docs/superpowers/specs/2026-09-10-nsgeo-qgis-plugin-design.md`.

**Worktree:** `.worktrees/nsgeo-m7`, branch `nsgeo-m7`, forked from `main` at `affbabd`.

---

## Global Constraints

These apply to every task. They are not restated per task.

- **Two test tiers, both must pass before any task is reported done.**
  - Pure tier (no QGIS): `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh`
  - QGIS tier: `QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh`
  - **Baseline at `affbabd`, measured in this worktree:** pure `363 passed, 2 skipped`; QGIS `372 passed`. Any task that ends below those pass counts has broken something.
- **`-p no:xonsh` is required on this machine only.** `.venv-qgis` is built `--system-site-packages`, so the system `xonsh` package's stale pytest plugin breaks collection. Never add it to a config file committed to the repo (Plan 2, Ruling 12).
- **`PYTHONDONTWRITEBYTECODE=1` on every run.** Stale `.pyc` files fake mutation-test survivors and mask reverted source.
- **Lint and types, from the pure venv (neither tool is on `PATH`):**
  - `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .`
  - `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`
  - Note that `map_link.py` is **not** in the mypy list: that list is deliberately restricted to modules importable without QGIS. Do not add it.
- **Every Qt slot catches its own exceptions.** An exception escaping a slot prints and passes locally (PyQt 5.15.10) but reaches `qFatal()` in the `qgis/qgis:ltr` CI container and aborts the whole job. Every method connected to a signal wraps its body in `try/except Exception` and reports via the module's `_log` helper. The `_no_swallowed_slot_exceptions` conftest fixture fails any test that lets one escape — do not fight it, fix the slot.
- **No unhandled modals.** The `_no_unhandled_modals` fixture forbids `QMessageBox.question/warning/information`, `QFileDialog.*`, `QInputDialog.getText`, `QDialog.exec`, `QMenu.exec`, and `QTest.mouseDClick`. M7 adds no dialogs; nothing here should need `answer_modal` or `drive_dialog`.
- **Real data is the primary validation.** Ten real GSSI DZT files are symlinked at `packages/nsgeo-core/tests/data/local/`. Use `plugin_testing.REAL_DZT` / `needs_real_data` where a test benefits; `plugin_testing.synthetic_dzt` is fine for geometry-only tests, which most of M7's are.
- **The session is the only state holder.** No widget stores survey state or talks to another widget directly; everything reads `SiteSession` and connects to its signals. `MapLink` follows this rule — it holds canvas items and a geometry cache, never survey state.
- **Commit after each task**, message in the repo's style (lowercase `feat:`/`fix:`/`test:`/`docs:` prefix, imperative, and the body explains *why*). End every commit message with:
  ```
  Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  ```

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `packages/nsgeo-qgis/nsgeo_qgis/session.py` | modify | Adds `preview_key` / `preview_trace` / `display_key` and `set_preview` / `clear_preview`. The preview is session state because two widgets read it; it is *separate* state because it must never be a write target. |
| `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` | modify | Renders the displayed line, which is the preview when there is one. Owns the "you are looking at a preview" banner and hides the two overlays bound to the working line. |
| `packages/nsgeo-qgis/nsgeo_qgis/map_link.py` | **create** | The whole map↔profile link: the marker, the band, the canvas-CRS geometry cache, hover hit-testing, and selection promotion. |
| `packages/nsgeo-qgis/nsgeo_qgis/loader.py` | modify | One connection, so a previewed line's samples load in the background too. |
| `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` | modify | Constructs `MapLink` in `initGui`, disposes it in `unload`. |
| `packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py` | **create** | Every `MapLink` test. |
| `packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py` | **create** | Spec §6: every declared signal has a `connect`. Pure tier — it reads source text, not QGIS. |
| `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py` | modify | Preview-state tests. |
| `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py` | modify | Preview-rendering tests. |

**Why `map_link.py` is not in `maptools/`.** It is deliberately *not* a `QgsMapTool` (spec §3.2) — filing it beside `digitise_tool.py` would tell the next reader the opposite of the design's central decision. It sits at the package top level beside `layers.py`, which is the other module that owns QGIS canvas/project objects on the session's behalf.

---

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

## Task 2: The profile shows the preview, and says so

The profile must state which line it is showing and whether that is the working line or a preview — without it, the user cannot tell whether what they are looking at is what they are about to edit, which reintroduces the confusion the split exists to prevent (spec §3.3).

Two overlays are bound to the working line and must not follow a preview: the **gain strip** (it edits a step in the working line's stack, and it writes on drag — a strip whose curve belongs to a line that is not on screen is precisely the C2 configuration) and the **difference view** (a property of a selected step). Both hide during a preview and return when the view snaps back. Returning matters: `_difference_index` must survive the round trip.

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py` (append)

**Interfaces:**
- Consumes (Task 1): `session.preview_changed(str, int)`, `session.preview_key`, `session.current_trace`, `session.selection`.
- Produces: no new public API. `ProfileDock._key` changes from an attribute to a read-only property returning the **displayed** key.

- [ ] **Step 1: Write the failing tests**

Append to `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py`.

That file's existing `opened` fixture builds only **one** line, and every test here needs a second one to preview. Add a sibling fixture rather than changing `opened`, which 20-odd existing tests depend on. `GRID`, `synthetic_dzt`, `Line`, `GridPlacement` and `build_step` are already imported at the top of that file.

```python
# ---- preview rendering (M7, spec §3.3) --------------------------------------


@pytest.fixture
def previewing(qgis_app, tmp_path):
    """Two lines on one grid, the first open. `opened` has only one line,
    and a preview needs somewhere else to point."""
    session = SiteSession()
    dock = ProfileDock(session)
    dock.resize(900, 360)
    dock.show()
    session.new_site(tmp_path)
    session.add_grid(GRID)
    for i in range(2):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=240)
        session.add_lines([Line.open(p, GridPlacement("A", "y", i * 2.0, 0.0, -1, p.stem))])
    keys = session.keys()
    session.open_line(keys[0])
    yield dock, session, keys
    # Parentless top-level widget: torn down explicitly rather than left
    # for Python's GC to race Qt's widget teardown. See `opened`.
    dock.hide()
    dock.deleteLater()


def test_preview_renders_the_previewed_line_not_the_working_one(previewing):
    dock, session, keys = previewing

    session.set_preview(keys[1], 5)

    assert dock._key == keys[1]
    assert session.current_key == keys[0]
    label = session.line_for_key(keys[1]).path.stem
    assert label in dock.windowTitle()


def test_the_banner_names_the_previewed_line_and_clears_on_snap_back(previewing):
    dock, session, keys = previewing
    assert dock.preview_label.text() == ""

    session.set_preview(keys[1], 5)
    assert session.line_for_key(keys[1]).path.stem in dock.preview_label.text()

    session.clear_preview()
    assert dock.preview_label.text() == ""
    assert dock._key == keys[0]


def test_the_gain_strip_hides_during_a_preview_and_comes_back(previewing):
    dock, session, keys = previewing
    dock.show_gain_strip([[0.0, 1.0], [1.0, 2.0]], owner=("x", 0, 0))
    assert dock.gain_strip.isVisible()

    session.set_preview(keys[1], 5)
    assert not dock.gain_strip.isVisible()

    session.clear_preview()
    assert dock.gain_strip.isVisible()


def test_a_hidden_gain_strip_stays_hidden_after_a_preview(previewing):
    dock, session, keys = previewing
    assert not dock.gain_strip.isVisible()

    session.set_preview(keys[1], 5)
    session.clear_preview()

    assert not dock.gain_strip.isVisible()


def test_the_difference_index_survives_a_preview_round_trip(previewing):
    dock, session, keys = previewing
    session.append_step(keys[0], build_step("dewow", window_ns=4.0))
    dock.set_difference_index(0)
    assert dock._difference_index == 0

    session.set_preview(keys[1], 5)
    assert dock._effective_difference_index == -1  # not computed on someone else's stack
    assert dock._difference_index == 0             # but remembered

    session.clear_preview()
    assert dock._effective_difference_index == 0


def test_snap_back_restores_the_working_lines_cursor_and_selection(previewing):
    dock, session, keys = previewing
    session.set_trace(keys[0], 9)
    session.set_selection(keys[0], 3, 11)

    session.set_preview(keys[1], 5)
    session.clear_preview()

    assert dock.view._cursor == 9
    assert dock.view._selection == (3, 11)


def test_hovering_the_profile_during_a_preview_does_not_move_the_working_trace(
    previewing,
):
    """The C2 guard at the widget level."""
    dock, session, keys = previewing
    session.set_trace(keys[0], 9)
    session.set_preview(keys[1], 5)

    dock.view.trace_hovered.emit(40)

    assert session.current_trace == 9
    assert session.current_key == keys[0]


def test_previewing_the_working_line_is_not_a_preview(previewing):
    dock, session, keys = previewing

    session.set_preview(keys[0], 5)

    assert dock.preview_label.text() == ""
    assert dock._key == keys[0]


def test_opening_a_line_while_previewing_ends_the_preview(previewing):
    dock, session, keys = previewing
    session.set_preview(keys[1], 5)

    session.open_line(keys[1])

    assert dock.preview_label.text() == ""
    assert dock._key == keys[1]


def test_closing_the_site_while_previewing_clears_the_banner(previewing):
    dock, session, keys = previewing
    session.set_preview(keys[1], 5)

    session.close_site()

    assert dock.preview_label.text() == ""
    assert dock._key is None
```

`ProfileView._cursor` (an `int`, `-1` when none) and `ProfileView._selection` (a `tuple[int, int]`, `(-1, -1)` when cleared) are the real attribute names — verified in `profile_view.py:67-68`. That file exposes no public accessors for either.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py -q -p no:xonsh -k preview`

Expected: FAIL — `AttributeError: 'ProfileDock' object has no attribute 'preview_label'`.

- [ ] **Step 3: Split the displayed key from the working key**

`self._key` has exactly **two** assignment sites (`profile_dock.py:268` in `_open`, `profile_dock.py:350` in `_clear`) and ~29 read sites. Turning it into a property means the read sites need no edits at all and automatically mean "the displayed line", which is what every one of them wants.

In `__init__`, replace `self._key: str | None = None` with:

```python
        self._working_key: str | None = None
        self._preview_key: str | None = None
        self._strip_was_visible = False
```

Add the property next to the `percentile` / `colormap_name` properties:

```python
    @property
    def _key(self) -> str | None:
        """The line being DISPLAYED -- the preview when there is one.

        Every read site in this file wants this: a stack_changed on the
        line currently on screen should re-render it whether that line is
        the working one or a preview, and `_on_trace_changed`'s key filter
        should reject the working line's cursor while a preview is up.
        The two assignment sites became `_working_key` instead.
        """
        return self._preview_key or self._working_key

    @property
    def _effective_difference_index(self) -> int:
        """`-1` while previewing: the difference view is a property of a
        step in the WORKING line's stack, and `_difference_index` indexes
        that stack. Computing it against a previewed line's stack would be
        an index into the wrong list -- at best an IndexError, at worst a
        plausible-looking image of the wrong subtraction. Kept separate
        from `_difference_index` itself so the mode is remembered and
        returns intact when the view snaps back (spec §3.3)."""
        return -1 if self._preview_key is not None else self._difference_index
```

Change line 268 (`_open`) from `self._key = key or None` to `self._working_key = key or None`, and line 350 (`_clear`) from `self._key = None` to:

```python
        self._working_key = None
        self._preview_key = None
        self.preview_label.setText("")
```

Then replace both uses of `self._difference_index` inside `current_radargram()` and `_render()` with `self._effective_difference_index`. **Do not** change the uses in `_open`, `_clear`, `set_difference_index` or `_decline_difference` — those manage the stored mode itself, not the rendering of it.

- [ ] **Step 4: Add the banner**

In `__init__`, in the toolbar row, immediately after `self.difference_label`:

```python
        self.preview_label = QLabel("")
        bar.addWidget(self.preview_label)
```

- [ ] **Step 5: Factor the shared view configuration out of `_open`**

`_open` currently does two things: it resets the difference view and forgets the previous line's cursor, and it configures the view for a line. A preview needs only the second. Extract it verbatim — do not retype it — as:

```python
    def _show_line(self, key: str) -> None:
        """Configure the view for `key`: title, direction, axes, image,
        channels, velocity. Shared by `_open` (the working line) and
        `_enter_preview`. Deliberately does NOT touch the difference view
        or the cursor/selection: those differ between the two callers,
        which is the whole reason this is a separate method."""
        line = self.session.line_for_key(key)
        label = getattr(line.placement, "label", None) or line.path.stem
        self.setWindowTitle(f"nsgeo Profile · {label} · {line.n_traces} traces")
        self.view.set_direction(int(getattr(line.placement, "direction", 1)))
        self.image = None
        profiles = self.session.profiles_for(key)
        if profiles:
            self._configure_channels(len(profiles))
            self._render()
        else:
            self.channel_combo.hide()
            self.view.set_axes(
                line.n_traces,
                line.header.n_samples,
                line.header.position_ns,
                line.header.dt_ns,
                self._safe_distance(line),
            )
            self.view.set_image(None)
        self._refresh_velocity()
```

`_open`'s body after `self._working_key = key or None` becomes:

```python
        self._preview_key = None
        self.preview_label.setText("")
        if not key:
            self._clear_view_only()
            return
        # C1: open_line resets the session's cursor and selection without
        # emitting for that reset, and set_axes touches neither -- cleared
        # explicitly so the previous line's cursor does not carry across.
        self.view.set_cursor(-1)
        self.view.clear_selection()
        self._show_line(key)
```

Keep the existing C1 comment block that sits above those two view calls; it explains exactly this.

- [ ] **Step 6: Add the preview slot**

```python
    def _on_preview_changed(self, key: str, trace: int) -> None:
        try:
            if key and key != self._working_key:
                self._enter_preview(key, trace)
            else:
                # Either the preview was cleared, or the pointer is over
                # the line already being worked on -- which is not a
                # preview at all: showing a banner and hiding the gain
                # strip for the line the user is editing would be pure
                # noise, and a re-render of what is already on screen.
                self._exit_preview()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not show the preview of {key!r}: {exc}", Qgis.MessageLevel.Critical)

    def _enter_preview(self, key: str, trace: int) -> None:
        if self._preview_key is None:
            self._strip_was_visible = self.gain_strip.isVisible()
        self._preview_key = key
        self.gain_strip.hide()
        self.difference_label.setText("")
        line = self.session.line_for_key(key)
        label = getattr(line.placement, "label", None) or line.path.stem
        self.preview_label.setText(f"Preview: {label} — select it on the map to work on it")
        self._show_line(key)
        self.view.clear_selection()
        self.view.set_cursor(trace)

    def _exit_preview(self) -> None:
        if self._preview_key is None:
            return
        self._preview_key = None
        self.preview_label.setText("")
        if self._working_key is None:
            self._clear_view_only()
            return
        self._show_line(self._working_key)
        self.view.set_cursor(self.session.current_trace)
        start, end = self.session.selection
        if start < 0 or end < 0:
            self.view.clear_selection()
        else:
            self.view.set_selection(start, end)
        if self._strip_was_visible:
            self.gain_strip.show()
        self._strip_was_visible = False
```

`_strip_was_visible` is captured only on the *first* `_enter_preview` of a run: hovering straight from one line to another re-enters without an intervening exit, and re-reading the (now hidden) strip would lose the memory that it had been showing.

Connect it in `__init__` beside the other session connections:

```python
        session.preview_changed.connect(self._on_preview_changed)
```

- [ ] **Step 6b: Refuse to author a pick while previewing**

`_pick` (profile_dock.py:578) emits `self.pick_requested.emit(self._key, trace, time_ns)`, and `self._key` is now the *displayed* line. Nothing consumes that signal today, so M7 ships no defect — but M8 connects it to `session.add_pick`, and it would then author a pick on a line the user only hovered over. Spec §4.3: "Picking targets the **working line**, never a preview." Guard it in the task that creates the hazard, not in the one that would trip over it.

Add as the first statement of `_pick`'s body, before the existing guard:

```python
        if self._preview_key is not None:
            # A preview never authors data (spec §3.3, §4.3). `self._key`
            # is the DISPLAYED line, so without this a shift-click on a
            # previewed radargram would emit a pick for a line the user
            # only hovered. Nothing consumes pick_requested until M8 --
            # this is guarded here, in the change that makes `_key` mean
            # "displayed", rather than left for M8 to discover.
            return
```

And the test:

```python
def test_a_shift_click_on_a_preview_authors_no_pick(previewing):
    dock, session, keys = previewing
    emitted = []
    dock.pick_requested.connect(lambda k, t, ns: emitted.append((k, t, ns)))
    session.set_preview(keys[1], 5)

    dock.view.pick_requested.emit(20, 15.0)

    assert emitted == []
```

**Note — no guard is needed on `_hovered`.** Hovering the profile during a preview calls `session.set_trace(self._key, trace)` with `_key` = the previewed line, and `set_trace` returns early because that is not `current_key`. The safety is structural, not a check that could be forgotten. The test asserts it anyway.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py packages/nsgeo-qgis/tests/qgis/test_plugin_gain_strip.py packages/nsgeo-qgis/tests/qgis/test_plugin_difference_presets.py -q -p no:xonsh`

Expected: PASS, including every pre-existing test in all three files.

- [ ] **Step 8: Run both tiers and the linters, then commit**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
.venv/bin/ruff check . && .venv/bin/ruff format --check .
git add packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py
git commit -m "feat: render the previewed line, and say that it is a preview

The dock's _key becomes the DISPLAYED line, so every read site means the
right thing without edits. The gain strip and the difference view stay
bound to the working line and hide while a preview is up: the strip writes
on drag, and a curve belonging to a line that is not on screen is exactly
the C2 configuration.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `MapLink` — the profile drawn onto the map

Marker and band only. Hover comes in Task 4, promotion in Task 5, so this task ends with a link that is already useful: drag a selection in the profile and watch it light up on the map.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/map_link.py`
- Test: create `packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py`

**Interfaces:**
- Consumes (Tasks 1-2): `session.trace_changed`, `session.selection_changed`, `session.preview_changed`, `session.line_opened`, `session.lines_changed`, `session.grids_changed`, `session.site_closed`, `session.display_key`, `session.preview_key`, `session.preview_trace`, `session.current_trace`, `session.selection`; `SiteLayers.layers` (a `dict[str, QgsVectorLayer]`, key `"lines"`).
- Produces:
  - `MapLink(session: SiteSession, layers: SiteLayers, canvas: QgsMapCanvas, parent: QObject | None = None)`
  - `MapLink.dispose() -> None` — idempotent
  - `MapLink._geometries() -> dict[str, QgsGeometry]` — line geometries **in canvas CRS**, keyed by `line_key` (Task 4 hit-tests against these)
  - `MapLink._invalidate() -> None`
  - Module constants `MARKER_COLOUR`, `BAND_COLOUR`

**Verified API facts** (probed against QGIS 3.44.7 in this worktree — do not re-derive):
- `QgsGeometry.closestVertexWithContext(pt)` returns `(sqrDist, vertexIndex)`. The distance is **squared**.
- `QgsGeometry.vertexAt(i)` returns a `QgsPoint`, **not** a `QgsPointXY` — wrap it: `QgsPointXY(geom.vertexAt(i))`.
- `QgsVertexMarker.setCenter(pt)` takes map (canvas CRS) coordinates.
- `QgsRubberBand.setToGeometry(geom, layer)` — passing `None` for `layer` means "already in canvas CRS, do not transform".
- Constructing a `QgsVertexMarker(canvas)` or `QgsRubberBand(canvas, ...)` adds exactly one item to `canvas.scene()`; `scene().removeItem(item)` takes it back off. An empty canvas's scene already holds 1 item, so assert on deltas, never absolutes.
- `refill_lines` writes one geometry vertex per trace (`_line_points` → `Line.trace_coords`), so **vertex index == trace index**. That equality is the whole reason this module needs no coordinate maths of its own.

**Deviation from spec §3.1, deliberate.** The spec says a trace's world position is `Line.trace_coords(frames)[index]` transformed to the canvas CRS. This module reads the `lines` layer's own geometry vertex instead. It is the *same value by a cheaper route* — `refill_lines` computed it with exactly that call — and it is strictly better in two ways: the marker is guaranteed to sit on the line as drawn rather than on a recomputation that could drift from it, and an unplaceable line (a time-triggered acquisition, which `trace_coords` raises `ValueError` for) is simply absent from the layer and therefore absent here, with no second error path to handle.

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py`:

```python
"""MapLink: the map <-> profile link (M7, spec §3)."""

from __future__ import annotations

import pytest
from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.layers import SiteLayers
from nsgeo_qgis.map_link import MapLink
from nsgeo_qgis.session import SiteSession
from plugin_testing import REAL_DZT, needs_real_data, synthetic_dzt
from qgis.core import QgsGeometry, QgsPointXY, QgsProject
from qgis.gui import QgsMapCanvas

GRID = Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5)


@pytest.fixture
def linked(qgis_app, tmp_path):
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    session.add_grid(GRID)
    lines = []
    for i in range(2):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", i * 2.0, 0.0, 1, p.stem)))
    session.add_lines(lines)
    canvas = QgsMapCanvas()
    canvas.setDestinationCrs(layers.crs())
    link = MapLink(session, layers, canvas)
    keys = session.keys()
    session.open_line(keys[0])
    yield link, session, layers, canvas, keys
    link.dispose()
    layers.detach()
    project.clear()


def _vertex(link, key, i):
    return QgsPointXY(link._geometries()[key].vertexAt(i))


def test_the_marker_sits_on_the_traces_own_vertex(linked):
    link, session, _layers, _canvas, keys = linked

    session.set_trace(keys[0], 10)

    want = _vertex(link, keys[0], 10)
    assert link._marker.isVisible()
    assert link._marker.center().distance(want) < 1e-6


def test_the_band_spans_the_selected_traces(linked):
    link, session, _layers, _canvas, keys = linked

    session.set_selection(keys[0], 4, 9)

    assert link._band.numberOfVertices() == 6  # 4..9 inclusive


def test_clearing_the_selection_empties_the_band(linked):
    link, session, _layers, _canvas, keys = linked
    session.set_selection(keys[0], 4, 9)

    session.clear_selection()

    assert link._band.numberOfVertices() == 0


def test_the_marker_follows_the_preview_not_the_working_line(linked):
    link, session, _layers, _canvas, keys = linked
    session.set_trace(keys[0], 10)

    session.set_preview(keys[1], 3)

    want = _vertex(link, keys[1], 3)
    assert link._marker.center().distance(want) < 1e-6


def test_hovering_the_working_line_keeps_its_own_selection_band(linked):
    """`preview_key == current_key` is reachable and emits, and it means
    the pointer is over the line already being worked on -- not a preview.
    Testing `preview_key is not None` alone blanks that line's own band."""
    link, session, _layers, _canvas, keys = linked
    session.set_selection(keys[0], 4, 9)

    session.set_preview(keys[0], 3)

    assert link._band.numberOfVertices() == 6
    assert link._marker.isVisible()


def test_a_preview_shows_no_selection_band(linked):
    link, session, _layers, _canvas, keys = linked
    session.set_selection(keys[0], 4, 9)

    session.set_preview(keys[1], 3)

    assert link._band.numberOfVertices() == 0


def test_snapping_back_restores_the_working_lines_marker_and_band(linked):
    link, session, _layers, _canvas, keys = linked
    session.set_trace(keys[0], 10)
    session.set_selection(keys[0], 4, 9)

    session.set_preview(keys[1], 3)
    session.clear_preview()

    assert link._marker.center().distance(_vertex(link, keys[0], 10)) < 1e-6
    assert link._band.numberOfVertices() == 6


def test_closing_the_site_hides_both_items(linked):
    link, session, _layers, _canvas, keys = linked
    session.set_trace(keys[0], 10)
    session.set_selection(keys[0], 4, 9)

    session.close_site()

    assert not link._marker.isVisible()
    assert link._band.numberOfVertices() == 0


def test_dispose_takes_both_items_off_the_scene_and_is_idempotent(qgis_app, tmp_path):
    """I4's lesson: a QgsMapCanvasItem is owned by the canvas SCENE, and
    nothing removes it when the Python wrapper goes away."""
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    canvas = QgsMapCanvas()
    before = len(canvas.scene().items())

    link = MapLink(session, layers, canvas)
    assert len(canvas.scene().items()) == before + 2

    link.dispose()
    assert len(canvas.scene().items()) == before

    link.dispose()  # must not raise
    assert len(canvas.scene().items()) == before
    layers.detach()
    project.clear()


def test_the_geometry_cache_is_rebuilt_after_the_lines_change(linked):
    link, session, _layers, _canvas, keys = linked
    link._geometries()  # populate
    assert link._geoms is not None

    session.remove_line(keys[1])

    assert link._geoms is None
    assert keys[1] not in link._geometries()


def test_geometries_are_transformed_into_canvas_crs(linked):
    """Hit testing (Task 4) measures its tolerance in canvas units, so the
    cache must already be transformed -- not left in the layer's CRS.

    Asserting against a DIFFERENT canvas CRS is the only version of this
    test that can fail: with the canvas on the layer's own CRS the
    transform is a no-op and an untransformed cache looks identical."""
    from qgis.core import QgsCoordinateReferenceSystem

    link, _session, layers, canvas, keys = linked
    in_layer_crs = QgsPointXY(link._geometries()[keys[0]].vertexAt(0))

    canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    link._invalidate()
    in_wgs84 = QgsPointXY(link._geometries()[keys[0]].vertexAt(0))

    assert abs(in_wgs84.x()) <= 180.0 and abs(in_wgs84.y()) <= 90.0
    assert in_wgs84.distance(in_layer_crs) > 1.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py -q -p no:xonsh`

Expected: FAIL at collection — `ModuleNotFoundError: No module named 'nsgeo_qgis.map_link'`.

- [ ] **Step 3: Write `map_link.py`**

Create `packages/nsgeo-qgis/nsgeo_qgis/map_link.py`:

```python
"""MapLink: the map <-> profile link.

Deliberately NOT a QgsMapTool, which is why this module does not live in
`maptools/`. A map tool claims the canvas: while it is active the user
loses pan, identify and select, which is the wrong trade for an always-on
feature. `QgsMapCanvas.xyCoordinates` fires on mouse move regardless of
the active tool (verified against QGIS 3.44 with no tool set and with
QgsMapToolPan active), and a QgsVertexMarker attaches to the canvas scene
without owning the tool -- so the whole link coexists with whatever the
user is already doing.

Clicks are deliberately not intercepted. Catching one ambiently means an
event filter on the canvas viewport adjudicating every click in QGIS
against the active tool -- the same shape as the Plan 2 bug where a
right-click committed a left-drag selection in the profile. Selection
gives us a deliberate gesture for free instead (see `_on_selection`).

Every slot here catches its own exceptions: PyQt cannot propagate an
exception out of a slot invoked from C++, this build prints it and carries
on, and the CI container routes it to qFatal(). See `session.py`.
"""

from __future__ import annotations

from typing import Any

from qgis.core import (
    Qgis,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsMessageLog,
    QgsPointXY,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsMapCanvas, QgsRubberBand, QgsVertexMarker
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QObject
from qgis.PyQt.QtGui import QColor

from .layers import SiteLayers
from .session import SiteSession

MARKER_COLOUR = QColor("#e67e22")
BAND_COLOUR = QColor("#e67e22")
MARKER_SIZE_PX = 9
BAND_WIDTH_PX = 3


def _log(message: str, level: Qgis.MessageLevel = Qgis.MessageLevel.Warning) -> None:
    QgsMessageLog.logMessage(message, "nsgeo", level)


class MapLink(QObject):
    def __init__(
        self,
        session: SiteSession,
        layers: SiteLayers,
        canvas: QgsMapCanvas,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.layers = layers
        self.canvas = canvas

        self._marker: QgsVertexMarker | None = QgsVertexMarker(canvas)
        self._marker.setIconType(QgsVertexMarker.ICON_CROSS)
        self._marker.setColor(MARKER_COLOUR)
        self._marker.setIconSize(MARKER_SIZE_PX)
        self._marker.setPenWidth(2)
        self._marker.setVisible(False)

        self._band: QgsRubberBand | None = QgsRubberBand(canvas, QgsWkbTypes.LineGeometry)
        self._band.setColor(BAND_COLOUR)
        self._band.setWidth(BAND_WIDTH_PX)

        # None means "not built". Holds every line's geometry already
        # transformed into the CANVAS's CRS, so neither the marker nor the
        # hit test has to transform anything per mouse move, and the hover
        # tolerance -- which is a pixel count times mapUnitsPerPixel -- is
        # in the same units as the distances it is compared against.
        self._geoms: dict[str, QgsGeometry] | None = None

        for signal in (
            session.trace_changed,
            session.selection_changed,
            session.preview_changed,
            session.line_opened,
        ):
            signal.connect(self._on_session_changed)
        for signal in (session.lines_changed, session.grids_changed, session.site_opened):
            signal.connect(self._on_lines_changed)
        session.site_closed.connect(self._on_lines_changed)
        canvas.destinationCrsChanged.connect(self._on_lines_changed)

    # ---- cache ------------------------------------------------------------
    def _invalidate(self) -> None:
        self._geoms = None

    def _geometries(self) -> dict[str, QgsGeometry]:
        if self._geoms is not None:
            return self._geoms
        geoms: dict[str, QgsGeometry] = {}
        layer = self._lines_layer()
        if layer is not None:
            tr = self._transform(layer)
            for feature in layer.getFeatures():
                # A copy: the QgsFeature the iterator yields is reused, so
                # its geometry must not be held by reference.
                geom = QgsGeometry(feature.geometry())
                if tr is not None:
                    geom.transform(tr)
                geoms[str(feature["line_key"])] = geom
        self._geoms = geoms
        return geoms

    def _lines_layer(self) -> QgsVectorLayer | None:
        layer = self.layers.layers.get("lines")
        if layer is None or sip.isdeleted(layer):
            return None
        return layer

    def _transform(self, layer: QgsVectorLayer) -> QgsCoordinateTransform | None:
        dest = self.canvas.mapSettings().destinationCrs()
        source = layer.crs()
        if not dest.isValid() or not source.isValid() or source == dest:
            return None
        return QgsCoordinateTransform(source, dest, QgsProject.instance())

    # ---- drawing ----------------------------------------------------------
    def _on_lines_changed(self, *_: Any) -> None:
        try:
            self._invalidate()
            self._refresh()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not rebuild the map link: {exc}", Qgis.MessageLevel.Critical)

    def _on_session_changed(self, *_: Any) -> None:
        try:
            self._refresh()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not update the map link: {exc}", Qgis.MessageLevel.Critical)

    def _refresh(self) -> None:
        """Redraw both items from the session, whatever changed.

        Every signal lands here rather than each one updating its own item:
        the marker and the band both depend on which line is displayed AND
        on whether that line is a preview, so per-signal updates would have
        to re-derive the same answer in four places and could disagree.
        """
        if self._marker is None or self._band is None:
            return  # disposed
        key = self.session.display_key if self.session.is_open else None
        if key is None:
            self._marker.setVisible(False)
            self._band.reset(QgsWkbTypes.LineGeometry)
            return
        # `preview_key == current_key` is reachable -- the session allows
        # it and emits for it -- and it means the pointer is over the line
        # already being worked on, which is not a preview at all. Testing
        # `preview_key is not None` alone would blank that line's own
        # selection band the moment the pointer crossed it. ProfileDock
        # draws the same distinction in `_on_preview_changed`; the two must
        # agree or the map and the profile disagree about what is showing.
        previewing = self.session.preview_key not in (None, self.session.current_key)
        if previewing:
            self._set_marker(key, self.session.preview_trace)
            # A preview has no selection of its own, and the working
            # line's selection belongs to a line that is not on screen.
            self._band.reset(QgsWkbTypes.LineGeometry)
            return
        self._set_marker(key, self.session.current_trace)
        self._set_band(key, *self.session.selection)

    def _set_marker(self, key: str, trace: int) -> None:
        assert self._marker is not None
        geom = self._geometries().get(key)
        if geom is None or trace < 0 or trace >= self._n_vertices(geom):
            self._marker.setVisible(False)
            return
        self._marker.setCenter(QgsPointXY(geom.vertexAt(trace)))
        self._marker.setVisible(True)

    def _set_band(self, key: str, start: int, end: int) -> None:
        assert self._band is not None
        geom = self._geometries().get(key)
        if geom is None or start < 0 or end < 0:
            self._band.reset(QgsWkbTypes.LineGeometry)
            return
        n = self._n_vertices(geom)
        lo = max(0, min(start, end))
        hi = min(n - 1, max(start, end))
        if lo > hi:
            self._band.reset(QgsWkbTypes.LineGeometry)
            return
        points = [QgsPointXY(geom.vertexAt(i)) for i in range(lo, hi + 1)]
        # layer=None: the cache is already in canvas CRS, so asking for a
        # transform here would apply one twice.
        self._band.setToGeometry(QgsGeometry.fromPolylineXY(points), None)

    @staticmethod
    def _n_vertices(geom: QgsGeometry) -> int:
        part = geom.constGet()
        return 0 if part is None else int(part.numPoints())

    # ---- teardown ---------------------------------------------------------
    def dispose(self) -> None:
        """Take both canvas items back off the scene, for good.

        Item I4 in Plan 2's final fix round: a QgsMapCanvasItem is owned by
        the canvas's QGraphicsScene, not by the Python wrapper, so dropping
        the reference leaks the item for the life of the QGIS session --
        the objects implicated in a shutdown segfault "once enough of them
        pile up alongside a QgsMapCanvas".

        Idempotent, because more than one finaliser can reach the same
        link. `item.scene()` rather than `self.canvas.scene()`: it removes
        the item from whatever scene actually holds it, and does not
        assume the canvas is still alive.
        """
        items, self._marker, self._band = (self._marker, self._band), None, None
        for item in items:
            if item is None or sip.isdeleted(item):
                continue
            scene = item.scene()
            if scene is not None:
                # removeItem() hands ownership back to us, so dropping the
                # last reference (done above) is what actually frees it.
                scene.removeItem(item)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py -q -p no:xonsh`

Expected: PASS, 11 tests.

- [ ] **Step 5: Verify the boundary test still passes**

`packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py` asserts the plugin never imports `nsgeo.processing` internals. `map_link.py` imports none, but run it explicitly — the test enumerates plugin modules, so a new file is newly in scope:

Run: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_plugin_boundary.py -q -p no:xonsh`

Expected: PASS.

- [ ] **Step 6: Run both tiers and the linters, then commit**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
.venv/bin/ruff check . && .venv/bin/ruff format --check .
git add packages/nsgeo-qgis/nsgeo_qgis/map_link.py packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py
git commit -m "feat: draw the profile's cursor and selection on the map

MapLink owns a vertex marker and a rubber band and redraws both from the
session. refill_lines writes one geometry vertex per trace, so the vertex
index IS the trace index and this module needs no coordinate maths.

Geometries are cached already transformed into canvas CRS: the hover
tolerance in Task 4 is a pixel count times mapUnitsPerPixel, and it has to
be compared against distances in the same units.

dispose() takes both items off the scene. I4 showed that nothing else will.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Ambient hover previews the line under the pointer

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/map_link.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/loader.py`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py` (append)

**Interfaces:**
- Consumes (Tasks 1, 3): `session.set_preview`, `session.clear_preview`, `MapLink._geometries()`.
- Produces:
  - `MapLink.HOVER_DWELL_MS = 100`, `MapLink.HOVER_TOLERANCE_PX = 12` (module constants)
  - `MapLink._hit_test(point: QgsPointXY) -> tuple[str, int] | None`
  - `MapLink._dwell: QTimer` (single-shot)
  - `LineLoader._on_preview_changed(key: str, trace: int) -> None`

- [ ] **Step 1: Write the failing tests**

**First, restore two imports.** Task 3 legitimately removed `REAL_DZT` and `needs_real_data` from this module — nothing there used them, and ruff flagged them. The real-data test below is their first consumer, so put them back:

```python
from plugin_testing import REAL_DZT, needs_real_data, synthetic_dzt
```

Then append to `packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py`:

```python
# ---- ambient hover (spec §3.2) ----------------------------------------------


def _fire_dwell(link):
    """Drive the dwell timer deterministically instead of waiting on it."""
    link._dwell.timeout.emit()


def test_hovering_a_line_previews_it_at_the_hovered_trace(linked):
    link, session, _layers, canvas, keys = linked
    target = QgsPointXY(link._geometries()[keys[1]].vertexAt(7))

    canvas.xyCoordinates.emit(target)
    _fire_dwell(link)

    assert session.preview_key == keys[1]
    assert session.preview_trace == 7


def test_hover_never_moves_the_working_line(linked):
    """The headline guard of the whole design (spec §3.3)."""
    link, session, _layers, canvas, keys = linked
    opened = []
    session.line_opened.connect(opened.append)
    target = QgsPointXY(link._geometries()[keys[1]].vertexAt(7))

    canvas.xyCoordinates.emit(target)
    _fire_dwell(link)

    assert session.current_key == keys[0]
    assert opened == []


def test_hovering_the_working_line_moves_its_cursor_not_a_preview(linked):
    """Ruling 12: the working line's cursor IS `current_trace`. Routing a
    hover over it through `set_preview` would give one line two sources of
    truth for one cursor, and the map marker would stop following a drag
    in the profile."""
    link, session, _layers, canvas, keys = linked
    target = QgsPointXY(link._geometries()[keys[0]].vertexAt(11))

    canvas.xyCoordinates.emit(target)
    _fire_dwell(link)

    assert session.preview_key is None
    assert session.current_trace == 11
    assert session.current_key == keys[0]


def test_hovering_the_working_line_ends_a_preview_of_another(linked):
    link, session, _layers, canvas, keys = linked
    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[keys[1]].vertexAt(7)))
    _fire_dwell(link)
    assert session.preview_key == keys[1]

    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[keys[0]].vertexAt(11)))
    _fire_dwell(link)

    assert session.preview_key is None
    assert session.current_trace == 11


def test_hovering_away_from_every_line_clears_the_preview(linked):
    link, session, _layers, canvas, keys = linked
    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[keys[1]].vertexAt(7)))
    _fire_dwell(link)
    assert session.preview_key == keys[1]

    canvas.xyCoordinates.emit(QgsPointXY(999_999.0, 999_999.0))
    _fire_dwell(link)

    assert session.preview_key is None


def test_the_preview_waits_for_the_dwell(linked):
    link, session, _layers, canvas, keys = linked
    target = QgsPointXY(link._geometries()[keys[1]].vertexAt(7))

    canvas.xyCoordinates.emit(target)

    assert session.preview_key is None  # not yet -- the timer has not fired
    assert link._dwell.isActive()


def test_only_the_last_position_of_a_sweep_is_used(linked):
    link, session, _layers, canvas, keys = linked

    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[keys[0]].vertexAt(2)))
    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[keys[1]].vertexAt(7)))
    _fire_dwell(link)

    assert session.preview_key == keys[1]
    assert session.preview_trace == 7


def test_the_dwell_timer_really_fires_on_its_own(linked):
    """The other hover tests drive the timer by hand; this one proves the
    timer is actually started and connected."""
    from qgis.PyQt.QtTest import QTest

    link, session, _layers, canvas, keys = linked
    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[keys[1]].vertexAt(7)))

    QTest.qWait(link.HOVER_DWELL_MS * 4)

    assert session.preview_key == keys[1]


def test_the_tolerance_is_a_distance_not_a_squared_distance(linked):
    """closestVertexWithContext returns a SQUARED distance, so the tolerance
    must be squared to match it.

    The discriminating probe is a HIT, not a miss. With mapUnitsPerPixel()
    == 1.0 the tolerance is 12 map units and 12 > sqrt(12), so comparing
    the squared distance against a RAW tolerance is *stricter* than
    correct, not looser: it rejects past 3.46 m where the correct
    comparison rejects past 12 m. A miss test therefore passes under both
    spellings and proves nothing. Hovering inside the real tolerance but
    outside sqrt(tolerance) separates them."""
    link, session, _layers, canvas, keys = linked
    tol = canvas.mapUnitsPerPixel() * link.HOVER_TOLERANCE_PX
    assert tol > 1.0, "the discriminating band exists only while tol > sqrt(tol)"
    on = link._geometries()[keys[1]].vertexAt(7)
    near = QgsPointXY(on.x() + tol * 0.8, on.y())

    canvas.xyCoordinates.emit(near)
    _fire_dwell(link)

    assert session.preview_key is not None


def test_hover_with_no_site_open_does_nothing(qgis_app, tmp_path):
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    layers = SiteLayers(session, project=project)
    canvas = QgsMapCanvas()
    link = MapLink(session, layers, canvas)

    canvas.xyCoordinates.emit(QgsPointXY(1.0, 2.0))
    link._dwell.timeout.emit()  # must not raise

    assert session.preview_key is None
    link.dispose()
    project.clear()


@needs_real_data
def test_hovering_a_real_line_previews_its_real_trace(qgis_app, tmp_path):
    """Spec §7: real data is the primary validation. The synthetic fixtures
    above all use one synthetic header; a real GSSI file has its own
    traces_per_metre and trace count, and those are what turn a pointer
    position into a trace index."""
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    session.add_grid(GRID)
    line = Line.open(REAL_DZT[0], GridPlacement("A", "y", 0.0, 0.0, 1, "real"))
    session.add_lines([line])
    canvas = QgsMapCanvas()
    canvas.setDestinationCrs(layers.crs())
    link = MapLink(session, layers, canvas)
    key = session.keys()[0]
    session.open_line(key)

    want = line.n_traces // 3
    canvas.xyCoordinates.emit(QgsPointXY(link._geometries()[key].vertexAt(want)))
    link._dwell.timeout.emit()

    # The working line is the only line, so the preview is a no-op on the
    # dock -- what is being asserted is that the hit test resolved a real
    # file's geometry to the right trace index.
    assert link._hit_test(QgsPointXY(link._geometries()[key].vertexAt(want))) == (key, want)
    assert session.current_key == key
    link.dispose()
    layers.detach()
    project.clear()


def test_a_previewed_line_is_requested_from_the_loader(linked, monkeypatch):
    from nsgeo_qgis.loader import LineLoader

    link, session, _layers, canvas, keys = linked
    asked: list[str] = []
    loader = LineLoader(session, on_error=lambda k, m: None)
    monkeypatch.setattr(loader, "request", asked.append)

    session.set_preview(keys[1], 7)

    assert asked == [keys[1]]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py -q -p no:xonsh -k "hover or dwell or tolerance or loader or sweep or working or real"`

Expected: FAIL — `AttributeError: 'MapLink' object has no attribute '_dwell'`.

- [ ] **Step 3: Add the hover machinery to `MapLink`**

Add the constants beside `MARKER_COLOUR`:

```python
# Sweeping the map must not thrash the renderer: a preview commits only
# once the pointer has settled for this long.
HOVER_DWELL_MS = 100
# How close the pointer must come to a line before it counts as hovering
# it, in SCREEN pixels -- converted to map units per event, so the feel
# does not change with zoom.
HOVER_TOLERANCE_PX = 12
```

Expose them on the class so tests and future callers read one name:

```python
class MapLink(QObject):
    HOVER_DWELL_MS = HOVER_DWELL_MS
    HOVER_TOLERANCE_PX = HOVER_TOLERANCE_PX
```

Extend the `QtCore` import to `from qgis.PyQt.QtCore import QObject, QTimer`.

In `__init__`, after the geometry cache is declared:

```python
        self._last_point: QgsPointXY | None = None
        self._dwell = QTimer(self)
        self._dwell.setSingleShot(True)
        self._dwell.timeout.connect(self._on_dwell)
        canvas.xyCoordinates.connect(self._on_xy)
```

And the slots:

```python
    # ---- ambient hover ----------------------------------------------------
    def _on_xy(self, point: QgsPointXY) -> None:
        """Fired on every mouse move over the canvas, whatever tool is
        active -- that is the whole reason this feature needs no tool slot.
        Cheap on purpose: it records a position and restarts the dwell."""
        try:
            self._last_point = QgsPointXY(point)
            self._dwell.start(self.HOVER_DWELL_MS)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not track the pointer: {exc}", Qgis.MessageLevel.Critical)

    def _on_dwell(self) -> None:
        try:
            point = self._last_point
            if point is None or not self.session.is_open:
                return
            hit = self._hit_test(point)
            if hit is None:
                # Clearing goes through the same dwell as previewing, so
                # crossing a gap between two lines does not flicker the
                # profile back to the working line and out again.
                self.session.clear_preview()
                return
            key, trace = hit
            if key == self.session.current_key:
                # The pointer is over the line already being worked on,
                # which is NOT a preview. The working line's cursor is
                # `current_trace`; routing it through `set_preview` would
                # give one line two sources of truth for one cursor, and
                # the map marker would then stop following a drag in the
                # profile. Any preview in progress ends here.
                self.session.clear_preview()
                self.session.set_trace(key, trace)
            else:
                self.session.set_preview(key, trace)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not preview the hovered line: {exc}", Qgis.MessageLevel.Critical)

    def _hit_test(self, point: QgsPointXY) -> tuple[str, int] | None:
        """The (line_key, trace) under `point`, or None if nothing is close
        enough. `point` is in canvas CRS, and so is the geometry cache.

        `closestVertexWithContext` returns a SQUARED distance, so the
        tolerance is squared to match rather than the distance rooted --
        getting this backwards silently widens the hit radius by 12x and
        is invisible to any test that hovers exactly on a line.

        Nearest *vertex* rather than nearest point on the segment: the
        vertex index is the trace index, which is the answer being asked
        for, and traces are centimetres apart, so the two differ by less
        than the pointer's own precision.
        """
        tolerance = self.canvas.mapUnitsPerPixel() * self.HOVER_TOLERANCE_PX
        limit = tolerance * tolerance
        best: tuple[float, str, int] | None = None
        for key, geom in self._geometries().items():
            if geom.isEmpty():
                continue
            sq_dist, index = geom.closestVertexWithContext(point)
            if index < 0 or sq_dist > limit:
                continue
            if best is None or sq_dist < best[0]:
                best = (sq_dist, key, index)
        return None if best is None else (best[1], best[2])
```

Add `self._dwell.stop()` as the first line of `dispose()` (Task 5 gives that method its final form).

- [ ] **Step 4: Let the loader load a previewed line**

In `loader.py`'s `__init__`, beside the existing `session.line_opened.connect(...)`:

```python
        session.preview_changed.connect(self._on_preview_changed)
```

And next to `_on_line_opened`:

```python
    def _on_preview_changed(self, key: str, _trace: int) -> None:
        """A previewed line needs its samples too -- the first preview of a
        line pays the async load, and the session's profile cache makes
        every later one instant. Same guarded path as an opened line: the
        empty key is the cleared sentinel and asks for nothing."""
        self._on_line_opened(key)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py packages/nsgeo-qgis/tests/qgis/test_plugin_loader.py -q -p no:xonsh`

Expected: PASS.

- [ ] **Step 6: Run both tiers and the linters, then commit**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
.venv/bin/ruff check . && .venv/bin/ruff format --check .
git add packages/nsgeo-qgis/nsgeo_qgis/map_link.py packages/nsgeo-qgis/nsgeo_qgis/loader.py packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py
git commit -m "feat: preview the line under the pointer, without a map tool

xyCoordinates fires whatever tool owns the canvas, so hovering costs no
tool slot and the user keeps pan, identify and select. A 100ms dwell keeps
a sweep from thrashing the renderer; clearing waits for the same dwell so
crossing a gap between lines does not flicker.

closestVertexWithContext returns a SQUARED distance -- the tolerance is
squared to match, with a test that fails if that is ever reversed.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Selection promotes, the plugin wires it up, and no new orphans

The deliberate gesture that turns a preview into the working line, the plugin wiring that makes any of this reachable from QGIS, and the standing check from spec §6.

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/map_link.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (`initGui` ~line 148, `unload` ~line 270)
- Modify: `packages/nsgeo-qgis/README.md`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py` (append), `packages/nsgeo-qgis/tests/qgis/test_plugin_loads.py` (append)
- Test: create `packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py`

**Interfaces:**
- Consumes (Tasks 1-4): everything above; `session.open_line`, `session.keys()`.
- Produces: `MapLink._on_selection(selected, deselected, clear_and_select)`; `NsgeoPlugin.map_link: MapLink | None`.

- [ ] **Step 1: Write the failing tests**

Append to `packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py`:

```python
# ---- selection promotes (spec §3.4) -----------------------------------------


def _feature_id(layers, key):
    layer = layers.layers["lines"]
    for f in layer.getFeatures():
        if str(f["line_key"]) == key:
            return f.id()
    raise AssertionError(f"no feature for {key!r}")


def test_selecting_one_line_makes_it_the_working_line(linked):
    link, session, layers, _canvas, keys = linked
    assert session.current_key == keys[0]

    layers.layers["lines"].selectByIds([_feature_id(layers, keys[1])])

    assert session.current_key == keys[1]


def test_promotion_goes_through_open_line_so_it_cannot_diverge(linked):
    link, session, layers, _canvas, keys = linked
    opened = []
    session.line_opened.connect(opened.append)

    layers.layers["lines"].selectByIds([_feature_id(layers, keys[1])])

    assert opened == [keys[1]]


def test_selecting_several_lines_promotes_none(linked):
    link, session, layers, _canvas, keys = linked

    layers.layers["lines"].selectByIds(
        [_feature_id(layers, keys[0]), _feature_id(layers, keys[1])]
    )

    assert session.current_key == keys[0]


def test_deselecting_everything_promotes_nothing(linked):
    link, session, layers, _canvas, keys = linked
    layer = layers.layers["lines"]
    layer.selectByIds([_feature_id(layers, keys[1])])

    layer.removeSelection()

    assert session.current_key == keys[1]  # unchanged by the deselect


def test_promotion_still_works_after_the_lines_layer_is_rebuilt(linked):
    """refill_lines replaces the layer's features; a connection made once
    at construction and never renewed would silently stop promoting."""
    link, session, layers, _canvas, keys = linked
    layers.refresh()

    layers.layers["lines"].selectByIds([_feature_id(layers, keys[1])])

    assert session.current_key == keys[1]
```

Append to `packages/nsgeo-qgis/tests/qgis/test_plugin_loads.py`:

```python
def test_the_plugin_builds_and_disposes_its_map_link(fake_iface):
    from nsgeo_qgis.plugin import NsgeoPlugin

    canvas = fake_iface.mapCanvas()
    before = len(canvas.scene().items())

    plugin = NsgeoPlugin(fake_iface)
    plugin.initGui()
    assert plugin.map_link is not None
    assert len(canvas.scene().items()) == before + 2

    plugin.unload()
    assert plugin.map_link is None
    assert len(canvas.scene().items()) == before
```

Create `packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py`:

```python
"""Spec §6: every declared signal has a consumer.

Plan 2 shipped three APIs with no consumer at all. The cost was not
theoretical: a manual tester went looking for a pick mode, found
`ProfileView.set_pick_mode`, and concluded the build was wrong rather than
that the feature was unbuilt.

A signal with no consumer reads exactly like a working feature from the
emitting side, so the check is to look for the `connect`, never the
`emit`. This lives in the pure tier because it reads source text and needs
no QGIS.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "nsgeo_qgis"

# Declared with no consumer anywhere, each with the reason it survives.
# Anything NOT listed here must have a connect.
#
# NOTE: spec §1's orphan table is incomplete and partly wrong. It lists
# three orphans; the real set is the four below, and `pick_requested` --
# which it lists -- is NOT a name-level orphan at all (see
# test_profile_docks_pick_signal_is_still_unconsumed).
KNOWN_UNCONSUMED = {
    # Adopted by M8, the pick tool (spec §4.1): session.add_pick emits it.
    "picks_changed",
    # Dead API from Plan 2: plugin.py's toolbar actions do New, Open and
    # Save, and SurveyDock's own signals for them were never wired to
    # anything. Deleting them is Plan 2 cleanup, not M7 work -- pulling it
    # in here is the scope creep the 3-6 task rule exists to prevent.
    "new_site_requested",
    "open_site_requested",
    "save_requested",
}


def _sources() -> dict[Path, str]:
    return {p: p.read_text(encoding="utf-8") for p in sorted(PACKAGE.rglob("*.py"))}


def _declared_signals(sources: dict[Path, str]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path, text in sources.items():
        for node in ast.walk(ast.parse(text, filename=str(path))):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            func = node.value.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name != "pyqtSignal":
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = path
    return found


def _connect_count(blob: str, name: str) -> int:
    return len(re.findall(rf"\.{re.escape(name)}\s*\.connect\s*\(", blob))


def test_every_declared_signal_has_a_connect() -> None:
    sources = _sources()
    blob = "\n".join(sources.values())
    orphans = {
        name: path.name
        for name, path in _declared_signals(sources).items()
        if name not in KNOWN_UNCONSUMED and not _connect_count(blob, name)
    }
    assert not orphans, (
        "signals declared with no consumer anywhere in the plugin: "
        f"{orphans}. A signal nothing connects to reads like a working "
        "feature from the emitting side. Either connect it, delete it, or "
        "-- if a later milestone adopts it -- add it to KNOWN_UNCONSUMED "
        "with the reason."
    )


def test_the_known_unconsumed_signals_are_still_unconsumed() -> None:
    """Keeps KNOWN_UNCONSUMED honest: once one is connected it must leave
    the list, or the list stops being a to-do and becomes a permanent
    exemption nobody rereads."""
    blob = "\n".join(_sources().values())
    stale = [name for name in KNOWN_UNCONSUMED if _connect_count(blob, name)]
    assert not stale, f"now consumed -- remove from KNOWN_UNCONSUMED: {stale}"


def test_profile_docks_pick_signal_is_still_unconsumed() -> None:
    """`pick_requested` is declared TWICE -- on ProfileView and on
    ProfileDock -- and only ProfileView's is connected (profile_dock.py
    wires it to `_pick`). A name-keyed check cannot tell them apart, so
    ProfileDock's, which is the real orphan, would be invisible to the
    test above and listing it in KNOWN_UNCONSUMED would make the honesty
    test fail outright.

    Pin the count instead. M8 connecting ProfileDock's signal to
    `session.add_pick` makes it two and trips this test -- which is
    exactly the notification an allowlist entry would have given.
    """
    blob = "\n".join(_sources().values())
    assert _connect_count(blob, "pick_requested") == 1, (
        "the pick_requested connect count changed. If M8 wired "
        "ProfileDock.pick_requested to session.add_pick, that is the "
        "orphan being adopted: raise the expected count to 2 and say so."
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py -q -p no:xonsh -k "select or promot"
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py -q -p no:xonsh
```

Expected: the selection tests FAIL (`assert session.current_key == keys[1]` — nothing promotes). The orphan test FAILS listing `preview_changed` if Tasks 2 and 4 did not connect it, and otherwise PASSES — if it passes here, say so and keep it; a check that is green on arrival is still the check.

- [ ] **Step 3: Promote on selection**

In `map_link.py`'s `__init__`, add `self._lines_layer_bound: QgsVectorLayer | None = None`, and call `self._rebind_layer()` at the end of `__init__`. Add `self._rebind_layer()` as the first statement of `_on_lines_changed`'s try block, before `self._invalidate()`.

```python
    def _rebind_layer(self) -> None:
        """Follow the `lines` layer across rebuilds.

        `SiteLayers.refresh()` replaces the layer object, so a connection
        made once at construction would point at a dead wrapper after the
        first refresh and promotion would silently stop working -- with no
        error, which is the worst kind of stop.
        """
        old = self._lines_layer_bound
        if old is not None and not sip.isdeleted(old):
            try:
                old.selectionChanged.disconnect(self._on_selection)
            except TypeError:
                pass  # already gone; disconnect raises rather than no-ops
        layer = self._lines_layer()
        self._lines_layer_bound = layer
        if layer is not None:
            layer.selectionChanged.connect(self._on_selection)

    def _on_selection(self, *_: Any) -> None:
        """A preview becomes the working line when the user selects the
        line feature with QGIS's ordinary Select tool.

        No event filter, no tool of our own, no stolen clicks, and it
        composes with everything else QGIS does with selection. Promotion
        goes through `session.open_line` -- the same path the survey tree
        uses -- so opening from the map and opening from the tree cannot
        diverge.
        """
        try:
            layer = self._lines_layer()
            if layer is None or not self.session.is_open:
                return
            ids = layer.selectedFeatureIds()
            if len(ids) != 1:
                # A multi-selection has no single answer, and guessing one
                # is worse than doing nothing (spec §3.4). An empty
                # selection is the ordinary result of clicking empty map
                # and must not close the line the user is working on.
                return
            key = str(layer.getFeature(ids[0])["line_key"])
            if key in self.session.keys():
                self.session.open_line(key)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not open the selected line: {exc}", Qgis.MessageLevel.Critical)
```

`dispose()` reaches its final form here. Replace the whole method body's first statement with the unbind, so the link stops promoting as well as stops drawing:

```python
    def dispose(self) -> None:
        """...docstring unchanged from Task 3..."""
        self._dwell.stop()
        layer = self._lines_layer_bound
        self._lines_layer_bound = None
        if layer is not None and not sip.isdeleted(layer):
            try:
                layer.selectionChanged.disconnect(self._on_selection)
            except TypeError:
                pass
        items, self._marker, self._band = (self._marker, self._band), None, None
        for item in items:
            if item is None or sip.isdeleted(item):
                continue
            scene = item.scene()
            if scene is not None:
                scene.removeItem(item)
```

- [ ] **Step 4: Wire it into the plugin**

In `plugin.py`'s `__init__`, add `self.map_link: Any = None` beside the other attributes.

In `initGui`, immediately after `self.loader = LineLoader(...)`:

```python
        # Constructed here, with `layers`, because it reads the `lines`
        # layer's geometry and must be connected before the first
        # site_opened fires -- same reason SiteLayers is built this early.
        self.map_link = MapLink(self.session, self.layers, self.iface.mapCanvas())
```

with `from .map_link import MapLink` at the top.

In `unload`, **before** `self.layers.detach()`:

```python
        if self.map_link is not None:
            # Before layers.detach(): the link holds geometry copied from
            # the `lines` layer and disposal only touches its own canvas
            # items, but ordering teardown outside-in keeps the link from
            # observing a half-dismantled layer set through the signals it
            # is still connected to.
            self.map_link.dispose()
            self.map_link = None
```

- [ ] **Step 5: Document it**

Add to `packages/nsgeo-qgis/README.md`, in the features section:

```markdown
### The map ↔ profile link

Hovering a line on the map canvas previews its radargram in the profile
dock, and the profile's trace cursor and selected range draw back onto the
map. Hovering is ambient — it does not take over the canvas, so pan,
identify and select all keep working while it is on.

A preview is **not** the line you are working on. It drives the view and
nothing else: the processing dock, the gain strip and every operation that
edits a stack stay pointed at the working line, and the profile says so
while a preview is showing. To work on a previewed line, select it with
QGIS's Select tool.
```

- [ ] **Step 6: Run everything**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent \
  packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py \
  packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
```

Expected: pure above baseline (`363 passed` + 2 orphan tests), QGIS above baseline, ruff and mypy clean.

- [ ] **Step 7: The manual half of the no-orphans check**

The automated test covers signals. Public *methods* are checked by hand, once, here. For each public method added by Tasks 1-5 (`set_preview`, `clear_preview`, `preview_key`, `preview_trace`, `display_key`, `dispose`), grep for a caller in production code — not only in tests:

```bash
for name in set_preview clear_preview display_key preview_key preview_trace dispose; do
  echo "== $name =="
  grep -rn "\.$name" packages/nsgeo-qgis/nsgeo_qgis/ | grep -v "def $name"
done
```

Every one must have at least one hit outside its own definition. Record the result in the task report. Confirm too that the pre-existing orphans are unchanged in status: `picks_changed` still deferred to M8, `ProfileDock.pick_requested` still unconsumed (pinned at one connect), the three dead `SurveyDock` signals still listed, and `ProfileView.set_pick_mode` still uncalled. M7 adopts none of them and must not have quietly added another.

**Report back for the user:** spec §1's orphan table and §6's "the three existing orphans" are both wrong — the real set is `picks_changed`, `ProfileDock.pick_requested`, `ProfileView.set_pick_mode`, plus `SurveyDock.new_site_requested` / `open_site_requested` / `save_requested`. The three `SurveyDock` signals are dead API from Plan 2 and want an issue.

- [ ] **Step 8: Commit and push**

```bash
git add -A
git commit -m "feat: selecting a line on the map makes it the working line

Promotion goes through session.open_line, the same path the survey tree
uses, so opening from the map and from the tree cannot diverge. A
multi-selection promotes nothing: there is no single answer and guessing
one is worse than doing nothing.

_rebind_layer follows the lines layer across SiteLayers.refresh(), which
replaces the layer object -- a connection made once would point at a dead
wrapper and promotion would stop with no error at all.

Adds the standing no-orphan-signals check from spec §6, with the two
signals M8 adopts listed explicitly rather than silently exempt.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push -u origin nsgeo-m7
```

---

## M7 acceptance

Automated tests do not cover the thing M7 is for. Run these by hand in QGIS against a real site before calling the milestone done, and record the result:

1. Hover a line on the map — its radargram appears, the banner names it, and the processing dock still shows the *working* line.
2. Hover along the line — the profile's cursor tracks the pointer.
3. Hover off every line — the view snaps back to the working line and the banner clears.
4. With a gain step selected and the strip showing, hover another line — the strip hides; hover away — it comes back on the same curve.
5. With the difference view on, hover another line — the difference turns off for the preview and is back when the view snaps back.
6. Select the previewed line with QGIS's Select tool — it becomes the working line and the processing dock follows.
7. Select two lines at once — nothing is promoted.
8. Drag a selection in the profile — the band lights up on the map over the right stretch.
9. Pan and zoom the map while hovering — the preview keeps working (this is the claim that justifies not using a map tool).
10. Unload the plugin — no crash, and no marker or band left on the canvas.

Known limit, not a defect (spec §3.6): previewing across a large site can eventually load every line, at ~1.3 MB each. Comfortable for tens of lines, uncomfortable for hundreds. No eviction policy in M7 — file an issue if a real site makes it bite.
