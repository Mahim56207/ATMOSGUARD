"""Pydantic models for a reading and a verdict.

Inputs are only temperature (C), pressure (hPa), relative humidity (%), plus the
timestamp and station id. A channel may be None (dropout); it is stored as received.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


CHANNELS = ("temperature_c", "pressure_hpa", "humidity_pct")


class Verdict(str, Enum):
    VALID = "VALID"
    WEATHER = "WEATHER"
    SUSPECT = "SUSPECT"
    FAULT = "FAULT"


class Reading(BaseModel):
    """One reading. Timestamps are UTC and kept without a zone: a zone-aware value is converted to UTC first,
    so readings from different senders can always be compared. A value that is NaN or infinite is not a
    measurement, so it is kept as missing (None)."""
    station_id: str = Field(min_length=1, max_length=64)
    timestamp: datetime
    temperature_c: Optional[float] = None
    pressure_hpa: Optional[float] = None
    humidity_pct: Optional[float] = None
    device_flags: Optional[list[str]] = None   # L0 flags raised on the node itself (firmware / simnode)

    @field_validator("timestamp")
    @classmethod
    def _utc_without_zone(cls, v: datetime) -> datetime:
        return v.astimezone(timezone.utc).replace(tzinfo=None) if v.tzinfo is not None else v

    @field_validator("temperature_c", "pressure_hpa", "humidity_pct")
    @classmethod
    def _finite_or_missing(cls, v: Optional[float]) -> Optional[float]:
        return v if v is None or math.isfinite(v) else None


class CheckResult(BaseModel):
    """Result of one QC check. Every check gives a reason string, not just a boolean."""
    check: str
    flagged: bool
    reason: str
    severity: str = "hard"   # "hard" or "soft". Soft flags (e.g. wet-bulb) can only lead to SUSPECT.


class ImputedValue(BaseModel):
    """An estimate for a missing or faulty value, with an uncertainty band. The raw value is never replaced."""
    value: float
    lower: float
    upper: float
    age_minutes: float               # time since the newest trusted value it is based on
    method: str
    reason: str


class Imputation(BaseModel):
    channels: dict[str, ImputedValue]


class VerdictResult(BaseModel):
    verdict: Verdict
    confidence: float                       # 0.0 - 1.0
    reason: str                             # plain English
    health_score: Optional[float] = None    # 0-100
    service_date: Optional[date] = None     # projected service date
    imputed_temperature_c: Optional[float] = None
    imputed_pressure_hpa: Optional[float] = None
    imputed_humidity_pct: Optional[float] = None
    imputation: Optional[Imputation] = None  # the same estimates with their bands and reasons
    checks: list[CheckResult] = []
    notices: list[str] = []                 # informational events (e.g. a communication gap) that do not change the verdict


class StoredRecord(BaseModel):
    """One row: raw reading, verdict and imputed value side by side."""
    id: int
    reading: Reading
    verdict: Optional[VerdictResult] = None
