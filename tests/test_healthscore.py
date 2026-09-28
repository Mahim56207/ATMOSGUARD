"""Tests for atmos/healthscore.py: score, Theil-Sen drift, service date, ticket."""
from datetime import datetime, timedelta

import pytest

from atmos.healthscore import HealthRecord, compute_health, flagged_channels, to_health_record
from atmos.normality import NormalityTable
from atmos.schema import CHANNELS, CheckResult, Verdict, VerdictResult
from tests.conftest import T0, make_reading, synthetic_readings

CADENCE = 15


def rec(i, verdict=Verdict.VALID, flagged=(), offset=0.0, table=None, base=None):
    """One HealthRecord i samples in. Temperature = expected + offset."""
    ts = T0 + timedelta(minutes=i * CADENCE)
    exp = table.expected(ts, "temperature_c") if table else 20.0
    vals = {"temperature_c": exp + offset, "pressure_hpa": 1000.0, "humidity_pct": 50.0}
    return HealthRecord(ts, vals, verdict, frozenset(flagged))


def now_of(records):
    return records[-1].timestamp


@pytest.fixture(scope="module")
def table():
    from atmos.config import load_settings
    return NormalityTable.fit(synthetic_readings(days=20, cadence=CADENCE, noise_t=0.1), load_settings())


def test_no_score_before_enough_records(settings):
    recs = [rec(i) for i in range(5)]
    rep = compute_health("S1", recs, None, now_of(recs), settings)
    assert rep.score is None and "Not enough records" in rep.note and rep.ticket is None


def test_clean_station_scores_100_and_no_ticket(settings):
    recs = [rec(i) for i in range(200)]
    rep = compute_health("S1", recs, None, now_of(recs), settings)
    assert rep.score == 100 and rep.ticket is None


def test_faults_lower_only_the_flagged_channel_and_station_takes_the_worst(settings):
    recs = [rec(i, Verdict.FAULT, {"temperature_c"}) if i % 10 == 0 else rec(i) for i in range(200)]
    rep = compute_health("S1", recs, None, now_of(recs), settings)
    assert rep.channels["temperature_c"].score == pytest.approx(90.0, abs=0.5)      # 10% faulty x weight 100
    assert rep.channels["pressure_hpa"].score == 100
    assert rep.score == rep.channels["temperature_c"].score


def test_suspect_costs_less_than_fault(settings):
    fault = compute_health("S1", [rec(i, Verdict.FAULT, {"temperature_c"}) if i % 10 == 0 else rec(i) for i in range(200)],
                           None, T0 + timedelta(minutes=199 * CADENCE), settings)
    susp = compute_health("S1", [rec(i, Verdict.SUSPECT, {"temperature_c"}) if i % 10 == 0 else rec(i) for i in range(200)],
                          None, T0 + timedelta(minutes=199 * CADENCE), settings)
    assert susp.score > fault.score


def test_weather_never_counts_against_the_sensor(settings):
    recs = [rec(i, Verdict.WEATHER, {"temperature_c", "humidity_pct"}) for i in range(200)]
    assert compute_health("S1", recs, None, now_of(recs), settings).score == 100


def test_records_outside_the_window_are_ignored(settings):
    old = [rec(i, Verdict.FAULT, {"temperature_c"}) for i in range(50)]
    settings["healthscore"]["window_minutes"] = 24 * 60
    recent = [rec(i) for i in range(1000, 1200)]
    rep = compute_health("S1", old + recent, None, now_of(recent), settings)
    assert rep.score == 100


# ---- drift: daily means over ~45 days. Slow drift needs weeks of data, on purpose (see DriftTracker). ----------
HOURLY = 60


def hrec(i, verdict=Verdict.VALID, flagged=(), offset=0.0, table=None, rh_offset=0.0):
    """Every channel sits at its expected value, temperature plus `offset`. So only temperature can drift."""
    ts = T0 + timedelta(minutes=i * HOURLY)
    exp = {ch: (table.smooth_expected(ts, ch) if table else d)
           for ch, d in (("temperature_c", 20.0), ("pressure_hpa", 1000.0), ("humidity_pct", 50.0))}
    return HealthRecord(ts, {**exp, "temperature_c": exp["temperature_c"] + offset,
                             "humidity_pct": exp["humidity_pct"] + rh_offset}, verdict, frozenset(flagged))


@pytest.fixture(scope="module")
def long_table():
    """A table with a cell for every hour of Jan, Feb and Mar, and enough spread that a drift is not clipped."""
    from atmos.config import load_settings
    return NormalityTable.fit(synthetic_readings(days=85, cadence=HOURLY, noise_t=0.5), load_settings())


