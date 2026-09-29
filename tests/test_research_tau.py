"""research/tau_rh.py: the bench analysis recovers a known answer, and the study says what it should."""
import numpy as np
import pytest

from research import tau_rh


def test_first_order_response_hits_63_percent_at_tau():
    t = np.arange(0, 600.0)
    x = np.where(t < 100, 20.0, 80.0)
    y = tau_rh.first_order(x, 25.0, 1.0)
    assert tau_rh.response_time_63(t, y, 100.0, 300.0) == pytest.approx(25.0, abs=1.5)


def test_onset_is_found_where_the_step_is_not_a_minute_early():
    t = np.arange(0, 600.0)
    y = tau_rh.first_order(np.where(t < 200, 20.0, 80.0), 10.0, 1.0)
    steps = tau_rh.find_transitions(t, y)
    assert len(steps) == 1 and steps[0] == pytest.approx(200.0, abs=3.0)


def test_selftest_recovers_the_known_time_constants_and_the_rank_test_is_significant():
    r = tau_rh.selftest()
    assert r["usable"] >= 8
    assert r["median_clean_s"] == pytest.approx(10.0, abs=2.0) and r["median_covered_s"] == pytest.approx(40.0, abs=4.0)
    assert r["ratio"] > 3 and r["p_value"] < 0.01


def test_a_temperature_mismatch_makes_a_transition_unusable():
    rng = np.random.default_rng(1)
    s = tau_rh.simulate_pair(10.0, 40.0, 3600, rng, boxes=True)
    temp = np.full_like(s["t"], 24.0)
    bad = tau_rh.analyse_bench(s["t"], s["clean"], s["covered"], temp, temp + 0.8)      # 0.8 C apart: thermal lag risk
    assert bad["usable"] == 0 and "ratio" not in bad


def test_the_pair_recovers_the_lag_at_1hz_but_not_at_15_minute_means():
    rows = tau_rh.study(seed=5, hours=6, repeats=6)
    by = {(r["fouled_tau_s"], r["resolution"]): r for r in rows}
    assert by[(40.0, "1 s")]["within_30pct"] == "100%"
    assert by[(40.0, "15 min mean")]["within_30pct"] == "0%"
    assert by[(20.0, "1 min mean")]["within_30pct"] == "0%"
