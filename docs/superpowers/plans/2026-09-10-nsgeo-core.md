# nsgeo Core Library (Plan 1: M0–M3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `nsgeo`, a pure-Python core library that reads GSSI DZT files, models a georeferenced survey, and applies user-ordered processing steps — with no QGIS dependency and no UI.

**Architecture:** Four layers with one-way dependencies: `io` (format readers) → `model` (Profile/Line/Grid/Site) → `geometry` (placements, grid affine) → `processing` (step registry and stack). Everything is plain dataclasses and numpy arrays. Nothing imports QGIS, Qt, matplotlib, or scipy, and a test enforces that.

**Tech Stack:** Python 3.9+, numpy (only runtime dependency), pytest, ruff, mypy, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-10-nsgeo-gpr-qgis-design.md`

## Global Constraints

Copied verbatim from the spec. Every task's requirements implicitly include these.

- **Python 3.9+.** Use `from __future__ import annotations` in every module. No `X | Y` union syntax at runtime; use `typing.Optional` / `typing.Union` where an annotation is evaluated.
- **numpy is the only runtime dependency.** scipy is an optional accelerator only, imported lazily inside a function, never at module level. matplotlib, qgis, and PyQt must not appear anywhere in `src/nsgeo`.
- **Raw data is never mutated.** `Profile.data` is the raw array. Processing produces new arrays.
- **Nothing runs automatically.** No step is applied unless explicitly added to a stack.
- **A step returns a whole `Radargram`,** never a bare array, so time-axis metadata cannot desynchronise from the data.
- **Real survey files are never committed.** They live in `packages/nsgeo-core/tests/data/local/`, which is gitignored. Tests that need them skip when absent.
- Licence header/package metadata: core is **MIT**.

## Verified DZT facts (from spec §6a — do not re-derive)

These were measured against ten real SIR-4000 files. A reader that ignores any of them produces plausible-looking but wrong data.

| Fact | Value |
|---|---|
| `rh_tag` | **2047** (0x07FF) in real files, not the widely cited 255 |
| Header size | `1024 * rh_data` when `rh_data < 1024`, else `1024 * rh_nchan` |
| Real `rh_data` | 128 → header is **131,072 bytes** |
| Header *fields* | All within the **first 1024 bytes** (this is why header parsing is cheap; do not confuse with header *size*) |
| `rh_nsamp` | 512 |
| `rh_bits` | 32 → signed `int32`, centred near zero |
| `rh_zero` | 105 — **not** a valid sentinel; do not apply it |
| `rhf_spm` | 60 traces/m |
| Leading zero traces | Normal (recording before cart moves) — never trim |
| Non-integer trace count | **Hard error**, never truncate |

Only 32-bit files have been validated. 8- and 16-bit paths are written from the format description and must be marked as unvalidated.

---

### Task 1: Repo scaffold, tooling, and the boundary test

Establishes the package, test runner, linting, CI, and the mechanical guard that keeps the core free of QGIS/Qt/matplotlib/scipy. Nothing else is verifiable until this exists.

**Files:**
- Create: `packages/nsgeo-core/pyproject.toml`
- Create: `packages/nsgeo-core/src/nsgeo/__init__.py`
- Create: `packages/nsgeo-core/tests/test_boundary.py`
- Create: `.github/workflows/ci.yml`
- Create: `ruff.toml`

**Interfaces:**
- Consumes: nothing
- Produces: an installable `nsgeo` package exposing `__version__: str`

- [ ] **Step 1: Write the failing boundary test**

Create `packages/nsgeo-core/tests/test_boundary.py`:

```python
"""The core must never import QGIS, Qt, matplotlib, or scipy at module level.

This is what makes a single repository safe: the rule fails the build rather
than relying on vigilance. It also catches scipy becoming a hard dependency
and matplotlib appearing at all, neither of which a repo split would catch.
"""
from __future__ import annotations

import ast
import pathlib

import nsgeo

SRC = pathlib.Path(nsgeo.__file__).parent

FORBIDDEN = {"qgis", "PyQt5", "PyQt6", "PySide2", "PySide6", "matplotlib", "scipy"}


def _module_level_imports(tree: ast.Module) -> set[str]:
    """Top-level import names only. Imports inside functions are allowed,
    which is how scipy may be used as an optional accelerator."""
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                found.add(node.module.split(".")[0])
    return found


def test_no_forbidden_module_level_imports() -> None:
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        bad = _module_level_imports(tree) & FORBIDDEN
        if bad:
            offenders.append(f"{path.relative_to(SRC)}: {sorted(bad)}")
    assert not offenders, "forbidden module-level imports:\n" + "\n".join(offenders)


def test_src_tree_is_actually_being_scanned() -> None:
    """Guards against the test silently passing because it found no files."""
    assert len(list(SRC.rglob("*.py"))) >= 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_boundary.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo'`

- [ ] **Step 3: Create the package and pyproject**

Create `packages/nsgeo-core/src/nsgeo/__init__.py`:

```python
"""nsgeo — near-surface geophysics core library."""
from __future__ import annotations

__version__ = "0.1.0.dev0"
```

Create `packages/nsgeo-core/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "nsgeo"
version = "0.1.0.dev0"
description = "Near-surface geophysics: survey processing, analysis, and visualisation"
readme = "README.md"
requires-python = ">=3.9"
license = { text = "MIT" }
dependencies = ["numpy>=1.20"]

[project.optional-dependencies]
dev = ["pytest>=7", "mypy>=1.5", "ruff>=0.5"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.mypy]
python_version = "3.9"
disallow_untyped_defs = true
warn_unused_ignores = true
warn_redundant_casts = true
no_implicit_optional = true
# Deliberately not `strict = true`: numpy's stubs and the step-registry
# decorator produce a stream of Any-related errors that would be silenced
# with ignores rather than fixed, which is worse than not asking.
```

Create `ruff.toml` at the repo root:

```toml
line-length = 100
target-version = "py39"

[lint]
select = ["E", "F", "I", "UP", "B", "SIM"]
```

- [ ] **Step 4: Install and verify the test passes**

Run:
```bash
cd packages/nsgeo-core && python -m pip install -e ".[dev]" && python -m pytest tests/ -v
```
Expected: both tests PASS

- [ ] **Step 5: Add CI**

Create `.github/workflows/ci.yml`:

```yaml
name: CI
on: [push, pull_request]

jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
        python: ["3.9", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - run: python -m pip install -e "./packages/nsgeo-core[dev]"
      - run: python -m pytest packages/nsgeo-core/tests -v

  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install ruff mypy numpy
      - run: ruff check .
      - run: ruff format --check .
      - run: mypy packages/nsgeo-core/src/nsgeo
```

- [ ] **Step 6: Verify lint and types pass locally**

Run:
```bash
cd /home/jameszd/Documents/Github/archaeo_geophysics
ruff check . && ruff format --check . && mypy packages/nsgeo-core/src/nsgeo
```
Expected: all clean

- [ ] **Step 7: Commit**

```bash
git add packages/nsgeo-core .github ruff.toml
git commit -m "feat: scaffold nsgeo core package with boundary test and CI

The boundary test walks the AST of every core module and fails the build on
any module-level import of qgis, PyQt, matplotlib, or scipy. It lands before
there is any code to violate it."
```

---

### Task 2: DZT header parsing

Parses the fixed header fields, all of which live in the first 1024 bytes, and computes the data offset using the verified `1024 * rh_data` rule. Includes a synthetic DZT writer used only by tests.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/io/__init__.py`
- Create: `packages/nsgeo-core/src/nsgeo/io/dzt.py`
- Create: `packages/nsgeo-core/tests/synthetic.py`
- Create: `packages/nsgeo-core/tests/test_dzt_header.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `DztHeader` dataclass with fields `tag: int`, `n_samples: int`, `bits: int`, `n_channels: int`, `data_offset: int`, `samples_per_second: float`, `traces_per_metre: float`, `range_ns: float`, `position_ns: float`, `epsr: float`, `antenna: str`, `zero: int`
  - `DztHeader.dt_ns -> float` property
  - `parse_header(raw: bytes) -> DztHeader`
  - `read_header(path) -> DztHeader`
  - `DztError(Exception)`
  - `tests/synthetic.py: write_dzt(path, data, *, traces_per_metre=60.0, range_ns=110.864, bits=32, n_channels=1, rh_data=128) -> None`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/synthetic.py`:

```python
"""Test-only DZT writer. Produces files with known headers and known samples
so the reader can be round-trip tested without committing real survey data."""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

MINHEADSIZE = 1024


def write_dzt(
    path: Path,
    data: np.ndarray,
    *,
    traces_per_metre: float = 60.0,
    range_ns: float = 110.864,
    bits: int = 32,
    n_channels: int = 1,
    rh_data: int = 128,
    tag: int = 2047,
) -> None:
    """Write `data` (n_samples, n_traces) as a DZT file.

    For n_channels > 1, `data` is (n_channels, n_samples, n_traces) and
    channels are interleaved per trace, which is how GSSI writes them.
    """
    if n_channels == 1:
        n_samples, n_traces = data.shape
        stack = data[None, :, :]
    else:
        stack = data
        _, n_samples, n_traces = stack.shape

    head = bytearray(MINHEADSIZE)
    struct.pack_into("<H", head, 0, tag)
    struct.pack_into("<H", head, 2, rh_data)
    struct.pack_into("<H", head, 4, n_samples)
    struct.pack_into("<H", head, 6, bits)
    struct.pack_into("<h", head, 8, 105)          # rh_zero: junk, as in real files
    struct.pack_into("<f", head, 10, 250.0)       # rhf_sps
    struct.pack_into("<f", head, 14, traces_per_metre)
    struct.pack_into("<f", head, 18, 5.0)         # rhf_mpm
    struct.pack_into("<f", head, 22, -11.086)     # rhf_position
    struct.pack_into("<f", head, 26, range_ns)
    struct.pack_into("<H", head, 52, n_channels)
    struct.pack_into("<f", head, 54, 14.0)        # rhf_epsr
    head[98:98 + 7] = b"HS350US"

    headsize = MINHEADSIZE * rh_data if rh_data < MINHEADSIZE else MINHEADSIZE * n_channels
    blob = bytearray(headsize)
    blob[:MINHEADSIZE] = head

    dtype = {8: "<u1", 16: "<i2", 32: "<i4"}[bits]
    # interleave channels per trace: trace0ch0, trace0ch1, trace1ch0, ...
    interleaved = np.transpose(stack, (2, 0, 1)).astype(dtype).reshape(-1)
    path.write_bytes(bytes(blob) + interleaved.tobytes())
```

Create `packages/nsgeo-core/tests/test_dzt_header.py`:

```python
from __future__ import annotations

import numpy as np
import pytest

from nsgeo.io.dzt import DztError, parse_header, read_header
from tests.synthetic import write_dzt


def test_header_size_uses_rh_data_rule(tmp_path):
    """Verified against real files: rh_data=128 means a 131072-byte header,
    not the 1024-byte minimum. Getting this wrong yields a non-integer
    trace count and silently misaligned data."""
    p = tmp_path / "a.DZT"
    write_dzt(p, np.zeros((512, 10), dtype=np.int32), rh_data=128)
    h = read_header(p)
    assert h.data_offset == 131072


def test_header_size_falls_back_to_channel_rule(tmp_path):
    p = tmp_path / "b.DZT"
    write_dzt(p, np.zeros((512, 10), dtype=np.int32), rh_data=1024, n_channels=2)
    h = read_header(p)
    assert h.data_offset == 2048


def test_parses_verified_real_world_field_values(tmp_path):
    p = tmp_path / "c.DZT"
    write_dzt(p, np.zeros((512, 10), dtype=np.int32))
    h = read_header(p)
    assert h.tag == 2047          # real files use 0x07FF, not the cited 255
    assert h.n_samples == 512
    assert h.bits == 32
    assert h.n_channels == 1
    assert h.traces_per_metre == pytest.approx(60.0)
    assert h.range_ns == pytest.approx(110.864, abs=1e-3)
    assert h.antenna == "HS350US"


def test_dt_ns_is_range_over_samples(tmp_path):
    p = tmp_path / "d.DZT"
    write_dzt(p, np.zeros((512, 10), dtype=np.int32), range_ns=102.4)
    h = read_header(p)
    assert h.dt_ns == pytest.approx(0.2)


def test_rejects_short_file():
    with pytest.raises(DztError, match="too short"):
        parse_header(b"\x00" * 100)


def test_rejects_unknown_bit_depth(tmp_path):
    raw = bytearray(1024)
    import struct
    struct.pack_into("<H", raw, 0, 2047)
    struct.pack_into("<H", raw, 2, 128)
    struct.pack_into("<H", raw, 4, 512)
    struct.pack_into("<H", raw, 6, 24)      # unsupported
    struct.pack_into("<H", raw, 52, 1)
    with pytest.raises(DztError, match="bit depth"):
        parse_header(bytes(raw))


def test_rejects_zero_samples():
    import struct
    raw = bytearray(1024)
    struct.pack_into("<H", raw, 0, 2047)
    struct.pack_into("<H", raw, 2, 128)
    struct.pack_into("<H", raw, 4, 0)
    struct.pack_into("<H", raw, 6, 32)
    struct.pack_into("<H", raw, 52, 1)
    with pytest.raises(DztError, match="samples"):
        parse_header(bytes(raw))
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_dzt_header.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo.io'`

- [ ] **Step 3: Implement the header parser**

Create `packages/nsgeo-core/src/nsgeo/io/__init__.py`:

```python
"""Format readers."""
from __future__ import annotations
```

Create `packages/nsgeo-core/src/nsgeo/io/dzt.py`:

