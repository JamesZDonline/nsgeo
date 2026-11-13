"""How a Grad601 download was walked: the import setup, and whether a file fits its grid."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any

from nsgeo.geometry.grid import Grid
from nsgeo.mag.grad601 import MISSING_RUN


def _whole_spacings(separation: float, spacing: float) -> bool:
    ratio = separation / spacing
    return ratio >= 1 and abs(ratio - round(ratio)) < 1e-9


@dataclass(frozen=True)
class MagSetup:
    """The walking pattern behind a file, in grid-local terms (defaults are the author's setup).

    `axis` is the grid axis the traverses run along. The first traverse starts
    at `x = size_x` when `far_x`, otherwise at `x = 0`, and likewise for y.
    Traverses are `spacing_m` apart, the first `first_offset_m` from its edge.
    One walking pass logs `sensors` rows that are `sensor_separation_m` apart.
    `zigzag` alternates the direction from pass to pass, and `flipped` says the
    download has already reversed the return traverses.
    """

    axis: str = "y"
    far_x: bool = False
    far_y: bool = False
    spacing_m: float = 0.5
    first_offset_m: float = 0.25
    readings_per_metre: float = 8.0
    sensors: int = 2
    sensor_separation_m: float = 1.0
    zigzag: bool = True
    flipped: bool = True
    missing_run: int = MISSING_RUN

    def __post_init__(self) -> None:
        if self.axis not in ("x", "y"):
            raise ValueError(f"axis must be 'x' or 'y', got {self.axis!r}")
        if not (math.isfinite(self.spacing_m) and self.spacing_m > 0):
            raise ValueError(f"spacing_m must be finite and above 0, got {self.spacing_m!r}")
        if not (math.isfinite(self.first_offset_m) and self.first_offset_m >= 0):
            raise ValueError(
                f"first_offset_m must be finite and at least 0, got {self.first_offset_m!r}"
            )
        if not (math.isfinite(self.readings_per_metre) and self.readings_per_metre > 0):
            raise ValueError(
                f"readings_per_metre must be finite and above 0, got {self.readings_per_metre!r}"
            )
        if self.sensors < 1:
            raise ValueError(f"sensors must be at least 1, got {self.sensors!r}")
        if self.missing_run < 1:
            raise ValueError(f"missing_run must be at least 1, got {self.missing_run!r}")
        if self.sensors > 1 and not (
            math.isfinite(self.sensor_separation_m)
            and _whole_spacings(self.sensor_separation_m, self.spacing_m)
        ):
            raise ValueError(
                f"the sensor separation ({self.sensor_separation_m:g} m) must be a whole "
                f"number of traverse spacings ({self.spacing_m:g} m)"
            )

    def passes_apart(self) -> int:
        """k: how many traverse spacings apart the sensors' rows are; 1 for one sensor."""
        if self.sensors == 1:
            return 1
        return int(round(self.sensor_separation_m / self.spacing_m))

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, doc: Mapping[str, Any]) -> MagSetup:
        """Every key is optional. Raises TypeError or ValueError for a bad value."""
        defaults = cls()
        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            if f.name not in doc:
                continue
            value = doc[f.name]
            default = getattr(defaults, f.name)
            if isinstance(default, bool):
                ok = isinstance(value, bool)
            elif isinstance(default, int):
                ok = isinstance(value, int) and not isinstance(value, bool)
            elif isinstance(default, float):
                ok = isinstance(value, (int, float)) and not isinstance(value, bool)
                value = float(value) if ok else value
            else:
                ok = isinstance(value, str)
            if not ok:
                raise TypeError(f"{f.name} has the wrong type: {value!r}")
            kwargs[f.name] = value
        return cls(**kwargs)


def fit_problems(setup: MagSetup, n_rows: int, n_readings: int, grid: Grid) -> list[str]:
    """What does not fit between a file's shape and its grid; [] when it fits."""
    along, across = ("Y", "X") if setup.axis == "y" else ("X", "Y")
    size_along = grid.size_y if setup.axis == "y" else grid.size_x
    size_across = grid.size_x if setup.axis == "y" else grid.size_y
    rpm = setup.readings_per_metre
    problems = []
    length = n_readings / rpm
    if abs(length - size_along) > 0.5 / rpm:
        problems.append(
            f"{n_readings} readings at {rpm:g} per metre make {length:g} m, "
            f"but the grid is {size_along:g} m along {along}."
        )
    width = n_rows * setup.spacing_m
    if abs(width - size_across) > setup.spacing_m / 2:
        problems.append(
            f"{n_rows} traverses {setup.spacing_m:g} m apart make {width:g} m, "
            f"but the grid is {size_across:g} m across {across}."
        )
    return problems
