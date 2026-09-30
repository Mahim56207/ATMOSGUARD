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
from dataclasses import dataclass
from datetime import datetime
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
from atmos import healthscore
from atmos.limits import StationLimits, complete_limits, fit_limits
from atmos.mlmodel import IsolationModel, MahalanobisModel, build_features
from atmos.normality import NormalityTable
from atmos.schema import CHANNELS, Reading

REPO = CONFIG_DIR.parent
REAL_DEV_DIR = REPO / "data" / "real" / "dev"
REAL_HOLDOUT_DIR = REPO / "data" / "holdout" / "real"
EVENTS_JSON = REPO / "data" / "real" / "events.json"
REAL_FRESH_DIR = REPO / "data" / "fresh" / "real"
FRESH_EVENTS_JSON = REPO / "data" / "fresh" / "events.json"
REAL_FRESH2_DIR = REPO / "data" / "fresh2" / "real"
FRESH2_EVENTS_JSON = REPO / "data" / "fresh2" / "events.json"
REAL_FRESH3_DIR = REPO / "data" / "fresh3" / "real"
FRESH3_EVENTS_JSON = REPO / "data" / "fresh3" / "events.json"
REAL_FRESH4_DIR = REPO / "data" / "fresh4" / "real"
FRESH4_EVENTS_JSON = REPO / "data" / "fresh4" / "events.json"
WARM_DAYS = 60                     # Amendment 4: days of regular reporting a station with an unlearned noise limit learns it from
RESULTS_DIR = REPO / "results"
TRAIN_END = pd.Timestamp("2020-01-01")          # training = everything before this
DEV_END = pd.Timestamp("2022-01-01")
LEAD_IN_DAYS = 2                                 # extra history fed before an event window, not counted
ALARM = ("FAULT", "SUSPECT")
# Slow drift is judged by the health score (drift_power), not by alarms, so it is not in the alarm table.
REAL_TYPES = tuple(t for t in ALL_FAULT_TYPES if t != "drift")
DRIFT_SEVERITIES = (1.0, 2.0, 4.0, 8.0)      # total offset at the end of the ramp, in multiples of the service limit
DRIFT_RAMP_DAYS = 45
DRIFT_START_DAY = 10
DRIFT_MIN_CHUNK_DAYS = 80


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


def memoize(predict: Predictor) -> Predictor:
    """Remember the predictions for a series (by identity). A clean chunk is judged once for the false-alarm count and is
    then reused as the un-faulted reference for the paired detection score."""
    cache: dict[int, tuple[list[Reading], list[Pred]]] = {}

    def wrapped(readings: list[Reading]) -> list[Pred]:
        hit = cache.get(id(readings))
        if hit is not None and hit[0] is readings:
            return hit[1]
        out = predict(readings)
        cache[id(readings)] = (readings, out)
        return out
    wrapped.clear = cache.clear                      # type: ignore[attr-defined]
    return wrapped


def pipeline_predictor(settings: dict, table: NormalityTable, model: IsolationModel, limits: StationLimits,
                       sid: str, cadence: float, mahal: Optional[MahalanobisModel] = None) -> Predictor:
    def predict(readings: list[Reading]) -> list[Pred]:
        pipe = Pipeline(settings, {sid: {"cadence_minutes": cadence}}, {sid: table},
                        {sid: ev._PrecomputedModel(model, readings)}, {sid: limits},
                        {sid: mahal} if mahal is not None else None)
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


def pin_registered(settings: dict) -> dict:
    """Every remedy off: the pipeline as registered and reported in dev_run4, holdout_run1/2 and fresh_run1."""
    settings["health"]["frozen"]["ceiling_aware"] = False       # remedy 1 (Amendment 2, adopted afterwards)
    settings["limits"]["learned_step_cap"] = False              # remedy 2 (Amendment 2, rejected)
    settings["health"]["step"]["expected_aware"] = False        # remedy 3 (Amendment 3)
    settings["health"]["offset"]["enabled"] = False             # remedy 4 (Amendment 3)
    settings["health"]["frozen"]["freezing_aware"] = False      # remedy 7 (Amendment 5)
    settings["limits"]["gap_aware_noise"] = False               # remedy 8 (Amendment 6)
    return settings


