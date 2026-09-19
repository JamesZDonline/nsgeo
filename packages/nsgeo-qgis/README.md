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
