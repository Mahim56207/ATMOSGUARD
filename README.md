# AtmosGuard

**Is this the sensor, or is this the sky?** An anomaly and sensor-health system for an Automatic Weather Station (AWS), built
for SIH 2026 problem statement 26073. It uses **only temperature, pressure and relative humidity**, one station at a time,
with **no neighbours**.

A broken barometer and a cyclone look the same on a chart. AtmosGuard answers per reading with one of four verdicts,
`VALID | WEATHER | SUSPECT | FAULT`: real weather is **escalated as an alert, never deleted as noise**, and every verdict comes
with a plain-English reason, a health score and a service-date estimate. The raw value is never overwritten.

## What makes this submission different (and what it does not claim)
- **We do not claim a new algorithm.** Physics checks, persistence tests, CUSUM, Isolation Forest and SHAP are standard. See
  [`docs/NOVELTY_AND_PRIOR_ART.md`](docs/NOVELTY_AND_PRIOR_ART.md) for what is standard, what we adapted (and from whom), and what is ours.
- **We evaluate on real weather.** 14 Indian airport stations, 2016-2024 (NOAA ISD), real cyclones (Vardah, Fani, Amphan, Tauktae,
  Michaung, Remal, Biparjoy...), heat waves, cold waves and thunderstorm outflows, chosen by rule on the data. The false-alarm rate
  **on real extreme weather is reported separately** from the injected-fault score.
- **The holdout was sealed in time and in space and run once**, with the protocol committed first. Whatever it gave is below.
- **Real data broke our first version, and we kept the record**: on real airport METAR (whole degrees, whole hPa) the fixed-limit
  pipeline alarmed on 63 % of clean samples (the results row "without station-learned limits"), a real pressure plateau inside a
  cyclone read as a frozen barometer, and real thunderstorm outflows were called faults. What we changed and why is in the tuning log in
  [`config/protocol.md`](config/protocol.md).
- **We say what we cannot do:** [`docs/WHAT_WE_DO_NOT_CLAIM.md`](docs/WHAT_WE_DO_NOT_CLAIM.md) and
  [`docs/FAILURE_MODES.md`](docs/FAILURE_MODES.md).

## Results at a glance
<!-- RESULTS:START -->
| | DEV (tuned here) | Holdout, same stations, later years | Holdout, eight unseen stations |
|---|---|---|---|
| **False alarms on clean real data** | 1.9% (1.8-2.0) of 98340 samples got FAULT or SUSPECT; 0.0% (0.0-0.0) got FAULT | 2.5% (2.4-2.6) of 147078 samples got FAULT or SUSPECT; 0.0% (0.0-0.0) got FAULT | 2.9% (2.8-3.0) of 237411 samples got FAULT or SUSPECT; 0.0% (0.0-0.1) got FAULT |
| **Real cyclones, heat, cold, fronts (nothing injected)** | FAULT on 0.0% (0.0-0.1) of 3503 samples (0 of 30 windows); WEATHER on 10.8%, SUSPECT on 9.0% | FAULT on 0.0% (0.0-0.1) of 4374 samples (0 of 38 windows); WEATHER on 11.8%, SUSPECT on 8.2% | FAULT on 0.3% (0.2-0.4) of 9074 samples (3 of 98 windows); WEATHER on 15.7%, SUSPECT on 8.6% |
| **Injected faults detected (injected, not real)** | frozen 100%; spike 98%; level shift 97%; noise burst 78%; dropout 99%; clock 3 h out 97% | frozen 100%; spike 96%; level shift 98%; noise burst 79%; dropout 100%; clock 3 h out 97% | frozen 100%; spike 90%; level shift 89%; noise burst 67%; dropout 98%; clock 3 h out 84% |
| **Agreement with NOAA quality flags** | escalated (FAULT, SUSPECT or WEATHER) on 66.9% of 236 NOAA-flagged values (FAULT or SUSPECT alone: 22.9%); escalated on 4.7% of the 101736 values NOAA left alone | escalated (FAULT, SUSPECT or WEATHER) on 61.5% of 265 NOAA-flagged values (FAULT or SUSPECT alone: 18.5%); escalated on 5.7% of the 151336 values NOAA left alone | escalated (FAULT, SUSPECT or WEATHER) on 67.6% of 559 NOAA-flagged values (FAULT or SUSPECT alone: 40.8%); escalated on 6.9% of the 246257 values NOAA left alone |
| **Slow drift (one station, no reference)** | false drift claims on 1.1% of 3859 station-days; an injected ramp reaching 8x the service limit was found in 56% of trials | false drift claims on 1.1% of 5797 station-days; an injected ramp reaching 8x the service limit was found in 50% of trials | false drift claims on 0.6% of 12495 station-days; an injected ramp reaching 8x the service limit was found in 56% of trials |

