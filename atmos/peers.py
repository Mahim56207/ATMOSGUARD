"""Optional peer layer: a constant offset or a slow drift that one station cannot see on its own.

One station, judged only against its own history, has no way to notice that all its pressures are 1 hPa high from the day it was
installed: the offset is part of its "normal". Neighbouring stations weather the same synoptic systems, so the DEPARTURE of a
station from its own normal moves with the departures of its neighbours. If it stops doing so, and stays apart, the sensor has moved.

    anomaly(station, channel) = reading - the station's own expected value (its month x hour normal, atmos.normality)
    difference                = own anomaly - median of the neighbours' anomalies at the same time
    alarm                     = the 7-day mean of the difference is beyond what the station's own clean training years ever produced

Working with anomalies removes elevation and local climate, so neighbours need not be alike. It needs at least `min_peers` neighbours with
a valid reading; without them the layer says nothing. It is a network feature: the core pipeline stays single-station (the problem
statement's setting), and this layer is off unless a deployment supplies neighbours (`peers:` in config/settings.yaml, the `/peers` endpoint).

Everything here is pandas/numpy on aligned hourly series; nothing is learned except one threshold per station and channel.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from .schema import CHANNELS


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def neighbours(coords: dict[str, tuple[float, float]], station: str, radius_km: float) -> list[str]:
    """Stations within `radius_km` of `station`, nearest first."""
    lat, lon = coords[station]
    found = [(haversine_km(lat, lon, *c), sid) for sid, c in coords.items() if sid != station]
    return [sid for d, sid in sorted(found) if d <= radius_km]


def peer_difference(anomalies: dict[str, pd.Series], station: str, peers: list[str], min_peers: int = 3) -> pd.Series:
    """Own anomaly minus the median of the peers' anomalies, at the timestamps where at least `min_peers` peers have a value."""
    own = anomalies[station]
    if len(peers) < min_peers:
        return pd.Series(np.nan, index=own.index)
    stack = pd.concat([anomalies[p].reindex(own.index) for p in peers], axis=1)
    ok = stack.notna().sum(axis=1) >= min_peers
    med = stack.median(axis=1).where(ok)
    return own - med


def rolling_mean(x: pd.Series, window_hours: int, min_fraction: float = 0.6) -> pd.Series:
    return x.rolling(window_hours, min_periods=max(2, int(window_hours * min_fraction))).mean()


@dataclass
class PeerLimit:
    threshold: float                  # alarm when |rolling mean of the difference| exceeds this (channel units)
    n_train_windows: int


def fit_limit(diff_train: pd.Series, window_hours: int = 168, quantile: float = 0.999, margin: float = 1.2,
              min_windows: int = 500) -> Optional[PeerLimit]:
    """The threshold is the largest 7-day mean difference the station's clean training years produced (a high quantile), with a margin,
    the same construction as the station-learned limits in atmos/limits.py. None if the training data are too thin."""
    r = rolling_mean(diff_train, window_hours).abs().dropna()
    if len(r) < min_windows:
        return None
    return PeerLimit(float(np.quantile(r, quantile)) * margin, int(len(r)))


def offset_alarm(diff: pd.Series, limit: PeerLimit, window_hours: int = 168) -> pd.Series:
    """Boolean series: the rolling mean of the difference is beyond the station's limit."""
    return rolling_mean(diff, window_hours).abs() > limit.threshold


def own_anomalies(readings: pd.DataFrame, table, index: pd.DatetimeIndex) -> dict[str, pd.Series]:
    """Anomalies of every channel of one station against its own normality table, on a regular `index` (missing = NaN)."""
    df = readings.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.drop_duplicates("timestamp").set_index("timestamp").reindex(index)
    out = {}
    for ch in CHANNELS:
        exp = np.array([np.nan if (e := _expected(table, ts, ch)) is None else e for ts in index], dtype=float)
        out[ch] = df[ch].astype(float) - pd.Series(exp, index=index)
    return out


def _expected(table, ts, ch: str) -> Optional[float]:
    """The smooth expected value (no month-boundary steps) where the table has it, else the plain cell mean."""
    e = table.smooth_expected(ts, ch)
    return e if e is not None else table.expected(ts, ch)
