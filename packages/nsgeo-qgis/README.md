# nsgeo QGIS plugin

GPL-2.0-or-later. Consumes the MIT `nsgeo` core from `../nsgeo-core`; contains no
signal processing (a test enforces it).

## Features

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

A pick's position on the map is fixed at the moment you make it. Moving,
resizing or reorienting a grid afterwards does **not** move any pick already
recorded against a line on that grid — the line itself redraws in its new
place, but the pick does not follow, and the plugin logs a warning rather
than silently re-placing it (re-placing on every refresh could just as
easily overwrite a pick you moved by hand). Changing a grid's CRS is the
exception: that re-projects every pick, the same way it re-projects
everything else in the package.

## Development install

```bash
python packages/nsgeo-qgis/scripts/dev_link.py      # symlink into the QGIS profile
```

Then enable **nsgeo** in QGIS's plugin manager. The plugin finds the core source
through the symlink's real path; no `pip install` into QGIS's Python is needed.
Use the Plugin Reloader plugin after edits.

## Tests

Two tiers. `tests/pure` needs no QGIS and runs in the normal `.venv`. `tests/qgis`
needs the QGIS Python bindings and an offscreen display:

```bash
python3 -m venv --system-site-packages .venv-qgis     # from the interpreter QGIS uses
.venv-qgis/bin/pip install pytest
QT_QPA_PLATFORM=offscreen .venv-qgis/bin/python -m pytest packages/nsgeo-qgis/tests -q
```

The `qgis/` directory skips itself when `qgis` is not importable.
