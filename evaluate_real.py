"""Evaluation on REAL station data (NOAA ISD airport records), several stations, DEV and HOLDOUT. Protocol: config/protocol.md.

  python evaluate_real.py --dev                 # DEV only: the stations and years we are allowed to tune on
  python evaluate_real.py --dev --quick         # same, one year and one fault round (fast, for tuning loops)
  python evaluate_real.py --holdout             # ONCE, at the end. Guarded (protocol committed, lock file).

Per station the pipeline is fitted on that station's own first four years (2016-2019, extreme-weather windows and
NOAA-flagged values removed) and judged on data it never saw:
  DEV               DEV stations,    2020-2021          (tuning allowed)
  HOLDOUT (time)    DEV stations,    2022-2024          (same stations, later years)
  HOLDOUT (space)   sealed stations, 2020-2024          (stations never used for any tuning)
Reported for every configuration (full pipeline, ablations, baselines), never merged into one number:
  1  detection of injected faults, per fault type, plus how fast
  2  false alarms on clean real data (no faults injected)
  3  what happens on real extreme weather (no faults injected): FAULT rate, SUSPECT rate, WEATHER rate
  4  agreement with NOAA's own quality flags on the raw record (weak labels, not ground truth)
  5  slow drift, judged by the health score (Theil-Sen), not by alarms
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional, Sequence

import numpy as np
import pandas as pd

import evaluate as ev
import replay as replay_io
from atmos import health, physics
from atmos.config import CONFIG_DIR, load_settings
from atmos.fusion import Pipeline
from atmos.injector import ALL_FAULT_TYPES, InjectionResult, inject, make_plan
from atmos.limits import StationLimits, fit_limits
from atmos.mlmodel import IsolationModel, build_features
from atmos.normality import NormalityTable
from atmos.schema import CHANNELS, Reading

REPO = CONFIG_DIR.parent
REAL_DEV_DIR = REPO / "data" / "real" / "dev"
REAL_HOLDOUT_DIR = REPO / "data" / "holdout" / "real"
EVENTS_JSON = REPO / "data" / "real" / "events.json"
RESULTS_DIR = REPO / "results"
TRAIN_END = pd.Timestamp("2020-01-01")          # training = everything before this
DEV_END = pd.Timestamp("2022-01-01")
LEAD_IN_DAYS = 2                                 # extra history fed before an event window, not counted
ALARM = ("FAULT", "SUSPECT")


# ====================================================================================================
# data
# ====================================================================================================
def deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in extra.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def real_settings(settings: dict) -> dict:
    s = deep_merge(settings, settings["evaluate"]["real"]["overrides"])
    s["healthscore"]["recompute_every_minutes"] = 10 ** 9      # verdict runs do not need the (slow) health score
    return s


def read_frame(path: Path, settings: dict, allow_holdout: bool) -> pd.DataFrame:
    """A station CSV as a frame. The holdout folder is refused unless the caller passed the holdout guard."""
    replay_io.check_path(path, settings, allow_holdout=allow_holdout)
    df = pd.read_csv(path, parse_dates=["timestamp"])
    return df.sort_values("timestamp").reset_index(drop=True)


def to_readings(df: pd.DataFrame) -> list[Reading]:
    sid = df["station_id"].iloc[0] if len(df) else "?"
    return [Reading(station_id=sid, timestamp=t.to_pydatetime(), temperature_c=a, pressure_hpa=b, humidity_pct=c)
            for t, a, b, c in zip(df["timestamp"], df["temperature_c"], df["pressure_hpa"], df["humidity_pct"])]


def cadence_of(df: pd.DataFrame) -> float:
    d = df["timestamp"].diff().dt.total_seconds().dropna() / 60.0
    return float(d[d > 0].median())


def windows_of(events: list[dict]) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    spans = sorted((pd.Timestamp(e["start"]), pd.Timestamp(e["end"])) for e in events)
    out: list[list[pd.Timestamp]] = []
    for s, e in spans:
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def cut_chunks(df: pd.DataFrame, windows: Sequence[tuple[pd.Timestamp, pd.Timestamp]], min_rows: int) -> list[pd.DataFrame]:
    """`df` with the extreme-weather windows and NOAA-flagged rows removed, as separate contiguous chunks."""
    keep = df["noaa_flag"] == 0
    chunk_id = pd.Series(0, index=df.index)
    for i, (s, e) in enumerate(windows, start=1):
        inside = (df["timestamp"] >= s) & (df["timestamp"] <= e)
        keep &= ~inside
        chunk_id[df["timestamp"] > e] = i
    out = []
    for _, g in df[keep].groupby(chunk_id[keep]):
        if len(g) >= min_rows:
            out.append(g.reset_index(drop=True))
    return out


@dataclass
class EventSeries:
    kind: str
    center: str
    readings: list[Reading]          # lead-in + window
    core_start: int                  # index of the first sample that is counted
    core_end: int                    # index one past the last sample that is counted


def cut_events(df: pd.DataFrame, events: list[dict]) -> tuple[list[EventSeries], int]:
    """One series per event window (with lead-in). NOAA-flagged rows are cut out. Returns (series, rows cut)."""
    out, cut = [], 0
    for e in events:
        s, t = pd.Timestamp(e["start"]), pd.Timestamp(e["end"])
        seg = df[(df["timestamp"] >= s - pd.Timedelta(days=LEAD_IN_DAYS)) & (df["timestamp"] <= t)]
        cut += int((seg["noaa_flag"] > 0).sum())
        seg = seg[seg["noaa_flag"] == 0].reset_index(drop=True)
        core = seg["timestamp"] >= s
        if core.sum() < 3:
            continue
        first = int(np.argmax(core.values))
        out.append(EventSeries(e["kind"], e["center"], to_readings(seg), first, len(seg)))
    return out, cut


# ====================================================================================================
# predictors: one series in, one Pred per sample out
# ====================================================================================================
@dataclass
class Pred:
    verdict: str                                   # VALID / WEATHER / SUSPECT / FAULT
    kinds: frozenset = frozenset()                 # names of the checks that fired (without the channel)


Predictor = Callable[[list[Reading]], list[Pred]]


def pipeline_predictor(settings: dict, table: NormalityTable, model: IsolationModel, limits: StationLimits,
                       sid: str, cadence: float) -> Predictor:
    def predict(readings: list[Reading]) -> list[Pred]:
        pipe = Pipeline(settings, {sid: {"cadence_minutes": cadence}}, {sid: table},
                        {sid: ev._PrecomputedModel(model, readings)}, {sid: limits})
        out = []
        for r in readings:
            v = pipe.process(r)
            out.append(Pred(v.verdict.value, frozenset(c.check.split(":")[0] for c in v.checks if c.flagged)))
        return out
    return predict


def baseline_range(settings: dict) -> Predictor:
    def predict(readings: list[Reading]) -> list[Pred]:
        return [Pred("FAULT" if any(c.flagged for c in physics.check_ranges(r, settings)) else "VALID")
                for r in readings]
    return predict


def baseline_rules(settings: dict, cadence: float) -> Predictor:
    """Textbook operational QC with fixed limits: range + step + persistence (the guide's Appendix A fallbacks)."""
    s = copy.deepcopy(settings)
    s["health"]["frozen"]["window_minutes"] = {ch: 360 for ch in CHANNELS}      # 6 h identical
    s["health"]["step"]["rate_per_min"] = {"temperature_c": 4 / 60, "pressure_hpa": 3 / 60, "humidity_pct": 40 / 60}
    s["health"]["step"]["cap"] = {"temperature_c": 4.0, "pressure_hpa": 3.0, "humidity_pct": 40.0}
    s["limits"] = {**s["limits"]}
    keep = Pipeline(s)._history_length(cadence)

    def predict(readings: list[Reading]) -> list[Pred]:
        out = []
        for i, r in enumerate(readings):
            hist = readings[max(0, i + 1 - keep): i + 1]
            hit = any(c.flagged for c in physics.check_ranges(r, s))
            hit = hit or any(health.check_frozen(hist, ch, s, cadence).flagged or
                             health.check_step(hist, ch, s, cadence).flagged for ch in CHANNELS)
            out.append(Pred("FAULT" if hit else "VALID"))
        return out
    return predict


def baseline_climatology(table: NormalityTable, settings: dict) -> Predictor:
    z_flag = settings["normality"]["z_flag"]

    def predict(readings: list[Reading]) -> list[Pred]:
        out = []
        for r in readings:
            zs = [table.z_score(r, ch) for ch in CHANNELS]
            out.append(Pred("SUSPECT" if any(z is not None and abs(z) > z_flag for z in zs) else "VALID"))
        return out
    return predict


def baseline_iforest(model: IsolationModel) -> Predictor:
    def predict(readings: list[Reading]) -> list[Pred]:
        pre = ev._PrecomputedModel(model, readings)
        out = [Pred("VALID")]
        for i in range(1, len(readings)):
            s = pre.score(readings[i - 1: i + 1])[1]
            out.append(Pred("SUSPECT" if (not np.isnan(s) and s < model.threshold) else "VALID"))
        return out
    return predict


def baseline_mahalanobis(train: list[Reading], quantile: float = 0.995) -> Predictor:
    """The other common approach in this problem's public repos: Mahalanobis distance of (values, changes)."""
    X, ok = build_features(train)
    X = X[ok][:, :6]
    mu = X.mean(axis=0)
    cov = np.cov(X, rowvar=False) + 1e-6 * np.eye(6)
    inv = np.linalg.inv(cov)

    def d2(A: np.ndarray) -> np.ndarray:
        D = A - mu
        return np.einsum("ij,jk,ik->i", D, inv, D)
    limit = float(np.quantile(d2(X), quantile))

    def predict(readings: list[Reading]) -> list[Pred]:
        A, usable = build_features(readings)
        dist = d2(A[:, :6])
        return [Pred("SUSPECT" if (u and d > limit) else "VALID") for u, d in zip(usable, dist)]
    return predict


def build_configs(settings: dict, table: NormalityTable, model: IsolationModel, limits: StationLimits,
                  train: list[Reading], sid: str, cadence: float) -> list[tuple[str, str, Predictor]]:
    cfgs: list[tuple[str, str, Predictor]] = [
        ("full", "full", pipeline_predictor(settings, table, model, limits, sid, cadence))]
    for layer in ("physics", "health", "normality", "mlmodel", "timing", "limits"):
        variant = copy.deepcopy(settings)
        variant["layers"][layer] = False
        cfgs.append((f"no_{layer}", "ablation", pipeline_predictor(variant, table, model, limits, sid, cadence)))
    cfgs += [("baseline_range", "baseline", baseline_range(settings)),
             ("baseline_rules", "baseline", baseline_rules(settings, cadence)),
             ("baseline_climatology", "baseline", baseline_climatology(table, settings)),
             ("baseline_isolation_forest", "baseline", baseline_iforest(model)),
             ("baseline_mahalanobis", "baseline", baseline_mahalanobis(train))]
    return cfgs


# ====================================================================================================
# metrics
# ====================================================================================================
def is_alarm(p: Pred) -> bool:
    return p.verdict in ALARM


def count_clean(chunks: list[list[Reading]], predict: Predictor) -> dict:
    n = alarm = fault = weather = 0
    for series in chunks:
        for p in predict(series):
            n += 1
            alarm += is_alarm(p)
            fault += p.verdict == "FAULT"
            weather += p.verdict == "WEATHER"
    return {"n": n, "alarm": alarm, "fault": fault, "weather": weather}


def count_events(events: list[EventSeries], predict: Predictor) -> dict:
    by_kind: dict[str, Counter] = defaultdict(Counter)
    windows_with_fault: dict[str, list[int]] = defaultdict(lambda: [0, 0])      # kind -> [windows with a FAULT, windows]
    for es in events:
        preds = predict(es.readings)[es.core_start: es.core_end]
        c = by_kind[es.kind]
        for p in preds:
            c["n"] += 1
            c[p.verdict] += 1
        windows_with_fault[es.kind][1] += 1
        windows_with_fault[es.kind][0] += any(p.verdict == "FAULT" for p in preds)
    return {k: {**dict(c), "windows_with_fault": windows_with_fault[k][0], "windows": windows_with_fault[k][1]}
            for k, c in by_kind.items()}


def count_detection(faulted: list[tuple[list[Reading], InjectionResult]], predict: Predictor, settings: dict,
                    cadence: float) -> dict:
    grace = math.ceil(settings["evaluate"]["detection_grace_minutes"] / cadence)
    out: dict[str, dict] = {t: {"detected": 0, "injected": 0, "delays_min": []} for t in ALL_FAULT_TYPES}
    for readings, res in faulted:
        preds = predict(readings)
        for e in res.events:
            window = preds[e.start_index: e.end_index + 1 + grace]
            hit = next((i for i, p in enumerate(window) if is_alarm(p)), None)
            o = out[e.fault_type]
            o["injected"] += 1
            if hit is not None:
                o["detected"] += 1
                o["delays_min"].append(hit * cadence)
    return out


def make_faulted(chunks: list[list[Reading]], settings: dict, rounds: int, min_len: int
                 ) -> list[tuple[list[Reading], InjectionResult]]:
    out = []
    for rnd in range(rounds):
        for idx, series in enumerate(chunks):
            if len(series) < min_len:
                continue
            seed = settings["seed"] + 1000 * (rnd + 1) + idx
            plan = make_plan(series, settings, seed=seed, types=ALL_FAULT_TYPES)
            if plan:
                res = inject(series, settings, plan, seed=seed)
                out.append((res.readings, res))
    return out


def drift_by_health(faulted: list[tuple[list[Reading], InjectionResult]], settings: dict, table: NormalityTable,
                    model: IsolationModel, limits: StationLimits, sid: str, cadence: float) -> dict:
    """Slow drift is judged by the health score: did the Theil-Sen drift on the right channel become significant
    (and with the right sign) before the ramp ended, and how far had it gone by then?"""
    s = copy.deepcopy(settings)
    s["healthscore"]["recompute_every_minutes"] = 10 ** 9
    check_every = max(1, int(round(24 * 60 / cadence)))                      # once per day of data
    limit_of = s["healthscore"]["drift"]["service_limit"]
    res = {"detected": 0, "injected": 0, "days_to_detect": [], "offset_over_limit": [], "wrong_sign": 0}
    for readings, inj in faulted:
        drifts = [e for e in inj.events if e.fault_type == "drift"]
        if not drifts:
            continue
        pipe = Pipeline(s, {sid: {"cadence_minutes": cadence}}, {sid: table},
                        {sid: ev._PrecomputedModel(model, readings)}, {sid: limits})
        first_start = min(e.start_index for e in drifts)
        found: dict[int, tuple[int, float]] = {}
        for i, r in enumerate(readings):
            pipe.process(r)
            if i < first_start or (i - first_start) % check_every:
                continue
            for k, e in enumerate(drifts):
                if k in found or not (e.start_index <= i <= e.end_index):
                    continue
                rep = pipe.health_report(sid, r.timestamp)
                ch = rep.channels.get(e.channel) if rep else None
                if ch and ch.drift_significant:
                    sign = e.params.get("sign", 1.0)
                    if ch.drift_per_day is not None and ch.drift_per_day * sign > 0:
                        found[k] = (i - e.start_index, ch.offset_now or 0.0)
                    else:
                        res["wrong_sign"] += 1
        for k, e in enumerate(drifts):
            res["injected"] += 1
            if k in found:
                res["detected"] += 1
                res["days_to_detect"].append(found[k][0] * cadence / 1440.0)
                res["offset_over_limit"].append(abs(found[k][1]) / limit_of[e.channel])
    return res


def drift_false_alarms(clean: list[list[Reading]], settings: dict, table: NormalityTable, model: IsolationModel,
                       limits: StationLimits, sid: str, cadence: float) -> dict:
    """The other side of the drift number: on clean real data with NO drift injected, how often does the daily
    health report claim a significant drift on some channel, or open a maintenance ticket?"""
    s = copy.deepcopy(settings)
    check_every = max(1, int(round(24 * 60 / cadence)))
    warm = int(s["healthscore"]["window_minutes"] / cadence)
    out = {"channel_days": 0, "significant": 0, "days": 0, "days_with_significant": 0, "ticket_days": 0}
    for readings in clean:
        if len(readings) < 3 * warm:
            continue
        pipe = Pipeline(s, {sid: {"cadence_minutes": cadence}}, {sid: table},
                        {sid: ev._PrecomputedModel(model, readings)}, {sid: limits})
        for i, r in enumerate(readings):
            pipe.process(r)
            if i < warm or i % check_every:
                continue
            rep = pipe.health_report(sid, r.timestamp)
            if rep is None or not rep.channels:
                continue
            sig = sum(1 for ch in rep.channels.values() if ch.drift_significant)
            out["days"] += 1
            out["channel_days"] += len(rep.channels)
            out["significant"] += sig
            out["days_with_significant"] += sig > 0
            out["ticket_days"] += rep.ticket is not None
    return out


def noaa_agreement(df_raw: pd.DataFrame, predict: Predictor, cadence: float, max_examples: int = 12) -> dict:
    """Run the full pipeline on the raw record (NOAA-flagged values left in) and compare with NOAA's own flags."""
    gap = 3 * cadence
    starts = [0, *[i for i in range(1, len(df_raw))
                   if (df_raw["timestamp"].iloc[i] - df_raw["timestamp"].iloc[i - 1]).total_seconds() / 60 > 24 * 60 * 20]]
    segs = [df_raw.iloc[a:b].reset_index(drop=True) for a, b in zip(starts, [*starts[1:], len(df_raw)])]
    out = {"flagged": 0, "flagged_caught": 0, "erroneous": 0, "erroneous_caught": 0, "unflagged": 0,
           "unflagged_alarm": 0, "examples": []}
    for seg in segs:
        if len(seg) < 10:
            continue
        readings = to_readings(seg)
        preds = predict(readings)
        for i, (p, flag) in enumerate(zip(preds, seg["noaa_flag"])):
            if flag > 0:
                out["flagged"] += 1
                out["flagged_caught"] += is_alarm(p)
                if flag == 2:
                    out["erroneous"] += 1
                    out["erroneous_caught"] += is_alarm(p)
                if len(out["examples"]) < max_examples:
                    r = readings[i]
                    out["examples"].append({"t": r.timestamp.isoformat(), "flag": int(flag),
                                            "T": r.temperature_c, "P": r.pressure_hpa, "RH": r.humidity_pct,
                                            "verdict": p.verdict, "checks": sorted(p.kinds)})
            else:
                out["unflagged"] += 1
                out["unflagged_alarm"] += is_alarm(p)
    return out


# ====================================================================================================
# one station, one phase
# ====================================================================================================
@dataclass
class PhasePlan:
    name: str                       # "DEV", "HOLDOUT_TIME", "HOLDOUT_SPACE"
    station: str
    train_path: Path
    eval_path: Path
    period: tuple[pd.Timestamp, pd.Timestamp]
    allow_holdout: bool


def evaluate_station(plan: PhasePlan, settings: dict, quick: bool, events_all: list[dict]) -> dict:
    s = real_settings(settings)
    df_train_src = read_frame(plan.train_path, s, plan.allow_holdout)
    df_eval_src = df_train_src if plan.eval_path == plan.train_path else read_frame(plan.eval_path, s, plan.allow_holdout)
    sid = plan.station
    cadence = cadence_of(df_train_src)
    windows_all = windows_of(events_all)

    # ---- fit on this station's own first four years, extreme windows and NOAA-flagged values removed
    tr = df_train_src[df_train_src["timestamp"] < TRAIN_END]
    train_chunks = cut_chunks(tr, windows_all, min_rows=1)
    train = [r for c in train_chunks for r in to_readings(c)]
    t0 = time.time()
    table = NormalityTable.fit(train, s)
    model = IsolationModel.fit(train, s)
    limits = fit_limits(train, s, cadence)
    fit_seconds = time.time() - t0

    # ---- the evaluation period
    lo, hi = plan.period
    if quick:
        hi = min(hi, lo + pd.DateOffset(years=1))
    period_df = df_eval_src[(df_eval_src["timestamp"] >= lo) & (df_eval_src["timestamp"] < hi)]
    period_events = [e for e in events_all if lo <= pd.Timestamp(e["center"]) < hi]
    min_rows = int(3 * 1440 / cadence)
    clean_frames = cut_chunks(period_df, windows_all, min_rows=min_rows)
    clean = [to_readings(c) for c in clean_frames]
    event_series, event_rows_cut = cut_events(df_eval_src, period_events)
    rounds = 1 if quick else s["evaluate"]["injection_rounds"]
    faulted = make_faulted(clean, s, rounds, min_len=int(30 * 1440 / cadence))

    configs = build_configs(s, table, model, limits, train, sid, cadence)
    results = {}
    for name, kind, predict in configs:
        results[name] = {"kind": kind, "clean": count_clean(clean, predict),
                         "events": count_events(event_series, predict),
                         "detection": count_detection(faulted, predict, s, cadence)}
    full = configs[0][2]
    extra = {"drift_health": drift_by_health(faulted, s, table, model, limits, sid, cadence),
             "drift_false": drift_false_alarms(clean, s, table, model, limits, sid, cadence),
             "noaa": noaa_agreement(period_df.reset_index(drop=True), full, cadence)}

    # ---- speed of the full pipeline, per reading (median and 95th percentile)
    sample = clean[0][: 2000] if clean else []
    lat = []
    if sample:
        pipe = Pipeline(s, {sid: {"cadence_minutes": cadence}}, {sid: table}, {sid: model}, {sid: limits})
        for r in sample:
            a = time.perf_counter()
            pipe.process(r)
            lat.append((time.perf_counter() - a) * 1000.0)
    return {"station": sid, "phase": plan.name, "cadence_minutes": cadence, "train_rows": len(train),
            "fit_seconds": round(fit_seconds, 2), "clean_rows": sum(len(c) for c in clean),
            "event_rows_cut_noaa": event_rows_cut, "n_events": len(event_series),
            "n_fault_series": len(faulted), "limits": {ch: vars(c) for ch, c in limits.channels.items()},
            "latency_ms": {"median": round(float(np.median(lat)), 3) if lat else None,
                           "p95": round(float(np.percentile(lat, 95)), 3) if lat else None},
            "configs": results, **extra}


def _worker(args):
    plan, settings, quick, events_all = args
    return evaluate_station(plan, settings, quick, events_all)


# ====================================================================================================
# orchestration and report
# ====================================================================================================
def load_events() -> dict:
    return json.loads(EVENTS_JSON.read_text(encoding="utf-8"))


def make_plans(phase: str, meta: dict) -> list[PhasePlan]:
    dev_stations, sealed = meta["dev_stations"], meta["sealed_stations"]
    plans = []
    if phase == "DEV":
        for sid in dev_stations:
            p = REAL_DEV_DIR / f"{sid}.csv"
            plans.append(PhasePlan("DEV", sid, p, p, (TRAIN_END, DEV_END), False))
    elif phase == "HOLDOUT":
        for sid in dev_stations:                                     # later years, same stations
            plans.append(PhasePlan("HOLDOUT_TIME", sid, REAL_DEV_DIR / f"{sid}.csv",
                                   REAL_HOLDOUT_DIR / f"{sid}_future.csv",
                                   (DEV_END, pd.Timestamp("2025-01-01")), True))
        for sid in sealed:                                           # stations never seen
            p = REAL_HOLDOUT_DIR / f"{sid}.csv"
            plans.append(PhasePlan("HOLDOUT_SPACE", sid, p, p, (TRAIN_END, pd.Timestamp("2025-01-01")), True))
    return plans


def run(phase: str, quick: bool, workers: int, only: Optional[list[str]] = None) -> dict:
    settings = load_settings()
    meta = load_events()
    plans = [p for p in make_plans(phase, meta) if not only or p.station in only]
    jobs = [(p, settings, quick, meta["events"][p.station]) for p in plans]
    if workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(_worker, jobs))
    else:
        rows = [_worker(j) for j in jobs]
    return {"quick": quick, "generated": datetime.utcnow().isoformat() + "Z", "rules": meta["rules"], "stations": rows}


