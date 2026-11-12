"""The export dialog: the path, the export cell and pixel, what will be written,
and the two checks that refuse before anything starts."""

from __future__ import annotations

import collections
from pathlib import Path

import numpy as np
import pytest
from nsgeo_qgis.slices_plan import (
    EXPORT_BUDGET_BYTES,
    ExportPreview,
    export_refusal,
    format_bytes,
)
from nsgeo_qgis.ui.export_dialog import ExportChoice, ExportDialog, targets_in_use
from osgeo import gdal
from qgis.core import QgsProject, QgsRasterLayer
from qgis.PyQt.QtCore import QCoreApplication, QEvent
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox

DISK = collections.namedtuple("DISK", "total used free")
HELD = 1_000_000_000


def _preview(cell, pixel, *, grids=("A", "B"), held=1_000_000_000, file_bytes=600_000_000):
    return ExportPreview(
        cell=cell,
        pixel=pixel,
        width_px=int(100 / pixel),
        height_px=int(50 / pixel),
        bands=18,
        bands_detail="every 2.5 ns from -1.8 to 45 ns, 5 ns thick",
        slices="kriging, max distance 0.75 × spacing, no smoothing",
        grids=grids,
        normalisation=None if grids is None else "edge match",
        file_bytes=file_bytes,
        held_bytes=held,
    )


class Fake:
    """A preview callable that counts its calls."""

    def __init__(self, **kw):
        self.kw = kw
        self.calls = []

    def __call__(self, cell, pixel):
        self.calls.append((cell, pixel))
        kw = dict(self.kw)
        held = kw.pop("held", None)
        if callable(held):
            kw["held"] = held(cell, pixel)
        elif held is not None:
            kw["held"] = held
        return _preview(cell, pixel, **kw)


@pytest.fixture
def roomy_disk(monkeypatch):
    monkeypatch.setattr("shutil.disk_usage", lambda p: DISK(10**12, 10**11, 9 * 10**11))


@pytest.fixture
def make(qgis_app, tmp_path, roomy_disk):
    made = []

    def _make(
        preview=None, *, floor=0.015, live=0.05, project=None, path=True, coverage=True, **kw
    ):
        preview = preview or Fake(**kw)
        dialog = ExportDialog(
            preview,
            cell_floor=floor,
            live_cell=live,
            default_path=str(tmp_path / "site.tif") if path else "",
            project=project or QgsProject(),
            writes_coverage=coverage,
        )
        made.append(dialog)
        dialog.preview = preview
        return dialog

    yield _make
    # The session's QgsApplication is torn down right after the last test: a
    # dialog still alive then is destroyed against a dead application.
    for d in made:
        d.deleteLater()
    made.clear()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _rows(dialog):
    return dict(dialog.summary_rows())


def _settle(dialog):
    QTest.qWait(260)


def test_the_cell_and_pixel_default_to_the_live_cell(make):
    d = make(live=0.05)
    assert d.cell_spin.value() == 0.05
    assert d.pixel_spin.value() == 0.05
    assert d.cell_spin.decimals() == 3


def test_the_pixel_spin_maximum_follows_the_cell(make):
    d = make(live=0.05)
    d.cell_spin.setValue(0.03)
    assert d.pixel_spin.maximum() == pytest.approx(0.03)
    assert d.pixel_spin.value() == pytest.approx(0.03)  # it was the cell, so it follows
    d.pixel_spin.setValue(0.02)
    d.cell_spin.setValue(0.04)
    assert d.pixel_spin.maximum() == pytest.approx(0.04)
    assert d.pixel_spin.value() == pytest.approx(0.02)  # a finer pixel stays put
    d.cell_spin.setValue(0.015)
    assert d.pixel_spin.value() == pytest.approx(0.015)  # clamped to the cell


def test_the_cell_floor_is_the_largest_safe_cell(make):
    d = make(floor=0.0123, live=0.01)
    assert d.cell_spin.minimum() == pytest.approx(0.013)  # rounded up to a millimetre
    assert d.cell_spin.value() == pytest.approx(0.013)  # the live cell is below it
    d.cell_spin.setValue(0.001)
    assert d.cell_spin.value() == pytest.approx(0.013)


def test_the_summary_for_a_two_grid_site(make):
    d = make(live=0.025)
    d.cell_spin.setValue(0.025)
    d.pixel_spin.setValue(0.0125)
    d.refresh_now()
    assert d.summary_rows() == [
        ("Bands", "18, every 2.5 ns from -1.8 to 45 ns, 5 ns thick"),
        ("Picture", "8000 × 4000 pixels at 0.0125 m"),
        ("Grids", "2 included (A and B), rebuilt at 0.025 m"),
        ("Slices", "kriging, max distance 0.75 × spacing, no smoothing"),
        ("Normalisation", "edge match, measured again at 0.025 m"),
        ("Memory", f"about {format_bytes(HELD)} of the 1.5 GB allowed"),
        ("File", "about 600 MB before compression, plus a style file"),
        ("Disk", "900.0 GB free"),
    ]


