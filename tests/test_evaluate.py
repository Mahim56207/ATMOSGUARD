"""Tests for evaluate.py: metrics, baselines, ablation, the three printed numbers, and the holdout guard."""
import copy
import csv
import subprocess

import pytest

import evaluate as ev
import replay as rp
from atmos.config import load_settings
from atmos.injector import FaultEvent, InjectionResult
from atmos.mlmodel import IsolationModel
from tests.conftest import make_history


@pytest.fixture(scope="module")
def small():
    """Small synthetic settings so the whole evaluation runs in a few seconds."""
    s = copy.deepcopy(load_settings())
    s["evaluate"]["synthetic"].update(train_days=10, eval_days=4, event_count=2)
    s["evaluate"]["injection_rounds"] = 1
    return s


@pytest.fixture(scope="module")
def outcome(small):
    data = ev.synthetic_data(small)
    return data, ev.run_evaluation(small, data)


def _row(results, split, name):
    return next(r for r in results[split] if r.name == name)


# ---- metric definitions ---------------------------------------------------------------------------
def _result(events):
    return InjectionResult([], [None] * 100, [FaultEvent(t, "temperature_c", "a", "b", s, e) for t, s, e in events])


def test_detection_counts_an_alarm_inside_the_window_and_inside_the_grace_period(small):
    grace = small["evaluate"]["detection_grace_minutes"] // 15                    # samples
    alarms_at = {12 + grace}                                                       # last sample that still counts
    predict = lambda readings: [(i in alarms_at, False) for i in range(100)]
    inside = ev._detection([([], _result([("frozen", 10, 12)]))], predict, small, 15.0)
    assert inside["frozen"] == (1, 1)
    late = ev._detection([([], _result([("frozen", 10, 11)]))], predict, small, 15.0)      # alarm is 1 sample too late
    assert late["frozen"] == (0, 1)
    early = ev._detection([([], _result([("frozen", 50, 52)]))], predict, small, 15.0)     # alarm before the fault
    assert early["frozen"] == (0, 1)


def test_detection_is_counted_per_fault_type(small):
    predict = lambda readings: [(i == 10, False) for i in range(100)]
    d = ev._detection([([], _result([("frozen", 9, 11), ("spike", 40, 40), ("spike", 10, 10)]))], predict, small, 15.0)
    assert d["frozen"] == (1, 1) and d["spike"] == (1, 2) and d["step"] == (0, 0)


def test_false_alarm_counts_alarm_and_weather_separately():
    series = [make_history(10)]
    preds = [(True, False)] * 2 + [(False, True)] * 3 + [(False, False)] * 5
    assert ev._count(series, lambda r: preds) == (2, 10, 3)                       # WEATHER is not an alarm


def test_only_fault_and_suspect_are_alarms():
    assert ev.ALARM_VERDICTS == ("FAULT", "SUSPECT")


# ---- baselines ------------------------------------------------------------------------------------
def test_range_baseline_only_sees_impossible_values(small):
    h = make_history(5)
    h[2] = h[2].model_copy(update={"humidity_pct": 130.0})
    h[3] = h[3].model_copy(update={"pressure_hpa": None})                         # dropout: not a range problem
    flags = [a for a, _ in ev.range_baseline(small)(h)]
    assert flags == [False, False, True, False, False]


def test_range_persistence_baseline_adds_frozen_values(small):
    h = make_history(200, t=lambda i: 20.0)                                       # temperature stuck for 200 min
    flags = [a for a, _ in ev.range_persistence_baseline(small, 1.0)(h)]
    assert not any(flags[:50]) and all(flags[-20:])


def test_isolation_forest_baseline_flags_a_multi_channel_outlier(small, outcome):
    data, _ = outcome
    model = IsolationModel.fit(data.train, small)
    series = copy.deepcopy(data.dev.clean[0][:50])
    series[-1] = series[-1].model_copy(update={"temperature_c": series[-1].temperature_c + 25,
                                               "pressure_hpa": series[-1].pressure_hpa + 30,
                                               "humidity_pct": series[-1].humidity_pct + 40})
    assert ev.isolation_forest_baseline(model)(series)[-1][0] is True


