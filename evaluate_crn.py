"""Real labelled sensor faults and real 5-minute records: the US Climate Reference Network (Amendment 7 in config/protocol.md).

    python evaluate_crn.py --dev --workers 4 --out results/crn_dev.json          # the eight development stations (code and label thresholds were settled here)
    python evaluate_crn.py --sealed --workers 4 --out results/crn_run1.json      # ONCE, behind a guard: the sealed stations

Every CRN station has three independent, aspirated platinum thermometers and a humidity probe, and reports every 5 minutes. There is NO barometer in the stream, so the pipeline runs as a two-channel
station (`channels.absent: [pressure_hpa]`). Each thermometer is judged as its own sensor stream: its readings plus the station's humidity.

Where the real faults come from. A fault on one thermometer is a disagreement the other two do not share, and CRN's own quality control marks erroneous values. Neither uses AtmosGuard, and the pipeline sees only
one sensor's stream, so the labels are independent of it:
  redundancy episode of sensor k   |T_k - mean(T_a, T_b)| >= 1.0 C while |T_a - T_b| <= 0.3 C, runs merged across gaps of up to 30 min, at least 15 min long
  quality-control episode          CRN's quality code 3 (erroneous) on sensor k, same merging, at least 30 min
  clear tier                       a quality-control episode, or a redundancy episode with |deviation| >= 2.0 C that lasts at least 30 min.  marginal tier: every other redundancy episode.
Reported per tier, per system, with the false-alarm rate on clean stretches next to it.

The pipeline is fitted on 2016-2019 (rows CRN itself marked erroneous removed) and judged on 2020-2024: labelled episodes with two days of lead-in, clean 45-day stretches (no label on any of the station's three
sensors within a day) with the usual injected faults added (5-minute detection), and the healthy sensors while a neighbour fails.
"""
from __future__ import annotations

import argparse
import copy
import glob
import json
import math
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

import evaluate as ev
import evaluate_real as er
from atmos.config import CONFIG_DIR, load_settings
from atmos.limits import fit_limits
from atmos.mlmodel import IsolationModel, MahalanobisModel
from atmos.normality import NormalityTable
from atmos.schema import Reading

REPO = CONFIG_DIR.parent
CRN_DIR = REPO / "data" / "crn"
MANIFEST = CRN_DIR / "manifest.json"
TRAIN_END = pd.Timestamp("2020-01-01")
JUDGE_END = pd.Timestamp("2025-01-01")
CADENCE = 5.0
DEV_STATIONS = ("03047", "03048", "03054", "03055", "03060", "03062", "03063", "03067")   # WBAN numbers; everything in the labelling rules was settled on these
REDUNDANCY_C = 1.0
AGREE_C = 0.3
CLEAR_C = 2.0
MERGE_SAMPLES = 6                   # 30 min
MIN_REDUNDANCY_SAMPLES = 3          # 15 min
MIN_CLEAR_SAMPLES = 6               # 30 min
LEAD_IN_DAYS = 2
GRACE_MIN = 60
CLEAN_CHUNK_DAYS = 45
CLEAN_CHUNKS = 8
MAX_EPISODES_PER_STREAM = 40        # the longest-deviating episodes are not preferred: the first 40 in time order, so a dead sensor cannot drown the rest
SENSORS = (1, 2, 3)


# ====================================================================================================
# data and labels
# ====================================================================================================
def load_station(wban: str, directory: Path = CRN_DIR) -> pd.DataFrame:
    files = sorted(glob.glob(str(directory / f"999999{wban}_*.csv.gz")))
    if not files:
        raise FileNotFoundError(f"no CRN files for {wban} in {directory}")
    df = pd.concat([pd.read_csv(f, parse_dates=["timestamp"]) for f in files], ignore_index=True)
    return df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)


@dataclass
class Episode:
    sensor: int
    start: int                      # index of the first labelled sample
    end: int                        # index of the last
    kind: str                       # "redundancy", "qc" or "both"
    tier: str                       # "clear" or "marginal"
    max_dev: float                  # largest |T_k - mean(others)| inside, C (nan when the others are missing)


