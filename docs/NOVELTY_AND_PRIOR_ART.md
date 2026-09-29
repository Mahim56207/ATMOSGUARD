# Novelty and prior art

**Short version.** AtmosGuard does not introduce a new detection algorithm, and we do not claim one. Every technique in it
exists somewhere. What we contribute is (1) an *evidence* standard that the other public entries on this problem statement
do not meet, (2) a single-station, neighbour-free integration built for sparse networks, and (3) a small number of
engineering results that come from running on real data, each stated with its prior art next to it.

This document is the part of the submission a sharp judge will read first. It says what is standard, what we adapted, what
is ours, and where we looked for prior art and did not find it. "Not found" always means "not found in the sources listed",
never "does not exist".

## 1. What is standard (not ours)

| Technique | Where it already exists |
|---|---|
| Range, step, persistence, internal-consistency (dew point ≤ T) checks | WMO-No. 8; NOAA MADIS; HadISD (Dunn et al. 2012, 2016); Oklahoma Mesonet |
| Per-station seasonal / hour-of-day climatology limits | Oklahoma Mesonet; HadISD; Qu et al. 2025 (per-site K-sigma thresholds) |
| CUSUM, Theil-Sen / Mann-Kendall trend tests | textbook; Mann-Kendall with prewhitening for autocorrelated atmospheric series (Atmos. Meas. Tech. 2020) |
| Isolation Forest, autoencoder anomaly detection on observations | ECMWF operational observation checking (Dahoui et al.); Qu et al. 2025; many SIH entries |
| SHAP explanations of a meteorological anomaly model | Qu et al. 2025 (autoencoder + SHAP) |
| Weather-vs-fault discrimination | ECMWF classifier (can dismiss an event); Oklahoma Mesonet is designed to preserve real extremes; several SIH entries |
| Health score 0-100, maintenance tickets, imputation | Oklahoma Mesonet trouble tickets; Vaisala NM10; SaQC; many SIH entries |
| Isolation Forest on an ESP32-class device | industrial-IoT examples exist |
| Distribution-based (station-learned) thresholds for repeated-value streaks | **HadISD**: the streak threshold is set from the distribution of run lengths |
| "Weather moves several channels, a drifting sensor moves one" as an attribution idea | blind-calibration and sensor-network literature (e.g. probabilistic separation of environmental variation from instrumental drift) |
| Common-mode fault detection by analytical redundancy | standard in industrial fault detection and isolation |
| Spatial consistency against neighbouring stations (the optional peer layer, `docs/PEER_LAYER.md`) | spatial regression test (Hubbard et al. 2005, J. Atmos. Oceanic Technol. 22, 105-112); spatial corroboration in GHCN-Daily QA (Durre et al. 2010, J. Appl. Meteor. Climatol. 49, 1615-1633); MADIS spatial consistency check; HadISD neighbour checks (Dunn et al. 2012). Ours is the same idea in its simplest form (median neighbour anomaly, learned 7-day limit); we claim the measurement on 24 Australian AWS, not the method |
| Pressure response is fast, humidity response is slow (and slower when fouled) | eddy-covariance flux literature (Ibrom et al. 2007; Mammarella et al. 2009); radiosonde lag correction |

## 2. What we adapted (their idea, our engineering)

| What | From | What we changed | What we measured |
|---|---|---|---|
| Learned frozen-run limit | HadISD streak thresholds | Learned per station from clean history *online*, detects the station's reporting resolution, and grades the flag: a run just past the limit is `SUSPECT`, a run twice the limit is `FAULT` | On the six real DEV stations, switching the learned limits off (the ablation; fixed limits) makes **63.1 %** of clean samples alarm and gives FAULT on 28.6 % of real extreme-weather samples (all 30 windows); with learned, graded limits it is **1.9 %** and 0 FAULT verdicts in 30 windows (the fixed-limit version produced FAULTs from a real pressure plateau inside a cyclone) |
| Isolated-trend rule for drift | blind-calibration / environmental-vs-instrumental drift literature | Applied to the daily-mean residuals of a single station's three channels, with a persistence requirement | False drift claims on clean real data fell from **97.7 %** to about **1 %** of station-days |
| Autocorrelation-aware drift test | Mann-Kendall prewhitening literature | Daily means, AR(1)-inflated standard error, winsorised residuals, smooth (not stepped) climatology | see the drift table in `results/REPORT.md` |
| Common-mode / clock checks | HadISD diurnal-cycle timing check; industrial FDI | Implemented as layers T1/T2 that can be switched off; T1 evaluated on real data with an injected 3-hour clock shift | ablation row "without timing layer" |

