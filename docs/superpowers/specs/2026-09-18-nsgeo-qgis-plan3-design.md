# nsgeo QGIS plugin (Plan 3, M7–M9) — design

Plan 2 (M4–M6) merged to `main` as `0eadff0`: the plugin loads real DZT files, places them in
grids, and processes them. This phase adds the map ↔ profile link, the pick tool, and a
release anyone can install.

The parent spec is `2026-09-10-nsgeo-qgis-plugin-design.md`; its section 6 sketched M7 and M8.
This document supersedes that sketch where the two disagree, and says why.

---

## 1. Starting state, measured

Not assumed — checked against the merged code before designing.

**M7 — half the loop exists.** `session.set_trace` / `set_selection` and the `trace_changed` /
`selection_changed` signals are built, and `ProfileDock` already drives them on hover and drag.
Nothing listens on the map side: there is no `MapLink`, no marker, no selection band, and
`maptools/` holds only `digitise_tool.py`.

**M8 — storage without a tool.** The `picks` layer is writable and rendered; `marks` is derived
and refilled. There is no `session.add_pick`. Three APIs exist with **no consumer at all**:

| orphan | where | state |
|---|---|---|
| `SiteSession.picks_changed` | `session.py:62` | declared, never emitted, never connected |
| `ProfileView.set_pick_mode` | `profile_view.py:155` | never called outside a test |
| `ProfileDock.pick_requested` | `profile_dock.py` | emitted, nothing connected |

Plan 2 built both ends of picking and left the middle empty. This cost real time: a manual
tester went looking for a pick mode, found `set_pick_mode`, and concluded the build was wrong
rather than that the feature was unbuilt. See §6.

**M9 — `dev_link.py` only.** No `build_zip.py`, no release job, no install docs.

**Cost of opening a line** (ten real GSSI files, 1.4 MB each, 512 × ~620):

```
open           0.1 – 0.2 ms
load samples   0.9 – 3.6 ms      (mean 2.7 ms)
3-step stack  13   – 25   ms
memory         1.3 MB per line   (a 20-line grid resident ≈ 25 MB)
```

These numbers decide §3: previewing a line on hover costs about one to two frames of work, so it
is practical.

---

## 2. Decisions taken in brainstorming

| | Decision |
|---|---|
| Shape | One spec, **three plans of 3–6 tasks**, each written only when the previous milestone is done. Plan 2 ran 19 tasks in one plan; that is what prompted the smaller chunks. |
| Picking | **Points now, horizons designed for.** A pick is one trace and one time; the schema carries an unused grouping so horizons need no migration later. |
| Display gain | Issue #6 (clamp the display limit instead of rebalancing) stays **out of this phase**. |
| Release | **Zip now, repository listing later** — metadata and licensing correct for a listing from the start, so submitting is a form and not a rework. |
| Map → profile | **Ambient, no tool slot.** |
| Interaction | **Hover previews, select promotes.** |

---

## 3. M7 — the map ↔ profile link

### 3.1 Two directions, only one of which is hard

**Profile → map** needs no canvas ownership. `MapLink(QObject)` owns a `QgsVertexMarker` for the
trace cursor and a `QgsRubberBand` for the selected segment, listens to `trace_changed` and
`selection_changed`, and draws. A trace's world position is `Line.trace_coords(frames)[index]`
transformed to the canvas CRS.

**Map → profile** is the part that needed a decision, because the parent spec made it a
`QgsMapTool` and a map tool claims the canvas: while it is active the user loses pan, identify
and select. For an always-on feature that is the wrong trade.

### 3.2 Ambient tracking

`MapLink` connects `QgsMapCanvas.xyCoordinates`, which fires on mouse move **regardless of the
active tool**. Verified directly before committing to this design:

```
--- no map tool set at all ---
  xyCoordinates fired: 2 (50.34, 49.66)
--- with QgsMapToolPan active ---
  xyCoordinates fired: 2 (57.05, 42.95)
```

A `QgsVertexMarker` also attaches to the canvas scene without owning the tool. So the whole
hover link coexists with whatever the user is already doing.

