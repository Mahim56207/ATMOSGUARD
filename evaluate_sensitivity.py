"""How big does a fault have to be? Detection against the size of the injected fault, on the DEV stations.

    python evaluate_sensitivity.py --workers 4 --out results/sensitivity.json
    python evaluate_sensitivity.py --estimate                     # times one station and projects the whole run

The evaluation injects spikes, level shifts and noise bursts of ONE size (`injector.magnitude` in config/settings.yaml). This sweeps that size
(0.25, 0.5, 1, 2, 4 times the configured one) and reports, per fault type, the share of faults whose alarm the fault itself raised (the paired
criterion of Amendment 1), for AtmosGuard and for two simpler systems on the same faults. The size at which detection passes 50 % is the honest
statement of what "detects a level shift" means. Frozen sensors, dropouts and wrong clocks have no size and are not swept.
DEV stations and DEV years only (the tuning set): this is a study of the system's envelope, not a held-out result.
"""
from __future__ import annotations

import argparse
import copy
import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import pandas as pd

import evaluate_real as er
from atmos.config import load_settings
from atmos.limits import fit_limits
from atmos.mlmodel import IsolationModel, MahalanobisModel
from atmos.normality import NormalityTable

REPO = er.REPO
MULTIPLIERS = (0.25, 0.5, 1.0, 2.0, 4.0)
SWEPT = ("spike", "step", "noise")
SYSTEMS = {"full": "AtmosGuard", "baseline_rules": "textbook range + step + persistence", "baseline_mahalanobis": "Mahalanobis distance only"}


def scaled(settings: dict, m: float) -> dict:
    s = copy.deepcopy(settings)
    for ty in SWEPT:
        for ch in s["injector"]["magnitude"][ty]:
            s["injector"]["magnitude"][ty][ch] *= m
    return s


def one_station(args) -> dict:
    sid, settings, meta, multipliers = args
    t0 = time.perf_counter()
    s = er.real_settings(settings)
    events = meta["events"][sid]
    windows = er.windows_of(events)
    df = er.read_frame(er.REAL_DEV_DIR / f"{sid}.csv", s, False)
    cadence = er.cadence_of(df)
    train = [r for c in er.cut_chunks(df[df["timestamp"] < er.TRAIN_END], windows, 1) for r in er.to_readings(c)]
    table, model = NormalityTable.fit(train, s), IsolationModel.fit(train, s)
    limits, mahal = fit_limits(train, s, cadence), MahalanobisModel.fit(train, s, table)
    period = df[(df["timestamp"] >= er.TRAIN_END) & (df["timestamp"] < er.DEV_END)]
    clean = [er.to_readings(c) for c in er.cut_chunks(period, windows, int(3 * 1440 / cadence))]
    predictors = {name: p for name, _, p in er.build_configs(s, table, model, limits, train, sid, cadence, mahal) if name in SYSTEMS}
    out: dict = {name: {} for name in SYSTEMS}
    for m in multipliers:
        sm = scaled(s, m)
        sm["injector"]["events_per_type"] = 2
        faulted = er.make_faulted(clean, sm, 1, int(30 * 1440 / cadence))
        for name, predict in predictors.items():
            det = er.count_detection(faulted, predict, sm, cadence)
            out[name][str(m)] = {ty: [det[ty]["detected_new"], det[ty]["injected"]] for ty in SWEPT}
    return {"station": sid, "seconds": round(time.perf_counter() - t0, 1), "systems": out}


def pooled(results: list[dict], multipliers) -> dict:
    tot: dict = {name: {str(m): {ty: [0, 0] for ty in SWEPT} for m in multipliers} for name in SYSTEMS}
    for r in results:
        for name, by_m in r["systems"].items():
            for m, by_t in by_m.items():
                for ty, (d, n) in by_t.items():
                    tot[name][m][ty][0] += d
                    tot[name][m][ty][1] += n
    return tot


def fmt(tot: dict, multipliers) -> str:
    L = ["Detection (the fault raised the alarm) against the size of the injected fault, DEV stations, pooled. 1x = the size used everywhere else."]
    for name, label in SYSTEMS.items():
        L.append(f"\n{label}")
        L.append(f"  {'size':>6}" + "".join(f"{ty:>10}" for ty in SWEPT))
        for m in multipliers:
            cells = "".join(f"{100 * tot[name][str(m)][ty][0] / max(tot[name][str(m)][ty][1], 1):>9.0f}%" for ty in SWEPT)
            L.append(f"  {m:>5g}x{cells}")
    return "\n".join(L)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Detection against fault size on the DEV stations.")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--multipliers", type=float, nargs="+", default=list(MULTIPLIERS))
    ap.add_argument("--stations", nargs="*")
    ap.add_argument("--estimate", action="store_true")
    ap.add_argument("--out", type=Path, default=REPO / "results" / "sensitivity.json")
    args = ap.parse_args(argv)
    settings = load_settings()
    meta = er.load_events()
    todo = [sid for sid in meta["dev_stations"] if not args.stations or sid in args.stations]
    if args.estimate:
        r = one_station((todo[0], settings, meta, args.multipliers))
        print(f"one station ({todo[0]}): {r['seconds']} s; {len(todo)} stations on {args.workers} workers: about "
              f"{r['seconds'] * len(todo) / args.workers / 60:.1f} min")
        return 0
    jobs = [(sid, settings, meta, args.multipliers) for sid in todo]
    results, t0 = [], time.perf_counter()
    if args.workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            for f in as_completed([pool.submit(one_station, j) for j in jobs]):
                results.append(f.result())
                print(f"[{len(results)}/{len(jobs)}] {results[-1]['station']}: {results[-1]['seconds']} s, elapsed {(time.perf_counter() - t0) / 60:.1f} min", flush=True)
    else:
        for j in jobs:
            results.append(one_station(j))
    tot = pooled(results, args.multipliers)
    print(fmt(tot, args.multipliers))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"multipliers": args.multipliers, "swept": list(SWEPT), "systems": SYSTEMS, "pooled": tot, "stations": results,
                                    "timing": {"wall_minutes": round((time.perf_counter() - t0) / 60, 1), "workers": args.workers}}, indent=1),
                        encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
