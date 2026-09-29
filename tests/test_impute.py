"""Tests for atmos/impute.py: estimates and uncertainty bands for missing / faulty values."""
from datetime import timedelta

import pytest

import evaluate as ev
from atmos.fusion import Pipeline
from atmos.healthscore import HealthRecord
from atmos.impute import apply_imputation, fill_gaps, impute_reading, impute_value
from atmos.normality import NormalityTable
from atmos.schema import CHANNELS, CheckResult, Verdict, VerdictResult
from tests.conftest import make_history, make_reading


@pytest.fixture(scope="module")
def series():
    from atmos.config import load_settings
    return ev.synthetic_series(load_settings(), 4, 9)


@pytest.fixture(scope="module")
def table():
    from atmos.config import load_settings
    s = load_settings()
    return NormalityTable.fit(ev.synthetic_series(s, 20, 1), s)


def recs(readings, verdict=Verdict.VALID, flagged=()):
    return [HealthRecord(r.timestamp, {c: getattr(r, c) for c in CHANNELS}, verdict, frozenset(flagged))
            for r in readings]


def bad(ch, verdict=Verdict.FAULT):
    return VerdictResult(verdict=verdict, confidence=0.9, reason="x",
                         checks=[CheckResult(check=f"frozen:{ch}", flagged=True, reason="x")])


OK = VerdictResult(verdict=Verdict.VALID, confidence=0.9, reason="ok")


# ---- the estimate and its band ----------------------------------------------------------------------
def test_estimate_close_to_the_last_value_after_a_short_gap_and_the_band_is_narrow(series, table, settings):
    e = impute_value(recs(series[:100]), "temperature_c", series[100].timestamp, table, settings)
    assert abs(e.value - series[100].temperature_c) < 1.0
    assert e.lower < e.value < e.upper and e.age_minutes == 15 and "climatology" not in e.method
    assert "normal value" in e.method


def test_band_widens_as_the_gap_grows_for_the_same_target_time(series, table, settings):
    ts = series[100].timestamp                                            # same target time, older and older history
    widths = []
    for newest in (99, 95, 91):
        e = impute_value(recs(series[: newest + 1]), "humidity_pct", ts, table, settings)
        widths.append(e.upper - e.lower)
    assert widths[0] < widths[1] < widths[2]


def test_estimate_falls_back_to_the_normal_value_as_the_gap_grows(series, table, settings):
    ts = series[100].timestamp
    recent = impute_value(recs(series[:100]), "temperature_c", ts, table, settings)
    old = impute_value(recs(series[:92]), "temperature_c", ts, table, settings)
    normal = table.expected(ts, "temperature_c")
    assert abs(old.value - normal) < abs(recent.value - normal) + 0.3     # the older the gap, the closer to normal


def test_band_never_falls_below_the_sensor_noise(series, table, settings):
    floor = settings["normality"]["min_std"]["temperature_c"]
    e = impute_value(recs(series[:100]), "temperature_c", series[99].timestamp + timedelta(seconds=1), table, settings)
    assert (e.upper - e.lower) / 2 >= settings["impute"]["band_z"] * floor


def test_the_band_covers_about_the_stated_share_of_true_values(series, table, settings):
    """Calibration check on clean synthetic data: the 95 % band should cover at least ~90 %."""
    r = recs(series)
    for gap in (2, 8):
        hit = n = 0
        for i in range(gap + 40, len(series)):
            for ch in CHANNELS:
                e = impute_value(r[: i - gap + 1], ch, series[i].timestamp, table, settings)
                n += 1
                hit += e.lower <= getattr(series[i], ch) <= e.upper
        assert hit / n > 0.90


def test_without_a_table_it_uses_the_last_trusted_value_and_a_band_that_grows(settings):
    h = make_history(20, cadence=15)
    r = recs(h)
    a = impute_value(r, "temperature_c", h[-1].timestamp + timedelta(minutes=15), None, settings)
    b = impute_value(r, "temperature_c", h[-1].timestamp + timedelta(minutes=120), None, settings)
    assert a.value == b.value == h[-1].temperature_c and "no normal pattern" in a.method
    assert (b.upper - b.lower) > (a.upper - a.lower)


def test_nothing_is_invented_when_the_last_trusted_value_is_too_old(settings):
    h = make_history(5, cadence=15)
    late = h[-1].timestamp + timedelta(minutes=settings["impute"]["lookback_minutes"] + 1)
    assert impute_value(recs(h), "temperature_c", late, None, settings) is None
    assert impute_value([], "temperature_c", late, None, settings) is None


