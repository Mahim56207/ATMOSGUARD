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
"""
from __future__ import annotations

import argparse
import copy
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yaml

import evaluate_real as er
from atmos import coldstart
from atmos.config import CONFIG_DIR, load_settings, model_path
from atmos.fusion import Pipeline
from atmos.limits import StationLimits, fit_limits
from atmos.mlmodel import IsolationModel
from atmos.normality import NormalityTable

DAYS = (0, 7, 30, 90, 180, 365, 1460)
ML_FROM_DAYS = 90
TYPES = ("frozen", "spike", "step")
REPO = er.REPO


def _predict(settings, table, model, limits, sid, cadence):
    s = copy.deepcopy(settings)
    if model is None:
        s["layers"]["mlmodel"] = False

    def predict(readings):
        pipe = Pipeline(s, {sid: {"cadence_minutes": cadence}}, {sid: table} if table else {},
                        {sid: model} if model else {}, {sid: limits} if limits else {})
        return [er.Pred(v.verdict.value, frozenset(c.check.split(":")[0] for c in v.checks if c.flagged))
                for v in (pipe.process(r) for r in readings)]
    return predict


def one_station(args) -> dict:
    sid, settings, meta, stations = args
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
    starter_t = coldstart.starter_table([tabs[o] for o in near], s)
    starter_l = [lims[o] for o in near]

    # evaluation data (same for every D)
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
    start = own_all[0].timestamp
    rows = []
    for D in DAYS:
        own = [r for r in own_all if (r.timestamp - start).days < D] if D else []
        own_days = len({r.timestamp.date() for r in own})
        own_table = NormalityTable.fit(own, s) if len(own) > 50 else None
        own_lim = fit_limits(own, s, cadence) if len(own) > 200 else None
        model = IsolationModel.fit(own, s) if D >= ML_FROM_DAYS and len(own) > 200 else None
        for mode in ("starter", "own_only"):
            if mode == "starter":
                table = coldstart.blend_tables(starter_t, own_table, s)
                limits = coldstart.blend_limits(starter_l, own_lim, own_days, sid, cadence, s)
            else:
                table, limits = own_table, own_lim
            pred = _predict(s, table, model, limits, sid, cadence)
            c = er.count_clean(clean, pred)
            ev_ = er.count_events(event_series, pred)
            det = er.count_detection(faulted, pred, s, cadence)
            tot = {k: sum(d.get(k, 0) for d in ev_.values()) for k in ("n", "FAULT", "SUSPECT", "WEATHER")}
            rows.append({"station": sid, "days": D, "mode": mode, "own_days": own_days, "clean": c, "events": tot,
                         "detection": {t: [det[t]["detected"], det[t]["injected"]] for t in TYPES}})
    return {"station": sid, "borrowed_from": near, "rows": rows}


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
    args = ap.parse_args(argv)
    settings = load_settings()
    meta = er.load_events()
    stations = {sid: st for sid, st in load_stations_yaml().items()}
    todo = [sid for sid in meta["dev_stations"] if not args.stations or sid in args.stations]
    jobs = [(sid, settings, meta, stations) for sid in todo]
    if args.workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            res = list(pool.map(one_station, jobs))
    else:
        res = [one_station(j) for j in jobs]
    summary = summarize(res)
    print(format_table(summary))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"summary": summary, "stations": res}, indent=1), encoding="utf-8")
    return 0


def load_stations_yaml() -> dict:
    data = yaml.safe_load((CONFIG_DIR / "stations.yaml").read_text(encoding="utf-8"))
    return {s["id"]: s for s in data["stations"]}


if __name__ == "__main__":
    raise SystemExit(main())