def _per_day(i):
    return i * HOURLY / 1440.0


def test_slow_drift_is_found_over_weeks_and_projects_a_service_date(settings, long_table):
    recs = [hrec(i, offset=0.02 * _per_day(i), table=long_table) for i in range(60 * 24)]      # 0.02 C per day
    rep = compute_health("S1", recs, long_table, now_of(recs), settings)
    ch = rep.channels["temperature_c"]
    assert ch.drift_significant and ch.drift_per_day == pytest.approx(0.02, rel=0.2)
    assert ch.drift_z >= settings["healthscore"]["drift"]["z_crit"]
    assert ch.service_date is not None and ch.score < 100
    # limit is 0.5 C; the offset is already ~1.2 C -> service is due today
    assert ch.service_date == now_of(recs).date()


def test_service_date_is_in_the_future_when_limit_not_reached(settings, long_table):
    settings["healthscore"]["drift"]["service_limit"]["temperature_c"] = 3.0
    recs = [hrec(i, offset=0.02 * _per_day(i), table=long_table) for i in range(60 * 24)]
    ch = compute_health("S1", recs, long_table, now_of(recs), settings).channels["temperature_c"]
    expected_days = (3.0 - ch.offset_now) / ch.drift_per_day
    assert ch.service_date == (now_of(recs) + timedelta(days=expected_days)).date()
    assert 60 <= expected_days <= 120


def test_a_few_days_of_data_never_claim_a_drift(settings, long_table):
    recs = [hrec(i, offset=0.5 * _per_day(i), table=long_table) for i in range(8 * 24)]     # steep, but only 8 days
    ch = compute_health("S1", recs, long_table, now_of(recs), settings).channels["temperature_c"]
    assert not ch.drift_significant and "usable days" in ch.note


def test_the_seasonal_cycle_is_not_read_as_drift(settings):
    """A station with a real annual cycle: the table has one cell per month, so its step function differs from the
    smooth cycle by up to half a month's change. Reading that as a trend is the failure this design removes."""
    import math
    from atmos.schema import Reading
    def season(ts):
        return 20 + 8 * math.sin(2 * math.pi * (ts.timetuple().tm_yday - 100) / 365)
    def series(start, days):
        return [Reading(station_id="S1", timestamp=start + timedelta(hours=k), temperature_c=season(start + timedelta(hours=k)),
                        pressure_hpa=1000.0, humidity_pct=50.0) for k in range(days * 24)]
    fit_on = series(datetime(2025, 1, 1), 365)
    table = NormalityTable.fit(fit_on, settings)
    test = series(datetime(2026, 3, 1), 90)                  # spring: the steepest part of the cycle
    recs = [HealthRecord(r.timestamp, {"temperature_c": r.temperature_c, "pressure_hpa": 1000.0, "humidity_pct": 50.0},
                         Verdict.VALID, frozenset()) for r in test]
    ch = compute_health("S1", recs, table, now_of(recs), settings).channels["temperature_c"]
    assert not ch.drift_significant, ch.note
    step_offsets = [r.values["temperature_c"] - table.expected(r.timestamp, "temperature_c") for r in recs]
    assert max(step_offsets) - min(step_offsets) > 2.0        # the plain table WOULD have shown a large fake trend


def test_a_trend_on_two_channels_is_read_as_weather_not_drift(settings, long_table):
    """Weather moves several channels, a drifting sensor moves one. Temperature and humidity trending together
    (as in a monsoon onset) must not be reported as a sick sensor."""
    settings["healthscore"]["drift"]["winsor_sigma"] = 10.0             # this test is about the rule, not the clipping
    recs = [hrec(i, offset=0.02 * _per_day(i), rh_offset=0.1 * _per_day(i), table=long_table) for i in range(60 * 24)]
    rep = compute_health("S1", recs, long_table, now_of(recs), settings)
    for ch in ("temperature_c", "humidity_pct"):
        assert not rep.channels[ch].drift_significant and "trending together" in rep.channels[ch].note
    assert rep.channels["temperature_c"].service_date is None


