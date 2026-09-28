"""Tests for atmos/fusion.py: one test per verdict rule, rule order, confidence, reasons, Pipeline."""
import pytest

from atmos.fusion import Pipeline, fuse, match_signature, movement
from atmos.injector import FaultSpec, inject
from atmos.mlmodel import IsolationModel
from atmos.normality import NormalityTable
from atmos.schema import CheckResult, Verdict
from tests.conftest import make_history, make_reading, synthetic_readings


def chk(name, flagged=True, severity="hard", reason=None):
    return CheckResult(check=name, flagged=flagged, severity=severity, reason=reason or f"{name} happened.")


def flat_history():
    return make_history(10, cadence=15, t=lambda i: 20.0, p=lambda i: 1000.0, rh=lambda i: 50.0)


def weather_history():
    """Last 60 min: temperature falls 6 C and humidity rises 32 %, pressure flat."""
    return make_history(10, cadence=15, t=lambda i: 20.0 - 1.5 * max(0, i - 5),
                        p=lambda i: 1000.0, rh=lambda i: 50.0 + 8.0 * max(0, i - 5))


def run(checks, settings, history=None):
    return fuse(checks, history or flat_history(), settings, cadence_minutes=15)


# ---- rule 1 -------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["range:temperature_c", "dew_point", "frozen:pressure_hpa", "dropout"])
def test_rule1_impossible_frozen_dropout_is_fault(name, settings):
    v = run([chk(name)], settings)
    assert v.verdict == Verdict.FAULT and f"{name} happened." in v.reason


def test_rule1_beats_weather(settings):
    v = run([chk("frozen:temperature_c"), chk("normality:humidity_pct", severity="soft")], settings,
            weather_history())
    assert v.verdict == Verdict.FAULT


# ---- rule 2 -------------------------------------------------------------------------------------
def test_rule2_single_channel_jump_others_quiet_is_fault(settings):
    v = run([chk("step:temperature_c"), chk("step:pressure_hpa", flagged=False),
             chk("normality:humidity_pct", flagged=False, severity="soft")], settings)
    assert v.verdict == Verdict.FAULT and "only temperature_c jumped" in v.reason


def test_rule2_spike_counts_as_a_jump(settings):
    assert run([chk("spike:humidity_pct")], settings).verdict == Verdict.FAULT


def test_rule2_not_applied_when_another_channel_is_also_unusual(settings):
    v = run([chk("step:temperature_c"), chk("normality:humidity_pct", severity="soft")], settings)
    assert v.verdict == Verdict.SUSPECT


def test_two_channels_jumping_together_is_not_rule2(settings):
    v = run([chk("step:temperature_c"), chk("step:humidity_pct")], settings, weather_history())
    assert v.verdict == Verdict.SUSPECT              # not smooth, so not WEATHER either


# ---- rule 3 -------------------------------------------------------------------------------------
def test_rule3_channels_moving_together_matching_signature_is_weather(settings):
    v = run([chk("normality:temperature_c", severity="soft"), chk("normality:humidity_pct", severity="soft")],
            settings, weather_history())
    assert v.verdict == Verdict.WEATHER
    assert "temperature falling while humidity rises" in v.reason and "escalated, not suppressed" in v.reason


def test_rule3_needs_something_unusual_first(settings):
    assert run([chk("normality:temperature_c", flagged=False, severity="soft")], settings,
               weather_history()).verdict == Verdict.VALID


def test_rule3_not_applied_when_only_one_channel_moves(settings):
    h = make_history(10, cadence=15, t=lambda i: 20.0 - 1.5 * max(0, i - 5), p=lambda i: 1000.0, rh=lambda i: 50.0)
    assert run([chk("normality:temperature_c", severity="soft")], settings, h).verdict == Verdict.SUSPECT


