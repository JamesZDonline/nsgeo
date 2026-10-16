### Task 4: Live navigation — Position, Resolution and Display, and the slice on the map

The milestone's centre. After this task an archaeologist drags a slider and watches the map
redraw, sees the depth window they are actually averaging, sees where there is no data, and sees
what is being held and how fast it is going.

**Files:**
- Create: `packages/nsgeo-qgis/nsgeo_qgis/slice_layer.py`
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/ui/slices_dock.py` (three more groups)
- Modify: `packages/nsgeo-qgis/nsgeo_qgis/plugin.py` (own the layer, connect `slice_changed`)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_layer.py` (new)
- Test: `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py` (append)

**Interfaces:**

- Consumes: Task 1's `SliceWindow`, `plan_windows`, `window_label`, `to_north_up`, `fill`;
  Task 2's `SliceEngine`; `nsgeo.render`'s `colormap`, `colormap_names`, `UnipolarClip`,
  `PercentileClip`, `UNIPOLAR_COLORMAPS`; `SiteLayers.group`, `SiteLayers.crs()`.
- Produces:
  - `slice_layer.SliceLayer(session, layers, parent=None)` with `update(values, frame, *, limit,
    colormap_name, unipolar, subtitle)`, `clear()`, `dispose()`, `layer` (the `QgsRasterLayer` or
    `None`), `path` (the scratch GeoTIFF).
  - `slice_layer.build_shader(lut, limit, unipolar) -> QgsRasterShader`
  - `SlicesDock` gains: `slice_slider`, `readout`, `velocity_label`, `thickness_spin`,
    `step_spin`, `cell_spin`, `dz_spin`, `z0_spin`, `z1_spin`, `radius_spin`, `stretch_combo`,
    `palette_combo`, `coverage_check`, `legend_label`, `status_label`; methods `current_window()
    -> SliceWindow | None`, `current_values() -> np.ndarray | None`, `current_frame()`,
    `display_limit() -> float`, `refresh_slice()`, `step_slice(delta)`; signal
    `slice_changed = pyqtSignal()` (connected in `plugin.py` in this task).

---

- [ ] **Step 1: Write the failing `SliceLayer` tests**

Create `packages/nsgeo-qgis/tests/qgis/test_plugin_slice_layer.py`:

```python
"""The active slice as a QGIS raster layer."""

from __future__ import annotations

import numpy as np
import pytest
from nsgeo.render import colormap
from nsgeo.slices import CubeFrame
from nsgeo_qgis.layers import SiteLayers
from nsgeo_qgis.session import SiteSession
from nsgeo_qgis.slice_layer import SliceLayer, build_shader
from qgis.core import QgsProject
from qgis.PyQt.QtGui import qAlpha, qRed

FRAME = CubeFrame(origin=(500.0, 700.0), azimuth=0.0, cell=0.5, nx=12, ny=12, crs="EPSG:32616")


@pytest.fixture
def mapped(qgis_app, tmp_path):
    project = QgsProject.instance()
    project.clear()
    session = SiteSession()
    session.new_site(tmp_path)
    layers = SiteLayers(session, project=project)
    sl = SliceLayer(session, layers)
    yield sl, session, layers, project
    sl.dispose()
    layers.detach()
    project.clear()


def _values(fill_value=5.0):
    values = np.full((FRAME.ny, FRAME.nx), fill_value, dtype=np.float32)
    values[0, :] = np.nan  # an unsurveyed row
    return values


def test_updating_creates_a_valid_layer_in_the_site_group(mapped):
    sl, _, layers, project = mapped
    sl.update(_values(), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="x")
    assert sl.layer is not None and sl.layer.isValid()
    assert sl.layer.width() == FRAME.nx and sl.layer.height() == FRAME.ny
    assert project.mapLayer(sl.layer.id()) is not None


def test_the_pixel_values_are_the_slice_values_not_a_rendered_picture(mapped):
    """A float raster, so a reader can query an amplitude rather than a
    colour. Spec 9.4 exports float32 with NaN nodata for the same reason."""
    sl, _, _, _ = mapped
    sl.update(_values(7.5), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="")
    provider = sl.layer.dataProvider()
    centre = sl.layer.extent().center()
    value, ok = provider.sample(centre, 1)
    assert ok and value == pytest.approx(7.5)


def test_a_second_update_refreshes_the_pixels_in_place(mapped):
    """The layer is rewritten and reloaded on every tick rather than
    rebuilt, so a drag does not churn the layer tree. Measured: the
    rewrite plus reloadData is ~2.8 ms at 300x300."""
    sl, _, _, _ = mapped
    sl.update(_values(1.0), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="")
    first_id = sl.layer.id()
    sl.update(_values(9.0), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="")
    assert sl.layer.id() == first_id, "the layer must be updated, not replaced"
    value, ok = sl.layer.dataProvider().sample(sl.layer.extent().center(), 1)
    assert ok and value == pytest.approx(9.0)


def test_a_cell_size_change_resizes_the_same_layer(mapped):
    """The cell slider changes nx and ny. Verified directly against this
    GDAL and QGIS: width() and height() follow a reloadData() across a
    shape change, so there is no need to tear the layer down."""
    sl, _, _, _ = mapped
    sl.update(_values(), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="")
    finer = CubeFrame(origin=(500.0, 700.0), azimuth=0.0, cell=0.25, nx=24, ny=24, crs="EPSG:32616")
    sl.update(
        np.full((24, 24), 3.0, np.float32),
        finer,
        limit=10.0,
        colormap_name="amp_heat",
        unipolar=True,
        subtitle="",
    )
    assert (sl.layer.width(), sl.layer.height()) == (24, 24)


def test_nodata_renders_transparent(mapped):
    """The check that actually works. `block.isNoData()` is False on a
    RENDERED block -- the renderer's output is ARGB, so nodata is carried
    by the ALPHA channel, and asserting isNoData here is a false pass
    (verified directly against this build)."""
    sl, _, _, _ = mapped
    sl.update(_values(), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="")
    block = sl.layer.renderer().block(1, sl.layer.extent(), FRAME.nx, FRAME.ny)
    assert qAlpha(block.color(0, 0)) == 0, "the unsurveyed row must be transparent"
    assert qAlpha(block.color(FRAME.ny - 1, 0)) == 255


def test_the_shader_spans_zero_to_limit_for_unipolar_data(mapped):
    """Spec 8: a unipolar table maps 0 to 0 and the limit to 255, instead
    of wasting half the table and putting the data floor at mid-grey."""
    lut = colormap("amp_black_high")
    shader = build_shader(lut, limit=4.0, unipolar=True)
    items = shader.rasterShaderFunction().colorRampItemList()
    assert items[0].value == pytest.approx(0.0)
    assert items[-1].value == pytest.approx(4.0)
    assert (qRed(items[0].color.rgb()), qRed(items[-1].color.rgb())) == (
        int(lut[0, 0]),
        int(lut[255, 0]),
    )


def test_the_shader_spans_minus_limit_to_plus_limit_for_bipolar_data(mapped):
    lut = colormap("seismic")
    shader = build_shader(lut, limit=4.0, unipolar=False)
    items = shader.rasterShaderFunction().colorRampItemList()
    assert items[0].value == pytest.approx(-4.0)
    assert items[-1].value == pytest.approx(4.0)
    middle = items[len(items) // 2]
    assert abs(middle.value) < 0.05  # zero sits in the middle of a bipolar table


def test_disposing_removes_the_layer_and_the_scratch_file(mapped):
    sl, _, _, project = mapped
    sl.update(_values(), FRAME, limit=10.0, colormap_name="amp_heat", unipolar=True, subtitle="")
    layer_id = sl.layer.id()
    path = sl.path
    sl.dispose()
    assert project.mapLayer(layer_id) is None
    assert not path.exists()
```

- [ ] **Step 2: Run and watch them fail.** Expected: no module `slice_layer`.

