"""Fake sensor node, used only if the hardware fails. It behaves like firmware/node/node.ino:

  * makes 1 Hz samples of T, P and RH, runs the L0 range check on each one,
  * leaves invalid samples out, averages the rest over one minute,
  * sends one reading per minute to /ingest, with the same `device_flags` names as the firmware.

The weather is fake (a daily cycle plus noise). Optional faults: frozen temperature, pressure dropout, or
out-of-range humidity glitches.

Usage:
    python simnode.py --station S1 --minutes 120 --speed 0
    python simnode.py --station S1 --minutes 90 --fault frozen --fault-start 30 --fault-length 45
"""
from __future__ import annotations

import argparse
import math
import os
import time
from datetime import datetime, timedelta
from typing import Optional, Sequence

import httpx
import numpy as np

from atmos.config import load_settings
from atmos.physics import dew_point_c
from atmos.schema import CHANNELS

FAULTS = ("none", "frozen", "dropout", "glitch")


class FrozenTracker:
    """The device's frozen counter (finish_minute() in firmware/node/atmos_l0.h): the same minute mean, as a
    32-bit float, `frozen_minutes` times in a row. A missing minute breaks the run."""

    def __init__(self, minutes: int):
        self.minutes = minutes
        self.last: dict[str, float] = {}
        self.run: dict[str, int] = {ch: 0 for ch in CHANNELS}

    def update(self, values: dict) -> list[str]:
        flags = []
        for ch in CHANNELS:
            v = values[ch]
            if v is None:
                self.last.pop(ch, None)
                self.run[ch] = 0
                continue
            v32 = float(np.float32(v))
            self.run[ch] = self.run[ch] + 1 if self.last.get(ch) == v32 else 0
            self.last[ch] = v32
            if self.minutes > 0 and self.run[ch] + 1 >= self.minutes:
                flags.append(f"frozen:{ch}")
        return flags


def aggregate_minute(samples: Sequence[Sequence[Optional[float]]], settings: dict,
                     frozen: Optional[FrozenTracker] = None) -> tuple[dict, list[str]]:
    """The device's minute logic. `samples` is a list of (temperature, pressure, humidity), None or NaN = failed
    read. Returns ({channel: mean or None}, device_flags). Mirrors finish_minute() in atmos_l0.h. Pass a
    FrozenTracker (kept between minutes) to get the frozen flag too."""
    ranges, node = settings["physics"]["ranges"], settings["node"]
    sums = {ch: 0.0 for ch in CHANNELS}
    valid = {ch: 0 for ch in CHANNELS}
    range_hit = {ch: False for ch in CHANNELS}
    for sample in samples:
        for ch, v in zip(CHANNELS, sample):
            if v is None or (isinstance(v, float) and math.isnan(v)):
                continue
            lo, hi = ranges[ch]
            if v < lo or v > hi:
                range_hit[ch] = True
                continue
            sums[ch] += v
            valid[ch] += 1
    values: dict[str, Optional[float]] = {}
    flags: list[str] = []
    for ch in CHANNELS:
        values[ch] = sums[ch] / valid[ch] if (valid[ch] >= node["min_valid_samples"] and valid[ch] > 0) else None
        if range_hit[ch]:
            flags.append(f"range:{ch}")
        if values[ch] is None:
            flags.append(f"few_valid:{ch}")
    if frozen is not None:
        flags += frozen.update(values)
    t, rh = values["temperature_c"], values["humidity_pct"]
    if t is not None and rh is not None and rh > 0 and dew_point_c(t, rh) > t + settings["physics"]["dew_point_tolerance_c"]:
        flags.append("dew_point")
    # same order as node.ino: all range flags first (per channel), then few_valid, then dew_point
    flags.sort(key=lambda f: (0 if f.startswith("range") else 1 if f.startswith("few_valid") else 2 if f.startswith("frozen") else 3,
                              CHANNELS.index(f.split(":")[1]) if ":" in f else 0))
    return values, flags


