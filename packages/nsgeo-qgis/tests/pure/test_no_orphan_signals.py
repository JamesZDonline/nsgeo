"""Spec §6: every declared signal has a consumer.

Plan 2 shipped three APIs with no consumer at all. The cost was not
theoretical: a manual tester went looking for a pick mode, found
`ProfileView.set_pick_mode`, and concluded the build was wrong rather than
that the feature was unbuilt.

A signal with no consumer reads exactly like a working feature from the
emitting side, so the check is to look for the `connect`, never the
`emit`. This lives in the pure tier because it reads source text and needs
no QGIS.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "nsgeo_qgis"

# Declared with no consumer anywhere, each with the reason it survives.
# Anything NOT listed here must have a connect.
#
# NOTE: spec §1's orphan table is incomplete and partly wrong. It lists
# three orphans; the real set is the four below, and `pick_requested` --
# which it lists -- is NOT a name-level orphan at all (see
# test_profile_docks_pick_signal_is_still_unconsumed).
KNOWN_UNCONSUMED = {
    # Adopted by M8, the pick tool (spec §4.1): session.add_pick emits it.
    "picks_changed",
    # Dead API from Plan 2: plugin.py's toolbar actions do New, Open and
    # Save, and SurveyDock's own signals for them were never wired to
    # anything. Deleting them is Plan 2 cleanup, not M7 work -- pulling it
    # in here is the scope creep the 3-6 task rule exists to prevent.
    "new_site_requested",
    "open_site_requested",
    "save_requested",
}


def _sources() -> dict[Path, str]:
    return {p: p.read_text(encoding="utf-8") for p in sorted(PACKAGE.rglob("*.py"))}


def _declared_signals(sources: dict[Path, str]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path, text in sources.items():
        for node in ast.walk(ast.parse(text, filename=str(path))):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            func = node.value.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name != "pyqtSignal":
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = path
    return found


def _connect_count(blob: str, name: str) -> int:
    return len(re.findall(rf"\.{re.escape(name)}\s*\.connect\s*\(", blob))


def test_every_declared_signal_has_a_connect() -> None:
    sources = _sources()
    blob = "\n".join(sources.values())
    orphans = {
        name: path.name
        for name, path in _declared_signals(sources).items()
        if name not in KNOWN_UNCONSUMED and not _connect_count(blob, name)
    }
    assert not orphans, (
        "signals declared with no consumer anywhere in the plugin: "
        f"{orphans}. A signal nothing connects to reads like a working "
        "feature from the emitting side. Either connect it, delete it, or "
        "-- if a later milestone adopts it -- add it to KNOWN_UNCONSUMED "
        "with the reason."
    )


def test_the_known_unconsumed_signals_are_still_unconsumed() -> None:
    """Keeps KNOWN_UNCONSUMED honest: once one is connected it must leave
    the list, or the list stops being a to-do and becomes a permanent
    exemption nobody rereads."""
    blob = "\n".join(_sources().values())
    stale = [name for name in KNOWN_UNCONSUMED if _connect_count(blob, name)]
    assert not stale, f"now consumed -- remove from KNOWN_UNCONSUMED: {stale}"


def test_profile_docks_pick_signal_is_still_unconsumed() -> None:
    """`pick_requested` is declared TWICE -- on ProfileView and on
    ProfileDock -- and only ProfileView's is connected (profile_dock.py
    wires it to `_pick`). A name-keyed check cannot tell them apart, so
    ProfileDock's, which is the real orphan, would be invisible to the
    test above and listing it in KNOWN_UNCONSUMED would make the honesty
    test fail outright.

    Pin the count instead. M8 connecting ProfileDock's signal to
    `session.add_pick` makes it two and trips this test -- which is
    exactly the notification an allowlist entry would have given.
    """
    blob = "\n".join(_sources().values())
    assert _connect_count(blob, "pick_requested") == 1, (
        "the pick_requested connect count changed. If M8 wired "
        "ProfileDock.pick_requested to session.add_pick, that is the "
        "orphan being adopted: raise the expected count to 2 and say so."
    )
