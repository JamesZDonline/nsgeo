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
    write(tmp_path / "a.json", {"sources": {"cassidy2009": OK_SOURCE}, "claims": {"a-1": MEMORY}})
    write(tmp_path / "b.json", {"sources": {"cassidy2009": OK_SOURCE}, "claims": {"b-1": MEMORY}})
    merged = load_sources(tmp_path)
    assert set(merged.sources) == {"cassidy2009"} and merged.claims["b-1"].page == "b"
    write(
        tmp_path / "b.json",
        {"sources": {"cassidy2009": {**OK_SOURCE, "citation": "D"}}, "claims": {"a-1": MEMORY}},
    )
    with pytest.raises(ValueError) as e:
        load_sources(tmp_path)
    msg = str(e.value)
    assert "b.json: cassidy2009: differs" in msg and "a.json" in msg
    assert "a-1" in msg


def test_empty_or_missing_directory_loads_empty(tmp_path):
    assert load_sources(tmp_path) == Sources({}, {})
    assert load_sources(tmp_path / "nope") == Sources({}, {})


def test_read_claim_with_a_quote_is_accepted(tmp_path):
    claim = {"evidence": "read", "look": "p. 3", "quote": "wow"}
    write(tmp_path / "p.json", {"sources": {"cassidy2009": OK_SOURCE}, "claims": {"c": claim}})
    assert load_sources(tmp_path).claims["c"].quote == "wow"


def test_the_committed_sources_load():
    assert isinstance(load_sources(), Sources)


def test_a_source_conflict_alone_is_an_error(tmp_path):
    write(tmp_path / "a.json", {"sources": {"cassidy2009": OK_SOURCE}, "claims": {}})
    write(
        tmp_path / "b.json",
        {"sources": {"cassidy2009": {**OK_SOURCE, "citation": "D"}}, "claims": {}},
    )
    with pytest.raises(ValueError) as e:
        load_sources(tmp_path)
    msg = str(e.value)
    assert "b.json: cassidy2009: differs" in msg and "a.json" in msg


def test_a_non_object_section_is_reported_with_the_other_files_problems(tmp_path):
    write(tmp_path / "a.json", {"sources": ["x"], "claims": {}})
    write(tmp_path / "b.json", {"sources": {}, "claims": {"c1": {**MEMORY, "evidence": "guess"}}})
    write(tmp_path / "c.json", {"sources": {}, "claims": "x"})
    with pytest.raises(ValueError) as e:
        load_sources(tmp_path)
    msg = str(e.value)
    assert "a.json: sources: must be an object" in msg
    assert "b.json: c1: evidence" in msg
    assert "c.json: claims: must be an object" in msg


# --- the page contract checker -------------------------------------------------------------

from dataclasses import replace  # noqa: E402

from help_fixtures import PLAIN as PLAIN_TEXT  # noqa: E402
from help_fixtures import valid_sources, write_valid_help  # noqa: E402
from help_tools.pages import (  # noqa: E402
    FAMILIES,
    SECTIONS,
    check_page,
    check_site,
    expected_sections,
    parse_page,
)


def problems_for(tmp_path, edits=(), name="dewow", sources=None):
    path = write_valid_help(tmp_path, name=name, edits=tuple(edits))
    return check_page(parse_page(path), tmp_path, sources or valid_sources())


def test_a_valid_page_has_no_problems(tmp_path):
    assert problems_for(tmp_path) == []


def test_expected_sections_add_related_for_the_family_steps():
    assert expected_sections("dewow") == list(SECTIONS)
    for names in FAMILIES.values():
        for n in names:
            assert expected_sections(n) == [*SECTIONS[:5], "related", *SECTIONS[5:]]
    assert sorted(FAMILIES) == ["amplitude", "background", "gains"]
    assert sum(len(v) for v in FAMILIES.values()) == 9


def test_parse_page_reads_the_valid_page(tmp_path):
    page = parse_page(write_valid_help(tmp_path))
    assert page.name == "dewow"
    assert page.section_ids == list(SECTIONS)
    assert page.params == ["window_ns"]
    assert [(c.id, c.sources, c.section) for c in page.claims] == [
        ("t-claim", ("t-src",), "method")
    ]
    assert [(link.href, link.source, link.section) for link in page.links] == [
        ("https://example.org/a", "t-src", "method")
    ]
    assert page.ref_sources == ["t-src"]
    assert page.images == ["img/t.png"]
    assert page.stylesheets == ["style.css"]
    assert page.scripts == 0
    assert page.plain_text.startswith("The signal drifts.")


