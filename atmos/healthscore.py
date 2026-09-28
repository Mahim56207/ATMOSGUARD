"""Health score 0-100, Theil-Sen drift, projected service date, ticket.

Works from compact per-reading records (`HealthRecord`), so it can run for weeks of 1-minute data.
Score per channel = 100 - w_fault*fault_fraction - w_suspect*suspect_fraction - w_drift*drift_ratio.
The station score is the WORST channel. WEATHER verdicts never count against a sensor.
Drift is the Theil-Sen slope of (reading - expected from the L2 table) over time. We do NOT claim
long-term drift validation, and a slow offset with no reference cannot be seen (see README).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional, Sequence

import math

import numpy as np
from pydantic import BaseModel
from scipy.stats import theilslopes

from .normality import NormalityTable
from .schema import CHANNELS, CheckResult, Reading, Verdict, VerdictResult


@dataclass(frozen=True)
class HealthRecord:
    timestamp: datetime
    values: dict                     # channel -> raw value (or None)
    verdict: Verdict
    flagged_channels: frozenset


class ChannelHealth(BaseModel):
    channel: str
    score: float
    fault_fraction: float
    suspect_fraction: float
    drift_per_day: Optional[float] = None
    drift_z: Optional[float] = None                 # slope / autocorrelation-aware standard error
    drift_floor_per_day: Optional[float] = None     # smallest slope this station's weather noise lets us see
    drift_significant: bool = False
    offset_now: Optional[float] = None
    service_date: Optional[date] = None
    note: str = ""


class Ticket(BaseModel):
    station_id: str
    opened: datetime
    priority: str                    # "high" or "normal"
    channels: list[str]
    health_score: Optional[float]
    service_date: Optional[date]
    reason: str


class HealthReport(BaseModel):
    station_id: str
    computed_at: datetime
    records_used: int
    score: Optional[float] = None
    service_date: Optional[date] = None
    channels: dict[str, ChannelHealth] = {}
    ticket: Optional[Ticket] = None
    note: str = ""


def flagged_channels(checks: Sequence[CheckResult], reading: Reading, settings: dict) -> frozenset:
    """Which channels the flagged checks point at (from the check name, or the dropout / dew-point rule)."""
    extra = settings["healthscore"]["check_channels"]
    out: set[str] = set()
    for c in checks:
        if not c.flagged:
            continue
        kind, _, ch = c.check.partition(":")
        if ch in CHANNELS:
            out.add(ch)
        elif kind == "dropout":
            out.update(name for name in CHANNELS if getattr(reading, name) is None)
        elif kind in extra:
            out.update(extra[kind])
    return frozenset(out)


def to_health_record(reading: Reading, result: VerdictResult, settings: dict) -> HealthRecord:
    return HealthRecord(reading.timestamp, {ch: getattr(reading, ch) for ch in CHANNELS}, result.verdict,
                        flagged_channels(result.checks, reading, settings))


class DriftTracker:
    """Per-day aggregates of (reading - smooth expected value), per channel, for ONE station.

    Why daily means: weather anomalies last days, so hourly residuals are strongly autocorrelated and a slope test
    on them claims drift on almost every window (measured: 98 % of days on real data). A day's mean residual is the
    unit that is close enough to independent to test. Residuals are clipped at `winsor_sigma` standard deviations
    of the normality cell, so one front cannot move a day's mean. A sample that was judged a FAULT on this channel
    is left out (it is not counted twice as drift)."""

    def __init__(self, settings: dict):
        cfg = settings["healthscore"]["drift"]
        self._keep_days = int(cfg["window_days"]) + int(cfg["persist_days"]) + 3
        self._winsor = float(cfg["winsor_sigma"])
        self._min_std = settings["normality"]["min_std"]
        self.days: dict[str, dict[int, list]] = {ch: {} for ch in CHANNELS}      # ch -> day ordinal -> [sum, n]

    def update(self, reading: Reading, table: Optional[NormalityTable], faulty_channels: frozenset) -> None:
        if table is None:
            return
        day = reading.timestamp.toordinal()
        for ch in CHANNELS:
            v = getattr(reading, ch)
            if v is None or ch in faulty_channels:
                continue
            e = table.smooth_expected(reading.timestamp, ch)
            cell = table.cell(reading.timestamp, ch)
            if e is None or cell is None:
                continue
            lim = self._winsor * max(cell["std"], self._min_std[ch])
            acc = self.days[ch].setdefault(day, [0.0, 0])
            acc[0] += max(-lim, min(lim, v - e))
            acc[1] += 1
            for d in [d for d in self.days[ch] if d < day - self._keep_days]:
                del self.days[ch][d]

    def series(self, ch: str, now: datetime, window_days: int, min_samples: float) -> list[tuple[float, float]]:
        """[(day ordinal, mean residual)] for the last `window_days` days that have enough samples."""
        last = now.toordinal()
        return sorted((d, a[0] / a[1]) for d, a in self.days[ch].items()
                      if last - window_days < d <= last and a[1] >= min_samples)


def _daily_from_records(recs: Sequence[HealthRecord], table: Optional[NormalityTable], ch: str,
                        settings: dict, min_samples: float) -> list[tuple[float, float]]:
    """Same daily series, built from stored records (used when no DriftTracker is available)."""
    if table is None:
        return []
    tracker = DriftTracker(settings)
    for r in recs:
        faulty = frozenset({ch}) if (r.verdict == Verdict.FAULT and ch in r.flagged_channels) else frozenset()
        v = r.values.get(ch)
        if v is None:
            continue
        tracker.update(Reading(station_id="_", timestamp=r.timestamp, **{ch: v}), table, faulty)
    now = recs[-1].timestamp if recs else datetime.min
    dcfg = settings["healthscore"]["drift"]
    return tracker.series(ch, now, dcfg["window_days"] + dcfg["persist_days"], min_samples)


def _drift(ch: str, daily: Sequence[tuple[float, float]], now: datetime, settings: dict, have_table: bool) -> dict:
    """Theil-Sen slope of the daily mean residual, with an autocorrelation-aware significance test.

    Significance: OLS slope over its standard error, the error inflated by sqrt((1+rho)/(1-rho)) where rho is the
    lag-1 autocorrelation of the fit residuals (clipped to [0, ar1_max]). The reported slope is Theil-Sen (robust).
    `drift_floor_per_day` is the smallest slope this test can tell from weather at this station right now, so the
    honest answer to "how small a drift could you see?" is a number, not a claim."""
    cfg = settings["healthscore"]["drift"]
    if not have_table:
        return {"note": "drift not measured: no normality table for this station."}
    last = now.toordinal()
    daily = [(d, m) for d, m in daily if last - cfg["window_days"] < d <= last]
    if len(daily) < cfg["min_days"]:
        return {"note": f"drift not measured: {len(daily)} usable days of {cfg['min_days']} needed."}
    x = np.array([d for d, _ in daily], dtype=float)
    y = np.array([m for _, m in daily], dtype=float)
    xc = x - x.mean()
    sxx = float((xc ** 2).sum())
    ols = float((xc * (y - y.mean())).sum() / sxx)
    resid = y - y.mean() - ols * xc
    rho = 0.0
    if len(y) > 4 and resid.std() > 0:
        rho = float(np.clip(np.corrcoef(resid[:-1], resid[1:])[0, 1], 0.0, cfg["ar1_max"]))
    se = math.sqrt(float(resid.var(ddof=2)) / sxx) * math.sqrt((1 + rho) / (1 - rho))
    slope, intercept, _, _ = theilslopes(y, x - x[0])
    z = float(slope / se) if se > 0 else 0.0
    significant = bool(abs(z) >= cfg["z_crit"])
    offset_now = float(intercept + slope * (now.toordinal() - x[0]))
    floor = cfg["z_crit"] * se
    out = {"drift_per_day": float(slope), "drift_significant": significant, "offset_now": offset_now,
           "drift_z": z, "drift_floor_per_day": float(floor),
           "note": (f"drift {slope:+.4g} per day (z = {z:.1f}), offset now {offset_now:+.3g}" if significant else
                    f"no significant drift (slope {slope:+.3g} per day, z = {z:.1f}; smallest visible slope here "
                    f"{floor:.3g} per day).")}
    if significant:
        limit = cfg["service_limit"][ch]
        days = (np.sign(slope) * limit - offset_now) / slope     # time until the offset reaches the limit
        if days <= 0:
            out["service_date"] = now.date()
        elif days <= cfg["max_projection_days"]:
            out["service_date"] = (now + timedelta(days=float(days))).date()
    return out


def _isolated(results: dict[str, dict], settings: dict) -> dict[str, dict]:
    """The isolated-trend rule on one set of per-channel results (see drift_all)."""
    cfg = settings["healthscore"]["drift"]
    for ch in CHANNELS:
        d = results[ch]
        if not d.get("drift_significant"):
            continue
        partners = [o for o in CHANNELS if o != ch and abs(results[o].get("drift_z") or 0.0) >= cfg["partner_z"]]
        if partners:
            d["drift_significant"] = False
            d["coherent_with"] = partners
            d.pop("service_date", None)
            d["note"] = (f"{ch} and {', '.join(partners)} are trending together: read as a weather or seasonal "
                         f"transition, not sensor drift (slope {d['drift_per_day']:+.3g} per day, z = {d['drift_z']:.1f}).")
    return results


def drift_all(daily: dict[str, Sequence[tuple[float, float]]], now: datetime, settings: dict,
              have_table: bool) -> dict[str, dict]:
    """Drift result per channel, after two guards against weather being read as a sick sensor.

    Isolated trend: weather moves several channels, a drifting sensor moves one. If a channel's trend is
    significant but another channel also trends clearly (|z| at least `partner_z`), the trend is read as a seasonal
    or weather transition (monsoon onset, change of air mass) and is NOT counted as drift. The cost: a real drift
    that starts during a transition is masked until the transition is over.

    Persistence: the trend must be significant, with the same sign, on each of the last `persist_days` daily
    evaluations (windows ending today, yesterday, ...). One lucky day of weather is not enough. The cost: a drift
    is claimed `persist_days` days later than a single test would claim it.
    Pass `daily` covering `window_days + persist_days` days."""
    cfg = settings["healthscore"]["drift"]
    out = _isolated({ch: _drift(ch, daily.get(ch, []), now, settings, have_table) for ch in CHANNELS}, settings)
    for k in range(1, int(cfg["persist_days"])):
        if not any(out[ch].get("drift_significant") for ch in CHANNELS):
            break
        past = _isolated({ch: _drift(ch, daily.get(ch, []), now - timedelta(days=k), settings, have_table)
                          for ch in CHANNELS}, settings)
        for ch in CHANNELS:
            d = out[ch]
            if d.get("drift_significant") and not (
                    past[ch].get("drift_significant") and past[ch]["drift_per_day"] * d["drift_per_day"] > 0):
                d["drift_significant"] = False
                d.pop("service_date", None)
                d["note"] = (f"{ch}: a trend showed up today (z = {d['drift_z']:.1f}) but was not significant on each of "
                             f"the last {int(cfg['persist_days'])} days, so it is not claimed as drift yet.")
    return out


def _ticket(station_id: str, now: datetime, score: Optional[float], channels: dict[str, ChannelHealth],
            recs: Sequence[HealthRecord], service_date: Optional[date], settings: dict) -> Optional[Ticket]:
    cfg = settings["healthscore"]["ticket"]
    reasons, involved, high = [], set(), False
    if score is not None and score <= cfg["score_below"]:
        reasons.append(f"health score {score:.0f} is at or below {cfg['score_below']}")
        involved.update(ch for ch, h in channels.items() if h.score <= cfg["score_below"])
        high = high or score <= cfg["high_below"]
    recent = [r for r in recs if r.timestamp >= now - timedelta(minutes=cfg["recent_minutes"])]
    for ch in CHANNELS:
        if recent:
            frac = sum(1 for r in recent if r.verdict == Verdict.FAULT and ch in r.flagged_channels) / len(recent)
            if frac >= cfg["recent_fault_fraction"]:
                reasons.append(f"{ch} has been faulty in {frac:.0%} of the last {cfg['recent_minutes']} min")
                involved.add(ch)
                high = True
    for ch, h in channels.items():
        if h.service_date is not None and (h.service_date - now.date()).days <= cfg["service_within_days"]:
            reasons.append(f"{ch} is projected to need service by {h.service_date.isoformat()}")
            involved.add(ch)
            high = high or h.service_date <= now.date()
    if not reasons:
        return None
    return Ticket(station_id=station_id, opened=now, priority="high" if high else "normal",
                  channels=[ch for ch in CHANNELS if ch in involved], health_score=score,
                  service_date=service_date, reason="Maintenance needed: " + "; ".join(reasons) + ".")


def compute_health(station_id: str, records: Sequence[HealthRecord], table: Optional[NormalityTable],
                   now: datetime, settings: dict, tracker: Optional["DriftTracker"] = None,
                   cadence_minutes: Optional[float] = None) -> HealthReport:
    """`records` give the fault fractions over `window_minutes`. Drift uses the last `drift.window_days` days:
    from `tracker` if one is given, else from `records` (so pass a long enough list of records then)."""
    cfg = settings["healthscore"]
    all_records = records
    recs = [r for r in records if r.timestamp >= now - timedelta(minutes=cfg["window_minutes"])]
    if len(recs) < cfg["min_records"]:
        return HealthReport(station_id=station_id, computed_at=now, records_used=len(recs),
                            note=f"Not enough records yet for a score ({len(recs)} of {cfg['min_records']}).")
    w = cfg["weights"]
    channels: dict[str, ChannelHealth] = {}
    dcfg = cfg["drift"]
    if cadence_minutes is None and len(recs) > 1:
        gaps = sorted((b.timestamp - a.timestamp).total_seconds() / 60.0 for a, b in zip(recs, recs[1:]))
        cadence_minutes = max(gaps[len(gaps) // 2], 1e-3)
    min_samples = max(1.0, dcfg["min_day_fraction"] * 1440.0 / (cadence_minutes or 1440.0))
    daily_by_ch = {ch: (tracker.series(ch, now, dcfg["window_days"] + dcfg["persist_days"], min_samples) if tracker is not None
                        else _daily_from_records(all_records, table, ch, settings, min_samples)) for ch in CHANNELS}
    drifts = drift_all(daily_by_ch, now, settings, table is not None)
    for ch in CHANNELS:
        f_fault = sum(1 for r in recs if r.verdict == Verdict.FAULT and ch in r.flagged_channels) / len(recs)
        f_susp = sum(1 for r in recs if r.verdict == Verdict.SUSPECT and ch in r.flagged_channels) / len(recs)
        d = drifts[ch]
        ratio = min(1.0, abs(d["offset_now"]) / cfg["drift"]["service_limit"][ch]) if d.get("drift_significant") else 0.0
        score = min(100.0, max(0.0, 100.0 - w["fault"] * f_fault - w["suspect"] * f_susp - w["drift"] * ratio))
        channels[ch] = ChannelHealth(channel=ch, score=round(score, 2), fault_fraction=round(f_fault, 4),
                                     suspect_fraction=round(f_susp, 4), drift_per_day=d.get("drift_per_day"),
                                     drift_z=d.get("drift_z"), drift_floor_per_day=d.get("drift_floor_per_day"),
                                     drift_significant=d.get("drift_significant", False),
                                     offset_now=d.get("offset_now"), service_date=d.get("service_date"),
                                     note=d["note"])
    score = min(h.score for h in channels.values())
    dates = [h.service_date for h in channels.values() if h.service_date is not None]
    service_date = min(dates) if dates else None
    return HealthReport(station_id=station_id, computed_at=now, records_used=len(recs), score=score,
                        service_date=service_date, channels=channels,
                        ticket=_ticket(station_id, now, score, channels, recs, service_date, settings))
