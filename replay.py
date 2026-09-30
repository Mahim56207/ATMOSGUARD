"""Stream a historical CSV into /ingest at a chosen speed.

CSV columns: timestamp, temperature_c, pressure_hpa, humidity_pct, and optionally station_id.
An empty cell (or NaN / null) is a missing value and is sent as null. Rows are sent in file order.

Speed is a factor on data time: 1 is real time, 60 plays one hour of data per minute, 0 sends as
fast as possible.

`data/holdout/` is read once, by evaluate.py, at the end. This module refuses to read it.

Usage:
    python replay.py data/clean/demo.csv --station S1 --speed 60 --url http://localhost:8000
"""
from __future__ import annotations

import argparse
import csv
import os
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import httpx

from atmos.config import CONFIG_DIR, load_settings
from atmos.schema import CHANNELS, Reading

REPO_ROOT = CONFIG_DIR.parent
_MISSING = {"", "nan", "null", "none"}


def data_root(settings: dict) -> Path:
    p = Path(settings["replay"]["data_dir"])
    return (p if p.is_absolute() else REPO_ROOT / p).resolve()


def check_path(path: Path, settings: dict, must_be_in_data_dir: bool = False, allow_holdout: bool = False) -> Path:
    """Resolve `path` and refuse the holdout folder (and, if asked, anything outside the data folder).
    Only evaluate.py passes allow_holdout=True, after its own holdout guard."""
    p = Path(path)
    p = (p if p.is_absolute() else Path.cwd() / p).resolve()
    root = data_root(settings)
    for sealed in ("holdout", "fresh", "fresh2", "fresh3", "fresh4", "fresh5"):                 # each is read once, by an evaluation run behind its own guard
        if not allow_holdout and (p == root / sealed or (root / sealed) in p.parents):
            raise ValueError(f"data/{sealed}/ is read once, by the evaluation, behind its guard. Replay will not read it.")
    if must_be_in_data_dir and root not in p.parents:
        raise ValueError(f"CSV must be inside the data folder ({root}).")
    return p


def _number(text: str) -> Optional[float]:
    return None if text.strip().lower() in _MISSING else float(text)


def read_readings(path: Path, settings: dict, station_id: Optional[str] = None,
                  must_be_in_data_dir: bool = False, allow_holdout: bool = False) -> list[Reading]:
    path = check_path(path, settings, must_be_in_data_dir, allow_holdout)
    out: list[Reading] = []
    with open(path, newline="", encoding="utf-8-sig") as f:      # utf-8-sig: tolerate an Excel byte-order mark
        reader = csv.DictReader(f)
        needed = {"timestamp", *CHANNELS}
        missing = needed - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing columns: {', '.join(sorted(missing))}")
        if station_id is None and "station_id" not in (reader.fieldnames or []):
            raise ValueError("No station_id column in the CSV and no station given.")
        for n, row in enumerate(reader, start=2):              # line 1 is the header
            try:
                out.append(Reading(station_id=station_id or row["station_id"],
                                   timestamp=datetime.fromisoformat(row["timestamp"]),
                                   **{ch: _number(row[ch]) for ch in CHANNELS}))
            except (ValueError, TypeError) as e:
                raise ValueError(f"line {n}: {e}") from e
    return out


@dataclass
class ReplaySummary:
    sent: int = 0
    verdicts: Counter = field(default_factory=Counter)
    stopped: bool = False


def replay(readings: list[Reading], ingest: Callable[[Reading], str], speed: float, max_sleep_seconds: float,
           sleep: Callable[[float], None] = time.sleep, stop: Optional[threading.Event] = None,
           on_progress: Optional[Callable[[int, str], None]] = None) -> ReplaySummary:
    """Send readings one by one. `ingest` returns the verdict text. Waits data-time / speed between readings."""
    summary = ReplaySummary()
    prev: Optional[Reading] = None
    for r in readings:
        if stop is not None and stop.is_set():
            summary.stopped = True
            break
        if prev is not None and speed > 0:
            gap = (r.timestamp - prev.timestamp).total_seconds()
            if gap > 0:
                sleep(min(gap / speed, max_sleep_seconds))
        verdict = ingest(r)
        summary.sent += 1
        summary.verdicts[verdict] += 1
        if on_progress:
            on_progress(summary.sent, verdict)
        prev = r
    return summary


def api_headers() -> dict:
    """X-API-Key from the environment (ATMOS_API_KEY), if the API was started with one."""
    key = os.environ.get("ATMOS_API_KEY")
    return {"X-API-Key": key} if key else {}


def http_ingest(url: str, client: Optional[httpx.Client] = None) -> Callable[[Reading], str]:
    client = client or httpx.Client(base_url=url, timeout=30, headers=api_headers())

    def _ingest(reading: Reading) -> str:
        resp = client.post("/ingest", json=reading.model_dump(mode="json"))
        resp.raise_for_status()
        return resp.json()["verdict"]["verdict"]
    return _ingest


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Replay a historical CSV into /ingest.")
    ap.add_argument("csv", type=Path)
    ap.add_argument("--station", help="station id (needed if the CSV has no station_id column)")
    ap.add_argument("--speed", type=float, default=0.0, help="1 = real time, 60 = 1 hour per minute, 0 = fastest")
    ap.add_argument("--url", default=None, help="API address (default: dashboard.api_url in settings.yaml)")
    ap.add_argument("--limit", type=int, default=None, help="send only the first N readings")
    args = ap.parse_args(argv)

    settings = load_settings()
    url = args.url or settings["dashboard"]["api_url"]
    try:
        readings = read_readings(args.csv, settings, args.station)[: args.limit]
    except (ValueError, FileNotFoundError) as e:
        print(f"Cannot replay: {e}")
        return 2
    every = settings["replay"]["progress_every"]
    print(f"Replaying {len(readings)} readings to {url} (speed {args.speed:g})")
    summary = replay(readings, http_ingest(url), args.speed, settings["replay"]["max_sleep_seconds"],
                     on_progress=lambda n, v: print(f"  {n} sent") if n % every == 0 else None)
    print(f"Done. {summary.sent} sent. Verdicts: {dict(summary.verdicts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
