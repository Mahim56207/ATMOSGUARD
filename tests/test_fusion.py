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
    for name in ("noise:temperature_c", "gap", "timestamp", "drift:pressure_hpa"):
        assert run([chk(name)], settings).verdict == Verdict.SUSPECT


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
    s["layers"].update({"physics": False, "health": False, "normality": False, "mlmodel": False})
    v = pipe.process(make_reading(0, t=999.0))
    s["layers"].update({"physics": True, "health": True, "normality": True, "mlmodel": True})
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
