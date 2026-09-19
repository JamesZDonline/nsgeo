# M8 — the pick tool: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A click on the radargram authors a pick — stored in the site GeoPackage, drawn on the profile and on the map — and selecting a pick or a mark on the map jumps the profile to its line and trace.

**Architecture:** `SiteSession` gains `add_pick(key, trace, time_ns)`, which is where the invariant lives: a pick targets the **working line** (`current_key`) and nothing else. The session cannot write a GeoPackage feature itself (it holds no layers, and the parent spec forbids a second OGR handle on a package QGIS already has open), so `SiteLayers` registers itself with the session as the *pick store* and owns the provider write. The three orphaned pick APIs from Plan 2 — `SiteSession.picks_changed`, `ProfileDock.pick_requested`, `ProfileView.set_pick_mode` — each gain their first consumer, and `MapLink`'s selection-promotion mechanism is generalised from the `lines` layer to `picks` and `marks`.

**Tech Stack:** Python 3.12 (3.9 floor), PyQt5, QGIS 3.44 LTR bindings, numpy, pytest. No new third-party dependencies.

**Spec:** `docs/superpowers/specs/2026-09-18-nsgeo-qgis-plan3-design.md` — **§4 is M8**. §3 is M7 (merged); §5 is M9 (later). Parent spec: `docs/superpowers/specs/2026-09-10-nsgeo-qgis-plugin-design.md` (§4.3 the GeoPackage rules, §6 picking).

**Worktree:** `.worktrees/nsgeo-m8`, branch `nsgeo-m8`, forked from `main` at `54a8682`.

**M7's ledger is required reading when code looks strange:** `docs/superpowers/sdd/2026-09-18-nsgeo-qgis-plan3-m7/progress.md`. Nineteen numbered rulings, each with the defect it was reproduced against. The odd shapes in `session.py`, `profile_dock.py` and `map_link.py` are load bearing. Search that file before "tidying" anything.

---

## Global Constraints

These apply to every task. They are not restated per task.

- **Two test tiers, both must pass before any task is reported done.** Run from the worktree root.
  - Pure tier (no QGIS): `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh`
  - QGIS tier (~2.5 min): `QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh`
  - **Baseline at `54a8682`, measured in this worktree:** pure `367 passed, 2 skipped`; QGIS `469 passed`. Any task that ends below those pass counts has broken something.
- **`-p no:xonsh` is required on this machine only.** `.venv-qgis` is built `--system-site-packages`, so the system `xonsh` package's stale pytest plugin breaks collection. Never add it to a config file committed to the repo (Plan 2, Ruling 12).
- **`PYTHONDONTWRITEBYTECODE=1` on every run.** Stale `.pyc` files fake mutation-test survivors and mask reverted source.
- **Lint and types, from the pure venv (neither tool is on `PATH`):**
  - `.venv/bin/ruff check .` and `.venv/bin/ruff format --check .`
  - `.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py`
  - `session.py`, `layers.py`, `map_link.py` and the UI modules are **not** in the mypy list: that list is deliberately restricted to modules importable without QGIS. Do not add to it.
- **Every Qt slot catches its own exceptions.** An exception escaping a slot prints and passes locally (PyQt 5.15.10) but reaches `qFatal()` in the `qgis/qgis:ltr` CI container and aborts the whole job. Every method connected to a signal wraps its body in `try/except Exception` and reports via the module's `_log` helper (or, in `plugin.py`, `self.message`). The `_no_swallowed_slot_exceptions` conftest fixture fails any test that lets one escape — do not fight it, fix the slot.
  - **Corollary, and it bites in this milestone:** never connect a bare `SiteSession` method to a signal. `session.add_pick` raises by design; connected directly it would abort CI. It is always reached through a `plugin.py` slot that catches.
- **No unhandled modals.** The `_no_unhandled_modals` fixture forbids `QMessageBox.question/warning/information`, `QFileDialog.*`, `QInputDialog.getText`, `QDialog.exec`, `QMenu.exec`, and `QTest.mouseDClick`. M8 adds no dialogs; nothing here should need `answer_modal` or `drive_dialog`.
- **Real data is the primary validation.** Ten real GSSI DZT files (plus DZX sidecars) are symlinked at `packages/nsgeo-core/tests/data/local/`. Use `plugin_testing.REAL_DZT` / `needs_real_data` where a test benefits; `plugin_testing.synthetic_dzt` is fine for geometry-only tests.
- **The session is the only state holder.** No widget stores survey state or talks to another widget directly; everything reads `SiteSession` and connects to its signals.
- **THE INVARIANT.** `SiteSession.current_key` is the working line — the target of every write. `preview_key` is what the pointer is over; it drives the view and **nothing else, ever**. Spec §4.3: picking targets the working line, never a preview. M7's reviews caught three separate attempts by a preview to reach a write (`set_channel`, `clear_selection`, the deferred gain strip). Assume any new path from pointer to session is a fourth until proven otherwise. `ProfileDock._pick` already guards against previewing — **do not remove that guard.**
- **Picks are the one table the survey file is not the source of truth for.** `survey.nsgeo.json` can regenerate `grids`, `lines` and `marks`; nothing can regenerate `picks`. This project has already had to repair pick storage twice. A pick write that fails must fail loudly; a pick write that half-succeeds is a defect.
- **Commit after each task**, message in the repo's style (lowercase `feat:`/`fix:`/`test:`/`docs:` prefix, imperative, and the body explains *why*, not *what*). End every commit message with a co-author trailer naming **the model that actually did the work**:
  ```
  Co-Authored-By: <your own model name> <noreply@anthropic.com>
  ```
  Do **not** copy a model name out of this plan or out of another commit. Naming a model that did not write the commit is a false record.
- **Push as you go.** `git push -u origin nsgeo-m8` on the first commit, `git push` after each later one.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `packages/nsgeo-qgis/nsgeo_qgis/session.py` | modify | Adds the `Pick` record, the pick-store registration, `add_pick` (the invariant guard and every derived field), and `picks_for`. The guard lives here for the same reason `set_trace`'s does: structurally, where no caller can forget it. |
| `packages/nsgeo-qgis/nsgeo_qgis/layers.py` | modify | Adds `feature_id`/`seq` to the `picks` schema and owns the only write path: `write_pick` / `picks_for`, through the loaded layer's data provider. Registers itself as the session's pick store. |
| `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py` | modify | One guard: a pick click outside the image rect is not a pick. `set_pick_mode` and `set_picks` already exist and are unchanged. |
| `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` | modify | Public `set_pick_mode` passthrough; says why a pick was refused during a preview; feeds `view.set_picks` from the session. |
| `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` | modify | The "Pick" toolbar toggle, and the relay from `ProfileDock.pick_requested` to `session.add_pick` with failures reported to the message bar. |
| `packages/nsgeo-qgis/nsgeo_qgis/map_link.py` | modify | Generalises selection binding from the `lines` layer alone to `lines`, `picks` and `marks`, so selecting a pick or a mark jumps to its line and trace. Disposal releases all three. |
| `packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py` | modify | Schema migration, the provider write, the read-back. |
| `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py` | modify | `add_pick`'s guard, its derived fields, its signal. |
| `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py` | modify | Pick mode, refusal feedback, picks on the profile. |
| `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py` | modify | The image-rect guard. |
| `packages/nsgeo-qgis/tests/qgis/test_plugin_loads.py` | modify | The toolbar toggle and the relay, end to end through the plugin. |
| `packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py` | modify | Selecting a pick and selecting a mark; disposal releases all three layers. |
| `packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py` | modify | The pins move as the orphans are adopted. This test is the notification mechanism — expect it to go red and update it deliberately. |
| `README.md` | modify | One short section: how to author a pick. |

### Where the pick write lives, and why it is not all in the session

Spec §4.1 says `session.add_pick(key, trace, time_ns)` writes a pick. The session cannot literally do that: it holds no `QgsVectorLayer`, and the parent spec §4.3 rule 2 says **all writes go through the loaded QGIS layer's data provider — never a second OGR handle on a GeoPackage QGIS already has open.** Opening the package again from `session.py` would break that rule outright.

So the responsibility splits, and the split follows what each object already knows:

- **`SiteSession.add_pick`** is the public API the spec names. It enforces the invariant (`key` must be `current_key`), clamps the trace and the time into the line's real extents, derives `distance_m`, `depth_m`, `velocity_m_ns`, `stack_json` and `created`, and emits `picks_changed` — but only after the write has actually succeeded.
- **`SiteLayers.write_pick`** does the provider write and the geometry. It is registered on the session by `SiteLayers.__init__` (`session.set_pick_store(self)`), the same constructor that already connects six session signals.

This makes `session` hold a reference to `layers`, which already holds a reference to `session` — a reference cycle. That is deliberate and safe: neither class defines `__del__`, Python's cycle collector handles it, and `plugin.unload()` drops both together. Recorded here so a reviewer does not have to rediscover the reasoning.

**Alternative rejected:** putting the whole thing on `SiteLayers` and having `plugin.py` call `layers.add_pick(...)`. It needs no new coupling, but it puts the C2 guard in a widget-adjacent collaborator rather than in the session, where `set_trace` and `set_selection` already refuse a non-current key structurally. The M7 whole-branch review specifically credited that placement for why no preview could reach a write. Keep the guard where the other guards are.

---

## Task 1: The pick schema and the pick store

The data-corruption-class task. It changes the schema of the one table with no other source of truth, which makes every existing site package a migration, and it adds the only code in the plugin that writes an authored feature.

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py` (imports; new `Pick` dataclass after the module constants; `__init__` ~line 70-86; a new "picks" section before `# ---- preview (spec §3.3) ----`)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/layers.py` (`TABLES["picks"]` ~line 98-110; `SiteLayers.__init__` ~line 152-170; new methods after `feature_count` ~line 731)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `nsgeo_qgis.session.Pick` — frozen dataclass, fields in this exact order: `line_key: str`, `trace: int`, `time_ns: float`, `distance_m: float | None`, `depth_m: float | None`, `velocity_m_ns: float | None`, `stack_json: str`, `note: str`, `created: str`, `feature_id: str | None = None`, `seq: int | None = None`.
  - `SiteSession.set_pick_store(store: Any) -> None`
  - `SiteSession.pick_store` — read-only property, `Any | None`.
  - `SiteLayers.write_pick(pick: Pick) -> None` — raises `RuntimeError` on any failure to write.
  - `SiteLayers.picks_for(key: str) -> list[Pick]` — ordered by `(trace, time_ns)`.
  - `TABLES["picks"]` gains `("feature_id", "str")` and `("seq", "int")`, appended after `("created", "str")`.

**Facts established by experiment before this plan was written — do not re-derive them, but do not assume they cover your case either:**
1. A GPKG point table accepts a feature with **no geometry**; it reads back with `feature.geometry().isNull()` True.
2. `_rebuild_picks`'s migrate-by-field-name loop leaves the two new fields NULL on every pre-existing row, with no code change needed.
3. Assigning Python `None` to a `QgsFeature` attribute writes NULL. Reading it back gives a `QVariant` for which `value == NULL` is True and `value is None` is **False** — so `from qgis.core import NULL` and compare with `==`. An empty string is **not** NULL; it reads back as `''`.

- [ ] **Step 1: Write the failing tests**

Append to `packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py`. Two import edits at the top of that file: add `NULL` to the `from qgis.core import (...)` list, and extend `from nsgeo_qgis.session import GPKG_FILE, SURVEY_FILE, SiteSession` to `from nsgeo_qgis.session import GPKG_FILE, SURVEY_FILE, Pick, SiteSession`.

Its `populated` fixture yields `(session, layers, project)` and builds three synthetic lines `FILE__001..003.DZT` on grid `A` at origin `(500.0, 700.0)`, with a DZX sidecar on `FILE__002`. These tests use it as-is.

