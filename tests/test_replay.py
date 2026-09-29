"""Tests for replay.py: CSV reading, speed, holdout guard, and the /replay route."""
import copy
import csv
import threading
import time

import pytest
from fastapi.testclient import TestClient

import replay as rp
from api import create_app
from atmos.config import load_settings
from atmos.store import SQLiteStore
from tests.conftest import make_history, make_reading

HEADER = ["timestamp", "temperature_c", "pressure_hpa", "humidity_pct"]


def write_csv(path, rows, header=HEADER):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return path


def rows_for(readings):
    return [[r.timestamp.isoformat(), *("" if getattr(r, c) is None else getattr(r, c)
             for c in ("temperature_c", "pressure_hpa", "humidity_pct"))] for r in readings]


@pytest.fixture
def cfg(tmp_path):
    s = copy.deepcopy(load_settings())
    s["replay"]["data_dir"] = str(tmp_path / "data")
    return s


# ---- reading the CSV ------------------------------------------------------------------------------
def test_read_readings_parses_values_and_blanks_as_missing(cfg, tmp_path):
    f = write_csv(tmp_path / "data/clean/a.csv", [["2026-01-01T00:00:00", "20.5", "", "NaN"],
                                                   ["2026-01-01T00:01:00", "20.6", "1000.1", "55"]])
    a, b = rp.read_readings(f, cfg, "S1")
    assert (a.temperature_c, a.pressure_hpa, a.humidity_pct) == (20.5, None, None)
    assert (b.station_id, b.pressure_hpa) == ("S1", 1000.1)


def test_read_readings_uses_station_column_when_present(cfg, tmp_path):
    f = write_csv(tmp_path / "data/clean/a.csv", [["ST9", "2026-01-01T00:00:00", "20", "1000", "50"]],
                  header=["station_id", *HEADER])
    assert rp.read_readings(f, cfg)[0].station_id == "ST9"


def test_read_readings_needs_a_station_from_somewhere(cfg, tmp_path):
    f = write_csv(tmp_path / "data/clean/a.csv", [["2026-01-01T00:00:00", "20", "1000", "50"]])
    with pytest.raises(ValueError, match="station"):
        rp.read_readings(f, cfg)


def test_read_readings_reports_missing_columns_and_bad_lines(cfg, tmp_path):
    f = write_csv(tmp_path / "data/clean/a.csv", [["2026-01-01T00:00:00", "20"]], header=["timestamp", "temperature_c"])
    with pytest.raises(ValueError, match="missing columns"):
        rp.read_readings(f, cfg, "S1")
    g = write_csv(tmp_path / "data/clean/b.csv", [["2026-01-01T00:00:00", "20", "1000", "50"],
                                                   ["not-a-time", "20", "1000", "50"]])
    with pytest.raises(ValueError, match="line 3"):
        rp.read_readings(g, cfg, "S1")


def test_holdout_folder_is_refused(cfg, tmp_path):
    f = write_csv(tmp_path / "data/holdout/h.csv", [["2026-01-01T00:00:00", "20", "1000", "50"]])
    with pytest.raises(ValueError, match="holdout"):
        rp.read_readings(f, cfg, "S1")


def test_files_outside_the_data_folder_are_refused_for_the_api(cfg, tmp_path):
    f = write_csv(tmp_path / "elsewhere/a.csv", [["2026-01-01T00:00:00", "20", "1000", "50"]])
    with pytest.raises(ValueError, match="inside the data folder"):
        rp.read_readings(f, cfg, "S1", must_be_in_data_dir=True)
    assert rp.read_readings(f, cfg, "S1")            # fine from the command line


# ---- speed and stopping ---------------------------------------------------------------------------
def _delays(readings, speed, cap=5.0):
    waits = []
    rp.replay(readings, lambda r: "VALID", speed, cap, sleep=waits.append)
    return waits


