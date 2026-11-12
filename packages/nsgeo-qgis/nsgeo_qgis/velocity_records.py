"""One place to build a velocity source record (grid velocity spec §7.1).

A record copies, for each member, the line's label at the time (plan call P8:
the Survey panel's rule) and is stamped with when it was applied (P6:
ISO-8601 UTC to the second). The velocity dialog, the profile strip and the
Survey panel all follow those two rules, so they live here once.
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from nsgeo.velocity_fit import StoredFit
from nsgeo.velocity_source import SourceFit, VelocitySource

if TYPE_CHECKING:
    from nsgeo_qgis.session import SiteSession


def line_label(line: Any) -> str:
    """A line's name as the Survey panel shows it: its field label, else its
    file's stem."""
    return str(line.placement.label or line.path.stem)


def applied_now() -> str:
    """Now, as a record's `applied_at`: ISO-8601 UTC to the second."""
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fit_record(
    session: SiteSession,
    fits: Iterable[tuple[str, str, StoredFit]],
    *,
    applied_at: str | None,
) -> VelocitySource:
    """The record of `fits`, each `(line key, fit id, fit)` with the fit
    already measured at the zero it was used at: made by `fit` for one, by
    `weighted mean` for several. Each member copies its line's label now."""
    members = [
        SourceFit.of(key, fit_id, line_label(session.line_for_key(key)), fit)
        for key, fit_id, fit in fits
    ]
    return VelocitySource.from_fits(members, applied_at=applied_at)