- [ ] **Step 3: Implement `slice_layer.py`**

```python
"""The active slice on the map: a float raster, restyled and reloaded in place.

A real float32 raster with NaN nodata, not a picture. A reader can then
query an amplitude, and the same values go out to the GeoTIFF unchanged --
spec 9.4's reason for exporting float rather than bytes applies just as
well to what is on screen.

Rewritten in place on every tick rather than rebuilt: verified against
this GDAL and QGIS, `reloadData()` refreshes the pixel values, and the
layer's `width()`/`height()` follow even when the cell slider changes the
shape, so a drag never churns the layer tree.

Uncompressed, unlike the export (plan Ruling 3). Measured here at GDAL
3.8.4: `COMPRESS=DEFLATE, PREDICTOR=3` costs 8.8 ms for a 300x300 float
band and 25.2 ms at 600x600, against 1.0 and 1.3 ms uncompressed. Spec
9.5's option set is argued for a file someone keeps; this one lives in a
scratch directory for the length of a session.

That scratch file is also why this layer is a PREVIEW and says so in its
name: it is deliberately outside the project tree, so it cannot be
committed by accident or mistaken for the artefact -- and a saved QGIS
project would find it gone. `slice_export.py` writes the durable one.
"""
```

Key content:

```python
_CREATION_OPTIONS = ["INTERLEAVE=BAND", "TILED=NO", "BIGTIFF=IF_SAFER"]
LAYER_NAME = "Slice (live preview)"


def build_shader(lut: np.ndarray, limit: float, unipolar: bool) -> QgsRasterShader:
    """A 256-stop ramp from a core colour table.

    The core's LUT is the authority on colour, here as in the profile
    view, so the map and the radargram cannot drift apart. All 256 stops
    rather than a subsample: it is rebuilt only when the palette or the
    limit changes, never per tick, and a subsampled ramp would
    interpolate across the non-linear stretch of `amp_heat`.
    """
    lo = 0.0 if unipolar else -float(limit)
    hi = float(limit)
    items = [
        QgsColorRampShader.ColorRampItem(
            lo + (hi - lo) * i / 255.0,
            QColor(int(lut[i, 0]), int(lut[i, 1]), int(lut[i, 2])),
            f"{lo + (hi - lo) * i / 255.0:.3f}",
        )
        for i in range(256)
    ]
    function = QgsColorRampShader()
    function.setColorRampType(QgsColorRampShader.Type.Interpolated)
    function.setColorRampItemList(items)
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(function)
    return shader
```

`SliceLayer.__init__` takes `(session, layers, parent=None)`, makes
`self._dir = Path(tempfile.mkdtemp(prefix="nsgeo-slice-"))` and `self.path = self._dir /
"slice.tif"`, and sets `self.layer = None`.

`update(values, frame, *, limit, colormap_name, unipolar, subtitle)` must:

