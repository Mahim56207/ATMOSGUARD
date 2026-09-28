"""T1 clock / diurnal-phase check and T2 cross-channel co-jump check. Toggle with `layers.timing`.

T1: the daily cycle of temperature and humidity should look like this station's normal cycle (the L2 table).
    If the readings match the normal cycle much better after moving their timestamps by a whole number of
    hours, the logger clock may be wrong. SOFT flag. The L2 table has one cell per hour, so a clock error
    smaller than an hour cannot be seen.
T2: two or more channels jumping in the same sample is not smooth weather. It points at a common cause
    (power glitch, logger reset) or a very sharp real change. HARD flag, so it leads to SUSPECT.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional, Sequence

from .config import layer_enabled
from .health import check_step
from .normality import NormalityTable
from .schema import CHANNELS, CheckResult, Reading


def _hourly_bins(history: Sequence[Reading], channels: Sequence[str], window_minutes: float) -> dict:
    """{hour start: {channel: mean}} over the last `window_minutes`."""
    cutoff = history[-1].timestamp - timedelta(minutes=window_minutes)
    values: dict = defaultdict(lambda: defaultdict(list))
    for r in history:
        if r.timestamp < cutoff:
            continue
        hour = r.timestamp.replace(minute=0, second=0, microsecond=0)
        for ch in channels:
            v = getattr(r, ch)
            if v is not None:
                values[hour][ch].append(v)
    return {h: {ch: sum(v) / len(v) for ch, v in per.items()} for h, per in values.items()}


def _shift_scores(bins: dict, table: NormalityTable, channels: Sequence[str], settings: dict) -> dict[int, float]:
    """Mean squared z-score of the readings against the table, for each timestamp shift (whole hours)."""
    cfg = settings["timing"]["clock"]
    min_std = settings["normality"]["min_std"]
    scores: dict[int, float] = {}
    for shift in range(-cfg["max_shift_hours"], cfg["max_shift_hours"] + 1):
        total, count = 0.0, 0
        for hour, per in bins.items():
            for ch, mean in per.items():
                cell = table.cell(hour + timedelta(hours=shift), ch)
                if cell is None:
                    continue
                z = (mean - cell["mean"]) / max(cell["std"], min_std[ch])
                total += z * z
                count += 1
        if count >= cfg["min_bins"]:
            scores[shift] = total / count
    return scores


def check_clock(history: Sequence[Reading], table: Optional[NormalityTable], settings: dict) -> CheckResult:
    cfg = settings["timing"]["clock"]
    if table is None:
        return CheckResult(check="clock", flagged=False, severity="soft",
                           reason="Clock check not run: no normal daily pattern (L2 table) for this station.")
    bins = _hourly_bins(history, cfg["channels"], cfg["window_minutes"])
    if len(bins) < cfg["min_bins"]:
        return CheckResult(check="clock", flagged=False, severity="soft",
                           reason=f"Clock check needs {cfg['min_bins']} hours of data in the last day; "
                                  f"have {len(bins)}.")
    scores = _shift_scores(bins, table, cfg["channels"], settings)
    if 0 not in scores or len(scores) < 2:
        return CheckResult(check="clock", flagged=False, severity="soft",
                           reason="Clock check skipped: the normal pattern does not cover enough of these hours.")
    best = min(scores, key=lambda s: (scores[s], abs(s)))
    if best != 0 and abs(best) >= cfg["min_shift_hours"] and scores[best] < scores[0] * (1 - cfg["min_improvement"]):
        return CheckResult(
            check="clock", flagged=True, severity="soft",
            reason=f"The daily cycle matches this station's normal pattern much better if the timestamps are "
                   f"moved by {best:+d} h (fit error {scores[best]:.2f} instead of {scores[0]:.2f}). "
                   "The logger clock may be wrong.")
    return CheckResult(check="clock", flagged=False, severity="soft",
                       reason=f"The daily cycle matches this station's normal pattern with no time shift "
                              f"(fit error {scores[0]:.2f}).")


def check_cojump(history: Sequence[Reading], settings: dict, cadence_minutes: float) -> CheckResult:
    need = settings["timing"]["cojump"]["min_channels"]
    if len(history) < 2:
        return CheckResult(check="cojump", flagged=False, reason="Only one reading, no co-jump check.")
    jumped = [ch for ch in CHANNELS if check_step(history, ch, settings, cadence_minutes).flagged]
    if len(jumped) >= need:
        prev, cur = history[-2], history[-1]
        moves = ", ".join(f"{ch} {getattr(cur, ch) - getattr(prev, ch):+g}" for ch in jumped)
        return CheckResult(
            check="cojump", flagged=True,
            reason=f"{len(jumped)} channels jumped in the same sample ({moves}). Smooth weather does not do "
                   "this: look for a common cause such as a power glitch or logger reset, or a very sharp "
                   "real change.")
    return CheckResult(check="cojump", flagged=False,
                       reason=f"{len(jumped)} channel(s) jumped in the last sample; fewer than {need}.")


def check_timing(history: Sequence[Reading], table: Optional[NormalityTable], settings: dict,
                 cadence_minutes: float) -> list[CheckResult]:
    """Run T1 and T2 on the newest reading. Returns [] when the timing layer is off."""
    if not layer_enabled(settings, "timing") or not history:
        return []
    return [check_clock(history, table, settings), check_cojump(history, settings, cadence_minutes)]