def test_the_site_rows_are_absent_for_this_grid(make):
    d = make(grids=None)
    assert [k for k, _ in d.summary_rows()] == [
        "Bands",
        "Picture",
        "Slices",
        "Memory",
        "File",
        "Disk",
    ]


def test_over_budget_disables_export_and_names_the_finest_fit(make):
    # held ~ 1 / (cell * pixel): 2.8 GB at 0.025 / 0.0125.
    k = 2_800_000_000 * 0.025 * 0.0125
    d = make(held=lambda c, p: int(k / (c * p)))
    d.cell_spin.setValue(0.025)
    d.pixel_spin.setValue(0.0125)
    d.refresh_now()
    held = int(k / (0.025 * 0.0125))
    assert not d.export_button.isEnabled()
    # The current cell fits at pixel = cell, so only a finer-than-now pixel is
    # offered: from 0.024 m at this cell.
    assert d.reason_label.text() == export_refusal(held, EXPORT_BUDGET_BYTES, None, 0.024)
    assert d.reason_label.text() == (
        "This export would hold about 2.8 GB in memory, more than the 1.5 GB it is allowed."
        " A 0.024 m export pixel would fit."
    )


def test_over_budget_names_a_cell_when_the_current_one_does_not_fit(make):
    k = 2_800_000_000 * 0.02 * 0.02  # 2.8 GB at 0.02 / 0.02: the cell itself is too fine
    d = make(held=lambda c, p: int(k / (c * p)))
    d.cell_spin.setValue(0.02)
    d.refresh_now()
    assert "export cell would fit." in d.reason_label.text()


def test_the_reason_sits_inside_the_summary_group(make):
    d = make()
    assert d.reason_label.parentWidget() is d.summary_group


def test_target_paths_use_the_companion_rule_whatever_the_suffix(qgis_app, tmp_path):
    from nsgeo_qgis.ui.export_dialog import target_paths

    for suffix in (".tif", ".tiff"):
        t = tmp_path / f"site{suffix}"
        assert target_paths(t) == [
            t,
            tmp_path / "site.qml",
            tmp_path / "site_coverage.tif",
            tmp_path / "site_coverage.qml",
        ]


def test_a_fitting_export_is_enabled_with_no_reason(make):
    d = make()
    d.refresh_now()
    assert d.export_button.isEnabled()
    assert d.reason_label.text() == ""


def test_low_disk_disables_export_with_the_exact_copy(make, monkeypatch):
    monkeypatch.setattr("shutil.disk_usage", lambda p: DISK(10**12, 0, 700_000_000))
    d = make(file_bytes=600_000_000)  # 1.2 x 600 MB = 720 MB > 700 MB free
    d.refresh_now()
    assert not d.export_button.isEnabled()
    assert d.reason_label.text() == (
        f"Not enough free disk space: about {format_bytes(720_000_000)} needed, "
        f"{format_bytes(700_000_000)} free."
    )


def test_disk_exactly_at_the_margin_is_enough(make, monkeypatch):
    monkeypatch.setattr("shutil.disk_usage", lambda p: DISK(10**12, 0, 720_000_000))
    d = make(file_bytes=600_000_000)
    d.refresh_now()
    assert d.export_button.isEnabled()


def test_no_path_disables_export(make):
    d = make(path=False)
    d.refresh_now()
    assert not d.export_button.isEnabled()


def test_the_choice_carries_path_cell_and_pixel(make, tmp_path):
    d = make()
    d.cell_spin.setValue(0.04)
    d.pixel_spin.setValue(0.02)
    assert d.result_settings() == ExportChoice(tmp_path / "site.tif", 0.04, 0.02)
    d.path_edit.setText(str(tmp_path / "other"))
    assert d.result_settings().path == tmp_path / "other.tif"


def test_rapid_spin_changes_compute_the_estimate_once(make):
    d = make()
    n = len(d.preview.calls)  # the first, on open
    for v in (0.04, 0.035, 0.03, 0.028):
        d.cell_spin.setValue(v)
    assert len(d.preview.calls) == n
    _settle(d)
    assert len(d.preview.calls) == n + 1
    assert d.preview.calls[-1] == (pytest.approx(0.028), pytest.approx(0.028))


