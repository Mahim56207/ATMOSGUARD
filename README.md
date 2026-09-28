# AtmosGuard

Anomaly and sensor-health system for an Automatic Weather Station (AWS).

- **Inputs:** temperature (°C), pressure (hPa), relative humidity (%), plus timestamp and station metadata. Nothing else.
- **Single station.** We never compare against neighbouring stations.
- **Pipeline:** physics → health → normality → ML → fusion.
- **Output:** verdict `VALID | WEATHER | SUSPECT | FAULT`, with confidence, a plain-English reason, a health score, a projected service date, and optional imputation.

## Status
Built one module at a time (build order in `SETUP_GUIDE.md`).

| Step | Modules | State |
|---|---|---|
| 1 | `schema`, `store`, `config/`, `api` (`/ingest` stub) | done |
| 2 | `physics`, `health` + tests | done |
| 3 | `injector`, `normality`, `mlmodel` + tests | done (tested on synthetic data only; no real station data yet) |
| 4 | `fusion`, `healthscore`, full pipeline behind `/ingest` and `/health` | done (synthetic data only) |
| 5 | `replay`, `dashboard` | done |
| 6 | `evaluate` (baselines, ablation, DEV vs HOLDOUT, guarded holdout) | done (synthetic data only) |
| 7 | `timing`, `impute`, firmware, Docker | not started |

All thresholds in `config/settings.yaml` are starting points, not tuned.

## Run it
```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn api:app --port 8000                       # the API
.venv/bin/python replay.py data/clean/your.csv --station S1 --speed 60   # stream a CSV into /ingest
.venv/bin/streamlit run dashboard.py                        # the dashboard (reads the API)
.venv/bin/python -m pytest                                  # tests
.venv/bin/python evaluate.py --synthetic                    # fake-data run of the evaluation (plumbing check only)
.venv/bin/python evaluate.py --station S1                   # DEV only, from data/clean and data/events
.venv/bin/python evaluate.py --station S1 --holdout         # once, at the end (needs config/protocol.md committed)
```
CSV columns: `timestamp, temperature_c, pressure_hpa, humidity_pct` (+ optional `station_id`). An empty cell is a missing value.
Speed 1 is real time, 60 is one hour per minute, 0 is as fast as possible. `POST /replay` does the same inside the API,
for files in `data/` only. Both refuse `data/holdout/`, which only `evaluate.py` may read.
Put your station in `config/stations.yaml` (with `cadence_minutes`). Without it the cadence is guessed from the data.

## Known limits (current state)
- Nothing has been run on real station data yet. All tests use seeded synthetic data.
- The weather signatures in `settings.yaml` (`fusion.weather.signatures`) are an assumption and must be reviewed on real events.
- The CUSUM drift check is a soft flag. Real weather anomalies last hours and look like drift, so its alarm level is set high. Slow drift is measured by Theil-Sen in `healthscore.py`.
- A bad raw reading stays in the health windows (noise, frozen) for a while, so it can lower the verdict of the readings after it (for example FAULT to SUSPECT).
- The Isolation Forest is weak on a gross error in a single channel. The physics, health and normality layers catch those.
- Pipeline state (history, health records) is in memory and starts empty after a restart.

## Standard practice (not our invention)
Physics checks, persistence (frozen-value) checks, CUSUM, Isolation Forest, SHAP.

## What is ours
- Single-station, neighbour-free integration of the checks.
- `WEATHER` as a verdict of its own (escalate, never suppress).
- Evaluation on real extreme-weather events.

## What we do not claim
- Long-term drift validation.
- Performance on labelled real faults.
- Detection of offset drift when there is no reference.

## Out of scope
- τ_RH (humidity response time) in the live pipeline. Bench analysis only, in a separate `research/` notebook.
- Pressure-tide barometer health check.
- A hard "wet-bulb 35 °C is impossible" rule (it is only a soft SUSPECT flag).
- Spatial / neighbour-station checks.
