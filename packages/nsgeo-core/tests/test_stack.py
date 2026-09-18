from __future__ import annotations

import numpy as np
import pytest
from nsgeo.processing.base import Radargram, build_step
from nsgeo.processing.stack import StepStack


def source(n_samples=64, n_traces=120, seed=0):
    rng = np.random.default_rng(seed)
    band = np.linspace(4.0, 1.0, n_samples)[:, None] * np.ones((1, n_traces))
    return Radargram(data=band + rng.normal(0, 0.2, (n_samples, n_traces)), dt_ns=0.2, t0_ns=0.0)


def stack_of(*specs):
    st = StepStack()
    st.source = source()
    for name, kwargs in specs:
        st.append(build_step(name, **kwargs))
    return st


def test_empty_stack_returns_the_source_unchanged():
    st = StepStack()
    src = source()
    st.source = src
    np.testing.assert_array_equal(st.result().data, src.data)


def test_steps_apply_in_order():
    st = stack_of(("background_mean", {}))
    np.testing.assert_allclose(st.result().data.mean(axis=1), 0.0, atol=1e-12)


def test_disabled_step_is_skipped_but_keeps_its_index():
    st = stack_of(("background_mean", {}))
    st.set_enabled(0, False)
    np.testing.assert_array_equal(st.result().data, st.source.data)
    assert len(st) == 1


def test_appending_reuses_the_cached_prefix():
    st = stack_of(("dewow", {"window_ns": 4.0}))
    st.result()
    before = st.cache_size
    st.append(build_step("background_mean"))
    assert st.cache_size == before  # prefix survived
    st.result()
    assert st.cache_size == before + 1


def test_editing_a_step_invalidates_from_that_index_onward():
    st = stack_of(("dewow", {"window_ns": 4.0}), ("background_mean", {}))
    st.result()
    assert st.cache_size == 2
    st.replace_step(0, build_step("dewow", window_ns=8.0))
    assert st.cache_size == 0


def test_editing_a_later_step_keeps_the_earlier_cache():
    st = stack_of(("dewow", {"window_ns": 4.0}), ("background_mean", {}))
    st.result()
    st.replace_step(1, build_step("background_sliding", window_traces=20))
    assert st.cache_size == 1


def test_remove_and_move_invalidate_correctly():
    st = stack_of(("dewow", {"window_ns": 4.0}), ("background_mean", {}))
    st.result()
    st.move(0, 1)
    assert st.cache_size == 0
    assert [s.name for s, _ in st.entries] == ["background_mean", "dewow"]
    st.result()
    st.remove(1)
    assert st.cache_size == 1


def test_disabling_a_step_after_the_result_was_computed_changes_the_result():
    """A warm cache is the only state in which invalidation does anything.

    `test_disabled_step_is_skipped_but_keeps_its_index` toggles *before*
    ever calling `result()`, so the cache is empty and `set_enabled`'s
    `_invalidate_from` has nothing to invalidate -- with that call deleted,
    both tiers stayed green while `result()` handed back the pre-toggle
    data, off by up to 0.75 max-abs. The per-step checkbox in the
    processing dock is exactly this call, so what a user got was the
    unchanged radargram, which they could then save or apply to a whole
    grid.

    Asserts the cache emptied *and* that the data really changed, against a
    from-scratch recomputation rather than against the stack itself.
    """
    st = stack_of(("dewow", {"window_ns": 4.0}), ("background_mean", {}))
    processed = st.result().data.copy()
    assert st.cache_size == 2

    st.set_enabled(0, False)
    assert st.cache_size == 0

    after = st.result().data
    assert np.abs(after - processed).max() > 0.1
    np.testing.assert_allclose(after, build_step("background_mean").apply(st.source).data)


def test_inserting_a_step_before_a_cached_one_changes_the_result():
    """`insert` had no cache test at all, while append, replace_step, remove
    and move each had one -- and deleting its `_invalidate_from` survived
    both tiers for the same reason as `set_enabled` above. Inserting is
    reachable from the UI's drag-reorder and from applying a preset.
    """
    st = stack_of(("background_mean", {}))
    first = st.result().data.copy()
    assert st.cache_size == 1

    st.insert(0, build_step("gain_agc", window_ns=4.0))
    assert st.cache_size == 0

    after = st.result().data
    assert np.abs(after - first).max() > 0.1
    expected = build_step("background_mean").apply(
        build_step("gain_agc", window_ns=4.0).apply(st.source)
    )
    np.testing.assert_allclose(after, expected.data)

    # Inserting past the end of the cached prefix leaves that prefix alone.
    st.result()
    st.insert(2, build_step("dewow", window_ns=4.0))
    assert st.cache_size == 2


