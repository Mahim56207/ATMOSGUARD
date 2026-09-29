"""evaluate_coldstart.py: the runner's bookkeeping, and that batch scoring of the forest does not change a single verdict."""

import pytest

import evaluate_coldstart as cs
import evaluate_real as er
import loadtest
from atmos.config import load_settings
from atmos.fusion import Pipeline


def test_by_station_groups_and_orders_jobs():
    jobs = [{"station": "B", "days": 30, "borrowed_from": ["A"], "rows": [{"k": 2}]},
            {"station": "A", "days": 7, "borrowed_from": ["B"], "rows": [{"k": 1}]},
            {"station": "B", "days": 7, "borrowed_from": ["A"], "rows": [{"k": 3}]}]
    out = cs.by_station(jobs)
    assert [r["station"] for r in out] == ["A", "B"]
    assert out[1]["rows"] == [{"k": 3}, {"k": 2}] and out[1]["borrowed_from"] == ["A"]


def test_durations_eta_and_projection():
    assert cs.fmt_duration(30) == "30 s" and cs.fmt_duration(600) == "10 min" and cs.fmt_duration(3900) == "1 h 05 min"
    assert cs.eta_seconds(0, 42, 100.0) is None
    assert cs.eta_seconds(10, 42, 100.0) == pytest.approx(320.0)          # 10 s per finished job, 32 to go
    assert cs.eta_seconds(42, 42, 999.0) == 0.0
    typical, worst = cs.project([10.0, 20.0, 60.0], total_jobs=42, workers=4)
    assert typical == pytest.approx(30.0 * 42 / 4) and worst == pytest.approx(60.0 * 42 / 4)


def test_batch_scoring_of_the_forest_gives_the_same_verdicts_as_scoring_reading_by_reading():
    s = load_settings()
    tables, models, limits, mahal, streams, stations = loadtest.build_fleet(s, 1, train_days=6)
    sid = next(iter(streams))
    series, cad = streams[sid], stations[sid]["cadence_minutes"]
    live = Pipeline(s, stations, tables, models, limits, mahal)
    want = [er.Pred(v.verdict.value, frozenset(c.check.split(":")[0] for c in v.checks if c.flagged))
            for v in (live.process(r) for r in series)]
    got = cs._predict(s, tables[sid], models[sid], limits[sid], sid, cad, mahal[sid])(series)
    assert got == want
    assert any(c.check == "isolation_forest" for c in live.process(series[-1]).checks)      # the forest really was in the pipeline


def test_a_job_scores_both_modes_and_the_paired_counts_are_consistent():
    meta = er.load_events()
    stations = cs.load_stations_yaml()
    settings = load_settings()
    sid = meta["dev_stations"][0]
    try:
        st = cs.prepare_station(sid, settings, meta, stations)
        st["clean"], st["event_series"] = st["clean"][:2], st["event_series"][:2]      # a small slice keeps the test quick
        st["faulted"] = [f for f in st["faulted"] if any(f[2] is c for c in st["clean"])][:4]
        r = cs.run_job((sid, 30, settings, meta, stations))
    finally:
        cs._PREPARED.clear()
    assert r["station"] == sid and r["days"] == 30 and r["seconds"] >= 0
    assert [row["mode"] for row in r["rows"]] == ["starter", "own_only"]
    for row in r["rows"]:
        assert row["clean"]["n"] > 0 and 0 <= row["clean"]["fault"] <= row["clean"]["alarm"] <= row["clean"]["n"]
        assert all(0 <= d <= n for d, n in row["detection"].values())
