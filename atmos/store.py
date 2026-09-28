"""SQLite storage (Postgres swappable behind the same `Store` interface).

One row per reading. Raw values, verdict and imputed values sit side by side.
Raw columns are written once and never updated or deleted.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Optional

from .schema import CheckResult, Imputation, Reading, StoredRecord, Verdict, VerdictResult


class Store(ABC):
    @abstractmethod
    def add_reading(self, reading: Reading) -> int: ...

    @abstractmethod
    def get(self, record_id: int) -> Optional[StoredRecord]: ...

    @abstractmethod
    def set_verdict(self, record_id: int, result: VerdictResult) -> None: ...

    @abstractmethod
    def latest(self, station_id: Optional[str] = None, limit: int = 1) -> list[StoredRecord]: ...

    @abstractmethod
    def alerts(self, station_id: Optional[str] = None, limit: int = 50) -> list[StoredRecord]: ...

    @abstractmethod
    def stations(self) -> list[str]: ...

    @abstractmethod
    def recent_readings(self, station_id: str, limit: int) -> list[Reading]:
        """The newest `limit` raw readings of a station, oldest first."""

    @abstractmethod
    def counts(self) -> dict[str, int]: ...


_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    station_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    raw_temperature_c REAL,
    raw_pressure_hpa REAL,
    raw_humidity_pct REAL,
    verdict TEXT,
    confidence REAL,
    reason TEXT,
    health_score REAL,
    service_date TEXT,
    imputed_temperature_c REAL,
    imputed_pressure_hpa REAL,
    imputed_humidity_pct REAL,
    checks_json TEXT,
    imputation_json TEXT,
    raw_device_flags TEXT
);
CREATE INDEX IF NOT EXISTS idx_records_station_ts ON records (station_id, timestamp);
"""


def _locked(fn):
    """Run a store method while holding the store's lock (the connection is shared by API threads)."""
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return fn(self, *args, **kwargs)
    wrapper.__name__, wrapper.__doc__ = fn.__name__, fn.__doc__
    return wrapper


class SQLiteStore(Store):
    def __init__(self, path: str = ":memory:"):
        # check_same_thread=False: FastAPI may call from worker threads, so every call below takes this lock.
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Databases made by an older version get the columns added. Existing rows are kept as they are."""
        have = {r["name"] for r in self._db.execute("PRAGMA table_info(records)").fetchall()}
        for column in ("imputation_json", "raw_device_flags"):
            if column not in have:
                self._db.execute(f"ALTER TABLE records ADD COLUMN {column} TEXT")
        self._db.commit()

    @_locked
    def add_reading(self, reading: Reading) -> int:
        cur = self._db.execute(
            "INSERT INTO records (station_id, timestamp, raw_temperature_c, raw_pressure_hpa, raw_humidity_pct,"
            " raw_device_flags) VALUES (?, ?, ?, ?, ?, ?)",
            (reading.station_id, reading.timestamp.isoformat(),
             reading.temperature_c, reading.pressure_hpa, reading.humidity_pct,
             None if reading.device_flags is None else json.dumps(reading.device_flags)),
        )
        self._db.commit()
        return int(cur.lastrowid)

    @_locked
    def set_verdict(self, record_id: int, result: VerdictResult) -> None:
        """Writes verdict and imputed columns only. Raw columns are never touched."""
        self._db.execute(
            "UPDATE records SET verdict=?, confidence=?, reason=?, health_score=?, service_date=?,"
            " imputed_temperature_c=?, imputed_pressure_hpa=?, imputed_humidity_pct=?, checks_json=?,"
            " imputation_json=? WHERE id=?",
            (result.verdict.value, result.confidence, result.reason, result.health_score,
             result.service_date.isoformat() if result.service_date else None,
             result.imputed_temperature_c, result.imputed_pressure_hpa, result.imputed_humidity_pct,
             _dump_checks(result.checks),
             None if result.imputation is None else result.imputation.model_dump_json(), record_id),
        )
        self._db.commit()

    @_locked
    def get(self, record_id: int) -> Optional[StoredRecord]:
        row = self._db.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        return _row_to_record(row) if row else None

    @_locked
    def latest(self, station_id: Optional[str] = None, limit: int = 1) -> list[StoredRecord]:
        return self._query("", station_id, limit)

    @_locked
    def alerts(self, station_id: Optional[str] = None, limit: int = 50) -> list[StoredRecord]:
        return self._query("verdict IS NOT NULL AND verdict != 'VALID'", station_id, limit)

    @_locked
    def stations(self) -> list[str]:
        return [r["station_id"] for r in self._db.execute(
            "SELECT DISTINCT station_id FROM records ORDER BY station_id").fetchall()]

    @_locked
    def recent_readings(self, station_id: str, limit: int) -> list[Reading]:
        rows = self._db.execute("SELECT * FROM records WHERE station_id = ? ORDER BY id DESC LIMIT ?",
                                (station_id, limit)).fetchall()
        return [_row_to_record(r).reading for r in reversed(rows)]        # arrival order, oldest first

    @_locked
    def counts(self) -> dict[str, int]:
        rows = self._db.execute(
            "SELECT COALESCE(verdict, 'PENDING') AS v, COUNT(*) AS n FROM records GROUP BY v"
        ).fetchall()
        return {r["v"]: r["n"] for r in rows}

    def _query(self, where: str, station_id: Optional[str], limit: int) -> list[StoredRecord]:
        clauses, params = ([where] if where else []), []
        if station_id:
            clauses.append("station_id = ?")
            params.append(station_id)
        sql = "SELECT * FROM records"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY timestamp DESC, id DESC LIMIT ?"
        params.append(limit)
        return [_row_to_record(r) for r in self._db.execute(sql, params).fetchall()]


def _dump_checks(checks: list[CheckResult]) -> str:
    return json.dumps([c.model_dump() for c in checks])


def _row_to_record(r: sqlite3.Row) -> StoredRecord:
    reading = Reading(
        station_id=r["station_id"], timestamp=datetime.fromisoformat(r["timestamp"]),
        temperature_c=r["raw_temperature_c"], pressure_hpa=r["raw_pressure_hpa"],
        humidity_pct=r["raw_humidity_pct"],
        device_flags=None if r["raw_device_flags"] is None else json.loads(r["raw_device_flags"]),
    )
    verdict = None
    if r["verdict"] is not None:
        verdict = VerdictResult(
            verdict=Verdict(r["verdict"]), confidence=r["confidence"], reason=r["reason"],
            health_score=r["health_score"],
            service_date=date.fromisoformat(r["service_date"]) if r["service_date"] else None,
            imputed_temperature_c=r["imputed_temperature_c"],
            imputed_pressure_hpa=r["imputed_pressure_hpa"],
            imputed_humidity_pct=r["imputed_humidity_pct"],
            imputation=None if r["imputation_json"] is None else Imputation.model_validate_json(r["imputation_json"]),
            checks=[CheckResult(**c) for c in json.loads(r["checks_json"] or "[]")],
        )
    return StoredRecord(id=r["id"], reading=reading, verdict=verdict)