def test_setting_a_new_source_clears_everything():
    st = stack_of(("background_mean", {}))
    st.result()
    st.source = source(seed=9)
    assert st.cache_size == 0


def test_intermediate_returns_the_state_after_a_given_step():
    st = stack_of(("dewow", {"window_ns": 4.0}), ("background_mean", {}))
    mid = st.intermediate(0)
    expected = build_step("dewow", window_ns=4.0).apply(st.source)
    np.testing.assert_allclose(mid.data, expected.data)


def test_difference_shows_what_a_step_removed():
    """Nearly free because the intermediates are already cached, and it
    diagnoses over-removal of genuine flat-lying features."""
    st = stack_of(("background_mean", {}))
    diff = st.difference(0)
    np.testing.assert_allclose(
        diff.data,
        np.tile(st.source.data.mean(axis=1, keepdims=True), (1, st.source.n_traces)),
        atol=1e-9,
    )


def test_difference_rejects_an_out_of_range_index():
    st = stack_of(("background_mean", {}))
    with pytest.raises(IndexError):
        st.difference(5)


def test_difference_is_undefined_for_a_step_that_crops_samples():
    """time_zero drops rows, so before - after has no meaning; fail with a
    named error rather than numpy's broadcast message."""
    st = stack_of(("time_zero", {"mode": "sample", "sample": 8}))
    with pytest.raises(ValueError, match="changes the sample count"):
        st.difference(0)


def test_move_rejects_negative_or_out_of_range_indices():
    """A negative dst would under-invalidate and serve stale results."""
    st = stack_of(("dewow", {"window_ns": 4.0}), ("background_mean", {}))
    with pytest.raises(IndexError, match="move indices"):
        st.move(0, -1)
    with pytest.raises(IndexError, match="move indices"):
        st.move(2, 0)


def test_result_without_a_source_raises():
    with pytest.raises(ValueError, match="source"):
        StepStack().result()


def test_serialises_to_dicts():
    st = stack_of(("dewow", {"window_ns": 4.0}), ("background_svd", {"n_components": 2}))
    st.set_enabled(1, False)
    assert st.to_dicts() == [
        {"step": "dewow", "params": {"window_ns": 4.0}, "enabled": True},
        {"step": "background_svd", "params": {"n_components": 2}, "enabled": False},
    ]


def test_round_trips_through_dicts():
    st = stack_of(("dewow", {"window_ns": 4.0}), ("background_mean", {}))
    back = StepStack.from_dicts(st.to_dicts())
    back.source = st.source
    np.testing.assert_allclose(back.result().data, st.result().data)


def test_from_dicts_rejects_an_unknown_step():
    with pytest.raises(KeyError, match="available"):
        StepStack.from_dicts([{"step": "nope", "params": {}, "enabled": True}])


def test_project_round_trips_stacks(tmp_path):
    from nsgeo.geometry.grid import Grid
    from nsgeo.geometry.placement import GridPlacement
    from nsgeo.model.survey import Line, Site
    from nsgeo.project import load_site, save_site

    from tests.synthetic import write_dzt

    p = tmp_path / "L0.DZT"
    write_dzt(p, np.zeros((512, 60), dtype=np.int32))
    grid = Grid(
        id="G",
        origin=(0.0, 0.0),
        azimuth=0.0,
        size_x=20.0,
        size_y=20.0,
        crs="EPSG:32616",
        default_spacing=0.5,
    )
    line = Line.open(p, GridPlacement(grid_id="G", axis="y", offset=0.0))
    site = Site(grids=[grid], lines=[line])
    st = StepStack()
    st.append(build_step("dewow", window_ns=4.0))
    site.stacks = {"L0.DZT": st}

    out = tmp_path / "survey.nsgeo.json"
    save_site(site, out)
    back = load_site(out)
    assert back.stacks["L0.DZT"].to_dicts() == st.to_dicts()
