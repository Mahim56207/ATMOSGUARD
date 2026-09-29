# Likely judge questions, and honest answers

Rule for every answer: **agree with what is true, name the prior art, point at what we added, and never defend a claim we cannot
support.** Numbers below are from `results/REPORT.md`; say which split you are quoting.

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

## The three questions the build guide says you will certainly get

**1. How is this different from the standard WMO checks?**
The range, step and persistence checks are standard and we include them. Three things differ. (a) Fixed limits fail on real data:
on real Bhubaneswar reports (whole degrees, whole hPa) a fixed-limit version alarmed on about two thirds of clean readings and called
real cyclones faults. We learn the frozen-run and noise limits per station from its own clean history (an idea HadISD uses for streaks;
ours adds resolution detection and a two-tier flag). (b) Real weather is a verdict, not a mistake: a coherent multi-channel change is
escalated as `WEATHER`. (c) We measured all of it against the textbook rules on the same real data; the rules baseline calls almost
every real extreme-weather window a fault.

**2. How do you know it works on real faults and not just injected ones?**
We do not, and we say so. No labelled real-fault set exists for Indian AWS. What we did instead: (a) the false-alarm rate on *real*
weather (clean data and 30+ real extreme-weather windows) with nothing injected, reported separately; (b) agreement with NOAA's own
quality flags on the raw record (another automated system, so it shows consistency, not truth); (c) injected faults, labelled injected,
scored so that only alarms the fault itself raised count. Real-fault validation against maintenance records is future work.

**3. What happens during a cyclone?**
Pressure falls tens of hPa, humidity rises, temperature drops: several channels move together, so the reading is escalated as
`WEATHER` and kept, never deleted. On Cyclones Fani, Vardah, Amphan (and Tauktae, Michaung, Remal, Biparjoy in the holdout) the number of
`FAULT` verdicts is what we report. Live: replay `data/demo/fani_BBI_2019-05.csv`. A pressure plateau inside the low used to read as a
frozen barometer; that was a real bug real data found and we fixed it.

## Novelty
**Is this just Isolation Forest plus rules, like the other teams?** The techniques are standard and we say so
(`docs/NOVELTY_AND_PRIOR_ART.md`). The difference is the evidence (26 real stations, a holdout sealed in time and space, twelve fresh stations tested against a rule registered first, run once with the
protocol committed first, baselines and an ablation on the same data, false alarms on real cyclones) and honest engineering results
(learned limits, the graded frozen flag, the isolated-trend drift rule, the quiet-channel fix). In the ablation the Isolation Forest earns
almost nothing; the Mahalanobis layer does the work, and we kept the forest because the problem statement lists it.

**Is humidity response time (tau_RH) your novelty?** No, it is research. The physics is established in eddy-covariance and radiosonde work; we
found no operational AWS QC system using it as a health metric. We built bench-analysis code for the two-sensor experiment and a simulation:
a co-located pair recovers the relative lag at 1 Hz, the estimate is biased at 1-minute means and wrong at 15-minute means, and one sensor
alone cannot do it at any resolution. It is not in the pipeline.

## Trust in the numbers
**Why should we believe the holdout?** The protocol (`config/protocol.md`) was committed before the holdout was read; `evaluate_real.py
--holdout` refuses to run unless that file is committed and clean, and writes `data/holdout/.holdout_used` with the commit it ran under. The
holdout is sealed in time (the same six stations, later years) and in space (eight stations never used for any tuning, three of them 3-hourly).
Everything we changed after looking at DEV is in the tuning log with its reason. After the first holdout run we corrected the *scoring* of
detection (background alarms inside long fault windows had inflated it); the pipeline was not touched, both scores are reported, and the
rerun reproduced the first run's registered numbers exactly.

**Your DEV numbers are better than holdout, aren't they?** DEV is where we tuned and looked at failures, so it is the optimistic set. We
report all three splits side by side; see `results/REPORT.md`.

**What is your false-alarm rate, and is it acceptable?** Report both: "any alarm" (`FAULT` or `SUSPECT`; `SUSPECT` means "review", the
reading is kept) and `FAULT` alone. In operations the useful reading is per thousand readings: multiply the percentage by ten.

## What confidence means
It is agreement between checks, a heuristic, **not** a probability. No metric uses it. The honest way to read reliability is the measured
rates in the tables. (Calibrating it, with a reliability diagram and isotonic regression, is listed in the build guide; we did not do it.)

## Drift and offsets
**Can it detect slow drift?** Large drift, yes; small drift, no. A single station with no reference sees drifts of several times the
service limit within weeks, and the monitor reports the smallest slope it can see at that station. False drift claims on clean real data
are about 1 % of station-days. **A constant offset from day one?** No single-station method can. We say so.

## Design choices
**Why single-station only?** The places India needs this most (Ladakh, the Thar, the Andamans) have no neighbour within hundreds of km.
With neighbours we would do better, and that is future work; the cold-start module borrows a frozen table, not live data.
**Why airport data, not IMD?** IMD AWS data are not public. The pipeline takes any CSV in the same layout; if a faculty contact can share
even weeks of real AWS data, run `evaluate_real.py` on it. **Why four verdicts?** Quality control and severe-weather alerting come out of one
engine, and mixed evidence must not delete a real extreme.
**What if a real weather event looks exactly like a fault (a real one-channel jump)?** Rule 2 would call it a fault; that is why "quiet" now
means the other channels actually did not move, and why we report the `FAULT` rate on real extreme weather separately so the cost is visible.

## Explainability
Every verdict has a plain-English reason and the checks behind it, built before any model runs. For the statistical layers: the Mahalanobis
squared distance splits **exactly** into per-feature contributions (they add up), and SHAP values for the Isolation Forest are available
when `shap` is installed (`GET /explain`). SHAP is optional because the forest earns least in the ablation.

## Edge, scale, deployment
**Does it run on the ESP32?** The L0 logic is plain C++ that is compiled and checked against the Python on thousands of inputs, and the
sketch type-checks against stand-ins for the Arduino libraries. It has not been compiled with the real toolchain or run on hardware in this
repository, and no energy figure is measured.
**How does it scale?** State is per station and nothing is shared. In the scale test the median time per reading stays flat from 1 to 100
simulated stations: about 7.5 ms with every layer on (about 125 readings/s on one core, which is arithmetic for roughly 7,000 stations
reporting once a minute) and about 0.5 ms with the Isolation Forest layer switched off (`layers.mlmodel: false`). The forest is most of
the per-reading time and the ablation shows it adds almost nothing to the verdicts, so a large deployment should switch it off. Through
the real HTTP server (one process, one lock) we measured about 58 requests/s with 8 concurrent clients; capacity grows by adding worker
processes, each owning a set of stations. Simulated stations on one machine are a design check, not a production load test. (An earlier
version of our scale test fed readings under the wrong station id, so the pipeline ran without its per-station models and reported
0.2 ms; that bug is fixed and has a regression test.)
**Docker?** The files exist and are checked statically; run `docker compose up --build` once before the demo.

## Things we dropped (say them before a judge does)
The pressure-tide barometer test (an offset leaves the tide untouched and a gain change scales the tide and weather equally); "35 degC
wet-bulb is impossible" (it has been observed; it is a soft flag); "nobody separates weather from faults" (ECMWF, the Oklahoma Mesonet and
several SIH entries do).