```python
# ---- picks: the store (M8, spec §4.1, §4.2) --------------------------------


def _a_pick(key="raw/FILE__001.DZT", trace=7, time_ns=12.5, **kw):
    """A fully-populated Pick, so a test that cares about one field does
    not have to spell out the other ten."""
    fields = dict(
        line_key=key,
        trace=trace,
        time_ns=time_ns,
        distance_m=0.117,
        depth_m=0.25,
        velocity_m_ns=0.04,
        stack_json='[{"step": "dewow", "params": {}, "enabled": true}]',
        note="",
        created="2026-09-19T10:00:00+00:00",
    )
    fields.update(kw)
    return Pick(**fields)


def test_the_picks_table_carries_the_two_grouping_fields(populated):
    """Spec §4.2: `feature_id` and `seq` exist from M8 and are written
    null, so a horizon later is an ordered run of existing picks and
    needs no migration of an authored table."""
    session, layers, _ = populated
    names = [f.name() for f in layers.layers["picks"].fields() if f.name() != "fid"]
    assert names[-2:] == ["feature_id", "seq"]


def test_write_pick_stores_every_field_and_places_it_on_the_line(populated):
    session, layers, _ = populated
    layers.write_pick(_a_pick(trace=0))

    assert layers.feature_count("picks") == 1
    feat = next(layers.layers["picks"].getFeatures())
    assert feat["line_key"] == "raw/FILE__001.DZT"
    assert feat["trace"] == 0
    assert feat["time_ns"] == pytest.approx(12.5)
    assert feat["distance_m"] == pytest.approx(0.117)
    assert feat["depth_m"] == pytest.approx(0.25)
    assert feat["velocity_m_ns"] == pytest.approx(0.04)
    assert "dewow" in feat["stack_json"]
    assert feat["created"] == "2026-09-19T10:00:00+00:00"
    assert feat["feature_id"] == NULL
    assert feat["seq"] == NULL
    # Trace 0 of the first line sits at the grid origin, in the package CRS.
    point = feat.geometry().asPoint()
    assert (point.x(), point.y()) == pytest.approx((500.0, 700.0), abs=1e-6)


def test_write_pick_places_a_later_trace_further_along_the_line(populated):
    """The geometry is the trace's own world position, not the line's
    start: a pick's whole value on the map is where along the line it
    is."""
    session, layers, _ = populated
    layers.write_pick(_a_pick(trace=0))
    layers.write_pick(_a_pick(trace=59))

    points = [f.geometry().asPoint() for f in layers.layers["picks"].getFeatures()]
    a, b = sorted(points, key=lambda p: (p.x(), p.y()))
    assert a.distance(b) == pytest.approx(59 / 60, abs=1e-6)


def test_write_pick_refuses_rather_than_dropping_the_pick_when_the_table_is_gone(populated):
    session, layers, _ = populated
    layers.detach()
    with pytest.raises(RuntimeError, match="picks"):
        layers.write_pick(_a_pick())


def test_a_pick_on_an_unplaceable_line_is_stored_without_geometry(populated, tmp_path, message_log):
    """A time-triggered acquisition has no geometry (`trace_coords`
    raises), so the pick cannot be drawn -- but time is the truth and the
    pick is authored data with no other source. It is stored with a null
    geometry and the log says why, rather than being refused."""
    session, layers, _ = populated
    p = synthetic_dzt(tmp_path / "raw", "FILE__004.DZT", n_traces=40, traces_per_metre=0.0)
    session.add_lines([Line.open(p, GridPlacement("A", "y", 1.5, 0.0, 1, p.stem))])

    layers.write_pick(_a_pick(key="raw/FILE__004.DZT", trace=3))

    feat = next(layers.layers["picks"].getFeatures())
    assert feat["line_key"] == "raw/FILE__004.DZT"
    assert feat.geometry().isNull()
    assert any("cannot be placed" in m for m in message_log)


def test_picks_for_returns_only_that_lines_picks_in_trace_order(populated):
    session, layers, _ = populated
    layers.write_pick(_a_pick(trace=40, time_ns=30.0))
    layers.write_pick(_a_pick(trace=5, time_ns=10.0))
    layers.write_pick(_a_pick(key="raw/FILE__002.DZT", trace=9, time_ns=20.0))

    got = layers.picks_for("raw/FILE__001.DZT")

    assert [(p.trace, p.time_ns) for p in got] == [(5, 10.0), (40, 30.0)]
    assert all(p.line_key == "raw/FILE__001.DZT" for p in got)
    assert got[0].feature_id is None
    assert got[0].seq is None
    assert got[0].note == ""


def test_picks_for_is_empty_rather_than_raising_with_no_site_open(populated):
    session, layers, _ = populated
    layers.detach()
    assert layers.picks_for("raw/FILE__001.DZT") == []


def test_picks_for_skips_a_hand_edited_row_with_no_trace_or_time(populated, message_log):
    """The `picks` layer is deliberately editable in QGIS, so a user can
    digitise a point into it with the ordinary tools and leave the
    attributes blank. `float(NULL)` inside a slot would abort the CI
    container; such a row is skipped and named instead."""
    session, layers, _ = populated
    layer = layers.layers["picks"]
    f = QgsFeature(layer.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    f["line_key"] = "raw/FILE__001.DZT"
    assert layer.dataProvider().addFeatures([f])[0]
    layers.write_pick(_a_pick(trace=2, time_ns=8.0))

    got = layers.picks_for("raw/FILE__001.DZT")

    assert [(p.trace, p.time_ns) for p in got] == [(2, 8.0)]
    assert any("no trace or time" in m for m in message_log)


def test_a_package_with_the_pre_m8_picks_schema_migrates_with_its_rows_intact(
    qgis_app, tmp_path, message_log
):
    """The one migration in M8. `picks` is the only table that cannot be
    regenerated, and this project has already had to repair its storage
    twice -- so the rows, their attributes and their geometry must all
    survive the two new columns arriving, with the new columns null.
    """
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    session.add_grid(GRID)
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT", n_traces=60)
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0, 0.0, 1, p.stem))])
    session.save()
    package = session.gpkg_path
    layers.detach()
    project.clear()

    # Rewrite `picks` with the pre-M8 field set and put two authored rows
    # in it, exactly as a site created before this milestone would have.
    old_spec = [(name, kind) for name, kind in TABLES["picks"][1] if name not in ("feature_id", "seq")]
    old_fields = QgsFields()
    kinds = {"str": QMetaType.Type.QString, "int": QMetaType.Type.Int, "float": QMetaType.Type.Double}
    for name, kind in old_spec:
        old_fields.append(QgsField(name, kinds[kind]))
    opts = QgsVectorFileWriter.SaveVectorOptions()
    opts.driverName = "GPKG"
    opts.layerName = "picks"
    opts.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
    writer = QgsVectorFileWriter.create(
        str(package),
        old_fields,
        QgsWkbTypes.Type.Point,
        QgsCoordinateReferenceSystem("EPSG:32616"),
        project.transformContext(),
        opts,
    )
    assert writer.hasError() == QgsVectorFileWriter.WriterError.NoError
    del writer
    old = QgsVectorLayer(f"{package}|layername=picks", "picks", "ogr")
    rows = []
    for i, (trace, time_ns) in enumerate([(4, 11.0), (33, 26.5)]):
        f = QgsFeature(old.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0 + i, 700.0 + i)))
        f["line_key"] = "raw/FILE__001.DZT"
        f["trace"] = trace
        f["time_ns"] = time_ns
        f["note"] = f"note {i}"
        rows.append(f)
    assert old.dataProvider().addFeatures(rows)[0]
    del old

    again = SiteSession()
    layers2 = SiteLayers(again, project=project)
    again.open_site(tmp_path / SURVEY_FILE)

    names = [f.name() for f in layers2.layers["picks"].fields() if f.name() != "fid"]
    assert names == [name for name, _ in TABLES["picks"][1]]
    assert layers2.feature_count("picks") == 2
    got = sorted(layers2.layers["picks"].getFeatures(), key=lambda f: f["trace"])
    assert [(f["trace"], f["time_ns"], f["note"]) for f in got] == [
        (4, 11.0, "note 0"),
        (33, 26.5, "note 1"),
    ]
    assert [f["feature_id"] for f in got] == [NULL, NULL]
    assert [f["seq"] for f in got] == [NULL, NULL]
    assert not got[0].geometry().isNull()
    layers2.detach()


def test_the_layers_register_themselves_as_the_sessions_pick_store(populated):
    """Spec §4.1 names `session.add_pick`, but the session holds no
    layers and the parent spec forbids a second OGR handle on a package
    QGIS already has open -- so the write is delegated. The registration
    must happen in the constructor, before any site_opened could fire."""
    session, layers, _ = populated
    assert session.pick_store is layers
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest \
  packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py -q -p no:xonsh 2>&1 | tail -20
```

Expected: the new tests fail (`AttributeError: 'SiteLayers' object has no attribute 'write_pick'`, `ImportError: cannot import name 'Pick'`, and the schema assertions). Every pre-existing test in the file must still pass.

- [ ] **Step 3: Add the `Pick` record and the store registration to `session.py`**

Add to the imports at the top of `session.py`:

```python
import datetime as _dt
```

(`dataclasses` and `Any` are already imported.)

Add the record immediately after the `_SQLITE_JOURNALS` constant and before `def _log`:

```python
@dataclasses.dataclass(frozen=True)
class Pick:
    """One authored pick: a trace and a two-way time on one line.

    Time is the truth. `distance_m`, `depth_m` and `velocity_m_ns` are
    conveniences that can be recomputed from the line's geometry and its
    resolved velocity model, and are `None` when the line cannot supply
    them (a time-triggered acquisition has no distance axis).

    `feature_id` and `seq` are written null by M8 and exist now so that a
    horizon later is an ordered run of existing picks sharing a
    `feature_id`, needing no migration of an authored table (spec §4.2).
    `picks` is the one table `survey.nsgeo.json` cannot regenerate, and
    this project has already had to repair its storage twice; the cheap
    time to add these columns is before there are horizons to migrate.
    """

    line_key: str
    trace: int
    time_ns: float
    distance_m: float | None
    depth_m: float | None
    velocity_m_ns: float | None
    stack_json: str
    note: str
    created: str
    feature_id: str | None = None
    seq: int | None = None
```

In `SiteSession.__init__`, after `self._preview_trace = -1`:

```python
        # Set by SiteLayers' own constructor (see set_pick_store). None
        # until then, which is the normal state of a session built by a
        # test that has no layers at all.
        self._pick_store: Any | None = None
```

Add the accessor and the registration in a new section, placed immediately before the `# ---- preview (spec §3.3) ----` banner:

```python
    # ---- picks (spec §4) --------------------------------------------------
    @property
    def pick_store(self) -> Any | None:
        return self._pick_store

    def set_pick_store(self, store: Any) -> None:
        """Register the object that actually writes picks.

        Spec §4.1 names `session.add_pick`, and the invariant it enforces
        (a pick targets the WORKING line) belongs here beside
        `set_trace`'s and `set_selection`'s identical guards. The *write*
        cannot be here: this object holds no `QgsVectorLayer`, and the
        parent spec §4.3 rule 2 forbids opening a second OGR handle on a
        GeoPackage QGIS already has open. `SiteLayers` holds the loaded
        layer and registers itself from its own constructor.

        This makes the reference cycle session <-> layers explicit.
        Deliberate: neither class defines `__del__`, so Python's cycle
        collector handles it, and `plugin.unload()` drops both together.
        """
        self._pick_store = store
```

- [ ] **Step 4: Add the two fields to the `picks` schema**

In `layers.py`, `TABLES["picks"]`, append the two entries after `("created", "str")`:

```python
    "picks": (
        QgsWkbTypes.Type.Point,
        [
            ("line_key", "str"),
            ("trace", "int"),
            ("distance_m", "float"),
            ("time_ns", "float"),
            ("depth_m", "float"),
            ("velocity_m_ns", "float"),
            ("stack_json", "str"),
            ("note", "str"),
            ("created", "str"),
            # M8, spec §4.2: written null now. A horizon later is an
            # ordered run of existing picks sharing a `feature_id`, so
            # adding them here -- while `picks` holds at most a handful of
            # authored rows -- costs one migration now instead of a
            # migration of real interpretations later. `_ensure_table`
            # sees the field-set mismatch on any pre-M8 package and routes
            # it through `_rebuild_picks`, whose migrate-by-field-name
            # loop leaves both columns NULL on every existing row with no
            # code change needed (verified by experiment before this was
            # written, and by
            # `test_a_package_with_the_pre_m8_picks_schema_migrates_with_its_rows_intact`).
            ("feature_id", "str"),
            ("seq", "int"),
        ],
    ),
```

- [ ] **Step 5: Register the store and write the provider methods**

In `layers.py`, add `NULL` to the `qgis.core` import list, and extend the runtime import at `layers.py:58` — `from nsgeo_qgis.session import SiteSession` — to `from nsgeo_qgis.session import Pick, SiteSession`. (It is a plain runtime import, not a `TYPE_CHECKING` one, which is what `Pick` needs: it is constructed here, not only annotated.)

In `SiteLayers.__init__`, immediately after `self.project.layersWillBeRemoved.connect(self._on_layers_removed)`:

```python
        # Registered here, in the constructor, for the same reason the
        # session signals above are: this must be in place before the
        # first site_opened could fire, not whenever someone remembers.
        session.set_pick_store(self)
```

Add these methods after `feature_count`, before the `# ---- derived tables ----` banner:

