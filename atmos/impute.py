"""Gap fill with an uncertainty band. Toggle with `layers.impute`.

An estimate is given for a channel that is missing or was judged faulty. The raw reading is NEVER
replaced: the estimate is stored beside it.

Method, when the L2 table exists ("climatology + fading departure"):
    estimate = normal(ts) + rho * (last trusted value - normal(then)),   rho = 0.5 ** (age / halflife)
    band     = +/- band_z * sqrt(std(ts)**2 * (1 - rho**2) + (1 + rho**2) * noise**2)   (an AR(1) forecast plus
               the sensor noise of the last reading and of the value being estimated; noise = normality.min_std)
  Just after a trusted value the band is narrow but never below the sensor noise. As the gap grows the
  estimate falls back to the normal value for that month and hour, and the band widens to the normal spread.
Without a table: the last trusted value, with a band that grows with the age of that value.
"Trusted" = a value that is present and was not part of a FAULT verdict for that channel.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Optional, Sequence

from .config import absent_channels, layer_enabled
from .healthscore import HealthRecord, flagged_channels
from .normality import NormalityTable
from .schema import CHANNELS, ImputedValue, Imputation, Reading, Verdict, VerdictResult


def _trusted(rec: HealthRecord, ch: str) -> bool:
    return rec.values.get(ch) is not None and not (rec.verdict == Verdict.FAULT and ch in rec.flagged_channels)


def _normal(table: NormalityTable, ts: datetime, ch: str) -> Optional[dict]:
    """Normal mean and std at `ts`. The table has one cell per hour, so its mean is a step function; here it is
    read as the value at the middle of each hour and interpolated linearly between neighbouring hours."""
    here = table.cell(ts, ch)
    if here is None:
        return None
    centre = ts.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=30)
    other = table.cell(ts + timedelta(hours=1 if ts >= centre else -1), ch)
    if other is None:
        return here
    w = abs((ts - centre).total_seconds()) / 3600.0
    return {"mean": (1 - w) * here["mean"] + w * other["mean"], "std": (1 - w) * here["std"] + w * other["std"]}


def impute_value(records: Sequence[HealthRecord], ch: str, ts: datetime, table: Optional[NormalityTable],
                 settings: dict) -> Optional[ImputedValue]:
    """Estimate `ch` at time `ts` from records that are older than `ts`. None if nothing trusted is recent enough."""
    cfg = settings["impute"]
    last = next((r for r in reversed(records) if r.timestamp < ts and _trusted(r, ch)), None)
    if last is None:
        return None
    age = (ts - last.timestamp).total_seconds() / 60.0
    if age > cfg["lookback_minutes"]:
        return None
    floor = settings["normality"]["min_std"][ch]
    rho = 0.5 ** (age / cfg["residual_halflife_minutes"])
    now_cell = _normal(table, ts, ch) if table else None
    then_cell = _normal(table, last.timestamp, ch) if table else None
    if now_cell is not None and then_cell is not None:
        value = now_cell["mean"] + rho * (last.values[ch] - then_cell["mean"])
        # AR(1) forecast spread, plus the sensor noise in the last reading and in the value being estimated
        std = math.sqrt(max(now_cell["std"], floor) ** 2 * (1 - rho * rho) + (1 + rho * rho) * floor ** 2)
        method = "normal value for this month and hour plus the fading last departure"
    else:
        value = last.values[ch]
        std = math.sqrt(cfg["fallback_sigma"][ch] ** 2 * min(1.0, age / cfg["residual_halflife_minutes"]) + 2 * floor ** 2)
        method = "last trusted value (no normal pattern available)"
    half = cfg["band_z"] * std
    return ImputedValue(value=round(value, 4), lower=round(value - half, 4), upper=round(value + half, 4),
                        age_minutes=round(age, 2), method=method,
                        reason=f"based on the last trusted {ch} value {age:g} min earlier")


def impute_reading(reading: Reading, verdict: VerdictResult, records: Sequence[HealthRecord],
                   table: Optional[NormalityTable], settings: dict) -> Optional[Imputation]:
    """Estimates for the channels of this reading that are missing or faulty. None if there are none."""
    if not layer_enabled(settings, "impute"):
        return None
    absent = absent_channels(settings)
    need = {ch for ch in CHANNELS if getattr(reading, ch) is None and ch not in absent}
    if verdict.verdict == Verdict.FAULT:
        need |= set(flagged_channels(verdict.checks, reading, settings)) - set(absent)
    out = {}
    for ch in CHANNELS:
        if ch in need:
            est = impute_value(records, ch, reading.timestamp, table, settings)
            if est is not None:
                out[ch] = est
    return Imputation(channels=out) if out else None


def apply_imputation(verdict: VerdictResult, imputation: Optional[Imputation]) -> VerdictResult:
    """Copy the estimates into the verdict fields. The raw reading is not touched."""
    if imputation is None:
        return verdict
    update = {"imputation": imputation}
    for ch, est in imputation.channels.items():
        update[{"temperature_c": "imputed_temperature_c", "pressure_hpa": "imputed_pressure_hpa",
                "humidity_pct": "imputed_humidity_pct"}[ch]] = est.value
    return verdict.model_copy(update=update)


def fill_gaps(history: Sequence[Reading], settings: dict, cadence_minutes: float,
              table: Optional[NormalityTable] = None) -> list[tuple[datetime, dict[str, ImputedValue]]]:
    """Estimates for the missing sample times inside time gaps of `history` (all readings taken as trusted).
    At most `max_fill_samples` per gap. Returns (timestamp, {channel: estimate}) in time order."""
    limit = settings["health"]["gaps"]["gap_cadence_multiplier"] * cadence_minutes
    cap = settings["impute"]["max_fill_samples"]
    records = [HealthRecord(r.timestamp, {ch: getattr(r, ch) for ch in CHANNELS}, Verdict.VALID, frozenset())
               for r in history]
    out = []
    for i in range(1, len(history)):
        a, b = history[i - 1].timestamp, history[i].timestamp
        if (b - a).total_seconds() / 60.0 <= limit:
            continue
        missing = int(round((b - a).total_seconds() / 60.0 / cadence_minutes)) - 1
        for k in range(1, min(missing, cap) + 1):
            ts = a + timedelta(minutes=k * cadence_minutes)
            est = {ch: e for ch in CHANNELS if (e := impute_value(records[:i], ch, ts, table, settings))}
            if est:
                out.append((ts, est))
    return out
