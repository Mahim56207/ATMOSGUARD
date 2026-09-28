"""Fusion: verdicts VALID | WEATHER | SUSPECT | FAULT, confidence, plain-English reason text.

Rules run in this order (from the guide):
  1. Physically impossible / frozen / dropout            -> FAULT
  2. One channel jumps while the other two are quiet     -> FAULT
  3. Two or three channels move together, smoothly,
     matching a weather signature                        -> WEATHER (escalate, never suppress)
  4. Unusual but ambiguous                               -> SUSPECT
  5. Otherwise                                           -> VALID
Which checks belong to rule 1 and rule 2, the weather signatures and the confidence numbers all live
in config/settings.yaml (section `fusion`). Confidence is a heuristic score, not a probability.

`Pipeline` runs every enabled layer for a station and calls `fuse`.
"""
from __future__ import annotations

import math
import statistics
import threading
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Sequence

from . import health, healthscore, impute, limits as limits_mod, mlmodel, normality, physics, timing
from .config import layer_enabled, model_path
from .schema import CHANNELS, CheckResult, Reading, Verdict, VerdictResult


def _kind(c: CheckResult) -> str:
    return c.check.split(":")[0]


def _channel(c: CheckResult) -> Optional[str]:
    parts = c.check.split(":")
    return parts[1] if len(parts) > 1 else None


def _recent_change(history: Sequence[Reading], ch: str, window_minutes: float) -> Optional[float]:
    """Newest value minus the latest value that is at least `window_minutes` older."""
    newest = history[-1]
    cur = getattr(newest, ch)
    if cur is None:
        return None
    cutoff = newest.timestamp - timedelta(minutes=window_minutes)
    for r in reversed(history[:-1]):
        if r.timestamp <= cutoff:
            ref = getattr(r, ch)
            return None if ref is None else cur - ref
    return None


def movement(history: Sequence[Reading], cadence_minutes: float, settings: dict) -> dict[str, int]:
    """+1 rising, -1 falling, 0 not moving (or not enough history), per channel."""
    cfg = settings["fusion"]["weather"]
    window = max(cfg["direction_window_minutes"], cadence_minutes)
    out = {}
    for ch in CHANNELS:
        d = _recent_change(history, ch, window)
        out[ch] = 0 if d is None or abs(d) < cfg["min_move"][ch] else (1 if d > 0 else -1)
    return out


def match_signature(moves: dict[str, int], settings: dict) -> Optional[dict]:
    for sig in settings["fusion"]["weather"]["signatures"]:
        needed = {k: v for k, v in sig.items() if k in CHANNELS}
        if all(moves.get(ch) == sign for ch, sign in needed.items()):
            return sig
    return None


def _join(checks: Sequence[CheckResult]) -> str:
    return " ".join(c.reason for c in checks)


def fuse(checks: Sequence[CheckResult], history: Sequence[Reading], settings: dict,
         cadence_minutes: float) -> VerdictResult:
    fcfg = settings["fusion"]
    conf = fcfg["confidence"]
    checks = list(checks)
    info = set(fcfg.get("informational_checks", []))
    notices = [c.reason for c in checks if c.flagged and _kind(c) in info]
    flagged = [c for c in checks if c.flagged and _kind(c) not in info]
    hard = [c for c in flagged if c.severity == "hard"]

    def confidence(base: float, used: Sequence[CheckResult]) -> float:
        used_ids = {id(c) for c in used}
        support = sum(1 for c in flagged if id(c) not in used_ids and c.severity == "soft")
        return round(min(conf["max"], base + conf["bonus_per_supporting_flag"] * support), 3)

    def result(verdict: Verdict, base: float, used: Sequence[CheckResult], reason: str) -> VerdictResult:
        return VerdictResult(verdict=verdict, confidence=confidence(base, used), reason=reason, checks=checks,
                             notices=notices)

    # Rule 1: physically impossible / frozen / dropout
    rule1 = [c for c in hard if _kind(c) in fcfg["fault_checks"]]
    if rule1:
        return result(Verdict.FAULT, conf["fault_rule1"], rule1,
                      "Sensor fault (impossible, frozen or missing value). " + _join(rule1))

    # Rule 2: one channel jumps while the other two are quiet
    jumps = [c for c in hard if _kind(c) in fcfg["jump_checks"]]
    jump_channels = {_channel(c) for c in jumps}
    if len(jump_channels) == 1:
        (jumper,) = jump_channels
        others = [c for c in flagged if _channel(c) not in (None, jumper)]
        if not others:
            return result(Verdict.FAULT, conf["fault_rule2"], jumps,
                          f"Sensor fault: only {jumper} jumped while the other two channels stayed quiet. "
                          + _join(jumps))

    # Rule 3: two or three channels move together, smoothly, matching a weather signature
    if flagged and not hard:
        sig = match_signature(movement(history, cadence_minutes, settings), settings)
        if sig is not None:
            return result(Verdict.WEATHER, conf["weather"], [],
                          f"Likely real weather: {sig['description']}. Several channels are moving together "
                          "smoothly, so this is escalated, not suppressed. " + _join(flagged))

    # Rule 4: unusual but ambiguous
    if flagged:
        return result(Verdict.SUSPECT, conf["suspect"], flagged[:1],
                      "Unusual but not clear enough to call a fault or weather. " + _join(flagged))

    # Rule 5: otherwise valid
    return result(Verdict.VALID, conf["valid"], [], f"All {len(checks)} checks passed.")