def amendment3_variants(base: dict) -> list[tuple[str, dict]]:
    """FRESH2: the shipped pipeline (remedy 1 on) with each Amendment 3 remedy switched on alone, and all three together."""
    out = []
    for name, keys in (("r3_expected_step", ("step",)), ("r4_offset", ("offset",)), ("r34_both", ("step", "offset"))):
        v = copy.deepcopy(base)
        if "step" in keys:
            v["health"]["step"]["expected_aware"] = True
        if "offset" in keys:
            v["health"]["offset"]["enabled"] = True
        out.append((name, v))
    return out


def build_configs(settings: dict, table: NormalityTable, model: IsolationModel, limits: StationLimits,
                  train: list[Reading], sid: str, cadence: float,
                  mahal: Optional[MahalanobisModel] = None, phase: str = "DEV",
                  limits_alt: Optional[StationLimits] = None) -> list[tuple[str, str, Predictor]]:
    settings = pin_registered(copy.deepcopy(settings))          # `full`, the ablations and the baselines are the pipeline that was
    if phase == "FRESH4":                                       # Amendment 5: `full` is the pipeline as shipped; r7_freezing adds the freezing-point rule
        shipped = copy.deepcopy(settings)
        shipped["health"]["frozen"]["ceiling_aware"] = True
        shipped["health"]["step"]["expected_aware"] = True
        frz = copy.deepcopy(shipped)
        frz["health"]["frozen"]["freezing_aware"] = True
        cfgs = [("full", "full", pipeline_predictor(shipped, table, model, limits, sid, cadence, mahal)),
                ("r7_freezing", "remedy", pipeline_predictor(frz, table, model, limits, sid, cadence, mahal))]
    elif phase == "FRESH3":                                     # Amendment 4: `full` is the shipped pipeline (remedies 1 and 3 on); r6_warmup adds the warm-up limits
        shipped = copy.deepcopy(settings)
        shipped["health"]["frozen"]["ceiling_aware"] = True
        shipped["health"]["step"]["expected_aware"] = True
        cfgs = [("full", "full", pipeline_predictor(shipped, table, model, limits, sid, cadence, mahal)),
                ("r6_warmup", "remedy", pipeline_predictor(shipped, table, model, limits_alt or limits, sid, cadence, mahal))]
    elif phase == "FRESH2":                                     # registered and reported (all remedies off), whatever the shipped default is now
        shipped = copy.deepcopy(settings)
        shipped["health"]["frozen"]["ceiling_aware"] = True     # FRESH2's `full` is the pipeline as shipped before Amendment 3 (remedy 1 adopted)
        cfgs = [("full", "full", pipeline_predictor(shipped, table, model, limits, sid, cadence, mahal)),
                ("registered", "registered", pipeline_predictor(settings, table, model, limits, sid, cadence, mahal))]
        for name, variant in amendment3_variants(shipped):
            cfgs.append((name, "remedy", pipeline_predictor(variant, table, model, limits, sid, cadence, mahal)))
    else:
        cfgs = [("full", "full", pipeline_predictor(settings, table, model, limits, sid, cadence, mahal))]
    for name, frozen, step in ((("remedy_frozen", True, False), ("remedy_step", False, True), ("remedies", True, True))
                               if phase not in ("FRESH2", "FRESH3", "FRESH4") else ()):
        variant = copy.deepcopy(settings)                       # the two remedies of docs/HOLDOUT_POSTMORTEM.md (off in "full")
        variant["health"]["frozen"]["ceiling_aware"] = frozen
        variant["limits"]["learned_step_cap"] = step
        cfgs.append((name, "remedy", pipeline_predictor(variant, table, model, limits, sid, cadence, mahal)))
    for layer in (("physics", "health", "normality", "mlmodel", "mahalanobis", "timing", "limits") if phase not in ("FRESH2", "FRESH3", "FRESH4") else ()):
        variant = copy.deepcopy(settings)
        variant["layers"][layer] = False
        cfgs.append((f"no_{layer}", "ablation", pipeline_predictor(variant, table, model, limits, sid, cadence, mahal)))
    cfgs += [("baseline_range", "baseline", baseline_range(settings)),
             ("baseline_rules", "baseline", baseline_rules(settings, cadence)),
             ("baseline_climatology", "baseline", baseline_climatology(table, settings)),
             ("baseline_isolation_forest", "baseline", baseline_iforest(model)),
             ("baseline_mahalanobis", "baseline", baseline_mahalanobis(train))]
    return [(name, kind, memoize(p)) for name, kind, p in cfgs]


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


