# What we do not claim

Read this before the demo. Every line is something a judge could take apart if we said the opposite, and every line is
also true of the repository as it stands.

## About the data
- **The data are not IMD AWS records.** IMD AWS data are not public, and the hosts that might serve one are blocked where this was built. We use NOAA's Integrated Surface
  Database (METAR and SYNOP) for 26 Indian airport stations, 2016-2024 (14 for development and the first holdouts, 12 fresh), and, in the third sealed set, five more Indian airports and seven
  Australian Bureau of Meteorology automatic weather stations (hourly SYNOP at 0.1 C and 0.1 hPa). Those are real automatic weather stations at fine resolution, but Australian, hourly, and not IMD.
- **No 1-15 minute record has been tested.** The fastest real record is 20 minutes: seven US automated stations reporting every 20 minutes at 0.1 C (fresh-3: 2.7 % clean false alarms, 94-100 % of injected faults by type). Every other record is hourly or 3-hourly. The pipeline scales its windows with the cadence and is unit-tested at 1, 15 and 60 minutes, but a 1-15 minute real record has not been run.
- **Relative humidity is derived, not measured.** ISD carries temperature and dew point; RH is computed from them
  (Magnus). So T and RH are not independent measurements in our evaluation, and the humidity channel inherits the rounding
  of two whole-degree numbers.
- **METAR values are whole degrees and whole hPa.** Pressure is QNH (altimeter setting), not station pressure. Our
  learned-limits layer exists because of this.
- **No labelled real faults exist.** There is no public labelled fault set for Indian AWS. Every injected-fault score is
  measured on faults *we* injected.
- **NOAA quality flags are another automated system.** Agreement with them means consistency with existing practice, not
  proof that we are right or that they are.

## About the results
- **Injected-fault accuracy is not real-world accuracy.** It is always labelled "injected".
- **Confidence is agreement between checks, not a calibrated probability.** `0.95` does not mean 95 % chance of being right.
- **A single station with no reference cannot see small drifts.** The drift monitor finds drifts of several times the
  service limit within weeks and reports the smallest slope it can see. Drifts smaller than that need a reference (a
  neighbour, a redundant sensor, or a calibration visit).
- **Offset with no reference is invisible.** A humidity sensor that reads 3 % high from day one, with nothing else changing,
  cannot be seen by any single-station method, including the core of this one. The optional peer layer (`docs/PEER_LAYER.md`) sees offsets and drifts against three or more neighbours within 250 km
  (a 2 hPa offset in 91-96 % of trials within 21 days on two Australian AWS clusters, against 0-4 % for the station alone), but it needs a dense network, misses half-unit offsets, is weak on humidity,
  cannot see a fault that moves all the neighbours too, and was measured on injected faults. On 31 Indian airports it needs a 600 km radius (only 4 of 31 have three neighbours within 250 km), finds a 2 hPa offset in 91 % of trials against 21 % alone, gains nothing on humidity, and has 2-4 % false alarm days.
- **Long-term drift behaviour is not validated.** Real calibration drift plays out over months and years; we tested ramps
  of 45 days.
- **The holdout was run once.** The result is whatever it was, including if it is worse than DEV. `data/holdout/.holdout_used`
  records when, and the protocol was committed before. It was read a second time (`holdout_run2`) only to re-score detection under Amendment 1;
  every registered number reproduced exactly (`python compare_runs.py`).
- **The shipped default is not exactly what the holdout ran.** After the fresh-station test, one remedy (the ceiling-aware frozen rule) was adopted by a
  rule registered before that test. The evaluation's `full` configuration still forces it off, so every reported number reproduces; the remedy's own numbers
  are on the fresh stations only, and it changed nothing on DEV. A second remedy (the expected-change-aware step rule) was adopted after the fresh-2 test by a rule registered before it (4 windows with a `FAULT` to 1 of 134). The
  frozen pipeline got a `FAULT` in 3 of 98, 3 of 139 and 4 of 134 real extreme-weather windows on the three sets of unseen stations. A third remedy (a sustained one-channel offset) was
  tested and rejected.
