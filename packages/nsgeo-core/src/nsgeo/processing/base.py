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

    A name may be claimed once. The registry is what a saved
    `{"step": "gain_agc"}` resolves through, so a second front end or a
    user's own step module quietly taking a name already in use would make
    import order decide which implementation a saved stack runs -- the same
    project file producing different processing on different machines, with
    nothing in the file or the UI to say so. Re-registering the very same
    class is allowed, since a module imported twice is not a conflict.
    """
    existing = _REGISTRY.get(cls.name)
    if existing is not None and existing is not cls:
        raise ValueError(
            f"step name {cls.name!r} is already registered to "
            f"{existing.__module__}.{existing.__qualname__}; "
            f"{cls.__module__}.{cls.__qualname__} must choose another name, "
            f"because a saved stack naming it would resolve to whichever was "
            f"imported last"
        )
    _REGISTRY[cls.name] = cls
    return cls


def available_steps() -> list[str]:
    return sorted(_REGISTRY)


def get_step(name: str) -> type[Any]:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown step {name!r}; available: {available_steps()}") from None


def _out_of_bounds(spec: ParamSpec, value: float) -> str | None:
    """Why `value` is outside `spec`'s declared bounds, or None if it is not."""
    if spec.min is not None and value < spec.min:
        return f"must be >= {spec.min}"
    if spec.max is not None and value > spec.max:
        return f"must be <= {spec.max}"
    return None


def _validate_params(name: str, cls: type[Any], params: dict[str, Any]) -> None:
    """Check `params` against `cls.schema()` before the constructor sees them.

    Every step declares bounds and nothing enforced them: `build_step`
    passed `**params` straight through, and the plugin's parameter form
    reads no `spec.min`/`spec.max` at all because its own docstring says
    the core's validation is the only validation. Both halves believed the
    other one checked, so `gain_agc(target=-3.0)` (schema: min 0.0)
    inverted every sample's polarity and `time_zero(threshold=5.0)`
    (schema: max 1.0) silently did nothing -- both reachable from a
    hand-edited project file, a preset copied between machines, or any
    future front end, none of which raised.

    Here rather than in each step's `__init__` because this is the single
    funnel: the UI, `StepStack.from_dicts` (so every saved project and
    every preset), and any second front end all arrive through it. A rule
    added here is enforced for all of them at once; a rule added in a front
    end has to be added again by the next one.

    Raises ValueError, not the TypeError a bad `**kwargs` would otherwise
    produce: callers around every build_step in this repo already treat a
    rejected parameter set as a ValueError, and a parameter that is
    out of bounds is a bad value, not a bad call signature.
    """
    specs = {s.name: s for s in cls.schema()}
    unknown = sorted(set(params) - set(specs))
    if unknown:
        raise ValueError(f"step {name!r} has no parameter(s) {unknown}; it takes {sorted(specs)}")
    missing = sorted(s.name for s in specs.values() if s.required and s.name not in params)
    if missing:
        raise ValueError(f"step {name!r} requires {missing}, which has no safe default")
    for pname in sorted(params):
        spec = specs[pname]
        value = params[pname]
        if spec.kind in ("float", "int"):
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise ValueError(
                    f"step {name!r}: {pname} must be a number, got {value!r}"
                ) from None
            reason = _out_of_bounds(spec, number)
            if reason is not None:
                unit = f" {spec.unit}" if spec.unit else ""
                raise ValueError(f"step {name!r}: {pname} {reason}, got {value!r}{unit}")
        elif spec.kind == "curve" and (spec.min is not None or spec.max is not None):
            # A curve's bounds apply to its second column -- the schema's
            # `unit` is what min/max are expressed in (dB for gain_curve),
            # while the first column is a time axis the radargram bounds.
            try:
                column = [float(point[1]) for point in value]
            except (TypeError, ValueError, IndexError, KeyError):
                continue  # malformed shape: the constructor says so better
            for entry in column:
                reason = _out_of_bounds(spec, entry)
                if reason is not None:
                    unit = f" {spec.unit}" if spec.unit else ""
                    raise ValueError(
                        f"step {name!r}: every {pname} value {reason}, got {entry}{unit}"
                    )


def build_step(name: str, **params: Any) -> Any:
    """The one way a step is constructed. Validates against `schema()` first."""
    cls = get_step(name)
    _validate_params(name, cls, params)
    return cls(**params)


def default_params(name: str) -> dict[str, Any]:
    """Constructor kwargs for every parameter that has a real default."""
    return {s.name: s.default for s in get_step(name).schema() if not s.required}


def required_params(name: str) -> tuple[str, ...]:
    """Parameters the UI must collect before the step can be built."""
    return tuple(s.name for s in get_step(name).schema() if s.required)