def count_detection(faulted: list[tuple[list[Reading], InjectionResult, list[Reading]]], predict: Predictor,
                    settings: dict, cadence: float) -> dict:
    """Two scores per fault type.
      detected      : the registered criterion. Any alarm from the first faulty sample to the last plus the grace.
      detected_new  : the fault is what raised it. An alarm counts only if the same sample was NOT an alarm on the
                      un-faulted series. Background false alarms (about 2 % of samples) land inside long fault windows
                      (a 4-day window: an 84 % chance of some alarm), so the first score flatters long faults and every
                      system, baselines included; the second does not."""
    grace = math.ceil(settings["evaluate"]["detection_grace_minutes"] / cadence)
    out: dict[str, dict] = {t: {"detected": 0, "detected_new": 0, "injected": 0, "delays_min": [], "delays_new_min": [],
                                "named_fault": 0, "masked_as_weather": 0} for t in REAL_TYPES}
    for readings, res, original in faulted:
        preds, base = predict(readings), predict(original)
        for e in res.events:
            lo, hi = e.start_index, e.end_index + 1 + grace
            o = out[e.fault_type]
            o["injected"] += 1
            hit = next((i for i, p in enumerate(preds[lo:hi]) if is_alarm(p)), None)
            new = next((i for i, (p, b) in enumerate(zip(preds[lo:hi], base[lo:hi])) if is_alarm(p) and not is_alarm(b)), None)
            if hit is not None:
                o["detected"] += 1
                o["delays_min"].append(hit * cadence)
            if new is not None:
                o["detected_new"] += 1
                o["delays_new_min"].append(new * cadence)
                o["named_fault"] += any(p.verdict == "FAULT" and b.verdict != "FAULT" for p, b in zip(preds[lo:hi], base[lo:hi]))
            elif any(p.verdict == "WEATHER" and b.verdict != "WEATHER" for p, b in zip(preds[lo:hi], base[lo:hi])):
                o["masked_as_weather"] += 1                    # not raised as an alarm, but the fault made samples look like weather
    return out


def make_faulted(chunks: list[list[Reading]], settings: dict, rounds: int, min_len: int
                 ) -> list[tuple[list[Reading], InjectionResult, list[Reading]]]:
    """(faulted series, ground-truth log, the un-faulted series it came from)."""
    out = []
    for rnd in range(rounds):
        for idx, series in enumerate(chunks):
            if len(series) < min_len:
                continue
            seed = settings["seed"] + 1000 * (rnd + 1) + idx
            plan = make_plan(series, settings, seed=seed, types=REAL_TYPES)
            if plan:
                res = inject(series, settings, plan, seed=seed)
                out.append((res.readings, res, series))
    return out