```python
    # ---- picks (authored; spec §4) ----------------------------------------
    def _picks_layer(self) -> QgsVectorLayer | None:
        layer = self.layers.get("picks")
        if layer is None or sip.isdeleted(layer):
            return None
        return layer

    def _pick_point(self, pick: Pick) -> QgsPointXY | None:
        """The pick's position in the package CRS, or None when the line
        cannot be placed at all.

        Same path `refill_marks` uses for a mark, and for the same
        reason: the trace index IS the vertex index, so the pick lands
        exactly where the line is drawn rather than somewhere
        independently computed that could disagree with it.
        """
        site = self.session.site
        if site is None:
            return None
        line = self.session.line_for_key(pick.line_key)
        grid = self.session.grid_for_line(line)
        if grid is None:
            return None
        coords = self._line_points(line, grid, site.frames)
        if coords is None:
            return None
        return coords[max(0, min(pick.trace, len(coords) - 1))]

    def write_pick(self, pick: Pick) -> None:
        """Write one authored pick through the loaded layer's data
        provider (parent spec §4.3 rule 2: never a second OGR handle on a
        package QGIS already has open).

        Raises rather than returning a flag. `picks` is the one table
        `survey.nsgeo.json` cannot regenerate, so a write that fails must
        say so loudly enough to reach the user -- `SiteSession.add_pick`
        deliberately does not emit `picks_changed` if this raises, and
        `plugin.py`'s relay puts the message on the bar.
        """
        layer = self._picks_layer()
        if layer is None:
            raise RuntimeError("the picks table is not open; no site is loaded")
        point = self._pick_point(pick)
        if point is None:
            # Time is the truth and the pick is authored data with no
            # other source: a line with no geometry (a time-triggered
            # acquisition, or one whose grid is gone) still gets its pick
            # recorded, with a null geometry, and the log says why it
            # will not appear on the canvas. Refusing the write would
            # lose the one thing that cannot be recomputed.
            _log(
                f"{pick.line_key} cannot be placed on the map; its pick is recorded "
                f"but will not appear on the canvas"
            )
        feature = QgsFeature(layer.fields())
        if point is not None:
            feature.setGeometry(QgsGeometry.fromPointXY(point))
        # By field NAME against the layer's own fields, never positionally
        # against `_fields(spec)`: a GPKG table carries an implicit
        # leading "fid" that `spec` does not list, and attributes keyed
        # off a Fields object one short of the provider's own silently
        # land one column over. That was measured on this very table
        # during the package-naming migration -- a pick's `line_key` came
        # back as its `time_ns`.
        names = {f.name() for f in layer.fields()}
        for name, value in (
            ("line_key", pick.line_key),
            ("trace", int(pick.trace)),
            ("distance_m", pick.distance_m),
            ("time_ns", float(pick.time_ns)),
            ("depth_m", pick.depth_m),
            ("velocity_m_ns", pick.velocity_m_ns),
            ("stack_json", pick.stack_json),
            ("note", pick.note),
            ("created", pick.created),
            ("feature_id", pick.feature_id),
            ("seq", pick.seq),
        ):
            if name in names:
                feature[name] = value  # None writes NULL
        ok, _ = layer.dataProvider().addFeatures([feature])
        if not ok:
            raise RuntimeError(f"could not write the pick: {layer.dataProvider().error().message()}")
        layer.updateExtents()
        layer.triggerRepaint()

    def picks_for(self, key: str) -> list[Pick]:
        """Every pick on `key`, ordered by (trace, time).

        A plain scan rather than a `QgsFeatureRequest` filter expression:
        a line key is a relative POSIX path and can legitimately contain
        a quote, and the quoting bug that would cause is silent and
        occasional. Picks number in the handful to the low thousands, so
        the scan is not a cost worth that risk.
        """
        layer = self._picks_layer()
        if layer is None:
            return []
        picks = []
        for feature in layer.getFeatures():
            if _as_str(feature["line_key"]) != key:
                continue
            pick = self._row_to_pick(feature, key)
            if pick is not None:
                picks.append(pick)
        picks.sort(key=lambda p: (p.trace, p.time_ns))
        return picks

    def _row_to_pick(self, feature: QgsFeature, key: str) -> Pick | None:
        """One `picks` row as a `Pick`, or None if the row cannot be one.

        `picks` is deliberately editable in QGIS, so a user can digitise a
        point into it with the ordinary tools and leave the attributes
        blank. `float(NULL)` raises, and this is read from a Qt slot --
        which means the CI container turns it into `qFatal()` and aborts
        the whole job. Skipping the row and naming it is the only safe
        answer; refusing to read the layer at all would hide every good
        pick because of one bad one.
        """
        trace, time_ns = feature["trace"], feature["time_ns"]
        if trace == NULL or time_ns == NULL:
            _log(f"a pick on {key} has no trace or time and was skipped; edit or delete it")
            return None
        return Pick(
            line_key=key,
            trace=int(trace),
            time_ns=float(time_ns),
            distance_m=_as_float(feature["distance_m"]),
            depth_m=_as_float(feature["depth_m"]),
            velocity_m_ns=_as_float(feature["velocity_m_ns"]),
            stack_json=_as_str(feature["stack_json"]),
            note=_as_str(feature["note"]),
            created=_as_str(feature["created"]),
            feature_id=_as_opt_str(feature["feature_id"]),
            seq=None if feature["seq"] == NULL else int(feature["seq"]),
        )
```

And the three tiny converters, module level in `layers.py`, immediately after `_log`:

```python
def _as_float(value: Any) -> float | None:
    """A nullable numeric attribute. A QGIS NULL reads back as a
    `QVariant` for which `value is None` is False but `value == NULL` is
    True, so identity checks silently fail here."""
    return None if value == NULL else float(value)


def _as_str(value: Any) -> str:
    """A text attribute, with NULL flattened to the empty string. `note`
    and `stack_json` are always written, but a hand-edited row may not
    have them."""
    return "" if value == NULL else str(value)


def _as_opt_str(value: Any) -> str | None:
    """`feature_id` specifically: null and empty are different states
    here. Null means "not grouped"; an empty string would be a group
    whose name is empty."""
    return None if value == NULL else str(value)
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest \
  packages/nsgeo-qgis/tests/qgis/test_plugin_layers.py -q -p no:xonsh 2>&1 | tail -20
```

Expected: all pass. Note that `test_tables_exist_with_the_declared_fields_and_flags` already compares the on-disk field list against `TABLES` and so covers the new columns for free on a fresh package.

- [ ] **Step 7: Run both tiers and the linters**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh 2>&1 | tail -3
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh 2>&1 | tail -3
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
```

Expected: pure still `367 passed, 2 skipped` (this task adds no pure tests); QGIS `469 + <new>` passed; ruff and mypy clean.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: the picks table gains a grouping schema and a write path

feature_id and seq are written null by M8 and exist now so a horizon
later is an ordered run of existing picks sharing a feature_id --
picks is the one table survey.nsgeo.json cannot regenerate, and adding
columns while it holds a handful of rows is cheaper than migrating real
interpretations. _ensure_table routes every pre-M8 package through
_rebuild_picks, which migrates by field name and so leaves both columns
null with no code change.

SiteLayers owns the write because the parent spec forbids a second OGR
handle on a package QGIS already has open, and registers itself on the
session so add_pick can reach it without the session holding a layer.

Co-Authored-By: <your own model name> <noreply@anthropic.com>"
git push -u origin nsgeo-m8
```

---

## Task 2: `session.add_pick` — the invariant and the derived fields

The write-path task. Everything here exists so a pick can only ever land on the working line, and so the fields that are conveniences never silently disagree with the field that is the truth.

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/session.py` (the "picks" section added by Task 1)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py` (append)

**Interfaces:**
- Consumes: `Pick`, `SiteSession.set_pick_store` / `pick_store`, `SiteLayers.write_pick(pick)`, `SiteLayers.picks_for(key)` (Task 1).
- Produces:
  - `SiteSession.add_pick(key: str, trace: int, time_ns: float) -> Pick` — raises `ValueError` when `key` is not the working line or when `time_ns` is not finite; raises `RuntimeError` when no pick store is attached; propagates whatever `write_pick` raises. Emits `picks_changed` **only after** a successful write.
  - `SiteSession.picks_for(key: str) -> list[Pick]` — `[]` when no store is attached.

- [ ] **Step 1: Write the failing tests**

Append to `packages/nsgeo-qgis/tests/qgis/test_plugin_session.py`. That file already imports `json` and `pytest` and defines `GRID` and a `session` fixture; M7 added `previewable`. None of them builds a `SiteLayers`, which every `add_pick` test needs, so this adds one fixture rather than changing theirs. Add `from datetime import datetime` and `from plugin_testing import REAL_DZT, needs_real_data, synthetic_dzt` to the imports (`synthetic_dzt` is already there; extend that line).

```python
# ---- add_pick (M8, spec §4.1, §4.3) ----------------------------------------


@pytest.fixture
def pickable(qgis_app, tmp_path):
    """A session with two placed lines, a real GeoPackage behind it, and
    the first line open as the working line."""
    from nsgeo.geometry.grid import Grid
    from nsgeo.geometry.placement import GridPlacement
    from nsgeo.model.survey import Line
    from nsgeo_qgis.layers import SiteLayers
    from plugin_testing import synthetic_dzt
    from qgis.core import QgsProject

    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    session.add_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5))
    lines = []
    for i in range(2):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", i * 0.5, 0.0, 1, p.stem)))
    session.add_lines(lines)
    keys = session.keys()
    session.open_line(keys[0])
    yield session, layers, keys
    layers.detach()
    project.clear()


def test_add_pick_writes_the_pick_and_says_so_once(pickable):
    session, layers, keys = pickable
    seen = []
    session.picks_changed.connect(lambda: seen.append(1))

    pick = session.add_pick(keys[0], 12, 18.0)

    assert pick.line_key == keys[0]
    assert pick.trace == 12
    assert pick.time_ns == pytest.approx(18.0)
    assert layers.feature_count("picks") == 1
    assert seen == [1]


def test_add_pick_refuses_a_line_that_is_not_the_working_line(pickable):
    """Spec §4.3: picking targets the working line, never a preview. The
    guard is here, in the session, for the same reason set_trace's and
    set_selection's are -- so no caller can forget it. M7's reviews found
    three separate attempts by a preview to reach a write; this is the
    structural answer rather than a fourth guard in a widget."""
    session, layers, keys = pickable
    session.set_preview(keys[1], 5)
    seen = []
    session.picks_changed.connect(lambda: seen.append(1))

    with pytest.raises(ValueError, match="working line"):
        session.add_pick(keys[1], 5, 18.0)

    assert layers.feature_count("picks") == 0
    assert seen == []
    assert session.preview_key == keys[1]  # the refusal changed nothing


def test_add_pick_does_not_dirty_the_session(pickable):
    """A pick is written straight to the GeoPackage; survey.nsgeo.json is
    not involved and there is nothing for `Save site` to do. Marking the
    session dirty would prompt for a save that would write nothing."""
    session, layers, keys = pickable
    session.save()
    assert session.dirty is False

    session.add_pick(keys[0], 3, 10.0)

    assert session.dirty is False


def test_add_pick_clamps_the_trace_and_the_time_into_the_record(pickable):
    """ProfileView emits a pick for any left click in the widget, and
    `ViewTransform.time_of_y` does not clamp -- a click in the top margin
    yields a time before the record starts. The trace is clamped the same
    way `set_trace` clamps it."""
    session, layers, keys = pickable
    line = session.line_for_key(keys[0])
    t0 = line.header.position_ns
    t_end = t0 + (line.header.n_samples - 1) * line.header.dt_ns

    low = session.add_pick(keys[0], -5, t0 - 50.0)
    high = session.add_pick(keys[0], 9999, t_end + 50.0)

    assert low.trace == 0
    assert low.time_ns == pytest.approx(t0)
    assert high.trace == line.n_traces - 1
    assert high.time_ns == pytest.approx(t_end)


def test_add_pick_refuses_a_non_finite_time(pickable):
    session, layers, keys = pickable
    with pytest.raises(ValueError, match="finite"):
        session.add_pick(keys[0], 3, float("nan"))
    assert layers.feature_count("picks") == 0


def test_add_pick_derives_distance_depth_velocity_and_the_stack(pickable):
    session, layers, keys = pickable
    from nsgeo.processing import build_step

    session.append_step(keys[0], build_step("dewow", window_ns=4.0))
    line = session.line_for_key(keys[0])
    model = session.resolved_velocity(keys[0])

    pick = session.add_pick(keys[0], 30, 20.0)

    assert pick.distance_m == pytest.approx(float(line.distance_along()[30]))
    assert pick.depth_m == pytest.approx(float(model.depth_at([20.0])[0]))
    assert pick.velocity_m_ns == pytest.approx(float(model.velocity_at([20.0])[0]))
    assert json.loads(pick.stack_json)[0]["step"] == "dewow"
    assert pick.note == ""
    assert pick.feature_id is None
    assert pick.seq is None
    # An ISO-8601 UTC stamp, parseable rather than merely non-empty.
    assert datetime.fromisoformat(pick.created).tzinfo is not None


def test_add_pick_leaves_distance_null_for_a_line_with_no_distance_axis(pickable, tmp_path):
    """A time-triggered acquisition (traces_per_metre <= 0) has no
    distance axis at all -- `Line.distance_along()` raises. Time is the
    truth, so the pick is still authored; distance is simply absent."""
    session, layers, keys = pickable
    from nsgeo.geometry.placement import GridPlacement
    from nsgeo.model.survey import Line
    from plugin_testing import synthetic_dzt

    p = synthetic_dzt(tmp_path / "raw", "FILE__003.DZT", n_traces=40, traces_per_metre=0.0)
    session.add_lines([Line.open(p, GridPlacement("A", "y", 1.5, 0.0, 1, p.stem))])
    session.open_line("raw/FILE__003.DZT")

    pick = session.add_pick("raw/FILE__003.DZT", 3, 15.0)

    assert pick.distance_m is None
    assert pick.depth_m is not None  # time -> depth needs no geometry


def test_add_pick_does_not_announce_a_write_that_failed(pickable, monkeypatch):
    """picks_changed is what tells the profile and the map to redraw. If
    the provider refused the feature, emitting it would show a pick that
    is not on disk -- the worst possible report for the one table with no
    other source of truth."""
    session, layers, keys = pickable
    seen = []
    session.picks_changed.connect(lambda: seen.append(1))

    def boom(pick):
        raise RuntimeError("disk full")

    monkeypatch.setattr(layers, "write_pick", boom)
    with pytest.raises(RuntimeError, match="disk full"):
        session.add_pick(keys[0], 3, 10.0)

    assert seen == []


def test_add_pick_without_a_store_says_so_rather_than_silently_dropping_it(qgis_app, tmp_path):
    """A SiteSession built with no SiteLayers -- which most tests in this
    file do -- has nowhere to put a pick. Silence would look exactly like
    a successful pick."""
    from nsgeo.geometry.grid import Grid
    from nsgeo.geometry.placement import GridPlacement
    from nsgeo.model.survey import Line
    from plugin_testing import synthetic_dzt

    session = SiteSession()
    session.new_site(tmp_path)
    session.add_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5))
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT", n_traces=60)
    session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0, 0.0, 1, p.stem))])
    session.open_line("raw/FILE__001.DZT")

    with pytest.raises(RuntimeError, match="pick store"):
        session.add_pick("raw/FILE__001.DZT", 3, 10.0)


def test_picks_for_reads_back_through_the_store(pickable):
    session, layers, keys = pickable
    session.add_pick(keys[0], 40, 30.0)
    session.add_pick(keys[0], 5, 10.0)

    assert [(p.trace, p.time_ns) for p in session.picks_for(keys[0])] == [(5, 10.0), (40, 30.0)]
    assert session.picks_for(keys[1]) == []


def test_picks_for_is_empty_with_no_store_rather_than_raising(qgis_app, tmp_path):
    """Reading is not authoring: a dock asking "what picks are on this
    line" before any layers exist gets an honest empty answer, where
    add_pick would raise. A read that raised would abort the CI container
    from inside a render slot."""
    session = SiteSession()
    assert session.picks_for("raw/FILE__001.DZT") == []


@needs_real_data
def test_a_pick_on_a_real_line_lands_in_that_files_own_time_window(qgis_app, tmp_path):
    """Spec §7: real data is the primary validation. Every synthetic
    fixture above shares one header; a real GSSI file has its own
    `position_ns`, `dt_ns`, `n_samples` and dielectric, and those four
    are exactly what turn a click position into a clamped time and a
    depth. A clamp computed against the synthetic header would pass all
    of the above and be wrong on every real file.
    """
    from nsgeo.geometry.grid import Grid
    from nsgeo.geometry.placement import GridPlacement
    from nsgeo.model.survey import Line
    from nsgeo_qgis.layers import SiteLayers
    from qgis.core import QgsProject

    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    session.add_grid(GRID)
    line = Line.open(REAL_DZT[0], GridPlacement("A", "y", 0.0, 0.0, 1, "real"))
    session.add_lines([line])  # an absolute path is fine here; only save() cares
    key = session.keys()[0]
    session.open_line(key)
    header = session.line_for_key(key).header
    t_end = header.position_ns + (header.n_samples - 1) * header.dt_ns

    middle = session.add_pick(key, line.n_traces // 2, t_end / 2.0)
    past_the_end = session.add_pick(key, line.n_traces + 500, t_end * 10.0)

    assert middle.time_ns == pytest.approx(t_end / 2.0)
    assert middle.depth_m is not None and middle.depth_m > 0.0
    assert past_the_end.trace == line.n_traces - 1
    assert past_the_end.time_ns == pytest.approx(t_end)
    assert layers.feature_count("picks") == 2
    layers.detach()
    project.clear()
```