def _runs(mask: np.ndarray, merge: int, min_len: int) -> list[tuple[int, int]]:
    idx = np.flatnonzero(mask)
    if idx.size == 0:
        return []
    runs, s, p = [], int(idx[0]), int(idx[0])
    for i in idx[1:]:
        if i - p - 1 > merge:                 # `merge` samples of nothing in between still count as one run
            runs.append((s, p))
            s = int(i)
        p = int(i)
    runs.append((s, p))
    return [(a, b) for a, b in runs if b - a + 1 >= min_len]


def label_episodes(df: pd.DataFrame) -> dict[int, list[Episode]]:
    """Labelled episodes per sensor (see the module docstring). Sample indices refer to `df`."""
    T = {k: df[f"t{k}"].to_numpy(float) for k in SENSORS}
    Q = {k: df[f"q{k}"].to_numpy(float) for k in SENSORS}
    out: dict[int, list[Episode]] = {}
    for k in SENSORS:
        a, b = (j for j in SENSORS if j != k)
        with np.errstate(invalid="ignore"):
            dev = T[k] - (T[a] + T[b]) / 2.0
            red = (np.abs(dev) >= REDUNDANCY_C) & (np.abs(T[a] - T[b]) <= AGREE_C)
        qc = np.nan_to_num(Q[k], nan=0.0) == 3
        eps: list[Episode] = []
        red_runs = _runs(red, MERGE_SAMPLES, MIN_REDUNDANCY_SAMPLES)
        qc_runs = _runs(qc, MERGE_SAMPLES, MIN_CLEAR_SAMPLES)
        used = set()
        for s, e in red_runs:
            overlap = [i for i, (qs, qe) in enumerate(qc_runs) if qs <= e and qe >= s]
            used.update(overlap)
            md = float(np.nanmax(np.abs(dev[s:e + 1]))) if np.isfinite(dev[s:e + 1]).any() else float("nan")
            s2, e2 = min([s] + [qc_runs[i][0] for i in overlap]), max([e] + [qc_runs[i][1] for i in overlap])
            clear = bool(overlap) or (md >= CLEAR_C and e - s + 1 >= MIN_CLEAR_SAMPLES)
            eps.append(Episode(k, s2, e2, "both" if overlap else "redundancy", "clear" if clear else "marginal", md))
        for i, (s, e) in enumerate(qc_runs):
            if i not in used:
                md = float(np.nanmax(np.abs(dev[s:e + 1]))) if np.isfinite(dev[s:e + 1]).any() else float("nan")
                eps.append(Episode(k, s, e, "qc", "clear", md))
        eps.sort(key=lambda x: x.start)
        merged: list[Episode] = []
        for ep in eps:                                               # episodes of one kind that touch are one episode
            if merged and ep.start - merged[-1].end - 1 <= MERGE_SAMPLES:
                m = merged[-1]
                merged[-1] = Episode(k, m.start, max(m.end, ep.end), "both" if m.kind != ep.kind else m.kind,
                                     "clear" if "clear" in (m.tier, ep.tier) else "marginal", float(np.nanmax([m.max_dev, ep.max_dev])))
            else:
                merged.append(ep)
        out[k] = merged
    return out


def label_mask(df: pd.DataFrame, episodes: dict[int, list[Episode]], pad: int = 288) -> np.ndarray:
    """True where ANY of the three sensors has a labelled episode (padded by `pad` samples = one day each side)."""
    m = np.zeros(len(df), dtype=bool)
    for eps in episodes.values():
        for ep in eps:
            m[max(0, ep.start - pad): ep.end + pad + 1] = True
    m |= (df["rh_q"].to_numpy(float) == 3)
    return m


def stream_frame(df: pd.DataFrame, k: int, wban: str) -> pd.DataFrame:
    """One thermometer's stream in the layout evaluate_real reads: its temperature, the station's humidity, no pressure."""
    return pd.DataFrame({"station_id": f"{wban}-S{k}", "timestamp": df["timestamp"], "temperature_c": df[f"t{k}"].round(2),
                         "pressure_hpa": np.nan, "humidity_pct": df["rh"].round(1),
                         "noaa_flag": ((df[f"q{k}"].fillna(0) == 3) | (df["rh_q"].fillna(0) == 3)).astype(int)})