def drift_power(chunks: list[list[Reading]], settings: dict, table: NormalityTable, cadence: float) -> dict:
    """Detection power of the drift monitor. A ramp is added to ONE channel of a clean real chunk (from day
    DRIFT_START_DAY, over DRIFT_RAMP_DAYS, then held), and the daily monitor (DriftTracker + significance test +
    the isolated-trend rule) is read once a day. Severity = the offset reached at the end of the ramp, in multiples
    of the service limit. Detected = significant on the ramped channel with the right sign, at any day from the
    start of the ramp. Severity 0 = no ramp (false claims, on the same real weather). Uses the tracker on the raw
    residual stream: a drift does not make the hard checks raise FAULT, so it is the same stream the pipeline
    gives the tracker."""
    cfg = settings["healthscore"]["drift"]
    limit_of = cfg["service_limit"]
    min_samples = max(1.0, cfg["min_day_fraction"] * 1440.0 / cadence)
    per_day = max(1, int(round(1440 / cadence)))
    out: dict[str, dict] = {}
    for ch in CHANNELS:
        for sev in (0.0, *DRIFT_SEVERITIES):
            out[f"{ch}|{sev:g}"] = {"trials": 0, "detected": 0, "wrong_sign": 0, "days_to_detect": [],
                                    "offset_over_limit": []}
    for readings in chunks:
        if len(readings) * cadence / 1440.0 < DRIFT_MIN_CHUNK_DAYS:
            continue
        t0 = readings[0].timestamp
        for target in CHANNELS:
            for sev in (0.0, *DRIFT_SEVERITIES):
                if sev == 0.0 and target != CHANNELS[0]:
                    continue                                   # one no-ramp run per chunk covers every channel
                tracker = healthscore.DriftTracker(settings)
                total = sev * limit_of[target]
                found: dict[str, tuple[float, float]] = {}
                wrong = 0
                for i, r in enumerate(readings):
                    day = (r.timestamp - t0).total_seconds() / 86400.0
                    vals = {ch: getattr(r, ch) for ch in CHANNELS}
                    if vals[target] is not None and sev > 0:
                        vals[target] += total * min(1.0, max(0.0, (day - DRIFT_START_DAY) / DRIFT_RAMP_DAYS))
                    tracker.update(Reading(station_id=r.station_id, timestamp=r.timestamp, **vals), table, frozenset())
                    if day < DRIFT_START_DAY or i % per_day:
                        continue
                    daily = {ch: tracker.series(ch, r.timestamp, cfg["window_days"] + cfg["persist_days"], min_samples) for ch in CHANNELS}
                    res = healthscore.drift_all(daily, r.timestamp, settings, True)
                    for ch in ((target,) if sev > 0 else CHANNELS):
                        d = res[ch]
                        if ch in found or not d.get("drift_significant"):
                            continue
                        if sev == 0 or d["drift_per_day"] > 0:
                            found[ch] = (day - DRIFT_START_DAY, d["offset_now"])
                        else:
                            wrong += 1
                for ch in ((target,) if sev > 0 else CHANNELS):
                    o = out[f"{ch}|{sev:g}"]
                    o["trials"] += 1
                    o["wrong_sign"] += wrong if ch == target else 0
                    if ch in found:
                        o["detected"] += 1
                        o["days_to_detect"].append(found[ch][0])
                        o["offset_over_limit"].append(abs(found[ch][1]) / limit_of[ch])
    return out


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
    out = {"flagged": 0, "flagged_caught": 0, "flagged_escalated": 0, "erroneous": 0, "erroneous_caught": 0,
           "unflagged": 0, "unflagged_alarm": 0, "unflagged_escalated": 0, "examples": []}
    for seg in segs:
        if len(seg) < 10:
            continue
        readings = to_readings(seg)
        preds = predict(readings)
        for i, (p, flag) in enumerate(zip(preds, seg["noaa_flag"])):
            if flag > 0:
                out["flagged"] += 1
                out["flagged_caught"] += is_alarm(p)
                out["flagged_escalated"] += p.verdict != "VALID"
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
                out["unflagged_escalated"] += p.verdict != "VALID"
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


def warm_stretch(frame: pd.DataFrame, lo: pd.Timestamp, hi: pd.Timestamp) -> Optional[tuple[pd.Timestamp, pd.Timestamp, float]]:
    """Amendment 4. The first WARM_DAYS days of the judged period in which the station reports regularly at the cadence it has now (at least 90 % of the expected
    reports on at least 90 % of the days). Uses timestamps only, never the values or a verdict. Returns (start, end, cadence in minutes) or None."""
    f = frame[(frame["timestamp"] >= lo) & (frame["timestamp"] < hi)]
    if len(f) < 1000:
        return None
    recent = f[f["timestamp"] >= hi - pd.DateOffset(years=1)]
    cad = float(recent["timestamp"].diff().dt.total_seconds().median() / 60.0)
    if not cad or cad <= 0:
        return None
    per_day = 1440.0 / cad
    days = f.groupby(f["timestamp"].dt.floor("D")).size()
    days = days.reindex(pd.date_range(days.index.min(), days.index.max(), freq="D"), fill_value=0)
    good = (days >= 0.9 * per_day).astype(int)
    roll = good.rolling(WARM_DAYS).sum()
    ok = roll[roll >= 0.9 * WARM_DAYS]
    if ok.empty:
        return None
    end = ok.index[0] + pd.Timedelta(days=1)
    return end - pd.Timedelta(days=WARM_DAYS), end, cad


