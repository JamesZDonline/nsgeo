"""Helpers shared by both plugin test tiers. Imported as `plugin_testing`."""

from __future__ import annotations

import zlib
from pathlib import Path

import numpy as np
import pytest

CORE_DIR = Path(__file__).resolve().parent.parent.parent / "nsgeo-core"
LOCAL_DATA = CORE_DIR / "tests" / "data" / "local"
REAL_DZT = (
    sorted(p for p in LOCAL_DATA.rglob("*") if p.suffix.lower() == ".dzt")
    if LOCAL_DATA.exists()
    else []
)

needs_real_data = pytest.mark.skipif(not REAL_DZT, reason="no real DZT files in tests/data/local")


def synthetic_dzt(folder: Path, name: str, n_traces: int = 60, **kw) -> Path:
    """A small synthetic DZT with a visible pattern, written into `folder`."""
    from tests.synthetic import write_dzt

    folder.mkdir(parents=True, exist_ok=True)
    # crc32, not hash(): str hashing is salted per-process (PYTHONHASHSEED),
    # so the same `name` would otherwise seed different data every run.
    rng = np.random.default_rng(zlib.crc32(name.encode()))
    data = (rng.normal(size=(512, n_traces)) * 1e6).astype(np.int32)
    data[40:44, :] = 5_000_000  # a flat band, so background removal has something to remove
    path = folder / name
    write_dzt(path, data, **kw)
    return path