(`test_plugin_map_link.py::test_hovering_a_real_line_previews_its_real_trace`, ~line 519, is the precedent for this setup — an absolute `REAL_DZT[0]` path goes straight into `add_lines`; only `save()` cares about absolute paths, and this test never saves.)

- [ ] **Step 2: Run the tests to verify they fail**

```bash
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest \
  packages/nsgeo-qgis/tests/qgis/test_plugin_session.py -q -p no:xonsh 2>&1 | tail -20
```

Expected: the new tests fail with `AttributeError: 'SiteSession' object has no attribute 'add_pick'`. Everything pre-existing still passes.

- [ ] **Step 3: Write `add_pick` and `picks_for`**

Add `import json` and `import math` to `session.py`'s imports (`datetime as _dt` was added in Task 1).

Add to the `# ---- picks (spec §4) ----` section, after `set_pick_store`:

```python
    def add_pick(self, key: str, trace: int, time_ns: float) -> Pick:
        """Author one pick on the WORKING line.

        `key` must be `current_key`. This is the same guard `set_trace`
        and `set_selection` carry, and it exists here rather than only in
        the dock for the reason spec §3.3 gives: `current_key` is what
        every destructive operation resolves through, and a preview must
        never reach one. M7's reviews found three separate attempts by a
        preview to reach a write; the structural answer is to refuse in
        the session, where no caller can forget.

        Unlike `set_trace`, this RAISES rather than returning silently. A
        trace that does not move is invisible and harmless; a pick that
        does not appear is authored data lost with no message. The caller
        is `plugin.py`'s relay, which puts the reason on the message bar.

        `picks_changed` is emitted only after the store's write returns:
        announcing a pick that is not on disk is the worst report
        available for the one table `survey.nsgeo.json` cannot
        regenerate.

        Does NOT dirty the session. A pick goes straight into the
        GeoPackage; `survey.nsgeo.json` is untouched, so `Save site`
        would have nothing to write and prompting for it would be a lie.
        """
        if key != self._current_key:
            raise ValueError(
                f"a pick targets the working line ({self._current_key!r}), not {key!r}; "
                f"select the line on the map to work on it"
            )
        if self._pick_store is None:
            raise RuntimeError("no pick store is attached to this session; cannot author a pick")
        if not math.isfinite(time_ns):
            raise ValueError(f"a pick needs a finite two-way time, not {time_ns!r}")
        line = self.line_for_key(key)
        index = max(0, min(int(trace), line.n_traces - 1))
        # The view emits a pick for any left click in the widget, and
        # ViewTransform.time_of_y does not clamp -- a click in the top
        # margin yields a time before the record starts. Clamped into the
        # line's own recorded window, the same way the trace is.
        t0 = float(line.header.position_ns)
        t_end = t0 + (line.header.n_samples - 1) * float(line.header.dt_ns)
        lo, hi = (t0, t_end) if t0 <= t_end else (t_end, t0)
        time = max(lo, min(float(time_ns), hi))
        model = self.resolved_velocity(key)
        # A plain list, not a numpy array: `depth_at`/`velocity_at` both
        # call `np.asarray` on whatever they are handed, so this keeps
        # numpy out of session.py's imports entirely for one scalar.
        times = [time]
        pick = Pick(
            line_key=key,
            trace=index,
            time_ns=time,
            distance_m=self._pick_distance(line, index),
            depth_m=float(model.depth_at(times)[0]),
            velocity_m_ns=float(model.velocity_at(times)[0]),
            # insert=False: reading the stack to record it must not be
            # what creates one. M7's Finding 4 is the same shape -- a
            # hovered line persisted an empty StepStack purely because
            # something asked for it.
            stack_json=json.dumps(self.stack_for(key, insert=False).to_dicts()),
            note="",
            created=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        )
        self._pick_store.write_pick(pick)
        self.picks_changed.emit()
        return pick

    @staticmethod
    def _pick_distance(line: Line, index: int) -> float | None:
        """Distance along the line at `index`, or None when the line has
        no distance axis at all. `Line.distance_along()` raises
        `ValueError` for a time-triggered acquisition
        (`traces_per_metre <= 0`); `ProfileDock._safe_distance` and
        `SiteLayers._line_points` already treat that as a property of the
        file rather than an error. Time is the truth here, so a missing
        distance is a null field, not a refused pick.
        """
        try:
            return float(line.distance_along()[index])
        except (ValueError, IndexError):
            return None

    def picks_for(self, key: str) -> list[Pick]:
        """Every pick on `key`, ordered by (trace, time).

        Empty rather than raising when no store is attached: this is read
        from a render slot, and a raise there reaches `qFatal()` in the
        CI container. Reading is not authoring, so unlike `add_pick`
        there is no invariant to protect -- a preview may show its own
        line's picks.
        """
        if self._pick_store is None:
            return []
        picks: list[Pick] = self._pick_store.picks_for(key)
        return picks
```

`session.py` needs no new numpy import for any of this — `VelocityModel.depth_at` and `velocity_at` both `np.asarray` their argument, so a one-element list is enough.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest \
  packages/nsgeo-qgis/tests/qgis/test_plugin_session.py -q -p no:xonsh 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 5: Prove the guard tests are not vacuous**

The refusal test is the most important test in this milestone, and a refusal test passes trivially against an implementation that refuses everything. Verify it discriminates, by mutation:

```bash
# Mutant: drop the working-line guard entirely.
python - <<'EOF'
import re, pathlib
p = pathlib.Path("packages/nsgeo-qgis/nsgeo_qgis/session.py")
s = p.read_text()
# Target add_pick's guard SPECIFICALLY. `if key != self._current_key:` appears
# THREE times in this file -- set_trace's and set_selection's come first -- so a
# plain replace(..., count=1) mutates set_trace instead and the mutation check
# reports a false pass. Anchor on the line that follows only add_pick's guard.
guard = '''        if key != self._current_key:
            raise ValueError('''
assert s.count(guard) == 1, "the anchor is no longer unique -- re-derive it"
s = s.replace(guard, '''        if False:
            raise ValueError(''', 1)
p.write_text(s)
EOF
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest \
  packages/nsgeo-qgis/tests/qgis/test_plugin_session.py -q -p no:xonsh -k add_pick 2>&1 | tail -5
git checkout packages/nsgeo-qgis/nsgeo_qgis/session.py
```

Expected: `test_add_pick_refuses_a_line_that_is_not_the_working_line` **fails** under the mutant. Record the observed failure in the task report. Restore the file (the `git checkout` above) and re-run to confirm green before moving on.

- [ ] **Step 6: Run both tiers and the linters, then commit**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh 2>&1 | tail -3
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh 2>&1 | tail -3
.venv/bin/ruff check . && .venv/bin/ruff format --check .
git add -A
git commit -m "feat: session.add_pick authors a pick on the working line

The guard lives here, beside set_trace's and set_selection's identical
ones, because current_key is what every destructive operation resolves
through and a preview must never reach one -- M7's reviews caught three
separate attempts. Unlike set_trace this raises rather than returning
silently: a trace that does not move is invisible and harmless, a pick
that does not appear is authored data lost with no message.

picks_changed fires only after the store's write returns. Announcing a
pick that is not on disk is the worst available report for the one table
survey.nsgeo.json cannot regenerate.

Co-Authored-By: <your own model name> <noreply@anthropic.com>"
git push
```

---

## Task 3: Pick mode, and the click that becomes a pick

The wiring task: two of the three orphans gain their first consumer, and `test_no_orphan_signals.py` goes red on purpose.

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_view.py` (`mousePressEvent` ~line 427-443)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (a new public method near `set_difference_index` ~line 567; `_pick` ~line 807)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (`__init__` ~line 126-130; `initGui` ~line 161-210; `_update_enabled` ~line 308)
- Modify: `packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py` (`SHADOWED`)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py`, `test_plugin_profile_dock.py`, `test_plugin_loads.py` (append to each)

**Interfaces:**
- Consumes: `SiteSession.add_pick` (Task 2); the pre-existing `ProfileView.set_pick_mode(flag)`, `ProfileView.pick_requested(int, float)`, `ProfileDock.pick_requested(str, int, float)`, `ProfileDock.error(str)`.
- Produces:
  - `ProfileDock.set_pick_mode(flag: bool) -> None`
  - `NsgeoPlugin.act_pick: QAction | None` — checkable.
  - `NsgeoPlugin._toggle_pick_mode(checked: bool) -> None`
  - `NsgeoPlugin._on_pick_requested(key: str, trace: int, time_ns: float) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py`. Its `view` fixture yields **`(v, rg)`** and has already set the axes from a real radargram; `QTest`, `QPoint`, `Qt`, `MARGIN_LEFT` and `MARGIN_TOP` are all imported there already. The existing shift-click test at ~line 785 is the model for the click mechanics.

```python
# ---- picking: only inside the radargram (M8) -------------------------------


def test_a_shift_click_outside_the_image_rect_is_not_a_pick(view):
    """M8 adopts `pick_requested`, so where it fires is now load bearing.
    The press handler runs for the whole widget, including the axis
    margins, and `ViewTransform.time_of_y` does not clamp -- a shift
    click on the time-axis labels reaches it with a negative local y and
    used to emit a pick at a time before the record starts.
    `session.add_pick` clamps such a time into the record, which is
    exactly what would make the bad pick look plausible once written;
    refusing it here is what keeps it from being authored at all.

    MARGIN_LEFT is 56 and MARGIN_TOP is 8 (profile_view.py:42), so both
    out-of-rect points below are real widget coordinates, not clamped to
    zero.
    """
    v, _rg = view
    picks = []
    v.pick_requested.connect(lambda t, ns: picks.append((t, ns)))
    r = v.image_rect()
    assert r.left() >= 10 and r.top() >= 5, "the margins must be wide enough to click in"

    # Inside the radargram: a pick.
    QTest.mouseClick(
        v,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.ShiftModifier,
        QPoint(r.left() + 10, r.top() + 10),
    )
    assert len(picks) == 1

    # In the left margin (the time axis) and above the top edge: not picks.
    for pos in (
        QPoint(r.left() - 5, r.top() + 10),
        QPoint(r.left() + 10, r.top() - 5),
    ):
        QTest.mouseClick(v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, pos)
    assert len(picks) == 1