def evaluate_station(plan: PhasePlan, settings: dict, quick: bool, events_all: list[dict],
                     parts: frozenset = frozenset({"detect", "events", "noaa", "drift", "latency"})) -> dict:
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
    mahal = MahalanobisModel.fit(train, s, table)
    fit_seconds = time.time() - t0

    # ---- Amendment 4: a station whose training record left a noise limit unlearned learns it from its first regular stretch, and every configuration is judged after it
    warm_info, limits_warm = None, None
    lo, hi = plan.period
    if plan.name == "FRESH3" and any(c.noise_std is None for c in limits.channels.values()):
        ws = warm_stretch(df_eval_src, lo, hi)
        if ws is not None:
            wstart, wend, wcad = ws
            wframe = df_eval_src[(df_eval_src["timestamp"] >= wstart) & (df_eval_src["timestamp"] < wend)]
            wread = [r for c in cut_chunks(wframe, windows_all, min_rows=1) for r in to_readings(c)]
            limits_warm = complete_limits(limits, wread, s, wcad)
            warm_info = {"start": wstart.isoformat(), "end": wend.isoformat(), "cadence_minutes": wcad, "readings": len(wread),
                         "noise_learned": {ch: c.noise_std is not None for ch, c in limits_warm.channels.items()}}
            lo = wend
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

    configs = build_configs(s, table, model, limits, train, sid, cadence, mahal, plan.name, limits_warm)
    results = {}
    if parts & {"detect", "events"}:
        for name, kind, predict in configs:
            results[name] = {"kind": kind, "clean": count_clean(clean, predict),
                             "events": count_events(event_series, predict) if "events" in parts else {},
                             "detection": count_detection(faulted, predict, s, cadence) if "detect" in parts else
                             {t: {"detected": 0, "detected_new": 0, "injected": 0, "delays_min": [], "delays_new_min": []}
                              for t in REAL_TYPES}}
            predict.clear()                                    # free the remembered predictions of this configuration
    full = configs[0][2]
    extra = {"drift_power": drift_power(clean, s, table, cadence) if "drift" in parts else {},
             "drift_false": (drift_false_alarms(clean, s, table, model, limits, sid, cadence) if "drift" in parts else {}),
             "noaa": (noaa_agreement(period_df.reset_index(drop=True), full, cadence) if "noaa" in parts else {})}

    # ---- speed of the full pipeline, per reading (median and 95th percentile)
    sample = clean[0][: 2000] if (clean and "latency" in parts) else []
    lat = []
    if sample:
        pipe = Pipeline(s, {sid: {"cadence_minutes": cadence}}, {sid: table}, {sid: model}, {sid: limits}, {sid: mahal})
        for r in sample:
            a = time.perf_counter()
            pipe.process(r)
            lat.append((time.perf_counter() - a) * 1000.0)
    return {"station": sid, "phase": plan.name, "cadence_minutes": cadence, "train_rows": len(train),
            "fit_seconds": round(fit_seconds, 2), "clean_rows": sum(len(c) for c in clean),
            "event_rows_cut_noaa": event_rows_cut, "n_events": len(event_series),
            "n_fault_series": len(faulted), "limits": {ch: vars(c) for ch, c in limits.channels.items()}, "warm": warm_info,
            "latency_ms": {"median": round(float(np.median(lat)), 3) if lat else None,
                           "p95": round(float(np.percentile(lat, 95)), 3) if lat else None},
            "configs": results, **extra}


def _worker(args):
    plan, settings, quick, events_all, parts = args
    return evaluate_station(plan, settings, quick, events_all, parts)


