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


def test_theil_sen_finds_drift_and_projects_service_date(settings, table):
    recs = [rec(i, offset=0.05 * (i * CADENCE / 1440.0) * 10, table=table) for i in range(600)]   # 0.5 C per day
    rep = compute_health("S1", recs, table, now_of(recs), settings)
    ch = rep.channels["temperature_c"]
    assert ch.drift_significant and ch.drift_per_day == pytest.approx(0.5, rel=0.05)
    assert ch.service_date is not None and ch.score < 100
    # limit is 0.5 C; offset now is ~3.1 C, already beyond it -> service due today
    assert ch.service_date == now_of(recs).date()


def test_service_date_is_in_the_future_when_limit_not_reached(settings, table):
    settings["healthscore"]["drift"]["service_limit"]["temperature_c"] = 5.0
    recs = [rec(i, offset=0.5 * (i * CADENCE / 1440.0), table=table) for i in range(600)]     # 0.5 C per day, ~3.1 C now
    rep = compute_health("S1", recs, table, now_of(recs), settings)
    ch = rep.channels["temperature_c"]
    expected_days = (5.0 - ch.offset_now) / ch.drift_per_day
    assert ch.service_date == (now_of(recs) + timedelta(days=expected_days)).date()
    assert 3 <= expected_days <= 5


def test_no_significant_drift_means_no_service_date(settings, table):
    recs = [rec(i, table=table) for i in range(600)]
    ch = compute_health("S1", recs, table, now_of(recs), settings).channels["temperature_c"]
    assert not ch.drift_significant and ch.service_date is None


def test_drift_not_measured_without_a_table(settings):
    recs = [rec(i) for i in range(200)]
    assert "no normality table" in compute_health("S1", recs, None, now_of(recs), settings).channels["temperature_c"].note


def test_faulty_samples_are_not_counted_twice_as_drift(settings, table):
    recs = [rec(i, Verdict.FAULT, {"temperature_c"}, offset=8.0, table=table) if i > 300 else rec(i, table=table)
            for i in range(600)]
    assert not compute_health("S1", recs, table, now_of(recs), settings).channels["temperature_c"].drift_significant


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


def test_ticket_for_upcoming_service_date(settings, table):
    settings["healthscore"]["drift"]["service_limit"]["temperature_c"] = 5.0
    recs = [rec(i, offset=0.5 * (i * CADENCE / 1440.0), table=table) for i in range(600)]
    rep = compute_health("S1", recs, table, now_of(recs), settings)
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
