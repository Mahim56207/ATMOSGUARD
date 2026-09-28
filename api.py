"""FastAPI service.

Endpoints: /ingest /latest /alerts /health /replay /inject /metrics /status

/ingest runs the full pipeline (physics, health, normality, ML, fusion) and stores the raw reading,
the verdict and the checks side by side. /health gives the sensor health score, projected service
date and ticket per station. POST /replay starts a CSV replay in the background (GET shows progress).
/inject and /metrics stay 501 until evaluate.py exists.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

import replay as replay_module
from atmos.config import load_settings, load_stations
from atmos.fusion import Pipeline
from atmos.schema import Reading, StoredRecord
from atmos.store import SQLiteStore, Store


class ReplayRequest(BaseModel):
    csv_path: str                       # must be inside the data folder, never data/holdout
    station_id: Optional[str] = None    # needed if the CSV has no station_id column
    speed: float = 0.0                  # 1 = real time, 0 = fastest
    limit: Optional[int] = None


def create_app(store: Optional[Store] = None, settings: Optional[dict] = None,
               pipeline: Optional[Pipeline] = None) -> FastAPI:
    settings = settings if settings is not None else load_settings()
    stations = load_stations()
    if store is None:
        store = SQLiteStore(settings.get("store", {}).get("sqlite_path", ":memory:"))
    if pipeline is None:
        pipeline = Pipeline(settings, stations)
        for station_id in stations:
            pipeline.load_models(station_id)
    lock = threading.Lock()          # one reading at a time through store + pipeline
    replay_state: dict = {"state": "idle", "sent": 0, "total": 0, "verdicts": {}, "error": None}
    replay_stop = threading.Event()

    def ingest_reading(reading: Reading) -> StoredRecord:
        with lock:
            record_id = store.add_reading(reading)      # raw reading is stored first, unchanged
            store.set_verdict(record_id, pipeline.process(reading))
            return store.get(record_id)

    app = FastAPI(title="AtmosGuard")

    @app.post("/ingest", response_model=StoredRecord)
    def ingest(reading: Reading) -> StoredRecord:
        return ingest_reading(reading)

    @app.get("/latest", response_model=list[StoredRecord])
    def latest(station_id: Optional[str] = None, limit: int = Query(1, ge=1, le=1000)):
        return store.latest(station_id, limit)

    @app.get("/alerts", response_model=list[StoredRecord])
    def alerts(station_id: Optional[str] = None, limit: int = Query(50, ge=1, le=1000)):
        return store.alerts(station_id, limit)

    @app.get("/health")
    def health(station_id: Optional[str] = None):
        """Sensor health: score 0-100, projected service date, ticket."""
        ids = [station_id] if station_id else pipeline.stations_seen()
        reports = {sid: pipeline.health_report(sid) for sid in ids}
        if station_id and reports[station_id] is None:
            raise HTTPException(404, f"No readings yet for station {station_id}.")
        return {"stations": {sid: (r.model_dump(mode="json") if r else None) for sid, r in reports.items()}}

    @app.get("/status")
    def status():
        return {
            "status": "ok",
            "stations_configured": sorted(stations),
            "stations_seen": pipeline.stations_seen(),
            "models_loaded": {"normality": sorted(pipeline.tables), "isolation_forest": sorted(pipeline.models)},
            "layers": settings.get("layers", {}),
            "verdict_counts": store.counts(),
            "pipeline": "full",
            "replay": dict(replay_state),
        }

    def run_replay(readings: list[Reading], speed: float) -> None:
        def progress(n: int, verdict: str) -> None:
            replay_state["sent"] = n
        try:
            summary = replay_module.replay(
                readings, lambda r: ingest_reading(r).verdict.verdict.value, speed,
                settings["replay"]["max_sleep_seconds"], stop=replay_stop, on_progress=progress)
            replay_state.update(state="stopped" if summary.stopped else "done", verdicts=dict(summary.verdicts))
        except Exception as e:                       # report it, never crash the server thread silently
            replay_state.update(state="error", error=str(e))

    @app.post("/replay")
    def start_replay(req: ReplayRequest):
        """Play a CSV from the data folder through the pipeline in the background."""
        if replay_state["state"] == "running":
            raise HTTPException(409, "A replay is already running.")
        try:
            readings = replay_module.read_readings(Path(req.csv_path), settings, req.station_id,
                                                   must_be_in_data_dir=True)[: req.limit]
        except FileNotFoundError:
            raise HTTPException(404, f"No such file: {req.csv_path}")
        except ValueError as e:
            raise HTTPException(400, str(e))
        replay_stop.clear()
        replay_state.update(state="running", sent=0, total=len(readings), verdicts={}, error=None)
        threading.Thread(target=run_replay, args=(readings, req.speed), daemon=True).start()
        return dict(replay_state)

    @app.get("/replay")
    def replay_progress():
        return dict(replay_state)

    @app.delete("/replay")
    def stop_replay():
        replay_stop.set()
        return {"stopping": replay_state["state"] == "running"}

    @app.post("/inject")
    def inject():
        raise HTTPException(501, "Not built yet (build step 3 module exists; API route comes with evaluate/replay).")

    @app.get("/metrics")
    def metrics():
        raise HTTPException(501, "Not built yet (build step 6: evaluate.py).")

    return app


app = create_app()