Real NOAA airport records, 14 Indian stations. Full tables, baselines and ablation: [`results/REPORT.md`](results/REPORT.md). Protocol written and committed before the holdout was read: [`config/protocol.md`](config/protocol.md).
<!-- RESULTS:END -->

### A brand-new station, on its first day
<!-- COLDSTART:START -->
| days of own history | with a starter: clean false alarms | with a starter: FAULT on real extreme weather | with a starter: injected faults detected | own data only: clean false alarms | own data only: FAULT on real extreme weather | own data only: injected faults detected |
|---|---|---|---|---|---|---|
| 0 | 6.09% | 0.0% | 86.4% | 62.72% | 28.6% | 79.6% |
| 30 | 5.79% | 0.0% | 85.8% | 16.53% | 4.97% | 84.0% |
| 90 | 7.34% | 0.0% | 95.7% | 12.83% | 0.03% | 92.0% |
| 365 | 4.17% | 0.0% | 97.5% | 5.3% | 0.0% | 96.9% |
| 1460 | 1.88% | 0.0% | 96.3% | 1.88% | 0.0% | 96.3% |

Leave-one-station-out on the six DEV stations, judged on each station's DEV years (2020-2021), which it never trained on. The starter is a frozen normality table and frozen limits from the nearest other station, blended out as the station's own history grows; no live data of another station is used. Injected faults here are frozen, spike and level shift only. Details: [`results/REPORT.md`](results/REPORT.md). (42 jobs, 8.7 minutes on 4 workers.)
<!-- COLDSTART:END -->

Data caveats that apply to every number: airport METAR/SYNOP records (not IMD AWS records); humidity is derived from the dew point;
no labelled real faults exist, so detection is measured on injected faults; NOAA's flags are another automated system, not ground truth.

## Known limits (read before relying on any number)
- **Real extreme weather is not always safe.** On the eight stations never used for tuning, 3 of 98 extreme-weather windows contain a
  `FAULT` verdict (0.3 % of those samples): two at Visakhapatnam, where sustained torrential rain pins derived humidity at 100 %, and one at
  Bhuj, where a desert station warms 15 C across a 6-hour reporting gap. The causes and two untested remedies are in
  [`docs/HOLDOUT_POSTMORTEM.md`](docs/HOLDOUT_POSTMORTEM.md). We did not tune on them.
- **Noise bursts are the weakest injected-fault class**, and a wrong clock takes on the order of a day to notice. A stuck sensor
  takes hours by design (it has to stay stuck longer than real weather can). On the eight unseen stations detection is lower than on DEV
  for every type except frozen and dropout (table above).
- **A simpler detector beats us on some fault types.** A Mahalanobis-distance-only baseline detects spikes at least as well as the full
  pipeline (and level shifts on DEV) with fewer false alarms, and is blind to frozen sensors, dropouts and wrong clocks. No single
  simpler system covers all six types; the layers buy coverage. See "No single simpler system" in
  [`results/REPORT.md`](results/REPORT.md) and [`docs/TECHNICAL_REPORT.md`](docs/TECHNICAL_REPORT.md).
