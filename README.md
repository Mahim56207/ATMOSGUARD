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
| 4-7 | `fusion`, `healthscore`, `replay`, `dashboard`, `evaluate`, `timing`, `impute`, firmware, Docker | not started |

All thresholds in `config/settings.yaml` are starting points, not tuned.

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
