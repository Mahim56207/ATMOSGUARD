# Submission text

Ready-to-paste answers for the portal form, the content for the slides when you make them (this is **not** the deck), and two pitch
scripts. Every number comes from the block below, which is generated from `results/summary.json`; when you quote one, say which split it
is from. Anything the repository cannot support is not in here.

<!-- NUMBERS:START -->
**Numbers to have in your head** (generated from `results/summary.json`; say which split you are quoting):

- **DEV (tuned here):** clean data: 1.9% (1.8-2.0) of 98340 samples got FAULT or SUSPECT; 0.0% (0.0-0.0) got FAULT. Real extreme weather: FAULT on 0.0% (0.0-0.1) of 3503 samples (0 of 30 windows); WEATHER on 10.8%, SUSPECT on 9.0%. Injected faults raised the alarm: frozen 100%; spike 98%; level shift 97%; noise burst 78%; dropout 99%; clock 3 h out 97%.
- **holdout, same stations, later years:** clean data: 2.5% (2.4-2.6) of 147078 samples got FAULT or SUSPECT; 0.0% (0.0-0.0) got FAULT. Real extreme weather: FAULT on 0.0% (0.0-0.1) of 4374 samples (0 of 38 windows); WEATHER on 11.8%, SUSPECT on 8.2%. Injected faults raised the alarm: frozen 100%; spike 96%; level shift 98%; noise burst 79%; dropout 100%; clock 3 h out 97%.
- **holdout, eight unseen stations:** clean data: 2.9% (2.8-3.0) of 237411 samples got FAULT or SUSPECT; 0.0% (0.0-0.1) got FAULT. Real extreme weather: FAULT on 0.3% (0.2-0.4) of 9074 samples (3 of 98 windows); WEATHER on 15.7%, SUSPECT on 8.6%. Injected faults raised the alarm: frozen 100%; spike 90%; level shift 89%; noise burst 67%; dropout 98%; clock 3 h out 84%.
- **fresh, twelve more unseen stations:** clean data: 2.5% (2.5-2.6) of 364440 samples got FAULT or SUSPECT; 0.1% (0.1-0.1) got FAULT. Real extreme weather: FAULT on 0.1% (0.1-0.2) of 11782 samples (3 of 139 windows); WEATHER on 10.3%, SUSPECT on 6.8%. Injected faults raised the alarm: frozen 99%; spike 91%; level shift 80%; noise burst 57%; dropout 98%; clock 3 h out 85%.
- **Speed (simulated stations, one machine, one core, in-process, every layer on):** median 7.682 ms and 99th percentile 13.824 ms per reading with 100 stations, 123.9 readings/s.
- **The same with the Isolation Forest layer off** (a config flag; the ablation shows it adds almost nothing): median 0.526 ms, 1430.1 readings/s.
- **Speed through the real HTTP server (FastAPI + SQLite, 50 stations, 8 clients):** median 133.12 ms, 95th percentile 164.74 ms, 58.5 requests/s, 0 errors.
<!-- NUMBERS:END -->

## Title
**AtmosGuard: is this the sensor, or is this the sky?**

## One line
An explainable sensor-health and anomaly system for one automatic weather station, from temperature, pressure and humidity alone, that
escalates real extreme weather as an alert and flags broken sensors, with the evidence on real Indian weather.

## The problem (what and why)
An automatic weather station reports every few minutes from places nobody visits. A failing sensor and real weather look alike on a chart:
a stuck barometer looks like the calm before a cyclone, and a cyclone's pressure fall looks like a failing barometer. Filters that clean
everything delete the storm the network exists to see; filters that trust everything feed bad data into forecasts and warnings. Sparse
networks (the Andamans, Ladakh, the Thar) also cannot lean on neighbouring stations.

## Proposed solution (about 120 words)
AtmosGuard judges each reading from one station's own temperature, pressure and humidity, with no neighbours, and gives one of four
verdicts: `VALID`, `WEATHER`, `SUSPECT`, `FAULT`, with a plain-English reason. Real weather is escalated, never deleted. The raw value is
never overwritten; an estimate for a missing or faulty value is stored beside it with an uncertainty band. Around the verdicts it keeps a
health score, a drift monitor that states the smallest drift it can see, a maintenance ticket with a projected service date, and live
fault injection so a judge can break the sensor and watch the system respond. An ESP32 node runs the first layer on the device.

