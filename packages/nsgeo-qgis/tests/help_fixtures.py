"""A valid help page for the checker tests, with hooks for mutating it.

`write_valid_help(tmp_path)` writes a passing `dewow` page, `img/t.png` and
`style.css` into `tmp_path` and returns the page path. Each `(old, new)` pair in
`edits` is a string replace on the page text; it raises if `old` is absent, so a
mutation can never silently do nothing. `valid_sources()` is the matching ledger.
"""

from __future__ import annotations

from pathlib import Path

from help_tools.sources import ClaimEvidence, Source, Sources

SECTION_ORDER = ("plain", "pictures", "method", "settings", "know", "nsgeo", "refs")

PLAIN = "The signal drifts. This step removes the drift. It leaves the echoes alone."

VALID_PAGE = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Dewow</title>
<link rel="stylesheet" href="style.css"></head>
<body><main>
<section id="plain"><h2>Plain</h2><p>{PLAIN}</p></section>
<section id="pictures"><h2>Pictures</h2><img src="img/t.png" alt="a picture"></section>
<section id="method"><h2>Method</h2>
<p data-claim="t-claim" data-source="t-src">Wow and flutter.
<a href="https://example.org/a" data-source="t-src">A link</a></p></section>
<section id="settings"><h2>Settings</h2>
<div class="setting" data-param="window_ns"><p>The window.</p></div></section>
<section id="know"><h2>Know</h2><ul><li>One thing.</li></ul></section>
<section id="nsgeo"><h2>nsgeo</h2><p>It runs.</p></section>
<section id="refs"><h2>Refs</h2><ol><li data-source="t-src">A reference.</li></ol></section>
</main></body></html>
"""


def write_valid_help(
    help_dir: Path, name: str = "dewow", edits: tuple[tuple[str, str], ...] = ()
) -> Path:
    """Write the valid page as `<name>.html` (after `edits`) with its image and style.css."""
    text = VALID_PAGE
    for old, new in edits:
        if old not in text:
            raise AssertionError(f"fixture edit target not in the page: {old!r}")
        text = text.replace(old, new, 1)
    help_dir.mkdir(parents=True, exist_ok=True)
    (help_dir / "img").mkdir(exist_ok=True)
    (help_dir / "img" / "t.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (help_dir / "style.css").write_text("body{}", encoding="utf-8")
    path = help_dir / f"{name}.html"
    path.write_text(text, encoding="utf-8")
    return path


def valid_sources(claim_page: str = "dewow") -> Sources:
    """The ledger matching the valid page: source `t-src`, claim `t-claim` owned by `claim_page`."""
    src = Source("t-src", "A citation", None, "read it", "2026-10-15", "")
    claim = ClaimEvidence("t-claim", claim_page, "memory", "p. 1", "")
    return Sources({"t-src": src}, {"t-claim": claim})