def test_a_trend_must_persist_for_several_days_before_it_is_claimed(settings, monkeypatch):
    """The per-window test is faked to be significant only on the last 3 daily evaluations. Three days of
    persistence claims the drift; four days does not."""
    import atmos.healthscore as hs
    now = datetime(2026, 3, 1)

    def fake_drift(ch, daily, when, settings, have_table):
        hot = ch == "temperature_c" and when >= now - timedelta(days=2)
        return {"drift_significant": hot, "drift_per_day": 0.1, "drift_z": 9.0 if ch == "temperature_c" else 0.0,
                "offset_now": 1.0, "note": "x"}
    monkeypatch.setattr(hs, "_drift", fake_drift)

    def claimed(persist):
        settings["healthscore"]["drift"]["persist_days"] = persist
        return hs.drift_all({ch: [] for ch in CHANNELS}, now, settings, True)["temperature_c"]
    assert claimed(3)["drift_significant"]
    four = claimed(4)
    assert not four["drift_significant"] and "not claimed as drift yet" in four["note"]


def test_the_floor_is_reported(settings, long_table):
    import math
    recs = [hrec(i, offset=0.3 * math.sin(i / 7.0), table=long_table) for i in range(60 * 24)]
    ch = compute_health("S1", recs, long_table, now_of(recs), settings).channels["temperature_c"]
    assert ch.drift_floor_per_day is not None and ch.drift_floor_per_day > 0 and "smallest visible slope" in ch.note


def test_no_significant_drift_means_no_service_date(settings, long_table):
    recs = [hrec(i, table=long_table) for i in range(60 * 24)]
    ch = compute_health("S1", recs, long_table, now_of(recs), settings).channels["temperature_c"]
    assert not ch.drift_significant and ch.service_date is None


def test_drift_not_measured_without_a_table(settings):
    recs = [rec(i) for i in range(200)]
    assert "no normality table" in compute_health("S1", recs, None, now_of(recs), settings).channels["temperature_c"].note


def test_faulty_samples_are_not_counted_twice_as_drift(settings, long_table):
    recs = [hrec(i, Verdict.FAULT, {"temperature_c"}, offset=8.0, table=long_table) if i > 30 * 24 else hrec(i, table=long_table)
            for i in range(60 * 24)]
    assert not compute_health("S1", recs, long_table, now_of(recs), settings).channels["temperature_c"].drift_significant


def test_ticket_opens_when_score_is_low(settings):
    recs = [rec(i, Verdict.FAULT, {"temperature_c"}) if i < 100 else rec(i) for i in range(200)]     # 50% faulty
    rep = compute_health("S1", recs, None, now_of(recs), settings)
    assert rep.score == 50 and rep.ticket and rep.ticket.priority == "normal"
    assert rep.ticket.channels == ["temperature_c"] and "health score 50" in rep.ticket.reason


def test_ticket_is_high_priority_when_sensor_is_broken_right_now(settings):
    recs = [rec(i, Verdict.FAULT, {"pressure_hpa"}) if i >= 190 else rec(i) for i in range(200)]     # last 10 samples
    rep = compute_health("S1", recs, None, now_of(recs), settings)
    assert rep.score > settings["healthscore"]["ticket"]["score_below"]              # long-run score still fine
    assert rep.ticket and rep.ticket.priority == "high" and "pressure_hpa" in rep.ticket.reason


def test_ticket_for_upcoming_service_date(settings, long_table):
    settings["healthscore"]["drift"]["service_limit"]["temperature_c"] = 1.6       # ~20 days away from a 1.2 C offset
    recs = [hrec(i, offset=0.02 * _per_day(i), table=long_table) for i in range(60 * 24)]
    rep = compute_health("S1", recs, long_table, now_of(recs), settings)
    assert rep.ticket and "projected to need service" in rep.ticket.reason and rep.ticket.priority == "normal"


def test_flagged_channels_mapping(settings):
    r = make_reading(p=None)
    checks = [CheckResult(check="step:temperature_c", flagged=True, reason="x"),
              CheckResult(check="dropout", flagged=True, reason="x"),
              CheckResult(check="dew_point", flagged=True, reason="x"),
              CheckResult(check="gap", flagged=True, reason="x"),
              CheckResult(check="range:humidity_pct", flagged=False, reason="x")]
    assert flagged_channels(checks, r, settings) == {"temperature_c", "pressure_hpa", "humidity_pct"}
    assert flagged_channels([checks[3]], r, settings) == frozenset()


def test_to_health_record_keeps_raw_values(settings):
    r = make_reading(t=21.5)
    v = VerdictResult(verdict=Verdict.SUSPECT, confidence=0.5, reason="x",
                      checks=[CheckResult(check="noise:temperature_c", flagged=True, reason="x")])
    hr = to_health_record(r, v, settings)
    assert hr.values["temperature_c"] == 21.5 and hr.flagged_channels == {"temperature_c"}