def test_pick_mode_also_ignores_a_click_outside_the_radargram(view):
    """The same bound applies to the mode, not only to Shift+click --
    with pick mode on, the whole widget is a crosshair, so the margins
    are the easiest place to click by accident."""
    v, _rg = view
    picks = []
    v.pick_requested.connect(lambda t, ns: picks.append((t, ns)))
    v.set_pick_mode(True)
    r = v.image_rect()

    QTest.mouseClick(
        v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(r.left() - 5, r.top() + 10)
    )
    assert picks == []

    QTest.mouseClick(
        v, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(r.left() + 10, r.top() + 10)
    )
    assert len(picks) == 1
```

Append to `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py`. Add `Qt` to its imports: `from qgis.PyQt.QtCore import Qt`. Its two existing fixtures yield **different shapes** — `opened` yields `(session, dock, key, line)`, `previewing` yields `(dock, session, keys)`. Unpack each as written below; do not assume they match.

```python
# ---- pick mode and pick refusal (M8, spec §4.1, §4.3) ----------------------


def test_set_pick_mode_reaches_the_view(opened):
    """`ProfileView.set_pick_mode` shipped in Plan 2 with no caller at
    all -- a manual tester found it, went looking for a pick mode, and
    concluded the build was broken rather than that the feature was
    unbuilt (spec §1). This is its first consumer."""
    session, dock, key, line = opened
    dock.set_pick_mode(True)
    assert dock.view.cursor().shape() == Qt.CursorShape.CrossCursor
    dock.set_pick_mode(False)
    assert dock.view.cursor().shape() == Qt.CursorShape.ArrowCursor


def test_a_pick_while_previewing_is_refused_out_loud(previewing):
    """M7 guarded this and returned silently, because nothing consumed
    the signal yet. Now that a pick is real, silence is indistinguishable
    from a pick that landed -- the user shift-clicks a previewed line and
    nothing whatever happens. The guard stays; it just says why now."""
    dock, session, keys = previewing
    # The `previewing` fixture supplies two LOADED lines -- it does not
    # itself enter a preview. `ProfileDock._preview_key` is set only by
    # `_enter_preview`, which the session's preview signal drives, so
    # without this call the dock is not previewing at all and `_pick`
    # takes its ordinary path. Every sibling preview test in this file
    # makes the same call for the same reason.
    session.set_preview(keys[1], 5)
    emitted = []
    errors = []
    dock.pick_requested.connect(lambda k, t, ns: emitted.append((k, t, ns)))
    dock.error.connect(errors.append)

    dock.view.pick_requested.emit(20, 15.0)

    assert emitted == []
    assert len(errors) == 1
    assert "preview" in errors[0].lower()
```

Append to `packages/nsgeo-qgis/tests/qgis/test_plugin_loads.py`. That file has **no plugin fixture** — every test there builds one inline with `nsgeo_qgis.classFactory(fake_iface)`, calls `initGui()`, and calls `unload()` at the end. Follow that pattern; do not introduce a fixture, which would change how the file's existing tests are read. Its imports today are just `import nsgeo_qgis`; add `import pytest` and `from qgis.PyQt.QtCore import Qt`.

```python
# ---- the pick tool, end to end through the plugin (M8, spec §4.1) ----------


def _plugin_with_one_line(fake_iface, tmp_path):
    """A loaded plugin over a site with one placed line, open as the
    working line. Returns (plugin, key) -- the caller calls unload()."""
    from nsgeo.geometry.grid import Grid
    from nsgeo.geometry.placement import GridPlacement
    from nsgeo.model.survey import Line
    from plugin_testing import synthetic_dzt

    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    plugin.session.new_site(tmp_path)
    plugin.session.add_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5))
    p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT", n_traces=60)
    plugin.session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0, 0.0, 1, p.stem))])
    key = plugin.session.keys()[0]
    plugin.session.open_line(key)
    return plugin, key


def test_the_pick_action_is_a_checkable_toggle_that_drives_the_view(fake_iface, tmp_path):
    plugin, _key = _plugin_with_one_line(fake_iface, tmp_path)
    try:
        assert plugin.act_pick is not None
        assert plugin.act_pick.isCheckable()

        plugin.act_pick.setChecked(True)
        plugin.act_pick.triggered.emit(True)
        assert plugin.profile_dock.view.cursor().shape() == Qt.CursorShape.CrossCursor

        plugin.act_pick.setChecked(False)
        plugin.act_pick.triggered.emit(False)
        assert plugin.profile_dock.view.cursor().shape() == Qt.CursorShape.ArrowCursor
    finally:
        plugin.unload()


def test_the_pick_action_is_disabled_until_a_line_is_open(fake_iface, tmp_path):
    """A crosshair over an empty profile invites a click that can do
    nothing. The action follows the working line, not merely the site."""
    plugin = nsgeo_qgis.classFactory(fake_iface)
    plugin.initGui()
    try:
        assert plugin.act_pick.isEnabled() is False

        from nsgeo.geometry.grid import Grid
        from nsgeo.geometry.placement import GridPlacement
        from nsgeo.model.survey import Line
        from plugin_testing import synthetic_dzt

        plugin.session.new_site(tmp_path)
        plugin.session.add_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5))
        p = synthetic_dzt(tmp_path / "raw", "FILE__001.DZT", n_traces=60)
        plugin.session.add_lines([Line.open(p, GridPlacement("A", "y", 0.0, 0.0, 1, p.stem))])
        # A site with no line open yet: still disabled.
        assert plugin.act_pick.isEnabled() is False

        plugin.session.open_line(plugin.session.keys()[0])
        assert plugin.act_pick.isEnabled() is True

        plugin.session.close_site()
        assert plugin.act_pick.isEnabled() is False
    finally:
        plugin.unload()


def test_disabling_the_pick_action_also_turns_the_crosshair_off(fake_iface, tmp_path):
    """Closing the site with the toggle still checked would otherwise
    leave the view in pick mode forever: the action greys out, so there
    is no control left to switch it back."""
    plugin, _key = _plugin_with_one_line(fake_iface, tmp_path)
    try:
        plugin.act_pick.setChecked(True)
        plugin.act_pick.triggered.emit(True)
        assert plugin.profile_dock.view.cursor().shape() == Qt.CursorShape.CrossCursor

        plugin.session.close_site()

        assert plugin.act_pick.isChecked() is False
        assert plugin.profile_dock.view.cursor().shape() == Qt.CursorShape.ArrowCursor
    finally:
        plugin.unload()


def test_a_pick_from_the_profile_reaches_the_picks_table(fake_iface, tmp_path):
    """The whole loop: ProfileView -> ProfileDock.pick_requested ->
    plugin -> session.add_pick -> SiteLayers -> the picks layer."""
    plugin, key = _plugin_with_one_line(fake_iface, tmp_path)
    try:
        plugin.profile_dock.view.pick_requested.emit(12, 18.0)

        assert plugin.layers.feature_count("picks") == 1
        feat = next(plugin.layers.layers["picks"].getFeatures())
        assert feat["line_key"] == key
        assert feat["trace"] == 12
        assert feat["time_ns"] == pytest.approx(18.0)
    finally:
        plugin.unload()


def test_a_pick_that_cannot_be_written_is_reported_not_swallowed(
    fake_iface, tmp_path, monkeypatch
):
    """session.add_pick raises by design. It is never connected directly
    to a signal: an exception escaping a slot reaches qFatal() in the CI
    container and aborts the job. The relay catches it and puts the
    reason on the message bar, where someone authoring data will see
    it."""
    plugin, _key = _plugin_with_one_line(fake_iface, tmp_path)
    try:
        said = []
        monkeypatch.setattr(plugin, "message", lambda text, *a, **kw: said.append(text))

        def boom(pick):
            raise RuntimeError("disk full")

        monkeypatch.setattr(plugin.layers, "write_pick", boom)
        plugin.profile_dock.view.pick_requested.emit(12, 18.0)

        assert plugin.layers.feature_count("picks") == 0
        assert any("disk full" in text for text in said)
    finally:
        plugin.unload()
```

Note the `try/finally` around every one: `unload()` must run even on a failing assertion, or a leaked dock and toolbar follow the failure into every later test in the tier.

**`unload()` on a dirty session raises a modal, and the conftest forbids it.** `_plugin_with_one_line` dirties the session (`add_grid`, `add_lines`) and never closes it, so `unload()` reaches `save_with_prompt(ask_first=True, allow_cancel=False)` → `QMessageBox.question`. Any test here that ends with the session still dirty must install `answer_modal(QMessageBox, "question", QMessageBox.StandardButton.Discard)` first — that is three of the five tests above. The two that call `session.close_site()` in their body do not need it: `close_site` clears the dirty flag and the site before emitting, so `unload()` short-circuits.

Finally, update the pin in `packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py`:

```python
    # ProfileView.pick_requested is connected (profile_dock.py wires it to
    # `_pick`). ProfileDock's own pick_requested is connected too as of
    # M8: plugin.py wires it to `_on_pick_requested`, which calls
    # session.add_pick. Both declarations now have a consumer, so this
    # entry no longer hides an orphan -- it stays pinned because a
    # name-keyed count still cannot tell the two apart, and dropping to
    # one connect again would mean one of them had been orphaned.
    "pick_requested": {"declared": 2, "connects": 2},
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q -p no:xonsh 2>&1 | tail -20
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest \
  packages/nsgeo-qgis/tests/qgis/test_plugin_profile_view.py \
  packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py \
  packages/nsgeo-qgis/tests/qgis/test_plugin_loads.py -q -p no:xonsh 2>&1 | tail -20
```

Expected: `test_shadowed_signals_match_their_pinned_shape` fails in the pure tier (the pin says 2 connects, there is still 1) — that is the correct failure and it goes green when Step 5 lands. The QGIS tests fail on `plugin.act_pick` and `dock.set_pick_mode` not existing.

- [ ] **Step 3: Refuse a pick click outside the radargram**

In `profile_view.py`, `mousePressEvent`, inside the `LeftButton` branch:

```python
        if event.button() == Qt.MouseButton.LeftButton:
            shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if self._pick_mode or shift:
                # Only inside the radargram itself. This handler runs for
                # the whole widget, axis margins included, and
                # `time_of_y` does not clamp -- a shift click on the
                # depth-axis label reaches here with a negative local y
                # and would author a pick at a time before the record
                # starts. `add_pick` clamps such a time into the record,
                # which is precisely what makes the bad pick look
                # plausible once written. Hover already applies the same
                # bound (`_handle_mouse_move`'s `0 <= x < width`); this
                # is that rule for the other axis and the other gesture.
                if not (0 <= x < self.transform.width and 0 <= y < self.transform.height):
                    return
                self.pick_requested.emit(
                    self.transform.trace_index_at(x), self.transform.time_of_y(y)
                )
                return
```

- [ ] **Step 4: Add `set_pick_mode` and the spoken refusal to `ProfileDock`**

In `profile_dock.py`, add the public method immediately before `set_difference_index`:

```python
    def set_pick_mode(self, flag: bool) -> None:
        """Turn the profile's pick mode on or off.

        A passthrough, deliberately: `plugin.py` owns the toolbar toggle
        and must not reach into `self.view` past the dock that owns it.
        `ProfileView.set_pick_mode` shipped in Plan 2 with no caller
        anywhere -- a manual tester found it, went looking for a pick
        mode, and concluded the build was broken rather than that the
        feature was unbuilt (spec §1, §6). This is its first consumer.
        """
        self.view.set_pick_mode(bool(flag))
```

In `_pick`, replace the bare `return` in the preview branch (keep the existing comment above it — it explains the guard, which is still exactly right — and add to it):

```python
    def _pick(self, trace: int, time_ns: float) -> None:
        if self._preview_key is not None:
            # A preview never authors data (spec §3.3, §4.3). `self._key`
            # is the DISPLAYED line, so without this a shift-click on a
            # previewed radargram would emit a pick for a line the user
            # only hovered.
            #
            # M8: this used to return silently, which was right while
            # nothing consumed `pick_requested` -- there was no pick to
            # miss. Now there is, and silence is indistinguishable from a
            # pick that worked: the user shift-clicks a previewed line
            # and nothing whatever happens, which is the same complaint
            # issue #33 records about steps that "disappear". The guard
            # is unchanged; it says why now. `session.add_pick` refuses
            # the same write independently -- this is the message, not
            # the protection.
            self.error.emit(
                "picks are authored on the working line; this is a preview — "
                "select the line on the map to work on it"
            )
            return
```

Leave the rest of `_pick` — the `I6` comment block and the `try/except` around the emit — exactly as it is.

- [ ] **Step 5: Add the toolbar toggle and the relay to `plugin.py`**

In `NsgeoPlugin.__init__`, beside the other action attributes:

```python
        self.act_pick: QAction | None = None
```

In `initGui`, after the `act_import` line:

```python
        self.toolbar.addSeparator()
        self.act_pick = self._toolbar_action("Pick", self._toggle_pick_mode)
        self.act_pick.setCheckable(True)
        self.act_pick.setToolTip(
            "Pick mode: click the profile to author a pick. Shift+click works with this off."
        )
