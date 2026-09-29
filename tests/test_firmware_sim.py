"""node.ino, executed on the laptop.

firmware/tests/sim replaces the Arduino-ESP32 pieces the sketch uses (virtual clock, scripted BME280, WiFi that can drop, an HTTP client that
records each POST) so the sketch's own setup() and loop() run for virtual minutes. What the sketch would have POSTed is then given to the real
API. This tests the sketch's logic (sampling, the L0 range check, the minute mean, the frozen counter, JSON, the offline queue, the clock guard)
and the node-to-API contract. It does not prove the sketch builds with the ESP32 toolchain or runs on the chip: that needs the hardware.
"""
import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import create_app
from atmos.config import load_settings
from atmos.schema import Reading
from atmos.store import SQLiteStore

ROOT = Path(__file__).resolve().parent.parent
GXX = shutil.which("g++") or shutil.which("clang++")
pytestmark = pytest.mark.skipif(GXX is None, reason="no C++ compiler on this machine")


@pytest.fixture(scope="module")
def node_bin(tmp_path_factory):
    d = tmp_path_factory.mktemp("sim")
    shutil.copy(ROOT / "firmware/node/secrets.example.h", d / "secrets.h")
    out = d / "run_node"
    subprocess.run([GXX, "-std=c++17", "-O1", "-Wall", "-Wextra", "-Wno-unused-parameter",
                    f"-I{ROOT / 'firmware/tests/sim'}", f"-I{ROOT / 'firmware/node'}", f"-I{d}",
                    "-x", "c++", "-o", str(out), str(ROOT / "firmware/tests/sim/run_node.cpp")], check=True, capture_output=True, text=True)
    return out


def run(node_bin, scenario, minutes):
    r = subprocess.run([str(node_bin), scenario, str(minutes)], capture_output=True, text=True, timeout=120, check=True)
    posts = [json.loads(l[len("POST_BODY "):]) for l in r.stdout.splitlines() if l.startswith("POST_BODY ")]
    serial = [l[len("SERIAL "):] for l in r.stdout.splitlines() if l.startswith("SERIAL ")]
    return posts, serial


def api_client():
    return TestClient(create_app(store=SQLiteStore(), settings=load_settings(), clock=lambda: datetime(2026, 1, 1, 23, 0)))


def test_a_clean_run_posts_one_valid_reading_per_minute_and_the_api_accepts_each(node_bin):
    posts, serial = run(node_bin, "clean", 11)               # the minute that closes at the very end of the run is not posted yet
    assert len(posts) == 10 and "WiFi connected" in serial and "clock synced" in serial
    stamps = [datetime.fromisoformat(p["timestamp"]) for p in posts]
    assert all((b - a).total_seconds() == 60 for a, b in zip(stamps, stamps[1:]))
    client = api_client()
    for p in posts:
        Reading(**p)                                              # the API's own schema
        assert p["device_flags"] == [] and 15 < p["temperature_c"] < 30
        assert client.post("/ingest", json=p).status_code == 200


def test_a_repeated_temperature_is_flagged_frozen_on_the_device_after_the_configured_minutes(node_bin):
    n = load_settings()["node"]["frozen_minutes"]
    posts, _ = run(node_bin, "stuck", n + 5)
    flagged = [i for i, p in enumerate(posts) if "frozen:temperature_c" in p["device_flags"]]
    assert flagged and flagged[0] >= n - 1 and not any("frozen:pressure_hpa" in p["device_flags"] for p in posts)


def test_an_impossible_pressure_is_kept_out_of_the_mean_and_the_api_calls_the_minute_a_fault(node_bin):
    posts, _ = run(node_bin, "out_of_range", 6)
    assert all(p["pressure_hpa"] is None or p["pressure_hpa"] < 1100 for p in posts)      # 1250 never leaves the device as a value
    missing = [p for p in posts if p["pressure_hpa"] is None]
    assert missing and all("range:pressure_hpa" in p["device_flags"] for p in missing)     # no valid sample: missing, and the reason is on the reading
    client = api_client()
    for p in posts[:2]:
        client.post("/ingest", json=p)
    verdict = client.post("/ingest", json=missing[0]).json()["verdict"]["verdict"]
    assert verdict == "FAULT"


def test_a_dead_sensor_sends_missing_values_not_zeros(node_bin):
    posts, _ = run(node_bin, "dead", 4)
    assert len(posts) == 3 and all(p["temperature_c"] is None and p["pressure_hpa"] is None and p["humidity_pct"] is None for p in posts)
    assert all(any(f.startswith("few_valid:") for f in p["device_flags"]) for p in posts)


def test_a_missing_sensor_is_reported_on_serial_and_the_minutes_still_close(node_bin):
    posts, serial = run(node_bin, "no_sensor", 4)
    assert any("BME280 not found" in s for s in serial)
    assert len(posts) == 3 and all(p["temperature_c"] is None for p in posts)


def test_a_short_network_outage_loses_nothing_and_delivers_in_order(node_bin):
    posts, _ = run(node_bin, "outage", 11)
    stamps = [p["timestamp"] for p in posts]
    assert len(posts) == 10 and stamps == sorted(stamps) and len(set(stamps)) == 10


def test_a_long_outage_drops_the_oldest_minutes_and_says_so(node_bin):
    posts, serial = run(node_bin, "long_outage", 45)
    slots = 30                                                        # BUFFER_SLOTS in config.h
    assert any("queue full" in s for s in serial)
    stamps = [p["timestamp"] for p in posts]
    assert stamps == sorted(stamps) and len(stamps) == len(set(stamps))
    assert len(stamps) < 44                                           # some minutes were lost, and the log says which policy
    first_after = datetime.fromisoformat(stamps[0])
    assert (datetime.fromisoformat(stamps[-1]) - first_after).total_seconds() >= (slots - 1) * 60 or len(stamps) >= slots


def test_nothing_is_reported_until_the_clock_is_synced(node_bin):
    posts, serial = run(node_bin, "unsynced", 5)
    assert posts == [] and any("clock not synced" in s for s in serial)
