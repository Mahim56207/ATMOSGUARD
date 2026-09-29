"""Refit one station's learned models on a stretch of its own record and save them to models/.

    python refit.py path/to/station.csv --station MYAWS --from 2020-01-01 [--to 2022-01-01]

When the `limits` notice says a station's limits do not fit (an unlearned noise limit, or a cadence different from the one the limits were learned at), fit
again on a stretch that has the cadence and resolution you are going to judge. This fits the same four things every committed station has (month-by-hour
normality table, Isolation Forest, Mahalanobis model, learned limits) with the same code the evaluation uses, and writes models/<STATION>_*.  Stated limits:
whatever is in the stretch is learned as normal (a stuck sensor or a storm included), it needs at least two weeks and 300 complete readings, and it cuts nothing
out (`evaluate_csv.py` is the careful offline version that removes extreme-weather windows). On the seven Australian AWS of the third sealed set, refitting on the
hourly years only took clean false alarms from 13.6 % to 2.6 % (`refit_diagnostic.py`).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

from atmos import autofit
from atmos.config import load_settings, model_path
from atmos.limits import StationLimits, complete_limits, fit_limits
from atmos.mlmodel import IsolationModel, MahalanobisModel
from atmos.normality import NormalityTable
from atmos.schema import CHANNELS, Reading


def read_stretch(path: Path, station: str, start: Optional[str], end: Optional[str]) -> list[Reading]:
    df = pd.read_csv(path, parse_dates=["timestamp"]).sort_values("timestamp").drop_duplicates("timestamp")
    if start:
        df = df[df["timestamp"] >= pd.Timestamp(start)]
    if end:
        df = df[df["timestamp"] < pd.Timestamp(end)]
    return [Reading(station_id=station, timestamp=t.to_pydatetime(), temperature_c=a, pressure_hpa=b, humidity_pct=c)
            for t, a, b, c in zip(df["timestamp"], df["temperature_c"], df["pressure_hpa"], df["humidity_pct"])
            if not any(pd.isna(v) for v in (a, b, c))]


def refit(readings: list[Reading], station: str, settings: dict) -> dict:
    span_days = (readings[-1].timestamp - readings[0].timestamp).days if len(readings) > 1 else 0
    if len(readings) < autofit.MIN_ROWS or span_days < autofit.MIN_DAYS:
        raise ValueError(f"only {len(readings)} complete readings over {span_days} days: need at least {autofit.MIN_ROWS} over {autofit.MIN_DAYS}")
    cadence = autofit.cadence_of(readings)
    table = NormalityTable.fit(readings, settings)
    model = IsolationModel.fit(readings, settings)
    limits = fit_limits(readings, settings, cadence)
    mahal = MahalanobisModel.fit(readings, settings, table)
    table.save(model_path(settings, station, "normality", ".json"))
    model.save(model_path(settings, station, "iforest", ".joblib"))
    limits.save(model_path(settings, station, "limits", ".json"))
    mahal.save(model_path(settings, station, "mahalanobis", ".joblib"))
    unlearned = [ch for ch in CHANNELS if limits.noise_std(ch) is None]
    return {"station": station, "readings": len(readings), "days": span_days, "cadence_minutes": cadence,
            "resolution": {ch: c.resolution for ch, c in limits.channels.items()},
            "noise_limit_learned": {ch: limits.noise_std(ch) is not None for ch in CHANNELS},
            "warning": (f"no noise limit learned for {', '.join(unlearned)}: the stretch has too few runs of equally spaced readings; pick a more regular one"
                        if unlearned else None)}


def complete(readings: list[Reading], station: str, settings: dict) -> dict:
    """Amendment 4: keep the station's existing limits and fill only those it could not learn (typically the noise limit) from this stretch."""
    path = model_path(settings, station, "limits", ".json")
    if not Path(path).exists():
        raise ValueError(f"{station} has no saved limits to complete: run refit.py without --complete first")
    span_days = (readings[-1].timestamp - readings[0].timestamp).days if len(readings) > 1 else 0
    if len(readings) < autofit.MIN_ROWS or span_days < autofit.MIN_DAYS:
        raise ValueError(f"only {len(readings)} complete readings over {span_days} days: need at least {autofit.MIN_ROWS} over {autofit.MIN_DAYS}")
    base = StationLimits.load(path)
    out = complete_limits(base, readings, settings, autofit.cadence_of(readings))
    out.save(path)
    return {"station": station, "readings": len(readings), "days": span_days, "cadence_minutes": out.cadence_minutes,
            "noise_limit_learned": {ch: out.noise_std(ch) is not None for ch in CHANNELS}}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Refit one station's learned models on a stretch of its own record.")
    ap.add_argument("csv", type=Path)
    ap.add_argument("--station", required=True)
    ap.add_argument("--from", dest="start", default=None, help="first timestamp to learn from (UTC, e.g. 2020-01-01)")
    ap.add_argument("--to", dest="end", default=None, help="learn up to, not including, this timestamp")
    ap.add_argument("--complete", action="store_true", help="keep the saved limits and fill only the ones that were never learned from this stretch (needs saved limits). Tested in Amendment 4: it removes the false-alarm flood at stations with an irregular training record (45 % to 2 %) and costs noise-burst detection (about 6 points pooled), so it is an operator's choice, not a default")
    args = ap.parse_args(argv)
    settings = load_settings()
    try:
        stretch = read_stretch(args.csv, args.station, args.start, args.end)
        out = complete(stretch, args.station, settings) if args.complete else refit(stretch, args.station, settings)
    except ValueError as e:
        print(f"Cannot refit: {e}")
        return 2
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
