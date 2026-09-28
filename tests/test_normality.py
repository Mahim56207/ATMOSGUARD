"""Tests for atmos/normality.py (L2)."""
import pytest

from atmos.health import check_drift
from atmos.injector import FaultSpec, inject
from atmos.normality import NormalityTable, check_normality
from tests.conftest import by_name, make_reading, synthetic_readings


@pytest.fixture
def clean():
    return synthetic_readings(days=20, cadence=15)


@pytest.fixture
def table(clean, settings):
    return NormalityTable.fit(clean, settings)


def test_expected_follows_the_daily_cycle(table):
    afternoon = table.expected(make_reading(minute=15 * 60).timestamp, "temperature_c")   # 15:00
    night = table.expected(make_reading(minute=3 * 60).timestamp, "temperature_c")        # 03:00
    assert afternoon > night + 8                                          # true swing is 12 C


def test_normal_reading_not_flagged(table, settings):
    r = make_reading(minute=12 * 60, t=table.expected(make_reading(minute=12 * 60).timestamp, "temperature_c"),
                     p=1010.0, rh=table.expected(make_reading(minute=12 * 60).timestamp, "humidity_pct"))
    res = check_normality(r, table, settings)
    assert not by_name(res, "normality:temperature_c").flagged
    assert not by_name(res, "normality:humidity_pct").flagged


def test_outlier_flagged_with_reason_and_soft(table, settings):
    r = make_reading(minute=12 * 60, t=40.0)
    c = by_name(check_normality(r, table, settings), "normality:temperature_c")
    assert c.flagged and c.severity == "soft" and "standard deviations" in c.reason


def test_cell_with_too_little_data_is_not_scored(clean, settings):
    settings["normality"]["min_samples_per_cell"] = 10_000
    empty = NormalityTable.fit(clean, settings)
    c = by_name(check_normality(clean[0], empty, settings), "normality:temperature_c")
    assert not c.flagged and "not enough data" in c.reason


def test_missing_value_is_skipped(table, settings):
    c = by_name(check_normality(make_reading(t=None), table, settings), "normality:temperature_c")
    assert not c.flagged


def test_single_station_only(clean, settings):
    mixed = clean[:50] + [make_reading(t=20.0, station="OTHER")]
    with pytest.raises(ValueError):
        NormalityTable.fit(mixed, settings)


def test_save_and_load_roundtrip(table, settings, tmp_path):
    table.save(tmp_path / "S1_normality.json")
    loaded = NormalityTable.load(tmp_path / "S1_normality.json", settings)
    ts = make_reading(minute=600).timestamp
    assert loaded.station_id == "S1" and loaded.expected(ts, "pressure_hpa") == table.expected(ts, "pressure_hpa")


def test_normality_layer_can_be_switched_off(table, settings):
    settings["layers"]["normality"] = False
    assert check_normality(make_reading(t=99.0), table, settings) == []


def test_expected_series_lets_health_detect_injected_drift(clean, table, settings):
    res = inject(clean, settings, [FaultSpec("drift", "temperature_c", 500)])
    end = res.events[0].end_index
    history = res.readings[: end + 1]
    expected = table.expected_series(history)
    assert check_drift(history, "temperature_c", expected["temperature_c"], settings).flagged
    clean_hist = clean[: end + 1]
    assert not check_drift(clean_hist, "temperature_c", table.expected_series(clean_hist)["temperature_c"], settings).flagged
