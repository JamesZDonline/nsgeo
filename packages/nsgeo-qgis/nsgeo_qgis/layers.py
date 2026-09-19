"""The site GeoPackage: one file, several tables, four rules.

1. Regenerate per table, never per file: rebuilding `lines` truncates and
   refills that table; the file is never deleted, so picks survive and
   Windows file locks never bite.
2. All writes go through the loaded QGIS layer's data provider, never a
   second OGR handle on a package QGIS already has open.
3. Derived tables (grids, lines, marks) are read-only in QGIS; the survey
   JSON is the source of truth for geometry. Picks are authored.
4. A signal slot's exception never reaches whatever emitted the signal --
   PyQt5 prints it to stderr and moves on -- so `refresh()` contains each
   table's own refill and logs a failure via `QgsMessageLog` rather than
   letting one bad table silently cancel the other two.

The package CRS is the CRS of the first grid; other grids are transformed
into it on write. If the first grid's own CRS changes (or a package
predates a field this version of `TABLES` expects), every table is
rebuilt: the derived tables are simply overwritten, since they are fully
refilled anew immediately afterward, but `picks` has no other source of
truth, so its rebuild migrates every row into a fresh table and verifies
it before ever touching the original (see `_rebuild_picks`).
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

import numpy as np
from nsgeo.geometry.grid import Grid
from nsgeo.io.dzx import DzxError, read_dzx
from nsgeo.model.survey import Line
from qgis.core import (
    NULL,
    Qgis,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsMessageLog,
    QgsPointXY,
    QgsProject,
    QgsProviderRegistry,
    QgsRendererCategory,
    QgsSymbol,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QMetaType, QObject, Qt
from qgis.PyQt.QtGui import QColor

from nsgeo_qgis.session import Pick, SiteSession

_KIND = {
    "str": QMetaType.Type.QString,
    "int": QMetaType.Type.Int,
    "float": QMetaType.Type.Double,
}

TABLES: dict[str, tuple[Any, list[tuple[str, str]]]] = {
    "grids": (
        QgsWkbTypes.Type.Polygon,
        [
            ("grid_id", "str"),
            ("azimuth", "float"),
            ("size_x", "float"),
            ("size_y", "float"),
            ("default_spacing", "float"),
            ("velocity_json", "str"),
        ],
    ),
    "lines": (
        QgsWkbTypes.Type.LineString,
        [
            ("line_key", "str"),
            ("grid_id", "str"),
            ("label", "str"),
            ("axis", "str"),
            ("offset_m", "float"),
            ("start_along_m", "float"),
            ("direction", "int"),
            ("n_traces", "int"),
            ("length_m", "float"),
            ("antenna", "str"),
            ("file_name", "str"),
        ],
    ),
    "marks": (
        QgsWkbTypes.Type.Point,
        [("line_key", "str"), ("scan", "int"), ("kind", "str"), ("name", "str")],
    ),
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
}
DERIVED = ("grids", "lines", "marks")

GRID_COLOURS = ["#2f6fb2", "#c0392b", "#27ae60", "#8e44ad", "#d35400", "#16a085"]

# M5 follow-up (Finding 2): a grid's outline used to share its lines'
# colour (both indexed by the grid's position in `site.grids`), which is
# useless with the common case of a single grid. Offsetting the outline's
# index by half of `GRID_COLOURS` puts a grid's outline and its own lines
# at opposite ends of the 6-colour palette -- the maximum separation
# available -- while keeping the two associated by position. Consequence,
# examined rather than left implicit: with 6 colours and an offset of 3, a
# fourth grid's outline reuses the first grid's *line* colour. Lines and
# grids are different layers with different geometry types (LineString vs.
# Polygon) rendered as visually distinct symbols (solid fill vs. dashed
# unfilled stroke) regardless of hue, so a same-hue collision between a
# 4th grid's outline and the 1st grid's lines is not the same confusion
# this fix removes (a layer's own outline vs. its own lines) and is
# accepted.
_GRID_OUTLINE_OFFSET = len(GRID_COLOURS) // 2

# Working table names for a non-destructive picks rebuild (see
# SiteLayers._rebuild_picks): the original is never dropped until a
# verified copy exists under _PICKS_REBUILD.
_PICKS_REBUILD = "picks__rebuild"
_PICKS_BACKUP = "picks__before_rebuild"


def _fields(spec: list[tuple[str, str]]) -> QgsFields:
    fields = QgsFields()
    for name, kind in spec:
        fields.append(QgsField(name, _KIND[kind]))
    return fields


def _log(message: str, level: Qgis.MessageLevel = Qgis.MessageLevel.Warning) -> None:
    QgsMessageLog.logMessage(message, "nsgeo", level)


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


class SiteLayers(QObject):
    def __init__(
        self, session: SiteSession, project: QgsProject | None = None, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.project = project or QgsProject.instance()
        self.layers: dict[str, QgsVectorLayer] = {}
        self.group: Any = None
        session.site_opened.connect(self._on_site_opened)
        session.site_closed.connect(self.detach)
        session.grids_changed.connect(self.refresh)
        session.lines_changed.connect(self.refresh)
        # A layer removed from the legend by hand (or any other code) is
        # gone from QGIS but not from the GeoPackage: drop it from our
        # registry so the next refresh reopens it, rather than holding a
        # Python wrapper around a since-deleted C++ object.
        self.project.layersWillBeRemoved.connect(self._on_layers_removed)
        # Registered here, in the constructor, for the same reason the
        # session signals above are: this must be in place before the
        # first site_opened could fire, not whenever someone remembers.
        session.set_pick_store(self)

    # ---- lifecycle --------------------------------------------------------
    def _on_site_opened(self) -> None:
        self.detach()
        self.refresh()

    def _on_layers_removed(self, ids: list[str]) -> None:
        gone = {
            name for name, lyr in self.layers.items() if not sip.isdeleted(lyr) and lyr.id() in ids
        }
        for name in gone:
            del self.layers[name]

    def detach(self) -> None:
        if self.layers:
            self._commit_pending_edits()
            ids = [lyr.id() for lyr in self.layers.values() if not sip.isdeleted(lyr)]
            if ids:
                self.project.removeMapLayers(ids)
            self.layers.clear()
        if self.group is not None:
            if not sip.isdeleted(self.group):
                parent = self.group.parent()
                if parent is not None:
                    parent.removeChildNode(self.group)
            self.group = None

    def _commit_pending_edits(self) -> None:
        """Save anything still sitting in a layer's edit buffer.

        Final review, I6: `detach()` removed every layer unconditionally,
        and it runs on `site_closed` -- i.e. on every "Open site..." and
        on `unload()`. `picks` is deliberately writable (see
        `ensure_tables`: `setReadOnly(name in DERIVED)`), so a user can
        toggle editing on it in QGIS today. Verified: a layer with
        `isEditable()` and `isModified()` true and one buffered feature
        was destroyed by `removeMapLayers` with no prompt, no signal and
        no exception -- QGIS's own unsaved-edits prompt lives in the
        application's layer-removal *action*, not in
        `QgsProject::removeMapLayers`. Toggle editing, digitise twenty
        depth picks over an hour, forget "Save Layer Edits", click "Open
        site...": silently gone.

        Commit rather than refuse-and-report, which the review allowed
        instead. Refusing would mean keeping a layer bound to a package
        the session no longer owns, in a legend group `detach()` has
        already removed, while the next site opens on top of it -- a
        silent inconsistency traded for a silent loss. And there is no
        prompt to offer: this is a signal slot with no user in it, and by
        the time it runs the decision to close has been taken (the survey
        JSON's own save prompt happens before it, in `new_site`/
        `open_site`/`unload`). Committing is also the recoverable
        direction: a pick the user did not want is still visible and
        deletable, whereas a discarded one is gone.

        Every held layer, not just `picks`, so a future writable table
        gets this for free. The derived three are `setReadOnly(True)`, so
        in practice they can never be in this state.

        If the commit fails there is nothing further to do -- the site is
        closing either way, the same "QGIS cannot be told no here"
        `unload()`'s prompt already reasons from -- so the one thing that
        must not happen is silence: it reports at `Critical`, naming the
        layer and how many edits are being lost.

        One prompt, two stores, and they do not agree -- deliberately.
        "Save the site before continuing?" (`plugin.save_with_prompt`) is
        about the survey JSON. Answering **Discard** to it still gets
        buffered pick edits committed here, because `site_closed` fires
        either way and this runs on it. That reads as a contradiction and
        is not one: the prompt's Discard means "do not write my grid and
        line changes to survey.nsgeo.json", not "throw away the layer I
        was editing", and the two stores fail in opposite directions --
        an unwanted pick is visible and deletable, a discarded one is
        gone. Giving `detach()` a prompt of its own is not available
        either: it is a signal slot with no user in it, reached after the
        decision to close has been taken. What was missing was that
        nothing said so, which is why the success message above spells
        out that the site's save prompt does not cover layer edits.
        """
        for name, layer in self.layers.items():
            try:
                if sip.isdeleted(layer) or not (layer.isEditable() and layer.isModified()):
                    continue
                pending = self._pending_edit_count(layer)
                if layer.commitChanges():
                    _log(
                        f"saved {pending} unsaved edit(s) to {name!r} while closing the "
                        "site; layer edits live in the GeoPackage, not the survey file, "
                        "so the site's own save prompt does not cover them",
                        Qgis.MessageLevel.Info,
                    )
                else:
                    errors = "; ".join(layer.commitErrors()) or "no reason given"
                    _log(
                        f"could not save {pending} unsaved edit(s) to {name!r} "
                        f"before closing the site; they will be lost: {errors}",
                        Qgis.MessageLevel.Critical,
                    )
            except Exception as exc:  # noqa: BLE001 -- see rule 4 above
                # detach() is itself a signal slot (site_closed), so an
                # escape here would be swallowed and the site would half
                # close. One layer's commit failing must not stop the
                # others being tried, nor the teardown below.
                _log(
                    f"could not save unsaved edit(s) to {name!r} before closing "
                    f"the site; they will be lost: {exc}",
                    Qgis.MessageLevel.Critical,
                )

    @staticmethod
    def _pending_edit_count(layer: QgsVectorLayer) -> int:
        """How many buffered edits are about to be committed (or lost).

        Only ever used in a message, so it must not be the thing that
        raises: a provider with no edit buffer reports 0 rather than
        breaking the report it exists to fill in.
        """
        buf = layer.editBuffer()
        if buf is None:
            return 0
        return (
            len(buf.addedFeatures())
            + len(buf.deletedFeatureIds())
            + len(buf.changedGeometries())
            + len(buf.changedAttributeValues())
        )

    def crs(self) -> QgsCoordinateReferenceSystem | None:
        site = self.session.site
        if site is None or not site.grids:
            return None
        return QgsCoordinateReferenceSystem(site.grids[0].crs)

    def refresh(self) -> None:
        site = self.session.site
        if site is None:
            return
        if not site.grids:
            self._clear_derived_tables()
            return
        try:
            self.ensure_tables()
        except Exception as exc:  # noqa: BLE001 -- see rule 4 above
            # ensure_tables() already contains each table's own setup (see
            # below); this is the belt-and-braces catch for anything that
            # still escapes it (e.g. the group itself failing to create).
            # Nothing later in this method can do more than log too, but
            # not returning here matters: whichever refills below don't
            # depend on the table that just failed still get a chance.
            _log(f"could not prepare the site's tables: {exc}", Qgis.MessageLevel.Critical)
        for name, fn in (
            ("grids", self.refill_grids),
            ("lines", self.refill_lines),
            ("marks", self.refill_marks),
        ):
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 -- see rule 4 above
                _log(f"could not refill {name!r}: {exc}", Qgis.MessageLevel.Critical)

    def _clear_derived_tables(self) -> None:
        """No grids left: there is nothing to derive line/mark geometry
        from. The tables were already created while a grid existed, so
        clear them rather than leaving the last grid's stale features on
        the map. `picks` is untouched, same as every other refill."""
        for name in DERIVED:
            if name not in self.layers:
                continue  # a site that has never had a grid: nothing to clear
            try:
                self._refill(name, [])
            except Exception as exc:  # noqa: BLE001 -- see rule 4 above
                _log(f"could not clear {name!r}: {exc}", Qgis.MessageLevel.Critical)

    # ---- tables -----------------------------------------------------------
    def ensure_tables(self) -> None:
        path = str(self.session.gpkg_path)
        crs = self.crs()
        assert crs is not None
        for name, (wkb, spec) in TABLES.items():
            try:
                self._ensure_table(path, name, wkb, spec, crs)
            except Exception as exc:  # noqa: BLE001 -- see rule 4 above
                # This is the largest failure surface in the module (a
                # schema probe, for `picks` a full migration, a create):
                # one table's setup failing here must not silently cancel
                # trying the other three, the same containment refresh()
                # already gives each refill.
                _log(f"could not prepare table {name!r}: {exc}", Qgis.MessageLevel.Critical)
        if self.group is None:
            self.group = self.project.layerTreeRoot().addGroup(f"nsgeo · {self.session.site_name}")
        opened = []
        for name in TABLES:
            if name in self.layers:
                continue
            try:
                layer = QgsVectorLayer(f"{path}|layername={name}", name, "ogr")
                if not layer.isValid():
                    raise RuntimeError(f"could not open table {name!r} in {path}")
                layer.setReadOnly(name in DERIVED)
                self.project.addMapLayer(layer, False)
                self.group.addLayer(layer)
                self.layers[name] = layer
                opened.append(layer)
            except Exception as exc:  # noqa: BLE001 -- see rule 4 above
                _log(f"could not open table {name!r}: {exc}", Qgis.MessageLevel.Critical)
        # A just-(re)created table's provider feature count is sometimes
        # left at the GPKG driver's -1 "not yet counted" sentinel until
        # something forces a recount -- measured to need every table in
        # this GeoPackage opened first: reloading a layer immediately
        # after opening it does not reliably clear it, reloading again
        # once the whole batch is open does. feature_count() below also
        # falls back to counting directly, belt and braces.
        for layer in opened:
            layer.reload()

    def _ensure_table(
        self,
        path: str,
        name: str,
        wkb: Any,
        spec: list[tuple[str, str]],
        crs: QgsCoordinateReferenceSystem,
    ) -> None:
        """Create the table if it doesn't exist yet, or rebuild it if its
        on-disk CRS or field set no longer matches `crs`/`spec`. A grid's
        CRS can change after its table was first created (`replace_grid`),
        and an older package can predate a field this version of `TABLES`
        expects -- either way, refilling into a stale table would write
        the wrong CRS or crash on a missing field.

        `picks` has no other source of truth, so its rebuild
        (`_rebuild_picks`) never destroys the original until a verified
        copy exists elsewhere. The derived tables are about to be fully
        refilled by refill_grids/lines/marks right after this returns, so
        a plain overwrite is safe for them.
        """
        existing_crs, existing_fields = self._table_schema(path, name)
        if name == "picks" and existing_crs is None and self._recover_picks_backup(path):
            # `picks` is missing but a rebuild's backup is sitting on
            # disk: a previous rebuild died between renaming the
            # original out of the way and renaming the migrated table
            # into place (see _rebuild_picks). Recovered rows may or may
            # not still need the rebuild that was interrupted -- re-probe
            # rather than assume, and let the normal logic below decide.
            existing_crs, existing_fields = self._table_schema(path, name)
        up_to_date = existing_crs is not None and existing_crs == crs
        if up_to_date and existing_fields == [f for f, _ in spec]:
            return  # up to date; nothing to rebuild
        if name == "picks" and existing_crs is not None:
            self._rebuild_picks(path, wkb, spec, crs, existing_crs)
            return
        self._drop_loaded_layer(name)
        self._create_table(path, name, wkb, spec, crs)

    def _recover_picks_backup(self, path: str) -> bool:
        """True if a leftover `_PICKS_BACKUP` was renamed back into
        `picks`, False if there was nothing to recover.

        `_rebuild_picks` renames `picks` out of the way before renaming
        the verified migration into place; if the process dies in
        between, the authored rows are still on disk but under the
        backup's name -- invisible to `_table_schema` and therefore, left
        unchecked, silently replaced by a fresh empty table the next time
        `_ensure_table` runs. Restoring first means the rows are seen
        again (and, if the CRS/schema mismatch that started the
        interrupted rebuild is still there, `_rebuild_picks` runs again
        from a fully consistent starting point rather than from nothing).
        """
        if self._table_schema(path, _PICKS_BACKUP)[0] is None:
            return False
        _log(
            "found a leftover picks backup from an interrupted rebuild; "
            "restoring it before continuing",
            Qgis.MessageLevel.Warning,
        )
        conn = QgsProviderRegistry.instance().providerMetadata("ogr").createConnection(path, {})
        conn.renameVectorTable("", _PICKS_BACKUP, "picks")
        return True

    @staticmethod
    def _table_schema(
        path: str, name: str
    ) -> tuple[QgsCoordinateReferenceSystem | None, list[str]]:
        """The on-disk table's CRS and field names, or (None, []) when the
        table doesn't exist yet."""
        if not Path(path).exists():
            return None, []
        layer = QgsVectorLayer(f"{path}|layername={name}", name, "ogr")
        if not layer.isValid():
            return None, []
        return layer.crs(), [f.name() for f in layer.fields() if f.name() != "fid"]

    @staticmethod
    def _drop_table_if_exists(conn: Any, name: str) -> None:
        """Best-effort: drop `name` if the connection can see it, do
        nothing if it can't. Used only to clear a table this method is
        about to need for itself (a stale rebuild backup) -- if nothing
        is actually there, or this raises for some other reason, the
        very next operation that needs `name` to be free (a rename) fails
        loudly on its own account, so silence here never hides a real
        problem, only a no-op.
        """
        with contextlib.suppress(Exception):  # see the caller's comment
            conn.dropVectorTable("", name)

    def _rebuild_picks(
        self,
        path: str,
        wkb: Any,
        spec: list[tuple[str, str]],
        crs: QgsCoordinateReferenceSystem,
        existing_crs: QgsCoordinateReferenceSystem,
    ) -> None:
        """Rebuild `picks` without ever destroying the on-disk rows before
        a verified copy exists elsewhere. `picks` is the one table with
        no other source of truth: unlike grids/lines/marks it cannot be
        regenerated from survey.nsgeo.json, so a failure partway through
        must leave the original recoverable, never silently gone.

        Sequence: migrate every row into a fresh, differently-named table
        and confirm the row count matches exactly (the original `picks`
        is untouched throughout this part); only then rename the
        original out of the way, rename the migrated table into its
        place, and drop the renamed-out original. If the rename-in step
        itself fails, the original is renamed back before re-raising, so
        a failure *within this call* leaves a fully-populated `picks`
        table on disk -- the pre-rebuild one, or the migrated one, never
        neither. If the *process* dies between the two renames, there is
        no code left running to rename back -- `picks` is genuinely
        absent and the pre-rebuild rows sit under the backup name until
        `_ensure_table`'s next call finds it missing and recovers it via
        `_recover_picks_backup` before this method runs again.
        """
        old_rows = self._read_picks_rows(path, existing_crs, crs)

        self._create_table(path, _PICKS_REBUILD, wkb, spec, crs)
        temp_layer = QgsVectorLayer(f"{path}|layername={_PICKS_REBUILD}", _PICKS_REBUILD, "ogr")
        if not temp_layer.isValid():
            raise RuntimeError(
                f"could not open a temporary picks table in {path}; "
                f"the original picks table is untouched"
            )
        if old_rows:
            # Built against the temporary layer's own `.fields()`, not
            # `_fields(spec)`: a GPKG table always carries an implicit
            # leading "fid" field that `spec` doesn't list, and attributes
            # keyed off a Fields object one short of the provider's own
            # silently land one column over (measured directly: a pick's
            # `line_key` came back as its `time_ns` value, `time_ns` as
            # NULL). Setting by field *name* against the real fields is
            # what keeps this correct regardless of column order.
            new_field_names = {f.name() for f in temp_layer.fields()}
            feats = []
            for attrs, geom in old_rows:
                f = QgsFeature(temp_layer.fields())
                for fname, value in attrs.items():
                    if fname in new_field_names:
                        f[fname] = value
                f.setGeometry(geom)
                feats.append(f)
            ok, _ = temp_layer.dataProvider().addFeatures(feats)
            if not ok:
                raise RuntimeError(
                    f"could not migrate picks into a temporary table: "
                    f"{temp_layer.dataProvider().error().message()}; "
                    f"the original picks table is untouched"
                )
        written = temp_layer.featureCount()
        if written < 0:  # the -1 sentinel; see feature_count()
            written = sum(1 for _ in temp_layer.getFeatures())
        if written != len(old_rows):
            raise RuntimeError(
                f"picks migration wrote {written} of {len(old_rows)} rows; "
                f"the original picks table is untouched"
            )
        del temp_layer  # close the write handle before the swap below

        self._drop_loaded_layer("picks")
        conn = QgsProviderRegistry.instance().providerMetadata("ogr").createConnection(path, {})
        # A backup from an earlier, already-finished rebuild has no
        # reason to still be here (the last step of this same method
        # drops it), but if one is, the rename below would fail with
        # "table already exists" on every future rebuild forever rather
        # than just this once -- clear it first. Best-effort: if nothing
        # is there, or this connection cannot see it, there is nothing to
        # clear, and a real failure surfaces normally at the rename below
        # instead of being hidden here.
        self._drop_table_if_exists(conn, _PICKS_BACKUP)
        conn.renameVectorTable("", "picks", _PICKS_BACKUP)
        try:
            conn.renameVectorTable("", _PICKS_REBUILD, "picks")
        except Exception:
            # Put the verified-safe original back rather than leaving
            # "picks" missing while _PICKS_REBUILD (also verified) sits
            # under a different name.
            conn.renameVectorTable("", _PICKS_BACKUP, "picks")
            raise
        conn.dropVectorTable("", _PICKS_BACKUP)

    def _require_transform(
        self, source: QgsCoordinateReferenceSystem, target: QgsCoordinateReferenceSystem
    ) -> QgsCoordinateTransform:
        """A validated coordinate transform, or a loud failure.

        An invalid transform (PROJ has no path between the two CRSs --
        measured with a projected CRS on Earth and a geographic one on
        Mars) does not raise: `QgsCoordinateTransform.isValid()` is
        False, `isShortCircuited()` is True, and both the point- and
        geometry-based `transform()` calls silently return their input
        unchanged while reporting success. Left unchecked, that relabels
        a pick, grid, or line into the wrong CRS while looking like a
        completed transform -- the same defect class as writing a grid's
        old CRS into its table forever (this round's Finding 1),
        discovered while fixing picks specifically but not limited to it.
        """
        transform = QgsCoordinateTransform(source, target, self.project)
        if not transform.isValid():
            raise RuntimeError(
                f"no coordinate transform from {source.authid() or source.toWkt()} to "
                f"{target.authid() or target.toWkt()}; refusing to silently relabel geometry"
            )
        return transform

    def _read_picks_rows(
        self,
        path: str,
        existing_crs: QgsCoordinateReferenceSystem,
        target_crs: QgsCoordinateReferenceSystem,
    ) -> list[tuple[dict[str, Any], QgsGeometry]]:
        """Every row of the current on-disk `picks` table as a plain
        (field name -> value, geometry) pair, geometry already transformed
        if the CRS is changing. Read out *before* the table is touched --
        authored data, unlike grids/lines/marks there is nowhere else
        this comes from, so it must not be silently discarded or
        mis-transformed. Kept as plain dicts rather than `QgsFeature`
        objects tied to the old schema, since the new table's field set
        (and its implicit `fid` column) may not match.
        """
        old_layer = QgsVectorLayer(f"{path}|layername=picks", "picks", "ogr")
        if not old_layer.isValid():
            return []
        transform = None
        if existing_crs != target_crs:
            transform = self._require_transform(existing_crs, target_crs)
        field_names = [f.name() for f in old_layer.fields() if f.name() != "fid"]
        rows = []
        for old in old_layer.getFeatures():
            attrs = {fname: old[fname] for fname in field_names}
            geom = old.geometry()
            if transform is not None and not geom.isNull():
                result = geom.transform(transform)
                if result != Qgis.GeometryOperationResult.Success:
                    raise RuntimeError(
                        f"could not transform a pick's geometry from "
                        f"{existing_crs.authid()} to {target_crs.authid()} (error {result})"
                    )
            rows.append((attrs, geom))
        return rows

    def _drop_loaded_layer(self, name: str) -> None:
        layer = self.layers.pop(name, None)
        if layer is not None and not sip.isdeleted(layer):
            self.project.removeMapLayer(layer.id())

    def _create_table(
        self,
        path: str,
        name: str,
        wkb: Any,
        spec: list[tuple[str, str]],
        crs: QgsCoordinateReferenceSystem,
    ) -> None:
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        opts.layerName = name
        opts.actionOnExistingFile = (
            QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
            if Path(path).exists()
            else QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
        )
        writer = QgsVectorFileWriter.create(
            path, _fields(spec), wkb, crs, self.project.transformContext(), opts
        )
        if writer.hasError() != QgsVectorFileWriter.WriterError.NoError:
            raise RuntimeError(f"could not create table {name!r}: {writer.errorMessage()}")
        del writer  # closes the file handle before the layer opens it

    # ---- geometry helpers -------------------------------------------------
    def _transform_for(self, grid_crs: str) -> QgsCoordinateTransform | None:
        target = self.crs()
        assert target is not None
        source = QgsCoordinateReferenceSystem(grid_crs)
        if source == target:
            return None
        return self._require_transform(source, target)

    def _points(self, xy: np.ndarray, grid_crs: str) -> list[QgsPointXY]:
        tr = self._transform_for(grid_crs)
        pts = [QgsPointXY(float(x), float(y)) for x, y in np.asarray(xy, dtype=float)]
        return [tr.transform(p) for p in pts] if tr is not None else pts

    def _line_points(
        self, line: Line, grid: Grid, frames: dict[str, Grid]
    ) -> list[QgsPointXY] | None:
        """World points for every trace of `line`, or None when the line
        cannot be positioned at all.

        Only `Line.trace_coords` is guarded: it (by way of
        `GridPlacement.distance_along`) raises `ValueError` for a
        time-triggered acquisition (traces_per_metre <= 0), a property of
        one file that must not abort the whole table. `self._points`
        (the CRS transform) stays outside the guard -- a `ValueError`
        from there is a real bug (a bad shape, a broken transform), not
        an unplaceable line, and must not be misreported as one.
        """
        try:
            xy = line.trace_coords(frames)
        except ValueError as exc:
            _log(f"{line.path.name} could not be placed and was left out of the map: {exc}")
            return None
        return self._points(xy, grid.crs)

    def _refill(self, name: str, features: list[QgsFeature]) -> None:
        layer = self.layers[name]
        target = self.crs()
        # A table whose own prep failed this cycle (ensure_tables()
        # contains that failure and moves on, but does not track which
        # table it was) must not be refilled anyway: the geometry being
        # written is computed in `target`, so writing it into a layer
        # still declaring its old CRS would silently mislabel every
        # feature -- stale data left alone is recoverable next refresh;
        # mislabelled data looks correct and is wrong. `target` is only
        # None while clearing derived tables with no grids left, which
        # has no CRS to compare against and every reason to proceed.
        if target is not None and layer.crs() != target:
            raise RuntimeError(
                f"refusing to refill {name!r}: its CRS ({layer.crs().authid()}) does not "
                f"match the package CRS ({target.authid()}); its own preparation must have "
                f"failed this cycle"
            )
        provider = layer.dataProvider()
        if not provider.truncate():
            raise RuntimeError(f"could not truncate {name}: {provider.error().message()}")
        if features:
            ok, _ = provider.addFeatures(features)
            if not ok:
                raise RuntimeError(f"could not write {name}: {provider.error().message()}")
        layer.updateExtents()
        layer.triggerRepaint()

    def feature_count(self, name: str) -> int:
        layer = self.layers[name]
        count = layer.featureCount()
        if count < 0:
            # Belt and braces alongside ensure_tables()'s reload(): the
            # GPKG driver's cached count can come back negative in cases
            # we haven't all named. Counting features directly is correct
            # regardless of why the cache is stale, and this is a handful
            # to a few thousand rows, never a reason to avoid it.
            count = sum(1 for _ in layer.getFeatures())
        return int(count)

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
            raise RuntimeError(
                f"could not write the pick: {layer.dataProvider().error().message()}"
            )
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

    # ---- derived tables ---------------------------------------------------
    def refill_grids(self) -> None:
        site = self.session.site
        assert site is not None
        feats = []
        for grid in site.grids:
            local = np.array(
                [[0.0, 0.0], [grid.size_x, 0.0], [grid.size_x, grid.size_y], [0.0, grid.size_y]]
            )
            ring = self._points(grid.to_world(local), grid.crs)
            f = QgsFeature(self.layers["grids"].fields())
            f.setGeometry(QgsGeometry.fromPolygonXY([ring]))
            f["grid_id"] = grid.id
            f["azimuth"] = grid.azimuth
            f["size_x"] = grid.size_x
            f["size_y"] = grid.size_y
            f["default_spacing"] = grid.default_spacing
            f["velocity_json"] = json.dumps(grid.velocity.to_dict()) if grid.velocity else ""
            feats.append(f)
        self._refill("grids", feats)
        self._style_grids()

    def refill_lines(self) -> None:
        site = self.session.site
        assert site is not None
        feats = []
        keys = self.session.keys()
        for key in keys:
            line = self.session.line_for_key(key)
            grid = self.session.grid_for_line(line)
            if grid is None:
                continue  # trackless lines arrive with TrackPlacement, later
            coords = self._line_points(line, grid, site.frames)
            if coords is None:
                continue  # unplaceable (e.g. time-triggered); degrade, don't abort the table
            f = QgsFeature(self.layers["lines"].fields())
            f.setGeometry(QgsGeometry.fromPolylineXY(coords))
            p: Any = line.placement
            f["line_key"] = key
            f["grid_id"] = grid.id
            f["label"] = p.label or ""
            f["axis"] = p.axis
            f["offset_m"] = float(p.offset)
            f["start_along_m"] = float(p.start_along)
            f["direction"] = int(p.direction)
            f["n_traces"] = int(line.n_traces)
            f["length_m"] = float(line.n_traces / line.header.traces_per_metre)
            f["antenna"] = line.header.antenna
            f["file_name"] = line.path.name
            feats.append(f)
        self._refill("lines", feats)
        self._style_lines()

    def refill_marks(self) -> None:
        site = self.session.site
        assert site is not None
        feats = []
        keys = self.session.keys()
        for key in keys:
            line = self.session.line_for_key(key)
            grid = self.session.grid_for_line(line)
            if grid is None:
                continue
            try:
                info = read_dzx(line.path)
            except DzxError:
                continue
            if info is None or not info.marks:
                continue
            coords = self._line_points(line, grid, site.frames)
            if coords is None:
                continue  # unplaceable line; its marks have nowhere to go either
            for mark in info.marks:
                idx = max(0, min(mark.scan, line.n_traces - 1))
                f = QgsFeature(self.layers["marks"].fields())
                f.setGeometry(QgsGeometry.fromPointXY(coords[idx]))
                f["line_key"] = key
                f["scan"] = int(mark.scan)
                f["kind"] = mark.kind
                f["name"] = mark.name
                feats.append(f)
        self._refill("marks", feats)

    def _style_lines(self) -> None:
        site = self.session.site
        assert site is not None
        categories = []
        for i, grid in enumerate(site.grids):
            symbol = QgsSymbol.defaultSymbol(QgsWkbTypes.GeometryType.LineGeometry)
            symbol.setColor(QColor(GRID_COLOURS[i % len(GRID_COLOURS)]))
            symbol.setWidth(0.5)
            categories.append(QgsRendererCategory(grid.id, symbol, grid.id))
        self.layers["lines"].setRenderer(QgsCategorizedSymbolRenderer("grid_id", categories))
        self.layers["lines"].triggerRepaint()

    def _style_grids(self) -> None:
        # A dashed, unfilled outline: the grid is a reference frame drawn
        # over imagery and basemaps, and an opaque fill would hide the
        # ground the user is judging its placement against. Categorised by
        # `grid_id` and indexed by position in `site.grids`, same as
        # `_style_lines()` above, but offset by `_GRID_OUTLINE_OFFSET` so a
        # grid's outline colour is never the same as its own lines' colour
        # (see the M5 follow-up note by `GRID_COLOURS` above) -- the two
        # are still associated by position, just no longer by identical
        # hue.
        site = self.session.site
        assert site is not None
        categories = []
        for i, grid in enumerate(site.grids):
            symbol = QgsSymbol.defaultSymbol(QgsWkbTypes.GeometryType.PolygonGeometry)
            outline = symbol.symbolLayer(0)
            outline.setBrushStyle(Qt.BrushStyle.NoBrush)
            outline.setStrokeStyle(Qt.PenStyle.DashLine)
            colour_index = (i + _GRID_OUTLINE_OFFSET) % len(GRID_COLOURS)
            outline.setStrokeColor(QColor(GRID_COLOURS[colour_index]))
            outline.setStrokeWidth(0.5)
            categories.append(QgsRendererCategory(grid.id, symbol, grid.id))
        self.layers["grids"].setRenderer(QgsCategorizedSymbolRenderer("grid_id", categories))
        self.layers["grids"].triggerRepaint()


def line_for_feature(session: SiteSession, feature: QgsFeature) -> Line:
    """The session line a `lines` feature represents."""
    return session.line_for_key(str(feature["line_key"]))