1. `array, geotransform = to_north_up(values, frame)` — the one resample, from core.
2. Write `array` to `self.path` with `_CREATION_OPTIONS`, `gdal.GDT_Float32`, the geotransform,
   the frame's CRS as WKT (`QgsCoordinateReferenceSystem(frame.crs).toWkt()`), and
   `SetNoDataValue(float("nan"))`. **Hold the `gdal.Dataset` in a local and set it to `None`
   before returning** — GDAL flushes on destruction, and a dataset garbage-collected mid-expression
   is a real trap (it bit the spike that produced this plan's measurements).
3. If `self.layer is None`, create `QgsRasterLayer(str(self.path), LAYER_NAME, "gdal")`, add it to
   the project **without** adding it to the legend root
   (`project.addMapLayer(layer, addToLegend=False)`), then insert it into `layers.group` if that
   group exists, so it joins the site's layer group like every other layer here. Otherwise call
   `self.layer.dataProvider().reloadData()`.
4. Apply a `QgsSingleBandPseudoColorRenderer(provider, 1, build_shader(colormap(colormap_name),
   limit, unipolar))` with `setClassificationMin`/`Max` matching the shader's ends, but **only
   when `(colormap_name, limit, unipolar)` changed since the last update** — rebuilding 256 stops
   on every tick of the depth slider is waste, and the renderer is what makes the layer flicker
   if replaced needlessly.
5. `self.layer.setCustomProperty("nsgeo/window", subtitle)` and
   `self.layer.setAbstract(subtitle)`, so the window a layer shows is recorded on the layer
   itself rather than only in the dock.
6. `self.layer.triggerRepaint()`.

`clear()` removes the layer from the project and sets `self.layer = None`.
`dispose()` calls `clear()` then `shutil.rmtree(self._dir, ignore_errors=True)`.

Guard every public method body with `except Exception` reporting through `nsgeo_qgis.log.log` —
`update` is reached from a slider slot.

- [ ] **Step 4: Run and watch them pass.** Expected: 8 passed.

- [ ] **Step 5: Write the failing dock-navigation tests**

Append to `packages/nsgeo-qgis/tests/qgis/test_plugin_slices_dock.py`:

```python
def _ready(dock):
    dock.prepare()
    assert dock.engine.wait_for_preparation(20_000)
    dock.z0_spin.setValue(2.0)
    dock.z1_spin.setValue(30.0)
    dock.dz_spin.setValue(0.5)
    dock.cell_spin.setValue(0.25)
    dock.flush_debounce()  # applies the pending Resolution change immediately


def test_the_readout_states_the_window_that_was_actually_averaged(docked):
    """Spec 9.2: the control that moves the window and the statement of
    where the window now is are one unit, read together on every tick.
    Spec 6.6: always the full range, never the centre -- with overlapping
    slices, the extent of what is averaged is the thing a reader would
    otherwise mistake for vertical resolution."""
    dock, _ = docked
    _ready(dock)
    dock.thickness_spin.setValue(4.0)
    dock.slice_slider.setValue(10)
    text = dock.readout.text()
    window = dock.current_window()
    assert window is not None
    lo, hi = window_times_ns(dock.engine.z, window)
    assert f"{lo:.1f}" in text and f"{hi:.1f}" in text
    assert "ns" in text
    assert "/" in text and "slice" in text  # "slice 14 / 40"


def test_the_readout_shrinks_with_the_window_at_the_end_of_the_axis(docked):
    """Trap 3. At either end `ZAxis.level_range` returns a genuinely
    thinner window than asked for, and spec 6.6 requires the readout to
    show what was actually averaged. A readout rebuilt from the slider
    position plus the thickness spin box claims a window the axis
    refused."""
    dock, _ = docked
    _ready(dock)
    dock.thickness_spin.setValue(8.0)
    dock.slice_slider.setValue(dock.slice_slider.maximum())
    window = dock.current_window()
    lo, hi = window_times_ns(dock.engine.z, window)
    assert hi <= dock.engine.z.t_end_ns + 1e-9
    assert hi - lo < 8.0  # thinner than requested, and the readout says so
    assert f"{hi:.1f}" in dock.readout.text()


def test_moving_the_slider_emits_slice_changed_and_changes_the_values(docked):
    dock, _ = docked
    _ready(dock)
    seen: list[int] = []
    dock.slice_changed.connect(lambda: seen.append(1))
    dock.slice_slider.setValue(4)
    first = dock.current_values().copy()
    dock.slice_slider.setValue(30)
    second = dock.current_values()
    assert len(seen) >= 2
    both = np.isfinite(first) & np.isfinite(second)
    assert both.any()
    assert not np.allclose(first[both], second[both]), "a different depth must look different"


def test_the_fill_radius_is_metres_and_survives_a_cell_size_change(docked):
    """Spec 6.4's default is 1.5 x the line spacing -- a distance. The
    spin box is therefore in metres and the cell conversion happens
    underneath, so halving the cell size does not silently halve the
    smoothing."""
    dock, session = docked
    _ready(dock)
    assert dock.radius_spin.value() == pytest.approx(1.5 * GRID.default_spacing)
    before = dock.radius_cells()
    dock.cell_spin.setValue(0.125)
    dock.flush_debounce()
    assert dock.radius_spin.value() == pytest.approx(1.5 * GRID.default_spacing)
    assert dock.radius_cells() == pytest.approx(before * 2, abs=1)


def test_filling_reaches_between_the_lines_and_zero_radius_does_not(docked):
    """Spec 6.4: at realistic spacing about 80% of cells are empty, so the
    fill is most of the picture rather than a nicety."""
    dock, _ = docked
    _ready(dock)
    dock.radius_spin.setValue(0.0)
    dock.flush_debounce()
    unfilled = np.isfinite(dock.current_values()).sum()
    dock.radius_spin.setValue(1.0)
    dock.flush_debounce()
    filled = np.isfinite(dock.current_values()).sum()
    assert filled > unfilled


def test_the_coverage_toggle_shows_trace_counts_not_amplitudes(docked):
    """Spec 3: a zero that means 'no data' reading as 'no reflection' is
    the defect a count array exists to fix, and the coverage view is where
    a user sees it."""
    dock, _ = docked
    _ready(dock)
    dock.coverage_check.setChecked(True)
    coverage = dock.current_values()
    assert np.nanmax(coverage) >= 1.0
    assert np.allclose(coverage[np.isfinite(coverage)] % 1.0, 0.0), "counts are whole traces"
    dock.coverage_check.setChecked(False)
    assert not np.allclose(
        np.nan_to_num(dock.current_values()), np.nan_to_num(coverage)
    )


def test_a_shared_stretch_holds_one_limit_across_depth_and_per_slice_does_not(docked):
    """Spec 8: comparability by default, legibility on demand."""
    dock, _ = docked
    _ready(dock)
    dock.stretch_combo.setCurrentText("shared across the cube")
    dock.slice_slider.setValue(4)
    shallow = dock.display_limit()
    dock.slice_slider.setValue(40)
    deep = dock.display_limit()
    assert shallow == pytest.approx(deep)

    dock.stretch_combo.setCurrentText("this slice")
    dock.slice_slider.setValue(4)
    shallow_own = dock.display_limit()
    dock.slice_slider.setValue(40)
    deep_own = dock.display_limit()
    assert shallow_own != pytest.approx(deep_own)


def test_the_palette_offers_unipolar_tables_for_a_transformed_source(docked):
    """Spec 8's rule: a bipolar table on unipolar data is a configuration
    error, not a style choice. The combo is where that rule is enforced."""
    dock, _ = docked
    _ready(dock)
    offered = [dock.palette_combo.itemText(i) for i in range(dock.palette_combo.count())]
    assert set(offered) == set(colormap_names(unipolar=True))
    assert "seismic" not in offered

    dock.transform_combo.setCurrentText("none")  # re-prepares on its own (spec 9.1)
    assert dock.engine.wait_for_preparation(20_000)
    offered = [dock.palette_combo.itemText(i) for i in range(dock.palette_combo.count())]
    assert set(offered) == set(colormap_names(unipolar=False))
    assert "amp_heat" not in offered


def test_the_status_line_reports_what_is_held_and_how_fast(docked):
    dock, _ = docked
    _ready(dock)
    dock.slice_slider.setValue(8)
    text = dock.status_label.text()
    assert "lines held in memory" in text
    assert "slices redraw in" in text


def test_a_resolution_change_is_debounced_into_one_rebuild(docked):
    """Spec 7.2 and trap 4: a rebuild is 44 ms and even the improved fill
    is 32 ms at 600x600, so a slider emitting per-step would queue work
    faster than it can finish."""
    dock, _ = docked
    _ready(dock)
    rebuilds: list[int] = []
    dock.slice_changed.connect(lambda: rebuilds.append(1))
    for value in (0.2, 0.3, 0.4, 0.5):
        dock.cell_spin.setValue(value)
    assert rebuilds == [], "nothing should have rebuilt while the value was still moving"
    dock.flush_debounce()
    assert len(rebuilds) == 1
```

Add the imports these need at the top of the file: `numpy as np`,
`from nsgeo.render import colormap_names`, `from nsgeo.slices import window_times_ns`.

- [ ] **Step 6: Run and watch them fail.**

- [ ] **Step 7: Implement the three remaining groups**

Append to `slices_dock.py`. Requirements, in the order the tests pin them:

**Position group.** `slice_slider` is a horizontal `QSlider` over `0..nz-1` — it *is* the top of
the window, and there is no "Top" field (spec 9.2). Directly beneath it, in the same group and
with no other widget between, `readout` (a `QLabel`), then `velocity_label` in a smaller, dimmer
font — the velocity is provenance, not state. `thickness_spin` and `step_spin` are
`QDoubleSpinBox`es in nanoseconds, suffix `" ns"`, `thickness_spin` defaulting to `5.0` and
`step_spin` to half of it (spec 6.6's 50% overlap default, with its reason: a reflector on a
boundary is halved in both neighbours).

`current_window()` is:

```python
    def current_window(self) -> SliceWindow | None:
        z = self.engine.z
        if z is None:
            return None
        top_ns = z.t0_ns + self.slice_slider.value() * z.dz_ns
        k0, k1 = z.level_range(top_ns, max(z.dz_ns, self.thickness_spin.value()))
        return SliceWindow(k0, k1)
```

and `readout` is built from `window_label(z, window, velocity)` prefixed with
`f"slice {index + 1} / {total} · "`, where `index`/`total` come from
`plan_windows(z, window.n_levels, step_levels)`. **Never** rebuild the label from
`self.slice_slider.value()` and `self.thickness_spin.value()` — that is trap 3, and
`test_the_readout_shrinks_with_the_window_at_the_end_of_the_axis` exists to catch it.

**Resolution group.** `cell_spin` (m, 0.01–5.0, default `min(0.5, grid.default_spacing / 2)` —
spec 4's convention: no smaller than the trace spacing, no larger than half the line spacing),
`dz_spin` (ns, default the grid's first line's native `dt`), `z0_spin`/`z1_spin` (ns), and
`radius_spin` (**metres**, default `1.5 * grid.default_spacing`, spec 6.4). `radius_cells()` is
`max(0, int(round(radius_spin.value() / cell_spin.value())))`.

All five go through one debounce:

```python
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(120)
        self._debounce.timeout.connect(self._apply_resolution)
```

with every Resolution widget's `valueChanged` connected to `self._debounce.start` and a public
`flush_debounce()` that stops the timer and calls `_apply_resolution()` directly — tests use it,
and so does anything that needs the current geometry now. `_apply_resolution` builds a
`Resolution`, calls `engine.set_resolution(...)`, re-ranges `slice_slider` to `0..nz-1` keeping
the nearest equivalent time, invalidates the cached shared limit, and calls `refresh_slice()`.

**Display group.** `stretch_combo` with exactly `["shared across the cube", "this slice"]`;
`palette_combo` refilled from `colormap_names(unipolar=engine.output_unipolar)` whenever the
source is prepared, defaulting to `"amp_black_high"` when unipolar and to `DEFAULT_COLORMAP`
otherwise; `coverage_check` (`QCheckBox("Show coverage")`); `legend_label` reading
`f"0 – {limit:.3g}"` (or `f"−{limit:.3g} – {limit:.3g}"` when bipolar) with the transform's name,
so the number on screen has a stated meaning. Then `status_label` below the groups,
`setWordWrap(True)`, fed from `engine.status_text()`.

**`refresh_slice()`** is the one path everything funnels through:

```python
    def refresh_slice(self) -> None:
        try:
            window = self.current_window()
            if window is None or not self.engine.is_prepared:
                self._values = None
                return
            values, coverage = self.engine.slice_at(window)
            if self.coverage_check.isChecked():
                shown = coverage.astype(float)
                shown[coverage == 0] = np.nan
            else:
                shown = fill(values, coverage, self.radius_cells())
            self._values = shown
            self._window = window
            self._update_readout(window)
            self.status_label.setText(self.engine.status_text())
            self.slice_changed.emit()
        except Exception as exc:  # noqa: BLE001 -- reached from slider slots; an
            # escape passes locally and aborts the CI container.
            self.error.emit(str(exc))
```

**`display_limit()`** returns the cached shared limit when `stretch_combo` is on
`"shared across the cube"`, recomputing it through `engine.shared_limit(window.n_levels, clip)`
only when the thickness, the source or the mode changed; and `clip.limit(self._values)` when on
`"this slice"`. `clip` is `UnipolarClip()` when `engine.output_unipolar` and `PercentileClip()`
otherwise.

**`step_slice(delta)`** moves `slice_slider` by `delta * step_levels`, clamped — the unit that
makes a step a *step* rather than a level.

- [ ] **Step 8: Run and watch them pass.** Expected: ~10 more dock tests green.

- [ ] **Step 9: Wire the layer into `plugin.py`**

In `initGui`, after the Slices dock block:

```python
        self.slice_layer = SliceLayer(self.session, self.layers)
        self.slices_dock.slice_changed.connect(self._on_slice_changed)
```

and the handler, guarded like every other slot here:

```python
    def _on_slice_changed(self) -> None:
        try:
            dock, layer = self.slices_dock, self.slice_layer
            if dock is None or layer is None:
                return
            values, frame = dock.current_values(), dock.current_frame()
            if values is None or frame is None:
                layer.clear()
                return
            layer.update(
                values,
                frame,
                limit=dock.display_limit(),
                colormap_name=dock.palette_combo.currentText(),
                unipolar=dock.engine.output_unipolar,
                subtitle=dock.readout.text(),
            )
        except Exception as exc:  # noqa: BLE001 -- see the module docstring
            self.message(f"could not draw the slice: {exc}", Qgis.MessageLevel.Warning)
```

Add `self.slice_layer: SliceLayer | None = None` to `__init__`, and in `unload`, **before**
`self.layers.detach()`, `if self.slice_layer is not None: self.slice_layer.dispose();
self.slice_layer = None` — outside-in, the same ordering the existing `map_link.dispose()` call
documents.

- [ ] **Step 10: Verify and prove discrimination**

Run both tiers, ruff and mypy. Then four mutants, one at a time:

1. `current_window()` → build the label from `slice_slider.value()` and `thickness_spin.value()`
   instead of from `(k0, k1)`. Expect
   `test_the_readout_shrinks_with_the_window_at_the_end_of_the_axis` to FAIL.
2. `radius_cells()` → return `int(self.radius_spin.value())` (metres read as cells). Expect
   `test_the_fill_radius_is_metres_and_survives_a_cell_size_change` to FAIL.
3. `display_limit()` → always `clip.limit(self._values)` (per-slice, ignoring the combo). Expect
   `test_a_shared_stretch_holds_one_limit_across_depth_and_per_slice_does_not` to FAIL.
4. `build_shader` → `lo = -limit` unconditionally. Expect
   `test_the_shader_spans_zero_to_limit_for_unipolar_data` to FAIL — this is spec 8's wasted half
   table, the defect the whole unipolar path exists for.

Also record, by timing it, how long one `refresh_slice()` takes at the default resolution on the
synthetic fixture, and confirm it is in the single-digit milliseconds.

- [ ] **Step 11: Commit and push**

```bash
git add packages/nsgeo-qgis/nsgeo_qgis packages/nsgeo-qgis/tests/qgis
git commit -m "feat(slices): live navigation and the slice on the map

Position, Resolution and Display; a float raster rewritten and reloaded
in place; coverage; the shared stretch. The readout is derived from the
level range that was actually averaged, never from the request.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push origin nsgeo-m11
```

**Task 4 is done when:** dragging the depth slider redraws the map layer, the readout tracks the
real window, coverage and fill both work, the status line is live, and both tiers are green.

---

