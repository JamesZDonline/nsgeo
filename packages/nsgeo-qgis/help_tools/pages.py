"""Parse a help page and check it against the step registry and the sources ledger.

Dev-only and stdlib-only (html.parser). The markup it reads is the spec's section
6.3: `<section id>`, `data-param`, `data-claim` with `data-source`, `data-source` on
refs and outbound links, `<img>`, stylesheet `<link>`, `<script>`, and the first
`<p>` of `#plain`.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from nsgeo.processing import get_step

from help_tools.readability import FK_LIMIT, fk_grade
from help_tools.sources import Sources

SECTIONS = ("plain", "pictures", "method", "settings", "know", "nsgeo", "refs")

FAMILIES: dict[str, tuple[str, ...]] = {
    "gains": ("gain_agc", "gain_parametric", "gain_curve"),
    "background": ("background_mean", "background_sliding", "background_svd"),
    "amplitude": ("amp_abs", "amp_square", "amp_envelope"),
}

_VOID = {"img", "link", "meta", "br", "hr", "input", "mspace", "area", "base", "col", "wbr"}


def expected_sections(step_name: str) -> list[str]:
    """The section ids a step's page must have, in order."""
    out = list(SECTIONS)
    if any(step_name in names for names in FAMILIES.values()):
        out.insert(out.index("nsgeo"), "related")
    return out


@dataclass(frozen=True)
class Claim:
    id: str
    sources: tuple[str, ...]
    text: str
    section: str


@dataclass(frozen=True)
class Link:
    href: str
    source: str | None
    text: str
    section: str


@dataclass
class PageInfo:
    name: str
    section_ids: list[str]
    params: list[str]
    claims: list[Claim]
    links: list[Link]
    ref_sources: list[str]
    images: list[str]
    stylesheets: list[str]
    scripts: int
    plain_text: str


def _collapse(parts: list[str]) -> str:
    return re.sub(r"\s+", " ", "".join(parts)).strip()


class _Entry:
    """An open element. `buf` collects its text when something wants it."""

    __slots__ = ("tag", "section", "buf", "kind", "attrs")

    def __init__(self, tag, section=None, buf=None, kind=None, attrs=None):
        self.tag = tag
        self.section = section
        self.buf = buf
        self.kind = kind
        self.attrs = attrs or {}


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[_Entry] = []
        self.section_ids: list[str] = []
        self.params: list[str] = []
        self.claims: list[Claim] = []
        self.links: list[Link] = []
        self.ref_sources: list[str] = []
        self.images: list[str] = []
        self.stylesheets: list[str] = []
        self.scripts = 0
        self.plain_text = ""
        self._plain_done = False

    def _open_sections(self) -> list[str]:
        return [e.section for e in self.stack if e.section]

    def _section(self) -> str:
        secs = self._open_sections()
        return secs[-1] if secs else ""

    def _pop_to(self, index: int) -> None:
        while len(self.stack) > index:
            self._finish(self.stack.pop())

    def _finish(self, e: _Entry) -> None:
        if e.kind == "claim":
            self.claims.append(
                Claim(
                    e.attrs["id"],
                    tuple(e.attrs["source"].split()),
                    _collapse(e.buf),
                    e.attrs["section"],
                )
            )
        elif e.kind == "link":
            self.links.append(
                Link(e.attrs["href"], e.attrs["source"], _collapse(e.buf), e.attrs["section"])
            )
        elif e.kind == "plain":
            self.plain_text = _collapse(e.buf)

    def handle_startendtag(self, tag, attrs) -> None:
        self._start(tag, attrs, push=False)

    def handle_starttag(self, tag, attrs) -> None:
        self._start(tag, attrs, push=tag not in _VOID)

    def _start(self, tag: str, attrs, push: bool) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag in ("section", "p"):
            tags = [e.tag for e in self.stack]
            if "p" in tags:
                self._pop_to(len(tags) - 1 - tags[::-1].index("p"))
        entry = _Entry(tag, attrs=None)
        if tag == "section" and a.get("id"):
            entry.section = a["id"]
            self.section_ids.append(a["id"])
        section = entry.section or self._section()
        if "data-param" in a and "settings" in (*self._open_sections(), entry.section):
            self.params.append(a["data-param"])
        if "data-claim" in a:
            entry.kind = "claim"
            entry.buf = []
            entry.attrs = {
                "id": a["data-claim"],
                "source": a.get("data-source", ""),
                "section": section,
            }
        elif tag == "a" and a.get("href", "").lower().startswith(("http://", "https://")):
            entry.kind = "link"
            entry.buf = []
            entry.attrs = {
                "href": a["href"],
                "source": a.get("data-source") or None,
                "section": section,
            }
        elif tag == "p" and not self._plain_done and "plain" in self._open_sections():
            self._plain_done = True
            entry.kind = "plain"
            entry.buf = []
        is_ref_item = tag != "a" and entry.kind != "claim" and "refs" in self._open_sections()
        if is_ref_item and "data-source" in a:
            self.ref_sources.extend(a["data-source"].split())
        if tag == "img" and "src" in a:
            self.images.append(a["src"])
        elif tag == "link" and "stylesheet" in a.get("rel", "").lower().split():
            self.stylesheets.append(a.get("href", ""))
        elif tag == "script":
            self.scripts += 1
        if push:
            self.stack.append(entry)

    def handle_endtag(self, tag: str) -> None:
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i].tag == tag:
                self._pop_to(i)
                return

    def handle_data(self, data: str) -> None:
        for e in self.stack:
            if e.buf is not None:
                e.buf.append(data)

    def close(self) -> None:
        super().close()
        self._pop_to(0)


