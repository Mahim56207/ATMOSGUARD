"""Scale test: N simulated stations, each with its OWN normality table, Isolation Forest, Mahalanobis model and learned limits.

  python loadtest.py                       # 1, 10, 50, 200 stations, in-process pipeline, then the HTTP server
  python loadtest.py --stations 10 50 --http-clients 8

What it shows, and what it does not:
  * The pipeline keeps state per station and nothing is shared between stations, so the cost of one reading does not
    depend on how many stations exist. This measures that (median and 95th-percentile time per reading against the
    number of stations), plus memory and model storage per station.
  * The stations are SIMULATED on ONE machine. That is a design check, not a proof of a production deployment.
    To serve more stations you add worker processes (each owns a set of stations); nothing needs redesigning.
  * The HTTP run drives the real FastAPI app (validation, SQLite store, pipeline) with concurrent clients, so it
    includes serialisation and the database. It is the number to quote for "verdict per reading".
Run it on an otherwise quiet machine: other work distorts latency.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import statistics
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional


from atmos.config import load_settings
from atmos.fusion import Pipeline
from atmos.limits import fit_limits
from atmos.mlmodel import IsolationModel, MahalanobisModel
from atmos.normality import NormalityTable
from atmos.schema import Reading
import evaluate as ev

REPO = Path(__file__).resolve().parent


def rss_mb() -> float:
    try:
        with open("/proc/self/statm") as f:
            return int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1e6
    except OSError:
        return float("nan")


def station_series(settings: dict, i: int, days: int, station: Optional[str] = None) -> list[Reading]:
    """Fake weather with a station-specific mean and seed. Simulated: says nothing about real stations.
    `station` overrides the id, so the days that get judged carry the id of the station whose models judge them."""
    s = copy.deepcopy(settings)
    syn = s["evaluate"]["synthetic"]
    syn["temperature"]["mean"] = 12.0 + (i * 7 % 23)
    syn["pressure"]["mean"] = 1000.0 + (i * 5 % 20)
    syn["humidity"]["mean"] = 45.0 + (i * 3 % 30)
    return ev.synthetic_series(s, days, seed=settings["seed"] + i, station=station or f"ST{i:03d}")


def build_fleet(settings: dict, n: int, train_days: int = 12) -> tuple[dict, dict, dict, dict, dict, dict]:
    """Per-station models for n simulated stations: every layer of the shipped pipeline, none shared between stations."""
    tables, models, limits, mahal, streams = {}, {}, {}, {}, {}
    cad = float(settings["evaluate"]["synthetic"]["cadence_minutes"])
    for i in range(n):
        train = station_series(settings, i, train_days)
        sid = train[0].station_id
        tables[sid] = NormalityTable.fit(train, settings)
        models[sid] = IsolationModel.fit(train, settings)
        limits[sid] = fit_limits(train, settings, cad)
        mahal[sid] = MahalanobisModel.fit(train, settings, tables[sid])
        streams[sid] = station_series(settings, i + 10_000, 3, station=sid)   # the days that get judged, under the SAME id
    return tables, models, limits, mahal, streams, {sid: {"cadence_minutes": cad} for sid in tables}


def storage_per_station(tables: dict, models: dict, limits: dict, mahal: dict) -> dict:
    with tempfile.TemporaryDirectory() as d:
        sid = next(iter(tables))
        tables[sid].save(Path(d) / "n.json")
        models[sid].save(Path(d) / "m.joblib")
        limits[sid].save(Path(d) / "l.json")
        mahal[sid].save(Path(d) / "h.joblib")
        sizes = {"normality_json_kb": (Path(d) / "n.json").stat().st_size / 1024,
                 "isolation_forest_kb": (Path(d) / "m.joblib").stat().st_size / 1024,
                 "mahalanobis_kb": (Path(d) / "h.joblib").stat().st_size / 1024,
                 "limits_json_kb": (Path(d) / "l.json").stat().st_size / 1024}
    sizes["total_kb"] = sum(sizes.values())
    return {k: round(v, 1) for k, v in sizes.items()}


def run_pipeline(settings: dict, n: int) -> dict:
    """Interleave the readings of n stations, as a server would see them, and time each verdict."""
    s = copy.deepcopy(settings)
    s["healthscore"]["recompute_every_minutes"] = 60          # the real setting: health is recomputed hourly
    before = rss_mb()
    tables, models, limits, mahal, streams, stations = build_fleet(s, n)
    after_fit = rss_mb()
    pipe = Pipeline(s, stations, tables, models, limits, mahal)
    order = max(len(v) for v in streams.values())
    lat: list[float] = []
    t_all = time.perf_counter()
    for k in range(order):
        for sid, series in streams.items():
            if k < len(series):
                a = time.perf_counter()
                pipe.process(series[k])
                lat.append((time.perf_counter() - a) * 1000.0)
    wall = time.perf_counter() - t_all
    after = rss_mb()
    lat_sorted = sorted(lat[len(lat) // 10:])                  # drop the first tenth: history is still filling
    return {"stations": n, "readings": len(lat), "readings_per_second": round(len(lat) / wall, 1),
            "median_ms": round(statistics.median(lat_sorted), 3),
            "p95_ms": round(lat_sorted[int(0.95 * (len(lat_sorted) - 1))], 3),
            "p99_ms": round(lat_sorted[int(0.99 * (len(lat_sorted) - 1))], 3),
            "rss_mb_after_fit": round(after_fit, 1), "rss_mb_after_run": round(after, 1),
            "memory_per_station_mb": round((after - before) / n, 2),
            "storage_per_station": storage_per_station(tables, models, limits, mahal)}


def run_http(settings: dict, n_stations: int, clients: int, readings_per_station: int = 60) -> dict:
    """The real FastAPI app on a local port, hit by concurrent clients (one thread each, stations spread across them)."""
    import httpx
    import uvicorn
    import api as api_module
    from atmos.store import SQLiteStore
    s = copy.deepcopy(settings)
    tables, models, limits, mahal, streams, stations = build_fleet(s, n_stations, train_days=8)
    pipe = Pipeline(s, stations, tables, models, limits, mahal)
    app = api_module.create_app(store=SQLiteStore(), settings=s, pipeline=pipe)
    port = 8765
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    lat: list[float] = []
    lock = threading.Lock()
    sids = list(streams)
    errors = 0

    def worker(mine: list[str]) -> None:
        nonlocal errors
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30) as c:
            for k in range(readings_per_station):
                for sid in mine:
                    r = streams[sid][k]
                    a = time.perf_counter()
                    resp = c.post("/ingest", json=r.model_dump(mode="json"))
                    d = (time.perf_counter() - a) * 1000.0
                    with lock:
                        lat.append(d)
                        errors += resp.status_code != 200
    chunks = [sids[i::clients] for i in range(clients)]
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=clients) as pool:
        list(pool.map(worker, chunks))
    wall = time.perf_counter() - t0
    server.should_exit = True
    thread.join(timeout=5)
    lat_sorted = sorted(lat)
    return {"stations": n_stations, "clients": clients, "requests": len(lat), "errors": errors,
            "requests_per_second": round(len(lat) / wall, 1),
            "median_ms": round(statistics.median(lat_sorted), 2),
            "p95_ms": round(lat_sorted[int(0.95 * (len(lat_sorted) - 1))], 2),
            "p99_ms": round(lat_sorted[int(0.99 * (len(lat_sorted) - 1))], 2)}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="AtmosGuard scale test (simulated stations, one machine).")
    ap.add_argument("--stations", type=int, nargs="+", default=[1, 10, 50, 200])
    ap.add_argument("--http-stations", type=int, default=50)
    ap.add_argument("--http-clients", type=int, default=8)
    ap.add_argument("--no-http", action="store_true")
    ap.add_argument("--no-forest-rows", action="store_true", help="skip the extra rows with the Isolation Forest layer off")
    ap.add_argument("--out", type=Path, default=REPO / "results" / "scale.json")
    args = ap.parse_args(argv)
    settings = load_settings()
    rows = []
    print(f"{'stations':>9}{'readings/s':>12}{'median ms':>11}{'p95 ms':>9}{'p99 ms':>9}{'MB/station':>12}{'KB stored/station':>19}")
    for n in args.stations:
        r = run_pipeline(settings, n)
        rows.append(r)
        print(f"{r['stations']:>9}{r['readings_per_second']:>12}{r['median_ms']:>11}{r['p95_ms']:>9}{r['p99_ms']:>9}"
              f"{r['memory_per_station_mb']:>12}{r['storage_per_station']['total_kb']:>19}", flush=True)
    no_forest = []
    if not args.no_forest_rows:
        s_off = copy.deepcopy(settings)
        s_off["layers"]["mlmodel"] = False
        print("\nSame test with the Isolation Forest layer switched off (config flag):")
        for n in (1, 50):
            r = run_pipeline(s_off, n)
            no_forest.append(r)
            print(f"{r['stations']:>9}{r['readings_per_second']:>12}{r['median_ms']:>11}{r['p95_ms']:>9}{r['p99_ms']:>9}", flush=True)
    http = None
    if not args.no_http:
        http = run_http(settings, args.http_stations, args.http_clients)
        print(f"\nHTTP, real FastAPI + SQLite, {http['stations']} stations, {http['clients']} concurrent clients: "
              f"{http['requests_per_second']} requests/s, median {http['median_ms']} ms, p95 {http['p95_ms']} ms, "
              f"p99 {http['p99_ms']} ms, errors {http['errors']}")
    out = {"note": "Simulated stations on one machine (a design check, not a deployment proof). "
                   f"cpu_count={os.cpu_count()}, python={sys.version.split()[0]}.",
           "pipeline_by_station_count": rows, "pipeline_without_isolation_forest": no_forest, "http": http}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
