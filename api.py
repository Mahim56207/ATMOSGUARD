"""FastAPI service.

Endpoints: /ingest /latest /alerts /health /replay /inject /metrics /status

/ingest runs the full pipeline (physics, health, normality, ML, fusion) and stores the raw reading,
the verdict and the checks side by side. /health gives the sensor health score, projected service
date and ticket per station. /replay, /inject and /metrics stay 501 until their modules exist.
"""
from __future__ import annotations

import threading
from typing import Optional

from fastapi import FastAPI, HTTPException, Query

from atmos.config import load_settings, load_stations
from atmos.fusion import Pipeline
from atmos.schema import Reading, StoredRecord
from atmos.store import SQLiteStore, Store


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

    app = FastAPI(title="AtmosGuard")

    @app.post("/ingest", response_model=StoredRecord)
    def ingest(reading: Reading) -> StoredRecord:
        with lock:
            record_id = store.add_reading(reading)      # raw reading is stored first, unchanged
            store.set_verdict(record_id, pipeline.process(reading))
            return store.get(record_id)

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
        }

    @app.post("/replay")
    def replay():
        raise HTTPException(501, "Not built yet (build step 5: replay.py).")

    @app.post("/inject")
    def inject():
        raise HTTPException(501, "Not built yet (build step 3 module exists; API route comes with evaluate/replay).")

    @app.get("/metrics")
    def metrics():
        raise HTTPException(501, "Not built yet (build step 6: evaluate.py).")

    return app


app = create_app()