```python
"""GSSI DZT reader.

Written from the format description and verified against ten real SIR-4000
files. See spec section 6a: several widely cited facts about this format do
not hold in real data, and each is called out at the point it matters.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Union

MINHEADSIZE = 1024

#: Sample dtype by rh_bits. Only 32-bit has been validated against real files;
#: the 8- and 16-bit paths come from the format description and are untested.
_DTYPES = {8: "<u1", 16: "<i2", 32: "<i4"}


class DztError(Exception):
    """Raised when a DZT file is malformed or uses an unsupported variant."""


@dataclass(frozen=True)
class DztHeader:
    tag: int
    n_samples: int
    bits: int
    n_channels: int
    data_offset: int
    samples_per_second: float
    traces_per_metre: float
    range_ns: float
    position_ns: float
    epsr: float
    antenna: str
    zero: int

    @property
    def dt_ns(self) -> float:
        """Sample interval in nanoseconds."""
        return self.range_ns / self.n_samples

    @property
    def bytes_per_sample(self) -> int:
        return self.bits // 8

    @property
    def dtype(self) -> str:
        return _DTYPES[self.bits]


def parse_header(raw: bytes) -> DztHeader:
    """Parse a DZT header from at least the first 1024 bytes.

    All header *fields* live within the first 1024 bytes, which is why opening
    a survey is cheap. This is distinct from the header *size*, which is
    1024 * rh_data and is commonly far larger.
    """
    if len(raw) < MINHEADSIZE:
        raise DztError(f"file too short for a DZT header: {len(raw)} bytes")

    tag = struct.unpack_from("<H", raw, 0)[0]
    rh_data = struct.unpack_from("<H", raw, 2)[0]
    n_samples = struct.unpack_from("<H", raw, 4)[0]
    bits = struct.unpack_from("<H", raw, 6)[0]
    zero = struct.unpack_from("<h", raw, 8)[0]
    sps = struct.unpack_from("<f", raw, 10)[0]
    spm = struct.unpack_from("<f", raw, 14)[0]
    position = struct.unpack_from("<f", raw, 22)[0]
    range_ns = struct.unpack_from("<f", raw, 26)[0]
    n_channels = struct.unpack_from("<H", raw, 52)[0] or 1
    epsr = struct.unpack_from("<f", raw, 54)[0]
    antenna = raw[98:112].split(b"\x00")[0].decode("latin-1").strip()

    if n_samples == 0:
        raise DztError("header declares zero samples per trace")
    if bits not in _DTYPES:
        raise DztError(f"unsupported bit depth {bits}; expected one of {sorted(_DTYPES)}")

    # Verified against real files: rh_data is 128, giving a 131072-byte header.
    # Assuming MINHEADSIZE here produces a non-integer trace count.
    if rh_data < MINHEADSIZE:
        data_offset = MINHEADSIZE * rh_data
    else:
        data_offset = MINHEADSIZE * n_channels

    return DztHeader(
        tag=tag,
        n_samples=n_samples,
        bits=bits,
        n_channels=n_channels,
        data_offset=data_offset,
        samples_per_second=sps,
        traces_per_metre=spm,
        range_ns=range_ns,
        position_ns=position,
        epsr=epsr,
        antenna=antenna,
        zero=zero,
    )


def read_header(path: Union[str, Path]) -> DztHeader:
    """Read only the header. Cheap: reads 1024 bytes regardless of file size."""
    with open(path, "rb") as fh:
        return parse_header(fh.read(MINHEADSIZE))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_dzt_header.py -v`
Expected: all 7 PASS

- [ ] **Step 5: Commit**

```bash
git add packages/nsgeo-core/src/nsgeo/io packages/nsgeo-core/tests
git commit -m "feat: parse DZT headers with the verified rh_data size rule

Header size is 1024 * rh_data, not the 1024-byte minimum. Adds a test-only
synthetic DZT writer so the reader is round-trip tested without committing
real survey data."
```

---

### Task 3: DZT sample reading

Reads sample arrays, de-interleaves channels, and treats a non-integer trace count as a hard error rather than truncating.

**Files:**
- Modify: `packages/nsgeo-core/src/nsgeo/io/dzt.py`
- Create: `packages/nsgeo-core/tests/test_dzt_read.py`

**Interfaces:**
- Consumes: `DztHeader`, `parse_header`, `read_header`, `DztError` from Task 2
- Produces:
  - `trace_count(path, header) -> int`
  - `read_samples(path, header=None) -> np.ndarray` returning `(n_channels, n_samples, n_traces)`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_dzt_read.py`:

```python
from __future__ import annotations

import numpy as np
import pytest

from nsgeo.io.dzt import DztError, read_header, read_samples, trace_count
from tests.synthetic import write_dzt


def test_round_trips_single_channel(tmp_path):
    rng = np.random.default_rng(0)
    data = rng.integers(-10_000, 10_000, size=(512, 37)).astype(np.int32)
    p = tmp_path / "a.DZT"
    write_dzt(p, data)
    out = read_samples(p)
    assert out.shape == (1, 512, 37)
    np.testing.assert_array_equal(out[0], data)


def test_round_trips_multi_channel(tmp_path):
    rng = np.random.default_rng(1)
    data = rng.integers(-10_000, 10_000, size=(2, 512, 21)).astype(np.int32)
    p = tmp_path / "b.DZT"
    write_dzt(p, data, n_channels=2)
    out = read_samples(p)
    assert out.shape == (2, 512, 21)
    np.testing.assert_array_equal(out, data)


def test_trace_count_matches(tmp_path):
    p = tmp_path / "c.DZT"
    write_dzt(p, np.zeros((512, 44), dtype=np.int32))
    assert trace_count(p, read_header(p)) == 44


def test_non_integer_trace_count_is_a_hard_error(tmp_path):
    """The diagnostic that caught a wrong header-size assumption against real
    files. Truncating instead would turn a wrong header size into
    plausible-looking but misaligned data."""
    p = tmp_path / "d.DZT"
    write_dzt(p, np.zeros((512, 10), dtype=np.int32))
    with open(p, "ab") as fh:
        fh.write(b"\x00" * 7)          # a partial trace
    with pytest.raises(DztError, match="non-integer trace count"):
        read_samples(p)


def test_leading_zero_traces_are_preserved(tmp_path):
    """Recording starts before the cart moves. These are data, not corruption."""
    data = np.ones((512, 20), dtype=np.int32)
    data[:, :4] = 0
    p = tmp_path / "e.DZT"
    write_dzt(p, data)
    out = read_samples(p)
    assert out.shape == (1, 512, 20)
    assert not out[0, :, :4].any()
    assert out[0, :, 4:].all()


def test_empty_payload_raises(tmp_path):
    p = tmp_path / "f.DZT"
    write_dzt(p, np.zeros((512, 0), dtype=np.int32))
    with pytest.raises(DztError, match="no traces"):
        read_samples(p)


def test_rh_zero_is_not_applied_as_an_offset(tmp_path):
    """rh_zero is 105 in real files, which is not a valid sentinel. Applying it
    would shift every sample by a garbage offset."""
    data = np.full((512, 5), 1234, dtype=np.int32)
    p = tmp_path / "g.DZT"
    write_dzt(p, data)
    out = read_samples(p)
    assert out[0, 0, 0] == 1234
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_dzt_read.py -v`
Expected: FAIL — `ImportError: cannot import name 'read_samples'`

- [ ] **Step 3: Implement reading**

Append to `packages/nsgeo-core/src/nsgeo/io/dzt.py`:

```python
def _bytes_per_trace(header: DztHeader) -> int:
    return header.n_samples * header.bytes_per_sample * header.n_channels


def trace_count(path: Union[str, Path], header: DztHeader) -> int:
    """Number of traces, derived from file size. Raises if not a whole number."""
    payload = Path(path).stat().st_size - header.data_offset
    if payload <= 0:
        raise DztError(f"file has no traces after a {header.data_offset}-byte header")
    per = _bytes_per_trace(header)
    if payload % per:
        raise DztError(
            f"non-integer trace count: {payload} payload bytes is not divisible by "
            f"{per} bytes/trace. The header size ({header.data_offset}) is probably "
            f"wrong; refusing to truncate because that would silently misalign data."
        )
    return payload // per


def read_samples(path: Union[str, Path], header: Optional[DztHeader] = None) -> np.ndarray:
    """Read all samples as (n_channels, n_samples, n_traces).

    Channels are interleaved per trace on disk. Raw values are returned
    unmodified: no zero-offset is applied, because rh_zero is not trustworthy
    (it is 105 in real files, neither documented sentinel).
    """
    path = Path(path)
    if header is None:
        header = read_header(path)
    n_traces = trace_count(path, header)
    flat = np.fromfile(path, dtype=np.dtype(header.dtype), offset=header.data_offset)
    expected = n_traces * header.n_channels * header.n_samples
    if flat.size != expected:
        raise DztError(f"expected {expected} samples, read {flat.size}")
    return flat.reshape(n_traces, header.n_channels, header.n_samples).transpose(1, 2, 0)
```

In `dzt.py`, change the existing `from typing import Union` line to:

```python
from typing import Optional, Union
```

and add below the `struct` import:

```python
import numpy as np
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/nsgeo-core && python -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add packages/nsgeo-core
git commit -m "feat: read DZT samples with hard failure on non-integer trace count

Refuses to truncate a partial trace, because that is precisely how a wrong
header size produces plausible-looking but misaligned data. Applies no
zero-offset: rh_zero is not trustworthy in real files."
```

---

### Task 4: Grid coordinate frame and the world transform

`Grid` lives in `geometry`, not `model`, because the spec defines it as a coordinate frame rather than a container. This also keeps the dependency graph acyclic: `io` → `geometry` → `model`.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/geometry/__init__.py`
- Create: `packages/nsgeo-core/src/nsgeo/geometry/grid.py`
- Create: `packages/nsgeo-core/tests/test_grid.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `Grid` dataclass: `id: str`, `origin: Tuple[float, float]`, `azimuth: float`, `size_x: float`, `size_y: float`, `crs: str`, `default_spacing: float`
  - `Grid.axes() -> Tuple[np.ndarray, np.ndarray]` returning unit `(x_hat, y_hat)` in world coordinates
  - `Grid.to_world(local: np.ndarray) -> np.ndarray` for `(n, 2)` local → `(n, 2)` world

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_grid.py`:

```python
from __future__ import annotations

import numpy as np
import pytest

from nsgeo.geometry.grid import Grid


def g(azimuth=0.0, origin=(0.0, 0.0)):
    return Grid(id="G", origin=origin, azimuth=azimuth, size_x=20.0,
                size_y=20.0, crs="EPSG:32616", default_spacing=0.5)


def test_zero_azimuth_aligns_local_axes_with_world():
    """azimuth is degrees clockwise from CRS north to grid-local +Y."""
    x_hat, y_hat = g(0.0).axes()
    np.testing.assert_allclose(y_hat, [0.0, 1.0], atol=1e-12)
    np.testing.assert_allclose(x_hat, [1.0, 0.0], atol=1e-12)


def test_ninety_degree_azimuth_points_local_y_east():
    x_hat, y_hat = g(90.0).axes()
    np.testing.assert_allclose(y_hat, [1.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(x_hat, [0.0, -1.0], atol=1e-12)


def test_axes_stay_orthonormal_and_right_handed():
    for az in (0.0, 17.5, 90.0, 213.0, 359.9):
        x_hat, y_hat = g(az).axes()
        assert np.dot(x_hat, y_hat) == pytest.approx(0.0, abs=1e-12)
        assert np.linalg.norm(x_hat) == pytest.approx(1.0)
        assert np.linalg.norm(y_hat) == pytest.approx(1.0)
        cross = x_hat[0] * y_hat[1] - x_hat[1] * y_hat[0]
        assert cross == pytest.approx(1.0)


def test_to_world_translates_by_origin():
    grid = g(0.0, origin=(100.0, 200.0))
    out = grid.to_world(np.array([[0.0, 0.0], [1.0, 2.0]]))
    np.testing.assert_allclose(out, [[100.0, 200.0], [101.0, 202.0]])


def test_to_world_rotates_then_translates():
    grid = g(90.0, origin=(10.0, 20.0))
    out = grid.to_world(np.array([[0.0, 5.0]]))   # 5 m along local +Y
    np.testing.assert_allclose(out, [[15.0, 20.0]], atol=1e-12)


def test_to_world_preserves_distances():
    grid = g(37.0, origin=(5.0, -3.0))
    local = np.array([[0.0, 0.0], [3.0, 4.0]])
    out = grid.to_world(local)
    assert np.linalg.norm(out[1] - out[0]) == pytest.approx(5.0)


def test_to_world_rejects_wrong_shape():
    with pytest.raises(ValueError, match=r"\(n, 2\)"):
        g().to_world(np.zeros((3, 3)))
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_grid.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo.geometry'`

- [ ] **Step 3: Implement the grid frame**

Create `packages/nsgeo-core/src/nsgeo/geometry/__init__.py`:

```python
"""Coordinate frames and trace placement."""
from __future__ import annotations
```

Create `packages/nsgeo-core/src/nsgeo/geometry/grid.py`:

```python
"""Grid as a coordinate frame.

A Grid is not a container of lines. It is an affine frame that converts
grid-local metres to world coordinates. Lines reference it by id, which is what
lets one grid hold cross-hatched lines running in both directions.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

import numpy as np


@dataclass(frozen=True)
class Grid:
    id: str
    origin: Tuple[float, float]
    azimuth: float
    size_x: float
    size_y: float
    crs: str
    default_spacing: float

    def axes(self) -> Tuple[np.ndarray, np.ndarray]:
        """Unit vectors of grid-local +X and +Y in world coordinates.

        azimuth is degrees clockwise from CRS north to grid-local +Y, so
        +Y = (sin a, cos a) and +X is that turned 90 degrees clockwise.
        """
        a = math.radians(self.azimuth)
        y_hat = np.array([math.sin(a), math.cos(a)])
        x_hat = np.array([math.cos(a), -math.sin(a)])
        return x_hat, y_hat

    def to_world(self, local: np.ndarray) -> np.ndarray:
        """Convert (n, 2) grid-local metres to (n, 2) world coordinates."""
        local = np.asarray(local, dtype=float)
        if local.ndim != 2 or local.shape[1] != 2:
            raise ValueError(f"expected (n, 2) local coordinates, got {local.shape}")
        x_hat, y_hat = self.axes()
        return np.asarray(self.origin, dtype=float) + local[:, :1] * x_hat + local[:, 1:] * y_hat
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_grid.py -v`
Expected: all 7 PASS

- [ ] **Step 5: Commit**

```bash
git add packages/nsgeo-core
git commit -m "feat: add Grid coordinate frame with world transform

Grid lives in geometry rather than model because it is a frame, not a
container. Keeps the dependency graph acyclic: io -> geometry -> model."
```

---

### Task 5: Placement protocol and GridPlacement

The join between geometry and data. Everything downstream uses only `trace_coords()` and `distance_along()` and never learns which placement it received.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/geometry/placement.py`
- Create: `packages/nsgeo-core/tests/test_placement.py`

**Interfaces:**
- Consumes: `Grid` (Task 4), `DztHeader` (Task 2)
- Produces:
  - `Placement` Protocol with `distance_along(n_traces, header) -> np.ndarray` and `trace_coords(n_traces, header, frames: Mapping[str, Grid]) -> np.ndarray`
  - `GridPlacement` dataclass: `grid_id: str`, `axis: str` (`"x"` or `"y"`), `offset: float`, `start_along: float = 0.0`, `direction: int = 1`, `label: Optional[str] = None`

**Note on the signature:** the spec writes `trace_coords(n_traces, header)`. Implementation adds a `frames` mapping so a placement can resolve its grid by id without holding a reference, which keeps serialisation acyclic. `TrackPlacement` (v1.1) will ignore `frames`.

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_placement.py`:

```python
from __future__ import annotations

import numpy as np
import pytest

from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.io.dzt import read_header
from tests.synthetic import write_dzt


@pytest.fixture
def header(tmp_path):
    p = tmp_path / "h.DZT"
    write_dzt(p, np.zeros((512, 10), dtype=np.int32), traces_per_metre=60.0)
    return read_header(p)


@pytest.fixture
def frames():
    return {"G": Grid(id="G", origin=(0.0, 0.0), azimuth=0.0, size_x=20.0,
                      size_y=20.0, crs="EPSG:32616", default_spacing=0.5)}


def test_distance_along_forward(header):
    pl = GridPlacement(grid_id="G", axis="y", offset=0.5)
    d = pl.distance_along(120, header)
    assert d[0] == pytest.approx(0.0)
    assert d[60] == pytest.approx(1.0)       # 60 traces/m
    assert d[119] == pytest.approx(119 / 60)


def test_distance_along_reversed_decreases(header):
    """Zigzag: traces stay in raw file order, the coordinate decreases."""
    pl = GridPlacement(grid_id="G", axis="y", offset=0.5,
                       start_along=20.0, direction=-1)
    d = pl.distance_along(120, header)
    assert d[0] == pytest.approx(20.0)
    assert d[60] == pytest.approx(19.0)
    assert np.all(np.diff(d) < 0)


def test_start_along_offsets_a_line_beginning_inside_the_grid(header):
    pl = GridPlacement(grid_id="G", axis="y", offset=0.5, start_along=3.5)
    d = pl.distance_along(60, header)
    assert d[0] == pytest.approx(3.5)
    assert d[-1] == pytest.approx(3.5 + 59 / 60)


def test_axis_y_line_varies_in_world_y(header, frames):
    pl = GridPlacement(grid_id="G", axis="y", offset=2.0)
    xy = pl.trace_coords(60, header, frames)
    assert xy.shape == (60, 2)
    np.testing.assert_allclose(xy[:, 0], 2.0)            # constant cross-axis
    assert xy[-1, 1] == pytest.approx(59 / 60)


def test_axis_x_line_varies_in_world_x(header, frames):
    """Cross-hatched grids: the same grid holds lines along both axes."""
    pl = GridPlacement(grid_id="G", axis="x", offset=2.0)
    xy = pl.trace_coords(60, header, frames)
    np.testing.assert_allclose(xy[:, 1], 2.0)
    assert xy[-1, 0] == pytest.approx(59 / 60)


def test_cross_hatched_lines_share_one_grid(header, frames):
    along_y = GridPlacement(grid_id="G", axis="y", offset=1.0)
    along_x = GridPlacement(grid_id="G", axis="x", offset=1.0)
    a = along_y.trace_coords(60, header, frames)
    b = along_x.trace_coords(60, header, frames)
    assert not np.allclose(a, b)
    # they cross near local (1, 1)
    assert np.min(np.linalg.norm(a[:, None, :] - b[None, :, :], axis=-1)) < 0.05


def test_rotated_grid_places_traces_correctly(header):
    frames = {"G": Grid(id="G", origin=(100.0, 200.0), azimuth=90.0, size_x=20.0,
                        size_y=20.0, crs="EPSG:32616", default_spacing=0.5)}
    pl = GridPlacement(grid_id="G", axis="y", offset=0.0)
    xy = pl.trace_coords(61, header, frames)
    np.testing.assert_allclose(xy[0], [100.0, 200.0], atol=1e-9)
    np.testing.assert_allclose(xy[60], [101.0, 200.0], atol=1e-9)   # +Y is east


def test_unknown_grid_id_raises(header):
    pl = GridPlacement(grid_id="MISSING", axis="y", offset=0.0)
    with pytest.raises(KeyError, match="MISSING"):
        pl.trace_coords(10, header, {})


def test_rejects_bad_axis():
    with pytest.raises(ValueError, match="axis"):
        GridPlacement(grid_id="G", axis="z", offset=0.0)


def test_rejects_bad_direction():
    with pytest.raises(ValueError, match="direction"):
        GridPlacement(grid_id="G", axis="y", offset=0.0, direction=0)


def test_rejects_zero_traces_per_metre(tmp_path):
    """Time-triggered acquisition has no meaningful trace spacing; a grid
    placement cannot position such a line."""
    p = tmp_path / "t.DZT"
    write_dzt(p, np.zeros((512, 10), dtype=np.int32), traces_per_metre=0.0)
    hdr = read_header(p)
    pl = GridPlacement(grid_id="G", axis="y", offset=0.0)
    with pytest.raises(ValueError, match="traces_per_metre"):
        pl.distance_along(10, hdr)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_placement.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo.geometry.placement'`

- [ ] **Step 3: Implement placements**

Create `packages/nsgeo-core/src/nsgeo/geometry/placement.py`:

```python
"""Trace placement: how a line's trace index maps to real-world position.

Trace index is the join between geometry and data. `Profile.data[:, i]` and
`placement.trace_coords(...)[i]` describe the same trace, which is what makes
bidirectional map-to-profile navigation work.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Protocol

import numpy as np

from nsgeo.geometry.grid import Grid
from nsgeo.io.dzt import DztHeader

class Placement(Protocol):
    """How traces are positioned. Consumers use only these two methods and
    never learn which implementation they received."""

    def distance_along(self, n_traces: int, header: DztHeader) -> np.ndarray:
        """(n_traces,) metres along the line."""
        ...

    def trace_coords(
        self, n_traces: int, header: DztHeader, frames: Mapping[str, Grid]
    ) -> np.ndarray:
        """(n_traces, 2) world coordinates."""
        ...


@dataclass(frozen=True)
class GridPlacement:
    """A line positioned parametrically within a grid frame.

    `offset` is the position in metres along the axis the line does NOT run
    along, and is the geometric truth. `label` carries the human field name
    ("line 12") and is never used for geometry.
    """

    grid_id: str
    axis: str
    offset: float
    start_along: float = 0.0
    direction: int = 1
    label: Optional[str] = None

    def __post_init__(self) -> None:
        if self.axis not in ("x", "y"):
            raise ValueError(f"axis must be 'x' or 'y', got {self.axis!r}")
        if self.direction not in (1, -1):
            raise ValueError(f"direction must be +1 or -1, got {self.direction!r}")

    def distance_along(self, n_traces: int, header: DztHeader) -> np.ndarray:
        spm = header.traces_per_metre
        if not spm > 0:
            raise ValueError(
                "traces_per_metre is not positive; this line was probably recorded "
                "with time triggering and cannot be positioned by a grid placement"
            )
        return self.start_along + self.direction * (np.arange(n_traces, dtype=float) / spm)

    def trace_coords(
        self, n_traces: int, header: DztHeader, frames: Mapping[str, Grid]
    ) -> np.ndarray:
        if self.grid_id not in frames:
            raise KeyError(f"no grid frame named {self.grid_id!r}")
        along = self.distance_along(n_traces, header)
        cross = np.full(n_traces, self.offset, dtype=float)
        if self.axis == "y":
            local = np.column_stack([cross, along])
        else:
            local = np.column_stack([along, cross])
        return frames[self.grid_id].to_world(local)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_placement.py -v`
Expected: all 11 PASS

- [ ] **Step 5: Commit**

```bash
git add packages/nsgeo-core
git commit -m "feat: add Placement protocol and GridPlacement

Line position is stored in metres on the placement rather than as an index
times a spacing on the grid, so one grid holds cross-hatched lines running in
both directions, and infill lines are just another offset."
```

---

### Task 6: Fitting a grid from surveyed corners

All three georeferencing methods in the spec (GNSS corners, on-map digitising, existing polygons) reduce to the same four numbers. This task implements the fit, and reports a residual as a QC measure of how square the grid actually was.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/geometry/fit.py`
- Create: `packages/nsgeo-core/tests/test_fit.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `GridFit` dataclass: `origin: Tuple[float, float]`, `azimuth: float`, `residual_rms: float`
  - `fit_grid_from_corners(local: np.ndarray, world: np.ndarray) -> GridFit`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_fit.py`:

```python
from __future__ import annotations

import math

import numpy as np
import pytest

from nsgeo.geometry.fit import fit_grid_from_corners
from nsgeo.geometry.grid import Grid

LOCAL = np.array([[0.0, 0.0], [20.0, 0.0], [20.0, 20.0], [0.0, 20.0]])


def _rotate(pts, deg, origin):
    a = math.radians(deg)
    y_hat = np.array([math.sin(a), math.cos(a)])
    x_hat = np.array([math.cos(a), -math.sin(a)])
    return np.asarray(origin) + pts[:, :1] * x_hat + pts[:, 1:] * y_hat


def test_recovers_origin_and_azimuth_exactly():
    world = _rotate(LOCAL, 30.0, (500.0, 700.0))
    fit = fit_grid_from_corners(LOCAL, world)
    assert fit.origin[0] == pytest.approx(500.0, abs=1e-6)
    assert fit.origin[1] == pytest.approx(700.0, abs=1e-6)
    assert fit.azimuth == pytest.approx(30.0, abs=1e-6)
    assert fit.residual_rms == pytest.approx(0.0, abs=1e-9)


def test_round_trips_through_grid_to_world():
    world = _rotate(LOCAL, 213.0, (10.0, -5.0))
    fit = fit_grid_from_corners(LOCAL, world)
    grid = Grid(id="G", origin=fit.origin, azimuth=fit.azimuth, size_x=20.0,
                size_y=20.0, crs="EPSG:32616", default_spacing=0.5)
    np.testing.assert_allclose(grid.to_world(LOCAL), world, atol=1e-6)


def test_two_points_are_enough():
    world = _rotate(LOCAL[:2], 45.0, (0.0, 0.0))
    fit = fit_grid_from_corners(LOCAL[:2], world)
    assert fit.azimuth == pytest.approx(45.0, abs=1e-6)


def test_azimuth_is_normalised_to_0_360():
    world = _rotate(LOCAL, -45.0, (0.0, 0.0))
    fit = fit_grid_from_corners(LOCAL, world)
    assert 0.0 <= fit.azimuth < 360.0
    assert fit.azimuth == pytest.approx(315.0, abs=1e-6)


def test_non_square_grid_reports_nonzero_residual():
    """The QC number: a grid stretched on one axis cannot be fitted rigidly."""
    stretched = LOCAL.copy()
    stretched[:, 0] *= 1.10          # 10% long on one axis
    world = _rotate(stretched, 12.0, (0.0, 0.0))
    fit = fit_grid_from_corners(LOCAL, world)
    assert fit.residual_rms > 0.3


def test_noise_produces_small_residual():
    rng = np.random.default_rng(7)
    world = _rotate(LOCAL, 12.0, (0.0, 0.0)) + rng.normal(0, 0.02, LOCAL.shape)
    fit = fit_grid_from_corners(LOCAL, world)
    assert fit.residual_rms < 0.1


def test_rejects_reflection():
    """A mirrored layout is a data-entry error, not a rotation. The fit must
    not silently absorb it by flipping the frame."""
    world = _rotate(LOCAL, 0.0, (0.0, 0.0))
    world[:, 0] *= -1
    fit = fit_grid_from_corners(LOCAL, world)
    assert fit.residual_rms > 1.0


def test_requires_at_least_two_points():
    with pytest.raises(ValueError, match="at least two"):
        fit_grid_from_corners(LOCAL[:1], LOCAL[:1])


def test_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="same length"):
        fit_grid_from_corners(LOCAL, LOCAL[:3])
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_fit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo.geometry.fit'`

- [ ] **Step 3: Implement the rigid fit**

Create `packages/nsgeo-core/src/nsgeo/geometry/fit.py`:

```python
"""Fit a grid frame to surveyed control points.

GNSS corners, on-map digitising, and existing polygons are three UI paths that
all produce the same four numbers. This is the shared implementation.

The fit is rigid: rotation and translation only, no scale and no reflection.
That is deliberate. A grid that was not actually square shows up as a nonzero
residual, which is a QC number worth reporting, rather than being silently
absorbed into a scale factor.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

import numpy as np


@dataclass(frozen=True)
class GridFit:
    origin: Tuple[float, float]
    azimuth: float
    residual_rms: float


def fit_grid_from_corners(local: np.ndarray, world: np.ndarray) -> GridFit:
    """Least-squares rigid fit of grid-local metres to world coordinates."""
    local = np.asarray(local, dtype=float)
    world = np.asarray(world, dtype=float)
    if local.shape != world.shape:
        raise ValueError(f"local and world must be the same length: {local.shape} vs {world.shape}")
    if local.ndim != 2 or local.shape[1] != 2:
        raise ValueError(f"expected (n, 2) coordinates, got {local.shape}")
    if len(local) < 2:
        raise ValueError("need at least two control points to fit a grid")

    lc = local.mean(axis=0)
    wc = world.mean(axis=0)
    cov = (local - lc).T @ (world - wc)
    u, _, vt = np.linalg.svd(cov)

    # Forbid reflection: a mirrored layout is a data-entry error, not a rotation.
    d = np.sign(np.linalg.det(vt.T @ u.T))
    rot = vt.T @ np.diag([1.0, d]) @ u.T

    origin = wc - rot @ lc
    predicted = (rot @ local.T).T + origin
    residual = float(np.sqrt(np.mean(np.sum((world - predicted) ** 2, axis=1))))

    # rot maps local to world, so rot @ (0, 1) is the world direction of
    # grid-local +Y, which is (sin azimuth, cos azimuth).
    azimuth = math.degrees(math.atan2(rot[0, 1], rot[1, 1])) % 360.0

    return GridFit(origin=(float(origin[0]), float(origin[1])),
                   azimuth=azimuth, residual_rms=residual)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_fit.py -v`
Expected: all 9 PASS

- [ ] **Step 5: Commit**

```bash
git add packages/nsgeo-core
git commit -m "feat: fit grid origin and azimuth from surveyed corners

Rigid fit only, no scale and no reflection, so a non-square grid surfaces as
a nonzero residual rather than being silently absorbed."
```

---

### Task 7: Profile, Line, and Site

