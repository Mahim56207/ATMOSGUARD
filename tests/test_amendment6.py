"""Amendment 6 / remedy 8: a noise limit learned from a record that is not equally spaced."""
import copy
import math
from datetime import timedelta

import numpy as np
import pytest

from atmos.config import load_settings
from atmos.limits import fit_limits, noise_estimates, noise_estimates_gap_aware
from tests.conftest import T0, make_reading

SETTINGS = load_settings()


def series(offsets_min, sigma=0.4, seed=0, station="S1", smooth=True):
    """Readings at the given minute offsets: a smooth daily cycle plus independent noise of std `sigma` on every channel."""
    rng = np.random.default_rng(seed)
    out = []
    for m in offsets_min:
        cyc = math.sin(2 * math.pi * (m / 60.0 % 24 - 9) / 24) if smooth else 0.0
        out.append(make_reading(m, t=20 + 4 * cyc + rng.normal(0, sigma), p=1010 + 0.5 * cyc + rng.normal(0, sigma),
                                rh=60 - 10 * cyc + rng.normal(0, sigma), station=station))
    return out


def alternating(days, seed=0, sigma=0.4):
    """The irregular pattern of the FRESH2/FRESH3 Australian stations: reports alternate 1 h and 2 h apart."""
    t, offs, gap = 0, [], 60
    while t < days * 1440:
        offs.append(t)
        t += gap
        gap = 120 if gap == 60 else 60
    return series(offs, sigma=sigma, seed=seed)


def test_gap_aware_estimate_equals_the_standard_one_on_equally_spaced_readings():
    rs = series(range(0, 60 * 24 * 40, 60), sigma=0.5, smooth=False)
    std = noise_estimates(rs, "temperature_c", 30, 7, 60)
    gap = noise_estimates_gap_aware(rs, "temperature_c", 7, 180, 720)
    assert len(std) > 500 and len(std) == len(gap)
    assert np.allclose(std, gap, atol=1e-9)                          # the same 7-sample windows, the same numbers


def test_gap_aware_estimate_recovers_the_noise_on_a_record_that_alternates_one_and_two_hours():
    rs = alternating(60, sigma=0.5)
    est = noise_estimates_gap_aware(rs, "pressure_hpa", 7, 180, 720)
    assert len(est) > 500
    assert 0.35 < float(np.median(est)) < 0.75                      # the injected noise std is 0.5 (the smooth part adds a little)
    # the plain estimator is inflated on the same record (it treats unequal gaps as equal), which is why it cannot be used there
    plain = noise_estimates(rs, "pressure_hpa", 30, 7, 60)
    assert len(plain) == 0                                           # and the time-based window finds no window with 7 readings at all


def test_no_limit_is_learned_from_an_irregular_record_by_default_and_remedy_8_learns_it():
    rs = alternating(250)
    off = fit_limits(rs, SETTINGS, 60)
    assert all(c.noise_std is None for c in off.channels.values())
    s = copy.deepcopy(SETTINGS)
    s["limits"]["gap_aware_noise"] = True
    on = fit_limits(rs, s, 60)
    assert all(c.noise_std is not None and c.noise_std > 0 for c in on.channels.values())
    assert on.channels["temperature_c"].frozen_minutes == off.channels["temperature_c"].frozen_minutes      # nothing else changes


def test_remedy_8_changes_nothing_on_a_regular_record():
    rs = series(range(0, 60 * 24 * 250, 60), sigma=0.4)
    off = fit_limits(rs, SETTINGS, 60)
    s = copy.deepcopy(SETTINGS)
    s["limits"]["gap_aware_noise"] = True
    on = fit_limits(rs, s, 60)
    assert off.channels == on.channels                                # learned by the standard path, so the flag is never reached


def test_windows_across_a_long_gap_are_skipped():
    offs = [*range(0, 60 * 10, 60), *range(60 * 10 + 600, 60 * 10 + 600 + 60 * 10, 60)]        # a 10 h hole in the middle
    est = noise_estimates_gap_aware(series(offs), "temperature_c", 7, 180, 720)
    assert len(est) == 2 * (10 - 6)                                   # only windows entirely on one side of the hole


def test_the_shipped_default_keeps_remedy_8_off():
    assert SETTINGS["limits"]["gap_aware_noise"] is False


# ---- a station with no barometer (settings `channels.absent`): needed for the 5-minute CRN records, which carry temperature and humidity only
from atmos.fusion import Pipeline
from atmos.health import check_dropout
from atmos.injector import make_plan
from atmos.mlmodel import IsolationModel, MahalanobisModel, build_features
from atmos.normality import NormalityTable
from atmos.schema import Reading, Verdict

