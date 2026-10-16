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
    check_images,
    check_page,
    check_site,
    check_stylesheet,
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


def test_a_refs_entry_without_data_source_is_named(tmp_path):
    bare = "<li>A reference nobody put in the ledger.</li>"
    problems = problems_for(tmp_path, [("</ol></section>", bare + "</ol></section>")])
    assert [p for p in problems if "no data-source" in p] == [
        "dewow: a #refs entry has no data-source: 'A reference nobody put in the ledger.'"
    ]


def test_a_style_element_is_reported(tmp_path):
    problems = problems_for(tmp_path, [("</head>", "<style>p{}</style></head>")])
    assert any("<style>" in p for p in problems)


def test_a_style_attribute_with_a_url_is_reported(tmp_path):
    problems = problems_for(tmp_path, [("<main>", '<main style="background:url(img/t.png)">')])
    assert any("style attribute" in p for p in problems)


def test_a_plain_style_attribute_is_allowed(tmp_path):
    assert problems_for(tmp_path, [("<main>", '<main style="margin:0">')]) == []


def test_a_remote_img_srcset_entry_is_named(tmp_path):
    srcset = 'srcset="img/t.png 1x, https://x.org/big.png 2x"'
    problems = problems_for(tmp_path, [('alt="a picture"', f'alt="a picture" {srcset}')])
    assert any("https://x.org/big.png" in p and "srcset" in p for p in problems)


def test_a_remote_source_srcset_is_named(tmp_path):
    pic = '<picture><source srcset="//x.org/a.webp"><img src="img/t.png" alt="a"></picture>'
    problems = problems_for(tmp_path, [('<img src="img/t.png" alt="a picture">', pic)])
    assert any("//x.org/a.webp" in p for p in problems)


def test_a_local_srcset_is_allowed(tmp_path):
    edit = [('alt="a picture"', 'alt="a picture" srcset="img/t.png 1x, img/t.png 2x"')]
    assert problems_for(tmp_path, edit) == []


def test_a_remote_icon_link_is_named(tmp_path):
    link = '<link rel="icon" href="https://x.org/i.ico">'
    problems = problems_for(tmp_path, [("</head>", link + "</head>")])
    assert any("https://x.org/i.ico" in p for p in problems)


def test_a_remote_link_without_rel_is_named(tmp_path):
    problems = problems_for(tmp_path, [("</head>", '<link href="//x.org/y"></head>')])
    assert any("//x.org/y" in p for p in problems)


def test_the_stylesheet_is_scanned_for_remote_urls_and_imports(tmp_path):
    write_valid_help(tmp_path)
    assert check_stylesheet(tmp_path) == []
    css = '@import "https://f.org/a.css"; @import url(//f.org/b.css);\n'
    css += "a{background:url('http://x.org/i.png')} b{background:url(img/ok.png)}"
    (tmp_path / "style.css").write_text(css, encoding="utf-8")
    out = check_stylesheet(tmp_path)
    assert sorted(out) == [
        "style.css: '//f.org/b.css' is remote",
        "style.css: 'http://x.org/i.png' is remote",
        "style.css: 'https://f.org/a.css' is remote",
    ]