```

`_toolbar_action` connects `triggered`, which for a checkable action passes the new checked state.

After `self.profile_dock.error.connect(...)` in `initGui`:

```python
        self.profile_dock.pick_requested.connect(self._on_pick_requested)
```

Connect the enablement to the working line as well, alongside the existing two connections at the end of `initGui`:

```python
        self._update_enabled()
        self.session.site_opened.connect(self._update_enabled)
        self.session.site_closed.connect(self._update_enabled)
        # The pick action follows the WORKING LINE, not merely the site
        # (see _update_enabled), so it has to be re-evaluated when that
        # changes -- line_opened carries "" when there is none.
        self.session.line_opened.connect(self._update_enabled)
```

Extend `_update_enabled`:

```python
    def _update_enabled(self, *_: Any) -> None:
        try:
            is_open = self.session is not None and self.session.is_open
            for act in (self.act_save, self.act_add_grid, self.act_import):
                if act is not None:
                    act.setEnabled(is_open)
            # A crosshair over an empty profile invites a click that can
            # do nothing, so this one needs a working line and not merely
            # an open site. Turning it off also has to turn the MODE off:
            # a checked-but-disabled action leaves the view in pick mode
            # with no control left to switch it back.
            has_line = is_open and self.session.current_key is not None
            if self.act_pick is not None:
                self.act_pick.setEnabled(has_line)
                if not has_line and self.act_pick.isChecked():
                    self.act_pick.setChecked(False)
                    self._toggle_pick_mode(False)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            self.message(f"could not update the toolbar: {exc}", Qgis.MessageLevel.Warning)
```

(`_update_enabled` gains `*_` because `line_opened` passes a key.)

Add the two new slots beside `_on_gain_points`:

```python
    def _toggle_pick_mode(self, checked: bool) -> None:
        """The Pick toolbar toggle. Drives the dock, never the view
        directly: `ProfileDock` owns `ProfileView`."""
        try:
            if self.profile_dock is None:
                return
            self.profile_dock.set_pick_mode(bool(checked))
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            self.message(f"could not change the pick mode: {exc}", Qgis.MessageLevel.Warning)

    def _on_pick_requested(self, key: str, trace: int, time_ns: float) -> None:
        """Relay a pick from the profile to the session.

        `session.add_pick` is NEVER connected to a signal directly. It
        raises by design -- on a non-working line, on a non-finite time,
        on a failed provider write -- and an exception escaping a slot
        prints and passes on this build but reaches `qFatal()` in the
        `qgis/qgis:ltr` container and aborts the whole job. It also has
        somewhere better to go: a pick is authored data with no other
        source of truth, so the reason it did not land belongs on the
        message bar, not in a log the user is not reading.
        """
        try:
            if self.session is None:
                return
            self.session.add_pick(key, trace, time_ns)
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            self.message(f"could not author the pick: {exc}", Qgis.MessageLevel.Critical)
```

Check `unload()` for the list of actions it tears down — `self.toolbar_actions` already covers `act_pick` because `_toolbar_action` appends to it, but confirm `unload()` does not also enumerate the `act_*` attributes by name; if it does, add `act_pick` there too.

- [ ] **Step 6: Run the tests to verify they pass**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh 2>&1 | tail -3
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh 2>&1 | tail -3
```

Expected: both green, both above their baselines. The pure tier goes back to `367 passed, 2 skipped` once the pin matches reality.

- [ ] **Step 7: Confirm the orphan check still discriminates**

The pin was edited this task, so prove the edited check still catches what it exists to catch. In a scratch copy of the package (never in the working tree), inject an unconnected `pick_requested = pyqtSignal()` on a third class and confirm `test_shadowed_signals_match_their_pinned_shape` fails on the `declared` count. Restore, re-run, record both results in the task report.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: a click on the profile authors a pick

Adopts two of Plan 2's three orphaned pick APIs: ProfileDock.pick_requested
gains its first consumer in plugin.py, and ProfileView.set_pick_mode gains
one behind a checkable toolbar toggle. The no-orphan check's pin moves from
one connect to two, which is the notification it was built to give.

add_pick is reached through a plugin slot rather than connected directly:
it raises by design, and an exception escaping a slot reaches qFatal() in
the LTR container. The reason a pick did not land goes on the message bar,
where a user authoring data will see it.

A pick refused because a preview is showing now says so. The guard is
unchanged -- silence was right while nothing consumed the signal, and
became indistinguishable from success the moment something did.

Co-Authored-By: <your own model name> <noreply@anthropic.com>"
git push
```

---

## Task 4: Picks on the profile

The third orphan, `picks_changed`, gains its consumer, and the pick the user just made becomes visible where they made it.

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/profile_dock.py` (`__init__` connections ~line 214-222; `_show_line` ~line 370-415; a new slot beside `_on_stack_changed`)
- Modify: `packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py` (`KNOWN_UNCONSUMED`)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py` (append)

**Interfaces:**
- Consumes: `SiteSession.picks_for(key)` and `SiteSession.picks_changed` (Task 2); the pre-existing `ProfileView.set_picks(list[tuple[int, float]])`.
- Produces: `ProfileDock._refresh_picks() -> None` (private; called from `_show_line` and the `picks_changed` slot).

- [ ] **Step 1: Write the failing tests**

Append to `packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py`. These need a dock whose session has layers behind it; check whether `opened` already provides that — M7's fixtures build a bare `SiteSession`. If it does not, add this fixture rather than changing `opened`, which many tests depend on:

```python
# ---- picks on the profile (M8, spec §4.3) ----------------------------------


@pytest.fixture
def dock_with_picks(qgis_app, tmp_path):
    """A ProfileDock over a session that can actually store picks."""
    from nsgeo.geometry.grid import Grid
    from nsgeo.geometry.placement import GridPlacement
    from nsgeo.model.survey import Line
    from nsgeo_qgis.layers import SiteLayers
    from plugin_testing import synthetic_dzt
    from qgis.core import QgsProject

    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    session.add_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5))
    lines = []
    for i in range(2):
        p = synthetic_dzt(tmp_path / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
        lines.append(Line.open(p, GridPlacement("A", "y", i * 0.5, 0.0, 1, p.stem)))
    session.add_lines(lines)
    keys = session.keys()
    dock = ProfileDock(session)
    session.open_line(keys[0])
    yield dock, session, layers, keys
    dock.deleteLater()
    layers.detach()
    project.clear()


def test_a_new_pick_appears_on_the_profile_without_reopening_the_line(dock_with_picks):
    """`picks_changed` was declared in Plan 2, never emitted and never
    connected (spec §1). This is its first consumer, and the reason it
    exists: a pick the user just made has to show up where they made
    it."""
    dock, session, layers, keys = dock_with_picks
    assert dock.view._picks == []

    session.add_pick(keys[0], 12, 18.0)

    assert dock.view._picks == [(12, 18.0)]


def test_opening_a_line_shows_the_picks_already_on_it(dock_with_picks):
    dock, session, layers, keys = dock_with_picks
    session.add_pick(keys[0], 5, 10.0)
    session.open_line(keys[1])
    assert dock.view._picks == []

    session.open_line(keys[0])

    assert dock.view._picks == [(5, 10.0)]


def test_a_preview_shows_the_previewed_lines_own_picks(dock_with_picks):
    """Reading is not authoring. The view follows `display_key`, so a
    preview shows the hovered line's picks -- the point of a preview is
    to see what is on that line, interpretation included -- while
    `add_pick` still refuses to write there."""
    dock, session, layers, keys = dock_with_picks
    session.add_pick(keys[0], 5, 10.0)
    session.open_line(keys[1])
    session.add_pick(keys[1], 44, 33.0)
    session.open_line(keys[0])

    session.set_preview(keys[1], 20)
    assert dock.view._picks == [(44, 33.0)]

    session.clear_preview()
    assert dock.view._picks == [(5, 10.0)]


def test_closing_the_site_clears_the_picks_from_the_view(dock_with_picks):
    dock, session, layers, keys = dock_with_picks
    session.add_pick(keys[0], 5, 10.0)

    session.close_site()

    assert dock.view._picks == []


def test_a_failing_pick_read_is_logged_not_escaped(dock_with_picks, monkeypatch, message_log):
    """`picks_changed` is a Qt signal, so this slot's body runs under
    C++: an exception escaping it reaches qFatal() in the LTR container.
    The conftest's `_no_swallowed_slot_exceptions` fixture is what turns
    a regression here into a local red test."""
    dock, session, layers, keys = dock_with_picks

    def boom(key):
        raise RuntimeError("the picks table went away")

    monkeypatch.setattr(session, "picks_for", boom)
    session.picks_changed.emit()

    assert any("the picks table went away" in m for m in message_log)
```

And remove `picks_changed` from `KNOWN_UNCONSUMED` in `packages/nsgeo-qgis/tests/pure/test_no_orphan_signals.py`, along with its now-obsolete comment. Update the module docstring's NOTE block while you are there: the real orphan set is now down to the three dead `SurveyDock` signals.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-qgis/tests/pure -q -p no:xonsh 2>&1 | tail -10
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest \
  packages/nsgeo-qgis/tests/qgis/test_plugin_profile_dock.py -q -p no:xonsh 2>&1 | tail -20
```

Expected: `test_every_declared_signal_has_a_connect` fails in the pure tier (`picks_changed` left the allowlist and has no connect yet) — the correct failure. The QGIS tests fail on `dock.view._picks` staying empty.

- [ ] **Step 3: Feed the view from the session**

In `profile_dock.py`, add the connection with the others in `__init__`, after `session.stack_changed.connect(self._on_stack_changed)`:

```python
        session.picks_changed.connect(self._on_picks_changed)
```

Add the slot and the helper beside `_on_stack_changed`:

```python
    def _on_picks_changed(self) -> None:
        try:
            self._refresh_picks()
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not refresh the picks on the profile: {exc}", Qgis.MessageLevel.Critical)

    def _refresh_picks(self) -> None:
        """Put the DISPLAYED line's picks on the view.

        `self._key`, not `_working_key`: a preview shows the hovered
        line's own picks, because seeing what has been interpreted on a
        line is most of the point of glancing at it. That is not a breach
        of spec §3.3 -- reading is not authoring, and `session.add_pick`
        refuses a preview independently. `picks_changed` carries no key
        (it is a "something changed" signal), so this recomputes from
        whatever is on screen rather than filtering on one.
        """
        key = self._key
        if key is None:
            self.view.set_picks([])
            return
        self.view.set_picks([(p.trace, p.time_ns) for p in self.session.picks_for(key)])
```

At the end of `_show_line`, after `self._refresh_velocity()`:

```python
        self._refresh_picks()
```

`_show_line` is the one place both `_open` (the working line) and `_enter_preview` (a preview) configure the view, which is why this goes there and not in each caller. `_clear_view_only` needs nothing: `ProfileView.clear()` already resets `_picks` to `[]`.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh 2>&1 | tail -3
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh 2>&1 | tail -3
```

Expected: both green and above baseline.

- [ ] **Step 5: See it, do not only assert it**

An invisible banner survived three code reviews in M7 and died to one measurement. `_paint_picks` has one existing unit test (`test_set_picks_renders_a_marker_at_the_correct_position`, which calls `set_picks` by hand) but has never been exercised from a real `add_pick`. Render the widget and confirm a marker actually appears where the pick says it is:

```bash
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python - <<'PY'
import sys, tempfile
from pathlib import Path

sys.path.insert(0, "packages/nsgeo-qgis")
sys.path.insert(0, "packages/nsgeo-qgis/tests")

from qgis.core import QgsApplication, QgsProject
QgsApplication.setPrefixPath("/usr", True)
app = QgsApplication([], False)
app.initQgis()

from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.layers import SiteLayers
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.ui.profile_dock import ProfileDock
from plugin_testing import synthetic_dzt

tmp = Path(tempfile.mkdtemp())
project = QgsProject.instance()
session = SiteSession()
session.new_site(tmp)
layers = SiteLayers(session, project=project)
session.add_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5))
p = synthetic_dzt(tmp / "raw", "FILE__001.DZT", n_traces=240)
line = Line.open(p, GridPlacement("A", "y", 0.0, 0.0, 1, "FILE__001"))
session.add_lines([line])
key = session.keys()[0]
dock = ProfileDock(session)
dock.resize(900, 360)
dock.show()
session.open_line(key)
session.set_profiles(key, line.load())

before = dock.view.grab_image()
session.add_pick(key, 120, 40.0)
after = dock.view.grab_image()

# Bounding box of every pixel the pick changed.
xs, ys = [], []
for y in range(after.height()):
    for x in range(after.width()):
        if before.pixel(x, y) != after.pixel(x, y):
            xs.append(x)
            ys.append(y)
print("pick stored as:", [(pk.trace, pk.time_ns) for pk in session.picks_for(key)])
print("view holds:    ", dock.view._picks)
if not xs:
    print("CHANGED PIXELS: none -- the pick is INVISIBLE")
else:
    print(f"changed pixel box: x {min(xs)}..{max(xs)}  y {min(ys)}..{max(ys)}")
    r = dock.view.image_rect()
    want = dock.view._pick_positions(dock.view.transform)
    print("marker should be at (local):", want)
    print("i.e. widget coords:", [(r.left() + x, r.top() + y) for x, y in want])

