"""Pydantic models for a reading and a verdict.

Inputs are only temperature (C), pressure (hPa), relative humidity (%), plus the
timestamp and station id. A channel may be None (dropout); it is stored as received.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class Verdict(str, Enum):
    VALID = "VALID"
    WEATHER = "WEATHER"
    SUSPECT = "SUSPECT"
    FAULT = "FAULT"


class Reading(BaseModel):
    station_id: str
    timestamp: datetime
    temperature_c: Optional[float] = None
    pressure_hpa: Optional[float] = None
    humidity_pct: Optional[float] = None


class CheckResult(BaseModel):
    """Result of one QC check. Every check gives a reason string, not just a boolean."""
    check: str
    flagged: bool
    reason: str


class VerdictResult(BaseModel):
    verdict: Verdict
    confidence: float                       # 0.0 - 1.0
    reason: str                             # plain English
    health_score: Optional[float] = None    # 0-100
    service_date: Optional[date] = None     # projected service date
    imputed_temperature_c: Optional[float] = None
    imputed_pressure_hpa: Optional[float] = None
    imputed_humidity_pct: Optional[float] = None
    checks: list[CheckResult] = []


class StoredRecord(BaseModel):
    """One row: raw reading, verdict and imputed value side by side."""
    id: int
    reading: Reading
    verdict: Optional[VerdictResult] = None