def test_rule3_not_applied_when_moves_do_not_match_a_signature(settings):
    h = make_history(10, cadence=15, t=lambda i: 20.0 + 1.5 * max(0, i - 5), p=lambda i: 1000.0,
                     rh=lambda i: 50.0 + 8.0 * max(0, i - 5))      # both rising: no signature
    assert run([chk("normality:humidity_pct", severity="soft")], settings, h).verdict == Verdict.SUSPECT


def test_rule3_blocked_by_any_hard_flag(settings):
    v = run([chk("noise:pressure_hpa"), chk("normality:humidity_pct", severity="soft")], settings, weather_history())
    assert v.verdict == Verdict.SUSPECT


def test_movement_and_signature_helpers(settings):
    moves = movement(weather_history(), 15, settings)
    assert moves == {"temperature_c": -1, "pressure_hpa": 0, "humidity_pct": 1}
    assert match_signature(moves, settings)["name"] == "cooling_and_moistening"


# ---- rules 4 and 5 ------------------------------------------------------------------------------
def test_rule4_unusual_but_ambiguous_is_suspect(settings):
    v = run([chk("wet_bulb", severity="soft")], settings)
    assert v.verdict == Verdict.SUSPECT and "wet_bulb happened." in v.reason


def test_rule4_other_hard_flags_are_suspect(settings):
    for name in ("noise:temperature_c", "timestamp", "drift:pressure_hpa"):
        assert run([chk(name)], settings).verdict == Verdict.SUSPECT


def test_a_communication_gap_is_a_notice_and_does_not_change_the_verdict(settings):
    """The values that arrive after a gap are fine. The gap is reported beside the verdict, not as a fault."""
    v = run([chk("gap")], settings)
    assert v.verdict == Verdict.VALID
    assert len(v.notices) == 1 and "gap happened" in v.notices[0]
    v = run([chk("gap"), chk("range:temperature_c")], settings)          # a real fault still wins
    assert v.verdict == Verdict.FAULT and len(v.notices) == 1


def test_rule5_nothing_flagged_is_valid(settings):
    v = run([chk("range:temperature_c", flagged=False), chk("frozen:pressure_hpa", flagged=False)], settings)
    assert v.verdict == Verdict.VALID and "2 checks passed" in v.reason


def test_no_checks_at_all_is_valid(settings):
    assert run([], settings).verdict == Verdict.VALID


# ---- confidence ---------------------------------------------------------------------------------
def test_confidence_rises_with_agreeing_soft_flags_and_is_capped(settings):
    c = settings["fusion"]["confidence"]
    base = run([chk("step:temperature_c")], settings).confidence
    more = run([chk("step:temperature_c"), chk("isolation_forest", severity="soft")], settings).confidence
    assert base == c["fault_rule2"] and more == pytest.approx(c["fault_rule2"] + c["bonus_per_supporting_flag"])
    many = run([chk("frozen:temperature_c")] + [chk(f"isolation_forest{i}", severity="soft") for i in range(20)],
               settings).confidence
    assert many == c["max"]


def test_every_verdict_has_a_reason_and_keeps_the_checks(settings):
    checks = [chk("wet_bulb", severity="soft")]
    v = run(checks, settings)
    assert v.reason and v.checks == checks


# ---- Pipeline (all layers together, synthetic data only) ------------------------------------------
@pytest.fixture(scope="module")
def trained():
    from atmos.config import load_settings
    s = load_settings()
    train = synthetic_readings(days=20, cadence=15, seed=0, noise_t=0.1)
    return s, NormalityTable.fit(train, s), IsolationModel.fit(train, s)


def _pipeline(trained):
    s, table, model = trained
    return Pipeline(s, {"S1": {"cadence_minutes": 15}}, {"S1": table}, {"S1": model}), s


def test_pipeline_mostly_valid_on_fresh_clean_data(trained):
    pipe, _ = _pipeline(trained)
    fresh = synthetic_readings(days=4, cadence=15, seed=99, noise_t=0.1)
    verdicts = [pipe.process(r).verdict for r in fresh]
    assert verdicts.count(Verdict.FAULT) == 0
    assert verdicts.count(Verdict.VALID) / len(verdicts) > 0.9