ABSENT = copy.deepcopy(SETTINGS)
ABSENT["channels"]["absent"] = ["pressure_hpa"]


def no_baro(days=40, step=60, seed=1, station="S1"):
    rs = series(range(0, 1440 * days, step), sigma=0.3, seed=seed, station=station)
    return [r.model_copy(update={"pressure_hpa": None}) for r in rs]


def test_an_absent_channel_is_not_a_dropout_but_a_missing_present_channel_is():
    rs = no_baro(2)
    assert check_dropout(rs, ("pressure_hpa",)).flagged is False
    assert check_dropout(rs).flagged is True                             # the default still calls it a dropout
    cut = rs[:-1] + [rs[-1].model_copy(update={"humidity_pct": None})]
    assert check_dropout(cut, ("pressure_hpa",)).flagged is True


def test_models_train_and_score_with_a_constant_in_place_of_the_absent_channel():
    rs = no_baro(60)
    X, ok = build_features(rs, ("pressure_hpa",))
    assert ok.sum() == len(rs) - 1 and np.all(X[:, 1] == 0) and np.all(X[:, 4] == 0)
    table = NormalityTable.fit(rs, ABSENT)
    forest = IsolationModel.fit(rs, ABSENT)
    mahal = MahalanobisModel.fit(rs, ABSENT, table)
    assert forest.absent == ("pressure_hpa",) and mahal.absent == ("pressure_hpa",)
    assert not np.isnan(forest.score(rs[-2:])[1])
    assert not np.isnan(mahal.distance2(rs[-3:], table)[-1])


def test_pipeline_judges_a_two_channel_station_and_still_catches_a_frozen_temperature():
    train, live = no_baro(80, seed=1), no_baro(20, seed=2)
    table, forest = NormalityTable.fit(train, ABSENT), IsolationModel.fit(train, ABSENT)
    lim = fit_limits(train, ABSENT, 60)
    pipe = Pipeline(ABSENT, {"S1": {"cadence_minutes": 60}}, {"S1": table}, {"S1": forest}, {"S1": lim})
    verdicts = [pipe.process(r).verdict for r in live]
    assert verdicts.count(Verdict.FAULT) == 0                            # no barometer is not a fault
    stuck = [r.model_copy(update={"temperature_c": 22.0}) for r in live[-14:]]
    pipe2 = Pipeline(ABSENT, {"S1": {"cadence_minutes": 60}}, {"S1": table}, {"S1": forest}, {"S1": lim})
    out = [pipe2.process(r).verdict for r in live[:-14] + stuck]
    assert Verdict.FAULT in out[-14:]


def test_injector_never_puts_a_single_channel_fault_on_an_absent_channel():
    rs = no_baro(120)
    plan = make_plan(rs, ABSENT, seed=3, types=("spike", "step", "noise"))
    assert plan and all(p.channel != "pressure_hpa" for p in plan)
    default = make_plan(series(range(0, 1440 * 120, 60)), SETTINGS, seed=3, types=("spike", "step", "noise"))
    assert {p.channel for p in default} == {"temperature_c", "pressure_hpa", "humidity_pct"}


def test_default_settings_declare_no_absent_channel():
    assert SETTINGS["channels"]["absent"] == []


def test_models_of_a_station_without_a_barometer_keep_that_after_saving(tmp_path):
    rs = no_baro(60)
    table = NormalityTable.fit(rs, ABSENT)
    forest, mahal = IsolationModel.fit(rs, ABSENT), MahalanobisModel.fit(rs, ABSENT, table)
    forest.save(tmp_path / "f.joblib")
    mahal.save(tmp_path / "m.joblib")
    assert IsolationModel.load(tmp_path / "f.joblib").absent == ("pressure_hpa",)
    assert MahalanobisModel.load(tmp_path / "m.joblib").absent == ("pressure_hpa",)


# ---- FRESH5: the configurations, the guard and the decision rule --------------------------------------------------------------
def _cfg(alarm=20, clean_n=1000, windows_with_fault=3, fault_n=20, suspect=80, det=None, kind="full"):
    det = det or {}
    detection = {t: {"detected_new": det.get(t, 90), "injected": 100, "detected": det.get(t, 90)}
                 for t in ("frozen", "spike", "step", "noise", "dropout", "clock_shift")}
    return {"kind": kind, "clean": {"n": clean_n, "alarm": alarm, "fault": 0, "weather": 0},
            "events": {"low_pressure": {"n": 1000, "FAULT": fault_n, "SUSPECT": suspect, "WEATHER": 100, "VALID": 1000 - fault_n - suspect - 100,
                                        "windows": 100, "windows_with_fault": windows_with_fault}}, "detection": detection}


