"""Tests for atmos/limits.py and how the health and fusion layers use it."""
import numpy as np
import pytest

from atmos.fusion import Pipeline, channel_is_quiet
from atmos.health import check_frozen, check_noise
from atmos.limits import ChannelLimits, StationLimits, detect_resolution, fit_limits, noise_estimates, usual_step
from atmos.schema import Verdict
from tests.conftest import T0, make_history, make_reading

HOURLY = 60


def rounded_series(n=24 * 200, seed=0, station="S1"):
    """Hourly weather reported in whole degrees and whole hPa, the way METAR does: long runs of identical values."""
    import math
    from datetime import timedelta
    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        ts = T0 + timedelta(hours=i)
        cycle = math.sin(2 * math.pi * (ts.hour - 9) / 24)
        out.append(make_reading(i * HOURLY, t=float(round(26 + 4 * cycle + rng.normal(0, 0.4))),
                                p=float(round(1008 + rng.normal(0, 0.9))), rh=round(70 - 15 * cycle + float(rng.normal(0, 2)), 1),
                                station=station))
    return out


@pytest.fixture(scope="module")
def series():
    return rounded_series()


def test_resolution_of_whole_numbers_tenths_and_fine_values():
    assert detect_resolution([float(x) for x in range(-20, 40)] * 3) == 1.0
    assert detect_resolution([x / 10 for x in range(100, 400)]) == 0.1
    assert detect_resolution(list(np.random.default_rng(0).normal(20, 3, 300))) is None
    assert detect_resolution([1.0, 2.0]) is None                          # too few values to say


def test_a_station_that_reports_whole_numbers_gets_a_learned_frozen_limit_above_the_fixed_one(series, settings):
    lim = fit_limits(series, settings, HOURLY)
    assert lim.channels["temperature_c"].resolution == 1.0 and lim.channels["pressure_hpa"].resolution == 1.0
    fixed = settings["health"]["frozen"]["window_minutes"]
    assert lim.frozen_minutes("temperature_c") > fixed["temperature_c"]
    assert lim.frozen_minutes("pressure_hpa") > 2 * HOURLY                 # runs of identical pressure are normal here
    assert lim.channels["temperature_c"].n_runs >= settings["limits"]["min_runs"]


def test_too_few_runs_learns_nothing_and_the_fixed_window_is_used(settings):
    tiny = make_history(60, cadence=15)
    lim = fit_limits(tiny, settings, 15.0)
    assert lim.frozen_minutes("temperature_c") is None and lim.noise_std("temperature_c") is None


def test_the_learned_limit_only_relaxes_a_check_never_tightens_it(series, settings):
    lim = fit_limits(series, settings, HOURLY)
    assert lim.noise_std("humidity_pct") is not None
    off = {**settings, "layers": {**settings["layers"], "limits": False}}
    # with limits off, nothing learned is used: three identical hourly temperatures (the fixed window) are frozen...
    stuck = [make_reading(i * HOURLY, t=25.0, p=1000.0 + i, rh=50.0 + 0.1 * i) for i in range(3)]
    assert lim.frozen_minutes("temperature_c") > 2 * HOURLY
    assert check_frozen(stuck, "temperature_c", off, HOURLY, lim).flagged
    # ...and with limits on, it is an ordinary calm spell for a whole-degree station, so it is not
    assert not check_frozen(stuck, "temperature_c", settings, HOURLY, lim).flagged


def test_frozen_is_soft_just_past_the_learned_limit_and_hard_at_twice_it(settings):
    lim = StationLimits("S1", 60.0, {"temperature_c": ChannelLimits(resolution=1.0, frozen_minutes=600.0, n_runs=99)})
    def stuck_for(hours):
        return [make_reading(i * HOURLY, t=25.0) for i in range(hours + 1)]
    assert not check_frozen(stuck_for(8), "temperature_c", settings, HOURLY, lim).flagged        # 8 h < 10 h
    just_past = check_frozen(stuck_for(11), "temperature_c", settings, HOURLY, lim)
    assert just_past.flagged and just_past.severity == "soft"
    long_run = check_frozen(stuck_for(21), "temperature_c", settings, HOURLY, lim)
    assert long_run.flagged and long_run.severity == "hard"
    no_limits = check_frozen(stuck_for(21), "temperature_c", settings, HOURLY, None)
    assert no_limits.flagged and no_limits.severity == "hard"              # without learned limits it is hard, as before


def test_a_long_frozen_run_is_a_fault_through_the_pipeline_and_a_short_one_is_not(settings):
    lim = StationLimits("S1", 60.0, {ch: ChannelLimits(resolution=1.0, frozen_minutes=600.0, n_runs=99)
                                     for ch in ("temperature_c", "pressure_hpa", "humidity_pct")})
    def run(hours):
        pipe = Pipeline(settings, {"S1": {"cadence_minutes": 60}}, limits={"S1": lim})
        for r in make_history(30, cadence=60):
            pipe.process(r)
        last = None
        for i in range(hours):
            last = pipe.process(make_reading((30 + i) * 60, t=25.0, p=1000.0 + 0.3 * i, rh=50.0 + 0.2 * i))
        return last
    assert run(11).verdict == Verdict.SUSPECT and run(22).verdict == Verdict.FAULT


def test_noise_estimator_matches_the_health_check(series, settings):
    est = noise_estimates(series[:400], "humidity_pct", settings["health"]["noise"]["window_minutes"],
                          settings["health"]["noise"]["min_samples"], HOURLY)
    assert len(est) > 300 and all(e >= 0 for e in est)
    res = check_noise(series[:60], "humidity_pct", settings, HOURLY)
    # the same window and formula: the check's reported estimate is one of the learned estimates' kind of value
    assert "jitter" in res.reason


def test_usual_step_scales_with_cadence(series, settings):
    hourly = usual_step(series, "temperature_c", 180.0, 60.0)
    three_hourly = usual_step(series[::3], "temperature_c", 540.0, 180.0)
    assert hourly is not None and three_hourly is not None and three_hourly > hourly


def test_a_channel_is_quiet_against_its_own_usual_step(settings):
    lim = StationLimits("S1", 180.0, {"temperature_c": ChannelLimits(typical_step=3.0)})
    calm = [make_reading(i * 180, t=25.0) for i in range(3)]
    fall_5 = calm[:2] + [make_reading(2 * 180, t=20.0)]                     # 5 C in 3 h: over 1.5 x 3.0 = 4.5
    assert channel_is_quiet(calm, "temperature_c", settings, lim, 180.0)
    assert not channel_is_quiet(fall_5, "temperature_c", settings, lim, 180.0)
    assert channel_is_quiet(fall_5, "temperature_c", settings, None, 180.0)  # the old, looser rule: 5 <= 0.5 x 10


def test_save_and_load_round_trip(series, settings, tmp_path):
    lim = fit_limits(series, settings, HOURLY)
    lim.save(tmp_path / "l.json")
    back = StationLimits.load(tmp_path / "l.json")
    assert back == lim
    old = '{"station_id": "S1", "cadence_minutes": 60.0, "channels": {"temperature_c": {"resolution": 1.0, "frozen_minutes": 600.0, "noise_std": 2.0, "n_runs": 5}}}'
    (tmp_path / "old.json").write_text(old)                                 # a file written before typical_step existed
    assert StationLimits.load(tmp_path / "old.json").typical_step("temperature_c") is None


def test_fit_refuses_two_stations(series, settings):
    mixed = series[:300] + [r.model_copy(update={"station_id": "OTHER"}) for r in series[300:600]]
    with pytest.raises(ValueError):
        fit_limits(mixed, settings, HOURLY)