def simulate_minute(settings: dict, start: datetime, rng: np.random.Generator, fault: str,
                    faulty: bool, frozen_temperature: Optional[float]) -> list[tuple]:
    """60 one-second samples starting at `start`."""
    syn = settings["evaluate"]["synthetic"]
    n = int(settings["node"]["aggregate_seconds"] / settings["node"]["sample_interval_seconds"])
    out = []
    for i in range(n):
        ts = start + timedelta(seconds=i * settings["node"]["sample_interval_seconds"])
        cycle = math.sin(2 * math.pi * (ts.hour + ts.minute / 60.0 - 9) / 24)
        t = syn["temperature"]["mean"] + syn["temperature"]["daily_amp"] * cycle + float(rng.normal(0, syn["temperature"]["noise"]))
        p = syn["pressure"]["mean"] + float(rng.normal(0, syn["pressure"]["noise"]))
        rh = syn["humidity"]["mean"] - syn["humidity"]["daily_amp"] * cycle + float(rng.normal(0, syn["humidity"]["noise"]))
        if faulty and fault == "frozen":
            t = frozen_temperature
        elif faulty and fault == "dropout":
            p = float("nan")
        elif faulty and fault == "glitch" and rng.random() < 0.1:
            rh = 255.0
        out.append((t, p, rh))
    return out


def run(settings: dict, station: str, url: str, minutes: int, start: datetime, speed: float, fault: str,
        fault_start: int, fault_length: int, client: Optional[httpx.Client] = None,
        sleep=time.sleep) -> list[dict]:
    """Send `minutes` readings. Returns the payloads that were sent."""
    rng = np.random.default_rng(settings["seed"])
    client = client or httpx.Client(base_url=url, timeout=settings["node"]["post_timeout_seconds"],
                                    headers={"X-API-Key": os.environ["ATMOS_API_KEY"]} if os.environ.get("ATMOS_API_KEY") else {})
    sent = []
    frozen_value: Optional[float] = None
    tracker = FrozenTracker(settings["node"]["frozen_minutes"])
    for m in range(minutes):
        t0 = start + timedelta(minutes=m)
        faulty = fault != "none" and fault_start <= m < fault_start + fault_length
        samples = simulate_minute(settings, t0, rng, fault, faulty, frozen_value)
        if fault == "frozen" and frozen_value is None and m + 1 >= fault_start:
            frozen_value = samples[0][0]
        values, flags = aggregate_minute(samples, settings, tracker)
        payload = {"station_id": station,
                   "timestamp": (t0 + timedelta(seconds=settings["node"]["aggregate_seconds"])).strftime("%Y-%m-%dT%H:%M:%S"),
                   **values, "device_flags": flags}
        resp = client.post("/ingest", json=payload)
        resp.raise_for_status()
        sent.append(payload)
        if speed > 0:
            sleep(settings["node"]["aggregate_seconds"] / speed)
    return sent


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Fake AtmosGuard node.")
    ap.add_argument("--station", required=True)
    ap.add_argument("--url", default=None, help="API address (default: dashboard.api_url in settings.yaml)")
    ap.add_argument("--minutes", type=int, default=60)
    ap.add_argument("--start", default="2026-01-01T00:00:00", help="UTC start, ISO format")
    ap.add_argument("--speed", type=float, default=0.0, help="1 = real time, 60 = a minute per second, 0 = fastest")
    ap.add_argument("--fault", choices=FAULTS, default="none")
    ap.add_argument("--fault-start", type=int, default=30, help="minute the fault begins")
    ap.add_argument("--fault-length", type=int, default=30, help="minutes the fault lasts")
    args = ap.parse_args(argv)
    settings = load_settings()
    url = args.url or settings["dashboard"]["api_url"]
    try:
        sent = run(settings, args.station, url, args.minutes, datetime.fromisoformat(args.start), args.speed,
                   args.fault, args.fault_start, args.fault_length)
    except httpx.HTTPError as e:
        print(f"Cannot reach the API at {url}: {e}")
        return 2
    print(f"Sent {len(sent)} readings to {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