# ====================================================================================================
# orchestration and report
# ====================================================================================================
def load_events(phase: str = "DEV") -> dict:
    path = {"FRESH": FRESH_EVENTS_JSON, "FRESH2": FRESH2_EVENTS_JSON, "FRESH3": FRESH3_EVENTS_JSON, "FRESH4": FRESH4_EVENTS_JSON}.get(phase, EVENTS_JSON)
    return json.loads(path.read_text(encoding="utf-8"))


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
    elif phase == "FRESH":
        for sid in sealed:                                           # stations nobody had looked at (Amendment 2)
            p = REAL_FRESH_DIR / f"{sid}.csv"
            plans.append(PhasePlan("FRESH", sid, p, p, (TRAIN_END, pd.Timestamp("2025-01-01")), True))
    elif phase == "FRESH2":
        for sid in sealed:                                           # a third set, twelve stations, Indian airports and Australian AWS (Amendment 3)
            p = REAL_FRESH2_DIR / f"{sid}.csv"
            plans.append(PhasePlan("FRESH2", sid, p, p, (TRAIN_END, pd.Timestamp("2025-01-01")), True))
    elif phase == "FRESH3":
        for sid in sealed:                                           # a fourth set: seven US 20-minute stations and five Australian AWS with irregular training years (Amendment 4)
            p = REAL_FRESH3_DIR / f"{sid}.csv"
            plans.append(PhasePlan("FRESH3", sid, p, p, (TRAIN_END, pd.Timestamp("2025-01-01")), True))
    elif phase == "FRESH4":
        for sid in sealed:                                           # twelve northern US stations with freezing winters (Amendment 5)
            p = REAL_FRESH4_DIR / f"{sid}.csv"
            plans.append(PhasePlan("FRESH4", sid, p, p, (TRAIN_END, pd.Timestamp("2025-01-01")), True))
    return plans


def run(phase: str, quick: bool, workers: int, only: Optional[list[str]] = None,
        parts: frozenset = frozenset({"detect", "events", "noaa", "drift", "latency"})) -> dict:
    settings = load_settings()
    meta = load_events(phase)
    plans = [p for p in make_plans(phase, meta) if not only or p.station in only]
    jobs = [(p, settings, quick, meta["events"][p.station], parts) for p in plans]
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
        det = {t: {"detected": 0, "detected_new": 0, "injected": 0, "delays_min": [], "delays_new_min": []} for t in REAL_TYPES}
        clean = Counter()
        events: dict[str, Counter] = defaultdict(Counter)
        for r in sel:
            c = r["configs"][n]
            clean.update(c["clean"])
            for t, d in c["detection"].items():
                det[t]["detected"] += d["detected"]
                det[t]["detected_new"] += d.get("detected_new", 0)
                det[t]["injected"] += d["injected"]
                det[t]["delays_min"] += d["delays_min"]
                det[t]["delays_new_min"] += d.get("delays_new_min", [])
                det[t]["named_fault"] = det[t].get("named_fault", 0) + d.get("named_fault", 0)
                det[t]["masked_as_weather"] = det[t].get("masked_as_weather", 0) + d.get("masked_as_weather", 0)
            for k, d in c["events"].items():
                events[k].update(d)
        out[n] = {"kind": sel[0]["configs"][n]["kind"], "clean": dict(clean), "detection": det,
                  "events": {k: dict(v) for k, v in events.items()}}
    noaa = Counter()
    for r in sel:
        noaa.update({k: v for k, v in r["noaa"].items() if k != "examples"})
    drift: dict[str, dict] = {}
    for r in sel:
        for key, d in r["drift_power"].items():
            a = drift.setdefault(key, {"trials": 0, "detected": 0, "wrong_sign": 0, "days_to_detect": [], "offset_over_limit": []})
            for k in ("trials", "detected", "wrong_sign"):
                a[k] += d[k]
            a["days_to_detect"] += d["days_to_detect"]
            a["offset_over_limit"] += d["offset_over_limit"]
    dfa = Counter()
    for r in sel:
        dfa.update(r["drift_false"])
    return {"stations": [r["station"] for r in sel], "configs": out, "noaa": dict(noaa), "drift": drift,
            "drift_false": dict(dfa),
            "latency_ms": {"median": float(np.median([r["latency_ms"]["median"] for r in sel if r["latency_ms"]["median"]] or [0])),
                           "p95": float(np.max([r["latency_ms"]["p95"] for r in sel if r["latency_ms"]["p95"]] or [0]))}}