def test_pipeline_catches_injected_frozen_temperature(trained):
    pipe, s = _pipeline(trained)
    fresh = synthetic_readings(days=4, cadence=15, seed=99, noise_t=0.1)
    res = inject(fresh, s, [FaultSpec("frozen", "temperature_c", 200)])
    verdicts = [pipe.process(r) for r in res.readings]
    ev = res.events[0]
    hit = [v for v in verdicts[ev.start_index: ev.end_index + 1] if v.verdict == Verdict.FAULT]
    assert hit and "not changed" in hit[-1].reason
    assert all(v.verdict != Verdict.FAULT for v in verdicts[: ev.start_index])


def test_pipeline_catches_dropout_and_impossible_value(trained):
    pipe, s = _pipeline(trained)
    fresh = synthetic_readings(days=2, cadence=15, seed=99, noise_t=0.1)
    for r in fresh[:60]:
        pipe.process(r)
    bad = pipe.process(fresh[60].model_copy(update={"humidity_pct": 140.0}))
    gone = pipe.process(fresh[61].model_copy(update={"pressure_hpa": None}))
    assert bad.verdict == Verdict.FAULT and "physical range" in bad.reason
    assert gone.verdict == Verdict.FAULT and "pressure_hpa" in gone.reason


def test_pipeline_works_without_trained_models():
    from atmos.config import load_settings
    s = load_settings()
    pipe = Pipeline(s, {"S1": {"cadence_minutes": 15}})
    verdicts = [pipe.process(r).verdict for r in synthetic_readings(days=3, cadence=15, noise_t=0.1)]
    assert Verdict.FAULT not in verdicts


def test_pipeline_layers_can_be_switched_off(trained):
    pipe, s = _pipeline(trained)
    s["layers"].update({"physics": False, "health": False, "normality": False, "mlmodel": False, "timing": False})
    v = pipe.process(make_reading(0, t=999.0))
    s["layers"].update({"physics": True, "health": True, "normality": True, "mlmodel": True, "timing": True})
    assert v.verdict == Verdict.VALID and v.checks == []


def test_pipeline_cadence_is_inferred_when_station_unknown():
    from atmos.config import load_settings
    pipe = Pipeline(load_settings())
    for r in make_history(10, cadence=15):
        pipe.process(r)
    assert pipe.cadence_minutes("S1") == 15


def test_unknown_station_second_reading_is_not_a_gap():
    from atmos.config import load_settings
    pipe = Pipeline(load_settings())
    first, second = make_history(2, cadence=15)
    pipe.process(first)
    assert not [c for c in pipe.process(second).checks if c.check == "gap" and c.flagged]


