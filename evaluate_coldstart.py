"""Cold start on real data: how much history does a NEW station need? (DEV stations only.)

    python evaluate_coldstart.py --workers 4 --out results/coldstart.json

Leave-one-station-out. For each DEV station S, the other five are the "network". S is treated as brand new with only D
days of its own clean history (D = 0 ... all of 2016-2019). Two ways to start it are compared at every D:
  starter  : blend of S's own (partial) table and limits with a starter borrowed from the NEAREST other station
             (atmos/coldstart.py). The Isolation Forest is off until S has 90 days of its own data.
  own only : S's own partial table and limits, nothing borrowed.
Both are judged on the same DEV data S never trained on (2020-2021, extreme-weather windows and NOAA-flagged values
handled as in evaluate_real.py):  false alarms on clean data, FAULT verdicts on real extreme weather, and detection of a
few injected faults.
The starter is a frozen table from other stations, not their live data: the single-station principle is kept.

How the run is organised (so its running time is known, not guessed):
  * one job = one (station, days of own history); a job scores both starting modes. 6 stations x 7 history lengths = 42 jobs,
    handed to the workers one at a time, so no core sits idle while another finishes a big station;
  * every finished job prints a progress line with the elapsed time and an ETA, and is appended to `<out>.partial.json`,
    so an interrupted run resumes with `--resume` and loses at most the jobs in flight;
  * `--estimate` times three representative jobs (no history, 90 days, all of it) and projects the whole run, without running it;
  * the Isolation Forest is scored for a whole series in one batch (the same helper the main evaluation uses); the pipeline
    verdicts are identical to scoring one reading at a time (tests/test_coldstart_run.py checks this), only much faster.
"""
from __future__ import annotations

import argparse
import copy
import json
import statistics
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yaml

import evaluate as ev
import evaluate_real as er
from atmos import coldstart
from atmos.config import CONFIG_DIR, load_settings, model_path
from atmos.fusion import Pipeline
from atmos.limits import StationLimits, fit_limits
from atmos.mlmodel import IsolationModel, MahalanobisModel
from atmos.normality import NormalityTable

DAYS = (0, 7, 30, 90, 180, 365, 1460)
ML_FROM_DAYS = 90
TYPES = ("frozen", "spike", "step")
REPO = er.REPO


def _predict(settings, table, model, limits, sid, cadence, mahal=None):
    """Full-pipeline verdicts for a series. The forest is scored for the whole series in one batch (identical verdicts to
    scoring reading by reading, see tests/test_coldstart_run.py); without a forest the layer is off."""
    s = copy.deepcopy(settings)
    if model is None:
        s["layers"]["mlmodel"] = False

    def predict(readings):
        models = {sid: ev._PrecomputedModel(model, readings)} if model else {}
        pipe = Pipeline(s, {sid: {"cadence_minutes": cadence}}, {sid: table} if table else {},
                        models, {sid: limits} if limits else {}, {sid: mahal} if mahal else None)
        return [er.Pred(v.verdict.value, frozenset(c.check.split(":")[0] for c in v.checks if c.flagged))
                for v in (pipe.process(r) for r in readings)]
    return predict


_PREPARED: dict[str, dict] = {}          # per worker process: what does not depend on the history length


def prepare_station(sid: str, settings: dict, meta: dict, stations: dict) -> dict:
    """Everything about a station that is the same for every history length. Deterministic (seeded), cached per process."""
    if sid in _PREPARED:
        return _PREPARED[sid]
    s = er.real_settings(settings)
    events = meta["events"][sid]
    windows = er.windows_of(events)
    df = er.read_frame(er.REAL_DEV_DIR / f"{sid}.csv", s, False)
    cadence = er.cadence_of(df)

    # the network: the other DEV stations' saved artifacts (fitted on their own 2016-2019 record)
    others = [o for o in meta["dev_stations"] if o != sid]
    tabs = {o: NormalityTable.load(model_path(s, o, "normality", ".json"), s) for o in others}
    lims = {o: StationLimits.load(model_path(s, o, "limits", ".json")) for o in others}
    near = coldstart.nearest_stations(stations[sid], {o: stations[o] for o in others}, 1)

    # evaluation data (same for every history length)
    lo, hi = er.TRAIN_END, er.DEV_END
    period = df[(df["timestamp"] >= lo) & (df["timestamp"] < hi)]
    period_events = [e for e in events if lo <= pd.Timestamp(e["center"]) < hi]
    clean = [er.to_readings(c) for c in er.cut_chunks(period, windows, int(3 * 1440 / cadence))]
    event_series, _ = er.cut_events(df, period_events)
    s_inj = copy.deepcopy(s)
    s_inj["injector"]["events_per_type"] = 2
    faulted = er.make_faulted(clean, s_inj, 1, int(30 * 1440 / cadence))

    # own history: the station's first D days of clean 2016-2019 record
    train_all = er.cut_chunks(df[df["timestamp"] < er.TRAIN_END], windows, 1)
    own_all = [r for c in train_all for r in er.to_readings(c)]
    _PREPARED[sid] = {"s": s, "cadence": cadence, "near": near, "own_all": own_all, "start": own_all[0].timestamp,
                      "starter_t": coldstart.starter_table([tabs[o] for o in near], s), "starter_l": [lims[o] for o in near],
                      "clean": clean, "event_series": event_series, "faulted": faulted}
    return _PREPARED[sid]