## 3. What is ours

1. **The evidence standard.** Every other public repository we read for this problem statement is synthetic-only, reports
   unverified metrics, or has no metrics at all (the survey is in section 5). AtmosGuard is evaluated on **26 real Indian
   airport stations (2016-2024, NOAA ISD)**, with:
   - a protocol written and committed before the holdout was read (`config/protocol.md`, lock file `data/holdout/.holdout_used`);
   - a holdout sealed **in time** (same six stations, 2022-2024) **and in space** (eight stations never used for any tuning,
     including three that report only every 3 hours);
   - extreme-weather windows picked by objective rules on the data, not by what the system says about them;
   - the false-alarm rate **on real cyclones, heat, cold and sharp fronts, reported separately** from the injected-fault score;
   - baselines and an ablation run on the same real data;
   - agreement with NOAA's own quality flags, described as agreement with another automated system;
   - the failures found and fixed, listed (section 6).
2. **A single-station, neighbour-free design that survives contact with rounded data.** Most operational QC leans on
   neighbours or a model background. Every check here uses one station and its own history, and it copes with the whole-degree,
   whole-hPa reporting real Indian stations use (the reason the naive version alarmed on two thirds of clean data).
3. **Edge parity you can check.** The L0 checks that run on the ESP32 live in one portable C++ header. The tests compile that
   exact header on a laptop and compare it with the Python implementation on thousands of inputs. (It has not been run on
   hardware; see `docs/WHAT_WE_DO_NOT_CLAIM.md`.)
4. **Break-the-sensor-on-demand.** `POST /inject` alters the next readings of any live stream the way a failing sensor would,
   so a judge can cause a fault and watch the verdict, reason and health score respond.
5. **A stated detectability floor.** The drift monitor reports the smallest slope it can tell from weather at that station
   right now. On real data a single station with no reference can only see drifts of several times the service limit within
   weeks. We say so, with the numbers.
6. **τ_RH, tested against itself.** The humidity response-time idea from the novelty audit is kept as research
   (`research/tau_rh.py`): bench-analysis code for the two-sensor experiment, plus a simulation that shows a co-located pair
   recovers the relative lag at 1 Hz, and that the estimate becomes biased at 1-minute means and wrong at 15-minute means.
   That is a measured boundary, not a claim of a working detector.

## 4. Where we looked and did not find prior art (exact wording for the submission)

- τ_RH as a routine health or predictive-maintenance metric in operational AWS quality control: not found in WMO CIMO
  guidance, NOAA USCRN, vendor datasheets or the public SIH repositories we read. The same physics exists in eddy-covariance
  and radiosonde work. We do not present τ_RH as working.
- A reference-free RH *offset* detector based on saturation frequency: we considered it. Related work exists (sustained
  saturation as a "deteriorated sensor" heuristic in agricultural QC; Bell et al. 2017 study in-service humidity drift from
  Met Office calibration records; HadISD flags saturation streaks). We did not build or claim it.

## 5. The field on this problem statement (what judges will see side by side)

Read from the public repositories (their READMEs, not run; a further search on 29 September 2026 found the four entries at the end of the table, and no entry with a locked holdout, a baseline or an ablation):

