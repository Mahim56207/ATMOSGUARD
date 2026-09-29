"""Bring your own CSV: POST /replay/upload saves it under data/uploads/, checks it like any replay file and judges it."""
import copy
import time

import pytest
from fastapi.testclient import TestClient

import api
import dashboard as db
from atmos.config import load_settings
from atmos.store import SQLiteStore

CSV = "timestamp,temperature_c,pressure_hpa,humidity_pct,station_id\n" + "".join(
    f"2026-01-01T{h:02d}:00:00,{20 + h * 0.1:.1f},1010.{h % 10},{60 - h},MINE\n" for h in range(24))


@pytest.fixture
def client(tmp_path):
    s = copy.deepcopy(load_settings())
    s["replay"]["data_dir"] = str(tmp_path / "data")
    (tmp_path / "data").mkdir()
    return TestClient(api.create_app(store=SQLiteStore(), settings=s)), tmp_path


def _wait(c):
    for _ in range(100):
        if c.get("/replay").json()["state"] != "running":
            return c.get("/replay").json()
        time.sleep(0.05)
    raise AssertionError("replay did not finish")


def test_an_uploaded_csv_is_saved_and_judged(client):
    c, tmp = client
    r = c.post("/replay/upload", json={"filename": "my aws.csv", "text": CSV})
    assert r.status_code == 200 and r.json()["total"] == 24
    assert r.json()["saved_as"].startswith("data/uploads/") and r.json()["saved_as"].endswith("_my_aws.csv")
    assert (tmp / r.json()["saved_as"]).exists()
    done = _wait(c)
    assert done["state"] == "done" and sum(done["verdicts"].values()) == 24
    assert "MINE" in c.get("/status").json()["stations_seen"]
    assert any(p.startswith("data/uploads/") for p in c.get("/datasets").json()["datasets"])


def test_a_bad_file_is_refused_and_not_kept(client):
    c, tmp = client
    r = c.post("/replay/upload", json={"filename": "bad.csv", "text": "a,b\n1,2\n"})
    assert r.status_code == 400 and "missing columns" in r.json()["detail"]
    assert not list((tmp / "data" / "uploads").glob("*.csv"))


def test_a_path_in_the_name_cannot_escape_the_uploads_folder(client):
    c, tmp = client
    r = c.post("/replay/upload", json={"filename": "../../evil.csv", "text": CSV})
    assert r.status_code == 200
    assert (tmp / r.json()["saved_as"]).parent == tmp / "data" / "uploads"
    assert api.safe_upload_name("..\\..\\x y.txt") == "x_y.txt.csv" and api.safe_upload_name("...") == "upload.csv"


def test_too_big_a_file_is_refused(client):
    s = copy.deepcopy(load_settings())
    s["api"]["upload_max_bytes"] = 100
    s["replay"]["data_dir"] = str(client[1] / "data")
    small = TestClient(api.create_app(store=SQLiteStore(), settings=s))
    assert small.post("/replay/upload", json={"filename": "x.csv", "text": CSV}).status_code == 413


def test_the_fresh_folder_is_not_offered_for_replay(client):
    c, tmp = client
    (tmp / "data" / "fresh" / "real").mkdir(parents=True)
    (tmp / "data" / "fresh" / "real" / "X.csv").write_text(CSV)
    (tmp / "data" / "holdout").mkdir()
    (tmp / "data" / "holdout" / "Y.csv").write_text(CSV)
    (tmp / "data" / "ok.csv").write_text(CSV)
    listed = c.get("/datasets").json()["datasets"]
    assert any(p.endswith("ok.csv") for p in listed) and not any("fresh" in p or "holdout" in p for p in listed)


def test_dashboard_upload_body():
    body = db.upload_body("a.csv", "﻿timestamp,x\n".encode("utf-8"), "S9", 0.0, 500)
    assert body == {"filename": "a.csv", "text": "timestamp,x\n", "speed": 0.0, "learn_fraction": 0.5, "station_id": "S9", "limit": 500}
    assert db.upload_body("a.csv", b"t\n", "", 0.0, 0, learn=False)["learn_fraction"] == 0.0
    assert "station_id" not in db.upload_body("a.csv", b"t\n", "", 0.0, 0) and "limit" not in db.upload_body("a.csv", b"t\n", "", 0.0, 0)


def _long_csv(station, days, cadence=60, seed=1):
    from tests.conftest import synthetic_readings
    rd = synthetic_readings(days=days, cadence=cadence, seed=seed, station=station)
    return "timestamp,temperature_c,pressure_hpa,humidity_pct,station_id\n" + "".join(
        f"{r.timestamp.isoformat()},{r.temperature_c},{r.pressure_hpa},{r.humidity_pct},{r.station_id}\n" for r in rd), len(rd)


def test_an_unknown_station_learns_from_the_first_half_of_its_own_file_then_the_rest_is_judged(client):
    c, _ = client
    text, n = _long_csv("NEWSTN", days=40)
    r = c.post("/replay/upload", json={"filename": "long.csv", "text": text})
    assert r.status_code == 200
    body = r.json()
    assert body["learned"] and body["learned"][0]["station_id"] == "NEWSTN"
    assert body["learned"][0]["trained_on"] + body["total"] == n           # half to learn, the rest to judge
    assert any("learned from its first" in note for note in body["notes"])
    done = _wait(c)
    assert done["state"] == "done" and sum(done["verdicts"].values()) == body["total"]
    assert "NEWSTN" in c.get("/status").json()["models_loaded"]["normality"]
    assert done["verdicts"].get("VALID", 0) > 0.8 * body["total"]           # clean synthetic weather: mostly valid with its own limits


def test_a_short_file_is_not_learned_from_and_says_so(client):
    c, _ = client
    text, n = _long_csv("TINY", days=4)
    body = c.post("/replay/upload", json={"filename": "short.csv", "text": text}).json()
    assert body["learned"] == [] and body["total"] == n
    assert any("not enough history" in note for note in body["notes"])


def test_learning_can_be_switched_off(client):
    c, _ = client
    text, n = _long_csv("NOLEARN", days=40)
    body = c.post("/replay/upload", json={"filename": "x.csv", "text": text, "learn_fraction": 0}).json()
    assert body["learned"] == [] and body["total"] == n
