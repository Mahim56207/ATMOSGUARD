"""Fault injection with a ground-truth log. Fixed random seed (settings `seed`).

Fault types come from the L1 checks in the guide: frozen, spike, step, drift, noise, dropout.
The input readings are NEVER changed; faulted copies are returned with a per-sample label and an
event log, so the raw data stays untouched.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from .config import absent_channels
from .schema import CHANNELS, Reading

FAULT_TYPES = ("frozen", "spike", "step", "drift", "noise", "dropout")
# Faults that need a longer record than the six above (and that only the timing layer can see):
#   clock_shift: the logger clock is wrong by a whole number of hours, so every channel carries the value of
#   `injector.clock_shift_hours` earlier. Nothing is out of range and each value is plausible on its own.
EXTRA_FAULT_TYPES = ("clock_shift",)
ALL_FAULT_TYPES = FAULT_TYPES + EXTRA_FAULT_TYPES
ALL_CHANNELS_TAG = "all"           # channel tag for a fault that hits every channel at once


@dataclass
class FaultSpec:
    fault_type: str
    channel: str
    start_index: int


@dataclass
class FaultEvent:
    fault_type: str
    channel: str
    start: str            # ISO timestamp of first affected sample
    end: str              # ISO timestamp of last affected sample
    start_index: int
    end_index: int        # inclusive
    params: dict = field(default_factory=dict)


@dataclass
class InjectionResult:
    readings: list[Reading]           # faulted copies
    labels: list[Optional[str]]       # fault type per sample, None = clean
    events: list[FaultEvent]          # ground-truth log


def _cadence_minutes(readings: list[Reading]) -> float:
    gaps = [(b.timestamp - a.timestamp).total_seconds() / 60.0 for a, b in zip(readings, readings[1:])]
    return statistics.median(gaps)


def _n_samples(fault_type: str, settings: dict, cadence: float) -> int:
    if fault_type == "spike":
        return 1
    return max(1, round(settings["injector"]["duration_minutes"][fault_type] / cadence))


def make_plan(readings: list[Reading], settings: dict, seed: Optional[int] = None,
              types: tuple[str, ...] = FAULT_TYPES, channels: Optional[tuple[str, ...]] = None) -> list[FaultSpec]:
    """Random, non-overlapping fault placement. Same seed -> same plan (for the default six types the plan
    is the same as before `types` existed). `channels` limits the channel a single-channel fault can hit: by default the channels the station has
    (all three unless settings `channels.absent` says otherwise)."""
    if channels is None:
        channels = tuple(ch for ch in CHANNELS if ch not in absent_channels(settings))
    cfg = settings["injector"]
    rng = np.random.default_rng(settings["seed"] if seed is None else seed)
    cadence = _cadence_minutes(readings)
    sep = round(cfg["min_separation_minutes"] / cadence)
    taken: list[tuple[int, int]] = []          # (start, end) inclusive, padded by separation
    plan: list[FaultSpec] = []
    for fault_type in types:
        n = _n_samples(fault_type, settings, cadence)
        placed = 0
        for _ in range(1000):
            if placed >= cfg["events_per_type"]:
                break
            start = int(rng.integers(1, len(readings) - n))
            end = start + n - 1
            if end >= len(readings) or any(start <= b + sep and end >= a - sep for a, b in taken):
                continue
            channel = channels[int(rng.integers(len(channels)))]
            if fault_type in EXTRA_FAULT_TYPES:
                channel = ALL_CHANNELS_TAG
                lag = round(settings["injector"]["clock_shift_hours"] * 60.0 / cadence)
                if start < lag:
                    continue                                  # needs `lag` samples of earlier record to copy from
            taken.append((start, end))
            plan.append(FaultSpec(fault_type, channel, start))
            placed += 1
    return sorted(plan, key=lambda f: f.start_index)


def inject(readings: list[Reading], settings: dict, plan: list[FaultSpec],
           seed: Optional[int] = None) -> InjectionResult:
    """Apply the plan to copies of `readings`. Plan items must not overlap."""
    cfg = settings["injector"]
    rng = np.random.default_rng(settings["seed"] if seed is None else seed)
    cadence = _cadence_minutes(readings)
    out = list(readings)                        # same objects until a sample is replaced by a copy
    labels: list[Optional[str]] = [None] * len(readings)
    events: list[FaultEvent] = []

    for spec in sorted(plan, key=lambda f: f.start_index):
        if spec.fault_type not in ALL_FAULT_TYPES:
            raise ValueError(f"unknown fault type: {spec.fault_type}")
        ch = spec.channel
        if ch not in CHANNELS and not (spec.fault_type in EXTRA_FAULT_TYPES and ch == ALL_CHANNELS_TAG):
            raise ValueError(f"unknown channel: {ch}")
        if not 0 <= spec.start_index < len(readings):
            raise ValueError(f"start_index {spec.start_index} is outside the {len(readings)} readings")
        n = _n_samples(spec.fault_type, settings, cadence)
        s, e = spec.start_index, min(spec.start_index + n, len(readings)) - 1
        params: dict = {}
        if spec.fault_type == "clock_shift":
            lag = round(cfg["clock_shift_hours"] * 60.0 / cadence)
            if s < lag:
                raise ValueError(f"clock_shift at index {s} needs {lag} earlier samples")
            for i in range(s, e + 1):
                if labels[i] is not None:
                    raise ValueError(f"fault at index {i} overlaps another fault")
                src = readings[i - lag]
                out[i] = out[i].model_copy(update={c: getattr(src, c) for c in CHANNELS})
                labels[i] = spec.fault_type
            events.append(FaultEvent("clock_shift", ALL_CHANNELS_TAG, readings[s].timestamp.isoformat(),
                                     readings[e].timestamp.isoformat(), s, e,
                                     {"shift_hours": cfg["clock_shift_hours"]}))
            continue
        hold = getattr(readings[s - 1 if s > 0 else s], ch)
        mag = cfg["magnitude"].get(spec.fault_type, {}).get(ch)
        sign = 1.0 if rng.random() < 0.5 else -1.0
        for k, i in enumerate(range(s, e + 1)):
            if labels[i] is not None:
                raise ValueError(f"fault at index {i} overlaps another fault")
            orig = getattr(readings[i], ch)
            if spec.fault_type == "frozen":
                new = hold
            elif spec.fault_type == "spike":
                new = orig + sign * mag
            elif spec.fault_type == "step":
                new = orig + sign * mag
            elif spec.fault_type == "drift":
                new = orig + sign * mag * (k + 1) / (e - s + 1)
            elif spec.fault_type == "noise":
                new = orig + float(rng.normal(0.0, mag))
            else:  # dropout
                new = None
            out[i] = out[i].model_copy(update={ch: new})
            labels[i] = spec.fault_type
        if spec.fault_type == "frozen":
            params["held_value"] = hold
        elif mag is not None:
            params["magnitude"] = mag
            if spec.fault_type in ("step", "spike", "drift"):
                params["sign"] = sign
        events.append(FaultEvent(spec.fault_type, ch, readings[s].timestamp.isoformat(),
                                 readings[e].timestamp.isoformat(), s, e, params))
    return InjectionResult(out, labels, events)


def write_log(result: InjectionResult, path: Path) -> None:
    """Write the ground-truth event log as JSON."""
    Path(path).write_text(json.dumps([asdict(ev) for ev in result.events], indent=2), encoding="utf-8")
