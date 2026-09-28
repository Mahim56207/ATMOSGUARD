"""Tests for atmos/schema.py: what a Reading accepts and how it normalises it."""
from datetime import datetime

import pytest
from pydantic import ValidationError

from atmos.schema import Reading

BASE = {"station_id": "S1", "timestamp": "2026-01-01T00:00:00", "temperature_c": 20.0, "pressure_hpa": 1000.0, "humidity_pct": 50.0}


def test_zone_aware_timestamps_become_utc_without_a_zone():
    assert Reading(**{**BASE, "timestamp": "2026-01-01T02:00:00+02:00"}).timestamp == datetime(2026, 1, 1, 0, 0)
    assert Reading(**{**BASE, "timestamp": "2026-01-01T00:00:00Z"}).timestamp == datetime(2026, 1, 1, 0, 0)
    assert Reading(**BASE).timestamp.tzinfo is None


def test_readings_from_different_senders_can_be_compared():
    a, b = Reading(**BASE), Reading(**{**BASE, "timestamp": "2026-01-01T00:01:00Z"})
    assert (b.timestamp - a.timestamp).total_seconds() == 60          # would raise TypeError if one were zone-aware


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_values_that_are_not_measurements_are_kept_as_missing(bad):
    r = Reading(**{**BASE, "temperature_c": bad, "humidity_pct": bad})
    assert r.temperature_c is None and r.humidity_pct is None and r.pressure_hpa == 1000.0


def test_real_and_extreme_finite_values_are_kept_as_they_are():
    r = Reading(**{**BASE, "temperature_c": 1e308, "pressure_hpa": -5.0, "humidity_pct": 0.0})
    assert (r.temperature_c, r.pressure_hpa, r.humidity_pct) == (1e308, -5.0, 0.0)


@pytest.mark.parametrize("station", ["", "x" * 65])
def test_station_id_must_be_1_to_64_characters(station):
    with pytest.raises(ValidationError):
        Reading(**{**BASE, "station_id": station})
    assert Reading(**{**BASE, "station_id": "x" * 64}).station_id == "x" * 64
