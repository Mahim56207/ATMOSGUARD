"""Tests for atmos/store.py: raw stays untouched, verdict stored beside it."""
from datetime import datetime

from atmos.schema import Reading, Verdict, VerdictResult
from atmos.store import SQLiteStore


def _reading(**kw):
    base = dict(station_id="S1", timestamp=datetime(2026, 1, 1, 12, 0),
                temperature_c=20.0, pressure_hpa=1000.0, humidity_pct=50.0)
    base.update(kw)
    return Reading(**base)


def test_raw_reading_kept_unchanged_after_verdict():
    store = SQLiteStore()
    rid = store.add_reading(_reading())
    store.set_verdict(rid, VerdictResult(verdict=Verdict.FAULT, confidence=0.9, reason="test",
                                         imputed_temperature_c=19.5))
    rec = store.get(rid)
    assert rec.reading.temperature_c == 20.0          # raw untouched
    assert rec.verdict.verdict == Verdict.FAULT
    assert rec.verdict.imputed_temperature_c == 19.5  # imputed beside raw


def test_dropout_channel_stored_as_none():
    store = SQLiteStore()
    rid = store.add_reading(_reading(pressure_hpa=None))
    assert store.get(rid).reading.pressure_hpa is None


def test_alerts_exclude_valid_and_counts():
    store = SQLiteStore()
    a = store.add_reading(_reading())
    b = store.add_reading(_reading(timestamp=datetime(2026, 1, 1, 12, 1)))
    store.set_verdict(a, VerdictResult(verdict=Verdict.VALID, confidence=1.0, reason="ok"))
    store.set_verdict(b, VerdictResult(verdict=Verdict.SUSPECT, confidence=0.5, reason="odd"))
    assert [r.id for r in store.alerts()] == [b]
    assert store.counts() == {"VALID": 1, "SUSPECT": 1}


def test_imputation_and_device_flags_are_stored_beside_the_raw_values():
    from atmos.schema import Imputation, ImputedValue
    store = SQLiteStore()
    rid = store.add_reading(_reading(pressure_hpa=None, device_flags=["valid_samples:pressure_hpa"]))
    imp = Imputation(channels={"pressure_hpa": ImputedValue(value=1000.0, lower=999.0, upper=1001.0, age_minutes=15,
                                                            method="m", reason="r")})
    store.set_verdict(rid, VerdictResult(verdict=Verdict.FAULT, confidence=0.9, reason="x",
                                         imputed_pressure_hpa=1000.0, imputation=imp))
    rec = store.get(rid)
    assert rec.reading.pressure_hpa is None and rec.reading.device_flags == ["valid_samples:pressure_hpa"]
    assert rec.verdict.imputation.channels["pressure_hpa"].upper == 1001.0


def test_reading_without_device_flags_reads_back_as_none():
    store = SQLiteStore()
    assert store.get(store.add_reading(_reading())).reading.device_flags is None


def test_old_database_without_the_new_columns_is_migrated_and_keeps_its_rows(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite"
    db = sqlite3.connect(path)
    db.executescript("""CREATE TABLE records (id INTEGER PRIMARY KEY AUTOINCREMENT, station_id TEXT NOT NULL,
        timestamp TEXT NOT NULL, raw_temperature_c REAL, raw_pressure_hpa REAL, raw_humidity_pct REAL,
        verdict TEXT, confidence REAL, reason TEXT, health_score REAL, service_date TEXT,
        imputed_temperature_c REAL, imputed_pressure_hpa REAL, imputed_humidity_pct REAL, checks_json TEXT);
        INSERT INTO records (station_id, timestamp, raw_temperature_c, raw_pressure_hpa, raw_humidity_pct, verdict,
        confidence, reason, checks_json) VALUES ('S1', '2026-01-01T12:00:00', 20.5, 1000.0, 50.0, 'VALID', 0.9, 'ok', '[]');""")
    db.commit()
    db.close()
    store = SQLiteStore(str(path))
    old = store.get(1)
    assert old.reading.temperature_c == 20.5 and old.verdict.verdict == Verdict.VALID and old.verdict.imputation is None
    rid = store.add_reading(_reading(device_flags=["x"]))
    assert store.get(rid).reading.device_flags == ["x"]
    SQLiteStore(str(path))                                                  # opening it again is harmless