def format_phase(agg: dict, title: str) -> str:
    cfgs = agg["configs"]
    if not cfgs:                                        # a --parts run without the verdict tables
        cfgs = {"full": {"kind": "full", "clean": {"n": 0, "alarm": 0, "fault": 0, "weather": 0}, "events": {},
                         "detection": {t: {"detected": 0, "detected_new": 0, "injected": 0, "delays_min": [], "delays_new_min": []}
                                       for t in REAL_TYPES}}}
    w = max(len(n) for n in cfgs) + 2
    L = [f"### {title}", f"stations: {', '.join(agg['stations'])}", ""]
    L.append("1a) Detection of injected faults, by type: the fault raised the alarm  (paired: the same sample was NOT an alarm on the un-faulted series)")
    L.append(f"   {'config':<{w}}" + "".join(f"{t:>12}" for t in REAL_TYPES))
    for n, c in cfgs.items():
        L.append(f"   {n:<{w}}" + "".join(f"{_pct(c['detection'][t].get('detected_new', 0), c['detection'][t]['injected']):>12}"
                                          for t in REAL_TYPES))
    first = next(iter(cfgs.values()))
    L.append(f"   {'(faults injected)':<{w}}" + "".join(f"{first['detection'][t]['injected']:>12}" for t in REAL_TYPES))
    full = cfgs["full"]["detection"]
    med = {t: (float(np.median(full[t].get("delays_new_min", []))) if full[t].get("delays_new_min") else None) for t in REAL_TYPES}
    L.append(f"   {'full: median delay to the fault-raised alarm (min)':<{w}}" +
             "".join(f"{('-' if med[t] is None else f'{med[t]:.0f}'):>12}" for t in REAL_TYPES))
    L += ["", "1b) The same, by the REGISTERED criterion in config/protocol.md: any alarm from the first faulty sample to the last plus 60 min.",
          "    Background false alarms also land inside long fault windows, so 1b flatters long faults (frozen 48 h, clock shift 4 days) and every system.",
          f"   {'config':<{w}}" + "".join(f"{t:>12}" for t in REAL_TYPES)]
    for n, c in cfgs.items():
        L.append(f"   {n:<{w}}" + "".join(f"{_pct(c['detection'][t]['detected'], c['detection'][t]['injected']):>12}" for t in REAL_TYPES))
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
          f"   escalated at all (FAULT, SUSPECT or WEATHER) on {_pct(n.get('flagged_escalated', 0), n.get('flagged', 0))} of the flagged values, "
          f"and on {_pct(n.get('unflagged_escalated', 0), n.get('unflagged', 0))} of the values NOAA did not flag",
          f"   AtmosGuard alarmed on {_pct(n.get('unflagged_alarm', 0), n.get('unflagged', 0))} of the {n.get('unflagged', 0)} values NOAA did not flag"]
    d = agg["drift"]
    L += ["", "5) Slow drift, judged by the health score  (daily-mean Theil-Sen, autocorrelation-aware test)",
          f"   A ramp over {DRIFT_RAMP_DAYS} days is added to one channel of a clean real chunk; severity = offset at the end of the ramp in",
          "   multiples of the service limit (T 0.5 C, P 1 hPa, RH 3 %). Detected = significant with the right sign.",
          f"   {'severity':<10}" + "".join(f"{ch.split('_')[0]:>26}" for ch in CHANNELS),
          f"   {'':<10}" + "".join(f"{'detected  day  offset/limit':>26}" for _ in CHANNELS)]
    for sev in (0.0, *DRIFT_SEVERITIES):
        row = f"   {('none' if sev == 0 else f'{sev:g}x limit'):<10}"
        for ch in CHANNELS:
            a = d.get(f"{ch}|{sev:g}")
            if not a or not a["trials"]:
                row += f"{'n/a':>26}"
                continue
            det = _pct(a["detected"], a["trials"])
            if sev == 0:
                row += f"{det + ' (false claims)':>26}"
            else:
                day = f"{np.median(a['days_to_detect']):.0f}" if a["days_to_detect"] else "-"
                off = f"{np.median(a['offset_over_limit']):.1f}x" if a["offset_over_limit"] else "-"
                row += f"{f'{det:>6}  {day:>4}  {off:>7}':>26}"
        L.append(row)
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
    g.add_argument("--fresh", action="store_true", help="the twelve FRESH stations (Amendment 2 in config/protocol.md)")
    g.add_argument("--fresh2", action="store_true", help="the twelve FRESH2 stations (Amendment 3 in config/protocol.md)")
    g.add_argument("--fresh3", action="store_true", help="the twelve FRESH3 stations (Amendment 4 in config/protocol.md)")
    g.add_argument("--fresh4", action="store_true", help="the twelve FRESH4 stations (Amendment 5 in config/protocol.md)")
    ap.add_argument("--quick", action="store_true", help="one year and one fault round: for tuning loops only")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--stations", nargs="*", help="only these stations")
    ap.add_argument("--parts", default="detect,events,noaa,drift,latency",
                    help="comma list of what to run: detect, events, noaa, drift, latency (for tuning loops)")
    ap.add_argument("--out", type=Path, default=None, help="write the raw results as JSON")
    ap.add_argument("--force-rerun-holdout", action="store_true",
                    help="reproduce a holdout run that was already made (the original lock file stays in git history)")
    args = ap.parse_args(argv)
    settings = load_settings()
    phase = "HOLDOUT" if args.holdout else "FRESH" if args.fresh else "FRESH2" if args.fresh2 else "FRESH3" if args.fresh3 else "FRESH4" if args.fresh4 else "DEV"
    if args.fresh4:
        lock = REPO / "data" / "fresh4" / ev.FRESH4_LOCK_NAME
        if args.force_rerun_holdout and lock.exists():
            print(f"Re-running the FRESH4 evaluation to reproduce it. The first run is recorded in {lock}.")
        else:
            try:
                ev.guard_fresh4(settings, REPO, REPO / "data")
            except ev.HoldoutError as e:
                print(f"Cannot run the FRESH4 evaluation: {e}")
                return 2
    if args.fresh3:
        lock = REPO / "data" / "fresh3" / ev.FRESH3_LOCK_NAME
        if args.force_rerun_holdout and lock.exists():
            print(f"Re-running the FRESH3 evaluation to reproduce it. The first run is recorded in {lock}.")
        else:
            try:
                ev.guard_fresh3(settings, REPO, REPO / "data")
            except ev.HoldoutError as e:
                print(f"Cannot run the FRESH3 evaluation: {e}")
                return 2
    if args.fresh2:
        lock = REPO / "data" / "fresh2" / ev.FRESH2_LOCK_NAME
        if args.force_rerun_holdout and lock.exists():
            print(f"Re-running the FRESH2 evaluation to reproduce it. The first run is recorded in {lock}.")
        else:
            try:
                ev.guard_fresh2(settings, REPO, REPO / "data")
            except ev.HoldoutError as e:
                print(f"Cannot run the FRESH2 evaluation: {e}")
                return 2
    if args.fresh:
        lock = REPO / "data" / "fresh" / ev.FRESH_LOCK_NAME
        if args.force_rerun_holdout and lock.exists():
            print(f"Re-running the fresh evaluation to reproduce it. The first run is recorded in {lock}.")
        else:
            try:
                ev.guard_fresh(settings, REPO, REPO / "data")
            except ev.HoldoutError as e:
                print(f"Cannot run the fresh evaluation: {e}")
                return 2
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
    res = run(phase, args.quick, args.workers, args.stations, frozenset(args.parts.split(",")))
    text = []
    for ph in dict.fromkeys(r["phase"] for r in res["stations"]):
        text.append(format_phase(aggregate(res["stations"], ph), {"DEV": "DEV (tuning allowed)",
                                                                  "HOLDOUT_TIME": "HOLDOUT in time (DEV stations, 2022-2024)",
                                                                  "HOLDOUT_SPACE": "HOLDOUT in space (sealed stations, 2020-2024)",
                                                                  "FRESH": "FRESH (twelve stations nobody had looked at, 2020-2024)",
                                                                  "FRESH2": "FRESH2 (a third set of twelve: Indian airports and Australian AWS, 2020-2024)",
                                                                  "FRESH3": "FRESH3 (a fourth set of twelve: seven US 20-minute stations and five Australian AWS, 2020-2024)",
                                                                  "FRESH4": "FRESH4 (a fifth set of twelve northern US stations with freezing winters, 2020-2024)"}[ph]))
    print("\n\n".join(text))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
