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

from .config import absent_channels, layer_enabled
from .limits import StationLimits, limits_active
from .schema import CHANNELS, CheckResult, Reading


def _minutes(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 60.0


def _window(history: Sequence[Reading], minutes: float) -> list[Reading]:
    """Readings whose timestamp is within `minutes` of the newest one (newest included)."""
    cutoff = history[-1].timestamp - timedelta(minutes=minutes)
    return [r for r in history if r.timestamp >= cutoff]


def _allowed_step(ch: str, minutes_apart: float, settings: dict, learned_cap: Optional[float] = None) -> float:
    """Allowed change between two readings. `learned_cap` (remedy 2) can only raise the configured cap, never lower it."""
    cfg = settings["health"]["step"]
    cap = cfg["cap"][ch] if not learned_cap else max(cfg["cap"][ch], learned_cap)
    return min(cfg["rate_per_min"][ch] * minutes_apart, cap)


def _gap_limit_minutes(settings: dict, cadence_minutes: float) -> float:
    return settings["health"]["gaps"]["gap_cadence_multiplier"] * cadence_minutes


def _trailing_run_minutes(history: Sequence[Reading], ch: str, epsilon: float, gap_limit_minutes: float) -> float:
    """How long (minutes) the newest value of `ch` has been unchanged, looking back through `history`.
    A missing value or a time gap ends the run."""
    newest = getattr(history[-1], ch)
    if newest is None:
        return 0.0
    first = history[-1]
    for r in reversed(history[:-1]):
        v = getattr(r, ch)
        if v is None or abs(v - newest) > epsilon or _minutes(r.timestamp, first.timestamp) > gap_limit_minutes:
            break
        first = r
    return _minutes(first.timestamp, history[-1].timestamp)


def _at_humidity_ceiling(history: Sequence[Reading], ch: str, window_minutes: float, cfg: dict) -> bool:
    """Remedy 1. True when a frozen `ch` is explained by saturated air: humidity itself pinned at its ceiling, or temperature
    still while humidity has been at its ceiling for the whole window. Pressure is independent of saturation, so a frozen
    barometer stays a hard flag."""
    if ch == "pressure_hpa":
        return False
    ceiling = cfg["ceiling"]["humidity_pct"]
    rh = [r.humidity_pct for r in _window(history, window_minutes)]
    return bool(rh) and all(v is not None and v >= ceiling for v in rh)


def _at_freezing_plateau(history: Sequence[Reading], ch: str, window_minutes: float, cfg: dict) -> bool:
    """Remedy 7 (Amendment 5). True when a frozen temperature or humidity is explained by freezing precipitation: over the whole window the temperature
    stayed within `band_c` of 0 C while the air was humid (`humidity_min_pct`). Latent heat holds the air at the freezing point for hours in freezing
    rain and wet snow. A frozen barometer is never explained by this."""
    if ch == "pressure_hpa":
        return False
    fz = cfg["freezing"]
    rows = _window(history, window_minutes)
    return bool(rows) and all(r.temperature_c is not None and abs(r.temperature_c) <= fz["band_c"]
                              and r.humidity_pct is not None and r.humidity_pct >= fz["humidity_min_pct"] for r in rows)


def check_frozen(history: Sequence[Reading], ch: str, settings: dict, cadence_minutes: float,
                 limits: Optional[StationLimits] = None) -> CheckResult:
    """Frozen = no change at all over the window. The window is the configured one, stretched to the longest run
    of identical values this station's clean history produced (`limits`), so a station that reports whole
    numbers is not called stuck for an ordinary calm night.

    Two tiers when the window was learned: a run just past the learned limit is a SOFT flag (a long calm or a
    pressure plateau in a deep low looks like this); a run `hard_multiplier` times longer than the limit is HARD
    (nothing in the clean history comes close). Without learned limits every frozen flag is hard, as before."""
    cfg = settings["health"]["frozen"]
    window_min = max(cfg["window_minutes"][ch], (cfg["min_samples"] - 1) * cadence_minutes)
    learned = limits.frozen_minutes(ch) if (limits is not None and limits_active(settings)) else None
    if learned:
        window_min = max(window_min, learned)
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
        run = _trailing_run_minutes(history, ch, cfg["epsilon"][ch], _gap_limit_minutes(settings, cadence_minutes))
        hard = not learned or run >= cfg.get("hard_multiplier", 1.0) * window_min
        saturated = hard and cfg.get("ceiling_aware") and _at_humidity_ceiling(history, ch, window_min, cfg)
        if saturated:
            hard = False
        plateau = hard and cfg.get("freezing_aware") and _at_freezing_plateau(history, ch, window_min, cfg)
        if plateau:
            hard = False
        return CheckResult(check=name, flagged=True, severity="hard" if hard else "soft",
                           reason=f"{ch} has not changed for {max(run, window_min):g} min (stuck at {values[-1]})."
                                  + (" The temperature has sat at the freezing point in humid air for the whole window, which freezing rain and wet snow do "
                                     "for hours, so this is a warning, not proof." if plateau else "" if hard and not saturated else
                                     " Humidity is at its ceiling, and sustained heavy rain holds humidity (and, with it, the "
                                     "temperature) still for a day or more, so this is a warning, not proof." if saturated else
                                     " That is longer than usual for this station, but a long calm "
                                     "or a pressure plateau in a deep low can look like this."))
    return CheckResult(check=name, flagged=False,
                       reason=f"{ch} changed by {spread:g} in the last {window_min:g} min, so it is not frozen.")


def check_step(history: Sequence[Reading], ch: str, settings: dict, cadence_minutes: float,
               limits: Optional[StationLimits] = None,
               expected: Optional[Sequence[Optional[float]]] = None) -> CheckResult:
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
    learned = limits.step_cap(ch) if (limits is not None and limits_active(settings)
                                      and settings["limits"].get("learned_step_cap")) else None
    allowed = _allowed_step(ch, dt, settings, learned)
    delta = b - a
    note = ""
    if settings["health"]["step"].get("expected_aware") and expected is not None and len(expected) == len(history):
        ea, eb = expected[-2], expected[-1]
        if ea is not None and eb is not None and abs(delta - (eb - ea)) < abs(delta):
            # remedy 3: a desert warms 15 C between two reports on a clear day. Only the part of the change that the
            # station's own daily cycle does not explain is judged; this can relax a flag, never add one.
            note = f" (of which the usual daily cycle explains {eb - ea:+.1f})"
            delta_judged = delta - (eb - ea)
            if abs(delta_judged) > allowed:
                return CheckResult(check=name, flagged=True,
                                   reason=f"{ch} jumped by {delta:+g} in {dt:g} min{note}, allowed {allowed:g}.")
            return CheckResult(check=name, flagged=False,
                               reason=f"{ch} changed by {delta:+g} in {dt:g} min{note}, allowed {allowed:g}.")
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


def check_noise(history: Sequence[Reading], ch: str, settings: dict, cadence_minutes: float,
                limits: Optional[StationLimits] = None) -> CheckResult:
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
    if limits is not None and limits_active(settings):
        limit = max(limit, limits.noise_std(ch) or 0.0)          # learned from this station's clean history
    if noise > limit:
        return CheckResult(check=name, flagged=True,
                           reason=f"{ch} is too noisy: estimated jitter {noise:.3g} is above {limit:g} "
                                  f"over {window_min:g} min.")
    return CheckResult(check=name, flagged=False,
                       reason=f"{ch} jitter {noise:.3g} is within the limit of {limit:g}.")


def check_dropout(history: Sequence[Reading], absent: Sequence[str] = ()) -> CheckResult:
    """A channel in `absent` is one this station does not have (no barometer, say): it is never a dropout."""
    present = [ch for ch in CHANNELS if ch not in absent]
    missing = [ch for ch in present if getattr(history[-1], ch) is None]
    if missing:
        return CheckResult(check="dropout", flagged=True,
                           reason=f"No value received for: {', '.join(missing)}.")
    return CheckResult(check="dropout", flagged=False,
                       reason="All three channels have a value." if not absent else f"All {len(present)} channels this station has report a value.")


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


def check_limits_fit(limits: Optional[StationLimits], settings: dict, cadence_minutes: float) -> CheckResult:
    """Informational: are this station's learned limits usable at the cadence it reports at now? Never changes a verdict.

    Found on the FRESH2 stations: four Australian AWS reported 16 hours a day with alternating 1 h and 2 h gaps in 2016-2019 and hourly, all day, from 2020. No noise
    limit could be learned from that (no run of equally spaced readings), the fixed floor was used, and it alarms on 0.1-resolution data (13-33 % false alarms at those four)."""
    if limits is None or not limits_active(settings):
        return CheckResult(check="limits", flagged=False, reason="No station-learned limits to check.")
    problems = []
    unlearned = [ch for ch in CHANNELS if limits.noise_std(ch) is None and ch not in absent_channels(settings)]
    if unlearned:
        problems.append(f"the noise limit of {', '.join(unlearned)} was not learned (too few runs of equally spaced readings in the training data), so the fixed floor is "
                        "used, which can alarm on fine-resolution stations")
    if limits.cadence_minutes and abs(cadence_minutes / limits.cadence_minutes - 1.0) > 0.25:
        problems.append(f"the limits were learned at a {limits.cadence_minutes:g} min cadence and the station now reports every {cadence_minutes:g} min")
    if problems:
        return CheckResult(check="limits", flagged=True, reason="Station limits may not fit this data: " + "; and ".join(problems) + ". Refit them (python train.py) on a stretch at the current cadence.")
    return CheckResult(check="limits", flagged=False, reason="Station-learned limits fit the current cadence.")


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


def check_offset(history: Sequence[Reading], ch: str, expected: Optional[Sequence[Optional[float]]],
                 sigma: Optional[Sequence[Optional[float]]], all_expected: dict, all_sigma: dict,
                 settings: dict, cadence_minutes: float) -> CheckResult:
    """Remedy 4 (off by default): a sustained one-channel offset. Over the last `window_minutes` the MEDIAN departure of `ch` from
    the station's normal is at least `z_median` standard deviations, and the other two channels' median departures are both below
    `others_below`. One sample of weather cannot do this, and a weather system that moves the level of one channel usually moves
    another (a heat wave: hot, dry, low pressure), which is why the others must stay near normal. SOFT: it can only lead to SUSPECT."""
    name = f"offset:{ch}"
    cfg = settings["health"].get("offset") or {}
    if not cfg.get("enabled") or expected is None or sigma is None or len(expected) != len(history):
        return CheckResult(check=name, flagged=False, severity="soft", reason=f"{ch}: sustained-offset check is off.")
    window = max(cfg["window_minutes"], (cfg["min_samples"] - 1) * cadence_minutes)
    cutoff = history[-1].timestamp - timedelta(minutes=window)
    gap = _gap_limit_minutes(settings, cadence_minutes)

    def departures(c: str, exp, sig) -> Optional[list[float]]:
        zs, prev = [], None
        for i, r in enumerate(history):
            if r.timestamp < cutoff:
                continue
            v = getattr(r, c)
            if v is None or exp[i] is None or not sig[i]:
                return None
            if prev is not None and _minutes(prev, r.timestamp) > gap:
                return None
            prev = r.timestamp
            zs.append((v - exp[i]) / sig[i])
        return zs if len(zs) >= cfg["min_samples"] else None

    own = departures(ch, expected, sigma)
    if own is None:
        return CheckResult(check=name, flagged=False, severity="soft", reason=f"{ch}: not enough complete samples for an offset check.")
    med = sorted(own)[len(own) // 2] if len(own) % 2 else 0.5 * (sorted(own)[len(own) // 2 - 1] + sorted(own)[len(own) // 2])
    if abs(med) < cfg["z_median"]:
        return CheckResult(check=name, flagged=False, severity="soft", reason=f"{ch}: median departure {med:+.1f} sd over {window:g} min is ordinary.")
    for other in CHANNELS:
        if other == ch:
            continue
        z = departures(other, all_expected[other], all_sigma[other])
        if z is None:
            return CheckResult(check=name, flagged=False, severity="soft", reason=f"{ch}: the other channels cannot be compared.")
        m = sorted(z)[len(z) // 2] if len(z) % 2 else 0.5 * (sorted(z)[len(z) // 2 - 1] + sorted(z)[len(z) // 2])
        if abs(m) >= cfg["others_below"]:
            return CheckResult(check=name, flagged=False, severity="soft",
                               reason=f"{ch} is {med:+.1f} sd from normal but so is {other} ({m:+.1f}): moving together looks like weather.")
    return CheckResult(check=name, flagged=True, severity="soft",
                       reason=f"{ch} has sat {med:+.1f} standard deviations from this station's normal for {window:g} min while the other "
                              "two channels stayed near normal: a sustained offset on one sensor.")


def check_health(history: Sequence[Reading], settings: dict, cadence_minutes: float,
                 now: Optional[datetime] = None,
                 expected: Optional[dict[str, Sequence[Optional[float]]]] = None,
                 sigma: Optional[dict[str, Sequence[Optional[float]]]] = None,
                 limits: Optional[StationLimits] = None) -> list[CheckResult]:
    """Run all L1 checks on the newest reading. Returns [] when the health layer is off or no history."""
    if not layer_enabled(settings, "health") or not history:
        return []
    results = [check_timestamp(history, settings, now), check_dropout(history, absent_channels(settings)),
               check_gap(history, settings, cadence_minutes), check_limits_fit(limits, settings, cadence_minutes)]
    for ch in CHANNELS:
        results += [
            check_frozen(history, ch, settings, cadence_minutes, limits),
            check_step(history, ch, settings, cadence_minutes, limits, (expected or {}).get(ch)),
            check_spike(history, ch, settings, cadence_minutes),
            check_noise(history, ch, settings, cadence_minutes, limits),
            check_drift(history, ch, (expected or {}).get(ch), settings, (sigma or {}).get(ch), cadence_minutes),
        ]
    if (settings["health"].get("offset") or {}).get("enabled") and expected and sigma:
        for ch in CHANNELS:
            results.append(check_offset(history, ch, expected.get(ch), sigma.get(ch), expected, sigma, settings, cadence_minutes))
    return results