Clicks are deliberately **not** intercepted. Catching a click ambiently means an event filter on
the canvas viewport, adjudicating every click in QGIS against the active tool — the same shape as
the bug where a right-click committed a left-drag selection in the profile. Selection (§3.4) gives
us the deliberate gesture for free.

### 3.3 Preview is not the working line

This is the load-bearing distinction of M7.

`session.current_key` is not merely what is displayed: the processing dock binds to it, and
`replace_step`, `apply_to_grid`, preset application and step removal all resolve their target
through it. **If hovering the map changed `current_key`, moving the pointer would silently
repoint every destructive operation in the plugin** — edit a parameter or apply to a grid and it
lands on a line the user only passed over. That is C2's defect class exactly: a write target
resolved from a different source than the thing the user believes they are editing, with no error
and no cue. C2 is already on this codebase's record.

So the session gains a second, weaker notion:

- **`current_key`** — the working line. Drives the processing dock and every write. Changes only
  by a deliberate act.
- **`preview_key`** — what the pointer is over. Drives the profile *view* and the trace cursor,
  and **nothing else, ever**. Never a write target. Never dirties the session.

Hovering a line previews its radargram and sets the cursor to the nearest trace on it. Moving off
every line snaps the view back to the working line. The processing dock does not follow the
pointer.

The profile must **state which line it is showing** and whether that is the working line or a
preview. Without it the user cannot tell whether what they are looking at is what they are about
to edit, which reintroduces the confusion this split exists to prevent.

A preview renders through the **previewed line's own stack** — that is what makes it a useful
preview rather than a raw trace dump, and §1 measured the cost as one to two frames.

Two overlays are bound to the working line and must not follow a preview: the **gain strip**
(which edits a step in the working line's stack) and the **difference view** (which is a property
of a selected step). Both hide while a preview is displayed and return when the view snaps back.
Hiding is deliberate rather than leaving them live over someone else's radargram: the gain strip
writes on drag, and a strip whose curve belongs to a line that is not on screen is precisely the
C2 configuration.

### 3.4 Select promotes

A preview becomes the working line when the user selects the line feature with QGIS's ordinary
Select tool: `MapLink` listens to the `lines` layer's `selectionChanged` and calls
`session.open_line(key)` — the same path the survey tree already uses, so promotion and opening
from the tree cannot diverge. The `lines` layer already carries `line_key` on every feature, so
the mapping is direct.

Selecting several lines at once promotes none of them: a multi-selection has no single answer,
and guessing one is worse than doing nothing.

No event filter, no tool of our own, no stolen clicks, and it composes with everything else QGIS
does with selection. The same mechanism serves picks later: selecting a pick feature jumps to its
line and trace.

### 3.5 Details that need to be right

- **Dwell before previewing** (~100 ms) so sweeping the map does not thrash the renderer.
- **Tolerance**: `nearest_trace` only counts within a screen-distance tolerance of a line;
  outside it, there is no preview.