def test_missing_section_is_named(tmp_path):
    cut = ('<section id="know"><h2>Know</h2><ul><li>One thing.</li></ul></section>\n', "")
    problems = problems_for(tmp_path, [cut])
    assert any("missing ['know']" in p for p in problems)


def test_swapped_sections_are_reported(tmp_path):
    a = '<section id="method">'
    b = '<section id="settings">'
    problems = problems_for(tmp_path, [(a, "<section id='X'>"), (b, a), ("<section id='X'>", b)])
    assert any("sections" in p for p in problems)


def test_missing_data_param_names_the_setting(tmp_path):
    problems = problems_for(tmp_path, [(' data-param="window_ns"', "")])
    assert any("window_ns" in p for p in problems)


def test_unknown_data_param_names_it(tmp_path):
    problems = problems_for(
        tmp_path, [("</div></section>", '<p data-param="bogus">x</p></div></section>')]
    )
    assert any("bogus" in p for p in problems)


def test_script_is_reported(tmp_path):
    problems = problems_for(tmp_path, [("</main>", "<script>1</script></main>")])
    assert any("script" in p for p in problems)


def test_remote_stylesheet_is_named(tmp_path):
    link = '<link rel="stylesheet" href="https://cdn.example/x.css">'
    problems = problems_for(tmp_path, [("</head>", link + "</head>")])
    assert any("https://cdn.example/x.css" in p for p in problems)


def test_missing_image_is_named(tmp_path):
    problems = problems_for(tmp_path, [('src="img/t.png"', 'src="img/gone.png"')])
    assert any("img/gone.png" in p for p in problems)


def test_remote_image_is_named(tmp_path):
    problems = problems_for(tmp_path, [('src="img/t.png"', 'src="https://x.org/i.png"')])
    assert any("https://x.org/i.png" in p for p in problems)


def test_outbound_link_without_source_is_named(tmp_path):
    problems = problems_for(tmp_path, [("</main>", '<p><a href="https://x.org">x</a></p></main>')])
    assert any("https://x.org" in p for p in problems)


def test_unknown_source_is_named_on_claim_link_and_ref(tmp_path):
    for old in (
        '<p data-claim="t-claim" data-source="t-src">',
        '" data-source="t-src">A link',
        '<li data-source="t-src">',
    ):
        bad = old.replace("t-src", "nope")
        problems = problems_for(tmp_path, [(old, bad)])
        assert any("nope" in p for p in problems), old


def test_claim_missing_from_the_ledger_is_named(tmp_path):
    src = replace(valid_sources(), claims={})
    problems = problems_for(tmp_path, sources=src)
    assert any("t-claim" in p for p in problems)


def test_claim_declared_for_another_page_is_named(tmp_path):
    problems = problems_for(tmp_path, sources=valid_sources(claim_page="gain_agc"))
    assert any("t-claim" in p and "gain_agc" in p for p in problems)


def test_claim_with_no_source_is_named(tmp_path):
    problems = problems_for(
        tmp_path, [('<p data-claim="t-claim" data-source="t-src">', '<p data-claim="t-claim">')]
    )
    assert any("t-claim" in p for p in problems)


def test_hard_plain_paragraph_reports_its_grade(tmp_path):
    hard = (
        "Notwithstanding electromagnetic heterogeneity, geophysicists characteristically "
        "reconstruct subsurface archaeological configurations through computationally "
        "intensive deconvolution procedures, notwithstanding considerable methodological "
        "uncertainty regarding instrumentation"
    )
    problems = problems_for(tmp_path, [(PLAIN_TEXT, hard)])
    assert any("grade" in p and f"{fk_grade(hard):.1f}" in p for p in problems)


def test_missing_or_empty_plain_paragraph_is_reported(tmp_path):
    for edit in [(f"<p>{PLAIN_TEXT}</p>", ""), (f"<p>{PLAIN_TEXT}</p>", "<p>  </p>")]:
        problems = problems_for(tmp_path, [edit])
        assert any("plain" in p for p in problems), edit


def test_family_step_without_related_is_reported(tmp_path):
    problems = problems_for(tmp_path, name="gain_agc", sources=valid_sources("gain_agc"))
    assert any("related" in p for p in problems)


