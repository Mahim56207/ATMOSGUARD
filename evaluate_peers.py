"""Peer-layer study: can neighbours see the constant offsets and slow drifts that one station cannot?

    python evaluate_peers.py --out results/peers.json

Twelve Australian AWS in central-west New South Wales (data_tools/stations_peers.yaml, built by `python -m data_tools.make_peers`), hourly, 2016-2024.
Each station's own normality table is fitted on 2016-2019. Anomalies (reading minus that station's own smooth normal) are compared with the median
anomaly of its neighbours within RADIUS_KM (at least MIN_PEERS). The alarm is the 7-day mean of the difference beyond a limit learned from the clean
training years (99.9th percentile of |7-day mean| x 1.2). The comparison the study exists to make: the same statistic on the station's OWN
anomaly, with no neighbours, which is all a single station has.

Faults are injected into the test years 2020-2023 (constant offsets of three sizes per channel, and linear drifts); false alarms are counted
on the un-faulted series. Paired scoring as in Amendment 1: an alarm counts only if the same hour was not already an alarm on the clean series.
No pipeline layer other than the normality table is involved, and nothing here is tuned on the injected faults: the limit comes from the
training years alone. It is a study on a dense network, not a claim about a sparse one.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from atmos import peers
from atmos.config import load_settings
from atmos.normality import NormalityTable
from atmos.schema import CHANNELS, Reading
from data_tools import isd

REPO = Path(__file__).resolve().parent
DATA = REPO / "data" / "peers" / "nsw"                 # set by --cluster
CATALOG = REPO / "data_tools" / "stations_peers_nsw.yaml"
QUANTILE = 0.999                                       # limit = this quantile of the clean training |mean difference| x MARGIN (--quantile, --margin)
MARGIN = 1.2
TRAIN_END = pd.Timestamp("2020-01-01")
TEST_END = pd.Timestamp("2024-01-01")            # faults start in 2020-2023 so that a 60-day fault always fits
RADIUS_KM = 250.0
MIN_PEERS = 3
WINDOW_H = 168
SIZES = {"temperature_c": (0.5, 1.0, 2.0), "pressure_hpa": (0.5, 1.0, 2.0), "humidity_pct": (3.0, 6.0, 12.0)}
DRIFT_TOTAL = {"temperature_c": 2.0, "pressure_hpa": 2.0, "humidity_pct": 12.0}       # linear ramp over the fault length
FAULT_DAYS = 60
DETECT_DAYS = 21                                  # a constant offset must be caught within this long of its start
TRIALS_PER_STATION = 12
SEED = 7


def load_station(sid: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / f"{sid}.csv", parse_dates=["timestamp"])
    return df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)


def to_readings(df: pd.DataFrame) -> list[Reading]:
    return [Reading(station_id=r.station_id, timestamp=r.timestamp.to_pydatetime(), temperature_c=r.temperature_c,
                    pressure_hpa=r.pressure_hpa, humidity_pct=r.humidity_pct) for r in df.itertuples()]


def build(settings: dict) -> tuple[dict, dict, pd.DatetimeIndex]:
    cat = isd.load_catalog(CATALOG)
    coords = {sid: (st["lat"], st["lon"]) for sid, st in cat["stations"].items()}
    index = pd.date_range("2016-01-01", "2024-12-31 23:00", freq="h")
    anoms = {}
    for sid in cat["stations"]:
        df = load_station(sid)
        table = NormalityTable.fit(to_readings(df[df["timestamp"] < TRAIN_END]), settings)
        anoms[sid] = peers.own_anomalies(df, table, index)
    return coords, anoms, index


def first_alarm(alarm: np.ndarray, start: int, stop: int, clean_alarm: np.ndarray) -> Optional[int]:
    hit = np.flatnonzero(alarm[start:stop] & ~clean_alarm[start:stop])
    return int(hit[0]) if hit.size else None


def evaluate(coords: dict, anoms: dict, index: pd.DatetimeIndex) -> dict:
    rng = np.random.default_rng(SEED)
    train_mask = index < TRAIN_END
    test_lo, test_hi = int(np.searchsorted(index, TRAIN_END)), int(np.searchsorted(index, TEST_END))
    out = {"radius_km": RADIUS_KM, "min_peers": MIN_PEERS, "window_hours": WINDOW_H, "stations": {}, "trials": []}
    for sid in coords:
        nb = peers.neighbours(coords, sid, RADIUS_KM)
        out["stations"][sid] = {"n_peers": len(nb), "peers": nb[:8]}
        for ch in CHANNELS:
            series = {s: a[ch] for s, a in anoms.items()}
            diff = peers.peer_difference(series, sid, nb, MIN_PEERS)
            for mode, x in (("peer", diff), ("own", series[sid])):
                lim = peers.fit_limit(x[train_mask], WINDOW_H, QUANTILE, MARGIN)
                rec = out["stations"][sid].setdefault(ch, {})
                rec[mode] = {"threshold": None if lim is None else round(lim.threshold, 4)}
                if lim is None:
                    continue
                clean_alarm = peers.offset_alarm(x, lim, WINDOW_H).fillna(False).to_numpy(dtype=bool)
                days = clean_alarm[test_lo:test_hi].reshape(-1)[: (test_hi - test_lo) // 24 * 24].reshape(-1, 24).any(axis=1)
                rec[mode]["clean_alarm_day_fraction"] = round(float(days.mean()), 4)
                own_valid = series[sid].notna().to_numpy()
                for kind in ("offset", "drift"):
                    sizes = SIZES[ch] if kind == "offset" else (DRIFT_TOTAL[ch],)
                    for size in sizes:
                        for _ in range(TRIALS_PER_STATION):
                            start = int(rng.integers(test_lo, test_hi - FAULT_DAYS * 24 - 1))
                            n = FAULT_DAYS * 24
                            shape = np.ones(n) if kind == "offset" else np.linspace(0.0, 1.0, n)
                            fault = np.zeros(len(index))
                            fault[start:start + n] = size * shape
                            fault[start + n:] = size * shape[-1] if kind == "offset" else 0.0
                            if kind == "offset":
                                fault[start + n:] = 0.0                                   # the fault ends after FAULT_DAYS
                            if own_valid[start:start + n].mean() < 0.5:
                                continue
                            injected_own = series[sid] + pd.Series(fault, index=index)
                            xi = (injected_own - (series[sid] - diff)) if mode == "peer" else injected_own
                            alarm = peers.offset_alarm(xi, lim, WINDOW_H).fillna(False).to_numpy(dtype=bool)
                            horizon = DETECT_DAYS * 24 if kind == "offset" else n
                            hit = first_alarm(alarm, start, min(start + horizon, len(index)), clean_alarm)
                            out["trials"].append({"station": sid, "channel": ch, "mode": mode, "kind": kind, "size": size,
                                                  "detected": hit is not None, "days": None if hit is None else round(hit / 24.0, 2)})
    return out


def summarise(res: dict) -> dict:
    """Pool over stations: detection rate and median days to detect per (channel, kind, size, mode), and false alarms per station-year."""
    rows: dict = {}
    for t in res["trials"]:
        k = (t["channel"], t["kind"], t["size"], t["mode"])
        r = rows.setdefault(k, {"n": 0, "hit": 0, "days": []})
        r["n"] += 1
        r["hit"] += t["detected"]
        if t["days"] is not None:
            r["days"].append(t["days"])
    table = [{"channel": k[0], "kind": k[1], "size": k[2], "mode": k[3], "trials": v["n"], "detected": v["hit"],
              "rate": v["hit"] / v["n"], "median_days": float(np.median(v["days"])) if v["days"] else None}
             for k, v in sorted(rows.items())]
    fa: dict = {}
    for sid, st in res["stations"].items():
        for ch in CHANNELS:
            for mode in ("peer", "own"):
                f = st.get(ch, {}).get(mode, {}).get("clean_alarm_day_fraction")
                if f is not None:
                    fa.setdefault((ch, mode), []).append(f)
    false = [{"channel": ch, "mode": mode, "mean_alarm_day_fraction": float(np.mean(v)), "stations": len(v)}
             for (ch, mode), v in sorted(fa.items())]
    return {"detection": table, "false_alarms": false}


def format_text(res: dict, summ: dict) -> str:
    L = [f"Peer layer study, limit = q{QUANTILE:g} of the training windows x {MARGIN:g}: {len(res['stations'])} stations, radius {RADIUS_KM:g} km, at least {MIN_PEERS} peers, {WINDOW_H // 24}-day mean, "
         f"fault length {FAULT_DAYS} d, offsets must be caught within {DETECT_DAYS} d", ""]
    L.append("Fault detection (paired; peers = with neighbours, own = the same statistic on the station's own anomaly, no neighbours)")
    L.append(f"{'channel':15s} {'kind':7s} {'size':>6s}  {'peers':>18s}   {'own only':>18s}")
    keyed = {(d["channel"], d["kind"], d["size"], d["mode"]): d for d in summ["detection"]}
    for ch, kind, size in sorted({(d["channel"], d["kind"], d["size"]) for d in summ["detection"]}):
        cells = []
        for mode in ("peer", "own"):
            d = keyed.get((ch, kind, size, mode))
            cells.append("n/a" if d is None else f"{100 * d['rate']:5.1f}% ({d['detected']}/{d['trials']}) {('%.1f d' % d['median_days']) if d['median_days'] is not None else '-':>6s}")
        L.append(f"{ch:15s} {kind:7s} {size:6g}  {cells[0]:>18s}   {cells[1]:>18s}")
    L += ["", "False alarms: share of test days (2020-2023) with an alarm on clean data, mean over stations"]
    for f in summ["false_alarms"]:
        L.append(f"  {f['channel']:15s} {f['mode']:5s} {100 * f['mean_alarm_day_fraction']:.2f}%  ({f['stations']} stations)")
    return "\n".join(L)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Peer-layer study (offsets and drift seen with and without neighbours).")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--cluster", choices=("nsw", "vic", "india"), default="nsw")
    ap.add_argument("--radius-km", type=float, default=250.0)
    ap.add_argument("--window-days", type=int, default=7)
    ap.add_argument("--quantile", type=float, default=0.999)
    ap.add_argument("--margin", type=float, default=1.2)
    args = ap.parse_args(argv)
    global DATA, CATALOG, WINDOW_H, QUANTILE, MARGIN, RADIUS_KM
    RADIUS_KM = args.radius_km
    DATA, CATALOG = REPO / "data" / "peers" / args.cluster, REPO / "data_tools" / f"stations_peers_{args.cluster}.yaml"
    WINDOW_H, QUANTILE, MARGIN = args.window_days * 24, args.quantile, args.margin
    settings = load_settings()
    coords, anoms, index = build(settings)
    res = evaluate(coords, anoms, index)
    summ = summarise(res)
    print(format_text(res, summ))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({**res, "summary": summ}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