| Entry | Real data? | Metrics | Baselines / ablation | Notes |
|---|---|---|---|---|
| SkyGuard AI (muditagrawal-alt) | ISD-Lite, ~46k obs, 4 stations | precision 99.1 %, recall 91.3 % on **synthetic**; "real F1 90 %" | none shown | authors note their own bug fixes were entangled with re-tuning |
| SkyGuard (Devansh-66) | none | "Pre-Phase-0: nothing built or measured" | none | conformal prediction and neighbour differencing planned |
| SkyGuard AI (muditd27) | not stated | none | none | XGBoost + Isolation Forest + SHAP |
| SkyGuard AI (Alphaa1556) | synthetic generator | none | none | 46 commits, no validation |
| WeatherTrust | MOSDAC Junagadh AWS 2016-17 (not redistributable) | "98.83 % normal" (no ground truth) | none | rule + Isolation Forest, tower consensus |
| AWSense | synthetic only | "up to 98 % confidence" (uncalibrated) | none | psychrometric physics |
| AtmosAi | none documented | none | none | LSTM autoencoder |
| SkyGuard (vaibhav1874) | Open-Meteo ERA5 (reanalysis, not a station) | none | none | ensemble 35/35/30 |
| VAYU-GUARD (Aditya123CSE) | synthetic | none | none | 7 tests |
| ATML (Suryanshsaraf) | Jena, Chicago, Numenta | recall 59.6 %, F1 0.73 | LOF, dense AE | not the AWS problem's data |
| SkyGuard AI (anushreegoli28) | NOAA GHCNh, one station (Boston Logan), faults injected | "precision 100 %", "false-positive rate 0.0 %" on 150 injected ticks | none stated | physics ensemble + Isolation Forest, single station |
| Sky_Guard (VHARSHILJOSEPH) | IMD AWS data "with approved access", plus injected faults; volume not stated | none stated | none | uses neighbouring-station evidence; says its confidences "require empirical validation" |
| SkyGuard-AI (Kaviyakanagaraj77) | its own generator (states IMD data are not downloadable) | overall precision 0.50, recall 0.71, F1 0.59, on the same synthetic data used for development | none stated | five layers including neighbours, SHAP, fleet-wide detection, web app |
| SkyGuardAI (KATHIR-EEE) | not stated | none | none stated | Isolation Forest + z-score + an external weather API as reference |

None of them, as far as their READMEs show, has: a locked holdout, a real-cyclone false-alarm number, an ablation on real
data, an agreement check against operational QC flags, or a stated list of what it cannot do.

## 6. Failures real data exposed, and what we did (kept on purpose)

| Finding | Evidence | Fix |
|---|---|---|
| Fixed frozen and noise limits treat rounded values as stuck sensors | 63.1 % of clean DEV samples alarmed without them (1.9 % with), results table 2 | station-learned limits (`atmos/limits.py`) |
| A pressure plateau inside a cyclone reads as a frozen barometer | FAULT verdicts on real cyclone windows | two-tier frozen rule: soft just past the limit, hard at twice the limit |
| The drift monitor claimed drift almost every day | 97.7 % of station-days | daily means, autocorrelation-aware test, isolated-trend rule, persistence (about 1 %) |
| The seasonal cycle read as drift through a step-function climatology | reproduced in a unit test | smooth (bilinear in month and hour) expected value |
| A communication gap made the *next, healthy* reading SUSPECT | gap flags counted as false alarms | gaps are notices on the reading, not verdict changes |

## 7. The sentence for the submission

> AtmosGuard integrates physics-based T/P/RH coherence, per-station statistical normality, station-learned health limits
> and unsupervised multivariate ML into one explainable pipeline for a single station with no neighbours, and it treats
> genuine extreme weather as its own escalated verdict. We do not claim any technique is new. Our contribution is the
> integration and the evidence: 50 real stations (31 Indian airports, 12 Australian automatic weather stations and 7 US automated stations reporting every 20 minutes), a holdout sealed in time and in space, false alarms on real cyclones
> reported separately, baselines and an ablation on the same data, agreement with NOAA's quality flags, and the failures the
> real data exposed. We state plainly what we cannot claim: long-term drift validation, performance on labelled real faults,
> single-sensor humidity response time, and small offsets with no reference.