def test_a_png_no_page_uses_is_reported(tmp_path):
    page = parse_page(write_valid_help(tmp_path))
    assert check_images(tmp_path, [page]) == []
    (tmp_path / "img" / "stray.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    assert check_images(tmp_path, [page]) == ["img/stray.png is not used by any page"]


def test_text_from_br_and_mathml_tokens_does_not_run_together(tmp_path):
    math = "<math><mfrac><mn>1</mn><mi>W</mi></mfrac></math>"
    edit = [("Wow and flutter.", f"Wow<br>and flutter {math}.")]
    page = parse_page(write_valid_help(tmp_path, edits=tuple(edit)))
    # A space before each token, none after: the full stop stays on the formula.
    assert page.claims[0].text == "Wow and flutter 1 W. A link"


def test_block_boundaries_separate_words(tmp_path):
    edit = [("Wow and flutter.", "Wow<div>and</div><figcaption>flutter</figcaption>")]
    page = parse_page(write_valid_help(tmp_path, edits=tuple(edit)))
    assert page.claims[0].text == "Wow and flutter A link"
    edit = [("Wow and flutter.", "Wow<div>and</div>flutter")]  # only the end tag separates
    page = parse_page(write_valid_help(tmp_path / "e", edits=tuple(edit)))
    assert page.claims[0].text == "Wow and flutter A link"


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


# ---- ledger -----------------------------------------------------------------------------

from help_tools.ledger import build_ledger, render_checking_page  # noqa: E402

LINK = '<a href="https://example.org/a" data-source="t-src">A link</a>'


def test_build_ledger_on_the_fixture_page(tmp_path):
    write_valid_help(tmp_path)
    ledger = build_ledger(tmp_path, valid_sources())
    assert ledger["items"] == [
        {
            "id": "t-claim",
            "kind": "claim",
            "page": "dewow",
            "section": "method",
            "text": "Wow and flutter. A link",
            "sources": ["t-src"],
            "evidence": "memory",
            "look": "p. 1",
            "quote": "",
        },
        {
            "id": "link-dewow-t-src",
            "kind": "link",
            "page": "dewow",
            "section": "method",
            "text": "A link",
            "sources": ["t-src"],
            "hrefs": ["https://example.org/a"],
        },
    ]
    assert list(ledger["sources"]) == ["t-src"]


def test_build_ledger_is_deterministic(tmp_path):
    write_valid_help(tmp_path)
    s = valid_sources()
    assert build_ledger(tmp_path, s) == build_ledger(tmp_path, s)


def test_two_links_to_one_source_on_a_page_are_one_item(tmp_path):
    two = LINK + ' and <a href="https://example.org/b" data-source="t-src">B link</a>'
    write_valid_help(tmp_path, edits=((LINK, two),))
    items = build_ledger(tmp_path, valid_sources())["items"]
    links = [i for i in items if i["kind"] == "link"]
    assert [i["id"] for i in links] == ["link-dewow-t-src"]
    assert "A link" in links[0]["text"] and "B link" in links[0]["text"]
    assert links[0]["hrefs"] == ["https://example.org/a", "https://example.org/b"]


def test_a_repeated_href_is_listed_once(tmp_path):
    write_valid_help(tmp_path, edits=((LINK, LINK + " " + LINK),))
    link = build_ledger(tmp_path, valid_sources())["items"][1]
    assert link["hrefs"] == ["https://example.org/a"]


def two_pages(tmp_path, first="dewow", second="agc"):
    """Two valid pages citing t-src, the second with its own claim id `x-claim`."""
    write_valid_help(tmp_path, name=first)
    write_valid_help(
        tmp_path, name=second, edits=(('data-claim="t-claim"', 'data-claim="x-claim"'),)
    )
    base = valid_sources()
    claims = {**base.claims, "x-claim": replace(base.claims["t-claim"], id="x-claim")}
    return Sources(base.sources, claims)


def test_the_same_source_on_two_pages_gives_two_link_items(tmp_path):
    items = build_ledger(tmp_path, two_pages(tmp_path))["items"]
    assert [i["id"] for i in items if i["kind"] == "link"] == [
        "link-agc-t-src",
        "link-dewow-t-src",
    ]


def test_items_run_page_name_then_document_order(tmp_path):
    sources = two_pages(tmp_path, first="zeta", second="alpha")
    ids = [(i["page"], i["id"]) for i in build_ledger(tmp_path, sources)["items"]]
    assert ids == [
        ("alpha", "x-claim"),
        ("alpha", "link-alpha-t-src"),
        ("zeta", "t-claim"),
        ("zeta", "link-zeta-t-src"),
    ]


def test_claims_come_in_document_order_not_id_order(tmp_path):
    tail = '</p></section>\n<section id="settings">'
    extra = '<p data-claim="a-first" data-source="t-src">Later text.</p>' + tail
    write_valid_help(tmp_path, edits=((tail, extra),))
    sources = valid_sources()
    claims = dict(sources.claims)
    claims["a-first"] = replace(claims["t-claim"], id="a-first")
    ids = [i["id"] for i in build_ledger(tmp_path, Sources(sources.sources, claims))["items"]]
    assert ids.index("t-claim") < ids.index("a-first")


def test_a_link_without_a_source_gets_no_item(tmp_path):
    write_valid_help(tmp_path, edits=((' data-source="t-src">A link', ">A link"),))
    items = build_ledger(tmp_path, valid_sources())["items"]
    assert [i["kind"] for i in items] == ["claim"]


def test_the_ledger_reads_every_source_and_claim_field_from_a_loaded_file(tmp_path):
    d = tmp_path / "sources"
    d.mkdir()
    write(
        d / "dewow.json",
        {
            "sources": {
                "t-src": {
                    "citation": "CITE",
                    "url": "https://u.example/x",
                    "exists": {"checked_via": "VIA", "checked_on": "2026-01-02", "note": "NOTE"},
                }
            },
            "claims": {"t-claim": {"evidence": "read", "look": "LOOK", "quote": "QUOTE"}},
        },
    )
    write_valid_help(tmp_path / "help")
    ledger = build_ledger(tmp_path / "help", load_sources(d))
    assert ledger["sources"] == {
        "t-src": {
            "citation": "CITE",
            "url": "https://u.example/x",
            "checked_via": "VIA",
            "checked_on": "2026-01-02",
            "note": "NOTE",
        }
    }
    claim = ledger["items"][0]
    assert (claim["evidence"], claim["look"], claim["quote"]) == ("read", "LOOK", "QUOTE")


def test_render_replaces_the_token_and_escapes_script_ends(tmp_path):
    ledger = {"items": [{"text": "x </script><b> y"}], "sources": {}}
    template = tmp_path / "t.html"
    template.write_text("<script>const L = /*__LEDGER__*/null;</script>", encoding="utf-8")
    html = render_checking_page(ledger, template)
    assert "/*__LEDGER__*/" not in html
    assert html.count("</script>") == 1
    assert "<\\/script>" not in html and "\\u003c/script>" in html
    inner = html[len("<script>const L = ") : -len(";</script>")]
    assert json.loads(inner) == ledger


def test_render_leaves_no_script_or_comment_opener_in_the_json(tmp_path):
    ledger = {"items": [{"text": "a <!--<script> b <!-- c"}], "sources": {}}
    template = tmp_path / "t.html"
    template.write_text("<script>const L = /*__LEDGER__*/null;</script>", encoding="utf-8")
    html = render_checking_page(ledger, template)
    body = html[len("<script>") : -len("</script>")]
    assert "<" not in body
    assert json.loads(body[len("const L = ") : -1]) == ledger


@pytest.mark.parametrize(
    "bad", ["has space", "a/b", "..", ".", "x" * 201, "é-claim", "", "t-claim\n"]
)
def test_a_bad_item_id_is_refused(tmp_path, bad):
    write_valid_help(tmp_path, edits=(('data-claim="t-claim"', f'data-claim="{bad}"'),))
    base = valid_sources()
    sources = Sources(base.sources, {bad: replace(base.claims["t-claim"], id=bad)})
    with pytest.raises(ValueError, match="not a valid document id"):
        build_ledger(tmp_path, sources)


def test_a_repeated_item_id_is_refused(tmp_path):
    write_valid_help(tmp_path, name="dewow")
    write_valid_help(tmp_path, name="agc")  # both pages declare claim t-claim
    with pytest.raises(ValueError, match="more than once"):
        build_ledger(tmp_path, valid_sources())


def test_a_claim_with_two_sources_keeps_their_order(tmp_path):
    write_valid_help(
        tmp_path, edits=(('data-source="t-src">Wow', 'data-source="t-src u-src">Wow'),)
    )
    base = valid_sources()
    src2 = replace(base.sources["t-src"], id="u-src", citation="Other")
    sources = Sources({**base.sources, "u-src": src2}, base.claims)
    items = build_ledger(tmp_path, sources)["items"]
    assert items[0]["sources"] == ["t-src", "u-src"]
    assert list(build_ledger(tmp_path, sources)["sources"]) == ["t-src", "u-src"]


def test_a_source_cited_only_in_refs_gets_a_ref_item(tmp_path):
    ref = '<li data-source="t-src">A reference.</li>'
    both = ref + '<li data-source="r-src">Only here. <i>Title</i>.</li>'
    write_valid_help(tmp_path, edits=((ref, both),))
    base = valid_sources()
    sources = Sources(
        {**base.sources, "r-src": replace(base.sources["t-src"], id="r-src")}, base.claims
    )
    items = build_ledger(tmp_path, sources)["items"]
    refs = [i for i in items if i["kind"] == "ref"]
    assert refs == [
        {
            "id": "ref-dewow-r-src",
            "kind": "ref",
            "page": "dewow",
            "section": "refs",
            "text": "Only here. Title.",
            "sources": ["r-src"],
        }
    ]
    assert "r-src" in build_ledger(tmp_path, sources)["sources"]


def test_render_requires_exactly_one_token(tmp_path):
    template = tmp_path / "t.html"
    template.write_text("no token", encoding="utf-8")
    with pytest.raises(ValueError):
        render_checking_page({}, template)


def test_the_committed_ledger_builds_and_its_template_renders(tmp_path):
    from help_tools.ledger import HELP_DIR, TEMPLATE
    from help_tools.sources import SOURCES_DIR

    ledger = build_ledger(HELP_DIR, load_sources(SOURCES_DIR))
    ids = [i["id"] for i in ledger["items"]]
    assert len(ids) == len(set(ids)) and ids
    html = render_checking_page(ledger, TEMPLATE)
    assert "/*__LEDGER__*/null" not in html


def test_a_source_that_is_only_linked_is_not_also_a_ref_item(tmp_path):
    # the claim cites u-src, the link cites t-src, and #refs lists t-src: no ref item for it
    write_valid_help(tmp_path, edits=(('data-source="t-src">Wow', 'data-source="u-src">Wow'),))
    base = valid_sources()
    src2 = replace(base.sources["t-src"], id="u-src")
    items = build_ledger(tmp_path, Sources({**base.sources, "u-src": src2}, base.claims))["items"]
    assert [i["kind"] for i in items] == ["claim", "link"]


def test_a_source_in_two_ref_entries_gets_one_ref_item(tmp_path):
    ref = '<li data-source="t-src">A reference.</li>'
    twice = ref + '<li data-source="r-src">First.</li><li data-source="r-src">Second.</li>'
    write_valid_help(tmp_path, edits=((ref, twice),))
    base = valid_sources()
    src2 = replace(base.sources["t-src"], id="r-src")
    items = build_ledger(tmp_path, Sources({**base.sources, "r-src": src2}, base.claims))["items"]
    refs = [(i["id"], i["text"]) for i in items if i["kind"] == "ref"]
    assert refs == [("ref-dewow-r-src", "First.")]