def _pct(a: float, n: float) -> str:
    return "n/a" if not n else f"{100.0 * a / n:.1f}%"


def aggregate(rows: list[dict], phase: str) -> dict:
    """Sum counts over the stations of one phase."""
    sel = [r for r in rows if r["phase"] == phase]
    names = list(sel[0]["configs"]) if sel else []
    out = {}
    for n in names:
        det = {t: {"detected": 0, "injected": 0, "delays_min": []} for t in ALL_FAULT_TYPES}
        clean = Counter()
        events: dict[str, Counter] = defaultdict(Counter)
        for r in sel:
            c = r["configs"][n]
            clean.update(c["clean"])
            for t, d in c["detection"].items():
                det[t]["detected"] += d["detected"]
                det[t]["injected"] += d["injected"]
                det[t]["delays_min"] += d["delays_min"]
            for k, d in c["events"].items():
                events[k].update(d)
        out[n] = {"kind": sel[0]["configs"][n]["kind"], "clean": dict(clean), "detection": det,
                  "events": {k: dict(v) for k, v in events.items()}}
    noaa = Counter()
    for r in sel:
        noaa.update({k: v for k, v in r["noaa"].items() if k != "examples"})
    drift = {"detected": 0, "injected": 0, "days_to_detect": [], "offset_over_limit": [], "wrong_sign": 0}
    for r in sel:
        d = r["drift_health"]
        for k in ("detected", "injected", "wrong_sign"):
            drift[k] += d[k]
        drift["days_to_detect"] += d["days_to_detect"]
        drift["offset_over_limit"] += d["offset_over_limit"]
    dfa = Counter()
    for r in sel:
        dfa.update(r["drift_false"])
    return {"stations": [r["station"] for r in sel], "configs": out, "noaa": dict(noaa), "drift": drift,
            "drift_false": dict(dfa),
            "latency_ms": {"median": float(np.median([r["latency_ms"]["median"] for r in sel if r["latency_ms"]["median"]] or [0])),
                           "p95": float(np.max([r["latency_ms"]["p95"] for r in sel if r["latency_ms"]["p95"]] or [0]))}}


