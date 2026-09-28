"""Tests for atmos/timing.py: T1 clock / diurnal-phase check and T2 co-jump check."""
from datetime import timedelta

import pytest

import evaluate as ev
from atmos.fusion import Pipeline
from atmos.normality import NormalityTable
from atmos.schema import Verdict
from atmos.timing import check_clock, check_cojump, check_timing
from tests.conftest import by_name, make_history, make_reading


@pytest.fixture(scope="module")
def table():
    from atmos.config import load_settings
    s = load_settings()
    return NormalityTable.fit(ev.synthetic_series(s, 20, 1), s)


@pytest.fixture(scope="module")
def day():
    from atmos.config import load_settings
    return ev.synthetic_series(load_settings(), 3, 9)[:200]          # 50 h of 15-min data, all in the table's month


def _shifted(readings, hours):
    return [r.model_copy(update={"timestamp": r.timestamp + timedelta(hours=hours)}) for r in readings]


# ---- T1 --------------------------------------------------------------------------------------------
def test_correct_clock_is_not_flagged(day, table, settings):
    r = check_clock(day, table, settings)
    assert not r.flagged and r.severity == "soft" and "no time shift" in r.reason


@pytest.mark.parametrize("hours, fix", [(3, -3), (-2, 2), (1, -1)])
def test_shifted_clock_is_flagged_with_the_shift_that_fixes_it(day, table, settings, hours, fix):
    r = check_clock(_shifted(day, hours), table, settings)
    assert r.flagged and f"{fix:+d} h" in r.reason and "clock may be wrong" in r.reason


def test_clock_check_needs_a_day_of_data(day, table, settings):
    r = check_clock(day[:20], table, settings)                        # 5 hours
    assert not r.flagged and "needs" in r.reason


def test_clock_check_needs_the_normal_pattern(day, settings):
    r = check_clock(day, None, settings)
    assert not r.flagged and "no normal daily pattern" in r.reason


def test_a_shift_must_improve_the_fit_enough(day, table, settings):
    settings["timing"]["clock"]["min_improvement"] = 0.999            # almost impossible to satisfy
    assert not check_clock(_shifted(day, 3), table, settings).flagged


def test_clock_check_handles_missing_values(day, table, settings):
    holes = [r.model_copy(update={"temperature_c": None}) if i % 3 == 0 else r for i, r in enumerate(day)]
    assert not check_clock(holes, table, settings).flagged


# ---- T2 --------------------------------------------------------------------------------------------
def test_two_channels_jumping_together_is_flagged(settings):
    h = make_history(30) + [make_reading(30, t=35.0, rh=95.0)]
    r = check_cojump(h, settings, 1.0)
    assert r.flagged and r.severity == "hard" and "temperature_c" in r.reason and "humidity_pct" in r.reason


def test_one_channel_jumping_alone_is_not_a_cojump(settings):
    h = make_history(30) + [make_reading(30, t=35.0)]
    assert not check_cojump(h, settings, 1.0).flagged


def test_cojump_scales_with_cadence(settings):
    h = make_history(30, cadence=15) + [make_reading(29 * 15 + 15, t=26.0, rh=70.0)]     # fine over 15 min
    assert not check_cojump(h, settings, 15.0).flagged
    h1 = make_history(30) + [make_reading(30, t=26.0, rh=70.0)]                          # same change in 1 min
    assert check_cojump(h1, settings, 1.0).flagged


def test_cojump_needs_two_readings(settings):
    assert not check_cojump(make_history(1), settings, 1.0).flagged


def test_timing_layer_can_be_switched_off(day, table, settings):
    settings["layers"]["timing"] = False
    assert check_timing(day, table, settings, 15.0) == []
    settings["layers"]["timing"] = True
    assert [c.check for c in check_timing(day, table, settings, 15.0)] == ["clock", "cojump"]


# ---- through the pipeline -----------------------------------------------------------------------------
def test_pipeline_raises_the_clock_flag_and_a_suspect_verdict(day, table, settings):
    pipe = Pipeline(settings, {"S1": {"cadence_minutes": 15}}, {"S1": table})
    verdicts = [pipe.process(r) for r in _shifted(day, 3)]
    last = verdicts[-1]
    assert any(c.check == "clock" and c.flagged for c in last.checks)
    assert last.verdict == Verdict.SUSPECT and "moved by -3 h" in last.reason


def test_pipeline_does_not_flag_a_correct_clock(day, table, settings):
    pipe = Pipeline(settings, {"S1": {"cadence_minutes": 15}}, {"S1": table})
    verdicts = [pipe.process(r) for r in day]
    assert not any(c.check == "clock" and c.flagged for v in verdicts for c in v.checks)


def test_pipeline_cojump_gives_a_suspect_with_the_explanation(settings):
    pipe = Pipeline(settings, {"S1": {"cadence_minutes": 1}})
    for r in make_history(40):
        pipe.process(r)
    v = pipe.process(make_reading(40, t=35.0, rh=95.0))
    assert v.verdict == Verdict.SUSPECT and "jumped in the same sample" in v.reason


def test_clock_check_is_only_recomputed_once_per_hour(day, table, settings, monkeypatch):
    import atmos.fusion as fusion
    calls = []
    real = fusion.timing.check_clock
    monkeypatch.setattr(fusion.timing, "check_clock", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    pipe = Pipeline(settings, {"S1": {"cadence_minutes": 15}}, {"S1": table})
    for r in day[:48]:                                                # 12 hours of 15-min data
        pipe.process(r)
    assert 10 <= len(calls) <= 13