def test_speed_scales_the_wait_between_readings():
    h = make_history(4, cadence=1)                   # 60 s apart in data time
    assert _delays(h, 1) == [5.0, 5.0, 5.0]          # real time would be 60 s, capped at 5
    assert _delays(h, 60) == [1.0, 1.0, 1.0]
    assert _delays(h, 600) == [pytest.approx(0.1)] * 3


def test_speed_zero_does_not_wait():
    assert _delays(make_history(4), 0) == []


def test_long_gaps_are_capped():
    readings = [make_reading(0), make_reading(600)]
    assert _delays(readings, 1, cap=2.0) == [2.0]


def test_stop_event_halts_the_replay():
    stop = threading.Event()
    seen = []

    def ingest(r):
        seen.append(r)
        if len(seen) == 3:
            stop.set()
        return "VALID"
    summary = rp.replay(make_history(10), ingest, 0, 5.0, stop=stop)
    assert summary.sent == 3 and summary.stopped


# ---- /replay route --------------------------------------------------------------------------------
def _client(cfg):
    return TestClient(create_app(store=SQLiteStore(), settings=cfg))


def _wait(client, state, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        body = client.get("/replay").json()
        if body["state"] == state:
            return body
        time.sleep(0.05)
    raise AssertionError(f"replay never reached {state}: {client.get('/replay').json()}")


def test_replay_route_runs_a_csv_through_the_pipeline(cfg, tmp_path):
    f = write_csv(tmp_path / "data/clean/a.csv", rows_for(make_history(20, cadence=1)))
    c = _client(cfg)
    assert c.post("/replay", json={"csv_path": str(f), "station_id": "S1"}).json()["total"] == 20
    done = _wait(c, "done")
    assert done["sent"] == 20 and sum(done["verdicts"].values()) == 20
    assert len(c.get("/latest", params={"limit": 100}).json()) == 20


def test_replay_route_refuses_holdout_and_outside_files_and_missing_files(cfg, tmp_path):
    hold = write_csv(tmp_path / "data/holdout/h.csv", rows_for(make_history(3)))
    out = write_csv(tmp_path / "elsewhere/o.csv", rows_for(make_history(3)))
    c = _client(cfg)
    assert c.post("/replay", json={"csv_path": str(hold), "station_id": "S1"}).status_code == 400
    assert c.post("/replay", json={"csv_path": str(out), "station_id": "S1"}).status_code == 400
    assert c.post("/replay", json={"csv_path": str(tmp_path / "data/nope.csv"), "station_id": "S1"}).status_code == 404
    assert c.get("/latest").json() == []             # nothing was ingested


def test_only_one_replay_at_a_time_and_it_can_be_stopped(cfg, tmp_path):
    cfg["replay"]["max_sleep_seconds"] = 0.2
    f = write_csv(tmp_path / "data/clean/a.csv", rows_for(make_history(200, cadence=1)))
    c = _client(cfg)
    body = {"csv_path": str(f), "station_id": "S1", "speed": 1.0}
    assert c.post("/replay", json=body).status_code == 200
    assert c.post("/replay", json=body).status_code == 409
    assert c.delete("/replay").json() == {"stopping": True}
    stopped = _wait(c, "stopped")
    assert 0 < stopped["sent"] < 200


def test_csv_saved_by_excel_with_a_byte_order_mark_is_read(cfg, tmp_path):
    f = tmp_path / "data/clean/bom.csv"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"\xef\xbb\xbf" + b"timestamp,temperature_c,pressure_hpa,humidity_pct\n2026-01-01T00:00:00Z,20,1000,50\n")
    r = rp.read_readings(f, cfg, "S1")[0]
    assert r.temperature_c == 20.0 and r.timestamp.tzinfo is None            # BOM tolerated, "Z" converted to UTC


def test_csv_values_that_are_not_numbers_are_missing(cfg, tmp_path):
    f = write_csv(tmp_path / "data/clean/a.csv", [["2026-01-01T00:00:00", "nan", "inf", "1e999"]])
    r = rp.read_readings(f, cfg, "S1")[0]
    assert (r.temperature_c, r.pressure_hpa, r.humidity_pct) == (None, None, None)
