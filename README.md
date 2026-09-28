# AtmosGuard

Anomaly and sensor-health system for an Automatic Weather Station (AWS).

- **Inputs:** temperature (°C), pressure (hPa), relative humidity (%), plus timestamp and station metadata. Nothing else.
- **Single station.** We never compare against neighbouring stations.
- **Pipeline:** physics → health → normality → ML → fusion.
- **Output:** verdict `VALID | WEATHER | SUSPECT | FAULT`, with confidence, a plain-English reason, a health score, a projected service date, and optional imputation.

## Status
Structure and stubs only. Modules are built one at a time (see build order in `SETUP_GUIDE.md`).

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
