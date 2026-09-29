"""Turn the built station series into the DEV / HOLDOUT layout and cut real extreme-weather windows.

Layout written (all CSV, columns: station_id, timestamp, temperature_c, pressure_hpa, humidity_pct, noaa_flag):
  data/real/dev/<STN>.csv                    DEV stations, 2016-01-01 .. 2021-12-31
  data/holdout/real/<STN>_future.csv         the DEV stations again, 2022-01-01 .. 2024-12-31   (HOLDOUT in time)
  data/holdout/real/<STN>.csv                sealed stations, whole record 2016 .. 2024          (HOLDOUT in space)
  data/real/events.json                      the extreme-weather windows found by the rules below (both splits)

Extreme-weather windows are picked by objective rules on the station's own data, NOT by looking at what
AtmosGuard says about them, and the rules are written down in config/protocol.md before any holdout run:

  low     pressure at least `low_deficit_hpa` below its trailing 30-day median (cyclones, deep depressions)
  heat    the hottest days: daily maximum temperature in the top `heat_quantile` of the station's daily maxima
  cold    the coldest days: daily minimum temperature in the bottom `cold_quantile` of the station's daily minima
  sharp   the largest 3-hour temperature changes (thunderstorm outflow, nor'wester, western disturbance)
At most `max_per_kind` heat and cold windows and `max_low` low-pressure windows per station (strongest first,
ties broken by the earlier date).
Each window is +/- `pad_days` around the extreme. Windows are removed from the training and clean-evaluation data
of their station, so "clean" never contains the weather we call extreme.

Usage:  python -m data_tools.make_dataset
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import isd

REPO = isd.REPO
DEV_STATIONS = ["BBI", "MAA", "CCU", "DEL", "JAI", "TRV"]                 # tuning allowed here (2016-2021)
SEALED_STATIONS = ["AMD", "NAG", "BOM", "GAU", "VTZ",                      # hourly, never tuned on
                   "IXZ", "BHJ", "COK"]                                    # 3-hourly SYNOP, never tuned on
SPLIT_DATE = pd.Timestamp("2022-01-01")

RULES = {
    "low_deficit_hpa": 10.0,       # pressure this far below its trailing 30-day median
    "heat_quantile": 0.997,
    "cold_quantile": 0.003,
    "max_per_kind": 5,             # heat and cold windows per station
    "max_low": 8,                  # deepest low-pressure windows per station
    "sharp_per_year": 1,
    "separation_days": {"low": 5, "heat": 7, "cold": 7, "sharp": 3},
    "pad_days": {"low": 3, "heat": 3, "cold": 3, "sharp": 2},
    "local_utc_offset_hours": 5.5,  # only used to cut "days" for heat / cold
}


def _dedupe(candidates: list[tuple[pd.Timestamp, float]], sep_days: float) -> list[tuple[pd.Timestamp, float]]:
    """Strongest first, drop any that fall within `sep_days` of one already kept."""
    kept: list[tuple[pd.Timestamp, float]] = []
    for t, score in sorted(candidates, key=lambda x: (-x[1], x[0])):        # strongest first, earlier date on ties
        if all(abs((t - q).total_seconds()) > sep_days * 86400 for q, _ in kept):
            kept.append((t, score))
    return sorted(kept)


def find_events(df: pd.DataFrame, rules: dict = RULES) -> list[dict]:
    """Extreme-weather windows for ONE station (df has a `timestamp` column and the three channels)."""
    d = df.set_index(pd.to_datetime(df["timestamp"])).sort_index()
    events: list[dict] = []

    def add(kind: str, t: pd.Timestamp, score: float, note: str) -> None:
        pad = pd.Timedelta(days=rules["pad_days"][kind])
        events.append({"kind": kind, "center": t.isoformat(), "start": (t - pad).isoformat(),
                       "end": (t + pad).isoformat(), "score": round(float(score), 3), "note": note})

    # low pressure
    p = d["pressure_hpa"].dropna()
    base = p.rolling("30D", min_periods=20).median()
    dev = (p - base).dropna()
    cand = [(t, -v) for t, v in dev[dev <= -rules["low_deficit_hpa"]].items()]
    for t, score in sorted(sorted(_dedupe(cand, rules["separation_days"]["low"]), key=lambda x: (-x[1], x[0]))
                           [: rules["max_low"]]):
        add("low", t, score, f"pressure {dev[t]:+.1f} hPa vs 30-day median")

    # heat / cold (days are cut at local time)
    local = d.copy()
    local.index = local.index + pd.Timedelta(hours=rules["local_utc_offset_hours"])
    daily = local["temperature_c"].groupby(local.index.date)
    tmax, tmin = daily.max(), daily.min()
    counts = daily.count()
    ok = counts >= max(3, int(0.5 * counts.median()))
    tmax, tmin = tmax[ok], tmin[ok]
    hot_lim = tmax.quantile(rules["heat_quantile"])
    cold_lim = tmin.quantile(rules["cold_quantile"])
    cand = [(pd.Timestamp(day) + pd.Timedelta(hours=12), float(v)) for day, v in tmax[tmax >= hot_lim].items()]
    for t, score in sorted(sorted(_dedupe(cand, rules["separation_days"]["heat"]), key=lambda x: (-x[1], x[0]))
                           [: rules["max_per_kind"]]):
        add("heat", t, score, f"daily max {score:.0f} C")
    cand = [(pd.Timestamp(day) + pd.Timedelta(hours=12), float(-v)) for day, v in tmin[tmin <= cold_lim].items()]
    for t, score in sorted(sorted(_dedupe(cand, rules["separation_days"]["cold"]), key=lambda x: (-x[1], x[0]))
                           [: rules["max_per_kind"]]):
        add("cold", t, score, f"daily min {-score:.0f} C")

    # sharp 3-hour temperature change (consecutive-in-time samples only)
    tt = d["temperature_c"].dropna()
    step = tt.index.to_series().diff().dt.total_seconds() / 3600.0
    hours = 3.0
    if float(step.median()) >= 3.0:                       # 3-hourly SYNOP: one step is already 3 h
        change = tt.diff().abs()
        change[step > 3.5] = np.nan
    else:
        shifted = tt.reindex(tt.index - pd.Timedelta(hours=hours))
        change = (tt.values - shifted.values)
        change = pd.Series(np.abs(change), index=tt.index)
    change = change.dropna()
    for year, g in change.groupby(change.index.year):
        cand = [(t, float(v)) for t, v in g.items()]
        picked = _dedupe(cand, rules["separation_days"]["sharp"])
        picked = sorted(picked, key=lambda x: (-x[1], x[0]))[: rules["sharp_per_year"]]
        for t, score in sorted(picked):
            add("sharp", t, score, f"{score:.0f} C change in 3 h")
    return sorted(events, key=lambda e: e["center"])


def merge_windows(events: list[dict]) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    spans = sorted((pd.Timestamp(e["start"]), pd.Timestamp(e["end"])) for e in events)
    out: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for s, e in spans:
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def main() -> int:
    cat = isd.load_catalog()
    (REPO / "data" / "real" / "dev").mkdir(parents=True, exist_ok=True)
    (REPO / "data" / "holdout" / "real").mkdir(parents=True, exist_ok=True)
    all_events: dict[str, list[dict]] = {}
    for sid, st in cat["stations"].items():
        src = REPO / "data" / "real" / sid / f"{sid}_60min.csv"
        if not src.exists():
            continue
        df = pd.read_csv(src)
        ts = pd.to_datetime(df["timestamp"])
        if sid in DEV_STATIONS:
            df[ts < SPLIT_DATE].to_csv(REPO / "data" / "real" / "dev" / f"{sid}.csv", index=False)
            df[ts >= SPLIT_DATE].to_csv(REPO / "data" / "holdout" / "real" / f"{sid}_future.csv", index=False)
        elif sid in SEALED_STATIONS:
            df.to_csv(REPO / "data" / "holdout" / "real" / f"{sid}.csv", index=False)
        else:
            continue
        ev = find_events(df)
        all_events[sid] = ev
        kinds = pd.Series([e["kind"] for e in ev]).value_counts().to_dict()
        print(f"{sid}: {len(df)} rows, {len(ev)} events {kinds}")
    (REPO / "data" / "real" / "events.json").write_text(
        json.dumps({"rules": RULES, "dev_stations": DEV_STATIONS, "sealed_stations": SEALED_STATIONS,
                    "split_date": str(SPLIT_DATE.date()), "events": all_events}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
