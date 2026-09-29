"""Run the AtmosGuard evaluation on YOUR data (for example a few years of a real IMD AWS record).

    python evaluate_csv.py data/my_aws.csv --station MYAWS
    python evaluate_csv.py data/my_aws.csv --station MYAWS --train-fraction 0.6 --quick

CSV columns: timestamp (UTC), temperature_c, pressure_hpa, humidity_pct. Optional: station_id, noaa_flag (or any quality flag
column named noaa_flag with 0 = fine). An empty cell is a missing value.

What it does, on the same code as the committed evaluation: the first `--train-fraction` of the record (in time) fits the station's
models; the rest is judged. Extreme-weather windows are found by the SAME objective rules as for the NOAA stations (deepest low-pressure
episodes, hottest and coldest days, sharpest 3-hour changes) on your own data, cut out of training and clean evaluation, and judged
separately. You get the same numbers: false alarms on clean data, what happens to real extreme weather, detection of injected faults
(paired, so background alarms are not credited), drift power and false drift claims, plus the baselines and the ablation.

It needs at least about two years of record so every month has data, and reports the cadence it found. The output is a check on your
station, not a holdout: nothing about it is sealed.
"""
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path
from typing import Optional

import pandas as pd

import evaluate_real as er
from atmos.config import load_settings
from data_tools import make_dataset


def prepare(path: Path, station: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp"])
    missing = {"timestamp", "temperature_c", "pressure_hpa", "humidity_pct"} - set(df.columns)
    if missing:
        raise SystemExit(f"CSV is missing columns: {', '.join(sorted(missing))}")
    df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    df["station_id"] = station
    if "noaa_flag" not in df.columns:
        df["noaa_flag"] = 0
    return df[["station_id", "timestamp", "temperature_c", "pressure_hpa", "humidity_pct", "noaa_flag"]]


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate AtmosGuard on your own station CSV.")
    ap.add_argument("csv", type=Path)
    ap.add_argument("--station", required=True)
    ap.add_argument("--train-fraction", type=float, default=0.6, help="share of the record (in time) used to fit the models")
    ap.add_argument("--quick", action="store_true", help="one year of evaluation and one fault round")
    ap.add_argument("--parts", default="detect,events,noaa,drift", help="comma list: detect, events, noaa, drift, latency")
    args = ap.parse_args(argv)

    df = prepare(args.csv, args.station)
    span_days = (df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]).days
    if span_days < 700:
        print(f"Warning: only {span_days} days of record. The month-by-hour table needs about two years; results will be weak.")
    split = df["timestamp"].iloc[int(len(df) * args.train_fraction)].normalize()
    end = df["timestamp"].iloc[-1] + pd.Timedelta(seconds=1)
    events = make_dataset.find_events(df.assign(timestamp=df["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%S")))
    print(f"{args.station}: {len(df)} readings, cadence {er.cadence_of(df):g} min, train before {split.date()}, "
          f"{sum(pd.Timestamp(e['center']) >= split for e in events)} extreme-weather windows to judge "
          f"({sum(pd.Timestamp(e['center']) < split for e in events)} cut out of training)")

    er.TRAIN_END, er.DEV_END = split, end                     # the evaluation reads these two module settings
    settings = load_settings()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d) / f"{args.station}.csv"
        df.to_csv(tmp, index=False)
        plan = er.PhasePlan("DEV", args.station, tmp, tmp, (split, end), False)
        result = er.evaluate_station(plan, settings, args.quick, events, frozenset(args.parts.split(",")))
    print()
    print(er.format_phase(er.aggregate([result], "DEV"), f"YOUR DATA: {args.station}"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
