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

# An inline `[text](target)` / `![alt](target)` link, or a reference
# definition `[label]: target` on a line of its own.
_INLINE_LINK = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_REFERENCE_LINK = re.compile(r"^\s*\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)", re.MULTILINE)
_ABSOLUTE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")  # https:, mailto:, ...


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


def _relative_links(doc: Path) -> list[str]:
    text = doc.read_text(encoding="utf-8")
    targets = _INLINE_LINK.findall(text) + _REFERENCE_LINK.findall(text)
    return [t for t in targets if not _ABSOLUTE.match(t) and not t.startswith("#")]


def test_release_notes_exist_for_the_metadata_version_and_link_the_guide():
    notes = _notes().read_text(encoding="utf-8")
    assert "docs/guide/getting-started.md" in notes and "experimental" in notes.lower()


def test_every_relative_link_in_the_user_docs_resolves():
    docs = [README, GUIDE, *sorted((REPO / "docs" / "releases").glob("*.md"))]
    assert _notes() in docs
    broken = []
    for doc in docs:
        for target in _relative_links(doc):
            path = target.split("#", 1)[0]
            if path and not (doc.parent / path).exists():
                broken.append(f"{doc.relative_to(REPO)}: {target}")
    assert broken == []
    # Not vacuous: the README's Install section links the guide relatively.
    assert "docs/guide/getting-started.md" in _relative_links(README)


def test_known_issues_are_disclosed_in_notes_and_guide():
    for doc in (_notes(), GUIDE):
        text = doc.read_text(encoding="utf-8")
        for n in ISSUES:
            assert n in text, (doc.name, n)


def test_the_guide_says_to_restart_qgis_after_installing():
    assert "restart qgis" in GUIDE.read_text(encoding="utf-8").lower()


def test_about_states_both_licences_and_the_changelog_names_this_version():
    g = _metadata()
    assert "GPL-2.0-or-later" in g["about"] and "MIT" in g["about"]
    assert g["version"] in g["changelog"]
