"""Which check made a real extreme-weather window get a FAULT? Reads the reasons off the pipeline for one station.

    python window_forensics.py --phase FRESH --station IXR
    python window_forensics.py --phase HOLDOUT_SPACE --station VTZ --remedies

Fits the station exactly as evaluate_real.evaluate_station does (its own 2016-2019 record, windows and NOAA-flagged values removed),
runs the full pipeline over every extreme-weather window of the evaluation period, and prints the FAULT samples with the checks that
fired and their reasons. `--remedies` runs the pipeline with both post-mortem remedies switched on instead.
This is for explaining verdicts that are already reported. It never writes a lock file and changes nothing.
"""
from __future__ import annotations

import argparse
import copy
from typing import Optional

import pandas as pd

import evaluate_real as er
from atmos.config import load_settings
from atmos.fusion import Pipeline
from atmos.limits import fit_limits
from atmos.mlmodel import IsolationModel, MahalanobisModel
from atmos.normality import NormalityTable
import evaluate as ev


def forensics(phase: str, station: str, remedies: bool) -> list[dict]:
    settings = load_settings()
    s = er.real_settings(settings)
    if remedies:
        s["health"]["frozen"]["ceiling_aware"] = True
        s["limits"]["learned_step_cap"] = True
    meta = er.load_events(phase)
    plan = next(p for p in er.make_plans(phase if phase != "HOLDOUT_SPACE" else "HOLDOUT", meta) if p.station == station and p.name == phase)
    df = er.read_frame(plan.train_path, s, True)
    eval_df = df if plan.eval_path == plan.train_path else er.read_frame(plan.eval_path, s, True)
    cadence = er.cadence_of(df)
    events_all = meta["events"][station]
    windows = er.windows_of(events_all)
    train = [r for c in er.cut_chunks(df[df["timestamp"] < er.TRAIN_END], windows, 1) for r in er.to_readings(c)]
    table, model = NormalityTable.fit(train, s), IsolationModel.fit(train, s)
    limits, mahal = fit_limits(train, s, cadence), MahalanobisModel.fit(train, s, table)
    lo, hi = plan.period
    period_events = [e for e in events_all if lo <= pd.Timestamp(e["center"]) < hi]
    series, _ = er.cut_events(eval_df, period_events)
    out = []
    for es in series:
        pipe = Pipeline(s, {station: {"cadence_minutes": cadence}}, {station: table}, {station: ev._PrecomputedModel(model, es.readings)},
                        {station: limits}, {station: mahal})
        rows = []
        for i, r in enumerate(es.readings):
            v = pipe.process(r)
            if es.core_start <= i < es.core_end and v.verdict.value == "FAULT":
                rows.append({"time": r.timestamp.isoformat(), "T": r.temperature_c, "P": r.pressure_hpa, "RH": r.humidity_pct,
                             "checks": [(c.check, c.severity, c.reason) for c in v.checks if c.flagged], "reason": v.reason})
        if rows:
            out.append({"kind": es.kind, "center": es.center, "fault_samples": rows})
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Explain the FAULT verdicts inside real extreme-weather windows.")
    ap.add_argument("--phase", required=True, choices=("DEV", "HOLDOUT_SPACE", "FRESH"))
    ap.add_argument("--station", required=True)
    ap.add_argument("--remedies", action="store_true")
    args = ap.parse_args(argv)
    found = forensics(args.phase, args.station, args.remedies)
    print(f"{args.station} ({args.phase}{', remedies on' if args.remedies else ''}): {len(found)} window(s) with a FAULT")
    for w in found:
        print(f"\n{w['kind']} window centred {w['center'][:16]}: {len(w['fault_samples'])} FAULT sample(s)")
        for row in w["fault_samples"][:6]:
            print(f"  {row['time']}  T {row['T']}  P {row['P']}  RH {row['RH']}")
            for name, sev, reason in row["checks"]:
                print(f"     {name} [{sev}]: {reason}")
        if len(w["fault_samples"]) > 6:
            print(f"  ... and {len(w['fault_samples']) - 6} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
