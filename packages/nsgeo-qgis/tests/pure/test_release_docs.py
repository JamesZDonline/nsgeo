"""The practitioner-facing docs and metadata copy, pinned (spec 5.4, 5.5).

`build_zip.py --tag` already refuses a tag without `docs/releases/<v>.md`;
these pin what those notes, the getting-started guide and the README must
say, and that `metadata.txt`'s `about` and `changelog` match the release.
"""

from __future__ import annotations

import configparser
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
METADATA = REPO / "packages" / "nsgeo-qgis" / "nsgeo_qgis" / "metadata.txt"
README = REPO / "README.md"
GUIDE = REPO / "docs" / "guide" / "getting-started.md"
ISSUES = ("#22", "#23", "#40")

# An inline `[text](target)` / `![alt](target)` link, its target bare or in
# angle brackets (which may hold spaces), with an optional "title", 'title'
# or (title); a reference definition `[label]: target` on a line of its own;
# or an HTML `<img src="target">`.
_TITLE = r"""(?:\s+(?:"[^"]*"|'[^']*'|\([^)]*\)))?"""
_INLINE_LINK = re.compile(r"\]\(\s*(?:<([^>\n]*)>|([^)\s]+))" + _TITLE + r"\s*\)")
_REFERENCE_LINK = re.compile(r"^\s*\[[^\]]+\]:\s*(?:<([^>\n]*)>|(\S+))", re.MULTILINE)
_IMG_TAG = re.compile(r"""<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_ABSOLUTE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")  # https:, mailto:, ...
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)(?:\s+#+)?\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


def _metadata() -> configparser.SectionProxy:
    # Parsed exactly as QGIS's plugin installer parses it (installer_data.py,
    # `metadataParser`): a plain ConfigParser, interpolation on. A stray `%`
    # in `about` or `changelog` then fails here instead of blanking the field
    # in the Plugin Manager.
    parser = configparser.ConfigParser()
    with METADATA.open(encoding="utf-8") as f:
        parser.read_file(f)
    return parser["general"]


def _notes() -> Path:
    return REPO / "docs" / "releases" / f"{_metadata()['version']}.md"


def _link_targets(text: str) -> list[str]:
    targets = [a or b for a, b in _INLINE_LINK.findall(text)]
    targets += [a or b for a, b in _REFERENCE_LINK.findall(text)]
    return targets + _IMG_TAG.findall(text)


def _relative_links(doc: Path) -> list[str]:
    return [t for t in _link_targets(doc.read_text(encoding="utf-8")) if not _ABSOLUTE.match(t)]


def _headings(text: str) -> list[tuple[int, str]]:
    """(level, text) of each ATX heading, outside fenced code blocks."""
    found, fenced = [], False
    for line in text.splitlines():
        if _FENCE.match(line):
            fenced = not fenced
        elif not fenced and (m := _HEADING.match(line)):
            found.append((len(m.group(1)), m.group(2)))
    return found


def _anchors(text: str) -> set[str]:
    """The in-page anchors GitHub gives the headings: lower case, punctuation
    other than `-` and `_` dropped, spaces turned to `-`, and `-1`, `-2`, ...
    appended to repeats."""
    seen: dict[str, int] = {}
    anchors = set()
    for _, heading in _headings(text):
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        n = seen.get(slug, 0)
        seen[slug] = n + 1
        anchors.add(slug if n == 0 else f"{slug}-{n}")
    return anchors


def _section(text: str, heading: str) -> str:
    """The lines under `heading` (an exact line, such as "### Upgrading"),
    up to the next heading at its level or above."""
    level = len(heading) - len(heading.lstrip("#"))
    lines = text.splitlines()
    start = lines.index(heading) + 1
    end = next(
        (
            i
            for i in range(start, len(lines))
            if (m := _HEADING.match(lines[i])) and len(m.group(1)) <= level
        ),
        len(lines),
    )
    return "".join(line + "\n" for line in lines[start:end])


def _broken_links(doc: Path) -> list[str]:
    """Each relative link in `doc` whose file is missing, or whose `#anchor`
    names no heading in the file it points at."""
    broken = []
    for target in _relative_links(doc):
        path, _, anchor = target.partition("#")
        dest = doc.parent / path if path else doc
        if not dest.exists() or (
            anchor
            and dest.suffix == ".md"
            and anchor not in _anchors(dest.read_text(encoding="utf-8"))
        ):
            broken.append(target)
    return broken


def test_release_notes_exist_for_the_metadata_version_and_link_the_guide():
    notes = _notes().read_text(encoding="utf-8")
    assert "experimental" in notes.lower()
    # The guide as it was at this release's tag, not as it is on main.
    g = _metadata()
    guide = f"{g['repository']}/blob/v{g['version']}/docs/guide/getting-started.md"
    assert guide in [t.partition("#")[0] for t in _link_targets(notes)], guide


def test_release_notes_use_only_absolute_links():
    """The notes are pasted into the GitHub release page, where a relative
    link resolves against the release URL and breaks."""
    relative = [
        f"{notes.name}: {t}"
        for notes in sorted((REPO / "docs" / "releases").glob("*.md"))
        for t in _link_targets(notes.read_text(encoding="utf-8"))
        if not _ABSOLUTE.match(t)
    ]
    assert relative == []


def test_the_link_checker_finds_each_kind_of_broken_link(tmp_path):
    (tmp_path / "other.md").write_text("# Other\n\n## A section\n", encoding="utf-8")
    (tmp_path / "with space.md").write_text("# Spaced\n", encoding="utf-8")
    doc = tmp_path / "doc.md"
    doc.write_text(
        "# Doc\n\n## Step 1: Begin\n\n"
        "Good: [a](other.md), [b](other.md#a-section), [c](#step-1-begin),\n"
        "[d](<with space.md>), [e](other.md 'title'), [f](https://example.com/x#y).\n"
        "![g](other.md)\n\n"
        "Broken: [h](<missing one.md>), [i](missing2.md 'title'),\n"
        "[j](missing3.md (title)), [k](#no-such-section), [l](other.md#no-such-section).\n"
        '<img src="missing4.png" alt="m">\n\n'
        "[ref]: missing5.md 'title'\n"
        "```\n# not a heading\n```\n"
        "[n](#not-a-heading)\n",
        encoding="utf-8",
    )
    assert sorted(_broken_links(doc)) == sorted(
        [
            "missing one.md",
            "missing2.md",
            "missing3.md",
            "#no-such-section",
            "other.md#no-such-section",
            "missing4.png",
            "missing5.md",
            "#not-a-heading",
        ]
    )


def test_every_relative_link_in_the_user_docs_resolves():
    docs = [README, GUIDE, *sorted((REPO / "docs" / "releases").glob("*.md"))]
    assert _notes() in docs
    broken = [f"{doc.relative_to(REPO)}: {t}" for doc in docs for t in _broken_links(doc)]
    assert broken == []
    # Not vacuous: the README's Install section links the guide relatively.
    assert "docs/guide/getting-started.md" in _relative_links(README)


def test_known_issues_are_disclosed_in_notes_and_guide():
    for doc in (_notes(), GUIDE):
        text = doc.read_text(encoding="utf-8")
        for n in ISSUES:
            assert n in text, (doc.name, n)


def test_the_guide_says_to_restart_qgis_after_installing_and_after_upgrading():
    # Upgrading without a restart is the hazard: QGIS keeps parts of the old
    # plugin loaded. A restart elsewhere in the guide does not cover it.
    text = GUIDE.read_text(encoding="utf-8")
    for heading in ("### Windows", "### Upgrading"):
        assert "restart qgis" in _section(text, heading).lower(), heading


def test_section_runs_to_the_next_heading_at_its_level_or_above():
    text = "## A\na\n### B\nb\n#### C\nc\n### D\nd\n"
    assert _section(text, "### B") == "b\n#### C\nc\n"
    assert _section(text, "## A") == "a\n### B\nb\n#### C\nc\n### D\nd\n"


def test_about_states_both_licences_and_the_changelog_names_this_version():
    g = _metadata()
    assert "GPL-2.0-or-later" in g["about"] and "MIT" in g["about"]
    assert g["version"] in g["changelog"]