def run_job(args) -> dict:
    """One (station, days of own history): score both starting modes on the station's held-out DEV years."""
    sid, D, settings, meta, stations = args
    t0 = time.perf_counter()
    st = prepare_station(sid, settings, meta, stations)
    s, cadence = st["s"], st["cadence"]
    own = [r for r in st["own_all"] if (r.timestamp - st["start"]).days < D] if D else []
    own_days = len({r.timestamp.date() for r in own})
    own_table = NormalityTable.fit(own, s) if len(own) > 50 else None
    own_lim = fit_limits(own, s, cadence) if len(own) > 200 else None
    model = IsolationModel.fit(own, s) if D >= ML_FROM_DAYS and len(own) > 200 else None
    rows = []
    for mode in ("starter", "own_only"):
        if mode == "starter":
            table = coldstart.blend_tables(st["starter_t"], own_table, s)
            limits = coldstart.blend_limits(st["starter_l"], own_lim, own_days, sid, cadence, s)
        else:
            table, limits = own_table, own_lim
        mahal = (MahalanobisModel.fit(own, s, table)
                 if (table is not None and D >= ML_FROM_DAYS and len(own) > 200) else None)
        pred = er.memoize(_predict(s, table, model, limits, sid, cadence, mahal))
        c = er.count_clean(st["clean"], pred)
        ev_ = er.count_events(st["event_series"], pred)
        det = er.count_detection(st["faulted"], pred, s, cadence)
        tot = {k: sum(d.get(k, 0) for d in ev_.values()) for k in ("n", "FAULT", "SUSPECT", "WEATHER")}
        rows.append({"station": sid, "days": D, "mode": mode, "own_days": own_days, "clean": c, "events": tot,
                     "detection": {t: [det[t]["detected_new"], det[t]["injected"]] for t in TYPES}})
    return {"station": sid, "days": D, "borrowed_from": st["near"], "seconds": round(time.perf_counter() - t0, 1), "rows": rows}


def by_station(jobs: list[dict]) -> list[dict]:
    """Group finished jobs into one record per station (the shape `summarize` reads)."""
    out: dict[str, dict] = {}
    for j in sorted(jobs, key=lambda j: (j["station"], j["days"])):
        rec = out.setdefault(j["station"], {"station": j["station"], "borrowed_from": j["borrowed_from"], "rows": []})
        rec["rows"] += j["rows"]
    return list(out.values())


def fmt_duration(seconds: float) -> str:
    m = int(round(seconds / 60))
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min" if m >= 1 else f"{int(seconds)} s"


def eta_seconds(done: int, total: int, elapsed: float) -> Optional[float]:
    """Wall-clock estimate of what is left, from the pace so far (already includes the parallelism). None before any job ends."""
    return None if done <= 0 else elapsed / done * (total - done)


def project(job_seconds: list[float], total_jobs: int, workers: int) -> tuple[float, float]:
    """(typical, worst case) seconds for the whole run from timed sample jobs: mean or slowest job x jobs / workers."""
    return statistics.mean(job_seconds) * total_jobs / workers, max(job_seconds) * total_jobs / workers


def summarize(results: list[dict]) -> list[dict]:
    out = []
    for D in DAYS:
        for mode in ("starter", "own_only"):
            sel = [r for res in results for r in res["rows"] if r["days"] == D and r["mode"] == mode]
            n = sum(r["clean"]["n"] for r in sel)
            en = sum(r["events"]["n"] for r in sel)
            det_d = sum(r["detection"][t][0] for r in sel for t in TYPES)
            det_n = sum(r["detection"][t][1] for r in sel for t in TYPES)
            out.append({"days": D, "mode": mode, "clean_alarm_pct": round(100 * sum(r["clean"]["alarm"] for r in sel) / n, 2),
                        "clean_fault_pct": round(100 * sum(r["clean"]["fault"] for r in sel) / n, 2),
                        "event_fault_pct": round(100 * sum(r["events"]["FAULT"] for r in sel) / en, 2) if en else None,
                        "event_weather_pct": round(100 * sum(r["events"]["WEATHER"] for r in sel) / en, 2) if en else None,
                        "detect_pct": round(100 * det_d / det_n, 1) if det_n else None, "stations": len(sel)})
    return out


