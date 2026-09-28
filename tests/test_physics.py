"""Tests for atmos/physics.py (L0). One test per QC rule."""
from atmos.physics import check_dew_point, check_physics, check_ranges, check_wet_bulb, dew_point_c, wet_bulb_c
from tests.conftest import by_name, make_reading


def test_range_ok(settings):
    assert not any(r.flagged for r in check_ranges(make_reading(), settings))


def test_range_temperature_too_high(settings):
    r = by_name(check_ranges(make_reading(t=75.0), settings), "range:temperature_c")
    assert r.flagged and "outside the physical range" in r.reason


def test_range_pressure_too_low(settings):
    assert by_name(check_ranges(make_reading(p=100.0), settings), "range:pressure_hpa").flagged


def test_range_humidity_above_100(settings):
    assert by_name(check_ranges(make_reading(rh=120.0), settings), "range:humidity_pct").flagged


def test_range_missing_channel_is_not_a_range_fault(settings):
    r = by_name(check_ranges(make_reading(p=None), settings), "range:pressure_hpa")
    assert not r.flagged and "missing" in r.reason


def test_dew_point_math():
    assert abs(dew_point_c(20.0, 100.0) - 20.0) < 0.05
    assert abs(dew_point_c(20.0, 50.0) - 9.3) < 0.2


def test_dew_point_ok(settings):
    assert not check_dew_point(make_reading(t=20.0, rh=60.0), settings).flagged


def test_dew_point_above_temperature_flagged(settings):
    r = check_dew_point(make_reading(t=20.0, rh=110.0), settings)
    assert r.flagged and "impossible" in r.reason


def test_dew_point_skipped_when_missing(settings):
    assert not check_dew_point(make_reading(rh=None), settings).flagged


def test_wet_bulb_math():
    # Stull approximation: T=20C, RH=50% -> about 13.7C
    assert abs(wet_bulb_c(20.0, 50.0) - 13.7) < 0.5


def test_wet_bulb_is_soft_flag_only(settings):
    r = check_wet_bulb(make_reading(t=45.0, rh=90.0), settings)
    assert r.flagged and r.severity == "soft"
    # a hard-coded "impossible" rule is out of scope: no hard check may be raised by wet-bulb
    hard = [c for c in check_physics(make_reading(t=45.0, rh=90.0), settings) if c.flagged and c.severity == "hard"]
    assert hard == []


def test_wet_bulb_normal_not_flagged(settings):
    assert not check_wet_bulb(make_reading(t=20.0, rh=50.0), settings).flagged


def test_physics_layer_can_be_switched_off(settings):
    settings["layers"]["physics"] = False
    assert check_physics(make_reading(t=999.0), settings) == []
