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
