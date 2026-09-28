"""Tests for atmos/livefault.py and the /inject and /metrics routes."""
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import api
from atmos.livefault import LiveInjector
from atmos.store import SQLiteStore
from tests.conftest import make_reading


def mk(minute, t=20.0, p=1000.0, rh=50.0):
    return make_reading(minute, t, p, rh)


def test_nothing_armed_means_nothing_changes(settings):
    r = mk(0)
    assert LiveInjector(settings).apply(r) is r


def test_frozen_holds_the_last_value_seen_before_the_fault(settings):
    inj = LiveInjector(settings)
    inj.apply(mk(0, t=18.0))
    inj.add("S1", "frozen", "temperature_c", samples=3)
    out = [inj.apply(mk(m, t=20.0 + m)).temperature_c for m in (1, 2, 3, 4)]
    assert out == [18.0, 18.0, 18.0, 24.0]                              # three held, then the sensor is back


def test_spike_is_one_sample_and_of_the_configured_size(settings):
    inj = LiveInjector(settings)
    inj.add("S1", "spike", "pressure_hpa")
    a, b = inj.apply(mk(0)), inj.apply(mk(1))
    assert abs(a.pressure_hpa - 1000.0) == pytest.approx(settings["injector"]["magnitude"]["spike"]["pressure_hpa"])
    assert b.pressure_hpa == 1000.0


def test_step_and_drift_and_dropout(settings):
    inj = LiveInjector(settings)
    inj.add("S1", "step", "humidity_pct", samples=2, magnitude=10.0)
    steps = [inj.apply(mk(m)).humidity_pct for m in range(3)]
    assert sorted(abs(x - 50.0) for x in steps) == [0.0, 10.0, 10.0]
    inj = LiveInjector(settings)
    inj.add("S1", "drift", "temperature_c", samples=4, magnitude=4.0)
    offs = [abs(inj.apply(mk(m)).temperature_c - 20.0) for m in range(4)]
    assert offs == pytest.approx([1.0, 2.0, 3.0, 4.0])                   # a ramp
    inj = LiveInjector(settings)
    inj.add("S1", "dropout", "pressure_hpa", samples=2)
    assert [inj.apply(mk(m)).pressure_hpa for m in range(3)] == [None, None, 1000.0]


def test_only_the_armed_station_is_touched(settings):
    inj = LiveInjector(settings)
    inj.add("S2", "dropout", "pressure_hpa")
    assert inj.apply(mk(0)).pressure_hpa == 1000.0
    assert inj.any_active()


def test_bad_requests_are_refused(settings):
    inj = LiveInjector(settings)
    with pytest.raises(ValueError):
        inj.add("S1", "explode", "temperature_c")
    with pytest.raises(ValueError):
        inj.add("S1", "spike", "wind_speed")


def test_input_reading_object_is_not_mutated(settings):
    inj = LiveInjector(settings)
    inj.add("S1", "dropout", "pressure_hpa")
    r = mk(0)
    inj.apply(r)
    assert r.pressure_hpa == 1000.0


# ---- through the API --------------------------------------------------------------------------------
def _client(settings):
    return TestClient(api.create_app(store=SQLiteStore(), settings=settings))


def _payload(minute, **kw):
    ts = datetime(2026, 1, 1, 12, 0) + timedelta(minutes=minute)
    return {"station_id": "S1", "timestamp": ts.isoformat(), "temperature_c": 20.0, "pressure_hpa": 1000.0,
            "humidity_pct": 50.0, **kw}


def test_inject_then_ingest_gives_a_fault_and_the_altered_value_is_stored(settings):
    c = _client(settings)
    armed = c.post("/inject", json={"station_id": "S1", "fault_type": "dropout", "channel": "pressure_hpa", "samples": 1})
    assert armed.status_code == 200 and armed.json()["armed"]["fault_type"] == "dropout"
    body = c.post("/ingest", json=_payload(0)).json()
    assert body["reading"]["pressure_hpa"] is None and body["verdict"]["verdict"] == "FAULT"
    assert c.post("/ingest", json=_payload(1)).json()["verdict"]["verdict"] != "FAULT"     # it lasted one reading
    listed = c.get("/inject").json()["injections"]
    assert len(listed) == 1 and listed[0]["active"] is False


def test_inject_rejects_unknown_fault_or_channel(settings):
    c = _client(settings)
    assert c.post("/inject", json={"station_id": "S1", "fault_type": "explode", "channel": "temperature_c"}).status_code == 400
    assert c.post("/inject", json={"station_id": "S1", "fault_type": "spike", "channel": "wind"}).status_code == 400


def test_clear_removes_armed_faults(settings):
    c = _client(settings)
    c.post("/inject", json={"station_id": "S1", "fault_type": "dropout", "channel": "pressure_hpa", "samples": 5})
    assert c.delete("/inject").json() == {"removed": 1}
    assert c.post("/ingest", json=_payload(0)).json()["reading"]["pressure_hpa"] == 1000.0


def test_metrics_serves_the_summary_or_404(settings, tmp_path, monkeypatch):
    monkeypatch.setattr(api, "REPO_ROOT", tmp_path)
    c = _client(settings)
    assert c.get("/metrics").status_code == 404
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "summary.json").write_text(json.dumps({"hello": "world"}))
    assert c.get("/metrics").json() == {"hello": "world"}
