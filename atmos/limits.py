"""Station-learned limits for the two checks that depend on how the station reports its numbers.

Why this exists: the fixed frozen and noise limits in config/settings.yaml were tuned on synthetic data with fine
resolution. Real stations report rounded numbers (Indian METAR: whole degC, whole hPa). A rounded channel repeats
the same value for hours in perfectly normal weather, and a humidity value derived from two rounded numbers
jumps in steps. With the fixed limits, real clean data got alarms on about two thirds of its samples.

The guide already says "prefer limits derived from each station's own history". This module does that for:
  * frozen: the longest run of identical values that clean weather produces. A stuck sensor has to beat it.
  * noise:  the largest jitter estimate that clean weather produces (same estimator as health.check_noise).
Both come from an upper quantile of the CLEAN training data, so how often a clean station crosses them is set by
the quantile, not by a guess. The configured value stays as the floor: the learned limit can only make a check
less trigger-happy, never more.

Fit on clean DEV training data only. Toggle with `layers.limits`. Limits live in `settings["limits"]`.
"""
from __future__ import annotations

import json
import math
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from .config import layer_enabled
from .schema import CHANNELS, Reading


@dataclass
class ChannelLimits:
    resolution: Optional[float] = None       # detected reporting step (e.g. 1.0 = whole numbers); None = fine
    frozen_minutes: Optional[float] = None   # learned longest normal run of identical values
    noise_std: Optional[float] = None        # learned largest normal jitter estimate
    typical_step: Optional[float] = None     # 75th percentile of |change| between consecutive readings (the usual step)
    n_runs: int = 0                          # how many runs the frozen limit is based on


