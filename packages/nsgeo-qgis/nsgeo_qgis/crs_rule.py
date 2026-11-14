"""The one rule for which CRS a site's data is placed in (P10, C10).

Both the Grid dialog and the Import GPS lines dialog ask it: the site's CRS
when it is usable at the spot, else the project's, else that spot's UTM zone.
A CRS is usable when it has an authority code, is in metres, and its metres
are ground metres there (the local scale check).
"""

from __future__ import annotations

import math

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCsException,
    QgsDistanceArea,
    QgsPointXY,
    QgsProject,
    QgsUnitTypes,
)

from nsgeo_qgis.lookup import utm_epsg

# Local scale-factor thresholds for the CRS check (round 3, Finding 1):
# |k - 1| where k is ground distance / declared distance at the grid's own
# origin. Calibrated against real CRSs used as intended (UTM mid-zone/edge,
# British National Grid, a metres state plane: all comfortably under 0.1%;
# CONUS Albers/ETRS89 LAEA, both anisotropic equal-area projections: up to
# ~1.26% away from their centre) against CRSs that are not fit for a metric
# grid frame at all (EPSG:3857 well above both thresholds everywhere off the
# equator; a UTM zone abused three zones over, ~1.4-3%). Warn, but do not
# block, in between -- refusing at 1% would false-refuse legitimate
# Albers/LAEA work.
CRS_SCALE_WARN = 0.001  # 0.1%
CRS_SCALE_REFUSE = 0.02  # ~2%


def crs_scale_error(crs: QgsCoordinateReferenceSystem, point: QgsPointXY) -> float | None:
    """max|k - 1| of `crs`'s local linear scale at `point` (in `crs`
    coordinates), where k = ground (ellipsoidal) distance / declared
    (crs-unit) distance -- or None if it can't be measured.

    A CRS whose stated unit is metres is not the same thing as a CRS whose
    metres are ground metres here: EPSG:3857 (Web Mercator) reports Meters
    and is not geographic, yet its scale factor grows without bound away
    from the equator (round 3, Finding 1). Measuring at (0, 0) specifically
    would be worse than not checking at all -- that is the origin of the
    *CRS*, which for something like EPSG:5070 or EPSG:3035 sits far outside
    the CRS's own area of use and gives a spuriously large error -- so this
    measures at the given point instead, and answers None (skip, don't
    refuse) if the transform/measurement itself fails (e.g. the point lies
    outside the CRS's area of use).
    """
    ox, oy = point.x(), point.y()
    try:
        xform = QgsCoordinateTransform(
            crs, QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance()
        )
        da = QgsDistanceArea()
        da.setEllipsoid("WGS84")
        baseline = 1000.0
        worst = 0.0
        for dx, dy in ((baseline, 0.0), (-baseline, 0.0), (0.0, baseline), (0.0, -baseline)):
            g0 = xform.transform(QgsPointXY(ox, oy))
            g1 = xform.transform(QgsPointXY(ox + dx, oy + dy))
            ground = da.measureLine(g0, g1)
            worst = max(worst, abs(ground / baseline - 1.0))
    except Exception:  # noqa: BLE001 -- see the docstring: skip, don't refuse
        return None
    return worst


def crs_check(
    crs: QgsCoordinateReferenceSystem, point: QgsPointXY | None
) -> tuple[str | None, float | None]:
    """The three checks for `crs` at `point` (in `crs` coordinates; no scale
    check when None): (the failed check, the scale error). The check is
    "authid", "units" or "scale", or None when `crs` is usable there. A CRS
    that only draws the warning is usable."""
    if not crs.authid():
        return "authid", None
    if crs.mapUnits() != Qgis.DistanceUnit.Meters:
        return "units", None
    scale_error = None if point is None else crs_scale_error(crs, point)
    if scale_error is not None and scale_error > CRS_SCALE_REFUSE:
        return "scale", scale_error
    return None, scale_error


def usable_at(
    crs: QgsCoordinateReferenceSystem, lonlat: QgsPointXY
) -> tuple[str | None, float | None]:
    """`crs_check` for `crs` at a lon/lat. A CRS that cannot even place the
    location ("outside", "none") is not usable there."""
    if not crs.isValid():
        return "none", None
    try:
        xform = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem("EPSG:4326"), crs, QgsProject.instance()
        )
        point = xform.transform(lonlat)
    except QgsCsException:
        return "outside", None
    if not (math.isfinite(point.x()) and math.isfinite(point.y())):
        return "outside", None
    return crs_check(crs, point)


def project_reason(
    crs: QgsCoordinateReferenceSystem, kind: str | None, scale_error: float | None
) -> str:
    if not crs.isValid():
        return "the project has no CRS"
    if kind == "authid":
        return "the project CRS has no authority code"
    if kind == "units":
        return f"the project CRS ({crs.authid()}) is in {QgsUnitTypes.toString(crs.mapUnits())}"
    if kind == "outside":
        return f"the project CRS ({crs.authid()}) does not reach this location"
    return f"the project CRS ({crs.authid()}) is off by {(scale_error or 0.0) * 100:.1f}% here"


def choose_crs(
    site: QgsCoordinateReferenceSystem | None,
    project: QgsCoordinateReferenceSystem,
    lonlat: QgsPointXY,
    *,
    site_has_grids: bool = True,
) -> tuple[QgsCoordinateReferenceSystem, str]:
    """The CRS for data at `lonlat`, and the note saying why (C10): the
    site's CRS, else the project's, else that spot's UTM zone, taking the
    first that is usable there. The site's CRS, when it is not the project's,
    is explained as the other grids' CRS only when the site has grids; a site
    whose CRS its GPS lines pinned says "the site's CRS"."""
    if site is not None and usable_at(site, lonlat)[0] is None:
        if site == project:
            return site, ""
        who = "the CRS the site's other grids use" if site_has_grids else "the site's CRS"
        return site, f"picked for you: {who}"
    kind, scale_error = usable_at(project, lonlat)
    if kind is None:
        return project, ""
    epsg = utm_epsg(lonlat.x(), lonlat.y())
    if epsg is None:
        return project, "no UTM zone covers this latitude"
    reason = project_reason(project, kind, scale_error)
    return QgsCoordinateReferenceSystem(f"EPSG:{epsg}"), f"picked for you: {reason}"