dock.hide()
layers.detach()
project.clear()
app.exitQgis()
PY
```

Record both boxes in the task report. The changed-pixel box must straddle the reported marker position (`_paint_picks` draws a triangle five pixels either side and nine above the point). If it reports no changed pixels, the pick is invisible and that is a defect, not a cosmetic issue; if the boxes disagree, the pick is being drawn somewhere other than where it is stored.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: picks are drawn on the profile they were made on

picks_changed was declared in Plan 2, never emitted and never connected;
this is its first consumer and the last of the three orphans spec §1
recorded. The dock recomputes from the DISPLAYED line, so a preview shows
the hovered line's own interpretation -- reading is not authoring, and
add_pick refuses a preview independently.

Co-Authored-By: <your own model name> <noreply@anthropic.com>"
git push
```

---

## Task 5: Selecting a pick or a mark jumps to it; marks confirmed; the milestone closes

Lifetime and teardown code. `MapLink` currently binds one layer's `selectionChanged` and releases it in `dispose()`; this generalises that to three, which is precisely the shape of the leak (Item I4) that survived all of Plan 2 and the disposal-sentinel defect that Task 5 of M7 was reviewed for twice.

**Files:**
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/map_link.py` (`__init__` ~line 126-129; `_rebind_layer` ~line 364; `_on_selection` ~line 393; `dispose` ~line 599-606)
- Modify: `README.md`
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py` (append)

**Interfaces:**
- Consumes: `SiteSession.open_line`, `SiteSession.set_trace`, `SiteSession.keys` (all pre-existing); the `picks` and `marks` layers from `SiteLayers.layers`.
- Produces:
  - `MapLink.SELECTABLE: tuple[str, ...]` — `("lines", "picks", "marks")`.
  - `MapLink._on_pick_selection() / _on_mark_selection()` — private slots, one per layer so each connection is individually disconnectable.

- [ ] **Step 1: Write the failing tests**

Append to `packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py`. Two things about that file to get right before writing a line:

1. The `linked` fixture yields **`(link, session, layers, canvas, keys)`** — `link` first. Every test below unpacks it in that order.
2. `linked` writes **no DZX sidecar**, so its `marks` table is empty. The mark tests below add a third line that has one; `add_lines` emits `lines_changed`, which refills `marks`.

Add `QgsFeature`, `QgsGeometry` to the `qgis.core` import (`QgsPointXY` and `QgsProject` are already there).

```python
# ---- selecting a pick or a mark jumps to it (M8, spec §3.4, §4.4) ----------


MARK_DZX = """<?xml version="1.0" encoding="UTF-8"?>
<DZX xmlns="www.geophysical.com/DZX/1.02"><File><name>FILE__003.DZT</name>
<Profile><WayPt><scan>27</scan><mark>User</mark><name>Mark1</name></WayPt></Profile></File></DZX>"""


def _feature_with(layers, name, field, value):
    """The id of the one feature in `name` whose `field` equals `value`."""
    ids = [f.id() for f in layers.layers[name].getFeatures() if f[field] == value]
    assert len(ids) == 1, f"expected exactly one {name} with {field}={value!r}, got {len(ids)}"
    return ids[0]


def _add_a_marked_line(session, tmp_path):
    """A third line carrying a DZX mark at scan 27. `add_lines` emits
    lines_changed, which refills `marks` -- the `linked` fixture's own
    two lines have no sidecar, so without this the marks table is
    empty. Returns (key, scan)."""
    p = synthetic_dzt(tmp_path / "raw", "FILE__003.DZT", n_traces=60)
    (tmp_path / "raw" / "FILE__003.DZX").write_text(MARK_DZX)
    session.add_lines([Line.open(p, GridPlacement("A", "y", 4.0, 0.0, 1, p.stem))])
    return "raw/FILE__003.DZT", 27


def test_selecting_a_pick_opens_its_line_and_moves_the_trace(linked):
    """Spec §3.4's closing promise: "the same mechanism serves picks
    later: selecting a pick feature jumps to its line and trace." One
    gesture, QGIS's own Select tool, no map tool of ours."""
    link, session, layers, canvas, keys = linked
    session.open_line(keys[1])
    session.add_pick(keys[1], 33, 21.0)
    session.open_line(keys[0])
    assert session.current_key == keys[0]

    layers.layers["picks"].selectByIds([_feature_with(layers, "picks", "trace", 33)])

    assert session.current_key == keys[1]
    assert session.current_trace == 33


def test_selecting_a_mark_opens_its_line_and_moves_the_trace(linked, tmp_path):
    """Spec §4.4: `marks` stays derived and read-only, but a mark has to
    be navigable or it is decoration."""
    link, session, layers, canvas, keys = linked
    marked_key, scan = _add_a_marked_line(session, tmp_path)
    assert layers.feature_count("marks") == 1
    session.open_line(keys[0])

    layers.layers["marks"].selectByIds([_feature_with(layers, "marks", "scan", scan)])

    assert session.current_key == marked_key
    assert session.current_trace == scan


def test_the_marks_layer_stays_read_only(linked, tmp_path):
    """§4.4: M8 confirms marks render and are read-only; it does not make
    them editable. `marks` is derived from the DZX and refilled on every
    grid or line change, so an edit would be silently discarded."""
    link, session, layers, canvas, keys = linked
    _add_a_marked_line(session, tmp_path)
    assert layers.feature_count("marks") == 1  # it renders
    assert layers.layers["marks"].readOnly() is True
    assert layers.layers["picks"].readOnly() is False


def test_selecting_several_picks_at_once_jumps_nowhere(linked):
    """Same rule as a multi-selection of lines (spec §3.4): there is no
    single answer and guessing one is worse than doing nothing."""
    link, session, layers, canvas, keys = linked
    session.open_line(keys[1])
    session.add_pick(keys[1], 10, 12.0)
    session.add_pick(keys[1], 40, 25.0)
    session.open_line(keys[0])

    layers.layers["picks"].selectByIds(
        [
            _feature_with(layers, "picks", "trace", 10),
            _feature_with(layers, "picks", "trace", 40),
        ]
    )

    assert session.current_key == keys[0]


def test_a_pick_with_no_trace_jumps_to_the_line_and_stops_there(linked):
    """The picks layer is editable, so a hand-digitised row can carry a
    line_key and nothing else. Opening the line is still the right
    answer; `int(NULL)` inside this slot would abort the CI container."""
    link, session, layers, canvas, keys = linked
    layer = layers.layers["picks"]
    f = QgsFeature(layer.fields())
    f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(500.0, 700.0)))
    f["line_key"] = keys[1]
    assert layer.dataProvider().addFeatures([f])[0]
    session.open_line(keys[0])

    layer.selectByIds([_feature_with(layers, "picks", "line_key", keys[1])])

    assert session.current_key == keys[1]
    assert session.current_trace == -1


def test_a_disposed_link_stops_jumping_from_picks_and_marks(linked, tmp_path):
    """M7 Finding I1: `_on_lines_changed` re-armed a disposed link by
    calling `_rebind_layer` again. Three layers now, so the same failure
    has three ways to happen."""
    link, session, layers, canvas, keys = linked
    marked_key, scan = _add_a_marked_line(session, tmp_path)
    session.open_line(keys[1])
    session.add_pick(keys[1], 33, 21.0)
    session.open_line(keys[0])
    link.dispose()

    layers.layers["picks"].selectByIds([_feature_with(layers, "picks", "trace", 33)])
    assert session.current_key == keys[0]
    layers.layers["marks"].selectByIds([_feature_with(layers, "marks", "scan", scan)])
    assert session.current_key == keys[0]


def test_a_disposed_link_stays_disposed_when_the_layers_are_rebuilt(linked):
    """The disposal sentinel in `_on_lines_changed` covers all three
    bindings, not only `lines`."""
    link, session, layers, canvas, keys = linked
    session.open_line(keys[1])
    session.add_pick(keys[1], 33, 21.0)
    session.open_line(keys[0])
    link.dispose()

    session.lines_changed.emit()
    layers.layers["picks"].selectByIds([_feature_with(layers, "picks", "trace", 33)])

    assert session.current_key == keys[0]


def test_jumping_from_a_pick_still_works_after_the_site_is_reopened(linked):
    """A site reopen replaces every layer object (`detach()` empties the
    registry, `ensure_tables()` builds new ones), so a connection made
    once at construction would point at three dead wrappers and jumping
    would stop with no error at all -- the worst kind of stop. `lines`
    already has this test; picks need their own binding proved too."""
    link, session, layers, canvas, keys = linked
    session.open_line(keys[1])
    session.add_pick(keys[1], 33, 21.0)
    session.save()
    path = session.json_path

    session.close_site()
    session.open_site(path)
    keys = session.keys()
    session.open_line(keys[0])

    layers.layers["picks"].selectByIds([_feature_with(layers, "picks", "trace", 33)])

    assert session.current_key == keys[1]
    assert session.current_trace == 33


@needs_real_data
def test_selecting_a_real_files_mark_jumps_to_its_own_scan(qgis_app, tmp_path):
    """Spec §7: real data is the primary validation. The DZX above is a
    three-line fixture; a real GSSI sidecar carries its own scan numbers
    against its own trace count, and `refill_marks` clamps a scan into
    that count. Only a real pair proves the scan a mark reports is the
    trace the profile lands on.
    """
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    session.add_grid(GRID)
    marked = [p for p in REAL_DZT if p.with_suffix(".DZX").exists()]
    if not marked:
        pytest.skip("no real DZT has a DZX sidecar")
    lines = [
        Line.open(p, GridPlacement("A", "y", i * 2.0, 0.0, 1, p.stem))
        for i, p in enumerate(marked[:2])
    ]
    session.add_lines(lines)
    canvas = QgsMapCanvas()
    canvas.setDestinationCrs(layers.crs())
    link = MapLink(session, layers, canvas)
    keys = session.keys()
    session.open_line(keys[0])
    marks = list(layers.layers["marks"].getFeatures())
    if not marks:
        pytest.skip("the real DZX sidecars carry no marks")
    feat = next((f for f in marks if str(f["line_key"]) != keys[0]), marks[0])
    want_key, want_scan = str(feat["line_key"]), int(feat["scan"])

    layers.layers["marks"].selectByIds([feat.id()])

    assert session.current_key == want_key
    assert session.current_trace == want_scan
    link.dispose()
    layers.detach()
    project.clear()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest \
  packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py -q -p no:xonsh 2>&1 | tail -20
```

Expected: the jump tests fail (`current_key` unchanged); the read-only test passes already (that is the "confirms" half of §4.4 and needs no code).

- [ ] **Step 3: Bind all three layers**

In `map_link.py`, add `NULL` to the `qgis.core` import list. Add the class constant beside `HOVER_DWELL_MS`:

```python
    # Selecting a feature in any of these is a deliberate gesture that
    # navigates (spec §3.4). `lines` promotes; `picks` and `marks` jump to
    # a line AND a trace. QGIS's own Select tool, no tool slot of ours, no
    # stolen clicks.
    SELECTABLE = ("lines", "picks", "marks")
```

Replace the `_lines_layer_bound` attribute in `__init__` with a per-layer map, and build the slot table beside it:

```python
        # None means "not yet bound"; tracked per layer, and separately
        # from each `layers.layers[...]` lookup, for the reason
        # _rebind_layer gives. One NAMED slot per layer rather than a
        # lambda or `self.sender()`: a bound method is what
        # `disconnect()` can reliably take back off, and dispose() has to
        # be able to.
        self._bound: dict[str, QgsVectorLayer | None] = dict.fromkeys(self.SELECTABLE)
        self._selection_slots = {
            "lines": self._on_selection,
            "picks": self._on_pick_selection,
            "marks": self._on_mark_selection,
        }
        self._rebind_layer()
```

Replace `_lines_layer()`'s single-purpose body with a general lookup, keeping `_lines_layer` itself (the geometry cache and the hit test both call it):

```python
    def _selectable_layer(self, name: str) -> QgsVectorLayer | None:
        layer = self.layers.layers.get(name)
        if layer is None or sip.isdeleted(layer):
            return None
        return layer

    def _lines_layer(self) -> QgsVectorLayer | None:
        return self._selectable_layer("lines")
```

Rewrite `_rebind_layer`'s **body**. Do not retype its docstring: M7's Ruling 14 is exactly this situation — a plan handed an implementer a complete method that had been hardened across four review rounds, and following it literally would have dropped the hardening. Change the docstring's first line from "Follow the `lines` layer across rebuilds." to "Follow the selectable layers across rebuilds.", leave every existing paragraph below it untouched (the site-reopen reasoning is unchanged and is why this method exists at all), and append this one paragraph at the end of it:

```
        M8: three layers, not one. `picks` and `marks` are rebound on the
        same signals and released by the same `dispose()`, because a
        reopen replaces all four layer objects together -- binding only
        `lines` across a reopen while leaving pick and mark navigation
        pointing at dead wrappers would fail exactly the way this method
        exists to prevent, just less visibly.
```

Then replace everything below the docstring with:

```python
        for name in self.SELECTABLE:
            slot = self._selection_slots[name]
            old = self._bound.get(name)
            if old is not None and not sip.isdeleted(old):
                # Same two exceptions dispose() suppresses around this
                # same disconnect call, and for the same reason: a
                # RuntimeError from a wrapper that reports as not-deleted
                # but whose underlying C++ object is gone regardless must
                # not abort this method before the remaining layers are
                # bound below.
                with contextlib.suppress(TypeError, RuntimeError):
                    old.selectionChanged.disconnect(slot)
            layer = self._selectable_layer(name)
            self._bound[name] = layer
            if layer is not None:
                layer.selectionChanged.connect(slot)
```

