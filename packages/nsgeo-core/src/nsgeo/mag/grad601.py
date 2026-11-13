"""Bartington Grad601 grid files: reading them and marking the readings that are missing.

A file is plain text, one traverse per row, readings separated by whitespace.
The instrument writes 0.00 where it logged nothing, so a run of exact zeros is
missing data and a lone 0.00 is a reading.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

MISSING_RUN = 4
"""Runs of at least this many consecutive 0.00 readings are missing data."""

_LISTED = 6


class MagFileError(ValueError):
    """A file that does not look like a Grad601 grid file; the message names the file and row."""


def read_grad601(path: Path) -> np.ndarray:
    """The file as float64 (n_rows, n_readings), as written, zeros kept."""
    path = Path(path)
    name = path.name
    text = path.read_bytes().decode("utf-8", errors="replace")
    rows: list[list[float]] = []
    for i, line in enumerate(text.splitlines(), start=1):
        tokens = line.split()
        if not tokens:
            continue
        if rows and len(tokens) != len(rows[0]):
            raise MagFileError(
                f"{name}: row {i} has {len(tokens)} readings but row 1 has {len(rows[0])}; "
                "this does not look like a Grad601 grid file"
            )
        row = []
        for token in tokens:
            try:
                row.append(float(token))
            except ValueError:
                raise MagFileError(
                    f"{name}: row {i} holds {token!r}, which is not a number"
                ) from None
        rows.append(row)
    if not rows:
        raise MagFileError(f"{name} holds no readings")
    return np.array(rows, dtype=np.float64)


def mark_missing(raw: np.ndarray, min_run: int = MISSING_RUN) -> np.ndarray:
    """A copy with NaN for each run of at least `min_run` consecutive exact 0.0 along a row."""
    out = np.array(raw, dtype=np.float64, copy=True)
    for r in range(out.shape[0]):
        zero = out[r] == 0.0
        j = 0
        n = zero.size
        while j < n:
            if not zero[j]:
                j += 1
                continue
            k = j
            while k < n and zero[k]:
                k += 1
            if k - j >= min_run:
                out[r, j:k] = np.nan
            j = k
    return out


def missing_summary(readings: np.ndarray) -> str:
    """One sentence on the NaN readings and the traverses (numbered from 1) they are on."""
    nan = np.isnan(readings)
    n = int(nan.sum())
    if n == 0:
        return "No readings are missing data."
    rows = [int(r) + 1 for r in np.flatnonzero(nan.any(axis=1))]
    verb = "reading is" if n == 1 else "readings are"
    if len(rows) > _LISTED:
        where = ", ".join(str(r) for r in rows[:_LISTED]) + f" and {len(rows) - _LISTED} more"
    elif len(rows) == 1:
        where = str(rows[0])
    else:
        where = ", ".join(str(r) for r in rows[:-1]) + f" and {rows[-1]}"
    plural = "traverse" if len(rows) == 1 else "traverses"
    return f"{n} {verb} missing data, on {plural} {where}."
