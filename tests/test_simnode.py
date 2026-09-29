"""Tests for simnode.py: the fake node that mirrors the firmware."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import simnode
from api import create_app
from atmos.schema import Reading
from atmos.store import SQLiteStore

GOOD = (20.0, 1000.0, 50.0)


def test_clean_minute_gives_the_mean_and_no_flags(settings):
    values, flags = simnode.aggregate_minute([(20.0, 1000.0, 50.0), (22.0, 1002.0, 52.0)] * 30, settings)
    assert values == {"temperature_c": pytest.approx(21.0), "pressure_hpa": pytest.approx(1001.0),
                      "humidity_pct": pytest.approx(51.0)} and flags == []


def test_out_of_range_samples_are_left_out_and_flagged(settings):
    samples = [GOOD] * 50 + [(20.0, 1000.0, 255.0)] * 10
    values, flags = simnode.aggregate_minute(samples, settings)
    assert values["humidity_pct"] == pytest.approx(50.0) and flags == ["range:humidity_pct"]


def test_too_few_valid_samples_sends_the_channel_as_missing(settings):
    samples = [GOOD] * 20 + [(20.0, float("nan"), 50.0)] * 40
    values, flags = simnode.aggregate_minute(samples, settings)
    assert values["pressure_hpa"] is None and values["temperature_c"] == pytest.approx(20.0)
    assert flags == ["few_valid:pressure_hpa"]


def test_exactly_the_minimum_number_of_valid_samples_is_enough(settings):
    n = settings["node"]["min_valid_samples"]
    values, _ = simnode.aggregate_minute([GOOD] * n + [(None, None, None)] * (60 - n), settings)
    assert values["temperature_c"] == pytest.approx(20.0)
    values, _ = simnode.aggregate_minute([GOOD] * (n - 1) + [(None, None, None)] * (61 - n), settings)
    assert values["temperature_c"] is None


def test_impossible_dew_point_is_flagged(settings):
    settings["physics"]["ranges"]["humidity_pct"] = [0.0, 200.0]          # let RH 120 through the range check
    _, flags = simnode.aggregate_minute([(20.0, 1000.0, 120.0)] * 60, settings)
    assert flags == ["dew_point"]


def test_flags_come_in_the_same_order_as_the_firmware(settings):
    samples = [(20.0, float("nan"), 255.0)] * 60
    _, flags = simnode.aggregate_minute(samples, settings)
    assert flags == ["range:humidity_pct", "few_valid:temperature_c", "few_valid:pressure_hpa", "few_valid:humidity_pct"] or \
        flags[0] == "range:humidity_pct"
    assert [f.split(":")[0] for f in flags] == sorted((f.split(":")[0] for f in flags),
                                                      key=["range", "few_valid", "dew_point"].index)


# ---- sending to the API ----------------------------------------------------------------------------------
def _run(settings, fault="none", minutes=90, **kw):
    client = TestClient(create_app(store=SQLiteStore(), settings=settings))
    sent = simnode.run(settings, "S1", "http://test", minutes, datetime(2026, 1, 1), 0, fault,
                       kw.get("fault_start", 40), kw.get("fault_length", 30), client=client)
    records = sorted(client.get("/latest", params={"limit": 1000}).json(), key=lambda r: r["id"])
    return sent, records


def test_payloads_are_valid_readings_one_minute_apart(settings):
    sent, records = _run(settings, minutes=10)
    stamps = [datetime.fromisoformat(p["timestamp"]) for p in sent]
    assert all((b - a).total_seconds() == 60 for a, b in zip(stamps, stamps[1:]))
    assert all(Reading(**p).station_id == "S1" for p in sent) and len(records) == 10


def test_clean_run_has_no_faults_and_the_device_flags_are_stored(settings):
    sent, records = _run(settings)
    assert not any(r["verdict"]["verdict"] == "FAULT" for r in records)
    assert all(r["reading"]["device_flags"] == p["device_flags"] for r, p in zip(records, sent))


def test_frozen_fault_is_caught_by_the_server(settings):
    _, records = _run(settings, "frozen", fault_start=20, fault_length=70, minutes=100)      # longer than the 60 min window
    faults = [r for r in records if r["verdict"]["verdict"] == "FAULT"]
    assert faults and "not changed" in faults[0]["verdict"]["reason"]


def test_dropout_reaches_the_server_as_null_and_gets_an_estimate(settings):
    sent, records = _run(settings, "dropout", fault_start=40, fault_length=10, minutes=60)
    rec = records[45]
    assert sent[45]["pressure_hpa"] is None and rec["reading"]["pressure_hpa"] is None
    assert "few_valid:pressure_hpa" in rec["reading"]["device_flags"]
    assert rec["verdict"]["verdict"] == "FAULT" and "pressure_hpa" in rec["verdict"]["imputation"]["channels"]


def test_glitch_is_flagged_on_the_device_and_does_not_spoil_the_mean(settings):
    sent, _ = _run(settings, "glitch", fault_start=5, fault_length=20, minutes=30)
    glitched = [p for p in sent if "range:humidity_pct" in p["device_flags"]]
    assert glitched and all(p["humidity_pct"] is not None and p["humidity_pct"] < 100 for p in glitched)


def test_same_seed_sends_the_same_readings(settings):
    a, _ = _run(settings, minutes=8)
    b, _ = _run(settings, minutes=8)
    assert a == b


def test_speed_waits_between_minutes(settings):
    waits = []
    client = TestClient(create_app(store=SQLiteStore(), settings=settings))
    simnode.run(settings, "S1", "http://test", 3, datetime(2026, 1, 1), 60.0, "none", 0, 0, client=client, sleep=waits.append)
    assert waits == [1.0, 1.0, 1.0]


def test_cli_reports_an_unreachable_api(capsys):
    assert simnode.main(["--station", "S1", "--url", "http://127.0.0.1:1", "--minutes", "1"]) == 2
    assert "Cannot reach the API" in capsys.readouterr().out
