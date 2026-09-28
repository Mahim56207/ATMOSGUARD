"""Tests for atmos/health.py (L1). One test per QC rule, plus cadence scaling and layer toggle."""
from datetime import timedelta

from atmos.health import check_health, cusum
from tests.conftest import T0, by_name, make_history, make_reading


def _run(history, settings, cadence=1, **kw):
    return check_health(history, settings, cadence, **kw)


def test_clean_history_raises_no_flags(settings):
    res = _run(make_history(200), settings)
    assert [r.check for r in res if r.flagged] == []


def test_frozen_temperature_flagged(settings):
    h = make_history(100, t=lambda i: 20.0)
    r = by_name(_run(h, settings), "frozen:temperature_c")
    assert r.flagged and "not changed" in r.reason


def test_frozen_needs_enough_history(settings):
    h = make_history(10, t=lambda i: 20.0)          # only 9 min, window is 60
    r = by_name(_run(h, settings), "frozen:temperature_c")
    assert not r.flagged and "not enough history" in r.reason


def test_frozen_window_scales_with_cadence(settings):
    # hourly data: the 60-min window would hold 2 samples; it is stretched to min_samples
    h = make_history(6, cadence=60, t=lambda i: 20.0)
    assert by_name(_run(h, settings, cadence=60), "frozen:temperature_c").flagged
    h2 = make_history(6, cadence=60, t=lambda i: 20.0 + i)
    assert not by_name(_run(h2, settings, cadence=60), "frozen:temperature_c").flagged


def test_step_flagged(settings):
    h = make_history(30)
    h.append(make_reading(30, t=35.0))               # +15 C in 1 min
    r = by_name(_run(h, settings), "step:temperature_c")
    assert r.flagged and "jumped" in r.reason


def test_step_allowed_grows_with_time_apart(settings):
    # +8 C is too much in 1 min, but fine over 15 min
    h1 = make_history(30) + [make_reading(30, t=28.2)]
    assert by_name(_run(h1, settings), "step:temperature_c").flagged
    h2 = make_history(30, cadence=15)
    h2.append(make_reading(29 * 15 + 15, t=28.2))
    assert not by_name(_run(h2, settings, cadence=15), "step:temperature_c").flagged


def test_spike_flagged_on_previous_sample(settings):
    h = make_history(30)
    h.append(make_reading(30, t=40.0))
    h.append(make_reading(31, t=20.31))
    r = by_name(_run(h, settings), "spike:temperature_c")
    assert r.flagged and "one-sample spike" in r.reason


def test_no_spike_on_real_step_change(settings):
    h = make_history(30)
    h.append(make_reading(30, t=40.0))
    h.append(make_reading(31, t=40.1))
    assert not by_name(_run(h, settings), "spike:temperature_c").flagged


def test_noise_flagged(settings):
    h = make_history(60, t=lambda i: 20.0 + (3.0 if i % 2 else -3.0) * (i > 40))
    assert by_name(_run(h, settings), "noise:temperature_c").flagged


def test_dropout_flagged(settings):
    h = make_history(20)
    h[-1] = make_reading(19, p=None)
    r = by_name(_run(h, settings), "dropout")
    assert r.flagged and "pressure_hpa" in r.reason


def test_gap_flagged_and_scales_with_cadence(settings):
    h = make_history(20)
    h.append(make_reading(30))                       # 11 min after the last one
    assert by_name(_run(h, settings), "gap").flagged
    h15 = make_history(20, cadence=15)
    h15.append(make_reading(19 * 15 + 30))           # 30 min later on a 15-min station
    assert not by_name(_run(h15, settings, cadence=15), "gap").flagged


def test_timestamp_duplicate_and_out_of_order(settings):
    h = make_history(5)
    h.append(make_reading(4))
    assert "duplicate" in by_name(_run(h, settings), "timestamp").reason
    h2 = make_history(5) + [make_reading(2)]
    assert "out-of-order" in by_name(_run(h2, settings), "timestamp").reason


def test_timestamp_in_future(settings):
    h = make_history(5)
    r = by_name(_run(h, settings, now=T0 - timedelta(hours=1)), "timestamp")
    assert r.flagged and "ahead of the server clock" in r.reason


def test_cusum_detects_small_persistent_offset():
    alarm, peak = cusum([1.5] * 30, sigma=1.0, k_sigma=0.5, h_sigma=5.0)
    assert alarm and peak >= 5.0


def test_cusum_ignores_noise_around_zero():
    alarm, _ = cusum([0.3, -0.4, 0.2, -0.3, 0.1] * 10, sigma=1.0, k_sigma=0.5, h_sigma=5.0)
    assert not alarm


def test_drift_flagged_with_expected_values(settings):
    h = make_history(100)
    expected = {"temperature_c": [r.temperature_c - 2.0 for r in h]}   # reading is 2 C above expected
    assert by_name(_run(h, settings, expected=expected), "drift:temperature_c").flagged


def test_drift_not_run_without_expected(settings):
    r = by_name(_run(make_history(100), settings), "drift:temperature_c")
    assert not r.flagged and "needs L2 normality" in r.reason


def test_every_check_has_a_reason(settings):
    assert all(r.reason for r in _run(make_history(100), settings))


def test_health_layer_can_be_switched_off(settings):
    settings["layers"]["health"] = False
    assert _run(make_history(100, t=lambda i: 20.0), settings) == []
