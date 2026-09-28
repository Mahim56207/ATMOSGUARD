"""Fit and save the per-station artifacts (normality table, Isolation Forest, learned limits) from real data.

    python train.py --all                 # the six DEV stations, from data/real/dev
    python train.py --station BBI         # one station

Uses exactly the fitting of evaluate_real.py (the station's own 2016-2019 record, extreme-weather windows and
NOAA-flagged values removed), so what the demo runs is what the evaluation measured. Files land in models/
(<STATION>_normality.json, <STATION>_iforest.joblib, <STATION>_limits.json). Fixed seed: the same command gives
the same files. Only DEV stations can be trained here: the sealed stations are read by evaluate_real.py --holdout only.
"""
from __future__ import annotations

import argparse
import json
from typing import Optional

import pandas as pd

import evaluate_real as er
from atmos.config import load_settings, model_path
from atmos.limits import fit_limits
from atmos.mlmodel import IsolationModel
from atmos.normality import NormalityTable


def train_station(station: str, settings: dict, events: list[dict]) -> dict:
    s = er.real_settings(settings)
    df = er.read_frame(er.REAL_DEV_DIR / f"{station}.csv", s, allow_holdout=False)
    cadence = er.cadence_of(df)
    tr = df[df["timestamp"] < er.TRAIN_END]
    train = [r for c in er.cut_chunks(tr, er.windows_of(events), 1) for r in er.to_readings(c)]
    table = NormalityTable.fit(train, s)
    model = IsolationModel.fit(train, s)
    limits = fit_limits(train, s, cadence)
    table.save(model_path(settings, station, "normality", ".json"))
    model.save(model_path(settings, station, "iforest", ".joblib"))
    limits.save(model_path(settings, station, "limits", ".json"))
    return {"station": station, "rows": len(train), "cadence_minutes": cadence,
            "resolution": {ch: c.resolution for ch, c in limits.channels.items()},
            "frozen_limit_min": {ch: round(c.frozen_minutes or 0) for ch, c in limits.channels.items()}}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Train the per-station artifacts from real DEV data.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true")
    g.add_argument("--station")
    args = ap.parse_args(argv)
    settings = load_settings()
    meta = er.load_events()
    stations = meta["dev_stations"] if args.all else [args.station]
    for sid in stations:
        if sid not in meta["dev_stations"]:
            print(f"{sid} is not a DEV station. Sealed stations are only read by evaluate_real.py --holdout.")
            return 2
        print(json.dumps(train_station(sid, settings, meta["events"][sid])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
