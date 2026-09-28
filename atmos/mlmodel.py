"""L3 ML: one IsolationForest per station (+ optional LSTM-AE behind a flag).

Features per reading: the 3 values, the 3 rates of change per minute (vs the previous reading), and
the hour of day as sin/cos. Rates are per minute so the model is comparable across cadences.
Fit on clean DEV data only. The alarm level is a quantile of the clean training scores.
ML flags are SOFT: they can lead to SUSPECT, never to FAULT on their own.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional, Sequence

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

from .config import layer_enabled
from .schema import CHANNELS, CheckResult, Reading

_FLOAT32_MAX = float(np.finfo(np.float32).max)

FEATURE_NAMES = (*CHANNELS, *(f"d_{c}_per_min" for c in CHANNELS), "hour_sin", "hour_cos")


def build_features(readings: Sequence[Reading]) -> tuple[np.ndarray, np.ndarray]:
    """Return (X, usable). Row i uses readings[i-1] for the rates. Unusable rows are zeros:
    the first reading, missing values, or a non-increasing timestamp."""
    X = np.zeros((len(readings), len(FEATURE_NAMES)))
    usable = np.zeros(len(readings), dtype=bool)
    for i in range(1, len(readings)):
        cur, prev = readings[i], readings[i - 1]
        dt = (cur.timestamp - prev.timestamp).total_seconds() / 60.0
        vals = [getattr(cur, c) for c in CHANNELS]
        pvals = [getattr(prev, c) for c in CHANNELS]
        if dt <= 0 or None in vals or None in pvals:
            continue
        angle = 2 * math.pi * (cur.timestamp.hour + cur.timestamp.minute / 60.0) / 24.0
        row = [*vals, *((v - p) / dt for v, p in zip(vals, pvals)), math.sin(angle), math.cos(angle)]
        if all(abs(x) < _FLOAT32_MAX for x in row):          # the forest works in float32: absurd values are skipped
            X[i] = row
            usable[i] = True
    return X, usable


class IsolationModel:
    def __init__(self, station_id: str, forest: IsolationForest, threshold: float):
        self.station_id = station_id
        self.forest = forest
        self.threshold = threshold            # flag when score < threshold (lower = more unusual)

    @classmethod
    def fit(cls, readings: Sequence[Reading], settings: dict) -> "IsolationModel":
        stations = {r.station_id for r in readings}
        if len(stations) != 1:
            raise ValueError(f"model is single-station, got stations: {sorted(stations)}")
        X, usable = build_features(readings)
        if usable.sum() == 0:
            raise ValueError("no usable rows to train on")
        forest = IsolationForest(n_estimators=settings["mlmodel"]["n_estimators"],
                                 random_state=settings["seed"], n_jobs=1)
        forest.fit(X[usable])
        scores = forest.decision_function(X[usable])
        threshold = float(np.quantile(scores, settings["mlmodel"]["threshold_quantile"]))
        return cls(stations.pop(), forest, threshold)

    def score(self, readings: Sequence[Reading]) -> np.ndarray:
        """Score per reading (NaN where unusable). Lower = more unusual."""
        X, usable = build_features(readings)
        out = np.full(len(readings), np.nan)
        if usable.any():
            out[usable] = self.forest.decision_function(X[usable])
        return out

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"station_id": self.station_id, "forest": self.forest, "threshold": self.threshold}, path)

    @classmethod
    def load(cls, path: Path) -> "IsolationModel":
        d = joblib.load(path)
        return cls(d["station_id"], d["forest"], d["threshold"])


# ---------------------------------------------------------------------------------------------------
# Mahalanobis distance: the station's own covariance of (departure from normal, rate of change)
# ---------------------------------------------------------------------------------------------------
MAHAL_FEATURES = ("temperature_c departure", "pressure_hpa departure", "humidity_pct departure",
                  "temperature_c change/min", "pressure_hpa change/min", "humidity_pct change/min")


def mahalanobis_features(readings: Sequence[Reading], table) -> tuple[np.ndarray, np.ndarray]:
    """Row i: how far each channel is from this station's smooth expected value, and how fast each moved since the
    previous reading (per minute). Without a normality table the raw values are used instead of the departures.
    Unusable rows (first reading, missing values, non-increasing time, no expected value) are zeros."""
    X, usable = build_features(readings)
    out = np.zeros((len(readings), 6))
    ok = usable.copy()
    for i in np.nonzero(usable)[0]:
        vals = X[i, :3]
        if table is not None:
            exp = [table.smooth_expected(readings[i].timestamp, ch) for ch in CHANNELS]
            if any(e is None for e in exp):
                ok[i] = False
                continue
            vals = vals - np.array(exp)
        out[i, :3] = vals
        out[i, 3:] = X[i, 3:6]
    return out, ok


class MahalanobisModel:
    """Distance of (departures, rates) from the station's clean-history centre, in units set by its own covariance.
    Catches a mix that no single channel's limit sees (a level shift of a few degrees, a jump that fits no weather).
    Explains itself: the channel and the feature that contribute most to the distance."""

    def __init__(self, station_id: str, mean: np.ndarray, inv_cov: np.ndarray, threshold: float,
                 uses_table: bool = False):
        self.station_id, self.mean, self.inv_cov, self.threshold = station_id, mean, inv_cov, threshold
        self.uses_table = uses_table          # trained on departures from a normality table: it needs that table to run

    @classmethod
    def fit(cls, readings: Sequence[Reading], settings: dict, table=None) -> "MahalanobisModel":
        stations = {r.station_id for r in readings}
        if len(stations) != 1:
            raise ValueError(f"model is single-station, got stations: {sorted(stations)}")
        X, ok = mahalanobis_features(readings, table)
        X = X[ok]
        if len(X) < 50:
            raise ValueError("not enough usable rows to fit the Mahalanobis model")
        mean = X.mean(axis=0)
        cov = np.cov(X, rowvar=False) + settings["mlmodel"]["mahalanobis"]["ridge"] * np.eye(6)
        model = cls(stations.pop(), mean, np.linalg.inv(cov), 0.0, uses_table=table is not None)
        d2 = model._d2(X)
        model.threshold = float(np.quantile(d2, settings["mlmodel"]["mahalanobis"]["quantile"]))
        return model

    def _d2(self, X: np.ndarray) -> np.ndarray:
        D = X - self.mean
        return np.einsum("ij,jk,ik->i", D, self.inv_cov, D)

    def distance2(self, readings: Sequence[Reading], table=None) -> np.ndarray:
        X, ok = mahalanobis_features(readings, table)
        out = np.full(len(readings), np.nan)
        if ok.any():
            out[ok] = self._d2(X[ok])
        return out

    def explain(self, readings: Sequence[Reading], table=None) -> tuple[float, str]:
        """(squared distance of the newest reading, name of the feature contributing most)."""
        X, ok = mahalanobis_features(readings[-2:], table)
        if not ok[-1]:
            return float("nan"), ""
        D = X[-1] - self.mean
        contrib = D * (self.inv_cov @ D)
        return float(contrib.sum()), MAHAL_FEATURES[int(np.argmax(contrib))]

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"station_id": self.station_id, "mean": self.mean, "inv_cov": self.inv_cov,
                     "threshold": self.threshold, "uses_table": self.uses_table}, path)

    @classmethod
    def load(cls, path: Path) -> "MahalanobisModel":
        d = joblib.load(path)
        return cls(d["station_id"], d["mean"], d["inv_cov"], d["threshold"], d.get("uses_table", False))


def check_mahalanobis(history: Sequence[Reading], model: MahalanobisModel, table, settings: dict) -> list[CheckResult]:
    """Judge the newest reading. SOFT flag: it can lead to SUSPECT or WEATHER, never FAULT on its own."""
    if not layer_enabled(settings, "mahalanobis"):
        return []
    if model.uses_table and table is None:
        return [CheckResult(check="mahalanobis", flagged=False, severity="soft",
                            reason="Mahalanobis distance not run: this model needs the station's normality table.")]
    if len(history) < 2:
        return [CheckResult(check="mahalanobis", flagged=False, severity="soft",
                            reason="Mahalanobis distance not run: needs two consecutive readings.")]
    d2, feature = model.explain(history, table)
    if math.isnan(d2):
        return [CheckResult(check="mahalanobis", flagged=False, severity="soft",
                            reason="Mahalanobis distance not run: needs two consecutive readings with all three values "
                                   "and a normal value for this month and hour.")]
    if d2 > model.threshold:
        return [CheckResult(check="mahalanobis", flagged=True, severity="soft",
                            reason=f"The mix of departures from normal and rates of change is unusual for this station "
                                   f"(distance^2 {d2:.1f}, limit {model.threshold:.1f}); the {feature} contributes most.")]
    return [CheckResult(check="mahalanobis", flagged=False, severity="soft",
                        reason=f"The mix of departures and rates of change is within this station's normal "
                               f"(distance^2 {d2:.1f}, limit {model.threshold:.1f}).")]


def check_lstm_ae(history: Sequence[Reading], settings: dict) -> CheckResult:
    raise NotImplementedError("LSTM autoencoder is optional and not built yet (layers.lstm_ae).")


def check_ml(history: Sequence[Reading], model: IsolationModel, settings: dict) -> list[CheckResult]:
    """Judge the newest reading. Returns [] when the ML layer is off."""
    if not layer_enabled(settings, "mlmodel"):
        return []
    results = []
    score: Optional[float] = None
    if len(history) >= 2:
        s = model.score(history[-2:])[1]
        score = None if np.isnan(s) else float(s)
    if score is None:
        results.append(CheckResult(check="isolation_forest", flagged=False, severity="soft",
                                   reason="Isolation Forest not run: needs two consecutive readings with all "
                                          "three values."))
    elif score < model.threshold:
        results.append(CheckResult(
            check="isolation_forest", flagged=True, severity="soft",
            reason=f"Isolation Forest score {score:.3f} is below this station's normal limit "
                   f"{model.threshold:.3f}: the mix of values and their change is unusual."))
    else:
        results.append(CheckResult(check="isolation_forest", flagged=False, severity="soft",
                                   reason=f"Isolation Forest score {score:.3f} is inside this station's normal "
                                          f"limit ({model.threshold:.3f})."))
    if layer_enabled(settings, "lstm_ae"):
        results.append(check_lstm_ae(history, settings))
    return results