def parse_page(path: Path) -> PageInfo:
    """Read one help page. Tolerates MathML, entities and unclosed `<p>`."""
    path = Path(path)
    parser = _PageParser()
    parser.feed(path.read_text(encoding="utf-8"))
    parser.close()
    return PageInfo(
        name=path.stem,
        section_ids=parser.section_ids,
        params=parser.params,
        claims=parser.claims,
        links=parser.links,
        ref_sources=parser.ref_sources,
        images=parser.images,
        stylesheets=parser.stylesheets,
        scripts=parser.scripts,
        plain_text=parser.plain_text,
    )


def _is_remote(ref: str) -> bool:
    return bool(re.match(r"^([a-zA-Z][a-zA-Z0-9+.-]*:|//)", ref))


def check_page(page: PageInfo, help_dir: Path, sources: Sources) -> list[str]:
    """Every contract problem on one page; an empty list means it passes."""
    out: list[str] = []

    def bad(msg: str) -> None:
        out.append(f"{page.name}: {msg}")

    want = expected_sections(page.name)
    if page.section_ids != want:
        missing = [s for s in want if s not in page.section_ids]
        extra = [s for s in page.section_ids if s not in want]
        detail = f"; missing {missing}" if missing else ""
        detail += f"; unexpected {extra}" if extra else ""
        bad(f"sections are {page.section_ids}, expected {want}{detail}")

    try:
        schema = [p.name for p in get_step(page.name).schema()]
    except (KeyError, ValueError) as exc:
        bad(f"no registered step of that name ({exc})")
        schema = None
    if schema is not None:
        for name in schema:
            if name not in page.params:
                bad(f"setting '{name}' has no data-param block")
        for name in page.params:
            if name not in schema:
                bad(f"data-param '{name}' is not a setting of the step")

    if page.scripts:
        bad(f"{page.scripts} <script> element(s); pages are offline")
    if page.stylesheets != ["style.css"]:
        bad(f"stylesheets are {page.stylesheets}, expected ['style.css']")
    for src in page.images:
        if _is_remote(src):
            bad(f"image '{src}' is remote")
        elif not (Path(help_dir) / src).is_file():
            bad(f"image '{src}' does not exist in {help_dir}")

    for link in page.links:
        if link.source is None:
            bad(f"link '{link.href}' has no data-source")

    known = sources.sources
    used = [(f"claim '{c.id}'", s) for c in page.claims for s in c.sources]
    used += [(f"link '{lk.href}'", lk.source) for lk in page.links if lk.source]
    used += [("refs", s) for s in page.ref_sources]
    for where, sid in used:
        if sid not in known:
            bad(f"{where} cites source '{sid}', which is not in the sources ledger")

    for c in page.claims:
        if not c.sources:
            bad(f"claim '{c.id}' has no data-source")
        entry = sources.claims.get(c.id)
        if entry is None:
            bad(f"claim '{c.id}' is not in the sources ledger")
        elif entry.page != page.name:
            bad(f"claim '{c.id}' is declared in {entry.page}'s sources file, not this page's")

    if not page.plain_text:
        bad("the #plain section has no first paragraph text")
    else:
        grade = fk_grade(page.plain_text)
        if grade > FK_LIMIT:
            bad(f"the #plain paragraph reads at grade {grade:.1f}, above {FK_LIMIT}")
    return out


def check_site(pages: list[PageInfo], sources: Sources) -> list[str]:
    """Cross-page problems: reused claim ids, unused sources, orphaned claims."""
    out: list[str] = []
    uses: dict[str, list[str]] = {}
    for page in pages:
        for c in page.claims:
            uses.setdefault(c.id, []).append(page.name)
    for cid, where in sorted(uses.items()):
        if len(where) > 1:
            counts = ", ".join(f"{n} x{k}" if k > 1 else n for n, k in Counter(where).items())
            out.append(f"sources: claim '{cid}' is used more than once ({counts})")
    cited = {s for p in pages for c in p.claims for s in c.sources}
    cited |= {lk.source for p in pages for lk in p.links if lk.source}
    cited |= {s for p in pages for s in p.ref_sources}
    for sid in sorted(set(sources.sources) - cited):
        out.append(f"sources: source '{sid}' is not used by any page")
    for cid in sorted(set(sources.claims) - set(uses)):
        out.append(f"sources: claim '{cid}' is in the ledger but on no page")
    return out