def to_readings(frame: pd.DataFrame) -> list[Reading]:
    sid = frame["station_id"].iloc[0]
    return [Reading(station_id=sid, timestamp=t.to_pydatetime(), temperature_c=a, pressure_hpa=None, humidity_pct=c)
            for t, a, c in zip(frame["timestamp"], frame["temperature_c"], frame["humidity_pct"])]


# ====================================================================================================
# settings
# ====================================================================================================
def crn_settings(settings: dict) -> dict:
    s = er.real_settings(settings)
    s["channels"] = {"absent": ["pressure_hpa"]}
    return s


def crn_configs(settings: dict, table, model, limits, train, sid: str, mahal) -> list[tuple[str, str, er.Predictor]]:
    """`full` (the pipeline as shipped) and the five baselines, all two-channel."""
    s = er.pin_registered(copy.deepcopy(settings))
    shipped = copy.deepcopy(s)
    shipped["health"]["frozen"]["ceiling_aware"] = True
    shipped["health"]["step"]["expected_aware"] = True
    cfgs = [("full", "full", er.pipeline_predictor(shipped, table, model, limits, sid, CADENCE, mahal)),
            ("baseline_range", "baseline", er.baseline_range(s)),
            ("baseline_rules", "baseline", er.baseline_rules(s, CADENCE)),
            ("baseline_climatology", "baseline", er.baseline_climatology(table, s)),
            ("baseline_isolation_forest", "baseline", er.baseline_iforest(model)),
            ("baseline_mahalanobis", "baseline", er.baseline_mahalanobis(train, absent=tuple(s["channels"]["absent"])))]
    return [(n, k, er.memoize(p)) for n, k, p in cfgs]


# ====================================================================================================
# one stream
# ====================================================================================================
def clean_chunks(df: pd.DataFrame, mask: np.ndarray, frame: pd.DataFrame, seed: int) -> list[list[Reading]]:
    """Up to CLEAN_CHUNKS non-overlapping 45-day stretches of 2020-2024 with no label on any sensor and almost no missing values."""
    n = int(CLEAN_CHUNK_DAYS * 1440 / CADENCE)
    ts = df["timestamp"]
    lo = int(np.searchsorted(ts.values, np.datetime64(TRAIN_END)))
    hi = int(np.searchsorted(ts.values, np.datetime64(JUDGE_END)))
    rng = np.random.default_rng(seed)
    taken: list[tuple[int, int]] = []
    chunks = []
    bad = frame[["temperature_c", "humidity_pct"]].isna().any(axis=1).to_numpy()
    for _ in range(400):
        if len(chunks) >= CLEAN_CHUNKS or hi - lo <= n:
            break
        s = int(rng.integers(lo, hi - n))
        e = s + n
        if any(s < b and e > a for a, b in taken) or mask[s:e].any() or bad[s:e].mean() > 0.02:
            continue
        if (ts.iloc[e - 1] - ts.iloc[s]).total_seconds() / 60.0 > 1.05 * (n - 1) * CADENCE:      # a hole in the record
            continue
        taken.append((s, e))
        chunks.append(to_readings(frame.iloc[s:e].reset_index(drop=True)))
    return chunks