@dataclass
class StationLimits:
    station_id: str
    cadence_minutes: float
    channels: dict[str, ChannelLimits] = field(default_factory=dict)

    # ---- lookups used by health.py ------------------------------------------------------------------
    def frozen_minutes(self, ch: str) -> Optional[float]:
        c = self.channels.get(ch)
        return None if c is None else c.frozen_minutes

    def noise_std(self, ch: str) -> Optional[float]:
        c = self.channels.get(ch)
        return None if c is None else c.noise_std

    def typical_step(self, ch: str) -> Optional[float]:
        c = self.channels.get(ch)
        return None if c is None else c.typical_step

    def longest_frozen_window(self) -> float:
        return max((c.frozen_minutes or 0.0 for c in self.channels.values()), default=0.0)

    # ---- persistence --------------------------------------------------------------------------------
    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(asdict(self), indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "StationLimits":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(d["station_id"], d["cadence_minutes"],
                   {ch: ChannelLimits(**c) for ch, c in d["channels"].items()})


def detect_resolution(values: Sequence[float]) -> Optional[float]:
    """The reporting step of a channel: 1.0 if (almost) all values are whole numbers, 0.5 for halves,
    0.1 for tenths. None if the values are finer than that (e.g. a derived humidity)."""
    v = np.asarray([x for x in values if x is not None], dtype=float)
    if v.size < 50:
        return None
    for step in (1.0, 0.5, 0.1):
        if np.mean(np.abs(v / step - np.round(v / step)) < 1e-6) > 0.98:
            return step
    return None


def _runs(readings: Sequence[Reading], ch: str, epsilon: float, gap_limit_minutes: float) -> list[float]:
    """Durations (minutes, first to last sample) of runs of identical values that hold at least 2 samples.
    A missing value or a time gap ends a run."""
    out: list[float] = []
    start: Optional[Reading] = None
    last: Optional[Reading] = None
    anchor: Optional[float] = None
    for r in readings:
        v = getattr(r, ch)
        if v is None:
            if start is not None and last is not start:
                out.append((last.timestamp - start.timestamp).total_seconds() / 60.0)
            start = last = anchor = None
            continue
        gap = (r.timestamp - last.timestamp).total_seconds() / 60.0 if last is not None else 0.0
        if start is not None and gap <= gap_limit_minutes and abs(v - anchor) <= epsilon:
            last = r
            continue
        if start is not None and last is not start:
            out.append((last.timestamp - start.timestamp).total_seconds() / 60.0)
        start = last = r
        anchor = v
    if start is not None and last is not start:
        out.append((last.timestamp - start.timestamp).total_seconds() / 60.0)
    return out


def usual_step(readings: Sequence[Reading], ch: str, gap_limit_minutes: float, cadence_minutes: float,
               percentile: float = 75.0) -> Optional[float]:
    """The usual change of `ch` between two consecutive readings one cadence apart (a percentile of |change|).
    Channels differ and cadences differ (temperature moves about 1 C between hourly readings and 3 C between
    3-hourly ones), which is why "the other channel is quiet" has to be judged against this and not a fixed number."""
    d = []
    for a, b in zip(readings, readings[1:]):
        va, vb = getattr(a, ch), getattr(b, ch)
        dt = (b.timestamp - a.timestamp).total_seconds() / 60.0
        if va is None or vb is None or dt <= 0 or dt > 1.5 * cadence_minutes or dt > gap_limit_minutes:
            continue
        d.append(abs(vb - va))
    return float(np.percentile(d, percentile)) if len(d) >= 200 else None


def noise_estimates(readings: Sequence[Reading], ch: str, window_minutes: float, min_samples: int,
                    cadence_minutes: float) -> list[float]:
    """The same jitter estimate health.check_noise gives, for every sample that has a full window behind it.
    Second differences cancel a smooth trend; for independent noise of std s their RMS is s * sqrt(6)."""
    window = max(window_minutes, (min_samples - 1) * cadence_minutes)
    out: list[float] = []
    for i in range(len(readings)):
        cutoff = readings[i].timestamp.timestamp() - window * 60.0
        j = i
        while j > 0 and readings[j - 1].timestamp.timestamp() >= cutoff:
            j -= 1
        vals = [getattr(r, ch) for r in readings[j:i + 1]]
        if len(vals) < min_samples or any(v is None for v in vals):
            continue
        second = [vals[k + 2] - 2 * vals[k + 1] + vals[k] for k in range(len(vals) - 2)]
        out.append(math.sqrt(sum(d * d for d in second) / len(second) / 6.0))
    return out


def fit_limits(readings: Sequence[Reading], settings: dict, cadence_minutes: Optional[float] = None) -> StationLimits:
    """Learn the frozen-run and noise ceilings from clean readings of ONE station, oldest first."""
    stations = {r.station_id for r in readings}
    if len(stations) != 1:
        raise ValueError(f"limits are single-station, got stations: {sorted(stations)}")
    cfg = settings["limits"]
    hcfg = settings["health"]
    if cadence_minutes is None:
        gaps = [(b.timestamp - a.timestamp).total_seconds() / 60.0 for a, b in zip(readings, readings[1:])]
        cadence_minutes = statistics.median(g for g in gaps if g > 0)
    gap_limit = hcfg["gaps"]["gap_cadence_multiplier"] * cadence_minutes
    out = StationLimits(stations.pop(), float(cadence_minutes))
    for ch in CHANNELS:
        lim = ChannelLimits(resolution=detect_resolution([getattr(r, ch) for r in readings]))
        runs = _runs(readings, ch, hcfg["frozen"]["epsilon"][ch], gap_limit)
        lim.n_runs = len(runs)
        lim.typical_step = usual_step(readings, ch, gap_limit, cadence_minutes)
        if len(runs) >= cfg["min_runs"]:
            lim.frozen_minutes = float(np.quantile(runs, cfg["frozen_quantile"])) * cfg["frozen_margin"]
        noise = noise_estimates(readings, ch, hcfg["noise"]["window_minutes"], hcfg["noise"]["min_samples"],
                                cadence_minutes)
        if len(noise) >= cfg["min_noise_samples"]:
            lim.noise_std = float(np.quantile(noise, cfg["noise_quantile"])) * cfg["noise_margin"]
        out.channels[ch] = lim
    return out


def limits_active(settings: dict) -> bool:
    return layer_enabled(settings, "limits")
