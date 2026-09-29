"""Fetch and build the FRESH stations (data_tools/stations_fresh.yaml) and cut their extreme-weather windows.

    python -m data_tools.make_fresh fetch        # download 2016-2024 raw files (git-ignored), about 1 GB
    python -m data_tools.make_fresh build        # write data/fresh/real/<STN>.csv and data/fresh/events.json

Layout: one CSV per station, the whole record 2016-2024, columns station_id, timestamp, temperature_c, pressure_hpa,
humidity_pct, noaa_flag. Same builder, same extreme-weather rules (`make_dataset.RULES`) as for every other station.
`data/fresh/` is read only by `evaluate_real.py --fresh` after its guard passes (Amendment 2 in config/protocol.md).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional


from . import isd, make_dataset

REPO = isd.REPO
CATALOG = Path(__file__).resolve().parent / "stations_fresh.yaml"
OUT_DIR = REPO / "data" / "fresh" / "real"
EVENTS = REPO / "data" / "fresh" / "events.json"


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Fetch and build the FRESH stations.")
    ap.add_argument("cmd", choices=("fetch", "build"))
    args = ap.parse_args(argv)
    cat = isd.load_catalog(CATALOG)
    first, last = cat["years"]["first"], cat["years"]["last"]
    if args.cmd == "fetch":
        res = isd.fetch_all([s["file"] for s in cat["stations"].values()], list(range(first, last + 1)))
        missing = sorted(f"{k[1]}/{k[0]}" for k, v in res.items() if v is None)
        print(f"downloaded {sum(v is not None for v in res.values())} files; missing: {missing or 'none'}")
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    events: dict[str, list[dict]] = {}
    for sid, st in cat["stations"].items():
        df = isd.build_station(st, list(range(first, last + 1)), cadence_minutes=st["cadence_minutes"])
        df.insert(0, "station_id", sid)
        df.to_csv(OUT_DIR / f"{sid}.csv", index=False)
        events[sid] = make_dataset.find_events(df)
        print(f"{sid}: {len(df)} rows, coverage by year {isd.coverage(df, st['cadence_minutes'])}, {len(events[sid])} extreme-weather windows",
              flush=True)
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    EVENTS.write_text(json.dumps({"rules": make_dataset.RULES, "dev_stations": [], "sealed_stations": list(cat["stations"]),
                                  "split_date": "2020-01-01", "events": events}, indent=1), encoding="utf-8")
    print(f"wrote {EVENTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
