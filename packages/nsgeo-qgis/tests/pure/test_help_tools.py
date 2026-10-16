from __future__ import annotations

import json

import pytest
from help_tools.readability import fk_grade, syllables
from help_tools.sources import Sources, load_sources

MEMORY = {"evidence": "memory", "look": "x", "quote": ""}
OK_SOURCE = {
    "citation": "C",
    "url": None,
    "exists": {"checked_via": "u", "checked_on": "d", "note": ""},
}


def write(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")


@pytest.mark.parametrize(
    "word,n",
    [("the", 1), ("time", 1), ("water", 2), ("radar", 2), ("table", 2), ("average", 3), ("a", 1)],
)
def test_syllables(word, n):
    assert syllables(word) == n


def test_fk_grade_is_the_published_formula():
    # 6 words, 1 sentence, 6 syllables -> 0.39*6 + 11.8*1 - 15.59
    assert fk_grade("The cat sat on the mat.") == pytest.approx(-1.45)


def test_fk_grade_counts_sentences():
    # 6 words, 2 sentences, 6 syllables -> 0.39*3 + 11.8 - 15.59
    assert fk_grade("The cat sat. The dog ran.") == pytest.approx(-2.62)


def test_load_sources_reports_every_problem_at_once(tmp_path):
    bad = {
        "sources": {"x": {"citation": "", "url": None, "exists": {}}},
        "claims": {
            "c1": {"evidence": "guess", "look": "", "quote": ""},
            "c2": {"evidence": "read", "look": "p. 3", "quote": ""},
        },
    }
    write(tmp_path / "dewow.json", bad)
    with pytest.raises(ValueError) as e:
        load_sources(tmp_path)
    msg = str(e.value)
    for needle in ("x: citation", "x: exists.checked_via", "c1: evidence", "c2: quote"):
        assert needle in msg
    lines = msg.splitlines()
    assert len(lines) == 4
    assert all(line.startswith("dewow.json") for line in lines)


def test_shared_sources_merge_and_conflicts_are_named(tmp_path):
    write(tmp_path / "a.json", {"sources": {"s": OK_SOURCE}, "claims": {"a-1": MEMORY}})
    write(tmp_path / "b.json", {"sources": {"s": OK_SOURCE}, "claims": {"b-1": MEMORY}})
    merged = load_sources(tmp_path)
    assert set(merged.sources) == {"s"} and merged.claims["b-1"].page == "b"
    write(
        tmp_path / "b.json",
        {"sources": {"s": {**OK_SOURCE, "citation": "D"}}, "claims": {"a-1": MEMORY}},
    )
    with pytest.raises(ValueError) as e:
        load_sources(tmp_path)
    assert "s" in str(e.value) and "a.json" in str(e.value) and "b.json" in str(e.value)
    assert "a-1" in str(e.value)  # the duplicated claim id is named too


def test_empty_or_missing_directory_loads_empty(tmp_path):
    assert load_sources(tmp_path) == Sources({}, {})
    assert load_sources(tmp_path / "nope") == Sources({}, {})


def test_read_claim_with_a_quote_is_accepted(tmp_path):
    claim = {"evidence": "read", "look": "p. 3", "quote": "wow"}
    write(tmp_path / "p.json", {"sources": {"s": OK_SOURCE}, "claims": {"c": claim}})
    assert load_sources(tmp_path).claims["c"].quote == "wow"


def test_the_committed_sources_load():
    assert isinstance(load_sources(), Sources)


def test_a_source_conflict_alone_is_an_error(tmp_path):
    write(tmp_path / "a.json", {"sources": {"s": OK_SOURCE}, "claims": {}})
    write(tmp_path / "b.json", {"sources": {"s": {**OK_SOURCE, "citation": "D"}}, "claims": {}})
    with pytest.raises(ValueError) as e:
        load_sources(tmp_path)
    assert "s" in str(e.value) and "a.json" in str(e.value) and "b.json" in str(e.value)
