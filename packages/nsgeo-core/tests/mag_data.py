"""Writing Grad601 grid files for tests."""

from __future__ import annotations

from pathlib import Path

import numpy as np


def write_grad601(path: Path, values: np.ndarray) -> Path:
    """Write `values` as a Grad601 file: tab-separated, 2 decimals, CRLF line ends."""
    rows = ["\t".join(f"{v:.2f}" for v in row) for row in np.asarray(values, dtype=float)]
    path.write_bytes(("\r\n".join(rows) + "\r\n").encode("ascii"))
    return path
