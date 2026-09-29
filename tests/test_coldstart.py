"""Tests for atmos/coldstart.py: starter tables, blending by how much own data exists, blended limits."""
import math

import pytest

from atmos.coldstart import blend_limits, blend_tables, nearest_stations, same_zone, starter_table
from atmos.limits import ChannelLimits, StationLimits
from atmos.normality import NormalityTable
from atmos.schema import CHANNELS


def table(mean, std, n, key="1-0", station="X", settings=None):
    cells = {key: {ch: {"mean": mean, "std": std, "n": n} for ch in CHANNELS}}
    return NormalityTable(station, cells, settings)


def test_pooled_starter_is_the_mean_with_between_station_spread(settings):
    a, b = table(10.0, 1.0, 100, settings=settings), table(20.0, 1.0, 100, settings=settings)
    cell = starter_table([a, b], settings).cells["1-0"]["temperature_c"]
    assert cell["mean"] == pytest.approx(15.0)
    assert cell["std"] == pytest.approx(math.sqrt(1.0 + 25.0))           # within (1) plus between (5 squared)


def test_a_single_starter_is_used_as_it_is(settings):
    t = table(10.0, 1.0, 100, settings=settings)
    assert starter_table([t], settings) is t
    with pytest.raises(ValueError):
        starter_table([], settings)


def test_a_cell_with_no_own_data_is_the_starter(settings):
    starter = table(10.0, 2.0, 500, settings=settings)
    blended = blend_tables(starter, None, settings)
    assert blended.cells["1-0"]["temperature_c"]["mean"] == 10.0
    empty = NormalityTable("N", {}, settings)
    assert blend_tables(starter, empty, settings).cells["1-0"]["pressure_hpa"]["std"] == 2.0


def test_own_data_takes_over_as_it_grows(settings):
    full = settings["coldstart"]["full_weight_samples"]
    starter = table(10.0, 2.0, 500, settings=settings)
    for n, weight in ((0 + 3, 3 / full), (full // 2, 0.5), (full, 1.0), (full * 4, 1.0)):
        own = table(20.0, 1.0, n, settings=settings)
        cell = blend_tables(starter, own, settings).cells["1-0"]["temperature_c"]
        assert cell["mean"] == pytest.approx(weight * 20.0 + (1 - weight) * 10.0)
        assert cell["n"] == n
    own = table(20.0, 1.0, full, settings=settings)
    assert blend_tables(starter, own, settings).cells["1-0"]["temperature_c"]["std"] == pytest.approx(1.0)


def test_a_cell_only_the_station_has_is_kept(settings):
    starter = table(10.0, 2.0, 500, key="1-0", settings=settings)
    own = table(20.0, 1.0, 40, key="2-5", settings=settings)
    cells = blend_tables(starter, own, settings).cells
    assert cells["2-5"]["humidity_pct"]["mean"] == 20.0 and cells["1-0"]["humidity_pct"]["mean"] == 10.0


def _limits(frozen, noise, sid="X"):
    return StationLimits(sid, 60.0, {ch: ChannelLimits(resolution=1.0, frozen_minutes=frozen, noise_std=noise, n_runs=99)
                                     for ch in CHANNELS})


def test_limits_come_from_the_others_at_first_and_from_the_station_later(settings):
    others = [_limits(600, 1.0), _limits(1000, 3.0)]
    start = blend_limits(others, None, 0, "N", 60.0, settings)
    assert start.frozen_minutes("temperature_c") == pytest.approx(800) and start.noise_std("pressure_hpa") == pytest.approx(2.0)
    own = _limits(200, 0.5)
    half = blend_limits(others, own, settings["coldstart"]["full_weight_days"] / 2, "N", 60.0, settings)
    assert half.frozen_minutes("humidity_pct") == pytest.approx(0.5 * 200 + 0.5 * 800)
    done = blend_limits(others, own, settings["coldstart"]["full_weight_days"], "N", 60.0, settings)
    assert done.frozen_minutes("humidity_pct") == pytest.approx(200) and done.noise_std("humidity_pct") == pytest.approx(0.5)


def test_nearest_and_same_zone():
    cands = {"A": {"lat": 20.0, "lon": 85.0, "climate_zone": "east"}, "B": {"lat": 28.0, "lon": 77.0, "climate_zone": "north"},
             "C": {"lat": 21.5, "lon": 87.0, "climate_zone": "east"}}
    target = {"lat": 22.0, "lon": 88.0, "climate_zone": "east"}
    assert nearest_stations(target, cands, 1) == ["C"] and nearest_stations(target, cands, 2) == ["C", "A"]
    assert sorted(same_zone(target, cands)) == ["A", "C"]