- **Small drift is invisible from one station.** The drift monitor sees a ramp of several times the service limit, not one times the limit;
  the power curve is in the results and is the honest statement of what "drift detection" means here.
- **Not real-AWS validated.** Airport records round to whole degrees and whole hPa and carry derived humidity. A real AWS with 0.1
  resolution is easier in some ways and untested in others. [`docs/USE_YOUR_DATA.md`](docs/USE_YOUR_DATA.md) gives the one command that
  produces the same numbers for a real AWS record.
- **The firmware has been compiled against stubs and its L0 logic compared with the Python; it has not run on hardware.**

## Run it (one minute, no internet, no downloads)
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn api:app --port 8000 &                           # loads the six trained stations from models/
streamlit run dashboard.py                              # http://localhost:8501
```
Then open the dashboard's **Control panel**: replay a real cyclone (`data/demo/`), **break the sensor on demand** (frozen, spike,
level shift, drift, noise, dropout), and watch the verdict, the reason and the health score react. **No server?**
Open [`docs/demo/index.html`](docs/demo/index.html): a self-contained replay of six real events with the pipeline's actual verdicts.

Also: `python -m pytest -q` (340+ tests) - `docker compose up --build` - `python simnode.py --station BBI --minutes 120` (fake node) -
full reproduction commands in [`docs/REPRODUCE.md`](docs/REPRODUCE.md).

## How it works
```
ESP32 + BME280 (L0 on device)  -+
Replay of real records + live   -+-> POST /ingest -> L0 physics -> L1 health -> L2 normality -> L3 Isolation Forest + Mahalanobis
fault injection                                       -> timing (clock, co-jump) -> fusion -> VALID | WEATHER | SUSPECT | FAULT
                                                          + confidence + reason + health score + drift monitor + ticket + estimate
                                                          -> SQLite (raw, verdict, checks side by side) -> dashboard