## Technical approach (about 170 words)
Layer 0 is closed-form physics (ranges, dew point, wet-bulb). Layer 1 checks health per channel: frozen values, steps, spikes, noise, gaps
and CUSUM, with limits **learned from each station's own clean history** (the reporting resolution, the longest ordinary run, the usual
step), because airports and stations round differently and fixed limits alarmed on most of the clean data. Layer 2 asks whether a
reading is normal for this station in this month and hour. Layer 3 adds an Isolation Forest and a Mahalanobis distance of departures and
rates of change that names the channel that drove it. Timing checks catch a wrong clock and a same-instant jump on several channels.
Fusion decides: impossible, frozen or missing is a fault; one channel jumping while the others are actually quiet is a fault; several
channels moving or departing together is weather; anything ambiguous is suspect. Everything is configurable, every layer can be switched
off, and the system still runs.

## Feasibility and viability
Runs on a laptop (the speed lines above are measured; state is per station so the cost of a reading does not grow with the number of
stations). Committed models and real data mean a fresh clone runs in a minute. Docker Compose, an OpenAPI interface, an optional
API key and rate limit, retention, CI on every commit. The edge node is an ESP32 with a BME280 (about Rs 700-1,500); its checks are one
portable header that the tests compile and compare with the Python. **Not yet done:** running on hardware, measuring energy (an estimate
and the measurement recipe are in `docs/HARDWARE.md`).

## Impact and benefits
Cyclone and severe-weather warnings need pressure and temperature traces that can be trusted and that are not cleaned away when they
matter. Forecast models and agricultural advisories ingest fewer bad values. Maintenance visits go where a sensor is drifting or has failed
instead of on a calendar. Sparse networks get a quality check that needs no neighbour. See `docs/USE_CASES.md`.

## Research and references
NOAA ISD (data); HadISD (station-learned streak thresholds); Oklahoma Mesonet QA (preserve real extremes); ECMWF observation monitoring;
Isolation Forest (Liu et al. 2008); Mahalanobis distance; Theil-Sen and Mann-Kendall trend tests with autocorrelation care; SHAP. Full list,
with what is standard, adapted and ours: `docs/NOVELTY_AND_PRIOR_ART.md` and the References of `docs/TECHNICAL_REPORT.md`.

## What is novel (the exact sentence)
> AtmosGuard integrates physics-based T/P/RH coherence, per-station statistical normality, station-learned health limits and unsupervised
> multivariate ML into one explainable pipeline for a single station with no neighbours, and it treats genuine extreme weather as its own
> escalated verdict. We do not claim any technique is new. Our contribution is the integration and the evidence: 26 real Indian stations,
> a holdout sealed in time and in space, false alarms on real cyclones reported separately, baselines and an ablation on the same data,
> agreement with NOAA's quality flags, and the failures the real data exposed.

## What we say we cannot do (say it first)
Detection is measured on **injected** faults (no labelled real faults exist). The data are airport records, not IMD AWS records. On the
eight unseen stations 3 of 98 real extreme-weather windows contain a `FAULT` verdict (the causes are in `docs/HOLDOUT_POSTMORTEM.md`). A
single station with no reference cannot see small drift or a constant offset present from the start. The firmware has not run on hardware.

## 30-second pitch
"A broken barometer and a cyclone look the same on a chart. AtmosGuard tells them apart from one station's own temperature, pressure and
humidity, and it never deletes a storm: real weather is escalated as an alert. We tested it on real records from 26 Indian stations with a
holdout we sealed and ran once, and we report the false-alarm rate on real cyclones separately from the injected-fault scores. We also tell
you what it cannot do. Break the sensor yourself: this is the control panel."

## 2-minute pitch
1. **The gap (15 s).** Show the demo's Fani replay. "The station stopped reporting at landfall. Was that the sensor or the sky?"
2. **The idea (25 s).** Four verdicts, WEATHER as its own verdict, reason in words, raw value kept.
3. **The proof (40 s).** "Real data broke our first version: 63 % of clean samples alarmed. Here is what we changed and why (tuning log).
   Then we sealed a holdout in time and space, committed the protocol first, and ran it once." Show the three-column headline table.
4. **The demo (25 s).** Control panel: freeze the barometer, inject a spike, then replay a cyclone and show `WEATHER`, not `FAULT`.
5. **The honesty (15 s).** "On unseen stations 3 of 98 extreme windows got a FAULT; the causes are documented and we did not tune on them."