def test_export_waits_for_the_estimate_after_a_change(make):
    d = make()
    d.cell_spin.setValue(0.03)
    assert not d.export_button.isEnabled()  # stale until recomputed
    _settle(d)
    assert d.export_button.isEnabled()
    assert d.preview.calls[-1][0] == pytest.approx(0.03)


def test_the_dialog_does_not_widen_the_minimum_past_the_panel_rule(make):
    d = make()
    assert d.minimumSizeHint().width() <= 360, d.minimumSizeHint().width()


# ---- decision 17: a target that is already a layer --------------------------


def _tif(path: Path):
    ds = gdal.GetDriverByName("GTiff").Create(str(path), 4, 4, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((0.0, 1.0, 0.0, 4.0, 0.0, -1.0))
    ds.GetRasterBand(1).WriteArray(np.zeros((4, 4), np.float32))
    ds.Close()
    return path


@pytest.fixture
def project_with_target(qgis_app, tmp_path):
    project = QgsProject()
    layer = QgsRasterLayer(str(_tif(tmp_path / "site.tif")), "Site 15 ns", "gdal")
    assert layer.isValid()
    project.addMapLayer(layer)
    return project, layer


def test_targets_in_use_finds_the_target_and_its_companion(qgis_app, tmp_path):
    project = QgsProject()
    target = QgsRasterLayer(str(_tif(tmp_path / "site.tif")), "t", "gdal")
    cover = QgsRasterLayer(str(_tif(tmp_path / "site_coverage.tif")), "c", "gdal")
    other = QgsRasterLayer(str(_tif(tmp_path / "unrelated.tif")), "o", "gdal")
    project.addMapLayers([target, cover, other])
    paths = [
        tmp_path / "site.tif",
        tmp_path / "site.qml",
        tmp_path / "site_coverage.tif",
        tmp_path / "site_coverage.qml",
    ]
    found = targets_in_use(project, paths)
    assert {layer.name() for layer in found} == {"t", "c"}
    assert targets_in_use(QgsProject(), paths) == []


def test_a_target_open_as_a_layer_asks_before_replacing(make, project_with_target):
    project, layer = project_with_target
    d = make(project=project)
    d.export_button.click()
    assert not d.confirm_strip.isHidden()
    assert d.result() != QDialog.DialogCode.Accepted
    assert d.confirm_label.text() == (
        "Site 15 ns is open in this project. Replace it? "
        "The layer is removed and added again when the export finishes."
    )


def test_a_companion_open_as_a_layer_is_not_asked_about_when_none_is_written(make, tmp_path):
    project = QgsProject()
    companion = QgsRasterLayer(str(_tif(tmp_path / "site_coverage.tif")), "Site coverage", "gdal")
    project.addMapLayer(companion)
    d = make(project=project, coverage=False)
    d.export_button.click()
    assert d.confirm_strip.isHidden()
    assert d.result() == QDialog.DialogCode.Accepted
    assert d.layers_to_replace() == []
    again = make(project=project, coverage=True)
    again.export_button.click()
    assert not again.confirm_strip.isHidden()
    assert "Site coverage" in again.confirm_label.text()


def test_a_typed_path_expands_the_home_folder(make):
    d = make()
    d.path_edit.setText("~/slices/out.tif")
    assert d.result_settings().path == Path.home() / "slices" / "out.tif"


def test_replace_accepts_and_names_the_layers(make, project_with_target):
    project, layer = project_with_target
    d = make(project=project)
    d.export_button.click()
    d.replace_button.click()
    assert d.result() == QDialog.DialogCode.Accepted
    assert [x.id() for x in d.layers_to_replace()] == [layer.id()]


def test_cancel_on_the_strip_hides_it_and_keeps_the_dialog_open(make, project_with_target):
    project, _ = project_with_target
    d = make(project=project)
    d.export_button.click()
    d.keep_button.click()
    assert d.confirm_strip.isHidden()
    assert d.result() != QDialog.DialogCode.Accepted
    assert d.layers_to_replace() == []


def test_a_free_target_accepts_without_asking(make):
    d = make()
    d.export_button.click()
    assert d.confirm_strip.isHidden()
    assert d.result() == QDialog.DialogCode.Accepted
    assert d.layers_to_replace() == []


def test_the_dialog_opens_modally_through_exec(make, drive_dialog):
    d = make()
    calls = drive_dialog(QDialog, "exec", lambda dlg: dlg.export_button.click())
    assert d.exec() == QDialog.DialogCode.Accepted
    assert calls == [d]
    QCoreApplication.processEvents()
    assert isinstance(d.buttons, QDialogButtonBox)
