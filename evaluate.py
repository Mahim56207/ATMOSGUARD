"""Baselines, ablation, DEV vs HOLDOUT metrics. Protocol: config/protocol.md.

Always prints three separate numbers, for every configuration:
  1. detection rate per fault type
  2. false-alarm rate on clean data
  3. false-alarm rate on real extreme-weather windows (no faults injected)

Usage:
    python evaluate.py --synthetic            # fake data, tests the plumbing only. NOT results.
    python evaluate.py --station S1           # DEV only, from data/clean and data/events
    python evaluate.py --station S1 --holdout # DEV + HOLDOUT. Guarded: read once, protocol must be committed.

`data/holdout/` is read once, by this file, at the end. Models are fitted on DEV train only.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Sequence

import numpy as np

import replay as replay_io
from atmos import health, physics
from atmos.config import CONFIG_DIR, load_settings, load_stations
from atmos.fusion import Pipeline
from atmos.injector import FAULT_TYPES, InjectionResult, inject, make_plan
from atmos.mlmodel import IsolationModel
from atmos.normality import NormalityTable
from atmos.schema import CHANNELS, Reading

REPO_ROOT = CONFIG_DIR.parent
ALARM_VERDICTS = ("FAULT", "SUSPECT")          # an alarm. WEATHER is a correct answer on weather, not an alarm.
ABLATED_LAYERS = ("physics", "health", "normality", "mlmodel", "timing")
LOCK_NAME = ".holdout_used"

Prediction = tuple[bool, bool]                 # (alarm, weather verdict)


# =====================================================================================================
# Synthetic data (--synthetic and tests). Fake weather: it tests the plumbing, it says nothing real.
# =====================================================================================================
def synthetic_series(settings: dict, days: int, seed: int, station: str = "S1",
                     with_event: bool = False) -> list[Reading]:
    """Fake weather with a daily cycle. With `with_event`, a smooth front-like excursion sits in the middle."""
    from datetime import timedelta
    cfg = settings["evaluate"]["synthetic"]
    cad = cfg["cadence_minutes"]
    rng = np.random.default_rng(seed)
    n = days * 24 * 60 // cad
    start = datetime.fromisoformat(cfg["start"])
    t, p, rh = cfg["temperature"], cfg["pressure"], cfg["humidity"]
    pressure = p["mean"]
    ev_len = cfg["event_duration_minutes"] // cad
    ev_start = n // 2 - ev_len // 2
    out = []
    for i in range(n):
        ts = start + timedelta(minutes=i * cad)
        cycle = math.sin(2 * math.pi * (ts.hour + ts.minute / 60.0 - 9) / 24)
        pressure += -p["reversion"] * (pressure - p["mean"]) + float(rng.normal(0, p["noise"]))
        temp = t["mean"] + t["daily_amp"] * cycle + float(rng.normal(0, t["noise"]))
        press = pressure + float(rng.normal(0, p["noise"]))
        hum = min(95.0, max(5.0, rh["mean"] - rh["daily_amp"] * cycle + float(rng.normal(0, rh["noise"]))))
        if with_event and ev_start <= i < ev_start + ev_len:
            u = (i - ev_start) / max(1, ev_len - 1)
            bump = 0.5 * (1 - math.cos(2 * math.pi * u))            # 0 -> 1 -> 0, smooth
            d = cfg["event_delta"]
            temp += d["temperature_c"] * bump
            press += d["pressure_hpa"] * bump
            hum = min(100.0, max(0.0, hum + d["humidity_pct"] * bump))
        out.append(Reading(station_id=station, timestamp=ts, temperature_c=temp, pressure_hpa=press, humidity_pct=hum))
    return out


# =====================================================================================================
# Data sets
# =====================================================================================================
@dataclass
class SplitData:
    name: str                                          # "DEV" or "HOLDOUT"
    clean: list[list[Reading]]                         # clean series (no faults, no weather events)
    events: list[list[Reading]]                        # extreme-weather windows, no faults injected
    faulted: list[tuple[list[Reading], InjectionResult]] = field(default_factory=list)


@dataclass
class EvalData:
    station_id: str
    train: list[Reading]
    cadence_minutes: float
    dev: SplitData
    holdout: Optional[SplitData] = None
    synthetic: bool = False


def make_faulted(clean: list[list[Reading]], settings: dict) -> list[tuple[list[Reading], InjectionResult]]:
    """Inject a seeded fault plan into each clean series, `injection_rounds` times. Inputs are not changed."""
    out = []
    for rnd in range(settings["evaluate"]["injection_rounds"]):
        for idx, series in enumerate(clean):
            seed = settings["seed"] + 1000 * (rnd + 1) + idx
            res = inject(series, settings, make_plan(series, settings, seed=seed), seed=seed)
            out.append((res.readings, res))
    return out


def synthetic_data(settings: dict) -> EvalData:
    cfg, seed = settings["evaluate"]["synthetic"], settings["seed"]

    def split(name: str, base: int) -> SplitData:
        clean = [synthetic_series(settings, cfg["eval_days"], seed + base)]
        events = [synthetic_series(settings, cfg["event_window_days"], seed + base + 1 + k, with_event=True)
                  for k in range(cfg["event_count"])]
        sd = SplitData(name, clean, events)
        sd.faulted = make_faulted(clean, settings)
        return sd
    return EvalData("S1", synthetic_series(settings, cfg["train_days"], seed + 1), float(cfg["cadence_minutes"]),
                    split("DEV", 2), split("HOLDOUT (synthetic)", 101), synthetic=True)


class HoldoutError(RuntimeError):
    pass


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def guard_holdout(settings: dict, repo_dir: Optional[Path] = None, data_dir: Optional[Path] = None) -> None:
    """Refuse to read the holdout unless: protocol.md is committed and clean, has no unfinished markers,
    and the holdout has not been used before. Writes the lock file when it passes."""
    repo = Path(repo_dir or REPO_ROOT)
    proto = "config/protocol.md"
    lock = Path(data_dir or replay_io.data_root(settings)) / "holdout" / LOCK_NAME
    if lock.exists():
        raise HoldoutError(f"The holdout was already used ({lock}). It is read once. "
                           "If you really must run it again, delete that file yourself and record why.")
    if _git(repo, "ls-files", "--error-unmatch", proto).returncode != 0:
        raise HoldoutError(f"{proto} is not committed. Commit it BEFORE the first holdout run.")
    if _git(repo, "status", "--porcelain", "--", proto).stdout.strip():
        raise HoldoutError(f"{proto} has uncommitted changes. Commit it BEFORE the first holdout run.")
    if "TODO" in (repo / proto).read_text(encoding="utf-8"):
        raise HoldoutError(f"{proto} still has a TODO in it. Finish it, then commit it.")
    commit = _git(repo, "log", "-1", "--format=%H", "--", proto).stdout.strip()
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps({"used_at": datetime.now(timezone.utc).isoformat(), "protocol_commit": commit}),
                    encoding="utf-8")


def _read_dir(folder: Path, settings: dict, station: Optional[str], allow_holdout: bool = False) -> list[list[Reading]]:
    files = sorted(folder.glob("*.csv")) if folder.is_dir() else []
    out = []
    for f in files:
        rows = replay_io.read_readings(f, settings, station, allow_holdout=allow_holdout)
        out.append(sorted(rows, key=lambda r: r.timestamp))
    return out


def load_real(settings: dict, station: Optional[str], include_holdout: bool, data_dir: Optional[Path] = None,
              repo_dir: Optional[Path] = None) -> EvalData:
    root = Path(data_dir or replay_io.data_root(settings))
    clean_files = _read_dir(root / "clean", settings, station)
    if not clean_files:
        raise ValueError(f"No DEV clean data: put CSV files in {root / 'clean'} (see config/protocol.md).")
    allclean = sorted((r for series in clean_files for r in series), key=lambda r: r.timestamp)
    station_id = allclean[0].station_id
    cut = int(len(allclean) * settings["evaluate"]["train_fraction"])
    train, dev_clean = allclean[:cut], allclean[cut:]
    if len(train) < 2 or len(dev_clean) < 2:
        raise ValueError("Not enough clean data to split into train and clean-eval.")
    cadence = float(load_stations().get(station_id, {}).get("cadence_minutes") or
                    np.median([(b.timestamp - a.timestamp).total_seconds() / 60 for a, b in zip(train, train[1:])]))
    dev = SplitData("DEV", [dev_clean], _read_dir(root / "events", settings, station))
    dev.faulted = make_faulted(dev.clean, settings)
    data = EvalData(station_id, train, cadence, dev)
    if include_holdout:
        guard_holdout(settings, repo_dir, root)                # raises HoldoutError, otherwise writes the lock
        hold = SplitData("HOLDOUT", _read_dir(root / "holdout" / "clean", settings, station, allow_holdout=True),
                         _read_dir(root / "holdout" / "events", settings, station, allow_holdout=True))
        hold.faulted = make_faulted(hold.clean, settings)
        data.holdout = hold
    return data


# =====================================================================================================
# Predictors: each takes one series and returns (alarm, weather) per sample
# =====================================================================================================
class _PrecomputedModel:
    """IsolationForest scores for a whole series computed in one go (fast), served to the pipeline."""

    def __init__(self, model: IsolationModel, readings: Sequence[Reading]):
        self.threshold, self.station_id = model.threshold, model.station_id
        scores = model.score(readings)
        self._scores = {(readings[i - 1].timestamp, readings[i].timestamp): scores[i] for i in range(1, len(readings))}

    def score(self, pair: Sequence[Reading]) -> np.ndarray:
        return np.array([np.nan, self._scores.get((pair[0].timestamp, pair[1].timestamp), np.nan)])


def pipeline_predictor(settings: dict, table: NormalityTable, model: IsolationModel, station_id: str,
                       cadence: float) -> Callable[[list[Reading]], list[Prediction]]:
    settings = copy.deepcopy(settings)
    settings["healthscore"]["recompute_every_minutes"] = 10 ** 9      # verdicts do not use the score: skip the slow part

    def predict(readings: list[Reading]) -> list[Prediction]:
        pipe = Pipeline(settings, {station_id: {"cadence_minutes": cadence}}, {station_id: table},
                        {station_id: _PrecomputedModel(model, readings)})
        out = []
        for r in readings:
            v = pipe.process(r).verdict.value
            out.append((v in ALARM_VERDICTS, v == "WEATHER"))
        return out
    return predict


def range_baseline(settings: dict) -> Callable[[list[Reading]], list[Prediction]]:
    def predict(readings: list[Reading]) -> list[Prediction]:
        return [(any(c.flagged for c in physics.check_ranges(r, settings)), False) for r in readings]
    return predict


def range_persistence_baseline(settings: dict, cadence: float) -> Callable[[list[Reading]], list[Prediction]]:
    keep = Pipeline(settings)._history_length(cadence)

    def predict(readings: list[Reading]) -> list[Prediction]:
        out = []
        for i, r in enumerate(readings):
            hist = readings[max(0, i + 1 - keep): i + 1]
            alarm = any(c.flagged for c in physics.check_ranges(r, settings)) or any(
                health.check_frozen(hist, ch, settings, cadence).flagged for ch in CHANNELS)
            out.append((alarm, False))
        return out
    return predict


def isolation_forest_baseline(model: IsolationModel) -> Callable[[list[Reading]], list[Prediction]]:
    def predict(readings: list[Reading]) -> list[Prediction]:
        pre = _PrecomputedModel(model, readings)
        out: list[Prediction] = [(False, False)]
        for i in range(1, len(readings)):
            s = pre.score(readings[i - 1: i + 1])[1]
            out.append((bool(not np.isnan(s) and s < model.threshold), False))
        return out
    return predict


# =====================================================================================================
# Metrics
# =====================================================================================================
@dataclass
class ConfigResult:
    name: str
    kind: str                                          # "full", "ablation" or "baseline"
    detection: dict[str, tuple[int, int]]              # fault type -> (detected, injected)
    clean_alarms: tuple[int, int, int]                 # (alarmed samples, samples, WEATHER samples)
    events_alarms: Optional[tuple[int, int, int]]      # same, or None when there are no event windows


def _count(series_list: list[list[Reading]], predict: Callable) -> tuple[int, int, int]:
    alarms = total = weather = 0
    for series in series_list:
        for alarm, wx in predict(series):
            alarms += alarm
            weather += wx
            total += 1
    return alarms, total, weather


def _detection(faulted: list[tuple[list[Reading], InjectionResult]], predict: Callable, settings: dict,
               cadence: float) -> dict[str, tuple[int, int]]:
    grace = math.ceil(settings["evaluate"]["detection_grace_minutes"] / cadence)
    hits = {t: [0, 0] for t in FAULT_TYPES}
    for readings, res in faulted:
        preds = predict(readings)
        for ev in res.events:
            window = preds[ev.start_index: ev.end_index + 1 + grace]
            hits[ev.fault_type][1] += 1
            hits[ev.fault_type][0] += any(alarm for alarm, _ in window)
    return {t: (d, n) for t, (d, n) in hits.items()}


def evaluate_split(split: SplitData, configs: list[tuple[str, str, Callable]], settings: dict,
                   cadence: float) -> list[ConfigResult]:
    out = []
    for name, kind, predict in configs:
        out.append(ConfigResult(
            name, kind,
            _detection(split.faulted, predict, settings, cadence),
            _count(split.clean, predict),
            _count(split.events, predict) if split.events else None))
    return out


def build_configs(settings: dict, table: NormalityTable, model: IsolationModel, station_id: str,
                  cadence: float) -> list[tuple[str, str, Callable]]:
    configs = [("full", "full", pipeline_predictor(settings, table, model, station_id, cadence))]
    for layer in ABLATED_LAYERS:
        variant = copy.deepcopy(settings)
        variant["layers"][layer] = False
        configs.append((f"no_{layer}", "ablation", pipeline_predictor(variant, table, model, station_id, cadence)))
    configs += [("baseline_range", "baseline", range_baseline(settings)),
                ("baseline_range_persistence", "baseline", range_persistence_baseline(settings, cadence)),
                ("baseline_isolation_forest", "baseline", isolation_forest_baseline(model))]
    return configs


def run_evaluation(settings: dict, data: EvalData) -> dict[str, list[ConfigResult]]:
    """Fit on DEV train only, then score DEV (and HOLDOUT if loaded) with every configuration."""
    table = NormalityTable.fit(data.train, settings)
    model = IsolationModel.fit(data.train, settings)
    configs = build_configs(settings, table, model, data.station_id, data.cadence_minutes)
    results = {data.dev.name: evaluate_split(data.dev, configs, settings, data.cadence_minutes)}
    if data.holdout is not None:
        results[data.holdout.name] = evaluate_split(data.holdout, configs, settings, data.cadence_minutes)
    return results


# =====================================================================================================
# Report: the three numbers are ALWAYS printed
# =====================================================================================================
def pct(a: int, n: int) -> str:
    return "n/a" if n == 0 else f"{100.0 * a / n:.1f}%"


def format_report(results: dict[str, list[ConfigResult]], synthetic: bool, holdout_note: str = "") -> str:
    lines = ["AtmosGuard evaluation", "=" * 78]
    if synthetic:
        lines += ["SYNTHETIC DATA. These numbers only prove the code runs. They say NOTHING about real stations.",
                  "=" * 78]
    for split, rows in results.items():
        w = max(len(r.name) for r in rows) + 2
        lines += ["", f"### {split}", ""]
        lines.append("1) Detection rate per fault type  (alarm = FAULT or SUSPECT, from fault start to end + grace)")
        lines.append(f"   {'config':<{w}}" + "".join(f"{t:>10}" for t in FAULT_TYPES))
        for r in rows:
            lines.append(f"   {r.name:<{w}}" + "".join(f"{pct(*r.detection[t]):>10}" for t in FAULT_TYPES))
        counts = rows[0].detection
        lines.append(f"   {'(faults injected)':<{w}}" + "".join(f"{counts[t][1]:>10}" for t in FAULT_TYPES))
        lines += ["", "2) False-alarm rate on clean data  (no faults injected)",
                  f"   {'config':<{w}}{'rate':>9}{'alarms/samples':>18}{'WEATHER verdicts':>20}"]
        for r in rows:
            a, n, wx = r.clean_alarms
            lines.append(f"   {r.name:<{w}}{pct(a, n):>9}{f'{a}/{n}':>18}{(pct(wx, n) if r.kind != 'baseline' else '-'):>20}")
        label = ("synthetic stand-ins for real extreme-weather windows" if synthetic
                 else "real extreme-weather windows")
        lines += ["", f"3) False-alarm rate on {label}  (no faults injected; WEATHER is a correct verdict here)",
                  f"   {'config':<{w}}{'rate':>9}{'alarms/samples':>18}{'WEATHER verdicts':>20}"]
        for r in rows:
            if r.events_alarms is None:
                lines.append(f"   {r.name:<{w}}{'n/a':>9}{'no event data':>18}{'-':>20}")
            else:
                a, n, wx = r.events_alarms
                lines.append(f"   {r.name:<{w}}{pct(a, n):>9}{f'{a}/{n}':>18}{(pct(wx, n) if r.kind != 'baseline' else '-'):>20}")
    if holdout_note:
        lines += ["", holdout_note]
    lines += ["", "Not ablated: impute (it does not change any verdict), lstm_ae (not built).",
              "No injected fault targets the timing layer yet, so no_timing only shows its effect on false alarms."]
    return "\n".join(lines)


def to_json(results: dict[str, list[ConfigResult]], synthetic: bool) -> str:
    return json.dumps({"synthetic": synthetic, "results": {k: [asdict(r) for r in v] for k, v in results.items()}},
                      indent=2)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate AtmosGuard. See config/protocol.md.")
    ap.add_argument("--synthetic", action="store_true", help="fake data, tests the plumbing only")
    ap.add_argument("--station", help="station id (needed if the CSV files have no station_id column)")
    ap.add_argument("--holdout", action="store_true", help="also score data/holdout (once, guarded)")
    ap.add_argument("--out", type=Path, help="also write the results as JSON")
    args = ap.parse_args(argv)
    settings = load_settings()
    try:
        if args.synthetic:
            data = synthetic_data(settings)
        else:
            data = load_real(settings, args.station, args.holdout)
    except (ValueError, HoldoutError, FileNotFoundError) as e:
        print(f"Cannot evaluate: {e}")
        return 2
    results = run_evaluation(settings, data)
    note = "" if data.holdout is not None else (
        "HOLDOUT: not run. After tuning on DEV and committing config/protocol.md, run once with --holdout.")
    print(format_report(results, data.synthetic, note))
    if args.out:
        args.out.write_text(to_json(results, data.synthetic), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
