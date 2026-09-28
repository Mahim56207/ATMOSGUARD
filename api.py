"""FastAPI service.

Endpoints: /ingest /latest /alerts /health /replay /inject /metrics /status

Build step 1: /ingest returns a STUB verdict. The real pipeline is wired in from step 4.
/replay, /inject and /metrics are placeholders (501) until their modules exist.
"""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException, Query

from atmos.config import load_settings, load_stations
from atmos.schema import Reading, StoredRecord, Verdict, VerdictResult
from atmos.store import SQLiteStore, Store


def stub_verdict(reading: Reading) -> VerdictResult:
    """Placeholder until fusion.py exists. Confidence 0 so nobody mistakes it for a real result."""
    return VerdictResult(
        verdict=Verdict.VALID,
        confidence=0.0,
        reason="Stub verdict: the detection pipeline is not wired in yet.",
    )


def create_app(store: Optional[Store] = None, settings: Optional[dict] = None) -> FastAPI:
    settings = settings if settings is not None else load_settings()
    stations = load_stations()
    if store is None:
        store = SQLiteStore(settings.get("store", {}).get("sqlite_path", ":memory:"))

    app = FastAPI(title="AtmosGuard")

    @app.post("/ingest", response_model=StoredRecord)
    def ingest(reading: Reading) -> StoredRecord:
        record_id = store.add_reading(reading)          # raw reading is stored first, unchanged
        store.set_verdict(record_id, stub_verdict(reading))
        return store.get(record_id)

    @app.get("/latest", response_model=list[StoredRecord])
    def latest(station_id: Optional[str] = None, limit: int = Query(1, ge=1, le=1000)):
        return store.latest(station_id, limit)

    @app.get("/alerts", response_model=list[StoredRecord])
    def alerts(station_id: Optional[str] = None, limit: int = Query(50, ge=1, le=1000)):
        return store.alerts(station_id, limit)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/status")
    def status():
        return {
            "stations_configured": sorted(stations),
            "layers": settings.get("layers", {}),
            "verdict_counts": store.counts(),
            "pipeline": "stub",
        }

    @app.post("/replay")
    def replay():
        raise HTTPException(501, "Not built yet (build step 5: replay.py).")

    @app.post("/inject")
    def inject():
        raise HTTPException(501, "Not built yet (build step 3: injector.py).")

    @app.get("/metrics")
    def metrics():
        raise HTTPException(501, "Not built yet (build step 6: evaluate.py).")

    return app


app = create_app()
