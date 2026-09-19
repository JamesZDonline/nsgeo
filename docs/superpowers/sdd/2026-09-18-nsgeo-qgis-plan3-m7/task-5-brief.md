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

`dispose()` gains the layer unbind, so the link stops promoting as well as drawing.

**Do NOT retype the method.** Tasks 3 and 4 hardened it across four review rounds and it is longer and more careful than this plan originally anticipated: it tolerates a deleted canvas wrapper, a canvas that is not a sip object at all, and a `disconnect` that raises, and in every one of those cases it still reaches the scene-removal loop. Replacing it with a shorter version reintroduces the Item I4 leak the method exists to prevent — that regression has already happened once in this task's history.

Read the method as it stands, then **insert only** the unbind, immediately after the existing canvas-disconnect guard and before the `items, self._marker, self._band = ...` line:

```python
        # The lines layer is rebound across every SiteLayers.refresh()
        # (see _rebind_layer), so disposal has to release whichever
        # instance is currently bound -- guarded the same way as the
        # canvas above, and for the same reason: nothing here may abort
        # before the scene-removal loop below.
        layer = self._lines_layer_bound
        self._lines_layer_bound = None
        if layer is not None and not sip.isdeleted(layer):
            with contextlib.suppress(TypeError, RuntimeError):
                layer.selectionChanged.disconnect(self._on_selection)
```

Extend the existing docstring by a sentence naming the layer connection; do not rewrite what is there.

Then add to the disposal test that a `selectionChanged` after `dispose()` promotes nothing:

```python
def test_a_disposed_link_stops_promoting_on_selection(linked):
    link, session, layers, _canvas, keys = linked
    link.dispose()

    layers.layers["lines"].selectByIds([_feature_id(layers, keys[1])])

    assert session.current_key == keys[0]
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