- **First preview pays the async load** (M5's loading state covers it); afterwards the session's
  profile cache makes it instant.
- **Loop guard**: the session emits only on real change, so a marker update that round-trips to
  the same trace is a no-op.
- **Teardown**: the marker and band are `QgsMapCanvasItem`s owned by the canvas scene, exactly
  like the digitise rubber band that leaked through all of Plan 2 (item I4). `MapLink` gets an
  explicit disposal that takes them back off the scene, called from `unload()`, and a test that
  counts scene items across create/destroy cycles.

### 3.6 Known limit, not a defect

Previewing across a large site could eventually load every line. At ~1.3 MB per line this is
comfortable for tens of lines and uncomfortable for hundreds. No eviction policy in M7; a note in
the plan and an issue if a real site makes it bite.

---

## 4. M8 — the pick tool

### 4.1 Adopt the orphans

`session.add_pick(key, trace, time_ns)` writes a pick and emits the already-declared
`picks_changed`. `ProfileDock.pick_requested` connects to it. `ProfileView.set_pick_mode` is
driven by a toolbar toggle. All three orphans in §1 gain a consumer; none is left behind, and no
new one is added.

### 4.2 The feature

Per the parent spec: `line_key`, `trace`, `distance_m`, `time_ns`, `depth_m`, `velocity_m_ns`,
`stack_json`, `note`, `created`. Time is the truth; depth and velocity are conveniences that can
be recomputed.

Two fields are added now and left unused:

- **`feature_id`** (str, nullable) — groups picks into one interpreted feature.
- **`seq`** (int, nullable) — order within that feature.

M8 writes them null. A horizon later is an ordered run of existing picks sharing a `feature_id`,
which needs no migration of an authored table. That matters specifically here: picks are the one
table the survey file is not the source of truth for, and this project has already had to repair
pick storage twice (the rebuild's row-count gate, and the package-naming migration).

### 4.3 Interaction

With pick mode on, or Shift+click otherwise, a click in the profile becomes a pick at that trace
and time. Picks render on the profile and in the `picks` map layer. Picking targets the **working
line**, never a preview — the same rule as §3.3, for the same reason.

### 4.4 Marks

The `marks` layer is derived from DZX marks and already refilled. M8 confirms it renders and is
read-only, and that a mark can be navigated to; it does not become editable.

---

## 5. M9 — release

- **`build_zip.py`** producing a QGIS-installable zip: the plugin package plus the core vendored
  at the path the shim expects, excluding tests, caches and development files.
- **CI job on a tag** that builds the zip and attaches it to a GitHub release.
- **Metadata correct for a repository listing** — `metadata.txt` complete and accurate, an
  `experimental` flag while it settles, and a stable tag-to-release process. Listing itself is
  deferred; the work to make listing possible is not.
- **Licensing stated plainly**: the plugin is GPL-2.0-or-later, the core is MIT and is vendored
  into the zip. Both licences ship in the artifact.
- **Install docs** for someone who has never seen the repository.
- **Promote core exports**: settle what `nsgeo`'s public API is — what a second front end may
  import — and document it. The boundary tests already enforce that the plugin does not reach
  into processing internals; this names the supported surface. No PyPI publication in this phase.

---

## 6. Cross-cutting: no new orphans

Plan 2 shipped three APIs with no consumer, and the resulting confusion cost a manual testing
session. Each plan in this phase ends with a check that every new signal and every new public
method has a caller, and that the three existing orphans are consumed or deleted.

A signal with no consumer reads exactly like a working feature from the emitting side. The check
is to grep for the `connect`, never the `emit`.

---

## 7. Testing

Unchanged from Plan 2, and it is load-bearing:

- **Two tiers.** A pure tier with no QGIS; a `tests/qgis` tier that skips wholesale when the
  bindings are absent.
- **The conftest guards apply to all new work**: no unhandled modal, and any exception that
  escapes a Qt slot fails the test. The second one exists because the local PyQt prints such
  exceptions and passes while the CI container turns them into `qFatal()`.
- **Real data is the primary validation.** Ten real GSSI files are the reference; synthetic
  fixtures only as far as they mirror them.
- **Map items get lifetime tests.** §3.5's disposal is the kind of thing Plan 2 shipped broken.

---

## 8. Out of scope

From the parent spec, still out: timeslices, migration, velocity analysis, the layered-velocity
editor, `TrackPlacement` and the DZG reader, the `.gpr` reader, background processing of stacks,
relocating missing files, a target-layer picker for picks, writing processed data to disk, and any
instrument other than GPR.

Added here: the display-gain clamp (#6), horizon *editing* (the schema accommodates horizons; no
tool draws or edits one), click-interception on the canvas, a preview cache eviction policy, and
publication of `nsgeo-core` to PyPI.

---

## 9. Plans

| | Milestone | Ends with |
|---|---|---|
| M7 | `MapLink`, ambient hover preview, selection promotes, marker and band, disposal | Pointing at the map shows you the data |
| M8 | `add_pick`, pick mode, picks on profile and map, marks confirmed | An interpretation tool |
| M9 | `build_zip.py`, release job, metadata, licensing, install docs, named core API | Usable by other people |

Each plan is written when the previous milestone is complete, so it reflects what was actually
built rather than what was predicted.
