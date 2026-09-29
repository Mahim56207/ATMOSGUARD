# What we do not claim

Read this before the demo. Every line is something a judge could take apart if we said the opposite, and every line is
also true of the repository as it stands.

## About the data
- **The data are airport records, not IMD AWS records.** IMD AWS data are not public. We use NOAA's Integrated Surface
  Database (METAR and SYNOP) for 26 Indian airport stations, 2016-2024 (14 for development and the first holdouts, 12 fresh). The instruments and siting differ from an AWS.
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
  cannot be seen by any single-station method, including this one.
- **Long-term drift behaviour is not validated.** Real calibration drift plays out over months and years; we tested ramps
  of 45 days.
- **The holdout was run once.** The result is whatever it was, including if it is worse than DEV. `data/holdout/.holdout_used`
  records when, and the protocol was committed before.

## About novelty
- **No technique here is new.** Physics checks, persistence tests, CUSUM, Isolation Forest and SHAP are standard. See
  `docs/NOVELTY_AND_PRIOR_ART.md` for what is standard, what we adapted, and what is ours.
- **We are not the first to separate weather from faults.** ECMWF, the Oklahoma Mesonet and several SIH entries do it.
- **τ_RH (humidity response time) is research, not a feature.** It is not in the live pipeline and we do not claim it detects
  faults in the field. What exists is analysis code for a bench experiment and a simulation of where the idea breaks.
- **The pressure-tide test and a "35 °C wet-bulb is impossible" rule were dropped.** The wet-bulb check is a soft flag only.

## About the hardware and deployment
- **The ESP32 firmware has not been compiled with the ESP32 toolchain or run on hardware in this repository.** The L0 logic
  it runs is a portable C++ header that *is* compiled and tested against Python on a laptop, and the sketch is type-checked
  against stand-ins for the Arduino libraries. That catches logic and type errors, not toolchain or timing problems.
- **The Docker files have not been built here** (no Docker on the machine that produced this repository). They are checked
  statically. Run `docker compose up --build` once before the demo.
- **The scale test uses simulated stations on one machine.** It shows that per-station cost does not grow with the number
  of stations. It is not a production load test.
- **This is a validated prototype, not a system ready for an IMD server.** The gap is deployment engineering, security
  review and a long field trial.