```
| Layer | What it checks |
|---|---|
| L0 physics | ranges, dew point <= temperature, wet-bulb (soft flag only). Closed-form; also runs on the ESP32 |
| L1 health | frozen (limit learned per station, two tiers), step, spike, noise (limit learned per station), gaps (a notice), CUSUM |
| L2 normality | is this normal for THIS station, in THIS month, at THIS hour? |
| L3 | Isolation Forest, and a Mahalanobis distance of (departure from normal, rate of change) that names the channel that drove it |
| Timing | T1 clock phase (a 3-hour clock error), T2 same-instant jump on several channels |
| Fusion | impossible/frozen/missing -> FAULT; one channel jumps while the others are actually quiet -> FAULT; several channels move or depart together -> WEATHER; unusual but ambiguous -> SUSPECT |
| Health | score, drift monitor (daily means, autocorrelation-aware test, isolated-trend rule, persistence), ticket, projected service date, and the smallest drift it can see |
| Estimate | a value for a missing or faulty reading, with an uncertainty band, stored beside the raw value |

Every layer has a config switch, so the ablation needs no code edits and the system still runs with any layer off.
More: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Evidence and documents
| | |
|---|---|
| Results (all tables, DEV and both holdouts) | [`results/REPORT.md`](results/REPORT.md), raw JSON in `results/` |
| Protocol, split, tuning log | [`config/protocol.md`](config/protocol.md) |
| Technical report | [`docs/TECHNICAL_REPORT.md`](docs/TECHNICAL_REPORT.md) |
| Novelty and prior art | [`docs/NOVELTY_AND_PRIOR_ART.md`](docs/NOVELTY_AND_PRIOR_ART.md) |
| What we do not claim / failure modes | [`docs/WHAT_WE_DO_NOT_CLAIM.md`](docs/WHAT_WE_DO_NOT_CLAIM.md), [`docs/FAILURE_MODES.md`](docs/FAILURE_MODES.md) |
| Use cases (cyclones, NWP, aviation, maintenance, sparse networks) | [`docs/USE_CASES.md`](docs/USE_CASES.md) |
| Data provenance and limits | [`docs/DATA.md`](docs/DATA.md) |
| Run the evaluation on your own (real AWS) record | [`docs/USE_YOUR_DATA.md`](docs/USE_YOUR_DATA.md) |
| What the holdout found, and what we did not do about it | [`docs/HOLDOUT_POSTMORTEM.md`](docs/HOLDOUT_POSTMORTEM.md) |
| Hardware node, BOM, energy (estimate, not measurement) | [`docs/HARDWARE.md`](docs/HARDWARE.md) |
| Demo script and contingencies | [`docs/DEMO_RUNBOOK.md`](docs/DEMO_RUNBOOK.md) |
| Likely judge questions and honest answers | [`docs/JUDGE_QA.md`](docs/JUDGE_QA.md) |
| Submission playbook (criteria -> artifacts, what is left for the team) | [`docs/SIH_SUBMISSION_PLAYBOOK.md`](docs/SIH_SUBMISSION_PLAYBOOK.md) |
| Research: humidity response time (tau_RH), where it works and where it does not | [`research/tau_rh.py`](research/tau_rh.py) |

## Repository map
`atmos/` the pipeline - `api.py` FastAPI - `dashboard.py` Streamlit - `evaluate_real.py` the real-data evaluation -
`evaluate_coldstart.py` new-station study - `evaluate_csv.py` the same evaluation on your CSV - `loadtest.py` scale test - `data_tools/` NOAA download, split, event rules -
`firmware/node/` ESP32 sketch and the portable L0 header - `train.py` per-station models - `make_summary.py`,
`make_figures.py`, `make_offline_demo.py` - `data/real/dev`, `data/holdout/real` (sealed until the single run), `data/demo` -
`models/` trained station artifacts - `tests/` 340+ tests.

## Standard practice (not our invention)
Physics checks, persistence (frozen-value) checks including station-learned thresholds (HadISD), CUSUM, Theil-Sen and
Mann-Kendall trend tests, Isolation Forest, Mahalanobis distance, SHAP, weather-versus-fault discrimination (ECMWF, Oklahoma
Mesonet), health scores and maintenance tickets.

## What is ours
- The evidence standard: 14 real stations, a holdout sealed in time and space, false alarms on real cyclones reported separately,
  baselines and an ablation on the same data, agreement with NOAA's flags, and the failures kept on record.
- A single-station, neighbour-free integration that copes with the rounded values real stations report.
- `WEATHER` as a verdict of its own (escalate, never suppress), by movement **and** by level.
- A drift monitor with an isolated-trend rule and a stated detectability floor.
- Edge parity: the ESP32's L0 code is compiled and tested against the Python on a laptop.
- Live fault injection for the demo, and a measured boundary for the humidity response-time idea.

## What we do not claim
Any new technique. Real-fault accuracy (only injected faults exist to measure). Small drifts or constant offsets from a single
station with no reference. Long-term drift validation. Calibrated confidence (it is agreement between checks). That the firmware
has run on hardware or that any energy figure is measured. That humidity response time works in the field. Full list:
[`docs/WHAT_WE_DO_NOT_CLAIM.md`](docs/WHAT_WE_DO_NOT_CLAIM.md).

## Input rules
CSV columns `timestamp, temperature_c, pressure_hpa, humidity_pct` (+ optional `station_id`); an empty cell is a missing value.
Timestamps are UTC (a timestamp with a zone is converted). NaN or infinite is stored as missing and judged as a dropout. Absurd
finite numbers are stored as they are and get FAULT. If the checks ever fail on a reading it is stored raw and marked SUSPECT with a
`pipeline_error` check. Put a station in `config/stations.yaml` with its `cadence_minutes`; without it the cadence is guessed.

## Out of scope
tau_RH in the live pipeline (research only). The pressure-tide barometer check. A hard "wet-bulb 35 C is impossible" rule (it is a soft flag).
Spatial and neighbour-station checks (by design).
