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


def test_mixed_time_zones_no_longer_break_a_station():
    """Found by fuzzing: a zone-aware timestamp after a naive one crashed every later reading."""
    c = _client()
    for stamp in ("2026-01-01T00:00:00", "2026-01-01T00:01:00Z", "2026-01-01T02:02:00+02:00", "2026-01-01T00:03:00"):
        assert c.post("/ingest", json={**PAYLOAD, "timestamp": stamp}).status_code == 200
    stored = c.get("/latest", params={"limit": 10}).json()
    assert all(r["reading"]["timestamp"].endswith(("00:00", "01:00", "02:00", "03:00")) for r in stored)


def test_absurd_numbers_get_a_fault_verdict_not_a_server_error():
    r = _client().post("/ingest", json={**PAYLOAD, "temperature_c": -243.12, "pressure_hpa": 1e308, "humidity_pct": 1e308})
    assert r.status_code == 200 and r.json()["verdict"]["verdict"] == "FAULT"


def test_nan_and_infinity_in_the_json_are_stored_as_missing_not_lost_silently():
    c = _client()
    r = c.post("/ingest", content='{"station_id":"S1","timestamp":"2026-01-01T00:00:00","temperature_c":NaN,'
                                  '"pressure_hpa":Infinity,"humidity_pct":50}', headers={"content-type": "application/json"})
    body = r.json()
    assert r.status_code == 200 and body["reading"]["temperature_c"] is None and body["reading"]["pressure_hpa"] is None
    assert body["verdict"]["verdict"] == "FAULT" and "temperature_c" in body["verdict"]["reason"]


def test_a_timestamp_ahead_of_the_server_clock_is_flagged():
    """The server clock is now passed to the health checks (it was never passed before)."""
    from datetime import datetime
    c = TestClient(create_app(store=SQLiteStore(), settings=load_settings(), clock=lambda: datetime(2026, 1, 1, 12, 0)))
    ok = c.post("/ingest", json={**PAYLOAD, "timestamp": "2026-01-01T11:59:00"}).json()
    future = c.post("/ingest", json={**PAYLOAD, "timestamp": "2026-01-01T13:00:00"}).json()
    assert not any(k["check"] == "timestamp" and k["flagged"] for k in ok["verdict"]["checks"])
    assert future["verdict"]["verdict"] == "SUSPECT" and "ahead of the server clock" in future["verdict"]["reason"]


def test_an_internal_error_becomes_a_visible_alert_and_the_raw_reading_is_kept(monkeypatch):
    from atmos.fusion import Pipeline
    pipe = Pipeline(load_settings())
    monkeypatch.setattr(pipe, "process", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    c = TestClient(create_app(store=SQLiteStore(), settings=load_settings(), pipeline=pipe))
    body = c.post("/ingest", json=PAYLOAD).json()
    assert body["reading"]["temperature_c"] == 20.0
    assert body["verdict"]["verdict"] == "SUSPECT" and "internal error: RuntimeError" in body["verdict"]["reason"]
    assert [k["check"] for k in body["verdict"]["checks"]] == ["pipeline_error"]
    assert len(c.get("/alerts").json()) == 1


def test_after_a_restart_the_history_and_stations_come_back_from_the_database(tmp_path):
    path = str(tmp_path / "db.sqlite")
    first = TestClient(create_app(store=SQLiteStore(path), settings=load_settings()))
    for r in synthetic_readings(days=1, cadence=15, noise_t=0.1)[:60]:
        first.post("/ingest", json={**r.model_dump(mode="json"), "temperature_c": 20.0})     # temperature stuck
    second = TestClient(create_app(store=SQLiteStore(path), settings=load_settings()))     # "restart"
    assert second.get("/status").json()["stations_seen"] == ["S1"]
    assert second.get("/health", params={"station_id": "S1"}).status_code == 200
    nxt = synthetic_readings(days=1, cadence=15, noise_t=0.1)[60]
    v = second.post("/ingest", json={**nxt.model_dump(mode="json"), "temperature_c": 20.0}).json()["verdict"]
    assert v["verdict"] == "FAULT" and "not changed" in v["reason"]                          # it remembered the history
    assert len(second.get("/latest", params={"limit": 1000}).json()) == 61                   # warm-up wrote nothing


def test_replay_request_is_validated():
    c = _client()
    for body in ({"csv_path": "data/x.csv", "limit": -5}, {"csv_path": "data/x.csv", "limit": 0},
                 {"csv_path": "data/x.csv", "speed": -1}, {"csv_path": "data/x.csv", "station_id": ""}):
        assert c.post("/replay", json=body).status_code == 422
