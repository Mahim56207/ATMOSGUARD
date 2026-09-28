"""L2 normality: station x month x hour statistics and a score.

The table is built from ONE station's readings only (never neighbours). Fit it on clean DEV data.
Month and hour are read straight from the reading timestamp (no time-zone conversion).
Normality flags are SOFT: they can lead to SUSPECT, never to FAULT on their own.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from .config import layer_enabled
from .schema import CHANNELS, CheckResult, Reading


def _key(ts) -> str:
    return f"{ts.month}-{ts.hour}"


class NormalityTable:
    def __init__(self, station_id: str, cells: dict[str, dict[str, dict[str, float]]], settings: dict):
        self.station_id = station_id
        self.cells = cells                    # {"month-hour": {channel: {mean, std, n}}}
        self._min_std = settings["normality"]["min_std"]

    @classmethod
    def fit(cls, readings: Sequence[Reading], settings: dict) -> "NormalityTable":
        stations = {r.station_id for r in readings}
        if len(stations) != 1:
            raise ValueError(f"normality table is single-station, got stations: {sorted(stations)}")
        min_n = settings["normality"]["min_samples_per_cell"]
        values: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for r in readings:
            for ch in CHANNELS:
                v = getattr(r, ch)
                if v is not None:
                    values[_key(r.timestamp)][ch].append(v)
        cells: dict[str, dict[str, dict[str, float]]] = {}
        for key, per_ch in values.items():
            for ch, vals in per_ch.items():
                if len(vals) >= min_n:
                    cells.setdefault(key, {})[ch] = {
                        "mean": float(np.mean(vals)), "std": float(np.std(vals)), "n": len(vals)}
        return cls(stations.pop(), cells, settings)

    def cell(self, ts, ch: str) -> Optional[dict[str, float]]:
        return self.cells.get(_key(ts), {}).get(ch)

    def expected(self, ts, ch: str) -> Optional[float]:
        c = self.cell(ts, ch)
        return None if c is None else c["mean"]

    def z_score(self, reading: Reading, ch: str) -> Optional[float]:
        c, v = self.cell(reading.timestamp, ch), getattr(reading, ch)
        if c is None or v is None:
            return None
        return (v - c["mean"]) / max(c["std"], self._min_std[ch])

    def expected_series(self, history: Sequence[Reading]) -> dict[str, list[Optional[float]]]:
        """Expected value for each reading in `history`. Feeds the CUSUM drift check in health.py."""
        return {ch: [self.expected(r.timestamp, ch) for r in history] for ch in CHANNELS}

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({"station_id": self.station_id, "cells": self.cells}), encoding="utf-8")

    @classmethod
    def load(cls, path: Path, settings: dict) -> "NormalityTable":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(d["station_id"], d["cells"], settings)


def check_normality(reading: Reading, table: NormalityTable, settings: dict) -> list[CheckResult]:
    """One soft CheckResult per channel. Returns [] when the normality layer is off."""
    if not layer_enabled(settings, "normality"):
        return []
    z_flag = settings["normality"]["z_flag"]
    results = []
    for ch in CHANNELS:
        z, c = table.z_score(reading, ch), table.cell(reading.timestamp, ch)
        name = f"normality:{ch}"
        if z is None:
            results.append(CheckResult(check=name, flagged=False, severity="soft",
                                       reason=f"{ch}: no normal range for month {reading.timestamp.month}, "
                                              f"hour {reading.timestamp.hour} (missing value or not enough data)."))
        elif abs(z) > z_flag:
            results.append(CheckResult(
                check=name, flagged=True, severity="soft",
                reason=f"{ch} = {getattr(reading, ch)} is {z:+.1f} standard deviations from the usual "
                       f"{c['mean']:.1f} for month {reading.timestamp.month}, hour {reading.timestamp.hour}."))
        else:
            results.append(CheckResult(check=name, flagged=False, severity="soft",
                                       reason=f"{ch} is within the normal range for this month and hour "
                                              f"(z = {z:+.1f})."))
    return results
