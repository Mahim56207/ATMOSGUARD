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


def _drift(ch: str, recs: Sequence[HealthRecord], table: Optional[NormalityTable], now: datetime,
           settings: dict) -> dict:
    cfg = settings["healthscore"]["drift"]
    if table is None:
        return {"note": "drift not measured: no normality table for this station."}
    points = []
    for r in recs:
        v = r.values.get(ch)
        if v is None or (r.verdict == Verdict.FAULT and ch in r.flagged_channels):
            continue                                   # a fault is not counted twice as drift
        e = table.expected(r.timestamp, ch)
        if e is not None:
            points.append((r.timestamp, v - e))
    if len(points) < cfg["min_samples"]:
        return {"note": f"drift not measured: only {len(points)} usable samples (need {cfg['min_samples']})."}
    if len(points) > cfg["max_points"]:
        keep = np.linspace(0, len(points) - 1, cfg["max_points"]).astype(int)
        points = [points[i] for i in keep]
    t0 = points[0][0]
    x = np.array([(t - t0).total_seconds() / 86400.0 for t, _ in points])
    y = np.array([d for _, d in points])
    if x[-1] <= x[0]:
        return {"note": "drift not measured: all samples share one timestamp."}
    slope, intercept, lo, hi = theilslopes(y, x, alpha=cfg["alpha"])
    significant = bool(lo > 0 or hi < 0)
    offset_now = float(intercept + slope * (now - t0).total_seconds() / 86400.0)
    out = {"drift_per_day": float(slope), "drift_significant": significant, "offset_now": offset_now,
           "note": (f"drift {slope:+.4g} per day, offset now {offset_now:+.3g}" if significant
                    else f"no significant drift (slope {slope:+.3g} per day, interval includes 0).")}
    if significant:
        limit = cfg["service_limit"][ch]
        days = (np.sign(slope) * limit - offset_now) / slope     # time until the offset reaches the limit
        if days <= 0:
            out["service_date"] = now.date()
        elif days <= cfg["max_projection_days"]:
            out["service_date"] = (now + timedelta(days=float(days))).date()
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
                   now: datetime, settings: dict) -> HealthReport:
    cfg = settings["healthscore"]
    recs = [r for r in records if r.timestamp >= now - timedelta(minutes=cfg["window_minutes"])]
    if len(recs) < cfg["min_records"]:
        return HealthReport(station_id=station_id, computed_at=now, records_used=len(recs),
                            note=f"Not enough records yet for a score ({len(recs)} of {cfg['min_records']}).")
    w = cfg["weights"]
    channels: dict[str, ChannelHealth] = {}
    for ch in CHANNELS:
        f_fault = sum(1 for r in recs if r.verdict == Verdict.FAULT and ch in r.flagged_channels) / len(recs)
        f_susp = sum(1 for r in recs if r.verdict == Verdict.SUSPECT and ch in r.flagged_channels) / len(recs)
        d = _drift(ch, recs, table, now, settings)
        ratio = min(1.0, abs(d["offset_now"]) / cfg["drift"]["service_limit"][ch]) if d.get("drift_significant") else 0.0
        score = min(100.0, max(0.0, 100.0 - w["fault"] * f_fault - w["suspect"] * f_susp - w["drift"] * ratio))
        channels[ch] = ChannelHealth(channel=ch, score=round(score, 2), fault_fraction=round(f_fault, 4),
                                     suspect_fraction=round(f_susp, 4), drift_per_day=d.get("drift_per_day"),
                                     drift_significant=d.get("drift_significant", False),
                                     offset_now=d.get("offset_now"), service_date=d.get("service_date"),
                                     note=d["note"])
    score = min(h.score for h in channels.values())
    dates = [h.service_date for h in channels.values() if h.service_date is not None]
    service_date = min(dates) if dates else None
    return HealthReport(station_id=station_id, computed_at=now, records_used=len(recs), score=score,
                        service_date=service_date, channels=channels,
                        ticket=_ticket(station_id, now, score, channels, recs, service_date, settings))
