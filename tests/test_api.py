"""API tests: /ingest runs the real pipeline and keeps raw, verdict and checks side by side."""
from fastapi.testclient import TestClient

from api import create_app
from atmos.config import load_settings
from atmos.store import SQLiteStore
from tests.conftest import synthetic_readings

PAYLOAD = {"station_id": "S1", "timestamp": "2026-01-01T12:00:00",
           "temperature_c": 20.0, "pressure_hpa": 1000.0, "humidity_pct": 50.0}


def _client():
    return TestClient(create_app(store=SQLiteStore(), settings=load_settings()))


def test_ingest_valid_reading():
    body = _client().post("/ingest", json=PAYLOAD).json()
    assert body["reading"]["temperature_c"] == 20.0
    assert body["verdict"]["verdict"] == "VALID" and body["verdict"]["confidence"] > 0
    assert len(body["verdict"]["checks"]) > 0                      # real checks ran, not a stub


def test_ingest_impossible_value_is_fault_and_raw_is_kept():
    c = _client()
    body = c.post("/ingest", json={**PAYLOAD, "humidity_pct": 140.0}).json()
    assert body["verdict"]["verdict"] == "FAULT" and "physical range" in body["verdict"]["reason"]
    assert body["reading"]["humidity_pct"] == 140.0                # raw never overwritten
    assert [a["id"] for a in c.get("/alerts").json()] == [body["id"]]


def test_ingest_dropout_is_fault_and_stored_as_null():
    body = _client().post("/ingest", json={**PAYLOAD, "pressure_hpa": None}).json()
    assert body["verdict"]["verdict"] == "FAULT" and body["reading"]["pressure_hpa"] is None


def test_status_health_and_placeholders():
    c = _client()
    assert c.get("/health").json() == {"stations": {}}
    assert c.get("/health", params={"station_id": "S1"}).status_code == 404
    c.post("/ingest", json=PAYLOAD)
    s = c.get("/status").json()
    assert s["status"] == "ok" and s["pipeline"] == "full" and s["verdict_counts"] == {"VALID": 1}
    assert "S1" in c.get("/health").json()["stations"]
    assert c.post("/replay").status_code == 422                       # needs a body now: it is a real route
    assert c.get("/replay").json()["state"] == "idle"
    assert c.post("/inject").status_code == 501 and c.get("/metrics").status_code == 501


def test_health_report_gets_a_score_after_enough_readings_and_opens_a_ticket_for_a_dead_sensor():
    c = _client()
    for r in synthetic_readings(days=1, cadence=15, noise_t=0.1):
        c.post("/ingest", json={**r.model_dump(mode="json"), "humidity_pct": 140.0})   # RH impossible every time
    rep = c.get("/health", params={"station_id": "S1"}).json()["stations"]["S1"]
    assert rep["score"] is not None and rep["score"] < 10
    assert rep["ticket"]["priority"] == "high" and "humidity_pct" in rep["ticket"]["channels"]


def test_ingest_rejects_bad_payload():
    assert _client().post("/ingest", json={"station_id": "S1"}).status_code == 422


def test_device_flags_from_a_node_are_accepted_and_stored_beside_the_raw_values():
    c = _client()
    body = c.post("/ingest", json={**PAYLOAD, "device_flags": ["range:humidity_pct"]}).json()
    assert body["reading"]["device_flags"] == ["range:humidity_pct"]
    assert c.get("/latest").json()[0]["reading"]["device_flags"] == ["range:humidity_pct"]


def test_a_reading_without_device_flags_still_works():
    assert _client().post("/ingest", json=PAYLOAD).json()["reading"]["device_flags"] is None


def test_dropout_response_carries_an_estimate_when_there_is_history():
    c = _client()
    for r in synthetic_readings(days=1, cadence=15, noise_t=0.1)[:30]:
        c.post("/ingest", json=r.model_dump(mode="json"))
    last = synthetic_readings(days=1, cadence=15, noise_t=0.1)[30]
    body = c.post("/ingest", json={**last.model_dump(mode="json"), "pressure_hpa": None}).json()
    est = body["verdict"]["imputation"]["channels"]["pressure_hpa"]
    assert body["reading"]["pressure_hpa"] is None and est["lower"] < est["value"] < est["upper"]
    assert body["verdict"]["imputed_pressure_hpa"] == est["value"]