def format_phase(agg: dict, title: str) -> str:
    cfgs = agg["configs"]
    w = max(len(n) for n in cfgs) + 2
    L = [f"### {title}", f"stations: {', '.join(agg['stations'])}", ""]
    L.append("1) Detection of injected faults, by type  (alarm = FAULT or SUSPECT, from fault start to end + grace)")
    L.append(f"   {'config':<{w}}" + "".join(f"{t:>12}" for t in ALL_FAULT_TYPES))
    for n, c in cfgs.items():
        L.append(f"   {n:<{w}}" + "".join(f"{_pct(c['detection'][t]['detected'], c['detection'][t]['injected']):>12}"
                                          for t in ALL_FAULT_TYPES))
    first = next(iter(cfgs.values()))
    L.append(f"   {'(faults injected)':<{w}}" + "".join(f"{first['detection'][t]['injected']:>12}" for t in ALL_FAULT_TYPES))
    full = cfgs["full"]["detection"]
    med = {t: (float(np.median(full[t]["delays_min"])) if full[t]["delays_min"] else None) for t in ALL_FAULT_TYPES}
    L.append(f"   {'full: median delay to first alarm (min)':<{w}}" +
             "".join(f"{('-' if med[t] is None else f'{med[t]:.0f}'):>12}" for t in ALL_FAULT_TYPES))
    L += ["", "2) False alarms on clean real data  (no faults injected, extreme-weather windows and NOAA-flagged values removed)",
          f"   {'config':<{w}}{'any alarm':>11}{'FAULT only':>12}{'WEATHER':>10}{'samples':>10}"]
    for n, c in cfgs.items():
        k = c["clean"]
        L.append(f"   {n:<{w}}{_pct(k['alarm'], k['n']):>11}{_pct(k['fault'], k['n']):>12}"
                 f"{(_pct(k['weather'], k['n']) if c['kind'] != 'baseline' else '-'):>10}{k['n']:>10}")
    L += ["", "3) Real extreme weather  (no faults injected). A FAULT here is a failure: real weather called a broken sensor.",
          f"   {'config':<{w}}{'FAULT':>9}{'SUSPECT':>10}{'WEATHER':>10}{'VALID':>9}{'windows with a FAULT':>24}"]
    for n, c in cfgs.items():
        tot = Counter()
        wf = wn = 0
        for k, d in c["events"].items():
            tot.update({x: d.get(x, 0) for x in ("n", "FAULT", "SUSPECT", "WEATHER", "VALID")})
            wf += d["windows_with_fault"]
            wn += d["windows"]
        ratio = str(wf) + "/" + str(wn)
        L.append(f"   {n:<{w}}{_pct(tot['FAULT'], tot['n']):>9}{_pct(tot['SUSPECT'], tot['n']):>10}"
                 f"{(_pct(tot['WEATHER'], tot['n']) if c['kind'] != 'baseline' else '-'):>10}{_pct(tot['VALID'], tot['n']):>9}"
                 f"{ratio:>24}")
    L += ["", "   full pipeline, by kind of extreme weather:", f"   {'kind':<8}{'samples':>9}{'FAULT':>9}{'SUSPECT':>10}{'WEATHER':>10}{'windows with FAULT':>21}"]
    for k, d in sorted(cfgs["full"]["events"].items()):
        wf = str(d["windows_with_fault"]) + "/" + str(d["windows"])
        L.append(f"   {k:<8}{d['n']:>9}{_pct(d.get('FAULT', 0), d['n']):>9}{_pct(d.get('SUSPECT', 0), d['n']):>10}"
                 f"{_pct(d.get('WEATHER', 0), d['n']):>10}{wf:>21}")
    n = agg["noaa"]
    L += ["", "4) Agreement with NOAA's own quality flags on the raw record  (another automated system, NOT ground truth)",
          f"   NOAA-flagged values: {n.get('flagged', 0)}  (erroneous: {n.get('erroneous', 0)})",
          f"   AtmosGuard alarmed on {_pct(n.get('flagged_caught', 0), n.get('flagged', 0))} of them, "
          f"and on {_pct(n.get('erroneous_caught', 0), n.get('erroneous', 0))} of the erroneous ones",
          f"   AtmosGuard alarmed on {_pct(n.get('unflagged_alarm', 0), n.get('unflagged', 0))} of the {n.get('unflagged', 0)} values NOAA did not flag"]
    d = agg["drift"]
    L += ["", "5) Slow drift, judged by the health score  (Theil-Sen slope significant, right sign, before the ramp ends)",
          f"   detected {d['detected']}/{d['injected']}  ({_pct(d['detected'], d['injected'])}); wrong-sign detections: {d['wrong_sign']}"]
    if d["days_to_detect"]:
        L.append(f"   median time to detect: {np.median(d['days_to_detect']):.1f} days into the ramp; "
                 f"median offset at detection: {np.median(d['offset_over_limit']):.2f} x the service limit")
    f = agg["drift_false"]
    L += [f"   on clean data with NO drift injected: significant drift claimed on {_pct(f.get('days_with_significant', 0), f.get('days', 0))} "
          f"of {f.get('days', 0)} station-days (per channel: {_pct(f.get('significant', 0), f.get('channel_days', 0))}); "
          f"a maintenance ticket was open on {_pct(f.get('ticket_days', 0), f.get('days', 0))} of them"]
    L += ["", f"6) Speed (full pipeline, one reading): median {agg['latency_ms']['median']:.2f} ms, worst station 95th percentile {agg['latency_ms']['p95']:.2f} ms"]
    return "\n".join(L)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate AtmosGuard on real station data. See config/protocol.md.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dev", action="store_true")
    g.add_argument("--holdout", action="store_true")
    ap.add_argument("--quick", action="store_true", help="one year and one fault round: for tuning loops only")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--stations", nargs="*", help="only these stations")
    ap.add_argument("--out", type=Path, default=None, help="write the raw results as JSON")
    ap.add_argument("--force-rerun-holdout", action="store_true",
                    help="reproduce a holdout run that was already made (the original lock file stays in git history)")
    args = ap.parse_args(argv)
    settings = load_settings()
    phase = "HOLDOUT" if args.holdout else "DEV"
    if args.holdout:
        lock = REPO / "data" / "holdout" / ev.LOCK_NAME
        if args.force_rerun_holdout and lock.exists():
            print(f"Re-running the holdout to reproduce it. The first run is recorded in {lock}.")
        else:
            try:
                ev.guard_holdout(settings, REPO, REPO / "data")
            except ev.HoldoutError as e:
                print(f"Cannot run the holdout: {e}")
                return 2
    res = run(phase, args.quick, args.workers, args.stations)
    text = []
    for ph in dict.fromkeys(r["phase"] for r in res["stations"]):
        text.append(format_phase(aggregate(res["stations"], ph), {"DEV": "DEV (tuning allowed)",
                                                                  "HOLDOUT_TIME": "HOLDOUT in time (DEV stations, 2022-2024)",
                                                                  "HOLDOUT_SPACE": "HOLDOUT in space (sealed stations, 2020-2024)"}[ph]))
    print("\n\n".join(text))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