def test_a_failing_reading_does_not_poison_the_history_for_the_readings_after_it(monkeypatch):
    """Found by fuzzing: one crash left the bad reading in the history, so every later reading crashed too."""
    import atmos.fusion as fusion
    from atmos.config import load_settings
    pipe = Pipeline(load_settings(), {"S1": {"cadence_minutes": 1}})
    hist = make_history(10)
    for r in hist[:5]:
        pipe.process(r)
    real = fusion.physics.check_physics
    monkeypatch.setattr(fusion.physics, "check_physics", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        pipe.process(hist[5])
    monkeypatch.setattr(fusion.physics, "check_physics", real)
    assert len(pipe._history["S1"]) == 5 and len(pipe._records["S1"]) == 5      # rolled back
    for r in hist[5:]:
        pipe.process(r)                                                          # carries on normally
    assert len(pipe._history["S1"]) == 10


def test_pipeline_survives_mixed_time_zones_and_extreme_numbers():
    from atmos.config import load_settings
    from atmos.schema import Reading
    pipe = Pipeline(load_settings(), {"S1": {"cadence_minutes": 1}})
    pipe.process(Reading(station_id="S1", timestamp="2026-01-01T00:00:00", temperature_c=20, pressure_hpa=1000, humidity_pct=50))
    v = pipe.process(Reading(station_id="S1", timestamp="2026-01-01T00:01:00Z", temperature_c=-243.12,
                             pressure_hpa=1e308, humidity_pct=1e308))
    assert v.verdict == Verdict.FAULT


def test_warm_up_rebuilds_the_history_and_skips_readings_that_fail():
    from atmos.config import load_settings
    pipe = Pipeline(load_settings(), {"S1": {"cadence_minutes": 1}})
    assert pipe.warm_up(make_history(80, t=lambda i: 20.0)) == 80                # stored readings, temperature stuck
    v = pipe.process(make_reading(80, t=20.0))
    assert v.verdict == Verdict.FAULT and "not changed" in v.reason            # the frozen window was already full


def test_listing_stations_while_another_thread_adds_them_does_not_fail():
    import threading
    from atmos.config import load_settings
    from atmos.schema import Reading
    pipe = Pipeline(load_settings())
    errors = []

    def add():
        try:
            for i in range(150):
                pipe.process(Reading(station_id=f"S{i}", timestamp="2026-01-01T00:00:00", temperature_c=20, pressure_hpa=1000, humidity_pct=50))
        except Exception as e:
            errors.append(e)

    def listing():
        try:
            for _ in range(2000):
                pipe.stations_seen()
        except Exception as e:
            errors.append(e)

    ts = [threading.Thread(target=add), threading.Thread(target=listing), threading.Thread(target=listing)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errors == [] and len(pipe.stations_seen()) == 150


# ---- rule 2 needs the other channels to be QUIET, not merely un-flagged ---------------------------------
def _hourly_pipeline(settings):
    pipe = Pipeline(settings, {"S1": {"cadence_minutes": 60}})
    for r in make_history(30, cadence=60):                      # gentle ramps: T 20, P 1000, RH 50
        pipe.process(r)
    return pipe


def test_a_thunderstorm_outflow_is_not_a_fault(settings):
    """Humidity jumps 47 %, temperature falls 8 C (under the 10 C step limit, so no check fires on it), pressure rises.
    Rule 2 used to call this 'only humidity jumped'. Real records (Delhi and Kolkata) did exactly this."""
    v = _hourly_pipeline(settings).process(make_reading(30 * 60, t=12.0, p=1002.0, rh=97.0))
    assert v.verdict != Verdict.FAULT, v.reason


def test_a_lone_humidity_jump_on_calm_channels_is_still_a_fault(settings):
    v = _hourly_pipeline(settings).process(make_reading(30 * 60, t=20.3, p=1000.3, rh=97.0))
    assert v.verdict == Verdict.FAULT and "only humidity_pct jumped" in v.reason


# ---- WEATHER by level: several channels far from normal together ---------------------------------------------
def test_two_channels_far_from_normal_together_is_weather_not_suspect(settings):
    checks = [chk("normality:temperature_c", severity="soft"), chk("normality:humidity_pct", severity="soft")]
    calm = make_history(5)                                    # nothing moving, so no movement signature matches
    v = fuse(checks, calm, settings, 1, {"temperature_c": 3.1, "pressure_hpa": 0.2, "humidity_pct": -2.4})
    assert v.verdict == Verdict.WEATHER and "at the same time" in v.reason and "temperature_c +3.1" in v.reason


def test_one_channel_far_from_normal_alone_stays_suspect(settings):
    checks = [chk("normality:temperature_c", severity="soft")]
    v = fuse(checks, make_history(5), settings, 1, {"temperature_c": 5.0, "pressure_hpa": 0.2, "humidity_pct": -0.4})
    assert v.verdict == Verdict.SUSPECT


def test_coherent_level_never_overrides_a_hard_fault(settings):
    checks = [chk("range:humidity_pct"), chk("normality:temperature_c", severity="soft")]
    v = fuse(checks, make_history(5), settings, 1, {"temperature_c": 4.0, "pressure_hpa": -3.0, "humidity_pct": 5.0})
    assert v.verdict == Verdict.FAULT
