"""Loader for the per-page sources ledger, ``help_tools/sources/<step>.json``."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

SOURCES_DIR = Path(__file__).resolve().parent / "sources"
_EVIDENCE = ("read", "memory")


@dataclass(frozen=True)
class Source:
    id: str
    citation: str
    url: str | None
    checked_via: str
    checked_on: str
    note: str


@dataclass(frozen=True)
class ClaimEvidence:
    id: str
    page: str
    evidence: str
    look: str
    quote: str


@dataclass(frozen=True)
class Sources:
    sources: dict[str, Source]
    claims: dict[str, ClaimEvidence]


def load_sources(directory: Path = SOURCES_DIR) -> Sources:
    """Merge every ``*.json`` in ``directory``; raise ValueError listing every problem."""
    sources: dict[str, Source] = {}
    source_file: dict[str, str] = {}
    claims: dict[str, ClaimEvidence] = {}
    claim_file: dict[str, str] = {}
    problems: list[str] = []

    files = sorted(Path(directory).glob("*.json")) if Path(directory).is_dir() else []
    for path in files:
        name = path.name

        def bad(msg: str, name: str = name) -> None:
            problems.append(f"{name}: {msg}")

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            bad(f"not readable JSON ({exc})")
            continue
        if not isinstance(data, dict):
            bad("top level must be an object")
            continue
        for sid, raw in (data.get("sources") or {}).items():
            raw = raw if isinstance(raw, dict) else {}
            exists = raw.get("exists")
            exists = exists if isinstance(exists, dict) else {}
            if not str(raw.get("citation") or "").strip():
                bad(f"{sid}: citation is missing or empty")
            if not str(exists.get("checked_via") or "").strip():
                bad(f"{sid}: exists.checked_via is missing or empty")
            src = Source(
                id=sid,
                citation=str(raw.get("citation") or ""),
                url=raw.get("url"),
                checked_via=str(exists.get("checked_via") or ""),
                checked_on=str(exists.get("checked_on") or ""),
                note=str(exists.get("note") or ""),
            )
            if sid in sources and sources[sid] != src:
                bad(f"{sid}: differs from the copy in {source_file[sid]}")
            elif sid not in sources:
                sources[sid] = src
                source_file[sid] = name
        for cid, raw in (data.get("claims") or {}).items():
            raw = raw if isinstance(raw, dict) else {}
            evidence = raw.get("evidence")
            quote = str(raw.get("quote") or "")
            if evidence not in _EVIDENCE:
                bad(f"{cid}: evidence must be 'read' or 'memory', not {evidence!r}")
            elif evidence == "read" and not quote.strip():
                bad(f"{cid}: quote is required when evidence is 'read'")
            if cid in claims:
                bad(f"{cid}: claim id already declared in {claim_file[cid]}")
                continue
            claims[cid] = ClaimEvidence(
                id=cid,
                page=path.stem,
                evidence=str(evidence),
                look=str(raw.get("look") or ""),
                quote=quote,
            )
            claim_file[cid] = name
    if problems:
        raise ValueError("\n".join(problems))
    return Sources(sources, claims)