The data model. Headers are read eagerly because they are cheap; sample arrays load on demand through a bounded cache.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/model/__init__.py`
- Create: `packages/nsgeo-core/src/nsgeo/model/survey.py`
- Create: `packages/nsgeo-core/tests/test_survey.py`

**Interfaces:**
- Consumes: `DztHeader`, `read_header`, `read_samples`, `trace_count` (Tasks 2–3); `Grid` (Task 4); `Placement`, `GridPlacement` (Task 5)
- Produces:
  - `Profile` dataclass: `data: np.ndarray`, `header: DztHeader`, with `n_samples` and `n_traces` properties
  - `Line` dataclass: `path: Path`, `header: DztHeader`, `placement: Placement`, `n_traces: int`; `Line.open(path, placement) -> Line`; `Line.load() -> List[Profile]`; `Line.distance_along() -> np.ndarray`; `Line.trace_coords(frames) -> np.ndarray`
  - `Site` dataclass: `grids: List[Grid]`, `lines: List[Line]`, with `frames` property and `validate()`
  - `clear_profile_cache() -> None`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_survey.py`:

```python
from __future__ import annotations

import numpy as np
import pytest

from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line, Site, clear_profile_cache
from tests.synthetic import write_dzt


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_profile_cache()
    yield
    clear_profile_cache()


@pytest.fixture
def grid():
    return Grid(id="G", origin=(0.0, 0.0), azimuth=0.0, size_x=20.0,
                size_y=20.0, crs="EPSG:32616", default_spacing=0.5)


def _line(tmp_path, name="a.DZT", n_traces=120, n_channels=1, offset=0.5):
    p = tmp_path / name
    if n_channels == 1:
        data = np.zeros((512, n_traces), dtype=np.int32)
    else:
        data = np.zeros((n_channels, 512, n_traces), dtype=np.int32)
    write_dzt(p, data, n_channels=n_channels)
    return Line.open(p, GridPlacement(grid_id="G", axis="y", offset=offset))


def test_open_reads_header_and_trace_count_without_samples(tmp_path):
    line = _line(tmp_path, n_traces=137)
    assert line.n_traces == 137
    assert line.header.n_samples == 512


def test_load_returns_one_profile_per_channel(tmp_path):
    line = _line(tmp_path, n_channels=3)
    profiles = line.load()
    assert len(profiles) == 3
    assert all(p.n_traces == 120 for p in profiles)
    assert all(p.n_samples == 512 for p in profiles)


def test_all_channels_share_a_trace_count(tmp_path):
    """The invariant that makes trace index a valid join."""
    line = _line(tmp_path, n_channels=2)
    counts = {p.n_traces for p in line.load()}
    assert len(counts) == 1


def test_load_is_cached(tmp_path):
    line = _line(tmp_path)
    assert line.load()[0].data is line.load()[0].data


def test_cache_is_bounded(tmp_path):
    from nsgeo.model.survey import _load_profiles
    for i in range(_load_profiles.cache_parameters()["maxsize"] + 3):
        _line(tmp_path, name=f"f{i}.DZT", n_traces=8).load()
    info = _load_profiles.cache_info()
    assert info.currsize <= info.maxsize


def test_distance_along_uses_the_placement(tmp_path):
    line = _line(tmp_path, n_traces=120)
    d = line.distance_along()
    assert len(d) == 120
    assert d[60] == pytest.approx(1.0)


def test_trace_coords_join_data_by_index(tmp_path, grid):
    """Profile.data[:, i] and trace_coords()[i] are the same trace."""
    line = _line(tmp_path, n_traces=60, offset=2.0)
    xy = line.trace_coords({"G": grid})
    profile = line.load()[0]
    assert xy.shape[0] == profile.data.shape[1] == line.n_traces


def test_profile_data_is_read_only(tmp_path):
    """Raw data is never mutated."""
    line = _line(tmp_path)
    with pytest.raises(ValueError):
        line.load()[0].data[0, 0] = 1


def test_site_frames_maps_id_to_grid(grid):
    site = Site(grids=[grid], lines=[])
    assert site.frames["G"] is grid


def test_site_validate_rejects_dangling_grid_id(tmp_path, grid):
    line = Line.open(
        _line(tmp_path).path,
        GridPlacement(grid_id="NOPE", axis="y", offset=0.0),
    )
    site = Site(grids=[grid], lines=[line])
    with pytest.raises(ValueError, match="NOPE"):
        site.validate()


def test_site_validate_rejects_duplicate_grid_ids(grid):
    site = Site(grids=[grid, grid], lines=[])
    with pytest.raises(ValueError, match="duplicate"):
        site.validate()


def test_site_accepts_cross_hatched_lines_in_one_grid(tmp_path, grid):
    a = _line(tmp_path, name="y.DZT")
    b = Line.open(_line(tmp_path, name="x.DZT").path,
                  GridPlacement(grid_id="G", axis="x", offset=0.5))
    site = Site(grids=[grid], lines=[a, b])
    site.validate()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_survey.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo.model'`

- [ ] **Step 3: Implement the model**

Create `packages/nsgeo-core/src/nsgeo/model/__init__.py`:

```python
"""Survey data model."""
from __future__ import annotations
```

Create `packages/nsgeo-core/src/nsgeo/model/survey.py`:

```python
"""Profile, Line, and Site.

Ownership runs one way: a Line owns its Profiles, and a Profile holds no
back-reference. That keeps Profile a pure, picklable, trivially testable data
object with no cycles.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Mapping, Tuple

import numpy as np

from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import Placement
from nsgeo.io.dzt import DztHeader, read_header, read_samples, trace_count

#: How many lines' sample arrays stay resident. A 30x30 m grid at 0.5 m
#: spacing is about 100 MB in total, so a bound of 16 lines is generous
#: while still preventing unbounded growth over a long session.
_CACHE_SIZE = 16


@dataclass(frozen=True)
class Profile:
    """One channel of one radargram. `data` is raw and never mutated."""

    data: np.ndarray
    header: DztHeader

    @property
    def n_samples(self) -> int:
        return int(self.data.shape[0])

    @property
    def n_traces(self) -> int:
        return int(self.data.shape[1])


@lru_cache(maxsize=_CACHE_SIZE)
def _load_profiles(path_str: str, size: int, mtime_ns: int) -> Tuple[Profile, ...]:
    """Cached sample load. `size` and `mtime_ns` are part of the key so an
    edited file is not served from a stale entry."""
    path = Path(path_str)
    header = read_header(path)
    stack = read_samples(path, header)
    profiles = []
    for channel in stack:
        channel.setflags(write=False)
        profiles.append(Profile(data=channel, header=header))
    return tuple(profiles)


def clear_profile_cache() -> None:
    _load_profiles.cache_clear()


@dataclass(frozen=True)
class Line:
    """One collected survey line. Headers are eager, samples are lazy."""

    path: Path
    header: DztHeader
    placement: Placement
    n_traces: int

    @classmethod
    def open(cls, path: Path, placement: Placement) -> "Line":
        """Read the header and derive the trace count. Reads 1024 bytes plus
        a stat, regardless of file size."""
        path = Path(path)
        header = read_header(path)
        return cls(path=path, header=header, placement=placement,
                   n_traces=trace_count(path, header))

    def load(self) -> List[Profile]:
        """Sample arrays, one Profile per channel. Cached."""
        stat = self.path.stat()
        return list(_load_profiles(str(self.path), stat.st_size, stat.st_mtime_ns))

    def distance_along(self) -> np.ndarray:
        return self.placement.distance_along(self.n_traces, self.header)

    def trace_coords(self, frames: Mapping[str, Grid]) -> np.ndarray:
        return self.placement.trace_coords(self.n_traces, self.header, frames)


@dataclass
class Site:
    grids: List[Grid] = field(default_factory=list)
    lines: List[Line] = field(default_factory=list)

    @property
    def frames(self) -> Dict[str, Grid]:
        return {g.id: g for g in self.grids}

    def validate(self) -> None:
        """Fail loudly on structural problems rather than at render time."""
        ids = [g.id for g in self.grids]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate grid ids: {sorted(dupes)}")
        known = set(ids)
        for line in self.lines:
            grid_id = getattr(line.placement, "grid_id", None)
            if grid_id is not None and grid_id not in known:
                raise ValueError(f"line {line.path.name} references unknown grid {grid_id!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/nsgeo-core && python -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add packages/nsgeo-core
git commit -m "feat: add Profile, Line, and Site with lazy sample loading

Headers are eager because they cost 1024 bytes; sample arrays load on demand
through a bounded LRU keyed on path, size, and mtime. Profile arrays are set
read-only so raw data cannot be mutated in place."
```

---

### Task 8: Survey definition file

The source of truth: a human-readable, diffable JSON file with relative DZT paths, readable without QGIS.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/project.py`
- Create: `packages/nsgeo-core/tests/test_project.py`

**Interfaces:**
- Consumes: `Grid` (Task 4), `GridPlacement` (Task 5), `Line`, `Site` (Task 7)
- Produces:
  - `SCHEMA_VERSION: int = 1`
  - `save_site(site: Site, path) -> None`
  - `load_site(path) -> Site`
  - `ProjectError(Exception)`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_project.py`:

```python
from __future__ import annotations

import json

import numpy as np
import pytest

from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line, Site
from nsgeo.project import ProjectError, load_site, save_site
from tests.synthetic import write_dzt


@pytest.fixture
def site(tmp_path):
    grid = Grid(id="G1", origin=(500.0, 700.0), azimuth=30.0, size_x=20.0,
                size_y=20.0, crs="EPSG:32616", default_spacing=0.5)
    lines = []
    for i, axis in enumerate(["y", "y", "x"]):
        p = tmp_path / "data" / f"L{i}.DZT"
        p.parent.mkdir(exist_ok=True)
        write_dzt(p, np.zeros((512, 60), dtype=np.int32))
        lines.append(Line.open(p, GridPlacement(
            grid_id="G1", axis=axis, offset=i * 0.5,
            start_along=0.0, direction=-1 if i == 1 else 1, label=f"line {i}")))
    return Site(grids=[grid], lines=lines)


def test_round_trips(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    back = load_site(out)
    assert len(back.grids) == 1
    assert back.grids[0].azimuth == pytest.approx(30.0)
    assert len(back.lines) == 3
    assert [ln.placement.axis for ln in back.lines] == ["y", "y", "x"]
    assert back.lines[1].placement.direction == -1
    assert back.lines[2].placement.label == "line 2"


def test_paths_are_stored_relative_with_posix_separators(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    doc = json.loads(out.read_text())
    stored = [ln["path"] for ln in doc["lines"]]
    assert stored == ["data/L0.DZT", "data/L1.DZT", "data/L2.DZT"]
    assert not any(p.startswith("/") or "\\" in p for p in stored)


def test_moving_the_whole_project_still_loads(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    moved = tmp_path / "moved"
    moved.mkdir()
    (tmp_path / "data").rename(moved / "data")
    out.rename(moved / "survey.nsgeo.json")
    back = load_site(moved / "survey.nsgeo.json")
    assert len(back.lines) == 3


def test_writes_schema_version(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    assert json.loads(out.read_text())["schema_version"] == 1


def test_rejects_future_schema_version(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    doc = json.loads(out.read_text())
    doc["schema_version"] = 99
    out.write_text(json.dumps(doc))
    with pytest.raises(ProjectError, match="schema version 99"):
        load_site(out)


def test_rejects_unknown_placement_type(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    doc = json.loads(out.read_text())
    doc["lines"][0]["placement"]["type"] = "teleport"
    out.write_text(json.dumps(doc))
    with pytest.raises(ProjectError, match="teleport"):
        load_site(out)


def test_missing_dzt_file_names_the_path(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    (tmp_path / "data" / "L0.DZT").unlink()
    with pytest.raises(ProjectError, match="L0.DZT"):
        load_site(out)


def test_output_is_human_readable(tmp_path, site):
    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    text = out.read_text()
    assert "\n" in text and "  " in text      # indented, diffable
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_project.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo.project'`

- [ ] **Step 3: Implement persistence**

Create `packages/nsgeo-core/src/nsgeo/project.py`:

```python
"""The survey definition file: survey.nsgeo.json.

This is the source of truth. It is human-readable, diffable, git-friendly, and
loadable with no QGIS present. Front ends derive display layers from it; those
layers are regenerable and are explicitly not the source of truth.

DZT paths are stored relative to the JSON file with POSIX separators, so a
project directory can be moved or shared across platforms intact.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Union

from nsgeo.geometry.grid import Grid
from nsgeo.geometry.placement import GridPlacement
from nsgeo.model.survey import Line, Site

SCHEMA_VERSION = 1


class ProjectError(Exception):
    """Raised when a survey definition file is malformed or unreadable."""


def _grid_to_dict(grid: Grid) -> Dict[str, Any]:
    return {
        "id": grid.id,
        "origin": list(grid.origin),
        "azimuth": grid.azimuth,
        "size_x": grid.size_x,
        "size_y": grid.size_y,
        "crs": grid.crs,
        "default_spacing": grid.default_spacing,
    }


def _grid_from_dict(doc: Dict[str, Any]) -> Grid:
    return Grid(
        id=doc["id"],
        origin=(float(doc["origin"][0]), float(doc["origin"][1])),
        azimuth=float(doc["azimuth"]),
        size_x=float(doc["size_x"]),
        size_y=float(doc["size_y"]),
        crs=doc["crs"],
        default_spacing=float(doc["default_spacing"]),
    )


def _placement_to_dict(placement: Any) -> Dict[str, Any]:
    if isinstance(placement, GridPlacement):
        return {
            "type": "grid",
            "grid_id": placement.grid_id,
            "axis": placement.axis,
            "offset": placement.offset,
            "start_along": placement.start_along,
            "direction": placement.direction,
            "label": placement.label,
        }
    raise ProjectError(f"cannot serialise placement of type {type(placement).__name__}")


def _placement_from_dict(doc: Dict[str, Any]) -> GridPlacement:
    kind = doc.get("type")
    if kind != "grid":
        raise ProjectError(f"unknown placement type {kind!r}")
    return GridPlacement(
        grid_id=doc["grid_id"],
        axis=doc["axis"],
        offset=float(doc["offset"]),
        start_along=float(doc.get("start_along", 0.0)),
        direction=int(doc.get("direction", 1)),
        label=doc.get("label"),
    )


def save_site(site: Site, path: Union[str, Path]) -> None:
    path = Path(path)
    root = path.parent.resolve()
    doc = {
        "schema_version": SCHEMA_VERSION,
        "grids": [_grid_to_dict(g) for g in site.grids],
        "lines": [
            {
                "path": Path(line.path).resolve().relative_to(root).as_posix(),
                "placement": _placement_to_dict(line.placement),
            }
            for line in site.lines
        ],
    }
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def load_site(path: Union[str, Path]) -> Site:
    path = Path(path)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProjectError(f"{path} is not valid JSON: {exc}") from exc

    version = doc.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ProjectError(
            f"{path} declares schema version {version}, but this build reads "
            f"version {SCHEMA_VERSION}"
        )

    root = path.parent.resolve()
    grids = [_grid_from_dict(g) for g in doc.get("grids", [])]
    lines = []
    for entry in doc.get("lines", []):
        dzt = root / entry["path"]
        if not dzt.exists():
            raise ProjectError(f"referenced file does not exist: {dzt}")
        lines.append(Line.open(dzt, _placement_from_dict(entry["placement"])))

    site = Site(grids=grids, lines=lines)
    site.validate()
    return site
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_project.py -v`
Expected: all 8 PASS