def evaluate_stream(args: tuple) -> dict:
    wban, k, settings, quick = args
    t0 = time.time()
    s = crn_settings(settings)
    df = load_station(wban)
    eps_all = label_episodes(df)
    mask = label_mask(df, eps_all)
    frame = stream_frame(df, k, wban)
    sid = frame["station_id"].iloc[0]
    tr = frame[(frame["timestamp"] < TRAIN_END) & (frame["noaa_flag"] == 0)].reset_index(drop=True)
    train = to_readings(tr)
    table, model = NormalityTable.fit(train, s), IsolationModel.fit(train, s)
    limits = fit_limits(train, s, CADENCE)
    mahal = MahalanobisModel.fit(train, s, table)
    fit_seconds = time.time() - t0
    cfgs = crn_configs(s, table, model, limits, train, sid, mahal)

    results: dict[str, dict] = {n: {"kind": kind} for n, kind, _ in cfgs}
    chunks = clean_chunks(df, mask, frame, seed=s["seed"] + 7919 * k + int(wban))
    rounds = 1
    faulted = er.make_faulted(chunks, s, rounds, min_len=int(30 * 1440 / CADENCE)) if not quick else []
    # ---- real episodes of this sensor (judge period), and clear episodes of the neighbours (this sensor healthy)
    own = [ep for ep in eps_all[k] if TRAIN_END <= df["timestamp"].iloc[ep.start] < JUDGE_END][:MAX_EPISODES_PER_STREAM]
    neighbours = [ep for j in SENSORS if j != k for ep in eps_all[j] if ep.tier == "clear" and TRAIN_END <= df["timestamp"].iloc[ep.start] < JUDGE_END][:MAX_EPISODES_PER_STREAM]
    own_mask = np.zeros(len(df), dtype=bool)
    for ep in eps_all[k]:
        own_mask[max(0, ep.start - 12): ep.end + 13] = True
    neighbours = [ep for ep in neighbours if not own_mask[ep.start: ep.end + 1].any()]
    grace = int(math.ceil(GRACE_MIN / CADENCE))
    lead = int(LEAD_IN_DAYS * 1440 / CADENCE)

    def run_episode(ep: Episode, predict) -> dict:
        a = max(0, ep.start - lead)
        b = min(len(df), ep.end + grace + 1)
        seg = frame.iloc[a:b]
        readings = to_readings(seg.reset_index(drop=True))
        preds = predict(readings)
        off = ep.start - a
        n_in = ep.end - ep.start + 1
        inside = preds[off: off + n_in]
        win = preds[off: off + n_in + grace]
        first = next((i for i, p in enumerate(win) if er.is_alarm(p)), None)
        return {"tier": ep.tier, "kind": ep.kind, "samples": n_in, "alarm_samples": sum(er.is_alarm(p) for p in inside),
                "fault_samples": sum(p.verdict == "FAULT" for p in inside), "detected": first is not None,
                "detected_fault": any(p.verdict == "FAULT" for p in win), "delay_min": None if first is None else first * CADENCE,
                "minutes": n_in * CADENCE, "max_dev": None if not np.isfinite(ep.max_dev) else round(float(ep.max_dev), 2)}

    for name, kind, predict in cfgs:
        clean = er.count_clean(chunks, predict)
        det = er.count_detection(faulted, predict, s, CADENCE) if faulted else {t: {"detected": 0, "detected_new": 0, "injected": 0, "delays_min": [], "delays_new_min": []} for t in er.REAL_TYPES}
        real = [run_episode(ep, predict) for ep in own]
        healthy = [run_episode(ep, predict) for ep in neighbours]
        results[name].update({"clean": clean, "detection": det, "real": real,
                              "healthy": [{"samples": h["samples"], "alarm_samples": h["alarm_samples"], "fault_samples": h["fault_samples"], "tier": h["tier"]} for h in healthy]})
        predict.clear()
    return {"station": wban, "sensor": k, "stream": sid, "train_rows": len(train), "fit_seconds": round(fit_seconds, 1),
            "clean_chunks": len(chunks), "episodes": {"own": len(own), "own_clear": sum(e.tier == "clear" for e in own), "neighbours": len(neighbours)},
            "episodes_total_judged": {str(j): sum(TRAIN_END <= df["timestamp"].iloc[e.start] < JUDGE_END for e in eps_all[j]) for j in SENSORS},
            "limits": {ch: vars(c) for ch, c in limits.channels.items()}, "configs": results, "seconds": round(time.time() - t0, 1)}


# ====================================================================================================
# orchestration, aggregation, report
# ====================================================================================================
def sealed_and_dev(manifest_path: Path = MANIFEST) -> tuple[list[str], list[str]]:
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    return list(m["dev_stations"]), list(m["sealed_stations"])


