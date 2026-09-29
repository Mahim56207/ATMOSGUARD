"""The network view: /fleet lists every station, and the dashboard sorts it most urgent first."""
from fastapi.testclient import TestClient

import dashboard as db
from api import create_app
from atmos.config import load_settings
from atmos.store import SQLiteStore
from tests.conftest import synthetic_readings


def _client_with_two_stations():
    c = TestClient(create_app(store=SQLiteStore(), settings=load_settings()))
    for sid, seed in (("ALPHA", 1), ("BETA", 2)):
        for r in synthetic_readings(days=1, cadence=15, seed=seed, station=sid)[:60]:
            assert c.post("/ingest", json=r.model_dump(mode="json")).status_code == 200
    # BETA then reports an impossible humidity: its newest verdict is a FAULT
    last = synthetic_readings(days=1, cadence=15, seed=2, station="BETA")[60].model_dump(mode="json")
    c.post("/ingest", json={**last, "humidity_pct": 140.0})
    return c


def test_fleet_lists_every_station_with_its_newest_verdict_and_health():
    body = _client_with_two_stations().get("/fleet").json()
    rows = {s["station_id"]: s for s in body["stations"]}
    assert set(rows) == {"ALPHA", "BETA"}
    assert rows["BETA"]["verdict"] == "FAULT" and "physical range" in rows["BETA"]["reason"]
    assert rows["ALPHA"]["verdict"] in {"VALID", "WEATHER", "SUSPECT"}
    for s in rows.values():
        assert {"last_time", "health_score", "channel_scores", "service_date", "ticket", "recent_alerts"} <= set(s)


def test_fleet_is_empty_before_any_reading():
    c = TestClient(create_app(store=SQLiteStore(), settings=load_settings()))
    assert c.get("/fleet").json() == {"stations": []}


def test_fleet_rows_put_the_most_urgent_station_first():
    fleet = {"stations": [
        {"station_id": "A", "verdict": "VALID", "health_score": 95.0, "channel_scores": {}, "recent_alerts": 0},
        {"station_id": "B", "verdict": "FAULT", "health_score": 80.0, "channel_scores": {"pressure_hpa": 60.0}, "recent_alerts": 5,
         "ticket": {"priority": "high", "channels": ["pressure_hpa"], "reason": "x"}, "service_date": "2026-11-01"},
        {"station_id": "C", "verdict": "SUSPECT", "health_score": 40.0, "channel_scores": {}, "recent_alerts": 2},
        {"station_id": "D", "verdict": "SUSPECT", "health_score": 70.0, "channel_scores": {}, "recent_alerts": 1},
        {"station_id": "E", "verdict": None, "health_score": None, "channel_scores": {}},
    ]}
    rows = db.fleet_rows(fleet)
    assert [r["station"] for r in rows] == ["B", "C", "D", "A", "E"]           # FAULT, SUSPECT (lower health first), VALID, none yet
    assert rows[0]["ticket"] == "high: pressure" and rows[0]["service by"] == "2026-11-01" and rows[0]["P"] == 60.0
    assert rows[-1]["verdict"] == "no reading yet" and rows[-1]["ticket"] == "none"
