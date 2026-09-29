"""Operational settings: API key on writes, rate limit on /ingest, data retention, richer /status."""
import copy
from datetime import datetime

from fastapi.testclient import TestClient

import api
from atmos.store import SQLiteStore

PAYLOAD = {"station_id": "S1", "timestamp": "2026-01-01T12:00:00", "temperature_c": 20.0, "pressure_hpa": 1000.0, "humidity_pct": 50.0}


def client(settings, **api_cfg):
    s = copy.deepcopy(settings)
    s["api"].update(api_cfg)
    return TestClient(api.create_app(store=SQLiteStore(), settings=s)), s


def test_without_a_key_configured_everything_is_open(settings, monkeypatch):
    monkeypatch.delenv("ATMOS_API_KEY", raising=False)
    c, _ = client(settings)
    assert c.post("/ingest", json=PAYLOAD).status_code == 200
    assert c.get("/status").json()["auth_required_for_writes"] is False


def test_with_a_key_writes_need_it_and_reads_do_not(settings, monkeypatch):
    monkeypatch.setenv("ATMOS_API_KEY", "s3cret")
    c, _ = client(settings)
    assert c.post("/ingest", json=PAYLOAD).status_code == 401
    assert c.post("/ingest", json=PAYLOAD, headers={"X-API-Key": "wrong"}).status_code == 401
    assert c.post("/ingest", json=PAYLOAD, headers={"X-API-Key": "s3cret"}).status_code == 200
    assert c.delete("/inject").status_code == 401 and c.delete("/inject", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert c.post("/inject", json={"station_id": "S1", "fault_type": "spike", "channel": "temperature_c"}).status_code == 401
    assert c.get("/latest").status_code == 200 and c.get("/status").json()["auth_required_for_writes"] is True   # reads stay open


def test_rate_limit_on_ingest_per_client(settings, monkeypatch):
    monkeypatch.delenv("ATMOS_API_KEY", raising=False)
    c, _ = client(settings, rate_limit_per_minute=3)
    codes = [c.post("/ingest", json={**PAYLOAD, "timestamp": f"2026-01-01T12:0{i}:00"}).status_code for i in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    assert c.get("/latest").status_code == 200                       # only /ingest is limited


def test_retention_deletes_old_whole_records_and_keeps_the_rest(settings, monkeypatch):
    monkeypatch.delenv("ATMOS_API_KEY", raising=False)
    store = SQLiteStore()
    s = copy.deepcopy(settings)
    s["api"].update(retention_days=10, purge_every=3)
    now = datetime(2026, 3, 1)
    app = api.create_app(store=store, settings=s, clock=lambda: now)
    c = TestClient(app)
    for i, ts in enumerate(["2026-01-01T00:00:00", "2026-01-02T00:00:00", "2026-02-27T00:00:00"]):
        assert c.post("/ingest", json={**PAYLOAD, "timestamp": ts}).status_code == 200
    kept = [r.reading.timestamp.date().isoformat() for r in store.latest(None, 10)]
    assert kept == ["2026-02-27"]                                   # the two old records were purged on the 3rd reading


def test_store_purge_returns_the_count():
    from atmos.schema import Reading
    st = SQLiteStore()
    for d in (1, 2, 3):
        st.add_reading(Reading(station_id="S", timestamp=datetime(2026, 1, d), temperature_c=1.0))
    assert st.purge_older_than(datetime(2026, 1, 3)) == 2 and len(st.latest("S", 10)) == 1


def test_status_reports_uptime_counts_and_model_versions(settings, monkeypatch):
    monkeypatch.delenv("ATMOS_API_KEY", raising=False)
    c = TestClient(api.create_app(store=SQLiteStore()))
    c.post("/ingest", json={**PAYLOAD, "station_id": "BBI"})
    s = c.get("/status").json()
    assert s["readings_processed"] == 1 and s["uptime_seconds"] >= 0
    assert set(s["model_fingerprints"]["BBI"]) == {"normality", "iforest", "mahalanobis", "limits"}
    assert all(len(h) == 12 for h in s["model_fingerprints"]["BBI"].values())