def run(stations: list[str], quick: bool, workers: int, sensors: tuple = SENSORS) -> dict:
    settings = load_settings()
    jobs = [(w, k, settings, quick) for w in stations for k in sensors]
    if workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(evaluate_stream, jobs))
    else:
        rows = [evaluate_stream(j) for j in jobs]
    return {"quick": quick, "generated": datetime.utcnow().isoformat() + "Z", "stations": stations, "streams": rows}


def _pct(a: float, n: float, digits: int = 1) -> str:
    return "n/a" if not n else f"{100.0 * a / n:.{digits}f}%"


def aggregate(result: dict) -> dict:
    """Pool the sensor streams: per system, clean false alarms, injected-fault detection, and real-episode recall by tier."""
    rows = result["streams"]
    systems = list(rows[0]["configs"]) if rows else []
    out = {}
    for n in systems:
        clean = {"n": 0, "alarm": 0, "fault": 0, "weather": 0}
        det = {t: {"detected_new": 0, "injected": 0, "delays_new_min": []} for t in er.REAL_TYPES}
        tiers = {t: {"episodes": 0, "detected": 0, "detected_fault": 0, "samples": 0, "alarm_samples": 0, "minutes": 0.0, "delays": []} for t in ("clear", "marginal")}
        kinds = {kd: {"episodes": 0, "detected": 0} for kd in ("redundancy", "qc", "both")}
        healthy = {"samples": 0, "alarm_samples": 0, "fault_samples": 0, "episodes": 0}
        for r in rows:
            c = r["configs"][n]
            for key in clean:
                clean[key] += c["clean"].get(key, 0)
            for t, d in c["detection"].items():
                det[t]["detected_new"] += d.get("detected_new", 0)
                det[t]["injected"] += d["injected"]
                det[t]["delays_new_min"] += d.get("delays_new_min", [])
            for ep in c["real"]:
                a = tiers[ep["tier"]]
                a["episodes"] += 1
                a["detected"] += ep["detected"]
                a["detected_fault"] += ep["detected_fault"]
                a["samples"] += ep["samples"]
                a["alarm_samples"] += ep["alarm_samples"]
                a["minutes"] += ep["minutes"]
                if ep["delay_min"] is not None:
                    a["delays"].append(ep["delay_min"])
                kinds[ep["kind"]]["episodes"] += 1
                kinds[ep["kind"]]["detected"] += ep["detected"]
            for h in c["healthy"]:
                healthy["episodes"] += 1
                healthy["samples"] += h["samples"]
                healthy["alarm_samples"] += h["alarm_samples"]
                healthy["fault_samples"] += h["fault_samples"]
        out[n] = {"clean": clean, "detection": det, "tiers": tiers, "kinds": kinds, "healthy": healthy}
    return out