def _a6(irr_full, irr_r8, reg_full=None, reg_r8=None):
    reg_full = reg_full or _cfg()
    return ({"configs": {"full": irr_full, "r8_gapaware": irr_r8}},
            {"configs": {"full": reg_full, "r8_gapaware": reg_r8 if reg_r8 is not None else copy.deepcopy(reg_full)}})


def test_fresh5_configs_are_full_and_the_remedy_and_the_baselines():
    import evaluate_real as er
    from atmos.mlmodel import MahalanobisModel
    from tests.test_limits import rounded_series
    s = er.real_settings(load_settings())
    train = rounded_series(seed=5)
    table, model = NormalityTable.fit(train, s), IsolationModel.fit(train, s)
    lim, mahal = fit_limits(train, s, 60), MahalanobisModel.fit(train, s, table)
    names = [n for n, _, _ in er.build_configs(s, table, model, lim, train, "S1", 60.0, mahal, "FRESH5")]
    assert names[:2] == ["full", "r8_gapaware"] and "baseline_rules" in names
    assert er.pin_registered(copy.deepcopy(s))["limits"]["gap_aware_noise"] is False


def test_fresh5_guard_needs_amendment_6(tmp_path):
    import subprocess
    import evaluate as ev
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    (repo / "config/protocol.md").write_text("# Protocol\nDone.\n")
    for cmd in (["init", "-q"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "p"]):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True)
    with pytest.raises(ev.HoldoutError, match="Amendment 6"):
        ev.guard_fresh5(SETTINGS, repo, tmp_path / "data")
    (repo / "config/protocol.md").write_text("# Protocol\nDone.\n\n## Amendment 6\nThe sixth set.\n")
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "amendment"], check=True)
    ev.guard_fresh5(SETTINGS, repo, tmp_path / "data")
    assert (tmp_path / "data/fresh5/.fresh5_used").exists()


def test_rule_adopts_when_the_irregular_stations_become_like_the_controls():
    import make_summary as ms
    irr, reg = _a6(_cfg(alarm=450, det={"spike": 50, "noise": 95}), _cfg(alarm=20, det={"noise": 80, "spike": 90}, kind="remedy"))
    row = ms.amendment6_rows(irr, reg)[0]
    assert row["adopt"] == "yes" and row["rule (e)"] == "pass"
    assert "-15.0" not in row["(b) worst gap to the control stations' detection"]


def test_rule_fails_on_residual_false_alarms_lost_detection_more_fault_windows_or_a_changed_control():
    import make_summary as ms
    full = _cfg(alarm=450)
    good = dict(alarm=20, kind="remedy")
    assert ms.amendment6_rows(*_a6(full, _cfg(**{**good, "alarm": 60})))[0]["rule (a)"] == "FAIL"               # 6 %: above the 5 % ceiling
    assert ms.amendment6_rows(*_a6(_cfg(alarm=90), _cfg(**{**good, "alarm": 40})))[0]["rule (a)"] == "FAIL"      # only 5 points down
    assert ms.amendment6_rows(*_a6(full, _cfg(**good, det={"noise": 60})))[0]["rule (b)"] == "FAIL"               # 30 points below the controls
    assert ms.amendment6_rows(*_a6(full, _cfg(**good, windows_with_fault=4)))[0]["rule (c)"] == "FAIL"
    assert ms.amendment6_rows(*_a6(full, _cfg(**good, suspect=120)))[0]["rule (d)"] == "FAIL"                     # SUSPECT +4 points
    irr, reg = _a6(full, _cfg(**good), reg_r8=_cfg(alarm=21, kind="remedy"))
    assert ms.amendment6_rows(irr, reg)[0]["rule (e)"] == "FAIL"                                                  # the control changed
    assert ms.amendment6_rows(irr, reg)[0]["adopt"] == "no"


def test_the_strict_amendment_4_reading_is_reported_but_does_not_decide():
    import make_summary as ms
    irr, reg = _a6(_cfg(alarm=450, det={"noise": 99}), _cfg(alarm=20, det={"noise": 80}, kind="remedy"), reg_full=_cfg(det={"noise": 75}))
    row = ms.amendment6_rows(irr, reg)[0]
    assert row["adopt"] == "yes"
    assert "-19.0 pp (noise burst)" in row["for the record: Amendment 4 rule (b), worst change against full"]
