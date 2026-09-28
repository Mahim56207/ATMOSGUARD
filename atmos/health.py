"""L1 sensor health: frozen, step/spike, CUSUM drift, noise, gaps, timestamps.

`history` is a list of Reading for ONE station, oldest first, newest LAST. Checks judge the newest
reading. All windows are in minutes and scale with `cadence_minutes`, so the same code runs on
1-minute, 15-minute and hourly data. Limits come from config/settings.yaml (section `health`).
Every check returns a CheckResult with a reason string. Toggle with `layers.health`.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Optional, Sequence

from .config import layer_enabled
from .schema import CHANNELS, CheckResult, Reading


def _minutes(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 60.0


def _window(history: Sequence[Reading], minutes: float) -> list[Reading]:
    """Readings whose timestamp is within `minutes` of the newest one (newest included)."""
    cutoff = history[-1].timestamp - timedelta(minutes=minutes)
    return [r for r in history if r.timestamp >= cutoff]


def _allowed_step(ch: str, minutes_apart: float, settings: dict) -> float:
    cfg = settings["health"]["step"]
    return min(cfg["rate_per_min"][ch] * minutes_apart, cfg["cap"][ch])


def _gap_limit_minutes(settings: dict, cadence_minutes: float) -> float:
    return settings["health"]["gaps"]["gap_cadence_multiplier"] * cadence_minutes


def check_frozen(history: Sequence[Reading], ch: str, settings: dict, cadence_minutes: float) -> CheckResult:
    cfg = settings["health"]["frozen"]
    window_min = max(cfg["window_minutes"][ch], (cfg["min_samples"] - 1) * cadence_minutes)
    name = f"frozen:{ch}"
    if _minutes(history[0].timestamp, history[-1].timestamp) < window_min:
        return CheckResult(check=name, flagged=False,
                           reason=f"{ch}: not enough history yet to judge a frozen value ({window_min:g} min needed).")
    values = [getattr(r, ch) for r in _window(history, window_min)]
    if any(v is None for v in values) or len(values) < cfg["min_samples"]:
        return CheckResult(check=name, flagged=False,
                           reason=f"{ch}: missing values or too few samples in the last {window_min:g} min, frozen check skipped.")
    spread = max(values) - min(values)
    if spread <= cfg["epsilon"][ch]:
        return CheckResult(check=name, flagged=True,
                           reason=f"{ch} has not changed for {window_min:g} min (stuck at {values[-1]}).")
    return CheckResult(check=name, flagged=False,
                       reason=f"{ch} changed by {spread:g} in the last {window_min:g} min, so it is not frozen.")


def check_step(history: Sequence[Reading], ch: str, settings: dict, cadence_minutes: float) -> CheckResult:
    name = f"step:{ch}"
    if len(history) < 2:
        return CheckResult(check=name, flagged=False, reason=f"{ch}: only one reading, no step to check.")
    prev, cur = history[-2], history[-1]
    a, b = getattr(prev, ch), getattr(cur, ch)
    dt = _minutes(prev.timestamp, cur.timestamp)
    if a is None or b is None or dt <= 0:
        return CheckResult(check=name, flagged=False,
                           reason=f"{ch}: missing value or bad timestamp order, step check skipped.")
    if dt > _gap_limit_minutes(settings, cadence_minutes):
        return CheckResult(check=name, flagged=False,
                           reason=f"{ch}: {dt:g} min since the last reading is a gap, so a step cannot be judged.")
    allowed = _allowed_step(ch, dt, settings)
    delta = b - a
    if abs(delta) > allowed:
        return CheckResult(check=name, flagged=True,
                           reason=f"{ch} jumped by {delta:+g} in {dt:g} min (allowed {allowed:g}).")
    return CheckResult(check=name, flagged=False,
                       reason=f"{ch} changed by {delta:+g} in {dt:g} min (allowed {allowed:g}).")


def check_spike(history: Sequence[Reading], ch: str, settings: dict, cadence_minutes: float) -> CheckResult:
    """A one-sample excursion: the PREVIOUS reading jumped away and the newest jumped back."""
    name = f"spike:{ch}"
    if len(history) < 3:
        return CheckResult(check=name, flagged=False, reason=f"{ch}: fewer than 3 readings, no spike check.")
    r0, r1, r2 = history[-3], history[-2], history[-1]
    a, b, c = getattr(r0, ch), getattr(r1, ch), getattr(r2, ch)
    dt1, dt2 = _minutes(r0.timestamp, r1.timestamp), _minutes(r1.timestamp, r2.timestamp)
    gap = _gap_limit_minutes(settings, cadence_minutes)
    if None in (a, b, c) or dt1 <= 0 or dt2 <= 0 or dt1 > gap or dt2 > gap:
        return CheckResult(check=name, flagged=False,
                           reason=f"{ch}: missing value, gap or bad timestamp order, spike check skipped.")
    d1, d2 = b - a, c - b
    jumped_out = abs(d1) > _allowed_step(ch, dt1, settings)
    jumped_back = abs(d2) > _allowed_step(ch, dt2, settings)
    net_small = abs(c - a) <= _allowed_step(ch, dt1 + dt2, settings)
    if jumped_out and jumped_back and d1 * d2 < 0 and net_small:
        return CheckResult(check=name, flagged=True,
                           reason=f"{ch} at {r1.timestamp.isoformat()} was a one-sample spike "
                                  f"({a} -> {b} -> {c}).")
    return CheckResult(check=name, flagged=False, reason=f"{ch}: no one-sample spike ({a} -> {b} -> {c}).")


def check_noise(history: Sequence[Reading], ch: str, settings: dict, cadence_minutes: float) -> CheckResult:
    """Jitter check. Noise is estimated from SECOND differences, which cancel a smooth trend (a front or a
    diurnal ramp is not noise). For independent noise of std s, the second differences have RMS s * sqrt(6)."""
    cfg = settings["health"]["noise"]
    window_min = max(cfg["window_minutes"], (cfg["min_samples"] - 1) * cadence_minutes)
    name = f"noise:{ch}"
    values = [getattr(r, ch) for r in _window(history, window_min)]
    if any(v is None for v in values) or len(values) < cfg["min_samples"]:
        return CheckResult(check=name, flagged=False,
                           reason=f"{ch}: not enough complete samples in the last {window_min:g} min for a noise check.")
    second = [values[i + 2] - 2 * values[i + 1] + values[i] for i in range(len(values) - 2)]
    noise = math.sqrt(sum(d * d for d in second) / len(second) / 6.0)
    limit = cfg["max_noise_std"][ch]
    if noise > limit:
        return CheckResult(check=name, flagged=True,
                           reason=f"{ch} is too noisy: estimated jitter {noise:.3g} is above {limit:g} "
                                  f"over {window_min:g} min.")
    return CheckResult(check=name, flagged=False,
                       reason=f"{ch} jitter {noise:.3g} is within the limit of {limit:g}.")


def check_dropout(history: Sequence[Reading]) -> CheckResult:
    missing = [ch for ch in CHANNELS if getattr(history[-1], ch) is None]
    if missing:
        return CheckResult(check="dropout", flagged=True,
                           reason=f"No value received for: {', '.join(missing)}.")
    return CheckResult(check="dropout", flagged=False, reason="All three channels have a value.")


def check_gap(history: Sequence[Reading], settings: dict, cadence_minutes: float) -> CheckResult:
    if len(history) < 2:
        return CheckResult(check="gap", flagged=False, reason="Only one reading, no gap to check.")
    dt = _minutes(history[-2].timestamp, history[-1].timestamp)
    limit = _gap_limit_minutes(settings, cadence_minutes)
    if dt > limit:
        return CheckResult(check="gap", flagged=True,
                           reason=f"{dt:g} min since the last reading; the station reports every "
                                  f"{cadence_minutes:g} min (gap limit {limit:g} min).")
    return CheckResult(check="gap", flagged=False, reason=f"{dt:g} min since the last reading, no gap.")


def check_timestamp(history: Sequence[Reading], settings: dict, now: Optional[datetime] = None) -> CheckResult:
    cur = history[-1].timestamp
    if len(history) >= 2 and cur <= history[-2].timestamp:
        kind = "duplicate" if cur == history[-2].timestamp else "out-of-order"
        return CheckResult(check="timestamp", flagged=True,
                           reason=f"Timestamp {cur.isoformat()} is {kind} (previous was "
                                  f"{history[-2].timestamp.isoformat()}).")
    if now is not None:
        tol = settings["health"]["timestamps"]["future_tolerance_minutes"]
        if cur > now + timedelta(minutes=tol):
            return CheckResult(check="timestamp", flagged=True,
                               reason=f"Timestamp {cur.isoformat()} is more than {tol} min ahead of the "
                                      "server clock.")
    return CheckResult(check="timestamp", flagged=False, reason="Timestamp is in order.")


def cusum(residuals: Sequence[float], sigma, k_sigma: float, h_sigma: float, step_scale: float = 1.0,
          z_cap: Optional[float] = None) -> tuple[bool, float]:
    """Two-sided tabular CUSUM. `sigma` is one number or one number per residual.
    `step_scale` multiplies every step (cadence / reference minutes, so a shift of the same size and length
    gives the same sum on 1-min and 15-min data). `z_cap` limits one sample's z-score, so a single huge
    excursion (a front) cannot pile up and keep the alarm on for hours.
    Returns (alarm, largest sum)."""
    sigmas = [sigma] * len(residuals) if isinstance(sigma, (int, float)) else list(sigma)
    s_pos = s_neg = peak = 0.0
    for r, sg in zip(residuals, sigmas):
        z = r / sg
        if z_cap is not None:
            z = max(-z_cap, min(z_cap, z))
        s_pos = max(0.0, s_pos + (z - k_sigma) * step_scale)
        s_neg = max(0.0, s_neg + (-z - k_sigma) * step_scale)
        peak = max(peak, s_pos, s_neg)
    return peak >= h_sigma, peak


def check_drift(history: Sequence[Reading], ch: str, expected: Optional[Sequence[Optional[float]]],
                settings: dict, sigma: Optional[Sequence[Optional[float]]] = None,
                cadence_minutes: Optional[float] = None) -> CheckResult:
    """CUSUM drift on (reading - expected). SOFT flag: a long weather anomaly looks like drift over a few
    hours, so this can lead to SUSPECT but never blocks WEATHER. Real drift is measured by Theil-Sen in
    healthscore.py. `expected` (and optional `sigma`) are aligned with `history` and come from L2 normality.
    If `sigma` is missing, the fixed value in settings is used. If `cadence_minutes` is missing it is
    taken from the history."""
    name = f"drift:{ch}"
    if expected is None or len(expected) != len(history):
        return CheckResult(check=name, flagged=False, severity="soft",
                           reason=f"{ch}: drift not checked, no expected values supplied (needs L2 normality).")
    cfg = settings["health"]["cusum"]
    if cadence_minutes is None:
        gaps = [_minutes(a.timestamp, b.timestamp) for a, b in zip(history, history[1:])]
        gaps = sorted(g for g in gaps if g > 0)
        cadence_minutes = gaps[len(gaps) // 2] if gaps else cfg["reference_minutes"]
    cutoff = history[-1].timestamp - timedelta(minutes=cfg["window_minutes"])
    residuals, sigmas = [], []
    for i, (r, e) in enumerate(zip(history, expected)):
        v = getattr(r, ch)
        if r.timestamp >= cutoff and v is not None and e is not None:
            residuals.append(v - e)
            sg = sigma[i] if sigma is not None else None
            sigmas.append(sg if sg else cfg["sigma"][ch])
    if not residuals:
        return CheckResult(check=name, flagged=False, severity="soft",
                           reason=f"{ch}: no usable samples for drift check.")
    alarm, peak = cusum(residuals, sigmas, cfg["k_sigma"], cfg["h_sigma"],
                        step_scale=cadence_minutes / cfg["reference_minutes"], z_cap=cfg["z_cap"])
    if alarm:
        return CheckResult(check=name, flagged=True, severity="soft",
                           reason=f"{ch} is drifting away from its expected value (CUSUM {peak:.1f}, "
                                  f"alarm at {cfg['h_sigma']:g}). Could also be a long weather anomaly.")
    return CheckResult(check=name, flagged=False, severity="soft",
                       reason=f"{ch} has no sustained drift (CUSUM {peak:.1f}, alarm at {cfg['h_sigma']:g}).")


def check_health(history: Sequence[Reading], settings: dict, cadence_minutes: float,
                 now: Optional[datetime] = None,
                 expected: Optional[dict[str, Sequence[Optional[float]]]] = None,
                 sigma: Optional[dict[str, Sequence[Optional[float]]]] = None) -> list[CheckResult]:
    """Run all L1 checks on the newest reading. Returns [] when the health layer is off or no history."""
    if not layer_enabled(settings, "health") or not history:
        return []
    results = [check_timestamp(history, settings, now), check_dropout(history),
               check_gap(history, settings, cadence_minutes)]
    for ch in CHANNELS:
        results += [
            check_frozen(history, ch, settings, cadence_minutes),
            check_step(history, ch, settings, cadence_minutes),
            check_spike(history, ch, settings, cadence_minutes),
            check_noise(history, ch, settings, cadence_minutes),
            check_drift(history, ch, (expected or {}).get(ch), settings, (sigma or {}).get(ch), cadence_minutes),
        ]
    return results