class Pipeline:
    """Runs the enabled layers for each station, fuses them, and keeps the state the layers need."""

    def __init__(self, settings: dict, stations: Optional[dict[str, dict]] = None,
                 tables: Optional[dict[str, normality.NormalityTable]] = None,
                 models: Optional[dict[str, mlmodel.IsolationModel]] = None,
                 limits: Optional[dict[str, limits_mod.StationLimits]] = None):
        self.settings = settings
        self.stations = stations or {}
        self.tables = dict(tables or {})
        self.models = dict(models or {})
        self.limits = dict(limits or {})
        self._history: dict[str, deque] = {}
        self._records: dict[str, deque] = {}
        self._health: dict[str, healthscore.HealthReport] = {}
        self._drift: dict[str, healthscore.DriftTracker] = {}
        self._clock: dict[str, tuple] = {}
        self._lock = threading.Lock()

    def load_models(self, station_id: str) -> None:
        """Load the saved normality table and IsolationForest for a station, if the files exist."""
        p = model_path(self.settings, station_id, "normality", ".json")
        if p.exists():
            self.tables[station_id] = normality.NormalityTable.load(p, self.settings)
        p = model_path(self.settings, station_id, "iforest", ".joblib")
        if p.exists():
            self.models[station_id] = mlmodel.IsolationModel.load(p)
        p = model_path(self.settings, station_id, "limits", ".json")
        if p.exists():
            self.limits[station_id] = limits_mod.StationLimits.load(p)

    def cadence_minutes(self, station_id: str) -> float:
        configured = self.stations.get(station_id, {}).get("cadence_minutes")
        if configured:
            return float(configured)
        h = list(self._history.get(station_id, []))
        gaps = [(b.timestamp - a.timestamp).total_seconds() / 60.0 for a, b in zip(h, h[1:])]
        gaps = [g for g in gaps if g > 0]
        if gaps:                                   # one gap is enough: better than a blind default
            return statistics.median(gaps)
        return float(self.settings["pipeline"]["default_cadence_minutes"])

    def _history_length(self, cadence: float, with_clock_window: bool = False,
                        station_limits: Optional[limits_mod.StationLimits] = None) -> int:
        """Samples to keep. The health checks need a few hours (a station-learned frozen window can be longer);
        the clock check (T1) needs a full day."""
        h, w = self.settings["health"], self.settings["fusion"]["weather"]
        minutes = max(*h["frozen"]["window_minutes"].values(), h["noise"]["window_minutes"],
                      h["cusum"]["window_minutes"], w["direction_window_minutes"])
        if station_limits is not None and limits_mod.limits_active(self.settings):
            minutes = max(minutes, station_limits.longest_frozen_window() * h["frozen"].get("hard_multiplier", 1.0))
        if with_clock_window and layer_enabled(self.settings, "timing"):
            minutes = max(minutes, self.settings["timing"]["clock"]["window_minutes"])
        return math.ceil(minutes / cadence) + max(h["frozen"]["min_samples"], h["noise"]["min_samples"]) + 2

    def process(self, reading: Reading, now: Optional[datetime] = None) -> VerdictResult:
        """Run all enabled layers on a new reading and return the fused verdict.
        If anything fails, the reading is taken back out of the history before the error is raised, so one bad
        reading can never break the readings after it."""
        with self._lock:
            sid = reading.station_id
            hist = self._history.setdefault(sid, deque())
            records = self._records.setdefault(sid, deque())
            hist.append(reading)
            n_records = len(records)
            try:
                return self._process(reading, now, sid, hist, records)
            except Exception:
                if hist and hist[-1] is reading:
                    hist.pop()
                while len(records) > n_records and records:
                    records.pop()
                raise

    def _process(self, reading: Reading, now: Optional[datetime], sid: str, hist: deque, records: deque) -> VerdictResult:
        cadence = self.cadence_minutes(sid)
        station_limits = self.limits.get(sid)
        while len(hist) > self._history_length(cadence, with_clock_window=True, station_limits=station_limits):
            hist.popleft()
        full_history = list(hist)
        history = full_history[-self._history_length(cadence, station_limits=station_limits):]   # what the health checks need
        table, model = self.tables.get(sid), self.models.get(sid)

        use_table = table is not None and layer_enabled(self.settings, "normality")
        expected = table.expected_series(history) if use_table else None
        sigma = table.sigma_series(history) if use_table else None
        checks = [*physics.check_physics(reading, self.settings),
                  *health.check_health(history, self.settings, cadence, now=now, expected=expected, sigma=sigma,
                                       limits=station_limits)]
        if layer_enabled(self.settings, "timing"):
            checks += [self._clock_check(sid, full_history, table), timing.check_cojump(history, self.settings, cadence)]
        if table:
            checks += normality.check_normality(reading, table, self.settings)
        if model:
            checks += mlmodel.check_ml(history, model, self.settings)
        verdict = fuse(checks, history, self.settings, cadence)
        verdict = impute.apply_imputation(verdict, impute.impute_reading(reading, verdict, list(records), table,
                                                                         self.settings))

        hrec = healthscore.to_health_record(reading, verdict, self.settings)
        records.append(hrec)
        faulty = hrec.flagged_channels if verdict.verdict == Verdict.FAULT else frozenset()
        self._drift.setdefault(sid, healthscore.DriftTracker(self.settings)).update(reading, table, faulty)
        max_records = math.ceil(self.settings["healthscore"]["window_minutes"] / cadence) + 1
        while len(records) > max_records:
            records.popleft()
        report = self._health.get(sid)
        every = timedelta(minutes=self.settings["healthscore"]["recompute_every_minutes"])
        if report is None or reading.timestamp - report.computed_at >= every:
            report = healthscore.compute_health(sid, records, table, reading.timestamp, self.settings,
                                                self._drift.get(sid), cadence)
            self._health[sid] = report
        return verdict.model_copy(update={"health_score": report.score, "service_date": report.service_date})

    def warm_up(self, readings: Sequence[Reading]) -> int:
        """Feed stored readings through the layers to rebuild the history after a restart. Nothing is stored
        and the verdicts are thrown away. A reading that fails is skipped. Returns how many were used."""
        used = 0
        for r in readings:
            try:
                self.process(r)
                used += 1
            except Exception:
                continue
        return used

    def _clock_check(self, sid: str, full_history: list, table) -> CheckResult:
        """T1 result, recomputed every `timing.clock.recompute_hours` of data time. A wrong clock lasts days, so this only delays a flag."""
        step = timedelta(hours=self.settings["timing"]["clock"]["recompute_hours"])
        now = full_history[-1].timestamp
        cached = self._clock.get(sid)
        if cached is None or now - cached[0] >= step or now < cached[0]:
            cached = (now, timing.check_clock(full_history, table, self.settings))
            self._clock[sid] = cached
        return cached[1]

    def health_report(self, station_id: str, now: Optional[datetime] = None) -> Optional[healthscore.HealthReport]:
        """Fresh health report for a station (None if the station has no readings yet)."""
        with self._lock:
            records = self._records.get(station_id)
            if not records:
                return None
            return healthscore.compute_health(station_id, records, self.tables.get(station_id),
                                              now or records[-1].timestamp, self.settings,
                                              self._drift.get(station_id), self.cadence_minutes(station_id))

    def stations_seen(self) -> list[str]:
        with self._lock:                        # another thread may be adding a station
            return sorted(self._records)
