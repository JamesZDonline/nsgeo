"""The sources ledger: every claim and link of every help page, for the checking page.

Dev-only. `python -m help_tools.ledger --html OUT` (run from `packages/nsgeo-qgis`) writes
the checking page with the ledger embedded.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from nsgeo_qgis.help_pages import HELP_DIR

from help_tools.pages import parse_page
from help_tools.sources import SOURCES_DIR, Sources, load_sources

TEMPLATE = Path(__file__).resolve().parent / "checking_page.html"
TOKEN = "/*__LEDGER__*/null"


def build_ledger(help_dir: Path, sources: Sources) -> dict:
    """Items in page-name order, then document order; links once per (page, source)."""
    items: list[dict] = []
    for path in sorted(Path(help_dir).glob("*.html")):
        page = parse_page(path)
        for claim in page.claims:
            ev = sources.claims.get(claim.id)
            items.append(
                {
                    "id": claim.id,
                    "kind": "claim",
                    "page": page.name,
                    "section": claim.section,
                    "text": claim.text,
                    "sources": list(claim.sources),
                    "evidence": ev.evidence if ev else "",
                    "look": ev.look if ev else "",
                    "quote": ev.quote if ev else "",
                }
            )
        by_source: dict[str, dict] = {}
        for link in page.links:
            if not link.source:
                continue
            item = by_source.get(link.source)
            if item is None:
                item = by_source[link.source] = {
                    "id": f"link-{page.name}-{link.source}",
                    "kind": "link",
                    "page": page.name,
                    "section": link.section,
                    "text": link.text,
                    "sources": [link.source],
                    "hrefs": [link.href],
                }
                items.append(item)
            else:
                if link.text not in item["text"].split(" | "):
                    item["text"] += f" | {link.text}"
                if link.href not in item["hrefs"]:
                    item["hrefs"].append(link.href)
    return {
        "items": items,
        "sources": {
            sid: {
                "citation": s.citation,
                "url": s.url,
                "checked_via": s.checked_via,
                "checked_on": s.checked_on,
                "note": s.note,
            }
            for sid, s in sources.sources.items()
        },
    }


def render_checking_page(ledger: dict, template: Path) -> str:
    """Put the ledger JSON where the template's single token is; `</` becomes `<\\/`."""
    text = Path(template).read_text(encoding="utf-8")
    if text.count(TOKEN) != 1:
        raise ValueError(f"{template} must hold exactly one {TOKEN} token")
    data = json.dumps(ledger, ensure_ascii=False, indent=1).replace("</", "<\\/")
    return text.replace(TOKEN, data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="help_tools.ledger", description=__doc__)
    parser.add_argument("--html", required=True, type=Path, help="where to write the page")
    args = parser.parse_args(argv)
    ledger = build_ledger(HELP_DIR, load_sources(SOURCES_DIR))
    args.html.parent.mkdir(parents=True, exist_ok=True)
    args.html.write_text(render_checking_page(ledger, TEMPLATE), encoding="utf-8")
    print(f"{len(ledger['items'])} items, {len(ledger['sources'])} sources -> {args.html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
