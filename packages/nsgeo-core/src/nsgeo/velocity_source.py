"""Where a velocity came from: a record of the fits that made it.

A line's or a grid's velocity can be set from one saved hyperbola fit or from
the weighted mean of several. The record copies each member's numbers as they
were used, so it stays reproducible after a member fit is deleted, its line
is removed or moved, or its line's time zero changes (grid velocity spec §7).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from nsgeo.velocity_fit import StoredFit

__all__ = [
    "METHOD_FIT",
    "METHOD_WEIGHTED_MEAN",
    "SourceFit",
    "VelocitySource",
    "weighted_mean",
]

METHOD_FIT = "fit"
METHOD_WEIGHTED_MEAN = "weighted mean"
_METHODS = (METHOD_FIT, METHOD_WEIGHTED_MEAN)


def weighted_mean(values: Sequence[tuple[float, float]]) -> tuple[float, float]:
    """Inverse-variance mean of `(v, sigma)` pairs and its standard error."""
    if not values:
        raise ValueError("no fits")
    for i, (_, sigma) in enumerate(values, start=1):
        if not math.isfinite(sigma) or sigma <= 0:
            raise ValueError(f"fit {i} has σ {sigma}; it cannot be weighted")
    weights = [1.0 / (s * s) for _, s in values]
    total = sum(weights)
    mean = sum(v * w for (v, _), w in zip(values, weights)) / total
    return mean, 1.0 / math.sqrt(total)


@dataclass(frozen=True)
class SourceFit:
    """One member of a record: a fit's identity and its numbers as used."""

    line_key: str
    fit_id: str
    fitted_at: str
    line_label: str
    t0_ns: float
    v_m_ns: float
    v_stderr_m_ns: float
    zero_ns: float

    @classmethod
    def of(cls, line_key: str, fit_id: str, line_label: str, fit: StoredFit) -> SourceFit:
        """Copy `fit`'s numbers. The caller passes the fit already measured at
        the zero it used."""
        return cls(
            line_key=line_key,
            fit_id=fit_id,
            fitted_at=fit.fitted_at,
            line_label=line_label,
            t0_ns=fit.t0_ns,
            v_m_ns=fit.v_m_ns,
            v_stderr_m_ns=fit.v_stderr_m_ns,
            zero_ns=fit.zero_ns,
        )

    def names(self, fit_id: str, fit: StoredFit) -> bool:
        """True when `fit` is the fit this member copied: same id and `fitted_at`."""
        return self.fit_id == fit_id and self.fitted_at == fit.fitted_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_key": self.line_key,
            "fit_id": self.fit_id,
            "fitted_at": self.fitted_at,
            "line_label": self.line_label,
            "t0_ns": self.t0_ns,
            "v_m_ns": self.v_m_ns,
            "v_stderr_m_ns": self.v_stderr_m_ns,
            "zero_ns": self.zero_ns,
        }

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> SourceFit:
        return cls(
            line_key=_text(doc["line_key"]),
            fit_id=_text(doc["fit_id"]),
            fitted_at=_text(doc["fitted_at"]),
            line_label=_text(doc["line_label"]),
            t0_ns=_finite_number(doc["t0_ns"]),
            v_m_ns=_finite_number(doc["v_m_ns"]),
            v_stderr_m_ns=_finite_number(doc["v_stderr_m_ns"]),
            zero_ns=_finite_number(doc["zero_ns"]),
        )


def _finite_number(value: object) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"expected a number, got {value!r}")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"expected a finite number, got {value!r}")
    return number


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError(f"expected text, got {value!r}")
    return value


@dataclass(frozen=True)
class VelocitySource:
    method: str
    members: tuple[SourceFit, ...]
    v_m_ns: float
    v_stderr_m_ns: float
    applied_at: str | None

    @classmethod
    def from_fits(cls, members: Sequence[SourceFit], applied_at: str | None) -> VelocitySource:
        if not members:
            raise ValueError("no fits")
        if len(members) == 1:
            m = members[0]
            return cls(METHOD_FIT, (m,), m.v_m_ns, m.v_stderr_m_ns, applied_at)
        v, s = weighted_mean([(m.v_m_ns, m.v_stderr_m_ns) for m in members])
        return cls(METHOD_WEIGHTED_MEAN, tuple(members), v, s, applied_at)

    def summary(self) -> str:
        if self.method == METHOD_FIT:
            return f"fit on {self.members[0].line_label}"
        return f"average of {len(self.members)} fits"

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "members": [m.to_dict() for m in self.members],
            "v_m_ns": self.v_m_ns,
            "v_stderr_m_ns": self.v_stderr_m_ns,
            "applied_at": self.applied_at,
        }

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> VelocitySource:
        """Raises ValueError for an unknown method, no members or a bad number."""
        try:
            method = doc["method"]
            if method not in _METHODS:
                raise ValueError(f"unknown method {method!r}")
            raw = doc["members"]
            if not isinstance(raw, list) or not raw:
                raise ValueError("a velocity source needs at least one member")
            applied_at = doc.get("applied_at")
            if applied_at is not None:
                applied_at = _text(applied_at)
            return cls(
                method=method,
                members=tuple(SourceFit.from_dict(m) for m in raw),
                v_m_ns=_finite_number(doc["v_m_ns"]),
                v_stderr_m_ns=_finite_number(doc["v_stderr_m_ns"]),
                applied_at=applied_at,
            )
        except (KeyError, TypeError) as exc:
            raise ValueError(f"malformed velocity source: {exc!r}") from exc
