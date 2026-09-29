"""Amendment 3: two remedies behind flags that are off by default (an expected-change-aware step rule, a sustained one-channel offset
check), and the FRESH2 configuration set. The flags do not change anything unless switched on."""
import pytest

from atmos.config import load_settings
from atmos.health import check_health, check_offset, check_step
from tests.conftest import make_history, make_reading

CAD = 60
CH = ("temperature_c", "pressure_hpa", "humidity_pct")


def settings_with(**flags):
    s = load_settings()
    if "expected_step" in flags:
        s["health"]["step"]["expected_aware"] = flags["expected_step"]
    if "offset" in flags:
        s["health"]["offset"]["enabled"] = flags["offset"]
    return s


def test_new_flags_are_off_in_the_shipped_default():
    s = load_settings()
    assert s["health"]["step"]["expected_aware"] is False and s["health"]["offset"]["enabled"] is False


# ---- remedy 3: expected-change-aware step --------------------------------------------------------------------
def desert_morning():
    """Temperature 18.6 -> 34.2 across a 6 h gap-free pair of reports, as at a desert station on a clear day."""
    return [make_reading(0, t=18.6), make_reading(180, t=34.2)]


def test_a_large_daily_warming_is_a_jump_today_and_ordinary_with_the_remedy():
    hist = desert_morning()
    expected = [18.0, 33.0]                               # the station's own normal: +15 over the same hours
    off = check_step(hist, "temperature_c", settings_with(expected_step=False), 180.0, None, expected)
    on = check_step(hist, "temperature_c", settings_with(expected_step=True), 180.0, None, expected)
    assert off.flagged and not on.flagged and "daily cycle" in on.reason


def test_the_remedy_still_flags_a_jump_the_daily_cycle_does_not_explain():
    hist = [make_reading(0, t=20.0), make_reading(60, t=32.0)]
    expected = [20.0, 21.0]                                # the normal change is +1, the observed one +12
    assert check_step(hist, "temperature_c", settings_with(expected_step=True), CAD, None, expected).flagged


def test_the_remedy_never_adds_a_flag():
    """Expected change of the opposite sign would make |delta - expected change| larger: the raw change is what is judged then."""
    hist = [make_reading(0, t=20.0), make_reading(60, t=26.0)]           # +6, allowed 10 with rate 1.0/min capped at 10
    expected = [20.0, 12.0]                                # expected change -8: adjusted change +14 would be a jump
    assert not check_step(hist, "temperature_c", settings_with(expected_step=True), CAD, None, expected).flagged


def test_step_without_expected_values_is_unchanged():
    hist = [make_reading(0, t=20.0), make_reading(60, t=32.0)]
    assert check_step(hist, "temperature_c", settings_with(expected_step=True), CAD, None, None).flagged


# ---- remedy 4: sustained one-channel offset ------------------------------------------------------------------
def series(n, t_offset=0.0, p_offset=0.0, rh_offset=0.0):
    hist = make_history(n, cadence=CAD, t=lambda i: 25.0 + t_offset, p=lambda i: 1010.0 + p_offset + 0.05 * i, rh=lambda i: 60.0 + rh_offset + 0.1 * i)
    expected = {"temperature_c": [25.0] * n, "pressure_hpa": [1010.0 + 0.05 * i for i in range(n)],
                "humidity_pct": [60.0 + 0.1 * i for i in range(n)]}
    sigma = {"temperature_c": [2.0] * n, "pressure_hpa": [2.0] * n, "humidity_pct": [8.0] * n}
    return hist, expected, sigma


def offset_flags(hist, expected, sigma, s):
    return {c: check_offset(hist, c, expected[c], sigma[c], expected, sigma, s, CAD) for c in CH}


def test_offset_check_is_silent_when_off():
    hist, exp, sig = series(20, t_offset=7.0)
    assert not any(r.flagged for r in offset_flags(hist, exp, sig, settings_with(offset=False)).values())


def test_a_sustained_one_channel_offset_is_flagged_and_soft():
    hist, exp, sig = series(20, t_offset=7.0)             # temperature 3.5 sd high for all 12 h, the others normal
    res = offset_flags(hist, exp, sig, settings_with(offset=True))
    assert res["temperature_c"].flagged and res["temperature_c"].severity == "soft"
    assert not res["pressure_hpa"].flagged and not res["humidity_pct"].flagged


def test_the_same_departure_on_two_channels_is_weather_not_an_offset():
    hist, exp, sig = series(20, t_offset=7.0, rh_offset=-30.0)         # a hot, dry spell: temperature and humidity both far from normal
    res = offset_flags(hist, exp, sig, settings_with(offset=True))
    assert not res["temperature_c"].flagged and not res["humidity_pct"].flagged and "together" in res["temperature_c"].reason


def test_an_ordinary_departure_is_not_flagged():
    hist, exp, sig = series(20, t_offset=2.0)               # one sd
    assert not any(r.flagged for r in offset_flags(hist, exp, sig, settings_with(offset=True)).values())


def test_offset_needs_enough_complete_samples():
    hist, exp, sig = series(3, t_offset=7.0)
    assert not offset_flags(hist, exp, sig, settings_with(offset=True))["temperature_c"].flagged


def test_check_health_adds_offset_results_only_when_enabled():
    hist, exp, sig = series(20, t_offset=7.0)
    names_off = {c.check for c in check_health(hist, settings_with(offset=False), CAD, expected=exp, sigma=sig)}
    names_on = {c.check for c in check_health(hist, settings_with(offset=True), CAD, expected=exp, sigma=sig)}
    assert not any(n.startswith("offset:") for n in names_off)
    assert {"offset:temperature_c", "offset:pressure_hpa", "offset:humidity_pct"} <= names_on


# ---- the FRESH2 configuration set ----------------------------------------------------------------------------
def test_fresh2_configs_full_is_the_shipped_pipeline_and_registered_has_every_remedy_off():
    import evaluate_real as er
    from atmos.limits import fit_limits
    from atmos.mlmodel import IsolationModel, MahalanobisModel
    from atmos.normality import NormalityTable
    from tests.test_limits import rounded_series
    s = er.real_settings(load_settings())
    train = rounded_series(seed=5)
    table, model = NormalityTable.fit(train, s), IsolationModel.fit(train, s)
    lim, mahal = fit_limits(train, s, CAD), MahalanobisModel.fit(train, s, table)
    cfgs = er.build_configs(s, table, model, lim, train, "S1", float(CAD), mahal, "FRESH2")
    names = [n for n, _, _ in cfgs]
    assert names[:5] == ["full", "registered", "r3_expected_step", "r4_offset", "r34_both"]
    assert not any(n.startswith("no_") for n in names) and "baseline_rules" in names
    stuck = [make_reading(i * CAD, t=26.0, p=1000.0 + 0.2 * (i % 5), rh=100.0) for i in range(60)]
    by = {n: p for n, _, p in cfgs}
    assert any(p.verdict == "FAULT" for p in by["registered"](stuck))               # remedy 1 off: hard frozen
    assert not any(p.verdict == "FAULT" for p in by["full"](stuck))                # remedy 1 is the shipped default


