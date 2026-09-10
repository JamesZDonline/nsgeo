"""What flows through processing, and how steps are discovered.

A step returns a whole Radargram rather than a bare array. Time-zero
correction crops rows, so a step that returned only an array would silently
desynchronise the time axis from the data. Returning the Radargram makes that
an obvious test failure instead of a silent bug.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace as _dc_replace
from typing import Any, Protocol

import numpy as np


@dataclass(frozen=True, eq=False)
class Radargram:
    """Equality is identity (`eq=False`): comparing arrays is a test concern,
    done with `np.testing`."""

    data: np.ndarray
    dt_ns: float
    t0_ns: float

    def __post_init__(self) -> None:
        if np.asarray(self.data).ndim != 2:
            raise ValueError(f"radargram data must be 2-D, got shape {self.data.shape}")
        if not self.dt_ns > 0:
            raise ValueError(f"dt_ns must be positive, got {self.dt_ns}")

    @property
    def n_samples(self) -> int:
        return int(self.data.shape[0])

    @property
    def n_traces(self) -> int:
        return int(self.data.shape[1])

    def times_ns(self) -> np.ndarray:
        """Two-way time of each sample row."""
        return self.t0_ns + np.arange(self.n_samples, dtype=float) * self.dt_ns

    def replace(self, **changes: Any) -> Radargram:
        return _dc_replace(self, **changes)

    @classmethod
    def from_profile(cls, profile: Any) -> Radargram:
        """Build from a model.Profile without importing it, keeping
        processing independent of the data model."""
        return cls(
            data=np.asarray(profile.data, dtype=float),
            dt_ns=profile.header.dt_ns,
            t0_ns=profile.header.position_ns,
        )


class Step(Protocol):
    """A pure function of (parameters, radargram). No I/O, no hidden state."""

    name: str

    @property
    def params(self) -> dict[str, Any]: ...

    def apply(self, rg: Radargram) -> Radargram: ...


_REGISTRY: dict[str, type[Any]] = {}


def register(cls: type[Any]) -> type[Any]:
    """Class decorator adding a step to the registry.

    Front ends enumerate the registry and build parameter widgets from each
    step's declared params, so new instruments contribute steps without any
    UI change.
    """
    _REGISTRY[cls.name] = cls
    return cls


def available_steps() -> list[str]:
    return sorted(_REGISTRY)


def get_step(name: str) -> type[Any]:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown step {name!r}; available: {available_steps()}") from None


def build_step(name: str, **params: Any) -> Any:
    return get_step(name)(**params)