- **Fresh-2 false alarms are 9.3 %, not 2.5 %.** Four Australian AWS whose 2016-2019 records had 16 reports a day with alternating 1 h and 2 h gaps (hourly all day from 2020) have no learned noise
  limit, so a fixed floor tuned on coarser data alarms on them (33 %, 26 %, 21 % and 8 % of clean samples). Every other station in every set had its limits learned. Refit on the current cadence is the
  fix (`python refit.py`; a post-hoc diagnostic on the same stations gives 2.6 % false alarms). A fourth sealed set repeated the failure (45 % false alarms on five more irregular-record stations); the warm-up remedy cut it to 1.8 % but cost 6 points of noise-burst detection and was rejected by the rule registered first, so it is an operator's option, not a default; the pipeline says so in an informational notice on each reading.
- **Freezing rain can still look like a stuck thermometer.** At two Great Lakes stations in January 2024 the temperature sat at 0 C (or -1 C) for about nine hours in humid air and the frozen rule called it `FAULT` (3 of 103 real-weather windows). A remedy was registered and tested on a fifth set of twelve northern US airports; that set had no such window (0 `FAULT` in 180), so the remedy changed nothing and is not adopted. The case is neither fixed nor shown to be common.
- **Detection is lower on unseen stations than on DEV,** and most detections of spikes, level shifts, noise bursts and wrong clocks are `SUSPECT`, not `FAULT`.
  Simpler detectors beat the full pipeline on some fault types (see `results/REPORT.md`).
- **The cold-start study covers six stations,** each borrowing from its nearest neighbour among the other five. A new station in a climate none of them share may
  need more of its own history.
- **"Learn from the first half of the file" trusts that half.** Bring your own CSV learns a new station from the first half of its file; a stuck sensor or a storm in
  that half is learned as normal. `evaluate_csv.py` is the careful offline version.

## About novelty
- **No technique here is new.** Physics checks, persistence tests, CUSUM, Isolation Forest and SHAP are standard. See
  `docs/NOVELTY_AND_PRIOR_ART.md` for what is standard, what we adapted, and what is ours.
- **We are not the first to separate weather from faults.** ECMWF, the Oklahoma Mesonet and several SIH entries do it.
- **τ_RH (humidity response time) is research, not a feature.** It is not in the live pipeline and we do not claim it detects
  faults in the field. What exists is analysis code for a bench experiment and a simulation of where the idea breaks.
- **The pressure-tide test and a "35 °C wet-bulb is impossible" rule were dropped.** The wet-bulb check is a soft flag only.

## About the hardware and deployment
- **The ESP32 firmware has not been compiled with the ESP32 toolchain or run on hardware in this repository.** The L0 logic
  it runs is a portable C++ header that *is* compiled and tested against Python on a laptop, and the sketch itself is executed on the laptop against a simulator of the
  Arduino-ESP32 pieces it uses (virtual clock, scripted sensor, dropping Wi-Fi, recording HTTP client): sampling, the range check, the minute mean, the frozen counter,
  the JSON, the offline queue and the clock guard are exercised, and what it POSTs is accepted by the real API (`tests/test_firmware_sim.py`). That catches logic,
  type and contract errors, not toolchain, bus, radio or timing problems on the chip. `docs/HARDWARE_TEST_LOG.md` is the one-hour checklist for the board.
- **Docker was built and run once, not continuously.** `docker compose up --build` produced an image, both services started, the API's health check passed and a replay through the
  containerised API worked (in an environment whose proxy needed its CA injected into the build). It is not part of CI, so run it once on the demo machine.
- **The scale test uses simulated stations on one machine.** It shows that per-station cost does not grow with the number
  of stations. It is not a production load test.
- **This is a validated prototype, not a system ready for an IMD server.** The gap is deployment engineering, security
  review and a long field trial.
