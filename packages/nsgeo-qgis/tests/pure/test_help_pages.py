"""The page contract over the real `help/` directory."""

from __future__ import annotations

from help_tools.pages import check_page, check_site, parse_page
from help_tools.sources import load_sources
from nsgeo.processing import available_steps
from nsgeo_qgis.help_pages import HELP_DIR

PENDING = {
    "time_zero",
    "bandpass",
    "gain_agc",
    "gain_parametric",
    "gain_curve",
    "background_mean",
    "background_sliding",
    "background_svd",
    "amp_abs",
    "amp_square",
    "amp_envelope",
}  # shrinks to empty by the last chunk


def _pages():
    return sorted(HELP_DIR.glob("*.html"))


def test_every_registered_step_has_a_page_unless_pending():
    pages = {p.stem for p in HELP_DIR.glob("*.html")}
    assert pages == set(available_steps()) - PENDING
    assert set(available_steps()) >= PENDING


def test_every_page_meets_the_contract():
    src = load_sources()
    problems = [p for f in _pages() for p in check_page(parse_page(f), HELP_DIR, src)]
    assert problems == []


def test_pages_and_sources_file_agree():
    assert check_site([parse_page(f) for f in _pages()], load_sources()) == []