def format_result(result: dict, title: str) -> str:
    agg = aggregate(result)
    rows = result["streams"]
    L = [f"### {title}", f"stations: {', '.join(result['stations'])}   sensor streams: {len(rows)}   cadence 5 min, two channels (temperature, humidity), no barometer", ""]
    L.append("1) Real sensor faults (labelled by the other two thermometers and by CRN's own quality code; nothing injected)")
    L.append("   episode recall = at least one alarm (FAULT or SUSPECT) from the first labelled sample to 60 min after the last; sample recall = share of the labelled samples that were alarms")
    L.append(f"   {'system':<28}{'clear episodes':>16}{'clear samples':>15}{'FAULT named':>13}{'marginal episodes':>19}{'marginal samples':>18}")
    for n, a in agg.items():
        c, m = a["tiers"]["clear"], a["tiers"]["marginal"]
        L.append(f"   {n:<28}{_pct(c['detected'], c['episodes']):>16}{_pct(c['alarm_samples'], c['samples']):>15}{_pct(c['detected_fault'], c['episodes']):>13}"
                 f"{_pct(m['detected'], m['episodes']):>19}{_pct(m['alarm_samples'], m['samples']):>18}")
    first = next(iter(agg.values()))
    L.append(f"   (episodes: clear {first['tiers']['clear']['episodes']}, marginal {first['tiers']['marginal']['episodes']}; "
             f"clear minutes {first['tiers']['clear']['minutes']:.0f}; by label: " + ", ".join(f"{k} {v['episodes']}" for k, v in first["kinds"].items()) + ")")
    full = agg["full"]["tiers"]
    for t in ("clear", "marginal"):
        d = full[t]["delays"]
        if d:
            L.append(f"   full: median delay to the first alarm, {t} episodes: {float(np.median(d)):.0f} min (quartiles {float(np.percentile(d, 25)):.0f}-{float(np.percentile(d, 75)):.0f})")
    L += ["", "2) False alarms on clean 45-day stretches (no label on any of the station's sensors within a day)"]
    L.append(f"   {'system':<28}{'any alarm':>12}{'FAULT only':>12}{'samples':>12}{'healthy sensor, neighbour failing':>36}")
    for n, a in agg.items():
        c, h = a["clean"], a["healthy"]
        L.append(f"   {n:<28}{_pct(c['alarm'], c['n']):>12}{_pct(c['fault'], c['n']):>12}{c['n']:>12}{_pct(h['alarm_samples'], h['samples']):>36}")
    L += ["", "3) Detection of injected faults at 5 minutes (paired: the same sample was not an alarm on the un-faulted series)"]
    L.append(f"   {'system':<28}" + "".join(f"{t:>12}" for t in er.REAL_TYPES))
    for n, a in agg.items():
        L.append(f"   {n:<28}" + "".join(f"{_pct(a['detection'][t]['detected_new'], a['detection'][t]['injected']):>12}" for t in er.REAL_TYPES))
    L.append(f"   {'(faults injected)':<28}" + "".join(f"{first['detection'][t]['injected']:>12}" for t in er.REAL_TYPES))
    lat = [r["seconds"] for r in rows]
    L += ["", f"4) Streams: {len(rows)} sensor streams, {sum(r['clean_chunks'] for r in rows)} clean stretches, {sum(r['episodes']['own'] for r in rows)} labelled episodes judged "
              f"({sum(sum(r['episodes_total_judged'].values()) for r in rows) // max(1, len(set(r['station'] for r in rows)) and (len(rows) // len(set(r['station'] for r in rows))))} "
              f"labelled in 2020-2024 over all sensors, each sensor capped at {MAX_EPISODES_PER_STREAM}); median {float(np.median(lat)):.0f} s per stream"]
    return "\n".join(L)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Real labelled faults and 5-minute records: the US Climate Reference Network.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dev", action="store_true", help="the eight development stations")
    g.add_argument("--sealed", action="store_true", help="the sealed stations, ONCE, behind the guard (Amendment 7 in config/protocol.md)")
    ap.add_argument("--stations", nargs="*", help="only these WBAN numbers")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--quick", action="store_true", help="skip the injected faults")
    ap.add_argument("--sensors", type=int, nargs="*", default=list(SENSORS))
    ap.add_argument("--out", type=Path)
    ap.add_argument("--force-rerun", action="store_true", help="reproduce a sealed run that was already made (the original lock file stays in git history)")
    a = ap.parse_args(argv)
    settings = load_settings()
    if a.sealed:
        lock = CRN_DIR / ev.CRN_LOCK_NAME
        if a.force_rerun and lock.exists():
            print(f"Re-running the sealed CRN evaluation to reproduce it. The first run is recorded in {lock}.")
        else:
            try:
                ev.guard_crn(settings, REPO, REPO / "data")
            except ev.HoldoutError as e:
                print(f"Cannot run the sealed CRN evaluation: {e}")
                return 2
        stations = sealed_and_dev()[1]
    else:
        stations = list(DEV_STATIONS)
    if a.stations:
        stations = [s for s in stations if s in a.stations]
    result = run(stations, a.quick, a.workers, tuple(a.sensors))
    text = format_result(result, "CRN sealed stations" if a.sealed else "CRN development stations")
    print(text)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(result, indent=1, default=float), encoding="utf-8")
        a.out.with_suffix(".txt").write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