def test_every_problem_starts_with_the_page_name(tmp_path):
    problems = problems_for(tmp_path, [("</main>", "<script></script></main>")])
    assert problems and all(p.startswith("dewow: ") for p in problems)


def test_parser_survives_mathml_entities_and_an_unclosed_p(tmp_path):
    path = write_valid_help(
        tmp_path,
        edits=(
            (
                "<p>It runs.</p>",
                '<p>It runs. <math display="block"><mi>x</mi><mo>&lt;</mo>'
                '<mfrac><mn>1</mn><mi>y</mi></mfrac><mspace width="1em"></mspace></math>'
                "<p>never closed",
            ),
            ("Wow and flutter.", "Wow &amp; flutter."),
        ),
    )
    page = parse_page(path)
    assert page.section_ids == list(SECTIONS)
    assert page.params == ["window_ns"]
    assert page.claims[0].text == "Wow & flutter. A link"
    assert page.ref_sources == ["t-src"]


def test_claim_text_is_whitespace_collapsed(tmp_path):
    path = write_valid_help(tmp_path, edits=(("Wow and flutter.", "Wow\n   &amp;   flutter."),))
    assert parse_page(path).claims[0].text.startswith("Wow & flutter.")


def _site(tmp_path, n=1):
    pages = []
    for i in range(n):
        d = tmp_path / str(i)
        pages.append(parse_page(write_valid_help(d, name=f"p{i}")))
    return pages


def test_check_site_accepts_a_consistent_site(tmp_path):
    assert check_site(_site(tmp_path), valid_sources()) == []


def test_check_site_reports_a_duplicated_claim_id(tmp_path):
    problems = check_site(_site(tmp_path, 2), valid_sources())
    assert any("t-claim" in p and p.startswith("sources: ") for p in problems)


def test_check_site_reports_a_claim_used_twice_on_one_page(tmp_path):
    path = write_valid_help(
        tmp_path,
        edits=(("</main>", '<p data-claim="t-claim" data-source="t-src">again</p></main>'),),
    )
    problems = check_site([parse_page(path)], valid_sources())
    assert any("t-claim" in p for p in problems)


def test_check_site_reports_an_unused_source(tmp_path):
    src = valid_sources()
    extra = replace(src.sources["t-src"], id="unused-src")
    src = replace(src, sources={**src.sources, "unused-src": extra})
    problems = check_site(_site(tmp_path), src)
    assert any("unused-src" in p for p in problems)


def test_check_site_reports_an_orphaned_claim(tmp_path):
    src = valid_sources()
    extra = replace(src.claims["t-claim"], id="orphan-claim")
    src = replace(src, claims={**src.claims, "orphan-claim": extra})
    problems = check_site(_site(tmp_path), src)
    assert any("orphan-claim" in p for p in problems)


def test_an_unclosed_p_ends_at_the_next_section(tmp_path):
    path = write_valid_help(
        tmp_path, edits=((f"<p>{PLAIN_TEXT}</p></section>", f"<p>{PLAIN_TEXT}"),)
    )
    page = parse_page(path)
    assert page.plain_text == PLAIN_TEXT
    assert page.section_ids == list(SECTIONS)
    assert [c.section for c in page.claims] == ["method"]


def test_a_claim_on_the_plain_lede_is_still_the_plain_paragraph(tmp_path):
    lede = f'<p data-claim="t-claim" data-source="t-src">{PLAIN_TEXT}</p>'
    edits = (
        (f"<p>{PLAIN_TEXT}</p>", lede + "<p>Second para is here.</p>"),
        ('<p data-claim="t-claim" data-source="t-src">Wow and flutter.', "<p>Wow and flutter."),
    )
    page = parse_page(write_valid_help(tmp_path, edits=edits))
    assert page.plain_text == PLAIN_TEXT
    assert [(c.id, c.section, c.text) for c in page.claims] == [("t-claim", "plain", PLAIN_TEXT)]


def test_an_outbound_link_carrying_a_claim_is_both(tmp_path):
    old = '<a href="https://example.org/a" data-source="t-src">A link</a>'
    new = '<a href="https://example.org/a" data-source="t-src" data-claim="c2">A link</a>'
    page = parse_page(write_valid_help(tmp_path, edits=((old, new),)))
    assert [(c.id, c.text) for c in page.claims] == [
        ("c2", "A link"),
        ("t-claim", "Wow and flutter. A link"),
    ]
    assert [(k.href, k.text) for k in page.links] == [("https://example.org/a", "A link")]
