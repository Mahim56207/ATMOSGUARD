"""End-to-end replay test: historical CSV -> /ingest -> verdicts, with the raw data kept unchanged."""
import csv

import pytest
from fastapi.testclient import TestClient

import replay as rp
from api import create_app
from atmos.config import load_settings
from atmos.injector import FaultSpec, inject
from atmos.store import SQLiteStore
from tests.conftest import synthetic_readings


def test_csv_with_injected_faults_is_replayed_through_the_full_pipeline(tmp_path):
    settings = load_settings()
    clean = synthetic_readings(days=2, cadence=15, seed=3, noise_t=0.1)
    faulted = inject(clean, settings, [FaultSpec("frozen", "temperature_c", 60),
                                       FaultSpec("dropout", "pressure_hpa", 120)])
    path = tmp_path / "day.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "temperature_c", "pressure_hpa", "humidity_pct"])
        for r in faulted.readings:
            w.writerow([r.timestamp.isoformat(), *("" if v is None else v for v in
                        (r.temperature_c, r.pressure_hpa, r.humidity_pct))])

    settings["replay"]["data_dir"] = str(tmp_path)
    client = TestClient(create_app(store=SQLiteStore(), settings=settings))
    readings = rp.read_readings(path, settings, "S1")
    summary = rp.replay(readings, rp.http_ingest("http://test", client), speed=0, max_sleep_seconds=0)

    assert summary.sent == len(clean)
    stored = sorted(client.get("/latest", params={"limit": 1000}).json(), key=lambda r: r["id"])
    assert len(stored) == len(clean)
    # raw values in the store are exactly what was in the file (dropout stays null, frozen stays frozen)
    for rec, sent in zip(stored, faulted.readings):
        assert rec["reading"]["temperature_c"] == sent.temperature_c
        assert rec["reading"]["pressure_hpa"] == sent.pressure_hpa
    # the injected faults were caught, and the clean start of the file was not
    assert any(r["verdict"]["verdict"] == "FAULT" and "not changed" in r["verdict"]["reason"] for r in stored[60:70])
    assert any(r["verdict"]["verdict"] == "FAULT" and "pressure_hpa" in r["verdict"]["reason"] for r in stored[120:122])
    assert all(r["verdict"]["verdict"] != "FAULT" for r in stored[:60])
    assert summary.verdicts["FAULT"] >= 2
    # health report exists after the run
    assert client.get("/health").json()["stations"]["S1"]["score"] is not None