def test_precomputed_model_gives_the_same_scores_as_the_model(small, outcome):
    data, _ = outcome
    model = IsolationModel.fit(data.train, small)
    series = data.dev.clean[0][:30]
    pre = ev._PrecomputedModel(model, series)
    assert pre.score(series[9:11])[1] == pytest.approx(model.score(series[9:11])[1])


# ---- ablation and configurations ------------------------------------------------------------------
def test_configs_are_full_then_one_layer_off_then_baselines(small, outcome):
    data, results = outcome
    assert [r.name for r in results["DEV"]] == [
        "full", "no_physics", "no_health", "no_normality", "no_mlmodel", "no_timing",
        "baseline_range", "baseline_range_persistence", "baseline_isolation_forest"]
    assert [r.kind for r in results["DEV"]][:6] == ["full"] + ["ablation"] * 5


def test_ablation_actually_switches_the_layer_off(outcome):
    _, results = outcome
    full, no_health = _row(results, "DEV", "full"), _row(results, "DEV", "no_health")
    assert full.detection["dropout"][0] == full.detection["dropout"][1] > 0
    assert no_health.detection["dropout"][0] == 0                                 # dropout is only seen by the health layer
    assert no_health.detection["frozen"][0] < full.detection["frozen"][0]


def test_evaluation_does_not_change_the_callers_settings(small):
    before = copy.deepcopy(small)
    ev.build_configs(small, None, None, "S1", 15.0)
    assert small == before


# ---- results on synthetic data (plumbing check, not real results) -----------------------------------
def test_full_pipeline_beats_the_baselines_on_synthetic_faults(outcome):
    _, results = outcome
    full = _row(results, "DEV", "full")
    for base in ("baseline_range", "baseline_range_persistence", "baseline_isolation_forest"):
        b = _row(results, "DEV", base)
        assert sum(d for d, _ in full.detection.values()) > sum(d for d, _ in b.detection.values())
    for t in ("frozen", "dropout", "step"):
        assert full.detection[t][0] == full.detection[t][1] > 0


def test_false_alarms_are_low_on_clean_and_on_synthetic_weather(outcome):
    _, results = outcome
    full = _row(results, "DEV", "full")
    a, n, _ = full.clean_alarms
    assert n > 0 and a / n < 0.05
    a, n, wx = full.events_alarms
    assert n > 0 and a / n < 0.10 and wx > 0                                      # weather is answered with WEATHER, sometimes


def test_the_forest_alone_false_alarms_more_on_weather_than_the_pipeline(outcome):
    _, results = outcome
    full, forest = _row(results, "DEV", "full"), _row(results, "DEV", "baseline_isolation_forest")
    assert forest.events_alarms[0] > full.events_alarms[0]


def test_synthetic_run_repeats_exactly(small):
    a = ev.format_report(ev.run_evaluation(small, ev.synthetic_data(small)), True)
    b = ev.format_report(ev.run_evaluation(small, ev.synthetic_data(small)), True)
    assert a == b


def test_injected_frozen_faults_are_longer_than_the_longest_frozen_window(small):
    longest = max(small["health"]["frozen"]["window_minutes"].values())
    assert small["injector"]["duration_minutes"]["frozen"] > longest


def test_faulted_series_do_not_change_the_clean_input(small, outcome):
    data, _ = outcome
    before = [r.model_dump() for r in data.dev.clean[0]]
    ev.make_faulted(data.dev.clean, small)
    assert [r.model_dump() for r in data.dev.clean[0]] == before


# ---- the report: three numbers, always ------------------------------------------------------------
def test_report_always_has_the_three_sections_and_says_synthetic(outcome):
    _, results = outcome
    text = ev.format_report(results, True)
    assert "SYNTHETIC DATA" in text and "NOTHING about real stations" in text
    for heading in ("1) Detection rate per fault type", "2) False-alarm rate on clean data",
                    "3) False-alarm rate on synthetic stand-ins for real extreme-weather windows"):
        assert text.count(heading) == 2                                            # DEV and HOLDOUT
    assert "### DEV" in text and "### HOLDOUT (synthetic)" in text


def test_report_prints_all_three_even_with_no_event_data(outcome):
    _, results = outcome
    blank = copy.deepcopy(results)
    for r in blank["DEV"]:
        r.events_alarms = None
    text = ev.format_report({"DEV": blank["DEV"]}, False, "HOLDOUT: not run.")
    assert "3) False-alarm rate on real extreme-weather windows" in text and "no event data" in text
    assert "SYNTHETIC" not in text and "HOLDOUT: not run." in text