- [ ] **Step 5: Commit**

```bash
git add packages/nsgeo-core
git commit -m "feat: read and write survey.nsgeo.json

Human-readable source of truth with relative POSIX paths, so a project
directory moves or shares across platforms intact."
```

---

### Task 9: Radargram, the Step protocol, and the registry

Establishes what flows through processing and how steps are discovered. Tested with a dummy step; the real steps arrive in Tasks 10–13.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/processing/__init__.py`
- Create: `packages/nsgeo-core/src/nsgeo/processing/base.py`
- Create: `packages/nsgeo-core/src/nsgeo/processing/_util.py`
- Create: `packages/nsgeo-core/tests/test_processing_base.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `Radargram` frozen dataclass: `data: np.ndarray`, `dt_ns: float`, `t0_ns: float`, with `n_samples`, `n_traces`, `times_ns()` and `replace(data=..., t0_ns=...)`
  - `Step` Protocol: `name: str`, `params: Dict[str, Any]`, `apply(rg: Radargram) -> Radargram`
  - `register(cls)` decorator, `get_step(name) -> type`, `available_steps() -> List[str]`, `build_step(name, **params) -> Step`
  - `Radargram.from_profile(profile) -> Radargram`
  - `running_mean(a, window, axis) -> np.ndarray` in `_util`

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_processing_base.py`:

```python
from __future__ import annotations

import numpy as np
import pytest

from nsgeo.processing._util import running_mean
from nsgeo.processing.base import (
    Radargram,
    available_steps,
    build_step,
    get_step,
    register,
)


def rg(n_samples=8, n_traces=4, dt_ns=0.2, t0_ns=0.0):
    data = np.arange(n_samples * n_traces, dtype=float).reshape(n_samples, n_traces)
    return Radargram(data=data, dt_ns=dt_ns, t0_ns=t0_ns)


@pytest.fixture
def clean_registry():
    """Registering a step is a global side effect. Restore the registry so a
    test double cannot leak into available_steps() for every later test."""
    from nsgeo.processing import base
    saved = dict(base._REGISTRY)
    yield
    base._REGISTRY.clear()
    base._REGISTRY.update(saved)


def test_times_ns_starts_at_t0_and_steps_by_dt():
    r = rg(n_samples=5, dt_ns=0.25, t0_ns=1.0)
    np.testing.assert_allclose(r.times_ns(), [1.0, 1.25, 1.5, 1.75, 2.0])


def test_replace_keeps_unspecified_fields():
    r = rg(t0_ns=3.0)
    out = r.replace(data=r.data * 2)
    assert out.t0_ns == 3.0
    assert out.dt_ns == r.dt_ns


def test_shapes():
    r = rg(n_samples=9, n_traces=7)
    assert (r.n_samples, r.n_traces) == (9, 7)


def test_rejects_non_2d_data():
    with pytest.raises(ValueError, match="2-D"):
        Radargram(data=np.zeros(5), dt_ns=0.2, t0_ns=0.0)


def test_rejects_non_positive_dt():
    with pytest.raises(ValueError, match="dt_ns"):
        Radargram(data=np.zeros((4, 4)), dt_ns=0.0, t0_ns=0.0)


def test_registry_round_trip(clean_registry):
    @register
    class _Doubler:
        name = "test_doubler"
        def __init__(self, factor: float = 2.0):
            self.factor = factor
        @property
        def params(self):
            return {"factor": self.factor}
        def apply(self, r: Radargram) -> Radargram:
            return r.replace(data=r.data * self.factor)

    assert "test_doubler" in available_steps()
    assert get_step("test_doubler") is _Doubler
    step = build_step("test_doubler", factor=3.0)
    out = step.apply(rg())
    assert out.data[1, 1] == pytest.approx(rg().data[1, 1] * 3.0)
    assert step.params == {"factor": 3.0}


def test_unknown_step_name_lists_alternatives():
    with pytest.raises(KeyError, match="available"):
        get_step("no_such_step")


def test_running_mean_of_constant_is_constant():
    a = np.full((10, 3), 5.0)
    np.testing.assert_allclose(running_mean(a, 5, axis=0), 5.0)


def test_running_mean_window_one_is_identity():
    a = np.arange(12.0).reshape(4, 3)
    np.testing.assert_allclose(running_mean(a, 1, axis=0), a)


def test_running_mean_shrinks_window_at_edges():
    a = np.array([[0.0], [1.0], [2.0], [3.0]])
    out = running_mean(a, 3, axis=0)
    assert out[0, 0] == pytest.approx(0.5)      # mean of [0, 1]
    assert out[1, 0] == pytest.approx(1.0)      # mean of [0, 1, 2]
    assert out[3, 0] == pytest.approx(2.5)      # mean of [2, 3]


def test_running_mean_along_trace_axis():
    a = np.tile(np.arange(6.0), (2, 1))
    out = running_mean(a, 3, axis=1)
    assert out.shape == a.shape
    assert out[0, 2] == pytest.approx(2.0)