Keep `_on_selection` exactly as it is (it is the `lines` slot) and add the two new ones plus the shared body beneath it:

```python
    def _on_pick_selection(self, *_: Any) -> None:
        try:
            self._jump_to_feature("picks", "trace")
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not jump to the selected pick: {exc}", Qgis.MessageLevel.Critical)

    def _on_mark_selection(self, *_: Any) -> None:
        try:
            self._jump_to_feature("marks", "scan")
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            _log(f"could not jump to the selected mark: {exc}", Qgis.MessageLevel.Critical)

    def _jump_to_feature(self, name: str, trace_field: str) -> None:
        """Open the selected feature's line and put the cursor on its
        trace (spec §3.4's closing promise, and §4.4 for marks).

        `open_line` first, `set_trace` second, and not the other way
        round: `set_trace` structurally ignores a key that is not
        `current_key`, so a trace set before the promotion would be
        silently dropped. That ordering is the whole reason this is one
        method rather than two call sites.

        Promotion goes through `session.open_line`, the same path the
        survey tree and the `lines` layer already use, so no two ways of
        opening a line can diverge.
        """
        layer = self._selectable_layer(name)
        if layer is None or not self.session.is_open:
            return
        ids = layer.selectedFeatureIds()
        if len(ids) != 1:
            # A multi-selection has no single answer, and guessing one is
            # worse than doing nothing (spec §3.4). An empty selection is
            # the ordinary result of clicking empty map and must not
            # close the line the user is working on.
            return
        feature = layer.getFeature(ids[0])
        key = str(feature["line_key"])
        if key not in self.session.keys():  # noqa: SIM118 -- SiteSession.keys(), not a dict
            return
        self.session.open_line(key)
        trace = feature[trace_field]
        if trace == NULL:
            # `picks` is editable, so a hand-digitised row can carry a
            # line_key and nothing else. Opening its line is still the
            # right answer; `int(NULL)` raises, and this runs in a slot.
            return
        self.session.set_trace(key, int(trace))
```

In `dispose()`, replace the single-layer unbind block with the loop, keeping the surrounding docstring paragraph and updating its wording from "The `lines` layer's `selectionChanged` connection" to "Each selectable layer's `selectionChanged` connection":

```python
        # The selectable layers are rebound across every site reopen (see
        # _rebind_layer), so disposal has to release whichever instances
        # are currently bound -- guarded the same way as the canvas above,
        # and for the same reason: nothing here may abort before the
        # scene-removal loop below.
        for name in self.SELECTABLE:
            layer = self._bound.get(name)
            self._bound[name] = None
            if layer is not None and not sip.isdeleted(layer):
                with contextlib.suppress(TypeError, RuntimeError):
                    layer.selectionChanged.disconnect(self._selection_slots[name])
```

Leave `_on_lines_changed`'s disposal sentinel (`if self._marker is None or self._band is None: return`) alone — it already covers the rebind for all three.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest \
  packages/nsgeo-qgis/tests/qgis/test_plugin_map_link.py -q -p no:xonsh 2>&1 | tail -20
```

Expected: all pass, including every M7 test in the file unchanged.

- [ ] **Step 5: Prove disposal really releases three connections**

Counting scene items across create/destroy cycles is already tested (M7). What is new is three signal connections, and a connection that survives disposal is invisible to every test above — it only shows up as a disposed link quietly promoting again. Verify by execution rather than by reading:

```bash
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python - <<'PY'
import sys, tempfile
from pathlib import Path

sys.path.insert(0, "packages/nsgeo-qgis")
sys.path.insert(0, "packages/nsgeo-qgis/tests")

from qgis.core import QgsApplication, QgsProject
QgsApplication.setPrefixPath("/usr", True)
app = QgsApplication([], False)
app.initQgis()

from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line
from nsgeo_qgis.layers import SiteLayers
from nsgeo_qgis.map_link import MapLink
from nsgeo_qgis.session import SiteSession
from plugin_testing import synthetic_dzt
from qgis.gui import QgsMapCanvas

tmp = Path(tempfile.mkdtemp())
project = QgsProject.instance()
session = SiteSession()
session.new_site(tmp)
layers = SiteLayers(session, project=project)
session.add_grid(Grid("A", (500.0, 700.0), 12.0, 5.0, 11.0, "EPSG:32616", 0.5))
for i in range(2):
    p = synthetic_dzt(tmp / "raw", f"FILE__00{i + 1}.DZT", n_traces=60)
    session.add_lines([Line.open(p, GridPlacement("A", "y", i * 2.0, 0.0, 1, p.stem))])
canvas = QgsMapCanvas()
canvas.setDestinationCrs(layers.crs())


def counts(label):
    # receivers() counts connections to a signal on that object.
    got = {
        name: layers.layers[name].receivers(layers.layers[name].selectionChanged)
        for name in MapLink.SELECTABLE
    }
    print(f"{label:24s} {got}")
    return got


base = counts("no link:")
link = MapLink(session, layers, canvas)
bound = counts("link constructed:")
link.dispose()
after = counts("after dispose:")
link.dispose()  # dispose() promises idempotence
twice = counts("after a second dispose:")

for name in MapLink.SELECTABLE:
    assert bound[name] == base[name] + 1, f"{name} was never bound"
    assert after[name] == base[name], f"{name} still bound after dispose"
    assert twice[name] == after[name], f"a second dispose changed {name}"
print("OK: all three bound on construction, all three released on dispose, idempotent")

layers.detach()
project.clear()
app.exitQgis()
PY
```

Record the four printed rows in the task report. If `receivers()` is unavailable on this build for a Python-side signal, fall back to asserting behaviour: select a feature in each of the three layers after `dispose()` and confirm `session.current_key` never moves — and say in the report which method you used.

- [ ] **Step 6: Document it**

Add to `README.md`, in the same place M7's map-link section went:

```markdown
### Picking

Turn **Pick** on in the nsgeo toolbar and click the radargram, or Shift+click
with it off. A pick records the trace and the two-way time — the time is the
truth; the distance along the line, the depth and the velocity are recorded
alongside it as conveniences that can be recomputed.

Picks are authored data. They live in the site GeoPackage's `picks` table,
which is the one table `survey.nsgeo.json` cannot regenerate, and they are
written the moment you make them — there is nothing to save. The table is
editable in QGIS like any other layer, so a pick can be given a note, moved,
or deleted with the ordinary tools.

Picks go on the **working line** — the one the processing dock is bound to —
never on a line you are only previewing by hovering the map. Shift+clicking a
preview says so rather than doing nothing. Select the line on the map first if
you meant to pick on it.

Selecting a pick or a DZX mark on the map opens its line and moves the profile
cursor to its trace. Marks are derived from the DZX sidecar and stay read-only;
picks are yours.
```

- [ ] **Step 7: The manual half of the no-orphans check (spec §6)**

The automated test covers signals. Public *methods* are checked by hand, once, here. For each public name M8 added, confirm a caller in **production** code, not only in tests:

```bash
for name in add_pick picks_for set_pick_store pick_store write_pick set_pick_mode; do
  echo "== $name =="
  grep -rn "\.$name" packages/nsgeo-qgis/nsgeo_qgis/ | grep -v "def $name"
done
echo "== Pick (the record) =="
grep -rn "\bPick\b" packages/nsgeo-qgis/nsgeo_qgis/ | grep -v "pyqtSignal"
```

Every one must have at least one hit outside its own definition. Then confirm the orphan ledger is where it should be:

- `picks_changed` — **adopted**, out of `KNOWN_UNCONSUMED` (Task 4).
- `ProfileDock.pick_requested` — **adopted**, `SHADOWED` pin at `{"declared": 2, "connects": 2}` (Task 3).
- `ProfileView.set_pick_mode` — **adopted**, called by `ProfileDock.set_pick_mode` (Task 3).
- `ParamForm.error` — **still an orphan**, still pinned, untouched by M8.
- `SurveyDock.new_site_requested` / `open_site_requested` / `save_requested` — **still dead**, still in `KNOWN_UNCONSUMED`. M7 filed these back for an issue; M8 does not adopt or delete them.

Record the result in the task report, and state explicitly whether M8 added any new orphan.

- [ ] **Step 8: Run everything**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest packages/nsgeo-core/tests packages/nsgeo-qgis/tests/pure -q -p no:xonsh 2>&1 | tail -3
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q -p no:xonsh 2>&1 | tail -3
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml --follow-imports=silent packages/nsgeo-core/src/nsgeo packages/nsgeo-qgis/nsgeo_qgis/lookup.py packages/nsgeo-qgis/nsgeo_qgis/ui/view_transform.py
```

Expected: pure at or above `367 passed, 2 skipped`; QGIS well above `469 passed`; ruff and mypy clean.

- [ ] **Step 9: Commit and push**

```bash
git add -A
git commit -m "feat: selecting a pick or a mark jumps to its line and trace

Spec §3.4 closed with the promise that selection would serve picks the
same way it serves lines; this is that, plus §4.4's navigable mark.
MapLink binds three layers now instead of one, on the same signals and
released by the same dispose(): a site reopen replaces all four layer
objects together, so binding only lines would leave pick and mark
navigation pointing at dead wrappers and failing with no error at all.

open_line before set_trace, deliberately: set_trace structurally ignores
a key that is not current_key, so the reverse order drops the trace
silently. Marks stay derived and read-only -- confirmed, not changed.

Co-Authored-By: <your own model name> <noreply@anthropic.com>"
git push
```

---

## M8 acceptance

Automated tests do not cover the thing M8 is for. Deploy and run these by hand in QGIS against a real site before proposing any merge, and record the result:

```bash
.venv/bin/python packages/nsgeo-qgis/scripts/dev_link.py --profile ns_geo
```

(Note the underscore in `ns_geo`. **Do not** delete `.worktrees/nsgeo-m7` — the profile's plugin symlink points into it until this deploy repoints it, and the main checkout is not a safe target.)

1. Open a site, open a line, turn **Pick** on — the pointer over the radargram is a crosshair.
2. Click the radargram — a pick marker appears where you clicked, and a point appears on the map on that line at that trace.
3. Turn **Pick** off and Shift+click — same result, no mode change needed.
4. Open the `picks` attribute table — one row per pick, with `line_key`, `trace`, `distance_m`, `time_ns`, `depth_m`, `velocity_m_ns`, `stack_json`, `created` filled and `feature_id`/`seq` empty.
5. Close QGIS without saving the site and reopen it — the picks are still there. (They are written immediately; `Save site` has nothing to do with them.)
6. Hover another line on the map to preview it, then Shift+click it — **no pick is made**, and the message bar says the pick goes to the working line.
7. Hover a line that already has picks — its own picks show on the previewed radargram; move away and the working line's own picks come back.
8. Select a pick on the map with QGIS's Select tool — the profile opens that pick's line and the cursor lands on its trace.
9. Select a DZX mark on the map — same jump. Try to edit the `marks` layer — QGIS refuses; it is read-only.
10. Close the site — the **Pick** action greys out, and the crosshair is gone when you open a new line.
11. Add a note to a pick in the attribute table and save the layer edits — the note persists.
12. **Toggle Editing on the `picks` layer, then author a pick from the profile.** `write_pick` goes straight through the data provider, which the layer's open edit buffer knows nothing about. Check whether the new pick appears on the canvas immediately, only after you end the edit session, or not at all — and whether committing the buffer afterwards disturbs it. The write reaches disk either way; what is unknown is the visibility. (Task 1 review, Ruling 10.)
13. **Look at `depth_m` on a pick made near the very top of a real radargram.** Real GSSI files here carry `position_ns = -11.0864` — the record starts *before* time zero — so a pick clamped to the start of the record gets a **negative depth**, measured at −0.44 m on this data. That is honest (time is the truth; depth is derived from it), but it will look wrong in an attribute table. Confirm it is what you want recorded, rather than a floor at zero. (Task 2 review, Ruling 12.)
14. Unload the plugin with picks on screen — no crash, nothing left on the canvas.

**Open the site package from before this branch** (a site created under M7) at least once during the walkthrough. That exercises `_rebuild_picks` on real authored rows, which is the one irreversible thing this milestone does. Confirm the pick count is unchanged and the two new columns are empty.

### Carried forward, not fixed here

- **Issue #33** (processing steps appear to vanish). Task 3 addresses one half of its class — a refused pick now says why instead of doing nothing — but `ProcessingDock`'s stale `diff_button` cue during a preview is untouched, because no M8 task owns that file. If the walkthrough reproduces #33, the two want fixing together.
- **Issue #32** (no preview cache eviction). Untouched. Picking does not add to it.
- **Issue #21** (`processing_dock.py` overloaded). Untouched.
- **Issue #6** (display-gain clamp). Explicitly out of this phase per spec §2.
- **`ParamForm.error`** and the three dead `SurveyDock` signals remain orphans, pinned and recorded. Deleting them is Plan 2 cleanup.
- **A target-layer picker for picks**, horizon *editing*, and a pick-editing UI beyond QGIS's own attribute table are all out of scope per spec §8. The `feature_id`/`seq` columns exist so the first of those needs no migration; nothing in M8 writes them.