def test_json_output_round_trips(outcome):
    import json
    _, results = outcome
    d = json.loads(ev.to_json(results, True))
    assert d["synthetic"] is True and d["results"]["DEV"][0]["name"] == "full"


# ---- real data loading and the holdout guard ------------------------------------------------------
def _write(path, readings):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "temperature_c", "pressure_hpa", "humidity_pct"])
        for r in readings:
            w.writerow([r.timestamp.isoformat(), r.temperature_c, r.pressure_hpa, r.humidity_pct])


@pytest.fixture
def repo(tmp_path):
    """A throwaway git repo holding a finished, committed protocol.md."""
    r = tmp_path / "repo"
    (r / "config").mkdir(parents=True)
    (r / "config/protocol.md").write_text("# Protocol\nDone.\n")
    git = lambda *a: subprocess.run(["git", "-C", str(r), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                    check=True, capture_output=True)
    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "protocol")
    return r


@pytest.fixture
def cfg(tmp_path):
    s = copy.deepcopy(load_settings())
    s["replay"]["data_dir"] = str(tmp_path / "data")
    s["evaluate"]["injection_rounds"] = 1
    return s


def test_guard_passes_once_then_refuses_a_second_read(cfg, repo, tmp_path):
    ev.guard_holdout(cfg, repo, tmp_path / "data")
    assert (tmp_path / "data/holdout/.holdout_used").exists()
    with pytest.raises(ev.HoldoutError, match="already used"):
        ev.guard_holdout(cfg, repo, tmp_path / "data")


def test_guard_refuses_when_protocol_is_not_committed(cfg, tmp_path):
    bare = tmp_path / "bare"
    (bare / "config").mkdir(parents=True)
    (bare / "config/protocol.md").write_text("done")
    subprocess.run(["git", "-C", str(bare), "init", "-q"], check=True)
    with pytest.raises(ev.HoldoutError, match="not committed"):
        ev.guard_holdout(cfg, bare, tmp_path / "data")
    assert not (tmp_path / "data/holdout/.holdout_used").exists()


def test_guard_refuses_uncommitted_changes_and_unfinished_markers(cfg, repo, tmp_path):
    (repo / "config/protocol.md").write_text("# Protocol\nchanged after the commit\n")
    with pytest.raises(ev.HoldoutError, match="uncommitted"):
        ev.guard_holdout(cfg, repo, tmp_path / "data")
    (repo / "config/protocol.md").write_text("# Protocol\nTODO fill in\n")
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "x"], check=True)
    with pytest.raises(ev.HoldoutError, match="TODO"):
        ev.guard_holdout(cfg, repo, tmp_path / "data")


def test_fresh_guard_needs_amendment_2_in_the_committed_protocol_and_passes_once(cfg, repo, tmp_path):
    with pytest.raises(ev.HoldoutError, match="Amendment 2"):
        ev.guard_fresh(cfg, repo, tmp_path / "data")                              # the committed protocol has no Amendment 2
    assert not (tmp_path / "data/fresh/.fresh_used").exists()
    (repo / "config/protocol.md").write_text("# Protocol\nDone.\n\n## Amendment 2\nThe fresh stations.\n")
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "amendment"], check=True)
    ev.guard_fresh(cfg, repo, tmp_path / "data")
    assert (tmp_path / "data/fresh/.fresh_used").exists()
    assert not (tmp_path / "data/holdout/.holdout_used").exists()                 # its own lock, not the holdout's
    with pytest.raises(ev.HoldoutError, match="already used"):
        ev.guard_fresh(cfg, repo, tmp_path / "data")


def test_replay_refuses_the_fresh_folder_like_the_holdout(cfg, tmp_path):
    import replay
    for sealed in ("holdout", "fresh"):
        with pytest.raises(ValueError, match="Replay will not read it"):
            replay.check_path(tmp_path / "data" / sealed / "x.csv", cfg)
    replay.check_path(tmp_path / "data" / "fresh" / "x.csv", cfg, allow_holdout=True)      # the evaluation, behind its guard


def test_the_real_protocol_file_is_finished(cfg):
    assert "TODO" not in (ev.REPO_ROOT / "config/protocol.md").read_text()


