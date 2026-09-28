"""FastAPI service.

Endpoints: /ingest /latest /alerts /health /replay /inject /metrics /status

/ingest runs the full pipeline (physics, health, normality, ML, fusion) and stores the raw reading,
the verdict and the checks side by side. /health gives the sensor health score, projected service
date and ticket per station. POST /replay starts a CSV replay in the background (GET shows progress).
POST /inject arms a fault on a station's next readings (frozen, spike, step, drift, noise, dropout): whatever
streams in afterwards, from a replay, the fake node or a real ESP32, is altered the way a failing sensor would alter
it, and the altered value is stored and judged. /metrics serves the committed evaluation summary (results/summary.json).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

import replay as replay_module
from atmos.config import CONFIG_DIR, load_settings, load_stations
from atmos.fusion import Pipeline
from atmos.livefault import LIVE_FAULT_TYPES, LiveInjector
from atmos.schema import CheckResult, Reading, StoredRecord, Verdict, VerdictResult
from atmos.store import SQLiteStore, Store


log = logging.getLogger("atmosguard")
REPO_ROOT = CONFIG_DIR.parent


def utc_now() -> datetime:
    """Server clock as UTC without a zone, the same form the readings use."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def database_path(settings: dict) -> str:
    """ATMOS_SQLITE_PATH (a container keeps the database in a volume) wins; otherwise settings.yaml. A relative
    path is relative to the repo folder, not to wherever the server was started. ":memory:" is kept as it is."""
    path = os.environ.get("ATMOS_SQLITE_PATH") or settings.get("store", {}).get("sqlite_path", ":memory:")
    return path if path == ":memory:" or Path(path).is_absolute() else str(REPO_ROOT / path)


class ReplayRequest(BaseModel):
    csv_path: str                       # must be inside the data folder, never data/holdout
    station_id: Optional[str] = Field(default=None, min_length=1, max_length=64)   # needed if the CSV has no station_id column
    speed: float = Field(default=0.0, ge=0)   # 1 = real time, 0 = fastest
    limit: Optional[int] = Field(default=None, ge=1)


class InjectRequest(BaseModel):
    station_id: str = Field(min_length=1, max_length=64)
    fault_type: str                                        # one of LIVE_FAULT_TYPES
    channel: str                                           # temperature_c | pressure_hpa | humidity_pct
    samples: Optional[int] = Field(default=None, ge=1, le=100000)      # how many readings it lasts (default per type)
    magnitude: Optional[float] = Field(default=None, ge=0)             # default from settings injector.magnitude


def create_app(store: Optional[Store] = None, settings: Optional[dict] = None,
               pipeline: Optional[Pipeline] = None, clock: Callable[[], datetime] = utc_now) -> FastAPI:
    settings = settings if settings is not None else load_settings()
    stations = load_stations()
    if store is None:
        store = SQLiteStore(database_path(settings))
    if pipeline is None:
        pipeline = Pipeline(settings, stations)
        for station_id in stations:
            pipeline.load_models(station_id)
        # after a restart, rebuild each station's history from the stored raw readings (nothing is written)
        for station_id in store.stations():
            pipeline.warm_up(store.recent_readings(station_id, settings["pipeline"]["warmup_max_readings"]))
    injector = LiveInjector(settings)
    lock = threading.Lock()          # one reading at a time through store + pipeline
    replay_state: dict = {"state": "idle", "sent": 0, "total": 0, "verdicts": {}, "error": None}
    replay_stop = threading.Event()

    def ingest_reading(reading: Reading) -> StoredRecord:
        reading = injector.apply(reading)               # a fault armed with /inject alters the reading here
        with lock:
            record_id = store.add_reading(reading)      # raw reading is stored first, unchanged
            try:
                verdict = pipeline.process(reading, now=clock())
            except Exception as e:                      # a bug must show up as an alert, never as a lost verdict
                log.exception("pipeline failed on a reading of station %s", reading.station_id)
                reason = f"The checks could not run on this reading (internal error: {type(e).__name__}). The raw reading is stored."
                verdict = VerdictResult(verdict=Verdict.SUSPECT, confidence=0.0, reason=reason,
                                        checks=[CheckResult(check="pipeline_error", flagged=True, severity="soft", reason=reason)])
            store.set_verdict(record_id, verdict)
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
        ids = [station_id] if station_id else sorted(set(pipeline.stations_seen()) | set(store.stations()))
        reports = {sid: pipeline.health_report(sid) for sid in ids}
        if station_id and reports[station_id] is None:
            raise HTTPException(404, f"No readings yet for station {station_id}.")
        return {"stations": {sid: (r.model_dump(mode="json") if r else None) for sid, r in reports.items()}}

    @app.get("/status")
    def status():
        return {
            "status": "ok",
            "stations_configured": sorted(stations),
            "stations_seen": sorted(set(pipeline.stations_seen()) | set(store.stations())),
            "models_loaded": {"normality": sorted(pipeline.tables), "isolation_forest": sorted(pipeline.models)},
            "layers": settings.get("layers", {}),
            "verdict_counts": store.counts(),
            "pipeline": "full",
            "replay": dict(replay_state),
            "injections": injector.list(),
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
    def inject(req: InjectRequest):
        """Arm a fault on this station's next readings."""
        try:
            fault = injector.add(req.station_id, req.fault_type, req.channel, req.samples, req.magnitude)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"armed": {**vars(fault), "active": fault.active}, "fault_types": list(LIVE_FAULT_TYPES)}

    @app.get("/inject")
    def injections():
        return {"injections": injector.list(), "fault_types": list(LIVE_FAULT_TYPES)}

    @app.delete("/inject")
    def clear_injections(station_id: Optional[str] = None):
        return {"removed": injector.clear(station_id)}

    @app.get("/datasets")
    def datasets():
        """CSV files under the data folder that /replay may play (never data/holdout)."""
        root = replay_module.data_root(settings)
        files = sorted(str(p.relative_to(root.parent)) for p in root.rglob("*.csv")
                       if "holdout" not in p.relative_to(root).parts)
        return {"datasets": files}

    @app.get("/metrics")
    def metrics():
        """The committed evaluation summary (written by make_summary.py from evaluate_real.py results)."""
        path = REPO_ROOT / "results" / "summary.json"
        if not path.exists():
            raise HTTPException(404, "No evaluation summary yet: run evaluate_real.py and make_summary.py.")
        return json.loads(path.read_text(encoding="utf-8"))

    return app


app = create_app()
