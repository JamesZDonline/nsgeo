"""Every step carries a human title and a group, in the registry (#82).

A front end shows `title` wherever it names a step and lays its step menu
out by `grouped_steps()`. Neither is stored anywhere: stacks, presets and
cube recipes keep the id, so a title can be reworded without touching a
saved file.
"""

from __future__ import annotations

import pytest
from nsgeo.processing import (
    STEP_GROUPS,
    Radargram,
    available_steps,
    get_step,
    grouped_steps,
    step_title,
)
from nsgeo.processing.base import register

# The help pages' titles (the drafts on nsgeo-help-pages), so a step reads
# the same in the menu and on its page.
TITLES = {
    "time_zero": "Time zero",
    "time_cutoff": "Time cutoff",
    "dewow": "Dewow",
    "bandpass": "Bandpass",
    "background_mean": "Background removal (mean)",
    "background_sliding": "Background removal (sliding)",
    "background_svd": "Remove leading components (SVD)",
    "gain_curve": "Gain curve",
    "gain_agc": "Automatic gain control",
    "gain_parametric": "Parametric gain",
    "amp_abs": "Absolute value",
    "amp_envelope": "Envelope",
    "amp_square": "Square of the amplitude",
}


@pytest.fixture
def clean_registry():
    """Registering a step is a global side effect; restore the registry so a
    test double cannot leak into every later test."""
    from nsgeo.processing import base

    saved = dict(base._REGISTRY)
    yield
    base._REGISTRY.clear()
    base._REGISTRY.update(saved)


@pytest.mark.parametrize("name", available_steps())
def test_every_step_declares_a_title_a_known_group_and_an_order(name):
    """What stops a new step shipping as a bare id in the menu."""
    cls = get_step(name)
    assert isinstance(cls.title, str) and cls.title.strip() == cls.title != ""
    assert cls.group in STEP_GROUPS
    assert isinstance(cls.order, int) and not isinstance(cls.order, bool)


def test_titles_are_the_help_pages_wording():
    assert {name: step_title(name) for name in available_steps()} == TITLES


def test_no_two_steps_share_a_title_or_a_place_in_their_group():
    """Two equal titles could not be told apart in a menu, and two equal
    orders would leave the menu order to registration order."""
    titles = [get_step(n).title for n in available_steps()]
    places = [(get_step(n).group, get_step(n).order) for n in available_steps()]
    assert len(set(titles)) == len(titles)
    assert len(set(places)) == len(places)


def test_grouped_steps_is_the_processing_flow():
    assert grouped_steps() == [
        ("Time", ["time_zero", "time_cutoff"]),
        ("Filters", ["dewow", "bandpass"]),
        (
            "Background",
            ["background_mean", "background_sliding", "background_svd"],
        ),
        ("Gain", ["gain_curve", "gain_agc", "gain_parametric"]),
        ("Amplitude", ["amp_abs", "amp_envelope", "amp_square"]),
    ]


def test_grouped_steps_orders_a_group_by_order_not_by_registration(clean_registry):
    """A step registered later but declaring a lower `order` comes first."""

    class _Base:
        group = "Time"

        def __init__(self) -> None:
            pass

        @property
        def params(self):
            return {}

        @classmethod
        def schema(cls):
            return ()

        def apply(self, rg: Radargram) -> Radargram:
            return rg

    @register
    class _Early(_Base):
        name = "test_early"
        title = "Early"
        order = -1

    groups = dict(grouped_steps())
    assert groups["Time"][0] == "test_early"
    assert groups["Time"][1:] == ["time_zero", "time_cutoff"]


def _bare_step(**attrs):
    """A minimal step class carrying exactly `attrs` as class attributes."""

    def apply(self, rg: Radargram) -> Radargram:
        return rg

    body = {
        "params": property(lambda self: {}),
        "schema": classmethod(lambda cls: ()),
        "apply": apply,
        **attrs,
    }
    return type("_Bare", (), body)


@pytest.mark.parametrize("missing", ["title", "group", "order"])
def test_register_refuses_a_step_missing_a_display_attribute(clean_registry, missing):
    """Refused where the step is defined, not later where the Add step menu
    or the Difference caption first reads the attribute and fails far from
    the cause (a step without `group` stopped the Processing panel loading)."""
    attrs = {"name": "test_bare", "title": "Bare", "group": "Time", "order": 9}
    del attrs[missing]
    with pytest.raises(ValueError, match=rf"test_bare.*{missing}"):
        register(_bare_step(**attrs))
    assert "test_bare" not in available_steps()


@pytest.mark.parametrize(
    ("attr", "value"),
    [("title", ""), ("title", 3), ("group", "Display"), ("order", "1"), ("order", True)],
)
def test_register_refuses_a_display_attribute_of_the_wrong_kind(clean_registry, attr, value):
    """An unknown group would silently drop the step from every menu."""
    attrs = {"name": "test_bare", "title": "Bare", "group": "Time", "order": 9, attr: value}
    with pytest.raises(ValueError, match=rf"test_bare.*{attr}"):
        register(_bare_step(**attrs))
    assert "test_bare" not in available_steps()


def test_step_title_of_an_unknown_step_names_it():
    with pytest.raises(KeyError, match="no_such_step"):
        step_title("no_such_step")
