# Task 4 Report: `nsgeo.io.dzx` — the GSSI sidecar

## What I implemented

- `packages/nsgeo-core/src/nsgeo/io/dzx.py` — `DzxError`, `DzxMark`, `DzxInfo`,
  `sidecar_for(path) -> Path | None`, `read_dzx(path) -> DzxInfo | None`, as
  specified in the brief. Namespace-agnostic parsing (`_strip_namespaces`
  rewrites every element's tag to drop the `{www.geophysical.com/DZX/1.02}`
  prefix so xpath lookups don't need to spell the namespace), a `_text` helper
  for optional single-value lookups.
- `packages/nsgeo-core/tests/test_dzx.py` — the brief's ten tests verbatim,
  plus one test of my own (`test_malformed_field_raises_dzx_error_not_bare_valueerror`)
  covering the deviation described below.

Behaviour matches the brief: a missing sidecar returns `None` (not an error);
`sidecar_for` finds either case of extension and accepts a path that already
points at the `.DZX`; a malformed/truncated XML file raises `DzxError` naming
the file; missing optional elements (dielectric, system, name, scan range,
marks) come back as `None`/`()`, never raise. Verified against all nine real
sidecars via the symlinked `tests/data/local/` fixtures — I additionally
hand-inspected `FILE__001.DZX` and `FILE__007.DZX` directly to confirm the
brief's stated facts (dielectric 14, system `UtilityScanHS`, scan range
`0,607`, and `FILE__007`'s single `WayPt` at scan 634 named `Mark1`) before
trusting the reference code against them.

## Deviation from the brief's reference code

**Found:** the brief's `read_dzx` only wraps `xml.etree.ElementTree.ParseError`
(XML syntax failure) as `DzxError`. Everything after parsing — the
`scanRange` split/`int()`, the dielectric `float()`, and each `WayPt`'s
`int(scan)` — runs unguarded. A syntactically valid but semantically
malformed sidecar (e.g. `<scanRange>oops</scanRange>`, no comma to split on)
raises a bare `ValueError: not enough values to unpack`, not `DzxError`.

This contradicts the brief's own framing: "A sidecar is user-supplied data"
and "the same contract `DztError` and `ProjectError` follow elsewhere in this
package." Both of those precedents wrap every value-conversion path over
untrusted input, not just the top-level syntax check — see
`project.py::load_site`'s `json.JSONDecodeError` wrap alongside the
per-field `except (KeyError, TypeError, ValueError): raise ProjectError(...)`
around `VelocityModel.from_dict` and `StepStack.from_dicts`. `dzt.py` does the
analogous thing for header fields via `DztError`. Leaving `dzx.py` as the one
untrusted-input reader in the package that lets a stdlib `ValueError` escape
raw would be inconsistent with that pattern, and would hand callers (the
future import dialog) an exception type they have no reason to expect and
no contract to catch.

**Fix:** wrapped the whole post-parse field-extraction block (scan range,
dielectric, marks) in one `try/except ValueError`, re-raising as
`DzxError(f"{side.name} has a malformed field: {exc}")`. This is the same
shape as `project.py`'s wrapping, not a new validation layer — I did not add
range checks, sanity checks on scan ordering, or anything not already implied
by the existing conversions. `TypeError` is deliberately not caught here (unlike
`project.py`'s `except (KeyError, TypeError, ValueError)`): every value fed to
`int()`/`float()`/`str.split()` in this module already comes out of `_text()`
as `str | None`, guarded by truthiness checks, so `TypeError` isn't a reachable
failure mode the way it is for `project.py`'s untyped JSON dict lookups —
adding it would be defending against a case that can't occur here.

I verified this was a real, reachable defect rather than a
theoretical one: I temporarily reverted `dzx.py` to the brief's exact
unwrapped code, ran my new test, and watched it fail with the bare
`ValueError` shown below (see TDD Evidence). I did not touch anything else in
the reference code — `sidecar_for`, `_strip_namespaces`, `_text`, and the
xpath queries are all used as given, and I found no fault in them (verified
against real files directly, see above).

## TDD Evidence

### RED (brief's tests, before implementation)

Command:
```
.venv/bin/python -m pytest packages/nsgeo-core/tests/test_dzx.py -q
```
Output (module didn't exist yet):
```
ModuleNotFoundError: No module named 'nsgeo.io.dzx'
=========================== short test summary info ============================
ERROR packages/nsgeo-core/tests/test_dzx.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.12s
```
Expected and correct: `dzx.py` did not exist yet.

### RED (my own test, against the brief's *unwrapped* reference code)

After implementing `dzx.py` verbatim from the brief and adding
`test_malformed_field_raises_dzx_error_not_bare_valueerror`, I ran just that
test against the brief's code (before adding my `try/except ValueError` fix):

Command:
```
.venv/bin/python -m pytest packages/nsgeo-core/tests/test_dzx.py -q -k malformed_field
```
Output:
```
    def read_dzx(path: str | Path) -> DzxInfo | None:
        ...
        scan_range: tuple[int, int] | None = None
        raw_range = _text(root, "./File/scanRange")
        if raw_range:
>           lo, hi = raw_range.split(",")
            ^^^^^^
E           ValueError: not enough values to unpack (expected 2, got 1)

packages/nsgeo-core/src/nsgeo/io/dzx.py:73: ValueError
=========================== short test summary info ============================
FAILED packages/nsgeo-core/tests/test_dzx.py::test_malformed_field_raises_dzx_error_not_bare_valueerror
1 failed, 9 deselected in 0.05s
```
Expected: this demonstrates the reference code raises a bare `ValueError`
rather than `DzxError`, confirming the defect is real and reachable, not
speculative.

### GREEN (full test file, after the fix)

Command:
```
.venv/bin/python -m pytest packages/nsgeo-core/tests/test_dzx.py -v
```
Output:
```
test_parses_a_synthetic_sidecar PASSED
test_lowercase_extension_is_found PASSED
test_missing_sidecar_returns_none PASSED
test_path_may_point_at_the_sidecar_itself PASSED
test_malformed_xml_raises_dzx_error PASSED
test_malformed_field_raises_dzx_error_not_bare_valueerror PASSED
test_missing_elements_are_none_not_errors PASSED
test_real_sidecar_without_marks PASSED
test_real_sidecar_with_one_user_mark PASSED
test_real_file_without_sidecar PASSED
============================== 10 passed in 0.04s ==============================
```
All three real-sidecar tests ran (not skipped) — the symlinked
`tests/data/local/` fixtures are present in this worktree.

### GREEN (full core suite + lint + mypy)

```
.venv/bin/python -m pytest packages/nsgeo-core/tests -q
```
```
277 passed, 2 skipped in 0.69s
```
(2 pre-existing skips, both in `test_schema.py`, unrelated to this task —
confirmed via `-rs`.)

```
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```
```
All checks passed!
46 files already formatted
```
(One file, `test_dzx.py`, needed one auto-format pass for a long string
literal — applied via `ruff format`, then re-verified clean and re-ran the
suite.)

```
.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo
```
```
Success: no issues found in 22 source files
```

`test_boundary.py` (the qgis/Qt/matplotlib/scipy import guard) passes and
explicitly walks the src tree, confirmed by running it in isolation.

## Files changed

- `packages/nsgeo-core/src/nsgeo/io/dzx.py` (new, 97 lines)
- `packages/nsgeo-core/tests/test_dzx.py` (new, 108 lines)

Single commit: `9164ec7` — "feat: read the GSSI .DZX sidecar for import hints"
(message exactly as given in the brief, plus the required
`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` trailer).

## Self-review findings

- **API surface**: matches the brief's interface list exactly — same class
  names, same field order (`DzxMark(scan, kind, name)`,
  `DzxInfo(name, scan_range, dielectric, system, marks)`), same function
  signatures.
- **Naming/style**: follows `dzt.py`'s conventions — module docstring explains
  *why* (hints only, missing sidecar is normal), `DzxError` positioned right
  after the docstring like `DztError`, frozen dataclasses for parsed records,
  `from __future__ import annotations` at the top, `str | Path` parameter
  types, `Path | None` / `DzxInfo | None` returns.
  ruff's `UP` rules didn't need to touch anything (no legacy `Optional`/`Union`
  usage crept in).
  Missing optional elements are normal.
- **YAGNI**: the only deviation from the brief is the one `try/except`
  wrapping already-existing conversions in `DzxError` — no new validation
  rules, no schema versioning, no third-party XML library, no defensive
  checks beyond what the brief's own code attempted. I deliberately did not
  add checks the brief didn't ask for (e.g. validating `scan_range` order,
  rejecting negative dielectric, or reconciling scan range against a DZT trace
  count — the brief explicitly forbids that last one: "Do not over-trust
  `scanRange`").
  `sidecar_for`'s two-candidate loop (`.DZX` then `.dzx`) is a little
  redundant with the case-insensitive real filesystem check the brief
  describes, but it's the brief's own approach, it's simple, and rewriting it
  would be change for its own sake — left as-is.
- **Test quality**: every test in the file asserts on public return values
  (`DzxInfo`/`DzxMark` equality, `None`, raised exception + message content),
  none inspects internals like `_text` or `_strip_namespaces` directly. My
  added test follows the same shape as the brief's `test_malformed_xml_raises_dzx_error`
  (same file-naming/`pytest.raises(..., match=...)` pattern) so it reads as
  part of the same suite rather than a bolt-on.
  `test_boundary.py` I checked but didn't touch — it already discovers the new
  module by walking `src/nsgeo`.
  There is no dependency in `dzx.py` on `velocity.py`, `render.py`, or the
  processing schema, per the brief's instruction not to import velocity or
  convert dielectric here.
- **Test output**: pristine — 277 passed, 2 pre-existing unrelated skips, no
  warnings, ruff and mypy both clean.

## Concerns

None. I'm confident in the implementation; the one deviation is narrow,
directly justified by an existing in-repo precedent (`project.py`'s error
wrapping, referenced explicitly by this task's own brief), and proven with a
real RED/GREEN cycle against the brief's own unwrapped code, not just
asserted.

---

# Fix Round 1

Commit: `6b69e5b` — "fix: stop dzx.py from fabricating marks and mixing
multi-File data", on top of `9164ec7`.

## What I changed, finding by finding

**Finding 1 — WayPt with no scan fabricated scan 0 (dzx.py:82).**
Chose: **raise `DzxError`**, not skip. Reasoning: the module already has an
established, reviewer-endorsed rule from round 1 — a field/section that is
*absent* comes back as `None`/`()` (documented as normal), but a field that is
*present but unparseable* raises `DzxError` (already true for a malformed
`scanRange` or non-numeric `dielectric`, both wrapped in round 1). A `WayPt`
that exists in the XML but has no `<scan>` child is the "present but
malformed" case, not the "absent" case — it's structurally different from
"no `WayPt` at all" (which correctly stays `()`). Silently dropping the bad
`WayPt` would also make a genuinely mark-free line indistinguishable from a
line whose sidecar had a corrupt mark quietly discarded, which is exactly the
kind of reconciling-on-the-file's-behalf the module's own governing rule
forbids. I added `_mark()`, a small helper that raises
`ValueError("WayPt has no scan")` when the scan is absent; the existing
outer `except ValueError` (already in place from round 1's fix) re-wraps it
as `DzxError` naming the file, so the error-wrapping policy stays in one
place rather than growing a second copy.

**Finding 2 — marks merged across multiple `File` elements (dzx.py:72, 86,
92).** Resolved `file_el = root.find("./File")` once, and now read
`scanRange`, `name`, and `Profile/WayPt` all relative to that single element
instead of `name`/`scanRange` coming from `root.find("./File/...")` (first
File, implicitly) while marks came from `root.findall("./File/Profile/WayPt")`
(every File). Merging `WayPt`s across multiple `Profile` elements *within*
one `File` is unchanged and still correct (`file_el.findall("./Profile/WayPt")`
still walks every `Profile` child of that one `File`), since a single File's
several Profiles share its scan axis, while a second File's Profiles do not.

**Finding 3 — whitespace-only text returned `""` instead of `None`
(dzx.py:56).** Rewrote `_text` exactly as suggested:
`text = (el.text or "").strip(); return text or None`. Missing element and
whitespace-only element now both collapse to `None`, consistent with the
"absent field is `None`" contract for `name` and `system` (previously only
`scan_range` and `dielectric` were shielded by their own truthiness checks).

**Finding 4 — only `ET.ParseError` wrapped, so `OSError` (e.g. a directory at
the sidecar path) escaped raw (dzx.py:64-67).** Added
`except OSError as exc: raise DzxError(f"{side.name} could not be read:
{exc}") from exc` alongside the existing `ET.ParseError` handler (kept as a
separate `except` rather than merged, so each message names its actual cause
— "not well-formed XML" for a syntax failure, "could not be read" for an I/O
failure — rather than one message trying to cover both).

**Not-in-scope item (billion laughs).** Since I was already editing the
`try`/`except` around `ET.parse`, I added the one-line comment the reviewer
said would be welcome: `ElementTree expands internal entities, so a hostile
"billion laughs" sidecar is a memory DoS; accepted, since defusedxml would
break the stdlib-only rule and this is a file the user chose to open.` No
other change was made for this item, per the reviewer's explicit scope limit.

**Comment/description parsing** — left untouched, per the reviewer's
"Settled" note. `DzxMark` stays WayPt-only.

## Tests added

- `test_waypt_without_scan_raises_dzx_error` — Finding 1.
- `test_multiple_file_elements_do_not_mix_marks_across_lines` (with a new
  `TWO_FILE_XML` fixture) — Finding 2; asserts `name`/`scan_range` come from
  the first `File` and `marks` contains only the first `File`'s `WayPt`, not
  the second's.
- `test_whitespace_only_text_is_none_not_empty_string` — Finding 3, covering
  both `File/name` and `DataCollection/system`.
- `test_sidecar_that_is_a_directory_raises_dzx_error` — Finding 4.
- `test_reader_is_not_pinned_to_a_namespace` (new `OTHER_NAMESPACE_XML`
  fixture, a namespace that isn't `1.02`) and
  `test_reader_tolerates_no_namespace_at_all` (new `NO_NAMESPACE_XML`
  fixture, no `xmlns` at all) — namespace-agnosticism, previously asserted by
  the module's docstring but never exercised by a test, since every existing
  fixture happened to use exactly `www.geophysical.com/DZX/1.02`.
- `test_empty_file_raises_dzx_error` and
  `test_non_numeric_dielectric_raises_dzx_error` — pin two behaviours that
  were already correct but untested.

## TDD evidence

### RED: findings 1 and 2 against the pre-round-1-fix code

I backed up the round-1-fixed `dzx.py`, then temporarily replaced it with
`git show 9164ec7:packages/nsgeo-core/src/nsgeo/io/dzx.py` (the code exactly
as committed at the end of round 1, before any of this round's changes) and
ran the two new tests that target reachable bugs:

Command:
```
.venv/bin/python -m pytest packages/nsgeo-core/tests/test_dzx.py -q -k "waypt_without_scan or multiple_file_elements"
```
Output:
```
FAILED packages/nsgeo-core/tests/test_dzx.py::test_waypt_without_scan_raises_dzx_error
  Failed: DID NOT RAISE DzxError
FAILED packages/nsgeo-core/tests/test_dzx.py::test_multiple_file_elements_do_not_mix_marks_across_lines
  AssertionError: ... marks: (DzxMark(scan=1, kind='User', name='a'), DzxMark(scan=2, kind='User', name='b')) != (DzxMark(scan=1, kind='User', name='a'),)
2 failed, 16 deselected in 0.07s
```
Expected and confirmed: the pre-fix code invents `scan=0` for a scan-less
`WayPt` (no error raised) and merges the second `File`'s mark into the
first's report.

### RED: findings 3 and 4 against the same pre-fix code

Command:
```
.venv/bin/python -m pytest packages/nsgeo-core/tests/test_dzx.py -q -k "directory or whitespace_only"
```
Output (abridged):
```
FAILED packages/nsgeo-core/tests/test_dzx.py::test_whitespace_only_text_is_none_not_empty_string
  AssertionError (name/system came back as "" instead of None)
FAILED packages/nsgeo-core/tests/test_dzx.py::test_sidecar_that_is_a_directory_raises_dzx_error
  IsADirectoryError: [Errno 21] Is a directory: '.../weird.DZX'
  (raised inside xml.etree.ElementTree.parse -> open(), not caught, not DzxError)
2 failed, 16 deselected in 0.09s
```
Expected and confirmed: a directory at the sidecar path raised a bare
`IsADirectoryError`, and whitespace-only text was not treated as absent.

I restored the round-1-fixed file from my backup immediately after each RED
check, before making the round-2 edits described above.

### GREEN: full scoped test file, after all four fixes

Command:
```
.venv/bin/python -m pytest packages/nsgeo-core/tests/test_dzx.py -v
```
Output:
```
test_parses_a_synthetic_sidecar PASSED
test_lowercase_extension_is_found PASSED
test_missing_sidecar_returns_none PASSED
test_path_may_point_at_the_sidecar_itself PASSED
test_malformed_xml_raises_dzx_error PASSED
test_malformed_field_raises_dzx_error_not_bare_valueerror PASSED
test_missing_elements_are_none_not_errors PASSED
test_empty_file_raises_dzx_error PASSED
test_non_numeric_dielectric_raises_dzx_error PASSED
test_waypt_without_scan_raises_dzx_error PASSED
test_multiple_file_elements_do_not_mix_marks_across_lines PASSED
test_whitespace_only_text_is_none_not_empty_string PASSED
test_sidecar_that_is_a_directory_raises_dzx_error PASSED
test_reader_is_not_pinned_to_a_namespace PASSED
test_reader_tolerates_no_namespace_at_all PASSED
test_real_sidecar_without_marks PASSED
test_real_sidecar_with_one_user_mark PASSED
test_real_file_without_sidecar PASSED
============================== 18 passed in 0.06s ==============================
```
All three real-sidecar tests ran (not skipped) — the symlinked real data is
still present in this worktree.

### GREEN: full core suite, ruff, mypy

```
.venv/bin/python -m pytest packages/nsgeo-core/tests -q
```
```
285 passed, 2 skipped in 0.67s
```
(285 = the prior 277 plus 8 new tests in this round; the 2 skips are the same
pre-existing, unrelated `test_schema.py` skips noted in round 1.)

```
.venv/bin/ruff check .
```
```
All checks passed!
```

```
.venv/bin/ruff format --check .
```
```
46 files already formatted
```

```
.venv/bin/mypy --config-file packages/nsgeo-core/pyproject.toml packages/nsgeo-core/src/nsgeo
```
```
Success: no issues found in 22 source files
```

## Concerns

None. All four findings were verified as reachable (two — WayPt-without-scan
and multi-File merging — via a genuine RED run against the exact pre-fix
code; the other two — whitespace-only text and the directory sidecar — the
same way), fixed at the location the reviewer named, and the fixes are each
one small, targeted change rather than a broader rewrite. No new dependency
on `velocity`, `render`, or the processing schema was introduced. The
not-in-scope items (billion laughs beyond a comment, the `Optional` deref in
the test file) were left untouched as instructed.