def format_table(rows: list[dict]) -> str:
    L = ["Cold start, leave-one-station-out, six DEV stations (real data). Starter = nearest other station's frozen table.",
         f"{'own days':>9} {'mode':<9}{'clean alarms':>13}{'clean FAULT':>13}{'real-weather FAULT':>20}{'WEATHER':>9}{'detect (frozen/spike/step)':>28}"]
    for r in rows:
        L.append(f"{r['days']:>9} {r['mode']:<9}{r['clean_alarm_pct']:>12}%{r['clean_fault_pct']:>12}%"
                 f"{r['event_fault_pct']:>19}%{r['event_weather_pct']:>8}%{r['detect_pct']:>27}%")
    return "\n".join(L)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Cold-start evaluation (DEV stations, leave-one-out).")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--stations", nargs="*")
    ap.add_argument("--out", type=Path, default=REPO / "results" / "coldstart.json")
    ap.add_argument("--estimate", action="store_true", help="time three sample jobs, print the projected running time, and stop")
    ap.add_argument("--resume", action="store_true", help="continue from <out>.partial.json instead of starting over")
    args = ap.parse_args(argv)
    settings = load_settings()
    meta = er.load_events()
    stations = {sid: st for sid, st in load_stations_yaml().items()}
    todo = [sid for sid in meta["dev_stations"] if not args.stations or sid in args.stations]
    all_jobs = [(sid, D) for D in sorted(DAYS, reverse=True) for sid in todo]        # the slow ones (with a forest) first

    if args.estimate:
        secs = []
        for D in (0, ML_FROM_DAYS, max(DAYS)):
            r = run_job((todo[0], D, settings, meta, stations))
            secs.append(r["seconds"])
            print(f"probe: {todo[0]}, {D:>4} days of own history: {r['seconds']} s", flush=True)
        typical, worst = project(secs, len(all_jobs), args.workers)
        print(f"{len(all_jobs)} jobs on {args.workers} workers: about {fmt_duration(typical)} "
              f"(worst case, every job as slow as the slowest probe: {fmt_duration(worst)})")
        return 0

    partial = args.out.with_suffix(".partial.json")
    done: list[dict] = []
    if args.resume and partial.exists():
        done = [j for j in json.loads(partial.read_text(encoding="utf-8")) if (j["station"], j["days"]) in set(all_jobs)]
        print(f"resuming: {len(done)} of {len(all_jobs)} jobs already done", flush=True)
    finished = {(j["station"], j["days"]) for j in done}
    pending = [(sid, D) for sid, D in all_jobs if (sid, D) not in finished]
    total, t0 = len(all_jobs), time.perf_counter()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    print(f"{len(pending)} jobs to run on {args.workers} workers ({len(done)} already done)", flush=True)

    def note(job: dict, n_done: int) -> None:
        elapsed = time.perf_counter() - t0
        eta = eta_seconds(n_done - len(done_at_start), len(pending), elapsed)
        print(f"[{n_done}/{total}] {job['station']} {job['days']:>4} days: {job['seconds']} s | elapsed {fmt_duration(elapsed)} | "
              f"ETA {'unknown' if eta is None else fmt_duration(eta)}", flush=True)
        partial.write_text(json.dumps(done), encoding="utf-8")

    done_at_start = list(done)
    if args.workers > 1 and len(pending) > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(run_job, (sid, D, settings, meta, stations)) for sid, D in pending]
            for f in as_completed(futures):
                done.append(f.result())
                note(done[-1], len(done))
    else:
        for sid, D in pending:
            done.append(run_job((sid, D, settings, meta, stations)))
            note(done[-1], len(done))

    res = by_station(done)
    summary = summarize(res)
    print(format_table(summary))
    wall = time.perf_counter() - t0
    args.out.write_text(json.dumps({"summary": summary, "stations": res,
                                    "timing": {"jobs": total, "workers": args.workers, "wall_minutes": round(wall / 60, 1),
                                               "job_seconds_total": round(sum(j["seconds"] for j in done), 1)}}, indent=1), encoding="utf-8")
    partial.unlink(missing_ok=True)
    print(f"finished {total} jobs in {fmt_duration(wall)}; wrote {args.out}")
    return 0


def load_stations_yaml() -> dict:
    data = yaml.safe_load((CONFIG_DIR / "stations.yaml").read_text(encoding="utf-8"))
    return {s["id"]: s for s in data["stations"]}


if __name__ == "__main__":
    raise SystemExit(main())
