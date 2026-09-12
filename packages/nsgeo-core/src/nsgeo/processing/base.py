"""What flows through processing, and how steps are discovered.

A step returns a whole Radargram rather than a bare array. Time-zero
correction crops rows, so a step that returned only an array would silently
desynchronise the time axis from the data. Returning the Radargram makes that
an obvious test failure instead of a silent bug.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from dataclasses import replace as _dc_replace
from typing import Any, ClassVar, Final, Protocol

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


def nyquist_mhz(dt_ns: float) -> float:
    """Nyquist frequency, in MHz, for a sample interval given in ns.

    `1 / (2 * dt_ns * 1e-9)` in Hz, rearranged to take `dt_ns` directly and
    return MHz: `(1 / (2 * dt_ns * 1e-9)) / 1e6 == 500.0 / dt_ns`. Shared so
    a front end reporting "this file's Nyquist" (a fact about the header,
    not a processing step) and `Bandpass.apply`'s own guard use the same
    formula rather than risking two copies drifting apart.
    """
    return 500.0 / dt_ns


class _Required:
    """Sentinel default meaning: the UI must ask; there is no safe value."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "REQUIRED"


REQUIRED: Final = _Required()


@dataclass(frozen=True)
class ParamSpec:
    """One parameter of a step, declared so a front end can build a widget.

    `kind` decides the widget: float and int are numeric entries with optional
    bounds and a unit, choice is a combo box over `choices`, curve is the gain
    curve editor. `default` is a value or REQUIRED.
    """

    KINDS: ClassVar[tuple[str, ...]] = ("float", "int", "choice", "curve")

    name: str
    kind: str
    label: str
    default: Any
    unit: str | None = None
    min: float | None = None
    max: float | None = None
    choices: tuple[str, ...] = field(default=())
    help: str = ""

    def __post_init__(self) -> None:
        if self.kind not in self.KINDS:
            raise ValueError(f"unknown param kind {self.kind!r}; expected one of {self.KINDS}")
        if self.kind == "choice" and not self.choices:
            raise ValueError(f"param {self.name!r} is a choice but declares no choices")
        if self.kind != "choice" and self.choices:
            raise ValueError(f"param {self.name!r} is {self.kind!r} but declares choices")
        if (
            self.kind == "choice"
            and self.default is not REQUIRED
            and self.default not in self.choices
        ):
            raise ValueError(f"param {self.name!r} default {self.default!r} is not in choices")

    @property
    def required(self) -> bool:
        return self.default is REQUIRED


class Step(Protocol):
    """A pure function of (parameters, radargram). No I/O, no hidden state."""

    name: str

    @property
    def params(self) -> dict[str, Any]: ...

    @classmethod
    def schema(cls) -> tuple[ParamSpec, ...]: ...

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


def default_params(name: str) -> dict[str, Any]:
    """Constructor kwargs for every parameter that has a real default."""
    return {s.name: s.default for s in get_step(name).schema() if not s.required}


def required_params(name: str) -> tuple[str, ...]:
    """Parameters the UI must collect before the step can be built."""
    return tuple(s.name for s in get_step(name).schema() if s.required)
