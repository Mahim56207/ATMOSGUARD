"""API step-1 tests: /ingest returns a stub verdict and stores the raw reading."""
from fastapi.testclient import TestClient

from api import create_app
from atmos.store import SQLiteStore

PAYLOAD = {"station_id": "S1", "timestamp": "2026-01-01T12:00:00",
           "temperature_c": 20.0, "pressure_hpa": 1000.0, "humidity_pct": 50.0}


def _client():
    return TestClient(create_app(store=SQLiteStore(), settings={"layers": {}}))


def test_ingest_returns_stub_verdict_and_keeps_raw():
    c = _client()
    r = c.post("/ingest", json=PAYLOAD)
    assert r.status_code == 200
    body = r.json()
    assert body["reading"]["temperature_c"] == 20.0
    assert body["verdict"]["verdict"] == "VALID"
    assert body["verdict"]["confidence"] == 0.0
    assert "Stub" in body["verdict"]["reason"]


def test_latest_and_status_and_placeholders():
    c = _client()
    c.post("/ingest", json=PAYLOAD)
    assert len(c.get("/latest").json()) == 1
    assert c.get("/health").json() == {"status": "ok"}
    assert c.get("/status").json()["verdict_counts"] == {"VALID": 1}
    assert c.post("/replay").status_code == 501
    assert c.post("/inject").status_code == 501
    assert c.get("/metrics").status_code == 501


def test_ingest_rejects_bad_payload():
    assert _client().post("/ingest", json={"station_id": "S1"}).status_code == 422