def test_running_mean_rejects_zero_window():
    with pytest.raises(ValueError, match="window"):
        running_mean(np.zeros((4, 4)), 0, axis=0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_processing_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo.processing'`

- [ ] **Step 3: Implement the base**

Create `packages/nsgeo-core/src/nsgeo/processing/__init__.py`:

```python
"""User-ordered processing steps. Nothing here runs automatically."""
from __future__ import annotations
```

Create `packages/nsgeo-core/src/nsgeo/processing/_util.py`:

```python
"""Shared numpy helpers. numpy only: scipy is never imported at module level."""
from __future__ import annotations

import numpy as np


def running_mean(a: np.ndarray, window: int, axis: int = 0) -> np.ndarray:
    """Centred running mean with a shrinking window at the edges.

    Implemented with cumsum so it is O(n) rather than O(n * window), which is
    what makes dewow and sliding background removal fast enough to feel
    interactive without scipy.
    """
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")
    a = np.asarray(a, dtype=float)
    if window == 1:
        return a.copy()

    n = a.shape[axis]
    w = min(window, n)
    pad_shape = list(a.shape)
    pad_shape[axis] = 1
    cs = np.concatenate([np.zeros(pad_shape), np.cumsum(a, axis=axis)], axis=axis)

    idx = np.arange(n)
    half = w // 2
    lo = np.clip(idx - half, 0, n)
    hi = np.clip(idx - half + w, 0, n)
    counts = (hi - lo).astype(float)

    shape = [1] * a.ndim
    shape[axis] = n
    totals = np.take(cs, hi, axis=axis) - np.take(cs, lo, axis=axis)
    return totals / counts.reshape(shape)
```

Create `packages/nsgeo-core/src/nsgeo/processing/base.py`:

```python
"""What flows through processing, and how steps are discovered.

A step returns a whole Radargram rather than a bare array. Time-zero
correction crops rows, so a step that returned only an array would silently
desynchronise the time axis from the data. Returning the Radargram makes that
an obvious test failure instead of a silent bug.
"""
from __future__ import annotations

from dataclasses import dataclass, replace as _dc_replace
from typing import Any, Dict, List, Protocol, Type

import numpy as np

@dataclass(frozen=True)
class Radargram:
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

    def replace(self, **changes: Any) -> "Radargram":
        return _dc_replace(self, **changes)

    @classmethod
    def from_profile(cls, profile: Any) -> "Radargram":
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
    def params(self) -> Dict[str, Any]:
        ...

    def apply(self, rg: Radargram) -> Radargram:
        ...


_REGISTRY: Dict[str, Type[Any]] = {}


def register(cls: Type[Any]) -> Type[Any]:
    """Class decorator adding a step to the registry.

    Front ends enumerate the registry and build parameter widgets from each
    step's declared params, so new instruments contribute steps without any
    UI change.
    """
    _REGISTRY[cls.name] = cls
    return cls


def available_steps() -> List[str]:
    return sorted(_REGISTRY)


def get_step(name: str) -> Type[Any]:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown step {name!r}; available: {available_steps()}") from None


def build_step(name: str, **params: Any) -> Any:
    return get_step(name)(**params)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_processing_base.py -v`
Expected: all 12 PASS

- [ ] **Step 5: Commit**

```bash
git add packages/nsgeo-core
git commit -m "feat: add Radargram, Step protocol, and the step registry

Steps return a whole Radargram so the time axis cannot desynchronise from
the data when time-zero correction crops rows."
```

---

### Task 10: Time-zero and dewow

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/processing/timezero.py`
- Create: `packages/nsgeo-core/src/nsgeo/processing/dewow.py`
- Create: `packages/nsgeo-core/tests/test_steps_timezero_dewow.py`

**Interfaces:**
- Consumes: `Radargram`, `register`, `running_mean` (Task 9)
- Produces: steps registered as `"time_zero"` (`TimeZero(mode="first_break", sample=0, threshold=0.2)`) and `"dewow"` (`Dewow(window_ns=4.0)`)

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_steps_timezero_dewow.py`:

```python
from __future__ import annotations

import numpy as np
import pytest

from nsgeo.processing.base import Radargram, build_step
import nsgeo.processing.dewow  # noqa: F401  (registers the step)
import nsgeo.processing.timezero  # noqa: F401


def make(n_samples=100, n_traces=20, dt_ns=0.2, t0_ns=0.0, fill=0.0):
    return Radargram(data=np.full((n_samples, n_traces), fill, dtype=float),
                     dt_ns=dt_ns, t0_ns=t0_ns)


def test_time_zero_by_sample_crops_rows():
    rg = make(n_samples=100)
    out = build_step("time_zero", mode="sample", sample=17).apply(rg)
    assert out.n_samples == 83


def test_time_zero_updates_t0_consistently_with_dropped_rows():
    """The invariant that makes returning a whole Radargram worthwhile."""
    rg = make(n_samples=100, dt_ns=0.25, t0_ns=1.0)
    out = build_step("time_zero", mode="sample", sample=8).apply(rg)
    assert out.t0_ns == pytest.approx(1.0 + 8 * 0.25)
    assert out.times_ns()[0] == pytest.approx(3.0)


def test_time_zero_first_break_finds_the_onset():
    rg = make(n_samples=200)
    data = rg.data.copy()
    data[40:, :] = 100.0            # signal starts at row 40
    out = build_step("time_zero", mode="first_break", threshold=0.5).apply(
        rg.replace(data=data))
    assert out.n_samples == 160


def test_time_zero_first_break_ignores_leading_zero_traces():
    """Leading all-zero traces are normal and must not confuse the pick."""
    rg = make(n_samples=200, n_traces=20)
    data = rg.data.copy()
    data[40:, 4:] = 100.0
    data[:, :4] = 0.0
    out = build_step("time_zero", mode="first_break", threshold=0.5).apply(
        rg.replace(data=data))
    assert out.n_samples == 160


def test_time_zero_sample_zero_is_a_no_op():
    rg = make(n_samples=50, t0_ns=2.0)
    out = build_step("time_zero", mode="sample", sample=0).apply(rg)
    assert out.n_samples == 50
    assert out.t0_ns == pytest.approx(2.0)


def test_time_zero_rejects_cropping_everything():
    with pytest.raises(ValueError, match="would leave no samples"):
        build_step("time_zero", mode="sample", sample=100).apply(make(n_samples=100))


def test_time_zero_rejects_unknown_mode():
    with pytest.raises(ValueError, match="mode"):
        build_step("time_zero", mode="vibes").apply(make())


def test_time_zero_does_not_mutate_input():
    rg = make(n_samples=50, fill=3.0)
    before = rg.data.copy()
    build_step("time_zero", mode="sample", sample=5).apply(rg)
    np.testing.assert_array_equal(rg.data, before)


def test_dewow_removes_a_constant_offset():
    rg = make(n_samples=200, fill=7.0)
    out = build_step("dewow", window_ns=4.0).apply(rg)
    np.testing.assert_allclose(out.data, 0.0, atol=1e-9)


def test_dewow_preserves_high_frequency_content():
    n = 400
    t = np.arange(n)
    fast = np.sin(2 * np.pi * t / 4.0)[:, None] * np.ones((1, 5))
    slow = 10.0 * np.sin(2 * np.pi * t / 400.0)[:, None] * np.ones((1, 5))
    rg = Radargram(data=fast + slow, dt_ns=0.2, t0_ns=0.0)
    out = build_step("dewow", window_ns=8.0).apply(rg)
    mid = slice(50, 350)
    assert np.std(out.data[mid]) > 0.5 * np.std(fast[mid])
    assert np.abs(out.data[mid].mean()) < 0.5


def test_dewow_leaves_time_axis_untouched():
    rg = make(n_samples=100, dt_ns=0.2, t0_ns=1.5)
    out = build_step("dewow", window_ns=4.0).apply(rg)
    assert out.t0_ns == pytest.approx(1.5)
    assert out.n_samples == 100


def test_dewow_rejects_window_shorter_than_one_sample():
    with pytest.raises(ValueError, match="window_ns"):
        build_step("dewow", window_ns=0.0).apply(make(dt_ns=0.2))


def test_step_params_are_declared_for_the_ui():
    step = build_step("dewow", window_ns=6.0)
    assert step.params == {"window_ns": 6.0}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_steps_timezero_dewow.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo.processing.timezero'`

- [ ] **Step 3: Implement both steps**

Create `packages/nsgeo-core/src/nsgeo/processing/timezero.py`:

```python
"""Time-zero correction: crop rows above the first arrival."""
from __future__ import annotations

from typing import Any, Dict

import numpy as np

from nsgeo.processing.base import Radargram, register


@register
class TimeZero:
    name = "time_zero"

    def __init__(self, mode: str = "first_break", sample: int = 0,
                 threshold: float = 0.2) -> None:
        self.mode = mode
        self.sample = sample
        self.threshold = threshold

    @property
    def params(self) -> Dict[str, Any]:
        return {"mode": self.mode, "sample": self.sample, "threshold": self.threshold}

    def _pick(self, rg: Radargram) -> int:
        if self.mode == "sample":
            return int(self.sample)
        if self.mode == "first_break":
            # Mean absolute amplitude across traces. Averaging first means
            # leading all-zero traces (recording before the cart moves) dilute
            # rather than dominate the pick.
            envelope = np.abs(rg.data).mean(axis=1)
            peak = envelope.max()
            if peak <= 0:
                return 0
            above = np.flatnonzero(envelope >= self.threshold * peak)
            return int(above[0]) if above.size else 0
        raise ValueError(f"unknown time_zero mode {self.mode!r}; use 'sample' or 'first_break'")

    def apply(self, rg: Radargram) -> Radargram:
        k = self._pick(rg)
        if k <= 0:
            return rg
        if k >= rg.n_samples:
            raise ValueError(
                f"time_zero at sample {k} would leave no samples "
                f"(radargram has {rg.n_samples})"
            )
        return rg.replace(data=rg.data[k:, :].copy(), t0_ns=rg.t0_ns + k * rg.dt_ns)
```

Create `packages/nsgeo-core/src/nsgeo/processing/dewow.py`:

```python
"""Dewow: remove low-frequency drift by subtracting a running mean in time."""
from __future__ import annotations

from typing import Any, Dict

from nsgeo.processing._util import running_mean
from nsgeo.processing.base import Radargram, register


@register
class Dewow:
    name = "dewow"

    def __init__(self, window_ns: float = 4.0) -> None:
        self.window_ns = window_ns

    @property
    def params(self) -> Dict[str, Any]:
        return {"window_ns": self.window_ns}

    def apply(self, rg: Radargram) -> Radargram:
        window = int(round(self.window_ns / rg.dt_ns))
        if window < 1:
            raise ValueError(
                f"window_ns={self.window_ns} is shorter than one sample "
                f"({rg.dt_ns} ns); nothing to remove"
            )
        return rg.replace(data=rg.data - running_mean(rg.data, window, axis=0))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_steps_timezero_dewow.py -v`
Expected: all 13 PASS

- [ ] **Step 5: Commit**

```bash
git add packages/nsgeo-core
git commit -m "feat: add time_zero and dewow steps

time_zero updates t0_ns consistently with the rows it drops, and first-break
picking averages across traces so leading zero traces dilute rather than
dominate the pick."
```

---

### Task 11: Gain steps

Three separate steps rather than one with modes: they have different parameter schemas, and more than one may legitimately be used at once. `gain_curve` is the manual, real-time-draggable one.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/processing/gain.py`
- Create: `packages/nsgeo-core/tests/test_steps_gain.py`

**Interfaces:**
- Consumes: `Radargram`, `register`, `running_mean`
- Produces: `"gain_agc"` (`GainAgc(window_ns=20.0, target=1.0, eps=1e-12)`), `"gain_parametric"` (`GainParametric(mode="exponential", alpha=0.05, exponent=1.0)`), `"gain_curve"` (`GainCurve(points=[[t_ns, dB], ...])`)

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_steps_gain.py`:

```python
from __future__ import annotations

import numpy as np
import pytest

import nsgeo.processing.gain  # noqa: F401
from nsgeo.processing.base import Radargram, build_step


def decaying(n_samples=400, n_traces=10, dt_ns=0.25):
    t = np.arange(n_samples)[:, None]
    sig = np.sin(2 * np.pi * t / 8.0) * np.exp(-t / 80.0)
    return Radargram(data=np.tile(sig, (1, n_traces)), dt_ns=dt_ns, t0_ns=0.0)


def test_agc_equalises_amplitude_with_depth():
    rg = decaying()
    out = build_step("gain_agc", window_ns=20.0).apply(rg)
    early = np.abs(out.data[20:60]).mean()
    late = np.abs(out.data[300:340]).mean()
    assert late / early > 0.5      # was orders of magnitude smaller before


def test_agc_handles_all_zero_traces_without_dividing_by_zero():
    rg = Radargram(data=np.zeros((100, 5)), dt_ns=0.2, t0_ns=0.0)
    out = build_step("gain_agc", window_ns=10.0).apply(rg)
    assert np.isfinite(out.data).all()


def test_agc_leaves_the_time_axis_untouched():
    rg = decaying()
    out = build_step("gain_agc", window_ns=20.0).apply(rg)
    assert out.t0_ns == rg.t0_ns and out.n_samples == rg.n_samples


def test_exponential_gain_increases_with_time():
    rg = Radargram(data=np.ones((100, 3)), dt_ns=0.2, t0_ns=0.0)
    out = build_step("gain_parametric", mode="exponential", alpha=0.1).apply(rg)
    assert out.data[99, 0] > out.data[0, 0]


def test_power_gain_is_one_at_the_first_sample():
    rg = Radargram(data=np.ones((100, 3)), dt_ns=0.2, t0_ns=0.0)
    out = build_step("gain_parametric", mode="power", exponent=2.0).apply(rg)
    assert out.data[0, 0] == pytest.approx(1.0)
    assert out.data[99, 0] > 1.0


def test_parametric_rejects_unknown_mode():
    with pytest.raises(ValueError, match="mode"):
        build_step("gain_parametric", mode="wishful").apply(
            Radargram(data=np.ones((10, 2)), dt_ns=0.2, t0_ns=0.0))


def test_curve_applies_decibels_as_a_linear_multiplier():
    rg = Radargram(data=np.ones((100, 3)), dt_ns=0.2, t0_ns=0.0)
    out = build_step("gain_curve", points=[[0.0, 0.0], [19.8, 20.0]]).apply(rg)
    assert out.data[0, 0] == pytest.approx(1.0)          # 0 dB
    assert out.data[99, 0] == pytest.approx(10.0)        # 20 dB


def test_curve_interpolates_linearly_in_decibels():
    rg = Radargram(data=np.ones((3, 1)), dt_ns=10.0, t0_ns=0.0)
    out = build_step("gain_curve", points=[[0.0, 0.0], [20.0, 20.0]]).apply(rg)
    assert out.data[1, 0] == pytest.approx(10 ** (10.0 / 20.0))


def test_curve_holds_end_values_outside_the_control_range():
    rg = Radargram(data=np.ones((100, 1)), dt_ns=1.0, t0_ns=0.0)
    out = build_step("gain_curve", points=[[10.0, 6.0], [20.0, 6.0]]).apply(rg)
    assert out.data[0, 0] == pytest.approx(10 ** (6.0 / 20.0))
    assert out.data[99, 0] == pytest.approx(10 ** (6.0 / 20.0))


def test_curve_sorts_unordered_control_points():
    rg = Radargram(data=np.ones((3, 1)), dt_ns=10.0, t0_ns=0.0)
    a = build_step("gain_curve", points=[[20.0, 20.0], [0.0, 0.0]]).apply(rg)
    b = build_step("gain_curve", points=[[0.0, 0.0], [20.0, 20.0]]).apply(rg)
    np.testing.assert_allclose(a.data, b.data)


def test_curve_requires_at_least_two_points():
    with pytest.raises(ValueError, match="two"):
        build_step("gain_curve", points=[[0.0, 0.0]]).apply(
            Radargram(data=np.ones((10, 2)), dt_ns=0.2, t0_ns=0.0))


def test_curve_is_fast_enough_to_drag():
    """One broadcast multiply over a realistic radargram. The cached stack
    makes dragging recompute only this when gain is the last step."""
    import time
    rg = Radargram(data=np.ones((512, 3000)), dt_ns=0.2, t0_ns=0.0)
    step = build_step("gain_curve", points=[[0.0, 0.0], [100.0, 30.0]])
    start = time.perf_counter()
    step.apply(rg)
    assert time.perf_counter() - start < 0.1
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_steps_gain.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo.processing.gain'`

- [ ] **Step 3: Implement the gain steps**

Create `packages/nsgeo-core/src/nsgeo/processing/gain.py`:

```python
"""Gain steps.

Three separate steps rather than one with modes: they take different
parameters, and more than one may legitimately be applied at once.

Note the distinction from display gain, which lives in the front end: clip
percentile and colour range change how amplitude maps to colour, not the data,
and are never recorded in a stack.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence

import numpy as np

from nsgeo.processing._util import running_mean
from nsgeo.processing.base import Radargram, register


@register
class GainAgc:
    """Automatic gain control: normalise by a running RMS in time."""

    name = "gain_agc"

    def __init__(self, window_ns: float = 20.0, target: float = 1.0,
                 eps: float = 1e-12) -> None:
        self.window_ns = window_ns
        self.target = target
        self.eps = eps

    @property
    def params(self) -> Dict[str, Any]:
        return {"window_ns": self.window_ns, "target": self.target, "eps": self.eps}

    def apply(self, rg: Radargram) -> Radargram:
        window = int(round(self.window_ns / rg.dt_ns))
        if window < 1:
            raise ValueError(f"window_ns={self.window_ns} is shorter than one sample")
        rms = np.sqrt(running_mean(rg.data ** 2, window, axis=0))
        # eps guards all-zero traces, which are normal at the start of a line.
        return rg.replace(data=rg.data * (self.target / np.maximum(rms, self.eps)))


@register
class GainParametric:
    """Exponential or power-law gain as a function of two-way time."""

    name = "gain_parametric"

    def __init__(self, mode: str = "exponential", alpha: float = 0.05,
                 exponent: float = 1.0) -> None:
        self.mode = mode
        self.alpha = alpha
        self.exponent = exponent

    @property
    def params(self) -> Dict[str, Any]:
        return {"mode": self.mode, "alpha": self.alpha, "exponent": self.exponent}

    def apply(self, rg: Radargram) -> Radargram:
        # Elapsed time from the first sample, so gain is 1.0 at the top
        # regardless of what t0 happens to be.
        elapsed = np.arange(rg.n_samples, dtype=float) * rg.dt_ns
        if self.mode == "exponential":
            g = np.exp(self.alpha * elapsed)
        elif self.mode == "power":
            g = (1.0 + elapsed) ** self.exponent
        else:
            raise ValueError(
                f"unknown gain_parametric mode {self.mode!r}; use 'exponential' or 'power'"
            )
        return rg.replace(data=rg.data * g[:, None])


@register
class GainCurve:
    """Manual gain curve: draggable (time_ns, dB) control points.

    Applied as 10 ** (dB / 20). One broadcast multiply, so dragging a control
    point is interactive at full resolution when this is the last step.
    """

    name = "gain_curve"

    def __init__(self, points: Sequence[Sequence[float]]) -> None:
        self.points: List[List[float]] = [[float(t), float(db)] for t, db in points]

    @property
    def params(self) -> Dict[str, Any]:
        return {"points": [list(p) for p in self.points]}

    def apply(self, rg: Radargram) -> Radargram:
        if len(self.points) < 2:
            raise ValueError("gain_curve needs at least two control points")
        pts = sorted(self.points, key=lambda p: p[0])
        times = np.array([p[0] for p in pts], dtype=float)
        decibels = np.array([p[1] for p in pts], dtype=float)
        # np.interp holds the end values outside the control range, which is
        # the behaviour a user dragging a curve expects.
        db = np.interp(rg.times_ns(), times, decibels)
        return rg.replace(data=rg.data * (10.0 ** (db / 20.0))[:, None])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_steps_gain.py -v`
Expected: all 12 PASS

- [ ] **Step 5: Commit**

```bash
git add packages/nsgeo-core
git commit -m "feat: add AGC, parametric, and manual curve gain steps

gain_curve is one broadcast multiply, which is what makes dragging a control
point interactive at full resolution."
```

---

### Task 12: Bandpass filter

The one step where the numpy-only constraint requires real care. A brick-wall FFT filter causes ringing that can be mistaken for stratigraphy, so the passband edges are cosine-tapered.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/processing/bandpass.py`
- Create: `packages/nsgeo-core/tests/test_steps_bandpass.py`

**Interfaces:**
- Consumes: `Radargram`, `register`
- Produces: `"bandpass"` (`Bandpass(low_mhz, high_mhz, taper_frac=0.25)`)

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_steps_bandpass.py`:

```python
from __future__ import annotations

import numpy as np
import pytest

import nsgeo.processing.bandpass  # noqa: F401
from nsgeo.processing.base import Radargram, build_step

DT_NS = 0.2                      # 5 GHz sampling -> 2500 MHz Nyquist


def tone(freq_mhz, n_samples=1024, n_traces=4, dt_ns=DT_NS):
    t_ns = np.arange(n_samples) * dt_ns
    sig = np.sin(2 * np.pi * freq_mhz * 1e6 * t_ns * 1e-9)
    return Radargram(data=np.tile(sig[:, None], (1, n_traces)), dt_ns=dt_ns, t0_ns=0.0)


def amplitude(rg):
    mid = slice(rg.n_samples // 4, 3 * rg.n_samples // 4)
    return float(np.abs(rg.data[mid]).max())


def test_passes_an_in_band_tone():
    rg = tone(350.0)
    out = build_step("bandpass", low_mhz=150.0, high_mhz=600.0).apply(rg)
    assert amplitude(out) > 0.8 * amplitude(rg)


def test_attenuates_a_tone_below_the_band():
    rg = tone(30.0)
    out = build_step("bandpass", low_mhz=150.0, high_mhz=600.0).apply(rg)
    assert amplitude(out) < 0.1 * amplitude(rg)


def test_attenuates_a_tone_above_the_band():
    rg = tone(1500.0)
    out = build_step("bandpass", low_mhz=150.0, high_mhz=600.0).apply(rg)
    assert amplitude(out) < 0.1 * amplitude(rg)


def test_tapering_reduces_ringing_versus_a_brick_wall():
    """The reason the taper exists: brick-wall ringing looks like stratigraphy."""
    data = np.zeros((1024, 1))
    data[512, 0] = 1.0                    # impulse
    rg = Radargram(data=data, dt_ns=DT_NS, t0_ns=0.0)
    brick = build_step("bandpass", low_mhz=150.0, high_mhz=600.0,
                       taper_frac=0.0).apply(rg)
    tapered = build_step("bandpass", low_mhz=150.0, high_mhz=600.0,
                         taper_frac=0.5).apply(rg)
    far = np.r_[0:400, 624:1024]          # away from the main lobe
    assert np.abs(tapered.data[far, 0]).sum() < np.abs(brick.data[far, 0]).sum()


def test_preserves_shape_and_time_axis():
    rg = tone(350.0, n_samples=512, n_traces=7)
    out = build_step("bandpass", low_mhz=150.0, high_mhz=600.0).apply(rg)
    assert out.data.shape == rg.data.shape
    assert out.dt_ns == rg.dt_ns and out.t0_ns == rg.t0_ns


def test_rejects_low_above_high():
    with pytest.raises(ValueError, match="low_mhz"):
        build_step("bandpass", low_mhz=600.0, high_mhz=150.0).apply(tone(300.0))


def test_rejects_high_above_nyquist():
    """Nyquist here is 2500 MHz; asking for more is a user error worth naming."""
    with pytest.raises(ValueError, match="Nyquist"):
        build_step("bandpass", low_mhz=150.0, high_mhz=9000.0).apply(tone(300.0))


def test_rejects_negative_low():
    with pytest.raises(ValueError, match="low_mhz"):
        build_step("bandpass", low_mhz=-5.0, high_mhz=600.0).apply(tone(300.0))


def test_output_is_real_valued():
    out = build_step("bandpass", low_mhz=150.0, high_mhz=600.0).apply(tone(350.0))
    assert np.isrealobj(out.data)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_steps_bandpass.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo.processing.bandpass'`

- [ ] **Step 3: Implement the bandpass**

Create `packages/nsgeo-core/src/nsgeo/processing/bandpass.py`:

```python
"""FFT bandpass with cosine-tapered passband edges.

scipy.signal.butter plus filtfilt is the textbook route. An FFT bandpass is
equally valid *provided* the passband edges are tapered: a brick-wall filter
rings, and that ringing can be mistaken for real stratigraphy. The taper is
the whole reason this implementation is acceptable without scipy.
"""
from __future__ import annotations

from typing import Any, Dict

import numpy as np

from nsgeo.processing.base import Radargram, register


@register
class Bandpass:
    name = "bandpass"

    def __init__(self, low_mhz: float, high_mhz: float, taper_frac: float = 0.25) -> None:
        self.low_mhz = low_mhz
        self.high_mhz = high_mhz
        self.taper_frac = taper_frac

    @property
    def params(self) -> Dict[str, Any]:
        return {"low_mhz": self.low_mhz, "high_mhz": self.high_mhz,
                "taper_frac": self.taper_frac}

    def _mask(self, freqs_mhz: np.ndarray) -> np.ndarray:
        width = self.taper_frac * (self.high_mhz - self.low_mhz)
        lo_stop, lo_pass = self.low_mhz - width, self.low_mhz
        hi_pass, hi_stop = self.high_mhz, self.high_mhz + width

        mask = np.zeros_like(freqs_mhz)
        mask[(freqs_mhz >= lo_pass) & (freqs_mhz <= hi_pass)] = 1.0

        if width > 0:
            rising = (freqs_mhz > lo_stop) & (freqs_mhz < lo_pass)
            x = (freqs_mhz[rising] - lo_stop) / width
            mask[rising] = 0.5 * (1.0 - np.cos(np.pi * x))

            falling = (freqs_mhz > hi_pass) & (freqs_mhz < hi_stop)
            x = (freqs_mhz[falling] - hi_pass) / width
            mask[falling] = 0.5 * (1.0 + np.cos(np.pi * x))
        return mask

    def apply(self, rg: Radargram) -> Radargram:
        nyquist_mhz = 500.0 / rg.dt_ns          # (1 / (2 * dt_ns * 1e-9)) / 1e6
        if self.low_mhz < 0:
            raise ValueError(f"low_mhz must be >= 0, got {self.low_mhz}")
        if self.low_mhz >= self.high_mhz:
            raise ValueError(
                f"low_mhz ({self.low_mhz}) must be below high_mhz ({self.high_mhz})"
            )
        if self.high_mhz > nyquist_mhz:
            raise ValueError(
                f"high_mhz ({self.high_mhz}) exceeds the Nyquist frequency "
                f"({nyquist_mhz:.1f} MHz) for a {rg.dt_ns} ns sample interval"
            )

        spectrum = np.fft.rfft(rg.data, axis=0)
        freqs_mhz = np.fft.rfftfreq(rg.n_samples, d=rg.dt_ns * 1e-9) / 1e6
        filtered = spectrum * self._mask(freqs_mhz)[:, None]
        return rg.replace(data=np.fft.irfft(filtered, n=rg.n_samples, axis=0))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_steps_bandpass.py -v`
Expected: all 9 PASS

- [ ] **Step 5: Commit**

```bash
git add packages/nsgeo-core
git commit -m "feat: add cosine-tapered FFT bandpass

The taper is what makes an FFT bandpass acceptable in place of scipy: a
brick-wall filter rings, and that ringing looks like stratigraphy."
```

---

### Task 13: Background removal

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/processing/background.py`
- Create: `packages/nsgeo-core/tests/test_steps_background.py`

**Interfaces:**
- Consumes: `Radargram`, `register`, `running_mean`
- Produces: `"background_mean"` (`BackgroundMean()`), `"background_sliding"` (`BackgroundSliding(window_traces=200)`), `"background_svd"` (`BackgroundSvd(n_components=1)`)

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_steps_background.py`:

```python
from __future__ import annotations

import numpy as np
import pytest

import nsgeo.processing.background  # noqa: F401
from nsgeo.processing.base import Radargram, build_step


def banded(n_samples=128, n_traces=300, seed=0):
    """A strong horizontal band plus random reflectors — the thing background
    removal exists to separate."""
    rng = np.random.default_rng(seed)
    band = np.linspace(5.0, 1.0, n_samples)[:, None] * np.ones((1, n_traces))
    features = rng.normal(0.0, 0.2, (n_samples, n_traces))
    return Radargram(data=band + features, dt_ns=0.2, t0_ns=0.0), band, features


def test_mean_output_has_zero_mean_along_the_trace_axis():
    rg, _, _ = banded()
    out = build_step("background_mean").apply(rg)
    np.testing.assert_allclose(out.data.mean(axis=1), 0.0, atol=1e-12)


def test_mean_removes_the_horizontal_band():
    rg, band, _ = banded()
    out = build_step("background_mean").apply(rg)
    assert np.abs(out.data).mean() < 0.25 * np.abs(rg.data).mean()


def test_mean_leaves_the_time_axis_untouched():
    rg, _, _ = banded()
    out = build_step("background_mean").apply(rg)
    assert out.t0_ns == rg.t0_ns and out.dt_ns == rg.dt_ns


def test_sliding_removes_a_band_that_drifts_along_the_line():
    """Full-line mean fails when the background changes; sliding is why the
    option exists."""
    n_s, n_t = 128, 600
    drift = np.linspace(0.0, 8.0, n_t)[None, :] * np.ones((n_s, 1))
    rng = np.random.default_rng(1)
    data = drift + rng.normal(0, 0.2, (n_s, n_t))
    rg = Radargram(data=data, dt_ns=0.2, t0_ns=0.0)
    sliding = build_step("background_sliding", window_traces=50).apply(rg)
    full = build_step("background_mean").apply(rg)
    assert np.abs(sliding.data).mean() < np.abs(full.data).mean()


def test_sliding_with_window_of_one_is_a_no_op_in_effect():
    rg, _, _ = banded()
    out = build_step("background_sliding", window_traces=1).apply(rg)
    np.testing.assert_allclose(out.data, 0.0, atol=1e-12)


def test_sliding_rejects_zero_window():
    rg, _, _ = banded()
    with pytest.raises(ValueError, match="window_traces"):
        build_step("background_sliding", window_traces=0).apply(rg)


def test_svd_with_zero_components_is_the_identity():
    rg, _, _ = banded()
    out = build_step("background_svd", n_components=0).apply(rg)
    np.testing.assert_allclose(out.data, rg.data, atol=1e-10)


def test_svd_removes_a_rank_one_band():
    rg, band, features = banded()
    out = build_step("background_svd", n_components=1).apply(rg)
    assert np.abs(out.data).mean() < 0.5 * np.abs(rg.data).mean()
    # the random reflectors survive
    assert np.corrcoef(out.data.ravel(), features.ravel())[0, 1] > 0.8


def test_svd_rejects_more_components_than_rank():
    rg, _, _ = banded(n_samples=8, n_traces=5)
    with pytest.raises(ValueError, match="n_components"):
        build_step("background_svd", n_components=99).apply(rg)


def test_svd_rejects_negative_components():
    rg, _, _ = banded()
    with pytest.raises(ValueError, match="n_components"):
        build_step("background_svd", n_components=-1).apply(rg)


def test_none_of_the_steps_mutate_their_input():
    rg, _, _ = banded()
    before = rg.data.copy()
    for name, kwargs in [("background_mean", {}),
                         ("background_sliding", {"window_traces": 20}),
                         ("background_svd", {"n_components": 1})]:
        build_step(name, **kwargs).apply(rg)
    np.testing.assert_array_equal(rg.data, before)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_steps_background.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo.processing.background'`

- [ ] **Step 3: Implement background removal**

Create `packages/nsgeo-core/src/nsgeo/processing/background.py`:

```python
"""Background removal: separating horizontal banding from real reflectors.

Three methods because they fail differently. Full-line mean is the cheapest
and fails when the background drifts along the line. Sliding handles drift but
can eat genuine flat-lying features if the window is short. SVD removes
banding that is not perfectly flat, at higher cost.
"""
from __future__ import annotations

from typing import Any, Dict

import numpy as np

from nsgeo.processing._util import running_mean
from nsgeo.processing.base import Radargram, register


@register
class BackgroundMean:
    """Subtract the mean trace over the whole line."""

    name = "background_mean"

    @property
    def params(self) -> Dict[str, Any]:
        return {}

    def apply(self, rg: Radargram) -> Radargram:
        return rg.replace(data=rg.data - rg.data.mean(axis=1, keepdims=True))


@register
class BackgroundSliding:
    """Subtract a running mean along the trace axis."""

    name = "background_sliding"

    def __init__(self, window_traces: int = 200) -> None:
        self.window_traces = window_traces

    @property
    def params(self) -> Dict[str, Any]:
        return {"window_traces": self.window_traces}

    def apply(self, rg: Radargram) -> Radargram:
        if self.window_traces < 1:
            raise ValueError(f"window_traces must be >= 1, got {self.window_traces}")
        return rg.replace(
            data=rg.data - running_mean(rg.data, self.window_traces, axis=1)
        )


@register
class BackgroundSvd:
    """Remove leading eigenimages.

    Banding that is strong and repeats across traces concentrates in the first
    few singular values, so dropping them removes it without assuming it is
    perfectly flat.
    """

    name = "background_svd"

    def __init__(self, n_components: int = 1) -> None:
        self.n_components = n_components

    @property
    def params(self) -> Dict[str, Any]:
        return {"n_components": self.n_components}

    def apply(self, rg: Radargram) -> Radargram:
        n = self.n_components
        if n < 0:
            raise ValueError(f"n_components must be >= 0, got {n}")
        if n == 0:
            return rg
        rank = min(rg.n_samples, rg.n_traces)
        if n > rank:
            raise ValueError(
                f"n_components={n} exceeds the rank of this radargram ({rank})"
            )
        u, s, vt = np.linalg.svd(rg.data, full_matrices=False)
        s = s.copy()
        s[:n] = 0.0
        return rg.replace(data=(u * s) @ vt)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_steps_background.py -v`
Expected: all 11 PASS

- [ ] **Step 5: Commit**

```bash
git add packages/nsgeo-core
git commit -m "feat: add mean, sliding, and SVD background removal

Three methods because they fail differently: full-line mean cannot follow a
drifting background, sliding can eat genuine flat-lying features, SVD costs
more but does not assume the banding is flat."
```

---

### Task 14: The step stack

Ordered, toggleable, with cached intermediates. Because steps are pure functions, the entire invalidation rule is "invalidate from the edited index onward". The cache is also what makes the difference view nearly free.

**Files:**
- Create: `packages/nsgeo-core/src/nsgeo/processing/stack.py`
- Modify: `packages/nsgeo-core/src/nsgeo/processing/__init__.py`
- Modify: `packages/nsgeo-core/src/nsgeo/project.py`
- Create: `packages/nsgeo-core/tests/test_stack.py`

**Interfaces:**
- Consumes: `Radargram`, `build_step`, all registered steps
- Produces:
  - `StepStack` with `source` property, `append(step)`, `insert(i, step)`, `remove(i)`, `replace_step(i, step)`, `move(i, j)`, `set_enabled(i, flag)`, `result()`, `intermediate(i)`, `difference(i)`, `to_dicts()`, `from_dicts(dicts)`, `__len__`, `cache_size`
  - `project.save_site` / `load_site` round-trip a `stack` per line
  - `Line.stack: Optional[StepStack]` is **not** added; stacks are stored in the project document and returned by `load_site` as `Site.stacks: Dict[str, StepStack]` keyed by the line's relative path

- [ ] **Step 1: Write the failing tests**

Create `packages/nsgeo-core/tests/test_stack.py`:

```python
from __future__ import annotations

import numpy as np
import pytest

from nsgeo.processing.base import Radargram, build_step
from nsgeo.processing.stack import StepStack


def source(n_samples=64, n_traces=120, seed=0):
    rng = np.random.default_rng(seed)
    band = np.linspace(4.0, 1.0, n_samples)[:, None] * np.ones((1, n_traces))
    return Radargram(data=band + rng.normal(0, 0.2, (n_samples, n_traces)),
                     dt_ns=0.2, t0_ns=0.0)


def stack_of(*specs):
    st = StepStack()
    st.source = source()
    for name, kwargs in specs:
        st.append(build_step(name, **kwargs))
    return st


def test_empty_stack_returns_the_source_unchanged():
    st = StepStack()
    src = source()
    st.source = src
    np.testing.assert_array_equal(st.result().data, src.data)


def test_steps_apply_in_order():
    st = stack_of(("background_mean", {}))
    np.testing.assert_allclose(st.result().data.mean(axis=1), 0.0, atol=1e-12)


def test_disabled_step_is_skipped_but_keeps_its_index():
    st = stack_of(("background_mean", {}))
    st.set_enabled(0, False)
    np.testing.assert_array_equal(st.result().data, st.source.data)
    assert len(st) == 1


def test_appending_reuses_the_cached_prefix():
    st = stack_of(("dewow", {"window_ns": 4.0}))
    st.result()
    before = st.cache_size
    st.append(build_step("background_mean"))
    assert st.cache_size == before          # prefix survived
    st.result()
    assert st.cache_size == before + 1


def test_editing_a_step_invalidates_from_that_index_onward():
    st = stack_of(("dewow", {"window_ns": 4.0}), ("background_mean", {}))
    st.result()
    assert st.cache_size == 2
    st.replace_step(0, build_step("dewow", window_ns=8.0))
    assert st.cache_size == 0


def test_editing_a_later_step_keeps_the_earlier_cache():
    st = stack_of(("dewow", {"window_ns": 4.0}), ("background_mean", {}))
    st.result()
    st.replace_step(1, build_step("background_sliding", window_traces=20))
    assert st.cache_size == 1


def test_remove_and_move_invalidate_correctly():
    st = stack_of(("dewow", {"window_ns": 4.0}), ("background_mean", {}))
    st.result()
    st.move(0, 1)
    assert st.cache_size == 0
    assert [s.name for s, _ in st.entries] == ["background_mean", "dewow"]
    st.result()
    st.remove(1)
    assert st.cache_size == 1


def test_setting_a_new_source_clears_everything():
    st = stack_of(("background_mean", {}))
    st.result()
    st.source = source(seed=9)
    assert st.cache_size == 0


def test_intermediate_returns_the_state_after_a_given_step():
    st = stack_of(("dewow", {"window_ns": 4.0}), ("background_mean", {}))
    mid = st.intermediate(0)
    expected = build_step("dewow", window_ns=4.0).apply(st.source)
    np.testing.assert_allclose(mid.data, expected.data)


def test_difference_shows_what_a_step_removed():
    """Nearly free because the intermediates are already cached, and it
    diagnoses over-removal of genuine flat-lying features."""
    st = stack_of(("background_mean", {}))
    diff = st.difference(0)
    np.testing.assert_allclose(
        diff.data, np.tile(st.source.data.mean(axis=1, keepdims=True), (1, st.source.n_traces)),
        atol=1e-9)


def test_difference_rejects_an_out_of_range_index():
    st = stack_of(("background_mean", {}))
    with pytest.raises(IndexError):
        st.difference(5)


def test_result_without_a_source_raises():
    with pytest.raises(ValueError, match="source"):
        StepStack().result()


def test_serialises_to_dicts():
    st = stack_of(("dewow", {"window_ns": 4.0}), ("background_svd", {"n_components": 2}))
    st.set_enabled(1, False)
    assert st.to_dicts() == [
        {"step": "dewow", "params": {"window_ns": 4.0}, "enabled": True},
        {"step": "background_svd", "params": {"n_components": 2}, "enabled": False},
    ]


def test_round_trips_through_dicts():
    st = stack_of(("dewow", {"window_ns": 4.0}), ("background_mean", {}))
    back = StepStack.from_dicts(st.to_dicts())
    back.source = st.source
    np.testing.assert_allclose(back.result().data, st.result().data)


def test_from_dicts_rejects_an_unknown_step():
    with pytest.raises(KeyError, match="available"):
        StepStack.from_dicts([{"step": "nope", "params": {}, "enabled": True}])


def test_project_round_trips_stacks(tmp_path):
    from nsgeo.geometry.grid import Grid
    from nsgeo.geometry.placement import GridPlacement
    from nsgeo.model.survey import Line, Site
    from nsgeo.project import load_site, save_site
    from tests.synthetic import write_dzt

    p = tmp_path / "L0.DZT"
    write_dzt(p, np.zeros((512, 60), dtype=np.int32))
    grid = Grid(id="G", origin=(0.0, 0.0), azimuth=0.0, size_x=20.0, size_y=20.0,
                crs="EPSG:32616", default_spacing=0.5)
    line = Line.open(p, GridPlacement(grid_id="G", axis="y", offset=0.0))
    site = Site(grids=[grid], lines=[line])
    st = StepStack()
    st.append(build_step("dewow", window_ns=4.0))
    site.stacks = {"L0.DZT": st}

    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    back = load_site(out)
    assert back.stacks["L0.DZT"].to_dicts() == st.to_dicts()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_stack.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'nsgeo.processing.stack'`

- [ ] **Step 3: Implement the stack**

Create `packages/nsgeo-core/src/nsgeo/processing/stack.py`:

```python
"""An ordered, toggleable list of steps with cached intermediates.

Nothing here runs automatically. A stack starts empty, and every step is added
by an explicit user action.

Because steps are pure functions of (params, radargram), cache invalidation is
not a hard problem: editing anything at index i invalidates i onward, and that
is the entire rule.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from nsgeo.processing.base import Radargram, build_step


class StepStack:
    def __init__(self) -> None:
        self._entries: List[Tuple[Any, bool]] = []
        self._cache: List[Radargram] = []
        self._source: Optional[Radargram] = None

    # ---- source -------------------------------------------------------
    @property
    def source(self) -> Optional[Radargram]:
        return self._source

    @source.setter
    def source(self, rg: Radargram) -> None:
        self._source = rg
        self._cache = []

    # ---- inspection ---------------------------------------------------
    @property
    def entries(self) -> List[Tuple[Any, bool]]:
        return list(self._entries)

    @property
    def cache_size(self) -> int:
        return len(self._cache)

    def __len__(self) -> int:
        return len(self._entries)

    # ---- mutation -----------------------------------------------------
    def _invalidate_from(self, index: int) -> None:
        del self._cache[index:]

    def append(self, step: Any) -> None:
        self._entries.append((step, True))
        # No invalidation: the existing prefix is still valid.

    def insert(self, index: int, step: Any) -> None:
        self._entries.insert(index, (step, True))
        self._invalidate_from(index)

    def remove(self, index: int) -> None:
        del self._entries[index]
        self._invalidate_from(index)

    def replace_step(self, index: int, step: Any) -> None:
        enabled = self._entries[index][1]
        self._entries[index] = (step, enabled)
        self._invalidate_from(index)

    def move(self, src: int, dst: int) -> None:
        entry = self._entries.pop(src)
        self._entries.insert(dst, entry)
        self._invalidate_from(min(src, dst))

    def set_enabled(self, index: int, flag: bool) -> None:
        step, _ = self._entries[index]
        self._entries[index] = (step, bool(flag))
        self._invalidate_from(index)

    # ---- evaluation ---------------------------------------------------
    def _ensure(self, upto: int) -> None:
        if self._source is None:
            raise ValueError("stack has no source radargram")
        while len(self._cache) <= upto:
            i = len(self._cache)
            previous = self._cache[i - 1] if i else self._source
            step, enabled = self._entries[i]
            self._cache.append(step.apply(previous) if enabled else previous)

    def result(self) -> Radargram:
        if self._source is None:
            raise ValueError("stack has no source radargram")
        if not self._entries:
            return self._source
        self._ensure(len(self._entries) - 1)
        return self._cache[-1]

    def intermediate(self, index: int) -> Radargram:
        """State after applying step `index`."""
        if not 0 <= index < len(self._entries):
            raise IndexError(f"step index {index} out of range (0..{len(self._entries) - 1})")
        self._ensure(index)
        return self._cache[index]

    def difference(self, index: int) -> Radargram:
        """What step `index` removed: the input minus the output.

        Nearly free, because both sides are already cached. Diagnoses
        over-removal of genuine flat-lying features by background steps.
        """
        if not 0 <= index < len(self._entries):
            raise IndexError(f"step index {index} out of range (0..{len(self._entries) - 1})")
        after = self.intermediate(index)
        before = self._cache[index - 1] if index else self._source
        assert before is not None
        return after.replace(data=before.data - after.data)

    # ---- serialisation ------------------------------------------------
    def to_dicts(self) -> List[Dict[str, Any]]:
        return [{"step": s.name, "params": s.params, "enabled": e} for s, e in self._entries]

    @classmethod
    def from_dicts(cls, dicts: List[Dict[str, Any]]) -> "StepStack":
        stack = cls()
        for entry in dicts:
            step = build_step(entry["step"], **entry.get("params", {}))
            stack._entries.append((step, bool(entry.get("enabled", True))))
        return stack
```

- [ ] **Step 4: Populate the registry on import**

Replace `packages/nsgeo-core/src/nsgeo/processing/__init__.py` with:

```python
"""User-ordered processing steps. Nothing here runs automatically.

Importing this package registers every built-in step, so `build_step` and
`available_steps` work without the caller importing each module.
"""
from __future__ import annotations

from nsgeo.processing import (  # noqa: F401
    background,
    bandpass,
    dewow,
    gain,
    timezero,
)
from nsgeo.processing.base import (  # noqa: F401
    Radargram,
    Step,
    available_steps,
    build_step,
    get_step,
    register,
)
from nsgeo.processing.stack import StepStack  # noqa: F401
```

- [ ] **Step 5: Add stacks to the project document**

In `packages/nsgeo-core/src/nsgeo/project.py`, add the import:

```python
from nsgeo.processing.stack import StepStack
```

In `save_site`, replace the `"lines"` list comprehension with:

```python
    lines_doc = []
    for line in site.lines:
        rel = Path(line.path).resolve().relative_to(root).as_posix()
        entry: Dict[str, Any] = {
            "path": rel,
            "placement": _placement_to_dict(line.placement),
        }
        stack = getattr(site, "stacks", {}).get(rel)
        if stack is not None:
            entry["stack"] = stack.to_dicts()
        lines_doc.append(entry)
```

and use `"lines": lines_doc` in the document.

In `load_site`, collect stacks alongside lines:

```python
    stacks: Dict[str, StepStack] = {}
    for entry in doc.get("lines", []):
        ...                                    # existing line construction
        if "stack" in entry:
            stacks[entry["path"]] = StepStack.from_dicts(entry["stack"])
    site = Site(grids=grids, lines=lines)
    site.stacks = stacks
```

In `packages/nsgeo-core/src/nsgeo/model/survey.py`, add the field to `Site`:

```python
    stacks: Dict[str, Any] = field(default_factory=dict)
```

- [ ] **Step 6: Run the full suite**

Run: `cd packages/nsgeo-core && python -m pytest tests/ -v`
Expected: all PASS, including the boundary test

- [ ] **Step 7: Commit**

```bash
git add packages/nsgeo-core
git commit -m "feat: add the processing step stack with cached intermediates

Invalidation is 'from the edited index onward', which is the whole rule
because steps are pure. The cache also makes the difference view — what a
background step actually removed — nearly free.

Stacks serialise into survey.nsgeo.json, so what was done to a profile is an
inspectable, diffable, shareable record."
```

---

### Task 15: Integration against real survey files

Validates the reader against the ten real SIR-4000 files. These are gitignored, so the test skips when they are absent and CI stays green — CI validates synthetic files, and real validation runs locally.

**Files:**
- Create: `packages/nsgeo-core/tests/test_real_files.py`

**Interfaces:**
- Consumes: everything above

- [ ] **Step 1: Write the test**

Create `packages/nsgeo-core/tests/test_real_files.py`:

```python
"""Validation against real survey files.

These files are gitignored: DZT headers can carry GPS and publishing site
locations is not reversible. The suite skips when they are absent, so CI
remains green while local runs get real validation.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from nsgeo.io.dzt import read_header, read_samples, trace_count
from nsgeo.processing import StepStack, build_step
from nsgeo.processing.base import Radargram

DATA = Path(__file__).parent / "data" / "local"
FILES = sorted(DATA.glob("*.DZT")) if DATA.exists() else []

pytestmark = pytest.mark.skipif(not FILES, reason="no real DZT files in tests/data/local")


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_header_matches_verified_expectations(path):
    h = read_header(path)
    assert h.tag == 2047                    # not the widely cited 255
    assert h.data_offset == 131072          # 1024 * rh_data, not the 1024 minimum
    assert h.n_samples == 512
    assert h.bits == 32
    assert h.n_channels == 1
    assert h.antenna == "HS350US"
    assert h.traces_per_metre == pytest.approx(60.0)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_trace_count_is_a_whole_number(path):
    """The diagnostic that caught the wrong header-size assumption."""
    h = read_header(path)
    n = trace_count(path, h)
    assert n > 0
    length_m = n / h.traces_per_metre
    assert 9.0 < length_m < 13.0            # recorded lines are 10.1-11.1 m


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_samples_are_int32_centred_near_zero(path):
    data = read_samples(path)
    assert data.shape[0] == 1
    assert data.dtype == np.int32
    assert abs(float(data.mean())) < 5_000        # real means are around -300
    assert np.abs(data).max() > 1_000_000


@pytest.mark.parametrize("path", FILES[:1], ids=lambda p: p.name)
def test_leading_zero_traces_survive_the_reader(path):
    """Recording starts before the cart moves. Real files begin with zero
    traces, and trimming them would corrupt the distance axis."""
    data = read_samples(path)[0]
    assert not data[:, 0].any()


def test_a_full_stack_runs_on_a_real_profile():
    h = read_header(FILES[0])
    data = read_samples(FILES[0])[0].astype(float)
    rg = Radargram(data=data, dt_ns=h.dt_ns, t0_ns=h.position_ns)

    stack = StepStack()
    stack.source = rg
    stack.append(build_step("time_zero", mode="first_break", threshold=0.25))
    stack.append(build_step("dewow", window_ns=4.0))
    stack.append(build_step("bandpass", low_mhz=100.0, high_mhz=700.0))
    stack.append(build_step("background_sliding", window_traces=200))
    stack.append(build_step("gain_agc", window_ns=20.0))

    out = stack.result()
    assert np.isfinite(out.data).all()
    assert out.n_traces == rg.n_traces
    assert out.n_samples <= rg.n_samples         # time_zero cropped rows
    assert out.t0_ns >= rg.t0_ns

    removed = stack.difference(3)                # what background removal took
    assert removed.data.shape == out.data.shape
```

- [ ] **Step 2: Run it against the real files**

Run: `cd packages/nsgeo-core && python -m pytest tests/test_real_files.py -v`
Expected: all PASS (not skipped — the files are present locally)

- [ ] **Step 3: Verify the suite still passes without them**

Run:
```bash
cd packages/nsgeo-core && python -m pytest tests/ -v --ignore=tests/test_real_files.py
```
Expected: all PASS — confirms CI is green without real data

- [ ] **Step 4: Run the complete verification set**

Run:
```bash
cd /home/jameszd/Documents/Github/archaeo_geophysics
ruff check . && ruff format --check . \
  && mypy packages/nsgeo-core/src/nsgeo \
  && python -m pytest packages/nsgeo-core/tests -v
```
Expected: clean lint, clean types, all tests pass

- [ ] **Step 5: Commit**

```bash
git add packages/nsgeo-core
git commit -m "test: validate the reader against ten real SIR-4000 files

Skips when the gitignored real files are absent, so CI stays green while
local runs get real validation. Asserts the header facts that a naive reader
gets wrong: tag 2047, a 131072-byte header, and untrimmed leading zero traces."
```

---

## Deferred to Plan 2 or later

Recorded so they are not silently lost:

- **Scrubbed committed fixtures.** Real files stay gitignored. Producing a truncated, coordinate-scrubbed fixture that could be committed needs the header contents inspected and the owner's explicit consent, so it is not part of this plan.
- **`.DZX` sidecar parsing** — XML metadata that may carry marks and line information (spec §6a).
- **`TrackPlacement` and the `.DZG` reader** — designed in Task 5's protocol, unbuilt until real DZG data exists.
- **`.gpr` reader** — instrument unidentified (spec §6a).
- **Odometer correction** against a known line length — deliberately not a model field.
- **Everything in M4–M9** — the QGIS plugin, which is Plan 2.