def test_faulty_and_missing_values_are_not_trusted(settings):
    h = make_history(6, cadence=15, t=lambda i: 10.0 * i)
    r = recs(h[:4]) + recs(h[4:], Verdict.FAULT, {"temperature_c"})       # the last two temperatures were faulty
    e = impute_value(r, "temperature_c", h[-1].timestamp + timedelta(minutes=15), None, settings)
    assert e.value == h[3].temperature_c and e.age_minutes == 15 * 3
    r2 = recs(h[:4]) + recs(h[4:], Verdict.FAULT, {"pressure_hpa"})       # a fault on ANOTHER channel does not matter
    assert impute_value(r2, "temperature_c", h[-1].timestamp + timedelta(minutes=15), None, settings).value == h[-1].temperature_c


# ---- which channels get an estimate ---------------------------------------------------------------------
def test_missing_channel_gets_an_estimate_and_the_raw_reading_stays_missing(settings):
    h = make_history(20, cadence=15)
    cur = make_reading(20 * 15, p=None)
    imp = impute_reading(cur, OK, recs(h), None, settings)
    assert set(imp.channels) == {"pressure_hpa"} and cur.pressure_hpa is None
    v = apply_imputation(OK, imp)
    assert v.imputed_pressure_hpa == imp.channels["pressure_hpa"].value and v.imputed_temperature_c is None
    assert OK.imputation is None                                          # the original verdict is not modified


def test_faulty_channel_gets_an_estimate_and_the_raw_value_is_left_alone(settings):
    h = make_history(20, cadence=15)
    cur = make_reading(20 * 15, t=99.0)
    imp = impute_reading(cur, bad("temperature_c"), recs(h), None, settings)
    assert set(imp.channels) == {"temperature_c"} and cur.temperature_c == 99.0


def test_a_good_reading_gets_no_estimate(settings):
    h = make_history(20, cadence=15)
    assert impute_reading(make_reading(300), OK, recs(h), None, settings) is None


def test_a_suspect_reading_keeps_its_value_and_gets_no_estimate(settings):
    h = make_history(20, cadence=15)
    assert impute_reading(make_reading(300), bad("temperature_c", Verdict.SUSPECT), recs(h), None, settings) is None


def test_impute_layer_can_be_switched_off(settings):
    settings["layers"]["impute"] = False
    h = make_history(20, cadence=15)
    assert impute_reading(make_reading(300, p=None), OK, recs(h), None, settings) is None


# ---- gap filling --------------------------------------------------------------------------------------
def test_fill_gaps_estimates_the_missing_sample_times(settings):
    h = make_history(10, cadence=15) + [make_reading(9 * 15 + 75)]        # 75 min gap = 4 missing samples
    filled = fill_gaps(h, settings, 15.0)
    assert [ts for ts, _ in filled] == [h[9].timestamp + timedelta(minutes=15 * k) for k in (1, 2, 3, 4)]
    assert all(set(est) == set(CHANNELS) for _, est in filled)
    assert len(h) == 11                                                    # the input is not changed


def test_fill_gaps_ignores_normal_spacing_and_is_capped(settings):
    assert fill_gaps(make_history(10, cadence=15), settings, 15.0) == []
    settings["impute"]["max_fill_samples"] = 2
    settings["impute"]["lookback_minutes"] = 10_000
    h = make_history(5, cadence=15) + [make_reading(4 * 15 + 600)]
    assert len(fill_gaps(h, settings, 15.0)) == 2


# ---- through the pipeline ------------------------------------------------------------------------------------
def test_pipeline_dropout_keeps_the_raw_none_and_adds_an_estimate_with_a_band(settings):
    pipe = Pipeline(settings, {"S1": {"cadence_minutes": 15}})
    for r in make_history(30, cadence=15):
        pipe.process(r)
    v = pipe.process(make_reading(30 * 15, p=None))
    est = v.imputation.channels["pressure_hpa"]
    assert v.verdict == Verdict.FAULT and est.lower < est.value < est.upper
    assert v.imputed_pressure_hpa == est.value


def test_pipeline_estimate_ignores_earlier_faulty_values(settings):
    pipe = Pipeline(settings, {"S1": {"cadence_minutes": 15}})
    for r in make_history(30, cadence=15):
        pipe.process(r)
    pipe.process(make_reading(30 * 15, rh=140.0))                         # impossible humidity -> FAULT
    v = pipe.process(make_reading(31 * 15, rh=None))
    assert abs(v.imputation.channels["humidity_pct"].value - 50.0) < 1.0  # about the good history, not 140