def _lay_out_data(cfg, tmp_path):
    root = tmp_path / "data"
    clean = ev.synthetic_series(cfg, 10, 5)
    _write(root / "clean/a.csv", clean)
    _write(root / "events/storm.csv", ev.synthetic_series(cfg, 2, 6, with_event=True))
    _write(root / "holdout/clean/h.csv", ev.synthetic_series(cfg, 4, 7))
    _write(root / "holdout/events/h_storm.csv", ev.synthetic_series(cfg, 2, 8, with_event=True))
    return root, clean


def test_dev_run_never_touches_the_holdout(cfg, tmp_path, monkeypatch):
    root, clean = _lay_out_data(cfg, tmp_path)
    opened = []
    real = rp.read_readings
    monkeypatch.setattr(rp, "read_readings", lambda path, *a, **k: (opened.append(str(path)), real(path, *a, **k))[1])
    data = ev.load_real(cfg, "S1", include_holdout=False)
    assert data.holdout is None and not any("/data/holdout/" in p for p in opened)
    assert not (root / "holdout/.holdout_used").exists()
    cut = int(len(clean) * cfg["evaluate"]["train_fraction"])
    assert len(data.train) == cut and len(data.dev.clean[0]) == len(clean) - cut     # split is in time order
    assert data.train[-1].timestamp < data.dev.clean[0][0].timestamp
    assert len(data.dev.events) == 1 and data.dev.faulted


def test_holdout_run_is_guarded_and_models_use_dev_train_only(cfg, repo, tmp_path):
    root, clean = _lay_out_data(cfg, tmp_path)
    data = ev.load_real(cfg, "S1", include_holdout=True, repo_dir=repo)
    assert data.holdout is not None and data.holdout.name == "HOLDOUT" and len(data.holdout.events) == 1
    assert (root / "holdout/.holdout_used").exists()
    holdout_values = {r.temperature_c for series in data.holdout.clean + data.holdout.events for r in series}
    assert holdout_values.isdisjoint({r.temperature_c for r in data.train})         # nothing from holdout is in training
    with pytest.raises(ev.HoldoutError):
        ev.load_real(cfg, "S1", include_holdout=True, repo_dir=repo)                # second read refused


def test_holdout_is_not_read_when_the_guard_refuses(cfg, tmp_path, monkeypatch):
    _lay_out_data(cfg, tmp_path)
    opened = []
    real = rp.read_readings
    monkeypatch.setattr(rp, "read_readings", lambda path, *a, **k: (opened.append(str(path)), real(path, *a, **k))[1])
    with pytest.raises(ev.HoldoutError):
        ev.load_real(cfg, "S1", include_holdout=True, repo_dir=tmp_path)             # tmp_path is not a git repo
    assert not any("/data/holdout/" in p for p in opened)


def test_replay_still_refuses_the_holdout_by_default(cfg, tmp_path):
    root, _ = _lay_out_data(cfg, tmp_path)
    with pytest.raises(ValueError, match="holdout"):
        rp.read_readings(root / "holdout/clean/h.csv", cfg, "S1")
    assert rp.read_readings(root / "holdout/clean/h.csv", cfg, "S1", allow_holdout=True)


def test_missing_dev_data_gives_a_clear_error(cfg, tmp_path):
    with pytest.raises(ValueError, match="No DEV clean data"):
        ev.load_real(cfg, "S1", include_holdout=False)


def test_cli_synthetic_and_missing_data(capsys, monkeypatch, tmp_path):
    monkeypatch.setattr(ev, "load_settings", lambda: _tiny())
    assert ev.main(["--synthetic", "--out", str(tmp_path / "r.json")]) == 0
    out = capsys.readouterr().out
    assert "SYNTHETIC DATA" in out and "HOLDOUT (synthetic)" in out and (tmp_path / "r.json").exists()
    s = _tiny()
    s["replay"]["data_dir"] = str(tmp_path / "nothing")
    monkeypatch.setattr(ev, "load_settings", lambda: s)
    assert ev.main([]) == 2 and "Cannot evaluate" in capsys.readouterr().out


def _tiny():
    s = copy.deepcopy(load_settings())
    s["evaluate"]["synthetic"].update(train_days=6, eval_days=2, event_count=1)
    s["evaluate"]["injection_rounds"] = 1
    return s
