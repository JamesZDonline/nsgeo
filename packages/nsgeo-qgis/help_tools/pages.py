"""Parse a help page and check it against the step registry and the sources ledger.

Dev-only and stdlib-only (html.parser). The markup it reads is the spec's section
6.3: `<section id>`, `data-param`, `data-claim` with `data-source`, `data-source` on
refs and outbound links, `<img>`, stylesheet `<link>`, `<script>`, and the first
`<p>` of `#plain`.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
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

# Elements whose edges separate words: text on either side must not run together.
_SPACED = {
    "br", "p", "li", "div", "section", "figure", "figcaption", "blockquote", "ul", "ol",
    "h1", "h2", "h3", "h4", "h5", "h6", "table", "tr", "td", "th", "thead", "tbody",
}  # fmt: skip

# MathML tokens get a space before them only, so a full stop after a formula stays attached.
_TOKENS = {"mi", "mn", "mo", "mtext"}

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


@dataclass(frozen=True)
class Ref:
    sources: tuple[str, ...]
    text: str


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
    refs: list[Ref] = field(default_factory=list)
    bare_refs: list[str] = field(default_factory=list)  # text of #refs <li> lacking data-source
    styles: int = 0  # <style> elements
    style_urls: list[str] = field(default_factory=list)  # style="" attributes containing url(
    remote_srcsets: list[str] = field(default_factory=list)  # remote <img>/<source> srcset entries
    remote_links: list[str] = field(default_factory=list)  # remote <link href>, other than sheets


def _collapse(parts: list[str]) -> str:
    return re.sub(r"\s+", " ", "".join(parts)).strip()


class _Entry:
    """An open element. `buf` collects its text when something wants it."""

    __slots__ = ("tag", "section", "buf", "kinds", "attrs")

    def __init__(self, tag, section=None):
        self.tag = tag
        self.section = section
        self.buf: list[str] | None = None
        self.kinds: set[str] = set()  # an element can be a claim, a link and the plain lede
        self.attrs: dict[str, dict] = {}


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[_Entry] = []
        self.section_ids: list[str] = []
        self.params: list[str] = []
        self.claims: list[Claim] = []
        self.links: list[Link] = []
        self.ref_sources: list[str] = []
        self.refs: list[Ref] = []
        self.bare_refs: list[str] = []
        self.styles = 0
        self.style_urls: list[str] = []
        self.remote_srcsets: list[str] = []
        self.remote_links: list[str] = []
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
        if e.buf is None:
            return
        text = _collapse(e.buf)
        if "claim" in e.kinds:
            c = e.attrs["claim"]
            self.claims.append(Claim(c["id"], tuple(c["source"].split()), text, c["section"]))
        if "link" in e.kinds:
            k = e.attrs["link"]
            self.links.append(Link(k["href"], k["source"], text, k["section"]))
        if "ref" in e.kinds:
            self.refs.append(Ref(tuple(e.attrs["ref"]["source"].split()), text))
        if "bareref" in e.kinds:
            self.bare_refs.append(text)
        if "plain" in e.kinds:
            self.plain_text = text

    def _space(self) -> None:
        for e in self.stack:
            if e.buf is not None:
                e.buf.append(" ")

    def handle_startendtag(self, tag, attrs) -> None:
        self._start(tag, attrs, push=False)

    def handle_starttag(self, tag, attrs) -> None:
        self._start(tag, attrs, push=tag not in _VOID)

    def _start(self, tag: str, attrs, push: bool) -> None:
        a = {k: (v or "") for k, v in attrs}
        if tag in _SPACED or tag in _TOKENS:
            self._space()
        if tag in ("section", "p"):
            tags = [e.tag for e in self.stack]
            if "p" in tags:
                self._pop_to(len(tags) - 1 - tags[::-1].index("p"))
        entry = _Entry(tag)
        if tag == "section" and a.get("id"):
            entry.section = a["id"]
            self.section_ids.append(a["id"])
        section = entry.section or self._section()
        if "data-param" in a and "settings" in (*self._open_sections(), entry.section):
            self.params.append(a["data-param"])
        if "data-claim" in a:
            entry.kinds.add("claim")
            entry.attrs["claim"] = {
                "id": a["data-claim"],
                "source": a.get("data-source", ""),
                "section": section,
            }
        if tag == "a" and a.get("href", "").lower().startswith(("http://", "https://")):
            entry.kinds.add("link")
            entry.attrs["link"] = {
                "href": a["href"],
                "source": a.get("data-source") or None,
                "section": section,
            }
        if tag == "p" and not self._plain_done and "plain" in self._open_sections():
            self._plain_done = True
            entry.kinds.add("plain")
        if entry.kinds:
            entry.buf = []
        is_ref_item = tag != "a" and "claim" not in entry.kinds and "refs" in self._open_sections()
        if is_ref_item and "data-source" in a:
            self.ref_sources.extend(a["data-source"].split())
            entry.kinds.add("ref")
            entry.attrs["ref"] = {"source": a["data-source"]}
            entry.buf = []
        bare = tag == "li" and "data-source" not in a and "claim" not in entry.kinds
        if bare and "refs" in self._open_sections():
            entry.kinds.add("bareref")
            entry.buf = []
        if tag == "img" and "src" in a:
            self.images.append(a["src"])
        elif tag == "link" and "stylesheet" in a.get("rel", "").lower().split():
            self.stylesheets.append(a.get("href", ""))
        elif tag == "link" and _is_remote(a.get("href", "").strip()):
            self.remote_links.append(a["href"])
        elif tag == "script":
            self.scripts += 1
        elif tag == "style":
            self.styles += 1
        if "url(" in a.get("style", "").lower():
            self.style_urls.append(a["style"])
        if tag in ("img", "source") and a.get("srcset"):
            for cand in a["srcset"].split(","):
                url = cand.strip().split(" ")[0]
                if url and _is_remote(url):
                    self.remote_srcsets.append(url)
        if push:
            self.stack.append(entry)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SPACED:
            self._space()
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
        refs=parser.refs,
        bare_refs=parser.bare_refs,
        styles=parser.styles,
        style_urls=parser.style_urls,
        remote_srcsets=parser.remote_srcsets,
        remote_links=parser.remote_links,
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
    if page.styles:
        bad(f"{page.styles} <style> element(s); the only stylesheet is style.css")
    for style in page.style_urls:
        bad(f"a style attribute loads a url: {style[:60]!r}")
    for url in page.remote_srcsets:
        bad(f"srcset entry '{url}' is remote")
    for href in page.remote_links:
        bad(f"<link href='{href}'> is remote")
    for src in page.images:
        if _is_remote(src):
            bad(f"image '{src}' is remote")
        elif not (Path(help_dir) / src).is_file():
            bad(f"image '{src}' does not exist in {help_dir}")

    for link in page.links:
        if link.source is None:
            bad(f"link '{link.href}' has no data-source")

    for text in page.bare_refs:
        bad(f"a #refs entry has no data-source: {text[:60]!r}")

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


def check_images(help_dir: Path, pages: list[PageInfo]) -> list[str]:
    """PNGs in `help/img/` that no page references."""
    help_dir = Path(help_dir)
    used = {(help_dir / src).resolve() for p in pages for src in p.images if not _is_remote(src)}
    return [
        f"img/{png.name} is not used by any page"
        for png in sorted((help_dir / "img").glob("*.png"))
        if png.resolve() not in used
    ]


_CSS_URL = re.compile(r"url\(\s*['\"]?([^)'\"]+)", re.I)
_CSS_IMPORT = re.compile(r"@import\s+['\"]?([^'\";)\s]+)", re.I)


def check_stylesheet(help_dir: Path) -> list[str]:
    """Remote `url(...)` or `@import` in `style.css`; pages are offline."""
    css = (Path(help_dir) / "style.css").read_text(encoding="utf-8")
    refs = [m.group(1).strip() for m in _CSS_URL.finditer(css)]
    refs += [m.group(1).strip() for m in _CSS_IMPORT.finditer(css)]
    return [f"style.css: '{r}' is remote" for r in dict.fromkeys(refs) if _is_remote(r)]
