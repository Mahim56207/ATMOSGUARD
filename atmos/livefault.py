"""Live fault injection for demos and tests: `POST /inject` arms a fault on a station's NEXT readings.

Whatever streams into /ingest (a replay, the fake node, a real ESP32) is altered on the way in, exactly the way a
failing sensor would alter it, and the altered value is what gets stored and judged. That is the point of the demo:
"break the sensor on demand" and watch the verdict, the reason and the health score react.

The offline injector (injector.py) works on a whole dataframe with a ground-truth log; this one works one reading
at a time. Sizes come from the same place (`injector.magnitude` in config/settings.yaml). Fixed seed.
"""
from __future__ import annotations

import itertools
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np

from .schema import CHANNELS, Reading

LIVE_FAULT_TYPES = ("frozen", "spike", "step", "drift", "noise", "dropout")
DEFAULT_SAMPLES = {"frozen": 30, "spike": 1, "step": 30, "drift": 60, "noise": 30, "dropout": 10}


@dataclass
class LiveFault:
    id: int
    station_id: str
    fault_type: str
    channel: str
    samples: int                       # how many readings it lasts
    magnitude: float
    sign: float
    applied: int = 0                   # readings altered so far
    held_value: Optional[float] = None
    started_at: Optional[str] = None

    @property
    def active(self) -> bool:
        return self.applied < self.samples


class LiveInjector:
    def __init__(self, settings: dict):
        self._settings = settings
        self._seed = settings["seed"]
        self._rng = np.random.default_rng(self._seed)
        self._faults: list[LiveFault] = []
        self._last: dict[tuple[str, str], Optional[float]] = {}     # (station, channel) -> last value seen, unaltered
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def add(self, station_id: str, fault_type: str, channel: str, samples: Optional[int] = None,
            magnitude: Optional[float] = None) -> LiveFault:
        if fault_type not in LIVE_FAULT_TYPES:
            raise ValueError(f"unknown fault type {fault_type!r}; choose from {', '.join(LIVE_FAULT_TYPES)}")
        if channel not in CHANNELS:
            raise ValueError(f"unknown channel {channel!r}; choose from {', '.join(CHANNELS)}")
        n = int(samples or DEFAULT_SAMPLES[fault_type])
        if n < 1:
            raise ValueError("samples must be at least 1")
        mags = self._settings["injector"]["magnitude"].get(fault_type, {})
        mag = float(magnitude) if magnitude is not None else float(mags.get(channel, 0.0))
        with self._lock:
            sign = 1.0 if self._rng.random() < 0.5 else -1.0
            fault = LiveFault(next(self._ids), station_id, fault_type, channel, n, mag, sign)
            self._faults.append(fault)
            return fault

    def apply(self, reading: Reading) -> Reading:
        """The reading as the failing sensor would have sent it. Unchanged if nothing is armed for its station."""
        with self._lock:
            sid = reading.station_id
            update: dict[str, Optional[float]] = {}
            for f in self._faults:
                if f.station_id != sid or not f.active:
                    continue
                current = update.get(f.channel, getattr(reading, f.channel))
                if current is None and f.fault_type != "dropout":
                    continue                                          # nothing to alter: the value is already missing
                if f.fault_type == "frozen":
                    if f.held_value is None:
                        prev = self._last.get((sid, f.channel))
                        f.held_value = prev if prev is not None else current
                    new = f.held_value
                elif f.fault_type == "spike":
                    new = current + f.sign * f.magnitude
                elif f.fault_type == "step":
                    new = current + f.sign * f.magnitude
                elif f.fault_type == "drift":
                    new = current + f.sign * f.magnitude * (f.applied + 1) / f.samples
                elif f.fault_type == "noise":
                    new = current + float(self._rng.normal(0.0, f.magnitude))
                else:                                                 # dropout
                    new = None
                if f.started_at is None:
                    f.started_at = reading.timestamp.isoformat()
                f.applied += 1
                update[f.channel] = new
            for ch in CHANNELS:                                       # remember the unaltered value for `frozen`
                v = getattr(reading, ch)
                if v is not None:
                    self._last[(sid, ch)] = v
            return reading.model_copy(update=update) if update else reading

    def clear(self, station_id: Optional[str] = None) -> int:
        with self._lock:
            keep = [f for f in self._faults if station_id is not None and f.station_id != station_id]
            removed = len(self._faults) - len(keep)
            self._faults = keep
            return removed

    def list(self) -> list[dict]:
        with self._lock:
            return [{**asdict(f), "active": f.active} for f in self._faults]

    def any_active(self) -> bool:
        with self._lock:
            return any(f.active for f in self._faults)
