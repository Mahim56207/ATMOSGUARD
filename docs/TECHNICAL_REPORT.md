# AtmosGuard: telling a broken sensor from real weather at one automatic weather station

**Technical report.** Smart India Hackathon 2026, problem statement 26073. Repository: <https://github.com/Mahim56207/ATMOSGUARD>. Every number below is generated from the committed result files (`results/`), which are produced by the commands in `results/RUNS.md`.

## Abstract

AtmosGuard judges every temperature, pressure and humidity reading of a single automatic weather station, with no neighbouring stations, as `VALID`, `WEATHER`, `SUSPECT` or `FAULT`, and says why. Real extreme weather is escalated as its own verdict and is never deleted as noise. We claim no new algorithm; the contribution is the integration for one station and an evidence standard: 62 real stations (31 Indian airports, 12 US northern airports, 12 Australian automatic stations and 7 US automated 20-minute stations; NOAA ISD, 2016-2024), a protocol committed before a holdout that is sealed in time and in space, false alarms on real cyclones reported separately from injected-fault scores, baselines and an ablation on the same data, and the failures kept on record. After the holdout showed three real-weather failure windows, we registered a decision rule and tested the proposed remedies on twelve further stations nobody had looked at: one remedy was adopted and one rejected. Headline results:

- **DEV (tuned here).** Clean data: 1.9% (1.8-2.0) of 98340 samples got FAULT or SUSPECT; 0.0% (0.0-0.0) got FAULT. Real extreme weather: FAULT on 0.0% (0.0-0.1) of 3503 samples (0 of 30 windows); WEATHER on 10.8%, SUSPECT on 9.0%.
- **holdout in time (same six stations, 2022-2024).** Clean data: 2.5% (2.4-2.6) of 147078 samples got FAULT or SUSPECT; 0.0% (0.0-0.0) got FAULT. Real extreme weather: FAULT on 0.0% (0.0-0.1) of 4374 samples (0 of 38 windows); WEATHER on 11.8%, SUSPECT on 8.2%.
- **holdout in space (eight unseen stations).** Clean data: 2.9% (2.8-3.0) of 237411 samples got FAULT or SUSPECT; 0.0% (0.0-0.1) got FAULT. Real extreme weather: FAULT on 0.3% (0.2-0.4) of 9074 samples (3 of 98 windows); WEATHER on 15.7%, SUSPECT on 8.6%.
- **fresh stations (twelve more, sealed before the remedies were tested).** Clean data: 2.5% (2.5-2.6) of 364440 samples got FAULT or SUSPECT; 0.1% (0.1-0.1) got FAULT. Real extreme weather: FAULT on 0.1% (0.1-0.2) of 11782 samples (3 of 139 windows); WEATHER on 10.3%, SUSPECT on 6.8%.
- **fresh-2 stations (a third set of twelve: five Indian airports, seven Australian automatic weather stations).** Clean data: 9.3% (9.2-9.3) of 453323 samples got FAULT or SUSPECT; 0.0% (0.0-0.0) got FAULT. Real extreme weather: FAULT on 0.0% (0.0-0.1) of 14732 samples (4 of 134 windows); WEATHER on 4.1%, SUSPECT on 14.1%.
- **fresh-2, the five Indian airport stations.** Clean data: 3.2% (3.1-3.3) of 189591 samples got FAULT or SUSPECT; 0.0% (0.0-0.0) got FAULT. Real extreme weather: FAULT on 0.0% (0.0-0.1) of 3994 samples (0 of 42 windows); WEATHER on 7.3%, SUSPECT on 4.7%.
- **fresh-2, the seven Australian automatic weather stations.** Clean data: 13.6% (13.5-13.7) of 263732 samples got FAULT or SUSPECT; 0.0% (0.0-0.0) got FAULT. Real extreme weather: FAULT on 0.0% (0.0-0.1) of 10738 samples (4 of 92 windows); WEATHER on 3.0%, SUSPECT on 17.6%.
- **fresh-3 stations (a fourth set of twelve: seven US 20-minute stations, five Australian AWS).** Clean data: 9.7% (9.6-9.8) of 1026508 samples got FAULT or SUSPECT; 0.0% (0.0-0.0) got FAULT. Real extreme weather: FAULT on 0.1% (0.1-0.1) of 45332 samples (5 of 160 windows); WEATHER on 3.0%, SUSPECT on 12.8%.
- **fresh-3, the seven US 20-minute stations.** Clean data: 2.7% (2.7-2.7) of 858141 samples got FAULT or SUSPECT; 0.0% (0.0-0.0) got FAULT. Real extreme weather: FAULT on 0.1% (0.1-0.1) of 38294 samples (3 of 103 windows); WEATHER on 3.4%, SUSPECT on 5.3%.
- **fresh-3, the five Australian AWS.** Clean data: 45.4% (45.1-45.6) of 168367 samples got FAULT or SUSPECT; 0.0% (0.0-0.0) got FAULT. Real extreme weather: FAULT on 0.0% (0.0-0.1) of 7038 samples (2 of 57 windows); WEATHER on 1.3%, SUSPECT on 53.7%.
- **fresh-4 stations (a fifth set of twelve northern US stations with freezing winters).** Clean data: 2.0% (1.9-2.0) of 498994 samples got FAULT or SUSPECT; 0.0% (0.0-0.0) got FAULT. Real extreme weather: FAULT on 0.0% (0.0-0.0) of 22864 samples (0 of 180 windows); WEATHER on 4.0%, SUSPECT on 6.2%.

Detection is measured on **injected** faults, because no labelled real faults exist; the data are airport records, not IMD AWS records; and on the unseen stations a small number of real extreme-weather windows did receive a `FAULT` verdict (3 of 98 on the eight holdout stations, 3 of 139 on the twelve fresh ones, 4 of 134 on the twelve fresh-2 ones, 5 of 160 on the twelve fresh-3 ones; Section 5). Sections 5 and 6 say exactly what we cannot show.

## 1. Introduction

### 1.1 The problem
An Automatic Weather Station (AWS) reports temperature, pressure and humidity every few minutes, often from places nobody visits.
A failing sensor and real weather look alike on a chart: a barometer that has stuck reads the same flat line as the calm before a
cyclone, and the sharp pressure fall of a cyclone reads like a barometer that has failed. A system that silences every surprise
deletes the storm the network exists to see; a system that trusts every surprise sends bad data into forecasts and warnings.
Problem statement 26073 asks for anomaly detection and sensor-health monitoring **from these three channels only**.

We accepted two constraints beyond the statement, because they are what sparse networks (the Andamans, Ladakh, the Thar) actually have:
one station is judged on its own record, with **no neighbouring stations and no reanalysis**; and **no fault labels**, because
no public labelled record of real AWS faults exists.

### 1.2 What we built
AtmosGuard judges every reading with one of four verdicts, `VALID | WEATHER | SUSPECT | FAULT`, and gives the reason in words. Real
weather is **escalated as an alert (`WEATHER`), never deleted as noise**. A raw value is never overwritten; an estimate for a missing
or faulty value is stored beside it with an uncertainty band. Around the verdicts sit a health score, a drift monitor with a stated
detectability floor, a maintenance ticket with a projected service date, live fault injection for the demonstration, and an ESP32
node whose first layer is one portable C++ header that the tests compile and compare with the Python (Section 3).

### 1.3 What we claim, and what we do not
**We do not claim a new algorithm.** Physics checks, persistence tests, CUSUM, Isolation Forest, Mahalanobis distance, SHAP and
weather-versus-fault discrimination are standard, and Section 7 says where each comes from. We claim an **integration** built for one
station with no neighbours that copes with the rounded values real stations report, and an **evidence standard**: real records from 14
Indian stations, a holdout sealed in time and in space with the protocol committed first, false alarms on real cyclones reported
separately from injected-fault scores, baselines and an ablation on the same data, and the failures kept on record. Section 6 lists what
we cannot show.

### 1.4 Reading guide
Section 2 describes the data and the protocol. Section 3 describes the method. Section 4 gives the results exactly as the evaluation
program wrote them, in five separate numbers that are never merged. Section 5 explains what the holdout found that development did not.
Section 6 is the limitations. Section 7 is related work and what is ours. Section 8 shows how to reproduce everything.


![Figure 1. What one reading goes through.](figures/diagram_pipeline.png)

*Figure 1. What one reading goes through.*

![Figure 2. The four verdicts and what each looks like on the three channels (sketches).](figures/diagram_sensor_or_sky.png)

*Figure 2. The four verdicts and what each looks like on the three channels (sketches).*

## 2. Data and evaluation protocol

### 2.1 Data
Records are NOAA Integrated Surface Database (ISD) hourly METAR and 3-hourly SYNOP reports for 14 Indian airports, 2016-2024,
downloaded from NOAA's public open-data bucket. We take temperature, dew point and pressure only. **Humidity is computed from
temperature and dew point** (Magnus formula), because ISD carries no relative humidity. METAR values are rounded to whole degrees and
whole hPa. These are airport observations, not IMD AWS records; every number in this report inherits that caveat. NOAA's own quality
code for each value is kept only as a weak label for an agreement table; it never influences a verdict.

### 2.2 Split
Every station is trained on its own 2016-2019 record with extreme-weather windows and NOAA-flagged values removed. Six stations
(Bhubaneswar, Chennai, Kolkata, Delhi, Jaipur, Thiruvananthapuram) are the **DEV** set: 2020-2021, where tuning was allowed. The
**holdout in time** is the same six stations in 2022-2024. The **holdout in space** is eight stations that were never used for any
tuning: Ahmedabad, Nagpur, Mumbai, Guwahati, Visakhapatnam (hourly) and Port Blair, Bhuj, Cochin (3-hourly SYNOP), 2020-2024.
The protocol (`config/protocol.md`) was committed before the holdout was read; the evaluation program refuses to read the sealed
files unless that file is tracked and unmodified, and it writes a lock file when it runs.

### 2.3 Extreme-weather windows
Windows are chosen by rule on the data, before any verdict is looked at: the deepest low-pressure episodes (at least 10 hPa below
the trailing 30-day median), the hottest and coldest days (top and bottom 0.3 %), and the sharpest 3-hour temperature change of each
year. Real cyclones fall out of the rules without our choosing them: Amphan (Kolkata, 2020) is judged in DEV; Tauktae (Mumbai and
Ahmedabad, 2021), Biparjoy (Bhuj, 2023), Michaung (Chennai, 2023) and Remal (Kolkata, 2024) in the holdouts. Vardah (2016) and Fani (2019)
fall in the training years, so they are cut out of training and used for the demonstration replay, not for a reported number.
A `FAULT` verdict inside such a window is counted as a failure: real weather was called a broken sensor.

### 2.4 The five numbers
1. **Detection of injected faults**, per type (frozen 48 h, spike, level shift 24 h, noise burst 24 h, dropout, clock 3 h out for 4 days).
2. **False alarms on clean real data** (nothing injected).
3. **Real extreme weather** (nothing injected): FAULT, SUSPECT, WEATHER and VALID shares, and windows containing a `FAULT`.
4. **Agreement with NOAA's flags**, described as consistency with another automated system, not accuracy.
5. **Slow drift** through the health monitor, including false drift claims.
plus speed. Each is computed for the full pipeline, for seven ablations (one layer off by its config flag) and for five baselines
(range only; textbook range + step + persistence; climatology z-score only; Isolation Forest only; Mahalanobis distance only), fitted on
the same training data.


### 2.5 What was changed after looking at DEV (the tuning log, from `config/protocol.md`)

Every change below was made against DEV stations and years only, and each was checked not to reduce detection of injected faults.

| # | Change | Why (measured on DEV) |
|---|---|---|
| 1 | Station-learned frozen and noise limits (`atmos/limits.py`) | fixed limits alarmed on 63.1 % of clean samples and gave FAULT on 28.6 % of real extreme-weather samples (30 of 30 windows) |
| 2 | Frozen is graded: soft just past the learned limit, hard at twice it | a pressure plateau inside a real cyclone read as a frozen barometer |
| 3 | Communication gaps are notices, not verdict changes | the healthy reading after a gap was counted as a false alarm |
| 4 | Drift monitor: daily means, smooth expected value, autocorrelation-aware test, isolated-trend rule, 7-day persistence, 60-day window | the first version claimed drift on 97.7 % of station-days; now 1.1 % |
| 5 | Rule 2 ("one channel jumped, the others are quiet") requires the others to be actually quiet | 2 of 30 real windows had a FAULT: real thunderstorm outflows (Kolkata, Delhi) where an un-flagged 8-12 C fall counted as "quiet" |
| 6 | Mahalanobis layer (departures from normal + rates of change) | level-shift detection 74 % and noise 66 % without it; 97 % and 81 % with it, false alarms unchanged. The Isolation Forest contributes almost nothing in the ablation and is kept because the guide lists it |
| 7 | WEATHER also when two or more channels depart from normal together (level, not only movement) | most SUSPECT verdicts in real extreme windows showed no movement in the last hour; detection of injected faults unchanged |
| 8 | Clock check recomputed every 3 hours of data time instead of every reading | 4.6x faster evaluation; a wrong clock lasts days |
| 9 | "Quiet" in rule 2 is also judged against the station's learned usual step (1.5 x its 75th percentile) | on a 3-hourly copy of a DEV station, 5 of 2,695 clean samples got FAULT: day/night swings where a 5 C fall (under the step cap) let derived humidity jump. Now 0. The copy was made from DEV data only; no sealed station was read to find this |

DEV result after the changes (`results/dev_run3.txt`, the final code): clean false alarms 1.9 % (FAULT 0.0 %) over 98,340 samples; real extreme weather: FAULT
0.0 % (0 of 30 windows), WEATHER 10.8 %, SUSPECT 9.0 %; detection: frozen 100 %, dropout 100 %, spike 98.8 %, level shift 97.1 %,
clock shift 96.8 %, noise burst 80.7 %.

### 2.6 Amendment 1: how detection is scored (from `config/protocol.md`)

`results/holdout_run1.*` was produced under the criterion registered above and is kept unedited. Afterwards we found a flaw in how
**detection is scored**, not in the pipeline: "any alarm in the fault window" also credits background false alarms (about 2 % of
samples) that land inside long windows. Over a 4-day clock-shift window that alone gives about an 84 % chance of some alarm, and the
simpler baselines get the same free credit (the climatology-only baseline "detects" 53-61 % of clock shifts almost entirely from its
background alarms). The scoring is corrected and both scores are reported:

- **Registered criterion** (unchanged): any `FAULT` or `SUSPECT` from the first faulty sample to the last plus 60 minutes.
- **Corrected criterion (now the primary detection table):** the same window, but an alarm counts only if the *same sample* was not an alarm on the
  un-faulted series ("the fault raised it"). Also reported: how often the alarm is a `FAULT` (named) and how often a miss made samples look like
  `WEATHER` (the risk of the coherent-level route).

To score it, DEV (`dev_run4`) and the holdout (`holdout_run2`, run with `--force-rerun-holdout`; the original lock file stays in git history) were run
again on the same code. Nothing about the pipeline or its settings changed between `holdout_run1` and `holdout_run2`
(`git diff 9cd24f1 HEAD -- atmos config/settings.yaml` shows only a new `explain.py`, an optional retention method and an `api:` block). The rerun is deterministic, so
its registered-criterion numbers must equal `holdout_run1`'s; `results/RUNS.md` records whether they do.

`holdout_run1` also showed what a holdout is for: on the eight unseen stations 3 of 98 real extreme-weather windows contain a `FAULT` verdict (0.3 % of
their samples), where DEV had none. No change was made in response. It is listed as a limitation and analysed in `docs/TECHNICAL_REPORT.md`.

### 2.7 Amendment 2: testing the post-mortem remedies on twelve unseen stations (from `config/protocol.md`)

`docs/HOLDOUT_POSTMORTEM.md` explained the three real-weather windows that got a `FAULT` on the sealed holdout and proposed two remedies, and said
they could not be evaluated honestly on the stations that revealed the problem. This amendment sets up that evaluation on data nobody has looked at.
`evaluate_real.py --fresh` refuses to run unless this amendment is in the committed `config/protocol.md` (guard `evaluate.guard_fresh`, lock file
`data/fresh/.fresh_used`); a second run is refused, as for the holdout; `replay.py` refuses `data/fresh/`.

**The stations.** Twelve Indian airport stations that were not used for training, tuning, DEV, the holdout, the demo or the post-mortem:
Lucknow, Patna, Indore, Ranchi, Coimbatore, Mangalore, Tiruchirappalli, Amritsar (hourly METAR) and Pune, Goa, Raipur, Jodhpur (3-hourly SYNOP),
listed in `data_tools/stations_fresh.yaml`. The list was fixed from a coverage scout of the year 2022 only (how many reports carry temperature, dew
point and pressure) and their identity in the raw files. No AtmosGuard verdict was computed on any of them before this amendment. Coverage varies
(Indore has 42-69 % of the expected hours in the training years); gaps stay gaps.

**The code.** The two remedies exist behind flags that are off in `full`, so `full` is the pipeline of the holdout, unchanged
(`git diff 9cd24f1 HEAD -- atmos config/settings.yaml` shows the new `explain.py`, an optional retention method, an `api:` block, and these flags with their
tests). Remedy 1 (`health.frozen.ceiling_aware`): a frozen humidity pinned at 99.5 % or more, or a frozen temperature while humidity was at or above 99.5 %
for the whole window, is a `SUSPECT`-level flag at most; a frozen barometer stays hard. Remedy 2 (`limits.learned_step_cap`): the step cap for a channel is
the larger of the configured cap and 1.1 times the 99.9th percentile of that station's own |change| between consecutive clean readings (gaps up to the
gap limit included). Configurations evaluated: `full`, `remedy_frozen`, `remedy_step`, `remedies` (both), the seven ablations and the five baselines.

**The data and the numbers.** Same layout and rules as the holdout in space: each station is trained on its own 2016-2019 record (extreme-weather
windows and NOAA-flagged values removed) and judged on 2020-2024; the extreme-weather windows come from the same rules (`data/fresh/events.json`); the
same five numbers are reported, detection under the paired criterion of Amendment 1 (the registered criterion is printed beside it).

**Decision rule, registered now.** On the FRESH stations pooled, a remedy (or both) is adopted as the recommended configuration only if
(a) the number of real extreme-weather windows containing a `FAULT` is not higher than with `full` and the share of `FAULT` samples in those windows does
not rise; (b) paired detection is not lower than with `full` by more than 2 percentage points for any injected-fault type; and (c) false alarms on clean data
do not rise by more than 0.2 percentage points. "Adopted" means the flag is switched on in `config/settings.yaml`, the six committed station models are
retrained, and the remedy is described as validated on unseen stations. Otherwise `full` stays the shipped configuration and the remedy is reported as tested and
rejected. Each remedy is judged on its own by the same rules, so the report can say which one earned adoption.

**What is reported whatever happens.** Every table for every station, for `full` and for the remedies, including any station where a remedy is worse.

**What this is not.** It is not a repeat of the registered holdout. `full` on the FRESH stations is one more out-of-sample number for the frozen pipeline.
The remedies are deliberately not run on DEV or on the earlier holdout: the post-mortem read those windows to design them, so those numbers would be
contaminated and are not evidence. These are airport records again, and injected faults again.

### 2.8 Amendment 2: outcome (from `config/protocol.md`)

`results/fresh_run1.*` was produced by the single run behind the guard (lock `data/fresh/.fresh_used`, protocol commit `aec7b6f`). The decision rule
registered above was applied by `make_summary.py` (`remedy_rows`) to the pooled numbers of the twelve stations, and every number is printed in
`results/REPORT.md` under "The two remedies from the post-mortem":

| | (a) windows with a FAULT (full / this, of 139) | (a) FAULT share of extreme-weather samples | (b) worst change in paired detection | (c) change in clean false alarms | adopt |
|---|---|---|---|---|---|
| remedy 1, ceiling-aware frozen rule | 3 / 2 | 0.09 % / 0.03 % | none | 0.00 pp | **yes** |
| remedy 2, learned step cap | 3 / 2 | 0.09 % / 0.08 % | -4.2 pp (clock 3 h out) | -0.18 pp | **no** (rule b) |
| both | 3 / 1 | 0.09 % / 0.01 % | -4.2 pp (clock 3 h out) | -0.18 pp | **no** (rule b) |

**Decision.** By the registered rule, remedy 1 is adopted: `health.frozen.ceiling_aware` is `true` in `config/settings.yaml`. Remedy 2 is rejected and
`limits.learned_step_cap` stays `false`. The six committed station models need no retraining (remedy 1 fits nothing). The evaluation's `full`
configuration, the ablations and the baselines keep both flags forced off (`evaluate_real.build_configs`), so `dev_run4`, `holdout_run1/2` and `fresh_run1`
reproduce with the shipped default; the remedy rows are the only ones with a flag on. On DEV, `results/dev_check_remedies.*` shows the shipped default
changes nothing there: identical counts for clean data, extreme weather and every injected-fault type.

**What the three FAULT windows of the frozen pipeline were** (`python window_forensics.py --phase FRESH --station <STN>`; read only after the results were fixed):
Ranchi, a low-pressure window in May 2021: humidity pinned at 100 % for more than 35 hours (`frozen:humidity_pct`, hard): the same cause as Visakhapatnam,
and the one remedy 1 removes. Coimbatore, a sharp-change window in February 2021: humidity up 47.3 % in 120 minutes against a 40 % cap (`step:humidity_pct`),
one sample. Jodhpur, a sharp-change window in December 2020: temperature up 16.2 C across a 6-hour reporting gap and 13 C across a 9-hour one, against a 10 C
cap (`step:temperature_c`): the same cause as Bhuj. Remedy 2 would remove the last two and costs 4.2 points of wrong-clock detection, because the same fixed
step cap is what flags the jump when a clock goes wrong; the rule registered first says that is too much.

**What the frozen pipeline did on the twelve stations, for the record:** clean false alarms 2.5 % (FAULT 0.1 %); extreme weather FAULT on 0.1 % of samples
(3 of 139 windows), WEATHER 10.3 %; paired detection frozen 99 %, spike 91 %, level shift 80 %, noise burst 57 %, dropout 98 %, clock 85 %. That is lower than
on DEV for level shift, noise bursts and clocks, in line with the first holdout, and two simpler systems are better at some fault types on these stations: a
Mahalanobis-only detector on spikes and level shifts, and the textbook rules on wrong clocks (94 % against 85 %) and noise bursts (63 % against 57 %), at 8.4 % false
alarms and a FAULT in 134 of 139 real extreme-weather windows.

### 2.9 Amendment 3: a third set of twelve stations, including real automatic weather stations (from `config/protocol.md`)

The limitations list in the README named what remained after Amendment 2: two step-rule windows that still get a `FAULT` on real extreme weather, weaker detection of
level shifts on unseen stations than on DEV, records that are airport METAR and not automatic weather stations, and no evidence at fine reporting resolution. This amendment
sets up one more evaluation, on a third set of stations nobody has looked at, of two further remedies designed after reading DEV and the explanations of the earlier
`FAULT` windows. `evaluate_real.py --fresh2` refuses to run unless this amendment is in the committed `config/protocol.md` (guard `evaluate.guard_fresh2`, lock file
`data/fresh2/.fresh2_used`); a second run is refused; `replay.py` and `/datasets` refuse `data/fresh2/`.

**The stations.** Twelve stations not used for training, tuning, DEV, the holdout, FRESH, the demo or any post-mortem, listed in `data_tools/stations_fresh2.yaml`:
five Indian airport stations (Hyderabad, Bengaluru, Calicut, Madurai, Vijayawada; hourly METAR, whole degrees) and seven Australian Bureau of Meteorology automatic
weather stations reporting SYNOP hourly at **0.1 C and 0.1 hPa** (Cape Wessel AWS on the monsoon coast, Lady Elliot Island and Willis Island in the Coral Sea on the
cyclone track, Giles in the central desert, Cape Otway on the Bass Strait storm track, Thredbo AWS in the Alps, Mount Crawford AWS in the South Australian ranges). Rule
fixed before any verdict was computed: at least 60 % of the expected hourly reports carry temperature, dew point and pressure in both the training years (2016-2019)
and the test years (2020-2024); then a spread of climates. Candidates that failed it (Agartala, Bhopal, Varanasi, Milingimbi, Cape Moreton, Mount Hotham, Hindmarsh
Island and others) were not used. Coverage was the only thing looked at (and the reporting resolution of the temperature column, to describe the set). The station
files are committed with this amendment, so the set is frozen before the run.

**The remedies**, both behind flags that are off by default and forced off in `registered`:
- **Remedy 3, expected-change-aware step rule** (`health.step.expected_aware`). The step check judges only the part of a change between two consecutive readings that the
  station's own smoothed daily cycle (the L2 normality table) does not explain, and only when that makes the change smaller, so it can relax a flag and never add one. Reason:
  an arid station warms 15 C between two reports six hours apart on a clear day, and a fixed cap calls it a jump (Bhuj, Jodhpur); a learned cap (remedy 2) fixed that but
  cost clock-shift detection, because it also relaxed the jump that a wrong clock produces.
- **Remedy 4, sustained one-channel offset** (`health.offset.*`, a soft flag, so at most `SUSPECT`). Over the last 12 hours (at least 4 readings, no gaps) the median
  departure of one channel from its own month-hour normal is at least 2.5 standard deviations while both other channels' median departures are below 1.0. A weather system that
  moves the level of one channel usually moves another, which is why the others must stay near normal. The parameters were chosen on DEV (`quick` runs, six stations, one
  fault round; grid of five settings) for a false-alarm cost below 0.5 points; DEV cannot show a gain (level-shift detection is already 98 % there), which is the reason for
  testing on data nobody has looked at. A fifth remedy considered (a short-window noise tier) was dropped before this amendment: at hourly cadence it is the same window as the
  existing check, so it changes nothing on DEV and could not be tested on this set, which is all hourly.

**Configurations** (`evaluate_real.build_configs`, phase `FRESH2`): `full`, the pipeline as shipped before this amendment (remedy 1 on, everything else off); `registered`,
every remedy off, for continuity with the earlier phases; `r3_expected_step`, `r4_offset`, `r34_both` (the shipped pipeline with those flags on); and the five baselines.
The ablations are not repeated on this set (they were run on three others).

**The data and the numbers.** As for the holdout in space and for FRESH: each station is trained on its own 2016-2019 record (extreme-weather windows and NOAA-flagged
values removed) and judged on 2020-2024; extreme-weather windows come from the same objective rules (`data/fresh2/events.json`); detection under the paired criterion of
Amendment 1 with the registered criterion beside it. Reported for the twelve stations pooled, and separately for the five Indian airports and the seven Australian AWS.

**Decision rule, registered now.** Each remedy is judged alone against `full` on the twelve stations pooled:
- *Remedy 3* is adopted only if (a) the number of real extreme-weather windows containing a `FAULT` is **lower** than with `full`, and the share of `FAULT` samples in those
  windows is not higher; (b) paired detection is not lower than with `full` by more than 2 percentage points for any injected-fault type; (c) false alarms on clean data do
  not rise by more than 0.2 points.
- *Remedy 4* is adopted only if (a) windows with a `FAULT` and their `FAULT` share are not higher than with `full`; (b) paired detection is not lower by more than 2 points
  for any type; (c) false alarms on clean data do not rise by more than 0.5 points; (d) paired level-shift detection is **higher by at least 5 points**; (e) the share of
  `SUSPECT` samples inside real extreme-weather windows does not rise by more than 2 points (it must not just flag storms).
- `r34_both` is reported and is adopted only if both are.
"Adopted" means the flag is switched on in `config/settings.yaml` and the result is described as validated on unseen stations. Otherwise the remedy is reported as tested
and rejected and the default stays. Nothing else is changed after the run.

**What is reported whatever happens.** Every table for every station and configuration, including any station where a remedy is worse, and the Indian-only and AWS-only
subtables, which answer separately whether the pipeline holds on fine-resolution automatic-station records.

**What this is not.** It is a set of real records with injected faults again, not labelled real faults. The Australian records are SYNOP reports of automatic weather
stations, not IMD data (which no reachable host serves), at hourly cadence: a 1 to 15 minute cadence at 0.1 resolution is still untested. It is not a repeat of the earlier
holdouts, and `full` on these stations is one more out-of-sample number for the shipped pipeline.

### 2.10 Amendment 3: outcome (from `config/protocol.md`)

`results/fresh2_run1.*` was produced by the single run behind the guard (lock `data/fresh2/.fresh2_used`, protocol commit `1a501f1`, 12 stations, 41 minutes on 4 workers). The
decision rules registered above were applied by `make_summary.py` (`amendment3_rows`) to the pooled numbers, and every number is in `results/REPORT.md`:

| | windows with a FAULT (full / this, of 134) | FAULT share (full / this) | worst change in paired detection | level-shift change | change in clean false alarms | SUSPECT share in real weather | adopt |
|---|---|---|---|---|---|---|---|
| remedy 3, expected-change-aware step rule | 4 / 1 | 0.03 % / 0.01 % | none | +0.0 pp | -0.02 pp | -0.10 pp | **yes** |
| remedy 4, sustained one-channel offset | 4 / 3 | 0.03 % / 0.02 % | -0.2 pp (spike) | +1.0 pp | +0.48 pp | +1.35 pp | **no** (rule d: +1.0 pp against the +5 required) |
| both | 4 / 1 | 0.03 % / 0.01 % | -0.2 pp (spike) | +1.0 pp | +0.46 pp | +1.25 pp | **no** (needs both) |

**Decision.** Remedy 3 is adopted: `health.step.expected_aware` is `true` in `config/settings.yaml`. Remedy 4 is rejected and `health.offset.enabled` stays `false`. The six committed
station models need no retraining (remedy 3 fits nothing). The evaluation's `full`, `registered`, ablations and baselines for DEV, both holdouts and FRESH keep every remedy forced
off (`evaluate_real.pin_registered`), so `dev_run4`, `holdout_run1/2` and `fresh_run1` reproduce with the shipped default; FRESH2's `full` is the pipeline as shipped before this amendment.

**What the four FAULT windows of the shipped pipeline were** (`python window_forensics.py --phase FRESH2 --station GLS`, with remedy 3 off; read only after the results were fixed): Giles
(central desert), a low-pressure window in August 2020: humidity -44.3 % in 60 minutes against a 40 % cap; a sharp-change window in September 2022: temperature +10.2 C in 120 minutes
against a 10 C cap. Thredbo (Alps), a low-pressure window in October 2023: humidity -48.9 % in 120 minutes; a sharp-change window in March 2024: humidity -42.5 % in 180 minutes. All four are a
fixed step cap meeting a real, fast, one-channel change that the station's own daily cycle partly explains (a dry air mass arriving, an afternoon warming). Remedy 3 removes three; the fourth,
Thredbo in October 2023 (humidity -48.9 % in 120 minutes), remains: the daily cycle explains too little of that drop.

**What FRESH2 also showed, which the registered rules did not cover.** It is a result and stays in the record:
- **False alarms on clean data are 9.3 % pooled (3.2 % on the five Indian airports, 13.6 % on the seven Australian AWS).** They are concentrated: Mount Crawford 32.7 %, Cape Wessel 25.5 %,
  Lady Elliot Island 21.1 %, Willis Island 8.3 %, and 0.9-2.1 % at the other three AWS (Giles, Cape Otway, Thredbo). The four bad stations share one cause: in 2016-2019 they reported 16 hours a
  day with alternating 1 h and 2 h gaps, and hourly all day from 2020, so **no noise limit could be learned** (`noise_std` is unset for every channel; no earlier station lacked one), the fixed
  floor of 0.5 C / 0.5 hPa / 3 % was used, and it alarms on 0.1-resolution hourly data. It is a mixed-cadence training record, not a defect specific to Australia; `docs/USE_YOUR_DATA.md` item 2
  had warned about mixed cadence. Nothing was changed in response, to the pipeline or its limits. Two things were added that change no verdict: an informational `limits` notice on every reading
  whose station has an unlearned noise limit or a cadence that differs from the one the limits were learned at (`health.check_limits_fit`), and a post-hoc diagnostic (`refit_diagnostic.py`,
  `results/fresh2_refit_diagnostic.*`, labelled as not sealed evidence) of what refitting at the current cadence does on the same stations: fitted on the hourly years 2020-2021 only and judged 2022-2024,
  every noise limit is learned and clean false alarms on the seven Australian AWS are **2.6 %** (1.3-3.6 % per station, Mount Crawford 2.0 %, Cape Wessel 3.6 %, Lady Elliot 2.6 %, Willis 2.5 %) instead of 13.6 %, with
  detection of injected faults frozen 100 %, spike 96 %, level shift 91 %, noise burst 82 %, dropout 98 %, clock 83 %. The judged years differ, so this diagnoses the cause; it is not a like-for-like test. `refit.py` is the
  one-command tool.
- Detection of injected faults on these stations (`full`): frozen 100 %, spike 89 %, level shift 91 %, noise burst 83 %, dropout 93 %, clock 90 %. The Indian and Australian subsets are in `results/REPORT.md`.
- Real extreme weather: FAULT on 0.0 % of 14,732 samples (4 of 134 windows, the four above); WEATHER 4.1 %, SUSPECT 14.1 % (SUSPECT is higher on the AWS, 17.6 %, in step with their higher false-alarm rate).

### 2.11 Amendment 4: a fourth set, including sub-hourly records (from `config/protocol.md`)

Two limits were left after Amendment 3: no record tested was sub-hourly, and four Australian stations of the third set were flooded with false alarms (33, 26, 21, 8 % of clean samples) because their
2016-2019 records were irregular, so no noise limit could be learned. A refit on the hourly years fixed it, but that check used the stations that revealed the problem. This amendment tests, once, on twelve
stations nobody has looked at, a remedy for the second and reports the first. `evaluate_real.py --fresh3` refuses to run unless this amendment is in the committed `config/protocol.md` (guard
`evaluate.guard_fresh3`, lock `data/fresh3/.fresh3_used`); a second run is refused; `replay.py` and `/datasets` refuse `data/fresh3/`.

**The stations** (`data_tools/stations_fresh3.yaml`, files committed with this amendment): seven US automated weather stations (AWOS/ASOS) that report **every 20 minutes** at 0.1 C (Fitch H Beach MI, Pratt KS, Madison
County AL, La Porte, Glasgow MT, George R Carr FL, Hutchinson KS; routine METAR at :15, :35 and :55, pressure = altimeter setting) and five Australian Bureau of Meteorology automatic stations with the irregular-then-hourly
pattern (Weipa, Tennant Creek, Alice Springs, Learmonth, Broome). Rule fixed before any verdict was computed: at least 60 % of the expected reports carry temperature, dew point and pressure in both the training
years (2016-2019) and the test years (2020-2024). The US stations came from a random sample of 90 stations of the US, Canada, Japan, the UK, Ireland, France, Spain and Italy (all with data in 2016 and 2024) scanned for a median cadence of 30 minutes or
finer; of those with tenth-degree temperatures and routine METAR reports every 20 minutes, the seven with the most complete 2022 records were taken; whole-degree stations and the ones that only file irregular SPECI reports were left out. Coverage, cadence and
resolution were the only things looked at. A second copy of each report one minute after the first (present in some years) is dropped: of any reports less than five minutes apart, the first is kept (`data_tools.isd`,
`any_minute`, tested). This is the first sub-hourly record in the project. It is 20 minutes, not the 1-15 minutes of a typical AWS.

**The remedy (`r6_warmup`).** For a station whose training years left any channel's noise limit unlearned, the unlearned limits (only those; learned ones are kept) are filled from the first stretch of the judged period
in which the station reports regularly: 60 days in which at least 90 % of the days carry at least 90 % of the reports expected at the station's current cadence (median gap over the last year of the period). That stretch is chosen
from timestamps only, never from values or verdicts; extreme-weather windows are cut out of it; it is treated as clean (a fault inside it is learned as normal, as in `atmos/autofit.py`). **Every configuration at such a station is
judged only after the stretch ends** (so `full` and the remedy are compared on the same samples); at all other stations nothing changes and `r6_warmup` equals `full`. (`limits.complete_limits`, `evaluate_real.warm_stretch`, tested.)

**Configurations** (phase `FRESH3`): `full`, the pipeline as shipped (remedies 1 and 3 on), `r6_warmup`, and the five baselines. No ablations.

**Decision rule, registered now.** The remedy is adopted only if, on the twelve stations pooled unless stated: (a) over the stations where the warm-up applied, clean false alarms fall by at least 3 percentage points; (b) no
injected-fault type's paired detection is lower than with `full` by more than 2 points; (c) real extreme-weather windows with a `FAULT` and their `FAULT` share are not higher; (d) the `SUSPECT` share in real extreme weather is not higher by
more than 2 points. "Adopted" means `refit.py --complete` (fill only the unlearned limits from a stretch you name) is the documented fix that the `limits` notice points to and the shipped notice says the warm-up is validated;
the pipeline does not change limits on its own. Otherwise the remedy is reported as tested and rejected. If the warm-up applies to no station, the remedy is reported as untested.

**Reported whatever happens.** Every table for `full` on the seven 20-minute US stations and the five Australian ones, pooled and by group (the five numbers), which is the sub-hourly result; the stations where the warm-up applied and
the stretch chosen for each; every station where anything is worse.

**What this is not.** Still injected faults, still not IMD, 20-minute and not 1-15-minute cadence. The US stations are airport automated stations, not a meteorological service's AWS network.

### 2.12 Amendment 4: outcome (from `config/protocol.md`)

`results/fresh3_run1.*` was produced by the single run behind the guard (lock `data/fresh3/.fresh3_used`, protocol commit `cbacfe6`, 12 stations, about 52 minutes on 4 workers).

**The decision rule, applied by `make_summary.py` (`amendment4_rows`):**

| | (a) clean false alarms at the five stations where the warm-up applied (full / this) | (b) worst change in paired detection | (c) windows with a FAULT (full / this, of 160) | (d) SUSPECT share in real weather | adopt |
|---|---|---|---|---|---|
| remedy 6, unlearned limits filled from the first regular stretch | 45.4 % / 1.8 % (pass, needs 3 points) | **-6.0 pp (noise burst)** (fail, allows 2) | 5 / 5 (pass) | -7.90 pp (pass) | **no** (rule b) |

**Decision.** By the rule registered first the remedy is **rejected**: it removes almost all of the false alarms it was designed for, and costs 6 points of noise-burst detection pooled over the twelve stations (at the five stations where
it applied, 72/72 to 67/72, 99/99 to 94/99, 79/81 to 48/81, 72/72 to 65/72, 78/81 to 57/81). The reading of that trade is ours and it is not part of the rule: with the fixed 0.5 C floor the pipeline alarmed on 29-61 % of *clean* samples at those stations,
so its "detection" of noise bursts there was mostly the floor firing on everything; with a learned limit the alarm means something, and it is less sensitive. The rule was written to stop a remedy that lost detection and it did its job; we do not
overturn it. Consequences: `refit.py --complete` stays in the repository as an operator's tool (it fills only unlearned limits from a stretch you name) with this trade-off stated, the `limits` notice still tells the operator when limits do not fit,
and the pipeline does not change limits by itself. The shipped default is unchanged.

**What FRESH3 shows about the sub-hourly, fine-resolution case (reported whatever the decision):** on the seven US automated stations reporting **every 20 minutes** at 0.1 C (pipeline as shipped, no station-specific tuning):
clean false alarms 2.7 % of 858,141 samples (FAULT 0.0 %); real extreme weather FAULT on 0.1 % of 38,294 samples (3 of 103 windows), WEATHER 3.4 %, SUSPECT 5.3 %; injected faults raised the alarm: frozen 100 %, spike 97 %, level shift 99 %,
noise burst 100 %, dropout 99 %, clock 94 %; NOAA-flagged values escalated 39.6 %. All seven stations had every limit learned. This is the first sub-hourly evidence in the project; it is 20 minutes, not 1-15.

**What the five Australian stations with irregular 2016-2019 records show:** with the pipeline as shipped, clean false alarms are 45.4 % (29.3 % Weipa, 42.1 % Tennant Creek, 60.7 % Alice Springs, 49.3 % Learmonth, 42.7 % Broome): no
noise limit could be learned at any of them (all five had the alternating 1 h / 2 h pattern, and Weipa, Learmonth and Broome stayed irregular through 2020). With the warm-up they are 1.2-2.8 %. This confirms, on stations nobody had looked at,
that the FRESH2 false-alarm finding is a property of the irregular training record and not of the four stations that revealed it. It is not fixed by default: the remedy failed its rule.

**The five real-weather windows that got a FAULT** (`python window_forensics.py --phase FRESH3 --station <STN>`, read only after the results were fixed):
- Fitch H Beach (Michigan), a low-pressure window in January 2024, and La Porte, low-pressure (Jan 2024) and cold (Jan 2024) windows: **temperature stuck at exactly 0 C (or -1 C) for 520-560 minutes** while humidity sat at 93 %, in the January 2024 US cold outbreak
  (freezing precipitation holds the air at the freezing point). It is the same kind of cause as the saturated humidity at Visakhapatnam and Ranchi, a physical plateau that the frozen rule reads as a stuck sensor; a freezing-point analogue of remedy 1 is the obvious candidate and
  would need another set of unseen stations to be judged honestly. It is not applied.
- Alice Springs, sharp-change and low-pressure windows around 3-4 August 2020: at night the temperature goes from 5.9 C to 18.4 C in one hour (+12.5 C, then +15 C over two hours by the next reading) with pressure smooth and humidity falling from 31 % to 23 %.
  Either a real warm downslope wind or a sensor step; the data cannot say which. The pipeline called it a single-channel jump against the 10 C step cap. It is the same cause, a fixed step cap meeting a fast real (or ambiguous) change, that Amendment 3's
  remedy addresses; here the daily cycle explains none of it, because it happened in the middle of the night.

### 2.13 Amendment 5: a fifth set and a freezing-point remedy (from `config/protocol.md`)

FRESH3 showed a failure of a new kind: at Fitch H Beach and La Porte, in the January 2024 US cold outbreak, temperature sat at exactly 0 C (or -1 C) for 520-560 minutes in humid air (freezing rain and wet snow hold the air at
the freezing point), and the frozen rule called it a stuck sensor (`FAULT`) in three real extreme-weather windows. This amendment tests a remedy on twelve stations nobody has looked at. `evaluate_real.py --fresh4` refuses to run
unless this amendment is in the committed protocol (guard `evaluate.guard_fresh4`, lock `data/fresh4/.fresh4_used`); `replay.py` and `/datasets` refuse `data/fresh4/`.

**The stations** (`data_tools/stations_fresh4.yaml`, files committed with this amendment): twelve northern US airport stations (Goshen IN, Scottsbluff NE, Ames IA, Montauk NY, Wheeling WV, Jamestown ND, Elko NV, Norwood MA, Burlington VT,
Brainerd MN, Bloomington-Normal IL, Muncie IN), hourly routine METAR (reported at :53 or similar; `any_minute`, duplicates dropped as before), whole degrees. Rule fixed before any verdict: a seeded random sample (seed 11) of 40 US stations
north of 40 N with K-prefixed ICAO codes and data in 2016 and 2024, not used in any earlier set, kept if at least 60 % of expected hourly reports carry temperature, dew point and pressure in both the training and the test years and the median gap is
50-70 minutes; stations with a duplicate report stream (coverage above 120 %) were dropped; the first twelve in list order were taken.

**The remedy (`health.frozen.freezing_aware`, remedy 7).** A frozen temperature or humidity is a `SOFT` flag at most when, over the whole window, the temperature stayed within 1.0 C of 0 C while humidity was at least 85 %. A frozen barometer is never
softened. Same pattern as remedy 1 (saturation). Off by default and forced off in every earlier configuration.

**Configurations** (phase `FRESH4`): `full` (the pipeline as shipped), `r7_freezing`, and the five baselines.

**Decision rule, registered now.** Adopted only if, pooled over the twelve stations: (a) real extreme-weather windows with a `FAULT` are fewer than with `full` and the `FAULT` share of those samples is not higher; (b) no injected-fault type's paired
detection is lower than with `full` by more than 2 points; (c) clean false alarms rise by at most 0.2 points; (d) the `SUSPECT` share in real extreme weather rises by at most 2 points. A stuck thermometer at 0 C in humid air would become a `SUSPECT`
instead of a `FAULT` until something else flags it, and we say so. Otherwise it is reported as tested and rejected. Reported whatever happens: every table, per station.

**What this is not.** Injected faults, airport METAR, whole degrees, hourly. It tests one mechanism.

### 2.14 Amendment 5: outcome (from `config/protocol.md`)

`results/fresh4_run1.*` was produced by the run behind the guard (lock `data/fresh4/.fresh4_used`, protocol commit `7fcbf32`, 12 stations, about 25 minutes on 4 workers). The first process died before writing any output and before anything was looked at;
it was started again with `--force-rerun-holdout`, which the guard allows because the evaluation is deterministic (see the determinism checks in `results/RUNS.md`). Nothing was seen between the two.

**The decision rule, applied by `make_summary.py` (`amendment5_rows`):**

| | (a) windows with a FAULT (full / this, of 180) | (a) FAULT share | (b) worst change in paired detection | (c) change in clean false alarms | (d) SUSPECT share | adopt |
|---|---|---|---|---|---|---|
| remedy 7, freezing-point plateau is a soft flag | 0 / 0 | 0.00 % / 0.00 % | none | +0.00 pp | +0.00 pp | **no** (rule a) |

**Decision.** By the rule registered first the remedy is **not adopted**, and the reason is not that it did harm: it changed nothing. On these twelve stations (Indiana to North Dakota to Nevada, winters 2020-2024) the pipeline as shipped
raised **no `FAULT` in any of the 180 real extreme-weather windows** (cold windows 0 of 26), so there was no stuck-thermometer-at-zero case for the remedy to rescue, and rule (a) asks for strictly fewer. Every number in every table is identical
between `full` and `r7_freezing`. We read this as: the FRESH3 failure (three windows at two stations of 103, both on the Great Lakes in one January 2024 outbreak, with 20-minute reports that hold the same whole reading for hours) is real but rare, and this
set did not reproduce it; it neither confirms nor refutes the remedy. The flag stays in the code, off, with its tests; the limit stays listed as open: *a stretch of air held at the freezing point by freezing rain can still be read as a stuck
thermometer*. We did not widen the test until it passed.

**What FRESH4 shows about the shipped pipeline (reported whatever the decision):** clean false alarms 2.0 % of 498,994 samples (FAULT 0.0 %; per station 1.3 % to 2.4 %); real extreme weather `FAULT` 0.0 %, `SUSPECT` 6.2 %, `WEATHER` 4.0 % of the samples in the 180 windows
(cold 11.4 % `SUSPECT`, the highest kind); injected faults raised the alarm (paired): frozen 100 %, spike 96.7 %, level shift 90.4 %, noise burst 74.8 %, dropout 99.2 %, clock 79.7 %; NOAA-flagged values escalated 17.4 %, alarmed on 8.1 %
(on 1.1 % of the 87 NOAA-erroneous ones: a small count, and NOAA flags are not truth); the textbook range + step + persistence baseline raised a `FAULT` in 166 of 180 real windows against 0 for the pipeline. This is the **fifth** unseen set. Its clean false-alarm rate (2.0 %) sits in the band of the earlier sets on hourly and 20-minute stations (1.9 % DEV, 2.5 % holdout in space, 2.5 % FRESH, 2.9 % holdout in time; FRESH2 was 9.3 % because of its irregular training records); noise-burst (74.8 %) and clock-shift (79.7 %) detection on
hourly whole-degree stations are the weakest rows again and are stated as such. Slow-drift detection is also weak on these winter stations (temperature 2.2 % to 6.7 % at 1x to 8x the service limit, humidity 4 % to 53 %); that test is not part of any decision rule.
On clean data with no drift injected, 0.4 % of 19,527 station-days claimed significant drift.

## 3. Method

AtmosGuard judges one reading at a time. State is per station; no station ever reads another's live data. Every threshold below
is a value in `config/settings.yaml` (nothing is hard-coded), and every layer has a switch, so the ablation needs no code edits.
The layers are ordered by cost; a fusion step turns their outputs into one of four verdicts.

### 3.1 L0 physics (closed form; also runs on the ESP32)
- **Range:** temperature -90..60 degC, pressure 300..1100 hPa, humidity 0..100 %. Outside is a hard flag.
- **Dew point** (Magnus, a = 17.62, b = 243.12 degC): g = ln(RH/100) + a T/(b+T), Td = b g/(a-g). Td above T + 0.5 degC is a hard flag.
- **Wet-bulb** (Stull 2011). At or above 35 degC it is a **soft** flag only. It is not an "impossible" rule: 35 degC wet-bulb has been observed.

### 3.2 L1 health (per channel; windows are in minutes and scale with the station's cadence)
- **Frozen.** No change over a window. The configured window (T 60, P 180, RH 120 min, at least 3 samples) is stretched to the
  longest run of identical values this station's clean history produced (section 3.3). Two tiers when the window was learned: a
  run past the limit is a **soft** flag; a run `2x` the limit is a **hard** flag.
- **Step / spike.** Allowed change = min(rate x minutes, cap): rates 1 degC, 0.5 hPa, 5 % per minute; caps 10, 10, 40. A spike is a
  one-sample excursion that returns.
- **Noise.** Jitter from **second differences** (which cancel a smooth trend): sqrt(mean(d2^2) / 6), over a window of at least 7 samples.
  Limit: configured (0.5, 0.5, 3.0) or learned, whichever is larger.
- **Gap.** More than 3 cadences since the last reading. Reported as a **notice** on the next reading; it does not change the verdict
  (the values after a gap are fine).
- **CUSUM** on (reading - expected) in normality sigmas, k = 1.5, h = 40, one sample capped at 4 sigma, steps scaled by cadence/15 min.
  A soft flag: real weather anomalies last hours and look like drift.

### 3.3 Station-learned limits (`atmos/limits.py`)
A station that reports whole degrees repeats the same value for hours in ordinary weather. On real Bhubaneswar METAR the fixed
limits alarmed on two thirds of clean samples. For each channel the station's own clean history gives:
the **reporting resolution** (1.0, 0.5, 0.1 or none), the 99.9th percentile of identical-value **run durations**, the 99.9th percentile
of the **noise estimate** (times 1.1), and the **usual step** (75th percentile of |change| between consecutive readings).
The configured values are a floor: learning can only relax a check. The frozen-run idea is HadISD's (streak thresholds from the
distribution of run lengths); the two-tier grading, the resolution detection and the real-time use are ours.

### 3.4 L2 normality (`atmos/normality.py`)
A table of mean, standard deviation and count per station x month x hour (cells with fewer than 10 samples are left out). The
z-score of a reading is (value - mean) / max(std, floor); |z| > 4 is a soft flag. A **smooth expected value** (bilinear in hour and
in month, each month's value taken at mid-month) is used wherever residuals are read over weeks, because the plain table is a step
function and turns the seasonal cycle into a fake trend.

### 3.5 L3 multivariate
- **Isolation Forest** (100 trees, one per station, fixed seed) over the three values, their per-minute changes and the hour as sin/cos;
  alarm below the 0.5 % quantile of the clean training scores.
- **Mahalanobis distance** of the six-vector (departure from the smooth expected value, per-minute change) for each channel, with the
  station's own covariance; alarm above the 99.5 % quantile of the clean training distances. The squared distance splits **exactly**
  into per-feature contributions, so the flag names the channel and feature that drove it.

### 3.6 Timing
- **T1 clock phase:** the daily cycle of the last day is compared with the station's normal cycle at timestamp shifts of -6..+6 whole
  hours; if a non-zero shift cuts the mean squared z by at least half, the clock may be wrong (soft flag). Recomputed every 3 hours of data time.
- **T2 co-jump:** two or more channels exceeding their step limit in the same sample (common-mode glitch). Meaningful only at fast
  cadence; weak on hourly data, and the README says so.

### 3.7 Fusion (first rule that matches wins)
1. A **hard** flag from range, dew point, frozen (at 2x the learned limit) or dropout -> `FAULT`.
2. **One** channel jumps (step or spike) and the other two are **actually quiet** -> `FAULT`. Quiet means each other channel moved by at
   most half of its step allowance over the last two intervals and, once known, at most 1.5x the station's usual step. (Checking only that no
   flag fired was a real bug: a thunderstorm outflow that drops temperature 8 degC fires nothing and made rule 2 call weather a fault.)
3. Only soft flags, and either (a) two or more channels **move** together over the last hour by more than a minimum (T 1 degC,
   P 1 hPa, RH 5 %) in a known pattern (cooling + moistening; warming + drying; falling pressure + rising humidity; rising pressure +
   drying), or (b) two or more channels **depart from normal together** (|z| >= 2) -> `WEATHER`, escalated as an alert.
4. Any other flag -> `SUSPECT` (kept, marked for review).
5. Otherwise `VALID`.

The reason text is built from the checks that fired. **Confidence** is a heuristic agreement score (0.9 valid, 0.95 rule 1, 0.8 rule 2,
0.7 weather, 0.5 suspect, +0.05 per extra supporting soft flag, capped at 0.99). It is **not** a probability and no metric uses it.

### 3.8 Health monitor and drift (`atmos/healthscore.py`)
- **Score** per channel over 7 days = 100 - 100 x (fraction of FAULT verdicts on it) - 50 x (fraction of SUSPECT) - 40 x (drift ratio);
  the station score is the worst channel. `WEATHER` never counts against a sensor.
- **Drift.** Daily means of (reading - smooth expected value), residuals clipped at 3 normality sigmas, samples judged FAULT on that
  channel left out. Over the last 60 days (at least 21 usable days): Theil-Sen slope; significance = OLS slope / a standard error inflated
  by sqrt((1+rho)/(1-rho)), rho the lag-1 autocorrelation of the fit residuals (0..0.9); significant at |z| >= 4.
  **Isolated-trend rule:** if another channel also trends (|z| >= 2.5) the trend is read as a seasonal or weather transition, not drift.
  **Persistence:** significant with the same sign on each of the last 7 daily evaluations.
  The monitor reports the **smallest slope it could see** (z_crit x standard error) so "no drift found" has a stated meaning.
  Service date = when the offset reaches the limit (T 0.5 degC, P 1 hPa, RH 3 %) at the fitted slope.
- **Ticket** when the score is at or below 60, a channel is faulty in at least half of the last hour, or a service date is within 30 days.

### 3.9 Estimate for a missing or faulty value (`atmos/impute.py`)
estimate = normal(t) + rho x (last trusted value - normal(then)), rho = 0.5^(age / 120 min); band = +/- 1.96 sqrt(std^2 (1-rho^2) + (1+rho^2) sigma^2),
sigma the sensor noise floor. It is stored **beside** the raw value; the raw value is never replaced.

### 3.10 Edge (`firmware/node/atmos_l0.h`)
1 Hz sampling, per-sample range check, one-minute mean of the valid samples (at least 30), dew point vs temperature, and a counter of identical
minute means (30 in a row -> frozen flag), with a queue of 30 unsent minutes while the network is down. The header is plain C++11
with no Arduino dependency, so the same code is compiled and compared with the Python implementation on thousands of inputs
(`tests/test_edge_parity.py`). It has not been run on hardware.

### 3.11 Cold start (`atmos/coldstart.py`)
A new station borrows the frozen table and limits of the nearest other station and blends them cell by cell with its own as its own
data grows (weight = samples in the cell / 30; limits over 365 days). No live neighbour data is read.

## 4. Results

Everything in this section is generated by `make_summary.py` from the JSON that `evaluate_real.py` wrote, and is copied here by `make_report.py`; nothing is typed by hand. **The five numbers are never merged**: the injected-fault score, the false-alarm rate on clean data, what happens to real extreme weather, agreement with NOAA's flags, and drift are different questions. Injected faults are injected; NOAA's flags come from another automated system, not from truth.

### 4.1 DEV: the six stations we were allowed to tune on, 2020-2021

*Tuning happened here. These numbers are the optimistic ones.* Stations: BBI, MAA, CCU, DEL, JAI, TRV.

#### Headline

Five separate numbers. They are never merged.

| question | answer |
|---|---|
| False alarms on clean real data (nothing injected) | 1.9% (1.8-2.0) of 98340 samples got FAULT or SUSPECT; 0.0% (0.0-0.0) got FAULT |
| What happens to real extreme weather (cyclones, heat, cold, sharp fronts; nothing injected) | FAULT on 0.0% (0.0-0.1) of 3503 samples (0 of 30 windows); WEATHER on 10.8%, SUSPECT on 9.0% |
| Injected faults whose alarm the fault raised (each type on its own; injected, not real) | frozen 100%; spike 98%; level shift 97%; noise burst 78%; dropout 99%; clock 3 h out 97% |
| Agreement with NOAA's own quality flags (another automated system, not ground truth) | escalated (FAULT, SUSPECT or WEATHER) on 66.9% of 236 NOAA-flagged values (FAULT or SUSPECT alone: 22.9%); escalated on 4.7% of the 101736 values NOAA left alone |
| Slow drift (health monitor, single station, no reference) | false drift claims on 1.1% of 3859 station-days; an injected ramp reaching 8x the service limit was found in 56% of trials |

#### 1. Detection of injected faults, by type (the fault raised the alarm)

Alarm = FAULT or SUSPECT on a sample that was NOT an alarm on the same series without the fault (paired), from the first faulty sample to the last plus 60 minutes. The faults are injected, not real. Ablation rows switch one layer off; baseline rows are simpler systems on the same data.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 98% | 97% | 78% | 99% | 97% |
| without physics layer | 100% | 97% | 96% | 76% | 99% | 97% |
| without health layer | 37% | 88% | 92% | 60% | 1% | 94% |
| without normality layer | 100% | 99% | 95% | 79% | 100% | 94% |
| without Isolation Forest | 100% | 98% | 97% | 77% | 99% | 97% |
| without Mahalanobis layer | 100% | 91% | 70% | 61% | 99% | 97% |
| without timing layer | 100% | 98% | 97% | 78% | 100% | 70% |
| without station-learned limits | 100% | 46% | 89% | 98% | 60% | 100% |
| baseline: range check only | 0% | 12% | 12% | 16% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 74% | 87% | 67% | 0% | 89% |
| baseline: climatology z-score only | 18% | 37% | 33% | 13% | 0% | 58% |
| baseline: Isolation Forest only | 1% | 12% | 10% | 10% | 0% | 56% |
| baseline: Mahalanobis distance only | 38% | 100% | 100% | 74% | 0% | 55% |
| (faults injected) | 243 | 243 | 243 | 243 | 243 | 220 |
| AtmosGuard: median minutes to the alarm | 480 | 0 | 0 | 420 | 0 | 1140 |

#### 1d. How sure are the detection numbers? (AtmosGuard full, paired criterion, Wilson 95 % interval)

Faults are injected at random places; each row's interval says how much the percentage could move with another draw of the same size. Faults of one type overlap little but are not fully independent, so read the interval as a guide, not a guarantee.

| fault type | injected | raised the alarm (fault-raised) | named FAULT |
|---|---|---|---|
| frozen | 243 | 100.0% (98.4-100.0) | 95.1% (91.6-97.2) |
| spike | 243 | 97.5% (94.7-98.9) | 12.3% (8.8-17.1) |
| level shift | 243 | 97.1% (94.2-98.6) | 11.5% (8.1-16.1) |
| noise burst | 243 | 77.8% (72.1-82.5) | 15.6% (11.6-20.7) |
| dropout | 243 | 99.2% (97.0-99.8) | 99.2% (97.0-99.8) |
| clock 3 h out | 220 | 96.8% (93.6-98.5) | 0.5% (0.1-2.5) |

#### 1c. How AtmosGuard names what it detects, and the WEATHER-masking check

A FAULT verdict names the problem; SUSPECT asks for review. The last row is the risk of the coherent-level WEATHER route: a fault that was not alarmed but made samples look like real weather.

| AtmosGuard, injected faults | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| raised an alarm (FAULT or SUSPECT) | 100% | 98% | 97% | 78% | 99% | 97% |
| of which named FAULT | 95% | 12% | 12% | 16% | 99% | 0% |
| missed, but made some samples look like WEATHER | 0% | 1% | 3% | 5% | 0% | 2% |

#### 2. False alarms on clean real data

No fault injected. Extreme-weather windows and NOAA-flagged values removed.

| configuration | any alarm | FAULT only | WEATHER verdicts | samples |
|---|---|---|---|---|
| AtmosGuard (full) | 1.9% | 0.0% | 2.2% | 98340 |
| without physics layer | 1.9% | 0.0% | 2.2% | 98340 |
| without health layer | 0.6% | 0.0% | 1.3% | 98340 |
| without normality layer | 1.0% | 0.0% | 0.8% | 98340 |
| without Isolation Forest | 1.9% | 0.0% | 1.9% | 98340 |
| without Mahalanobis layer | 1.8% | 0.0% | 1.9% | 98340 |
| without timing layer | 1.7% | 0.0% | 2.1% | 98340 |
| without station-learned limits | 63.1% | 34.2% | 0.5% | 98340 |
| baseline: range check only | 0.0% | 0.0% | - | 98340 |
| baseline: textbook range + step + persistence | 5.4% | 5.4% | - | 98340 |
| baseline: climatology z-score only | 0.8% | 0.0% | - | 98340 |
| baseline: Isolation Forest only | 0.4% | 0.0% | - | 98340 |
| baseline: Mahalanobis distance only | 0.5% | 0.0% | - | 98340 |

#### 3. Real extreme weather (nothing injected)

A FAULT here is a failure: real weather called a broken sensor. WEATHER is the escalated, correct verdict.

| configuration | FAULT | SUSPECT | WEATHER | VALID | windows with a FAULT |
|---|---|---|---|---|---|
| AtmosGuard (full) | 0.0% | 9.0% | 10.8% | 80.3% | 0/30 |
| without physics layer | 0.0% | 9.0% | 10.8% | 80.3% | 0/30 |
| without health layer | 0.0% | 3.9% | 7.1% | 89.1% | 0/30 |
| without normality layer | 0.0% | 3.6% | 3.1% | 93.3% | 0/30 |
| without Isolation Forest | 0.0% | 9.0% | 9.9% | 81.1% | 0/30 |
| without Mahalanobis layer | 0.0% | 8.8% | 10.4% | 80.8% | 0/30 |
| without timing layer | 0.0% | 8.9% | 10.7% | 80.4% | 0/30 |
| without station-learned limits | 28.6% | 34.3% | 4.1% | 33.0% | 30/30 |
| baseline: range check only | 0.0% | 0.0% | - | 100.0% | 0/30 |
| baseline: textbook range + step + persistence | 5.3% | 0.0% | - | 94.7% | 29/30 |
| baseline: climatology z-score only | 0.0% | 8.1% | - | 91.9% | 0/30 |
| baseline: Isolation Forest only | 0.0% | 2.1% | - | 97.9% | 0/30 |
| baseline: Mahalanobis distance only | 0.0% | 1.9% | - | 98.1% | 0/30 |

Full pipeline, by kind of extreme weather:

| kind of extreme weather | samples | FAULT | SUSPECT | WEATHER | windows with a FAULT |
|---|---|---|---|---|---|
| cold | 290 | 0.0% | 4.1% | 2.8% | 0/2 |
| heat | 270 | 0.0% | 1.5% | 10.7% | 0/2 |
| low | 1826 | 0.0% | 13.3% | 15.0% | 0/14 |
| sharp | 1117 | 0.0% | 4.9% | 5.9% | 0/12 |

#### 4. Agreement with NOAA's own quality flags

NOAA's flags come from another automated system. Agreement means consistency with existing practice, not proof of real-world accuracy.

| measure | value |
|---|---|
| NOAA-flagged values (suspect or erroneous) | 236 |
|   of which erroneous | 0 |
| AtmosGuard alarmed (FAULT or SUSPECT) on flagged values | 22.9% |
| AtmosGuard escalated at all (also WEATHER) on flagged values | 66.9% |
| AtmosGuard alarmed on erroneous values | n/a |
| values NOAA did not flag | 101736 |
| AtmosGuard alarmed on those (extra flags) | 2.3% |
| AtmosGuard escalated at all on those | 4.7% |

#### 5. Slow drift, judged by the health monitor

A ramp over 45 days is added to one channel of clean real data. Severity = offset at the end of the ramp in multiples of the service limit (T 0.5 C, P 1 hPa, RH 3 %). One station, no reference: small drifts cannot be told from weather.

| drift at end of ramp | temperature | pressure | humidity |
|---|---|---|---|
| none (false claims) | 15.8% of 19 chunks | 0.0% of 19 chunks | 21.1% of 19 chunks |
| 1x service limit | 5% of 19 (day 67, 3.6x at detection) | 0% of 19 (-, - at detection) | 11% of 19 (day 87, 2.6x at detection) |
| 2x service limit | 5% of 19 (day 62, 4.5x at detection) | 0% of 19 (-, - at detection) | 16% of 19 (day 45, 3.1x at detection) |
| 4x service limit | 16% of 19 (day 46, 4.4x at detection) | 16% of 19 (day 39, 4.0x at detection) | 32% of 19 (day 44, 4.6x at detection) |
| 8x service limit | 58% of 19 (day 41, 7.0x at detection) | 47% of 19 (day 45, 5.5x at detection) | 63% of 19 (day 46, 6.8x at detection) |

#### By station (full pipeline)

Each station judged on its own record.

| station | cadence (min) | clean any alarm | clean FAULT | extreme weather FAULT | windows with a FAULT | extreme weather WEATHER | injected faults detected |
|---|---|---|---|---|---|---|---|
| BBI | 60 | 1.8% | 0.0% | 0.0% | 0/7 | 10.5% | 94% |
| MAA | 60 | 2.5% | 0.0% | 0.0% | 0/6 | 16.1% | 99% |
| CCU | 60 | 1.9% | 0.0% | 0.0% | 0/5 | 13.8% | 92% |
| DEL | 60 | 1.6% | 0.0% | 0.0% | 0/4 | 11.5% | 94% |
| JAI | 60 | 1.9% | 0.0% | 0.0% | 0/6 | 3.4% | 91% |
| TRV | 60 | 1.6% | 0.0% | 0.0% | 0/2 | 8.9% | 99% |

#### 1b. The same, by the criterion registered in the protocol (any alarm in the window)

Background false alarms (about 2 % of samples) also fall inside long fault windows, so this flatters long faults (frozen 48 h, clock shift 4 days) and every system, baselines included. Kept because it was registered before the holdout.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 99% | 97% | 81% | 100% | 97% |
| without physics layer | 100% | 98% | 96% | 79% | 100% | 97% |
| without health layer | 40% | 88% | 92% | 62% | 3% | 94% |
| without normality layer | 100% | 99% | 95% | 81% | 100% | 94% |
| without Isolation Forest | 100% | 99% | 97% | 80% | 100% | 97% |
| without Mahalanobis layer | 100% | 93% | 74% | 65% | 100% | 97% |
| without timing layer | 100% | 99% | 97% | 81% | 100% | 70% |
| without station-learned limits | 100% | 100% | 100% | 100% | 100% | 100% |
| baseline: range check only | 0% | 12% | 12% | 16% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 78% | 92% | 82% | 8% | 90% |
| baseline: climatology z-score only | 24% | 38% | 36% | 17% | 2% | 59% |
| baseline: Isolation Forest only | 4% | 12% | 15% | 19% | 0% | 56% |
| baseline: Mahalanobis distance only | 46% | 100% | 100% | 77% | 0% | 55% |
| (faults injected) | 243 | 243 | 243 | 243 | 243 | 220 |
| AtmosGuard: median minutes to the alarm | 480 | 0 | 0 | 360 | 0 | 1140 |

#### No single simpler system is good at every fault type

Each system's weakest fault type from table 1, beside its false-alarm rate and its record on real extreme weather. A system that is best at one fault type is blind to another; the layers exist for coverage, and the WEATHER verdict exists so that coverage does not cost real storms.

| system | weakest injected-fault type (fault raised the alarm) | false alarms on clean data | real extreme weather, windows with a FAULT |
|---|---|---|---|
| AtmosGuard (full) | noise burst: 78% | 1.9% | 0/30 |
| baseline: range check only | frozen: 0% | 0.0% | 0/30 |
| baseline: textbook range + step + persistence | dropout: 0% | 5.4% | 29/30 |
| baseline: climatology z-score only | dropout: 0% | 0.8% | 0/30 |
| baseline: Isolation Forest only | dropout: 0% | 0.4% | 0/30 |
| baseline: Mahalanobis distance only | dropout: 0% | 0.5% | 0/30 |

### 4.2 HOLDOUT in time: the same six stations, 2022-2024

*Sealed until the single holdout run. Same stations, later years.* Stations: BBI, MAA, CCU, DEL, JAI, TRV.

#### Headline

Five separate numbers. They are never merged.

| question | answer |
|---|---|
| False alarms on clean real data (nothing injected) | 2.5% (2.4-2.6) of 147078 samples got FAULT or SUSPECT; 0.0% (0.0-0.0) got FAULT |
| What happens to real extreme weather (cyclones, heat, cold, sharp fronts; nothing injected) | FAULT on 0.0% (0.0-0.1) of 4374 samples (0 of 38 windows); WEATHER on 11.8%, SUSPECT on 8.2% |
| Injected faults whose alarm the fault raised (each type on its own; injected, not real) | frozen 100%; spike 96%; level shift 98%; noise burst 79%; dropout 100%; clock 3 h out 97% |
| Agreement with NOAA's own quality flags (another automated system, not ground truth) | escalated (FAULT, SUSPECT or WEATHER) on 61.5% of 265 NOAA-flagged values (FAULT or SUSPECT alone: 18.5%); escalated on 5.7% of the 151336 values NOAA left alone |
| Slow drift (health monitor, single station, no reference) | false drift claims on 1.1% of 5797 station-days; an injected ramp reaching 8x the service limit was found in 50% of trials |

#### 1. Detection of injected faults, by type (the fault raised the alarm)

Alarm = FAULT or SUSPECT on a sample that was NOT an alarm on the same series without the fault (paired), from the first faulty sample to the last plus 60 minutes. The faults are injected, not real. Ablation rows switch one layer off; baseline rows are simpler systems on the same data.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 96% | 98% | 79% | 100% | 97% |
| without physics layer | 100% | 95% | 96% | 77% | 100% | 97% |
| without health layer | 44% | 87% | 96% | 62% | 2% | 90% |
| without normality layer | 100% | 98% | 97% | 80% | 100% | 94% |
| without Isolation Forest | 100% | 96% | 98% | 79% | 100% | 97% |
| without Mahalanobis layer | 100% | 92% | 75% | 66% | 100% | 97% |
| without timing layer | 100% | 97% | 98% | 80% | 100% | 71% |
| without station-learned limits | 100% | 51% | 91% | 97% | 61% | 100% |
| baseline: range check only | 0% | 14% | 15% | 13% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 75% | 87% | 68% | 0% | 91% |
| baseline: climatology z-score only | 22% | 43% | 47% | 13% | 0% | 53% |
| baseline: Isolation Forest only | 1% | 10% | 13% | 13% | 0% | 46% |
| baseline: Mahalanobis distance only | 37% | 100% | 100% | 76% | 0% | 47% |
| (faults injected) | 279 | 279 | 279 | 279 | 279 | 260 |
| AtmosGuard: median minutes to the alarm | 480 | 0 | 0 | 420 | 0 | 1050 |

#### 1d. How sure are the detection numbers? (AtmosGuard full, paired criterion, Wilson 95 % interval)

Faults are injected at random places; each row's interval says how much the percentage could move with another draw of the same size. Faults of one type overlap little but are not fully independent, so read the interval as a guide, not a guarantee.

| fault type | injected | raised the alarm (fault-raised) | named FAULT |
|---|---|---|---|
| frozen | 279 | 100.0% (98.6-100.0) | 95.0% (91.8-97.0) |
| spike | 279 | 96.4% (93.5-98.0) | 14.7% (11.0-19.3) |
| level shift | 279 | 98.2% (95.9-99.2) | 14.7% (11.0-19.3) |
| noise burst | 279 | 79.2% (74.1-83.6) | 12.5% (9.2-16.9) |
| dropout | 279 | 99.6% (98.0-99.9) | 99.6% (98.0-99.9) |
| clock 3 h out | 260 | 96.9% (94.0-98.4) | 0.0% (0.0-1.5) |

#### 1c. How AtmosGuard names what it detects, and the WEATHER-masking check

A FAULT verdict names the problem; SUSPECT asks for review. The last row is the risk of the coherent-level WEATHER route: a fault that was not alarmed but made samples look like real weather.

| AtmosGuard, injected faults | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| raised an alarm (FAULT or SUSPECT) | 100% | 96% | 98% | 79% | 100% | 97% |
| of which named FAULT | 95% | 15% | 15% | 13% | 100% | 0% |
| missed, but made some samples look like WEATHER | 0% | 1% | 2% | 6% | 0% | 2% |

#### 2. False alarms on clean real data

No fault injected. Extreme-weather windows and NOAA-flagged values removed.

| configuration | any alarm | FAULT only | WEATHER verdicts | samples |
|---|---|---|---|---|
| AtmosGuard (full) | 2.5% | 0.0% | 2.7% | 147078 |
| without physics layer | 2.5% | 0.0% | 2.7% | 147078 |
| without health layer | 0.7% | 0.0% | 1.5% | 147078 |
| without normality layer | 1.2% | 0.0% | 0.8% | 147078 |
| without Isolation Forest | 2.5% | 0.0% | 2.4% | 147078 |
| without Mahalanobis layer | 2.4% | 0.0% | 2.4% | 147078 |
| without timing layer | 2.2% | 0.0% | 2.6% | 147078 |
| without station-learned limits | 61.2% | 34.1% | 0.8% | 147078 |
| baseline: range check only | 0.0% | 0.0% | - | 147078 |
| baseline: textbook range + step + persistence | 5.2% | 5.2% | - | 147078 |
| baseline: climatology z-score only | 0.9% | 0.0% | - | 147078 |
| baseline: Isolation Forest only | 0.4% | 0.0% | - | 147078 |
| baseline: Mahalanobis distance only | 0.5% | 0.0% | - | 147078 |

#### 3. Real extreme weather (nothing injected)

A FAULT here is a failure: real weather called a broken sensor. WEATHER is the escalated, correct verdict.

| configuration | FAULT | SUSPECT | WEATHER | VALID | windows with a FAULT |
|---|---|---|---|---|---|
| AtmosGuard (full) | 0.0% | 8.2% | 11.8% | 80.0% | 0/38 |
| without physics layer | 0.0% | 8.2% | 11.8% | 80.0% | 0/38 |
| without health layer | 0.0% | 2.5% | 7.0% | 90.5% | 0/38 |
| without normality layer | 0.0% | 4.4% | 2.9% | 92.7% | 0/38 |
| without Isolation Forest | 0.0% | 8.2% | 11.1% | 80.7% | 0/38 |
| without Mahalanobis layer | 0.0% | 8.0% | 10.7% | 81.3% | 0/38 |
| without timing layer | 0.0% | 8.1% | 11.8% | 80.1% | 0/38 |
| without station-learned limits | 33.7% | 31.1% | 3.7% | 31.6% | 38/38 |
| baseline: range check only | 0.0% | 0.0% | - | 100.0% | 0/38 |
| baseline: textbook range + step + persistence | 7.1% | 0.0% | - | 92.9% | 37/38 |
| baseline: climatology z-score only | 0.0% | 5.7% | - | 94.3% | 0/38 |
| baseline: Isolation Forest only | 0.0% | 1.7% | - | 98.3% | 0/38 |
| baseline: Mahalanobis distance only | 0.0% | 2.0% | - | 98.0% | 0/38 |

Full pipeline, by kind of extreme weather:

| kind of extreme weather | samples | FAULT | SUSPECT | WEATHER | windows with a FAULT |
|---|---|---|---|---|---|
| cold | 425 | 0.0% | 0.7% | 4.9% | 0/3 |
| heat | 653 | 0.0% | 8.1% | 19.9% | 0/5 |
| low | 1622 | 0.0% | 15.8% | 19.2% | 0/12 |
| sharp | 1674 | 0.0% | 2.8% | 3.2% | 0/18 |

#### 4. Agreement with NOAA's own quality flags

NOAA's flags come from another automated system. Agreement means consistency with existing practice, not proof of real-world accuracy.

| measure | value |
|---|---|
| NOAA-flagged values (suspect or erroneous) | 265 |
|   of which erroneous | 0 |
| AtmosGuard alarmed (FAULT or SUSPECT) on flagged values | 18.5% |
| AtmosGuard escalated at all (also WEATHER) on flagged values | 61.5% |
| AtmosGuard alarmed on erroneous values | n/a |
| values NOAA did not flag | 151336 |
| AtmosGuard alarmed on those (extra flags) | 2.8% |
| AtmosGuard escalated at all on those | 5.7% |

#### 5. Slow drift, judged by the health monitor

A ramp over 45 days is added to one channel of clean real data. Severity = offset at the end of the ramp in multiples of the service limit (T 0.5 C, P 1 hPa, RH 3 %). One station, no reference: small drifts cannot be told from weather.

| drift at end of ramp | temperature | pressure | humidity |
|---|---|---|---|
| none (false claims) | 19.2% of 26 chunks | 7.7% of 26 chunks | 15.4% of 26 chunks |
| 1x service limit | 4% of 26 (day 49, 1.7x at detection) | 4% of 26 (day 264, 3.6x at detection) | 12% of 26 (day 281, 2.5x at detection) |
| 2x service limit | 8% of 26 (day 51, 3.2x at detection) | 0% of 26 (-, - at detection) | 12% of 26 (day 281, 3.9x at detection) |
| 4x service limit | 19% of 26 (day 49, 4.7x at detection) | 19% of 26 (day 53, 4.0x at detection) | 23% of 26 (day 55, 5.1x at detection) |
| 8x service limit | 50% of 26 (day 49, 8.0x at detection) | 54% of 26 (day 55, 6.3x at detection) | 46% of 26 (day 36, 7.1x at detection) |

#### By station (full pipeline)

Each station judged on its own record.

| station | cadence (min) | clean any alarm | clean FAULT | extreme weather FAULT | windows with a FAULT | extreme weather WEATHER | injected faults detected |
|---|---|---|---|---|---|---|---|
| BBI | 60 | 2.4% | 0.0% | 0.0% | 0/5 | 4.4% | 94% |
| MAA | 60 | 3.2% | 0.0% | 0.0% | 0/6 | 23.8% | 97% |
| CCU | 60 | 1.9% | 0.0% | 0.0% | 0/9 | 13.6% | 94% |
| DEL | 60 | 2.2% | 0.0% | 0.0% | 0/7 | 7.7% | 96% |
| JAI | 60 | 3.1% | 0.0% | 0.0% | 0/8 | 10.5% | 89% |
| TRV | 60 | 2.1% | 0.0% | 0.0% | 0/3 | 7.0% | 99% |

#### 1b. The same, by the criterion registered in the protocol (any alarm in the window)

Background false alarms (about 2 % of samples) also fall inside long fault windows, so this flatters long faults (frozen 48 h, clock shift 4 days) and every system, baselines included. Kept because it was registered before the holdout.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 99% | 99% | 82% | 100% | 97% |
| without physics layer | 100% | 98% | 97% | 80% | 100% | 97% |
| without health layer | 50% | 88% | 96% | 64% | 2% | 90% |
| without normality layer | 100% | 99% | 98% | 82% | 100% | 95% |
| without Isolation Forest | 100% | 99% | 99% | 82% | 100% | 97% |
| without Mahalanobis layer | 100% | 95% | 76% | 68% | 100% | 97% |
| without timing layer | 100% | 99% | 99% | 82% | 100% | 72% |
| without station-learned limits | 100% | 100% | 100% | 100% | 100% | 100% |
| baseline: range check only | 0% | 14% | 15% | 13% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 78% | 94% | 82% | 10% | 92% |
| baseline: climatology z-score only | 27% | 44% | 48% | 18% | 3% | 53% |
| baseline: Isolation Forest only | 4% | 10% | 18% | 18% | 0% | 47% |
| baseline: Mahalanobis distance only | 46% | 100% | 100% | 81% | 0% | 47% |
| (faults injected) | 279 | 279 | 279 | 279 | 279 | 260 |
| AtmosGuard: median minutes to the alarm | 480 | 0 | 0 | 360 | 0 | 1020 |

#### No single simpler system is good at every fault type

Each system's weakest fault type from table 1, beside its false-alarm rate and its record on real extreme weather. A system that is best at one fault type is blind to another; the layers exist for coverage, and the WEATHER verdict exists so that coverage does not cost real storms.

| system | weakest injected-fault type (fault raised the alarm) | false alarms on clean data | real extreme weather, windows with a FAULT |
|---|---|---|---|
| AtmosGuard (full) | noise burst: 79% | 2.5% | 0/38 |
| baseline: range check only | frozen: 0% | 0.0% | 0/38 |
| baseline: textbook range + step + persistence | dropout: 0% | 5.2% | 37/38 |
| baseline: climatology z-score only | dropout: 0% | 0.9% | 0/38 |
| baseline: Isolation Forest only | dropout: 0% | 0.4% | 0/38 |
| baseline: Mahalanobis distance only | dropout: 0% | 0.5% | 0/38 |

### 4.3 HOLDOUT in space: eight stations never used for any tuning, 2020-2024

*Five hourly airport stations and three 3-hourly SYNOP stations (Port Blair, Bhuj, Cochin).* Stations: AMD, NAG, BOM, GAU, VTZ, IXZ, BHJ, COK.

#### Headline

Five separate numbers. They are never merged.

| question | answer |
|---|---|
| False alarms on clean real data (nothing injected) | 2.9% (2.8-3.0) of 237411 samples got FAULT or SUSPECT; 0.0% (0.0-0.1) got FAULT |
| What happens to real extreme weather (cyclones, heat, cold, sharp fronts; nothing injected) | FAULT on 0.3% (0.2-0.4) of 9074 samples (3 of 98 windows); WEATHER on 15.7%, SUSPECT on 8.6% |
| Injected faults whose alarm the fault raised (each type on its own; injected, not real) | frozen 100%; spike 90%; level shift 89%; noise burst 67%; dropout 98%; clock 3 h out 84% |
| Agreement with NOAA's own quality flags (another automated system, not ground truth) | escalated (FAULT, SUSPECT or WEATHER) on 67.6% of 559 NOAA-flagged values (FAULT or SUSPECT alone: 40.8%); escalated on 6.9% of the 246257 values NOAA left alone |
| Slow drift (health monitor, single station, no reference) | false drift claims on 0.6% of 12495 station-days; an injected ramp reaching 8x the service limit was found in 56% of trials |

#### 1. Detection of injected faults, by type (the fault raised the alarm)

Alarm = FAULT or SUSPECT on a sample that was NOT an alarm on the same series without the fault (paired), from the first faulty sample to the last plus 60 minutes. The faults are injected, not real. Ablation rows switch one layer off; baseline rows are simpler systems on the same data.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 90% | 89% | 67% | 98% | 84% |
| without physics layer | 100% | 88% | 88% | 65% | 98% | 84% |
| without health layer | 45% | 77% | 83% | 52% | 0% | 70% |
| without normality layer | 100% | 93% | 82% | 67% | 99% | 78% |
| without Isolation Forest | 100% | 90% | 89% | 67% | 98% | 84% |
| without Mahalanobis layer | 100% | 81% | 75% | 56% | 98% | 82% |
| without timing layer | 100% | 90% | 89% | 67% | 98% | 70% |
| without station-learned limits | 82% | 37% | 68% | 69% | 46% | 77% |
| baseline: range check only | 0% | 12% | 13% | 11% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 74% | 80% | 66% | 0% | 91% |
| baseline: climatology z-score only | 25% | 51% | 50% | 11% | 0% | 60% |
| baseline: Isolation Forest only | 3% | 17% | 16% | 15% | 0% | 56% |
| baseline: Mahalanobis distance only | 40% | 98% | 88% | 63% | 0% | 49% |
| (faults injected) | 702 | 702 | 702 | 702 | 702 | 619 |
| AtmosGuard: median minutes to the alarm | 480 | 0 | 0 | 360 | 0 | 1020 |

#### 1d. How sure are the detection numbers? (AtmosGuard full, paired criterion, Wilson 95 % interval)

Faults are injected at random places; each row's interval says how much the percentage could move with another draw of the same size. Faults of one type overlap little but are not fully independent, so read the interval as a guide, not a guarantee.

| fault type | injected | raised the alarm (fault-raised) | named FAULT |
|---|---|---|---|
| frozen | 702 | 99.9% (99.2-100.0) | 95.9% (94.1-97.1) |
| spike | 702 | 89.7% (87.3-91.8) | 17.0% (14.4-19.9) |
| level shift | 702 | 89.0% (86.5-91.1) | 13.4% (11.1-16.1) |
| noise burst | 702 | 67.4% (63.8-70.7) | 11.3% (9.1-13.8) |
| dropout | 702 | 98.4% (97.2-99.1) | 98.4% (97.2-99.1) |
| clock 3 h out | 619 | 83.5% (80.4-86.2) | 0.5% (0.2-1.4) |

#### 1c. How AtmosGuard names what it detects, and the WEATHER-masking check

A FAULT verdict names the problem; SUSPECT asks for review. The last row is the risk of the coherent-level WEATHER route: a fault that was not alarmed but made samples look like real weather.

| AtmosGuard, injected faults | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| raised an alarm (FAULT or SUSPECT) | 100% | 90% | 89% | 67% | 98% | 84% |
| of which named FAULT | 96% | 17% | 13% | 11% | 98% | 0% |
| missed, but made some samples look like WEATHER | 0% | 8% | 8% | 7% | 0% | 8% |

#### 2. False alarms on clean real data

No fault injected. Extreme-weather windows and NOAA-flagged values removed.

| configuration | any alarm | FAULT only | WEATHER verdicts | samples |
|---|---|---|---|---|
| AtmosGuard (full) | 2.9% | 0.0% | 3.2% | 237411 |
| without physics layer | 2.9% | 0.0% | 3.2% | 237411 |
| without health layer | 0.6% | 0.0% | 1.9% | 237411 |
| without normality layer | 1.6% | 0.0% | 1.1% | 237411 |
| without Isolation Forest | 2.9% | 0.0% | 2.9% | 237411 |
| without Mahalanobis layer | 2.7% | 0.0% | 2.8% | 237411 |
| without timing layer | 2.8% | 0.0% | 3.2% | 237411 |
| without station-learned limits | 67.7% | 25.8% | 0.9% | 237411 |
| baseline: range check only | 0.0% | 0.0% | - | 237411 |
| baseline: textbook range + step + persistence | 6.8% | 6.8% | - | 237411 |
| baseline: climatology z-score only | 1.1% | 0.0% | - | 237411 |
| baseline: Isolation Forest only | 0.6% | 0.0% | - | 237411 |
| baseline: Mahalanobis distance only | 0.7% | 0.0% | - | 237411 |

#### 3. Real extreme weather (nothing injected)

A FAULT here is a failure: real weather called a broken sensor. WEATHER is the escalated, correct verdict.

| configuration | FAULT | SUSPECT | WEATHER | VALID | windows with a FAULT |
|---|---|---|---|---|---|
| AtmosGuard (full) | 0.3% | 8.6% | 15.7% | 75.4% | 3/98 |
| without physics layer | 0.3% | 8.6% | 15.7% | 75.4% | 3/98 |
| without health layer | 0.0% | 3.0% | 9.6% | 87.4% | 0/98 |
| without normality layer | 0.3% | 5.9% | 4.4% | 89.5% | 3/98 |
| without Isolation Forest | 0.3% | 8.6% | 14.8% | 76.4% | 3/98 |
| without Mahalanobis layer | 0.3% | 8.1% | 14.7% | 76.9% | 3/98 |
| without timing layer | 0.3% | 8.6% | 15.7% | 75.5% | 3/98 |
| without station-learned limits | 23.9% | 43.7% | 5.1% | 27.3% | 70/98 |
| baseline: range check only | 0.0% | 0.0% | - | 100.0% | 0/98 |
| baseline: textbook range + step + persistence | 7.7% | 0.0% | - | 92.3% | 95/98 |
| baseline: climatology z-score only | 0.0% | 7.6% | - | 92.4% | 0/98 |
| baseline: Isolation Forest only | 0.0% | 2.8% | - | 97.2% | 0/98 |
| baseline: Mahalanobis distance only | 0.0% | 3.5% | - | 96.5% | 0/98 |

Full pipeline, by kind of extreme weather:

| kind of extreme weather | samples | FAULT | SUSPECT | WEATHER | windows with a FAULT |
|---|---|---|---|---|---|
| cold | 2033 | 0.0% | 7.9% | 8.7% | 0/20 |
| heat | 1069 | 0.0% | 5.6% | 19.4% | 0/11 |
| low | 3222 | 0.7% | 13.5% | 25.6% | 2/27 |
| sharp | 2750 | 0.0% | 4.5% | 7.9% | 1/40 |

#### 4. Agreement with NOAA's own quality flags

NOAA's flags come from another automated system. Agreement means consistency with existing practice, not proof of real-world accuracy.

| measure | value |
|---|---|
| NOAA-flagged values (suspect or erroneous) | 559 |
|   of which erroneous | 0 |
| AtmosGuard alarmed (FAULT or SUSPECT) on flagged values | 40.8% |
| AtmosGuard escalated at all (also WEATHER) on flagged values | 67.6% |
| AtmosGuard alarmed on erroneous values | n/a |
| values NOAA did not flag | 246257 |
| AtmosGuard alarmed on those (extra flags) | 3.2% |
| AtmosGuard escalated at all on those | 6.9% |

#### 5. Slow drift, judged by the health monitor

A ramp over 45 days is added to one channel of clean real data. Severity = offset at the end of the ramp in multiples of the service limit (T 0.5 C, P 1 hPa, RH 3 %). One station, no reference: small drifts cannot be told from weather.

| drift at end of ramp | temperature | pressure | humidity |
|---|---|---|---|
| none (false claims) | 6.8% of 59 chunks | 11.9% of 59 chunks | 6.8% of 59 chunks |
| 1x service limit | 7% of 59 (day 79, 4.7x at detection) | 0% of 59 (-, - at detection) | 2% of 59 (day 29, 4.5x at detection) |
| 2x service limit | 15% of 59 (day 46, 4.0x at detection) | 3% of 59 (day 61, 3.1x at detection) | 5% of 59 (day 42, 3.4x at detection) |
| 4x service limit | 31% of 59 (day 47, 6.3x at detection) | 12% of 59 (day 47, 4.4x at detection) | 20% of 59 (day 47, 4.9x at detection) |
| 8x service limit | 64% of 59 (day 47, 7.8x at detection) | 47% of 59 (day 48, 6.3x at detection) | 58% of 59 (day 42, 6.7x at detection) |

#### By station (full pipeline)

Each station judged on its own record.

| station | cadence (min) | clean any alarm | clean FAULT | extreme weather FAULT | windows with a FAULT | extreme weather WEATHER | injected faults detected |
|---|---|---|---|---|---|---|---|
| AMD | 60 | 2.6% | 0.1% | 0.0% | 0/13 | 18.6% | 95% |
| NAG | 60 | 2.8% | 0.0% | 0.0% | 0/12 | 9.0% | 92% |
| BOM | 60 | 1.8% | 0.0% | 0.0% | 0/13 | 18.3% | 96% |
| GAU | 60 | 4.4% | 0.0% | 0.0% | 0/15 | 18.3% | 93% |
| VTZ | 60 | 2.8% | 0.1% | 1.7% | 2/13 | 16.4% | 95% |
| IXZ | 180 | 2.0% | 0.0% | 0.0% | 0/11 | 9.1% | 73% |
| BHJ | 180 | 4.9% | 0.1% | 0.2% | 1/12 | 17.2% | 70% |
| COK | 180 | 2.4% | 0.0% | 0.0% | 0/9 | 9.4% | 78% |

#### 1b. The same, by the criterion registered in the protocol (any alarm in the window)

Background false alarms (about 2 % of samples) also fall inside long fault windows, so this flatters long faults (frozen 48 h, clock shift 4 days) and every system, baselines included. Kept because it was registered before the holdout.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 93% | 92% | 76% | 100% | 84% |
| without physics layer | 100% | 91% | 91% | 74% | 100% | 84% |
| without health layer | 47% | 77% | 84% | 55% | 1% | 70% |
| without normality layer | 100% | 94% | 84% | 73% | 100% | 78% |
| without Isolation Forest | 100% | 93% | 92% | 76% | 100% | 84% |
| without Mahalanobis layer | 100% | 85% | 79% | 65% | 100% | 83% |
| without timing layer | 100% | 93% | 92% | 76% | 100% | 71% |
| without station-learned limits | 100% | 98% | 100% | 100% | 100% | 100% |
| baseline: range check only | 0% | 12% | 13% | 11% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 79% | 92% | 84% | 16% | 92% |
| baseline: climatology z-score only | 29% | 52% | 53% | 16% | 1% | 61% |
| baseline: Isolation Forest only | 7% | 18% | 22% | 21% | 0% | 56% |
| baseline: Mahalanobis distance only | 46% | 98% | 88% | 67% | 0% | 49% |
| (faults injected) | 702 | 702 | 702 | 702 | 702 | 619 |
| AtmosGuard: median minutes to the alarm | 480 | 0 | 0 | 360 | 0 | 960 |

#### No single simpler system is good at every fault type

Each system's weakest fault type from table 1, beside its false-alarm rate and its record on real extreme weather. A system that is best at one fault type is blind to another; the layers exist for coverage, and the WEATHER verdict exists so that coverage does not cost real storms.

| system | weakest injected-fault type (fault raised the alarm) | false alarms on clean data | real extreme weather, windows with a FAULT |
|---|---|---|---|
| AtmosGuard (full) | noise burst: 67% | 2.9% | 3/98 |
| baseline: range check only | frozen: 0% | 0.0% | 0/98 |
| baseline: textbook range + step + persistence | dropout: 0% | 6.8% | 95/98 |
| baseline: climatology z-score only | dropout: 0% | 1.1% | 0/98 |
| baseline: Isolation Forest only | dropout: 0% | 0.6% | 0/98 |
| baseline: Mahalanobis distance only | dropout: 0% | 0.7% | 0/98 |

### 4.4 FRESH: twelve more stations nobody had looked at, 2020-2024

*Chosen and sealed before the two remedies from the holdout post-mortem were tested (Amendment 2 in config/protocol.md). Eight hourly airport stations and four 3-hourly SYNOP stations.* Stations: LKO, PAT, IDR, IXR, CJB, IXE, TRZ, ATQ, PNQ, GOI, RPR, JDH.

#### Headline

Five separate numbers. They are never merged.

| question | answer |
|---|---|
| False alarms on clean real data (nothing injected) | 2.5% (2.5-2.6) of 364440 samples got FAULT or SUSPECT; 0.1% (0.1-0.1) got FAULT |
| What happens to real extreme weather (cyclones, heat, cold, sharp fronts; nothing injected) | FAULT on 0.1% (0.1-0.2) of 11782 samples (3 of 139 windows); WEATHER on 10.3%, SUSPECT on 6.8% |
| Injected faults whose alarm the fault raised (each type on its own; injected, not real) | frozen 99%; spike 91%; level shift 80%; noise burst 57%; dropout 98%; clock 3 h out 85% |
| Agreement with NOAA's own quality flags (another automated system, not ground truth) | escalated (FAULT, SUSPECT or WEATHER) on 71.1% of 974 NOAA-flagged values (FAULT or SUSPECT alone: 54.9%); escalated on 5.7% of the 375993 values NOAA left alone |
| Slow drift (health monitor, single station, no reference) | false drift claims on 0.9% of 18493 station-days; an injected ramp reaching 8x the service limit was found in 62% of trials |

#### 1. Detection of injected faults, by type (the fault raised the alarm)

Alarm = FAULT or SUSPECT on a sample that was NOT an alarm on the same series without the fault (paired), from the first faulty sample to the last plus 60 minutes. The faults are injected, not real. Ablation rows switch one layer off; baseline rows are simpler systems on the same data.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 99% | 91% | 80% | 57% | 98% | 85% |
| AtmosGuard + remedy 1 (ceiling-aware frozen rule) | 99% | 91% | 80% | 57% | 98% | 85% |
| AtmosGuard + remedy 2 (learned step cap) | 99% | 88% | 80% | 56% | 99% | 81% |
| AtmosGuard + both remedies | 99% | 88% | 80% | 56% | 99% | 81% |
| without physics layer | 99% | 90% | 77% | 54% | 98% | 85% |
| without health layer | 47% | 74% | 72% | 40% | 0% | 68% |
| without normality layer | 99% | 93% | 72% | 56% | 99% | 81% |
| without Isolation Forest | 99% | 91% | 80% | 57% | 98% | 85% |
| without Mahalanobis layer | 99% | 78% | 66% | 46% | 98% | 85% |
| without timing layer | 99% | 91% | 80% | 57% | 98% | 69% |
| without station-learned limits | 75% | 35% | 57% | 62% | 44% | 72% |
| baseline: range check only | 0% | 12% | 13% | 9% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 72% | 78% | 63% | 0% | 94% |
| baseline: climatology z-score only | 27% | 42% | 38% | 9% | 0% | 63% |
| baseline: Isolation Forest only | 1% | 10% | 13% | 11% | 0% | 51% |
| baseline: Mahalanobis distance only | 39% | 99% | 82% | 51% | 0% | 45% |
| (faults injected) | 918 | 918 | 918 | 918 | 918 | 794 |
| AtmosGuard: median minutes to the alarm | 420 | 0 | 0 | 420 | 0 | 1140 |

#### 1d. How sure are the detection numbers? (AtmosGuard full, paired criterion, Wilson 95 % interval)

Faults are injected at random places; each row's interval says how much the percentage could move with another draw of the same size. Faults of one type overlap little but are not fully independent, so read the interval as a guide, not a guarantee.

| fault type | injected | raised the alarm (fault-raised) | named FAULT |
|---|---|---|---|
| frozen | 918 | 99.1% (98.3-99.6) | 89.4% (87.3-91.3) |
| spike | 918 | 91.1% (89.0-92.7) | 18.1% (15.7-20.7) |
| level shift | 918 | 80.3% (77.6-82.7) | 14.3% (12.2-16.7) |
| noise burst | 918 | 57.3% (54.1-60.5) | 9.6% (7.8-11.7) |
| dropout | 918 | 98.4% (97.3-99.0) | 98.4% (97.3-99.0) |
| clock 3 h out | 794 | 85.1% (82.5-87.4) | 1.5% (0.9-2.6) |

#### 1c. How AtmosGuard names what it detects, and the WEATHER-masking check

A FAULT verdict names the problem; SUSPECT asks for review. The last row is the risk of the coherent-level WEATHER route: a fault that was not alarmed but made samples look like real weather.

| AtmosGuard, injected faults | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| raised an alarm (FAULT or SUSPECT) | 99% | 91% | 80% | 57% | 98% | 85% |
| of which named FAULT | 89% | 18% | 14% | 10% | 98% | 2% |
| missed, but made some samples look like WEATHER | 0% | 7% | 10% | 7% | 0% | 9% |

#### The two remedies from the post-mortem, judged by the decision rule registered in Amendment 2

Rule: adopt only if (a) real extreme-weather windows with a FAULT and the FAULT share do not rise, (b) paired detection loses at most 2 points for any injected-fault type, (c) clean false alarms rise by at most 0.2 points. Compared with the frozen `full` pipeline on the same stations.

| configuration | (a) windows with a FAULT (full / this) | (a) FAULT share of extreme-weather samples (full / this) | (b) worst change in paired detection | (c) change in clean false alarms | rule (a) | rule (b) | rule (c) | adopt |
|---|---|---|---|---|---|---|---|---|
| AtmosGuard + remedy 1 (ceiling-aware frozen rule) | 3 / 2 of 139 | 0.09% / 0.03% | none | -0.00 pp | pass | pass | pass | yes |
| AtmosGuard + remedy 2 (learned step cap) | 3 / 2 of 139 | 0.09% / 0.08% | -4.2 pp (clock 3 h out) | -0.18 pp | pass | FAIL | pass | no |
| AtmosGuard + both remedies | 3 / 1 of 139 | 0.09% / 0.01% | -4.2 pp (clock 3 h out) | -0.18 pp | pass | FAIL | pass | no |

#### 2. False alarms on clean real data

No fault injected. Extreme-weather windows and NOAA-flagged values removed.

| configuration | any alarm | FAULT only | WEATHER verdicts | samples |
|---|---|---|---|---|
| AtmosGuard (full) | 2.5% | 0.1% | 2.8% | 364440 |
| AtmosGuard + remedy 1 (ceiling-aware frozen rule) | 2.5% | 0.0% | 2.8% | 364440 |
| AtmosGuard + remedy 2 (learned step cap) | 2.4% | 0.1% | 2.8% | 364440 |
| AtmosGuard + both remedies | 2.4% | 0.0% | 2.8% | 364440 |
| without physics layer | 2.5% | 0.1% | 2.8% | 364440 |
| without health layer | 0.7% | 0.0% | 1.4% | 364440 |
| without normality layer | 1.4% | 0.1% | 0.8% | 364440 |
| without Isolation Forest | 2.5% | 0.1% | 2.6% | 364440 |
| without Mahalanobis layer | 2.4% | 0.1% | 2.6% | 364440 |
| without timing layer | 2.3% | 0.1% | 2.7% | 364440 |
| without station-learned limits | 63.8% | 25.6% | 0.8% | 364440 |
| baseline: range check only | 0.0% | 0.0% | - | 364440 |
| baseline: textbook range + step + persistence | 8.4% | 8.4% | - | 364440 |
| baseline: climatology z-score only | 0.9% | 0.0% | - | 364440 |
| baseline: Isolation Forest only | 0.4% | 0.0% | - | 364440 |
| baseline: Mahalanobis distance only | 0.5% | 0.0% | - | 364440 |

#### 3. Real extreme weather (nothing injected)

A FAULT here is a failure: real weather called a broken sensor. WEATHER is the escalated, correct verdict.

| configuration | FAULT | SUSPECT | WEATHER | VALID | windows with a FAULT |
|---|---|---|---|---|---|
| AtmosGuard (full) | 0.1% | 6.8% | 10.3% | 82.9% | 3/139 |
| AtmosGuard + remedy 1 (ceiling-aware frozen rule) | 0.0% | 6.8% | 10.3% | 82.9% | 2/139 |
| AtmosGuard + remedy 2 (learned step cap) | 0.1% | 6.4% | 10.4% | 83.1% | 2/139 |
| AtmosGuard + both remedies | 0.0% | 6.4% | 10.5% | 83.1% | 1/139 |
| without physics layer | 0.1% | 6.8% | 10.3% | 82.9% | 3/139 |
| without health layer | 0.0% | 2.3% | 5.7% | 92.0% | 0/139 |
| without normality layer | 0.1% | 3.8% | 2.9% | 93.2% | 4/139 |
| without Isolation Forest | 0.1% | 6.7% | 9.7% | 83.5% | 3/139 |
| without Mahalanobis layer | 0.1% | 6.4% | 9.6% | 83.9% | 3/139 |
| without timing layer | 0.1% | 6.7% | 10.2% | 83.0% | 3/139 |
| without station-learned limits | 20.1% | 45.0% | 2.8% | 32.1% | 90/139 |
| baseline: range check only | 0.0% | 0.0% | - | 100.0% | 0/139 |
| baseline: textbook range + step + persistence | 10.3% | 0.0% | - | 89.7% | 134/139 |
| baseline: climatology z-score only | 0.0% | 4.4% | - | 95.6% | 0/139 |
| baseline: Isolation Forest only | 0.0% | 2.0% | - | 98.0% | 0/139 |
| baseline: Mahalanobis distance only | 0.0% | 1.9% | - | 98.1% | 0/139 |

Full pipeline, by kind of extreme weather:

| kind of extreme weather | samples | FAULT | SUSPECT | WEATHER | windows with a FAULT |
|---|---|---|---|---|---|
| cold | 1898 | 0.0% | 6.0% | 5.2% | 0/19 |
| heat | 1266 | 0.0% | 7.0% | 14.3% | 0/16 |
| low | 4389 | 0.2% | 9.8% | 15.9% | 1/44 |
| sharp | 4229 | 0.1% | 3.9% | 5.6% | 2/60 |

#### 4. Agreement with NOAA's own quality flags

NOAA's flags come from another automated system. Agreement means consistency with existing practice, not proof of real-world accuracy.

| measure | value |
|---|---|
| NOAA-flagged values (suspect or erroneous) | 974 |
|   of which erroneous | 0 |
| AtmosGuard alarmed (FAULT or SUSPECT) on flagged values | 54.9% |
| AtmosGuard escalated at all (also WEATHER) on flagged values | 71.1% |
| AtmosGuard alarmed on erroneous values | n/a |
| values NOAA did not flag | 375993 |
| AtmosGuard alarmed on those (extra flags) | 2.7% |
| AtmosGuard escalated at all on those | 5.7% |

#### 5. Slow drift, judged by the health monitor

A ramp over 45 days is added to one channel of clean real data. Severity = offset at the end of the ramp in multiples of the service limit (T 0.5 C, P 1 hPa, RH 3 %). One station, no reference: small drifts cannot be told from weather.

| drift at end of ramp | temperature | pressure | humidity |
|---|---|---|---|
| none (false claims) | 13.5% of 74 chunks | 9.5% of 74 chunks | 16.2% of 74 chunks |
| 1x service limit | 14% of 74 (day 60, 4.1x at detection) | 4% of 74 (day 22, 4.1x at detection) | 9% of 74 (day 145, 5.2x at detection) |
| 2x service limit | 16% of 74 (day 58, 4.6x at detection) | 7% of 74 (day 26, 3.1x at detection) | 18% of 74 (day 73, 4.4x at detection) |
| 4x service limit | 26% of 74 (day 55, 5.6x at detection) | 20% of 74 (day 43, 4.4x at detection) | 31% of 74 (day 52, 5.3x at detection) |
| 8x service limit | 54% of 74 (day 47, 7.7x at detection) | 59% of 74 (day 49, 5.8x at detection) | 73% of 74 (day 52, 7.6x at detection) |

#### By station (full pipeline)

Each station judged on its own record.

| station | cadence (min) | clean any alarm | clean FAULT | extreme weather FAULT | windows with a FAULT | extreme weather WEATHER | injected faults detected |
|---|---|---|---|---|---|---|---|
| LKO | 60 | 2.1% | 0.0% | 0.0% | 0/11 | 9.9% | 91% |
| PAT | 60 | 2.8% | 0.0% | 0.0% | 0/14 | 8.8% | 94% |
| IDR | 60 | 2.2% | 0.0% | 0.0% | 0/14 | 5.6% | 91% |
| IXR | 60 | 2.0% | 0.0% | 0.5% | 1/13 | 9.1% | 92% |
| CJB | 60 | 2.1% | 0.0% | 0.2% | 1/5 | 3.1% | 95% |
| IXE | 60 | 2.1% | 0.0% | 0.0% | 0/8 | 24.6% | 97% |
| TRZ | 60 | 2.3% | 0.0% | 0.0% | 0/7 | 4.2% | 99% |
| ATQ | 60 | 2.8% | 0.6% | 0.0% | 0/13 | 10.2% | 87% |
| PNQ | 180 | 6.0% | 0.0% | 0.0% | 0/16 | 8.2% | 73% |
| GOI | 180 | 3.2% | 0.0% | 0.0% | 0/12 | 13.3% | 77% |
| RPR | 180 | 3.0% | 0.0% | 0.0% | 0/13 | 20.9% | 71% |
| JDH | 180 | 3.9% | 0.2% | 0.4% | 1/13 | 12.6% | 66% |

#### 1b. The same, by the criterion registered in the protocol (any alarm in the window)

Background false alarms (about 2 % of samples) also fall inside long fault windows, so this flatters long faults (frozen 48 h, clock shift 4 days) and every system, baselines included. Kept because it was registered before the holdout.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 99% | 93% | 84% | 65% | 100% | 87% |
| AtmosGuard + remedy 1 (ceiling-aware frozen rule) | 99% | 93% | 84% | 65% | 100% | 87% |
| AtmosGuard + remedy 2 (learned step cap) | 99% | 90% | 82% | 61% | 100% | 82% |
| AtmosGuard + both remedies | 99% | 90% | 82% | 61% | 100% | 82% |
| without physics layer | 99% | 92% | 81% | 62% | 100% | 87% |
| without health layer | 50% | 74% | 74% | 44% | 1% | 68% |
| without normality layer | 99% | 94% | 76% | 62% | 100% | 81% |
| without Isolation Forest | 99% | 93% | 84% | 65% | 100% | 87% |
| without Mahalanobis layer | 99% | 80% | 71% | 54% | 100% | 86% |
| without timing layer | 99% | 93% | 84% | 65% | 100% | 71% |
| without station-learned limits | 100% | 97% | 100% | 99% | 100% | 100% |
| baseline: range check only | 0% | 12% | 13% | 9% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 82% | 94% | 86% | 19% | 94% |
| baseline: climatology z-score only | 32% | 43% | 41% | 13% | 2% | 64% |
| baseline: Isolation Forest only | 6% | 11% | 18% | 18% | 0% | 51% |
| baseline: Mahalanobis distance only | 44% | 99% | 83% | 53% | 0% | 45% |
| (faults injected) | 918 | 918 | 918 | 918 | 918 | 794 |
| AtmosGuard: median minutes to the alarm | 420 | 0 | 0 | 420 | 0 | 1080 |

#### No single simpler system is good at every fault type

Each system's weakest fault type from table 1, beside its false-alarm rate and its record on real extreme weather. A system that is best at one fault type is blind to another; the layers exist for coverage, and the WEATHER verdict exists so that coverage does not cost real storms.

| system | weakest injected-fault type (fault raised the alarm) | false alarms on clean data | real extreme weather, windows with a FAULT |
|---|---|---|---|
| AtmosGuard (full) | noise burst: 57% | 2.5% | 3/139 |
| AtmosGuard + remedy 1 (ceiling-aware frozen rule) | noise burst: 57% | 2.5% | 2/139 |
| AtmosGuard + remedy 2 (learned step cap) | noise burst: 56% | 2.4% | 2/139 |
| AtmosGuard + both remedies | noise burst: 56% | 2.4% | 1/139 |
| baseline: range check only | frozen: 0% | 0.0% | 0/139 |
| baseline: textbook range + step + persistence | dropout: 0% | 8.4% | 134/139 |
| baseline: climatology z-score only | dropout: 0% | 0.9% | 0/139 |
| baseline: Isolation Forest only | dropout: 0% | 0.4% | 0/139 |
| baseline: Mahalanobis distance only | dropout: 0% | 0.5% | 0/139 |

### 4.5 FRESH2: a third set of twelve stations, 2020-2024

*Chosen and sealed before the two Amendment 3 remedies were tested (config/protocol.md). Five Indian airport stations (hourly METAR, whole degrees) and seven Australian automatic weather stations (hourly SYNOP at 0.1 C and 0.1 hPa). `AtmosGuard (full)` here is the pipeline as shipped before Amendment 3 (remedy 1 on).* Stations: HYD, BLR, CCJ, IXM, VGA, CWS, LEI, WIL, GLS, COT, THB, MTC.

#### Headline

Five separate numbers. They are never merged.

| question | answer |
|---|---|
| False alarms on clean real data (nothing injected) | 9.3% (9.2-9.3) of 453323 samples got FAULT or SUSPECT; 0.0% (0.0-0.0) got FAULT |
| What happens to real extreme weather (cyclones, heat, cold, sharp fronts; nothing injected) | FAULT on 0.0% (0.0-0.1) of 14732 samples (4 of 134 windows); WEATHER on 4.1%, SUSPECT on 14.1% |
| Injected faults whose alarm the fault raised (each type on its own; injected, not real) | frozen 100%; spike 89%; level shift 91%; noise burst 83%; dropout 93%; clock 3 h out 90% |
| Agreement with NOAA's own quality flags (another automated system, not ground truth) | escalated (FAULT, SUSPECT or WEATHER) on 67.8% of 708 NOAA-flagged values (FAULT or SUSPECT alone: 43.1%); escalated on 11.5% of the 467945 values NOAA left alone |
| Slow drift (health monitor, single station, no reference) | false drift claims on 0.4% of 17919 station-days; an injected ramp reaching 8x the service limit was found in 50% of trials |

#### 1. Detection of injected faults, by type (the fault raised the alarm)

Alarm = FAULT or SUSPECT on a sample that was NOT an alarm on the same series without the fault (paired), from the first faulty sample to the last plus 60 minutes. The faults are injected, not real. Ablation rows switch one layer off; baseline rows are simpler systems on the same data.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 89% | 91% | 83% | 93% | 90% |
| AtmosGuard as registered (every remedy off) | 100% | 89% | 91% | 83% | 93% | 90% |
| AtmosGuard + remedy 3 (expected-change-aware step rule) | 100% | 89% | 91% | 83% | 93% | 90% |
| AtmosGuard + remedy 4 (sustained one-channel offset) | 100% | 89% | 92% | 83% | 93% | 91% |
| AtmosGuard + remedies 3 and 4 | 100% | 89% | 92% | 83% | 93% | 91% |
| baseline: range check only | 0% | 13% | 14% | 13% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 75% | 84% | 66% | 0% | 65% |
| baseline: climatology z-score only | 17% | 35% | 34% | 11% | 0% | 46% |
| baseline: Isolation Forest only | 3% | 14% | 15% | 17% | 0% | 52% |
| baseline: Mahalanobis distance only | 44% | 98% | 90% | 74% | 0% | 58% |
| (faults injected) | 927 | 927 | 927 | 927 | 927 | 862 |
| AtmosGuard: median minutes to the alarm | 240 | 0 | 0 | 300 | 0 | 780 |

#### 1d. How sure are the detection numbers? (AtmosGuard full, paired criterion, Wilson 95 % interval)

Faults are injected at random places; each row's interval says how much the percentage could move with another draw of the same size. Faults of one type overlap little but are not fully independent, so read the interval as a guide, not a guarantee.

| fault type | injected | raised the alarm (fault-raised) | named FAULT |
|---|---|---|---|
| frozen | 927 | 100.0% (99.6-100.0) | 93.2% (91.4-94.7) |
| spike | 927 | 89.1% (86.9-91.0) | 13.3% (11.2-15.6) |
| level shift | 927 | 90.8% (88.8-92.5) | 13.4% (11.3-15.7) |
| noise burst | 927 | 83.3% (80.7-85.5) | 13.1% (11.0-15.4) |
| dropout | 927 | 93.1% (91.3-94.6) | 93.1% (91.3-94.6) |
| clock 3 h out | 862 | 90.4% (88.2-92.2) | 0.9% (0.5-1.8) |

#### 1c. How AtmosGuard names what it detects, and the WEATHER-masking check

A FAULT verdict names the problem; SUSPECT asks for review. The last row is the risk of the coherent-level WEATHER route: a fault that was not alarmed but made samples look like real weather.

| AtmosGuard, injected faults | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| raised an alarm (FAULT or SUSPECT) | 100% | 89% | 91% | 83% | 93% | 90% |
| of which named FAULT | 93% | 13% | 13% | 13% | 93% | 1% |
| missed, but made some samples look like WEATHER | 0% | 3% | 3% | 3% | 0% | 3% |

#### The two Amendment 3 remedies, judged by the decision rule registered before the run

Remedy 3 (expected-change-aware step rule): adopt only if the windows with a FAULT are fewer than with `full`, the FAULT share does not rise, no fault type loses more than 2 points and clean false alarms rise by at most 0.2 points. Remedy 4 (sustained one-channel offset): adopt only if the windows with a FAULT and the FAULT share do not rise, no type loses more than 2 points, clean false alarms rise by at most 0.5 points, level-shift detection gains at least 5 points and the SUSPECT share in real extreme weather rises by at most 2 points. Compared with `full` (the shipped pipeline before this amendment) on the same stations.

| configuration | windows with a FAULT (full / this) | FAULT share of extreme-weather samples (full / this) | worst change in paired detection | level-shift detection change | change in clean false alarms | SUSPECT share in extreme weather (change) | remedy 3 rule (a: fewer FAULT windows, b, c) | remedy 4 rule (a, b, c 0.5 pp, d +5 pp level shift, e) | adopt |
|---|---|---|---|---|---|---|---|---|---|
| AtmosGuard + remedy 3 (expected-change-aware step rule) | 4 / 1 of 134 | 0.03% / 0.01% | none | +0.0 pp | -0.02 pp | -0.10 pp | pass | FAIL | yes |
| AtmosGuard + remedy 4 (sustained one-channel offset) | 4 / 3 of 134 | 0.03% / 0.02% | -0.2 pp (spike) | +1.0 pp | +0.48 pp | +1.35 pp | FAIL | FAIL | no |
| AtmosGuard + remedies 3 and 4 | 4 / 1 of 134 | 0.03% / 0.01% | -0.2 pp (spike) | +1.0 pp | +0.46 pp | +1.25 pp | FAIL | FAIL | no |

#### 2. False alarms on clean real data

No fault injected. Extreme-weather windows and NOAA-flagged values removed.

| configuration | any alarm | FAULT only | WEATHER verdicts | samples |
|---|---|---|---|---|
| AtmosGuard (full) | 9.3% | 0.0% | 1.9% | 453323 |
| AtmosGuard as registered (every remedy off) | 9.3% | 0.0% | 1.9% | 453323 |
| AtmosGuard + remedy 3 (expected-change-aware step rule) | 9.2% | 0.0% | 1.9% | 453323 |
| AtmosGuard + remedy 4 (sustained one-channel offset) | 9.7% | 0.0% | 2.1% | 453323 |
| AtmosGuard + remedies 3 and 4 | 9.7% | 0.0% | 2.1% | 453323 |
| baseline: range check only | 0.0% | 0.0% | - | 453323 |
| baseline: textbook range + step + persistence | 3.2% | 3.2% | - | 453323 |
| baseline: climatology z-score only | 0.9% | 0.0% | - | 453323 |
| baseline: Isolation Forest only | 0.6% | 0.0% | - | 453323 |
| baseline: Mahalanobis distance only | 0.6% | 0.0% | - | 453323 |

#### 3. Real extreme weather (nothing injected)

A FAULT here is a failure: real weather called a broken sensor. WEATHER is the escalated, correct verdict.

| configuration | FAULT | SUSPECT | WEATHER | VALID | windows with a FAULT |
|---|---|---|---|---|---|
| AtmosGuard (full) | 0.0% | 14.1% | 4.1% | 81.8% | 4/134 |
| AtmosGuard as registered (every remedy off) | 0.0% | 14.1% | 4.1% | 81.8% | 4/134 |
| AtmosGuard + remedy 3 (expected-change-aware step rule) | 0.0% | 14.0% | 4.2% | 81.8% | 1/134 |
| AtmosGuard + remedy 4 (sustained one-channel offset) | 0.0% | 15.4% | 4.7% | 79.9% | 3/134 |
| AtmosGuard + remedies 3 and 4 | 0.0% | 15.3% | 4.7% | 79.9% | 1/134 |
| baseline: range check only | 0.0% | 0.0% | - | 100.0% | 0/134 |
| baseline: textbook range + step + persistence | 3.9% | 0.0% | - | 96.1% | 100/134 |
| baseline: climatology z-score only | 0.0% | 2.2% | - | 97.8% | 0/134 |
| baseline: Isolation Forest only | 0.0% | 2.3% | - | 97.7% | 0/134 |
| baseline: Mahalanobis distance only | 0.0% | 2.3% | - | 97.7% | 0/134 |

Full pipeline, by kind of extreme weather:

| kind of extreme weather | samples | FAULT | SUSPECT | WEATHER | windows with a FAULT |
|---|---|---|---|---|---|
| cold | 2824 | 0.0% | 12.9% | 2.9% | 0/21 |
| heat | 2216 | 0.0% | 12.4% | 2.8% | 0/18 |
| low | 4342 | 0.0% | 15.0% | 5.6% | 2/35 |
| sharp | 5350 | 0.0% | 14.7% | 4.1% | 2/60 |

#### 4. Agreement with NOAA's own quality flags

NOAA's flags come from another automated system. Agreement means consistency with existing practice, not proof of real-world accuracy.

| measure | value |
|---|---|
| NOAA-flagged values (suspect or erroneous) | 708 |
|   of which erroneous | 0 |
| AtmosGuard alarmed (FAULT or SUSPECT) on flagged values | 43.1% |
| AtmosGuard escalated at all (also WEATHER) on flagged values | 67.8% |
| AtmosGuard alarmed on erroneous values | n/a |
| values NOAA did not flag | 467945 |
| AtmosGuard alarmed on those (extra flags) | 9.5% |
| AtmosGuard escalated at all on those | 11.5% |

#### 5. Slow drift, judged by the health monitor

A ramp over 45 days is added to one channel of clean real data. Severity = offset at the end of the ramp in multiples of the service limit (T 0.5 C, P 1 hPa, RH 3 %). One station, no reference: small drifts cannot be told from weather.

| drift at end of ramp | temperature | pressure | humidity |
|---|---|---|---|
| none (false claims) | 6.1% of 82 chunks | 4.9% of 82 chunks | 8.5% of 82 chunks |
| 1x service limit | 5% of 82 (day 33, 2.5x at detection) | 4% of 82 (day 175, 3.3x at detection) | 6% of 82 (day 172, 4.8x at detection) |
| 2x service limit | 11% of 82 (day 51, 3.1x at detection) | 5% of 82 (day 121, 4.0x at detection) | 7% of 82 (day 107, 5.0x at detection) |
| 4x service limit | 26% of 82 (day 47, 4.2x at detection) | 12% of 82 (day 54, 4.2x at detection) | 24% of 82 (day 55, 5.7x at detection) |
| 8x service limit | 57% of 82 (day 41, 6.0x at detection) | 38% of 82 (day 50, 5.3x at detection) | 56% of 82 (day 43, 7.5x at detection) |

#### By station (full pipeline)

Each station judged on its own record.

| station | cadence (min) | clean any alarm | clean FAULT | extreme weather FAULT | windows with a FAULT | extreme weather WEATHER | injected faults detected |
|---|---|---|---|---|---|---|---|
| HYD | 60 | 1.8% | 0.0% | 0.0% | 0/10 | 5.8% | 93% |
| BLR | 60 | 5.5% | 0.0% | 0.0% | 0/5 | 3.0% | 94% |
| CCJ | 60 | 2.3% | 0.0% | 0.0% | 0/7 | 6.6% | 97% |
| IXM | 60 | 2.6% | 0.0% | 0.0% | 0/7 | 5.9% | 96% |
| VGA | 60 | 3.6% | 0.0% | 0.0% | 0/13 | 12.4% | 93% |
| CWS | 60 | 25.5% | 0.0% | 0.0% | 0/10 | 4.3% | 92% |
| LEI | 60 | 21.1% | 0.0% | 0.0% | 0/16 | 2.5% | 91% |
| WIL | 60 | 8.3% | 0.0% | 0.0% | 0/15 | 3.2% | 94% |
| GLS | 60 | 1.9% | 0.0% | 0.2% | 2/11 | 3.2% | 88% |
| COT | 60 | 0.9% | 0.0% | 0.0% | 0/13 | 5.6% | 87% |
| THB | 60 | 2.1% | 0.2% | 0.1% | 2/15 | 1.5% | 87% |
| MTC | 60 | 32.7% | 0.0% | 0.0% | 0/12 | 0.5% | 88% |

#### 1b. The same, by the criterion registered in the protocol (any alarm in the window)

Background false alarms (about 2 % of samples) also fall inside long fault windows, so this flatters long faults (frozen 48 h, clock shift 4 days) and every system, baselines included. Kept because it was registered before the holdout.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 96% | 92% | 86% | 100% | 90% |
| AtmosGuard as registered (every remedy off) | 100% | 96% | 92% | 86% | 100% | 90% |
| AtmosGuard + remedy 3 (expected-change-aware step rule) | 100% | 96% | 92% | 86% | 100% | 90% |
| AtmosGuard + remedy 4 (sustained one-channel offset) | 100% | 96% | 93% | 86% | 100% | 91% |
| AtmosGuard + remedies 3 and 4 | 100% | 96% | 93% | 86% | 100% | 91% |
| baseline: range check only | 0% | 13% | 14% | 13% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 77% | 88% | 74% | 4% | 66% |
| baseline: climatology z-score only | 22% | 36% | 36% | 16% | 1% | 46% |
| baseline: Isolation Forest only | 9% | 15% | 22% | 23% | 0% | 52% |
| baseline: Mahalanobis distance only | 50% | 98% | 91% | 76% | 0% | 58% |
| (faults injected) | 927 | 927 | 927 | 927 | 927 | 862 |
| AtmosGuard: median minutes to the alarm | 180 | 0 | 0 | 240 | 0 | 660 |

#### No single simpler system is good at every fault type

Each system's weakest fault type from table 1, beside its false-alarm rate and its record on real extreme weather. A system that is best at one fault type is blind to another; the layers exist for coverage, and the WEATHER verdict exists so that coverage does not cost real storms.

| system | weakest injected-fault type (fault raised the alarm) | false alarms on clean data | real extreme weather, windows with a FAULT |
|---|---|---|---|
| AtmosGuard (full) | noise burst: 83% | 9.3% | 4/134 |
| AtmosGuard as registered (every remedy off) | noise burst: 83% | 9.3% | 4/134 |
| AtmosGuard + remedy 3 (expected-change-aware step rule) | noise burst: 83% | 9.2% | 1/134 |
| AtmosGuard + remedy 4 (sustained one-channel offset) | noise burst: 83% | 9.7% | 3/134 |
| AtmosGuard + remedies 3 and 4 | noise burst: 83% | 9.7% | 1/134 |
| baseline: range check only | frozen: 0% | 0.0% | 0/134 |
| baseline: textbook range + step + persistence | dropout: 0% | 3.2% | 100/134 |
| baseline: climatology z-score only | dropout: 0% | 0.9% | 0/134 |
| baseline: Isolation Forest only | dropout: 0% | 0.6% | 0/134 |
| baseline: Mahalanobis distance only | dropout: 0% | 0.6% | 0/134 |

### 4.6 FRESH2, the five Indian airport stations only

*Subset of FRESH2: hourly METAR at whole-degree resolution.* Stations: HYD, BLR, CCJ, IXM, VGA.

#### Headline

Five separate numbers. They are never merged.

| question | answer |
|---|---|
| False alarms on clean real data (nothing injected) | 3.2% (3.1-3.3) of 189591 samples got FAULT or SUSPECT; 0.0% (0.0-0.0) got FAULT |
| What happens to real extreme weather (cyclones, heat, cold, sharp fronts; nothing injected) | FAULT on 0.0% (0.0-0.1) of 3994 samples (0 of 42 windows); WEATHER on 7.3%, SUSPECT on 4.7% |
| Injected faults whose alarm the fault raised (each type on its own; injected, not real) | frozen 100%; spike 93%; level shift 95%; noise burst 83%; dropout 98%; clock 3 h out 99% |
| Agreement with NOAA's own quality flags (another automated system, not ground truth) | escalated (FAULT, SUSPECT or WEATHER) on 68.0% of 206 NOAA-flagged values (FAULT or SUSPECT alone: 29.6%); escalated on 6.5% of the 193607 values NOAA left alone |
| Slow drift (health monitor, single station, no reference) | false drift claims on 0.8% of 7580 station-days; an injected ramp reaching 8x the service limit was found in 70% of trials |

#### 1. Detection of injected faults, by type (the fault raised the alarm)

Alarm = FAULT or SUSPECT on a sample that was NOT an alarm on the same series without the fault (paired), from the first faulty sample to the last plus 60 minutes. The faults are injected, not real. Ablation rows switch one layer off; baseline rows are simpler systems on the same data.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 93% | 95% | 83% | 98% | 99% |
| AtmosGuard as registered (every remedy off) | 100% | 93% | 95% | 83% | 98% | 99% |
| AtmosGuard + remedy 3 (expected-change-aware step rule) | 100% | 93% | 95% | 83% | 98% | 99% |
| AtmosGuard + remedy 4 (sustained one-channel offset) | 100% | 93% | 95% | 83% | 97% | 99% |
| AtmosGuard + remedies 3 and 4 | 100% | 93% | 95% | 83% | 97% | 99% |
| baseline: range check only | 0% | 15% | 16% | 16% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 76% | 86% | 73% | 0% | 90% |
| baseline: climatology z-score only | 39% | 62% | 58% | 17% | 0% | 80% |
| baseline: Isolation Forest only | 2% | 14% | 16% | 17% | 0% | 67% |
| baseline: Mahalanobis distance only | 39% | 100% | 94% | 66% | 0% | 57% |
| (faults injected) | 306 | 306 | 306 | 306 | 306 | 303 |
| AtmosGuard: median minutes to the alarm | 360 | 0 | 0 | 480 | 0 | 810 |

#### 1d. How sure are the detection numbers? (AtmosGuard full, paired criterion, Wilson 95 % interval)

Faults are injected at random places; each row's interval says how much the percentage could move with another draw of the same size. Faults of one type overlap little but are not fully independent, so read the interval as a guide, not a guarantee.

| fault type | injected | raised the alarm (fault-raised) | named FAULT |
|---|---|---|---|
| frozen | 306 | 100.0% (98.8-100.0) | 84.6% (80.2-88.2) |
| spike | 306 | 93.1% (89.7-95.5) | 15.7% (12.0-20.2) |
| level shift | 306 | 94.8% (91.7-96.8) | 15.7% (12.0-20.2) |
| noise burst | 306 | 82.7% (78.0-86.5) | 15.7% (12.0-20.2) |
| dropout | 306 | 97.7% (95.4-98.9) | 97.7% (95.4-98.9) |
| clock 3 h out | 303 | 99.0% (97.1-99.7) | 0.0% (0.0-1.3) |

#### 1c. How AtmosGuard names what it detects, and the WEATHER-masking check

A FAULT verdict names the problem; SUSPECT asks for review. The last row is the risk of the coherent-level WEATHER route: a fault that was not alarmed but made samples look like real weather.

| AtmosGuard, injected faults | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| raised an alarm (FAULT or SUSPECT) | 100% | 93% | 95% | 83% | 98% | 99% |
| of which named FAULT | 85% | 16% | 16% | 16% | 98% | 0% |
| missed, but made some samples look like WEATHER | 0% | 6% | 3% | 5% | 0% | 1% |

#### The two Amendment 3 remedies, judged by the decision rule registered before the run

Remedy 3 (expected-change-aware step rule): adopt only if the windows with a FAULT are fewer than with `full`, the FAULT share does not rise, no fault type loses more than 2 points and clean false alarms rise by at most 0.2 points. Remedy 4 (sustained one-channel offset): adopt only if the windows with a FAULT and the FAULT share do not rise, no type loses more than 2 points, clean false alarms rise by at most 0.5 points, level-shift detection gains at least 5 points and the SUSPECT share in real extreme weather rises by at most 2 points. Compared with `full` (the shipped pipeline before this amendment) on the same stations.

| configuration | windows with a FAULT (full / this) | FAULT share of extreme-weather samples (full / this) | worst change in paired detection | level-shift detection change | change in clean false alarms | SUSPECT share in extreme weather (change) | remedy 3 rule (a: fewer FAULT windows, b, c) | remedy 4 rule (a, b, c 0.5 pp, d +5 pp level shift, e) | adopt |
|---|---|---|---|---|---|---|---|---|---|
| AtmosGuard + remedy 3 (expected-change-aware step rule) | 0 / 0 of 42 | 0.00% / 0.00% | none | +0.0 pp | -0.02 pp | -0.28 pp | FAIL | FAIL | no |
| AtmosGuard + remedy 4 (sustained one-channel offset) | 0 / 0 of 42 | 0.00% / 0.00% | -0.3 pp (dropout) | +0.7 pp | +0.79 pp | +1.78 pp | FAIL | FAIL | no |
| AtmosGuard + remedies 3 and 4 | 0 / 0 of 42 | 0.00% / 0.00% | -0.3 pp (dropout) | +0.7 pp | +0.77 pp | +1.50 pp | FAIL | FAIL | no |

#### 2. False alarms on clean real data

No fault injected. Extreme-weather windows and NOAA-flagged values removed.

| configuration | any alarm | FAULT only | WEATHER verdicts | samples |
|---|---|---|---|---|
| AtmosGuard (full) | 3.2% | 0.0% | 3.2% | 189591 |
| AtmosGuard as registered (every remedy off) | 3.2% | 0.0% | 3.2% | 189591 |
| AtmosGuard + remedy 3 (expected-change-aware step rule) | 3.2% | 0.0% | 3.2% | 189591 |
| AtmosGuard + remedy 4 (sustained one-channel offset) | 4.0% | 0.0% | 3.5% | 189591 |
| AtmosGuard + remedies 3 and 4 | 4.0% | 0.0% | 3.6% | 189591 |
| baseline: range check only | 0.0% | 0.0% | - | 189591 |
| baseline: textbook range + step + persistence | 5.0% | 5.0% | - | 189591 |
| baseline: climatology z-score only | 1.6% | 0.0% | - | 189591 |
| baseline: Isolation Forest only | 0.4% | 0.0% | - | 189591 |
| baseline: Mahalanobis distance only | 0.4% | 0.0% | - | 189591 |

#### 3. Real extreme weather (nothing injected)

A FAULT here is a failure: real weather called a broken sensor. WEATHER is the escalated, correct verdict.

| configuration | FAULT | SUSPECT | WEATHER | VALID | windows with a FAULT |
|---|---|---|---|---|---|
| AtmosGuard (full) | 0.0% | 4.7% | 7.3% | 88.0% | 0/42 |
| AtmosGuard as registered (every remedy off) | 0.0% | 4.7% | 7.3% | 88.0% | 0/42 |
| AtmosGuard + remedy 3 (expected-change-aware step rule) | 0.0% | 4.4% | 7.5% | 88.1% | 0/42 |
| AtmosGuard + remedy 4 (sustained one-channel offset) | 0.0% | 6.5% | 8.6% | 84.9% | 0/42 |
| AtmosGuard + remedies 3 and 4 | 0.0% | 6.2% | 8.8% | 85.0% | 0/42 |
| baseline: range check only | 0.0% | 0.0% | - | 100.0% | 0/42 |
| baseline: textbook range + step + persistence | 4.1% | 0.0% | - | 95.9% | 38/42 |
| baseline: climatology z-score only | 0.0% | 2.7% | - | 97.3% | 0/42 |
| baseline: Isolation Forest only | 0.0% | 2.2% | - | 97.8% | 0/42 |
| baseline: Mahalanobis distance only | 0.0% | 1.5% | - | 98.5% | 0/42 |

Full pipeline, by kind of extreme weather:

| kind of extreme weather | samples | FAULT | SUSPECT | WEATHER | windows with a FAULT |
|---|---|---|---|---|---|
| cold | 756 | 0.0% | 4.0% | 3.4% | 0/6 |
| heat | 403 | 0.0% | 1.7% | 3.5% | 0/4 |
| low | 724 | 0.0% | 8.8% | 14.2% | 0/7 |
| sharp | 2111 | 0.0% | 4.1% | 7.0% | 0/25 |

#### 4. Agreement with NOAA's own quality flags

NOAA's flags come from another automated system. Agreement means consistency with existing practice, not proof of real-world accuracy.

| measure | value |
|---|---|
| NOAA-flagged values (suspect or erroneous) | 206 |
|   of which erroneous | 0 |
| AtmosGuard alarmed (FAULT or SUSPECT) on flagged values | 29.6% |
| AtmosGuard escalated at all (also WEATHER) on flagged values | 68.0% |
| AtmosGuard alarmed on erroneous values | n/a |
| values NOAA did not flag | 193607 |
| AtmosGuard alarmed on those (extra flags) | 3.3% |
| AtmosGuard escalated at all on those | 6.5% |

#### 5. Slow drift, judged by the health monitor

A ramp over 45 days is added to one channel of clean real data. Severity = offset at the end of the ramp in multiples of the service limit (T 0.5 C, P 1 hPa, RH 3 %). One station, no reference: small drifts cannot be told from weather.

| drift at end of ramp | temperature | pressure | humidity |
|---|---|---|---|
| none (false claims) | 13.3% of 30 chunks | 10.0% of 30 chunks | 20.0% of 30 chunks |
| 1x service limit | 3% of 30 (day 31, 1.6x at detection) | 10% of 30 (day 175, 3.3x at detection) | 13% of 30 (day 101, 4.3x at detection) |
| 2x service limit | 13% of 30 (day 51, 1.7x at detection) | 10% of 30 (day 175, 4.2x at detection) | 13% of 30 (day 99, 5.0x at detection) |
| 4x service limit | 30% of 30 (day 46, 3.3x at detection) | 27% of 30 (day 56, 4.7x at detection) | 37% of 30 (day 59, 5.8x at detection) |
| 8x service limit | 77% of 30 (day 44, 6.8x at detection) | 67% of 30 (day 58, 5.2x at detection) | 67% of 30 (day 45, 7.5x at detection) |

#### By station (full pipeline)

Each station judged on its own record.

| station | cadence (min) | clean any alarm | clean FAULT | extreme weather FAULT | windows with a FAULT | extreme weather WEATHER | injected faults detected |
|---|---|---|---|---|---|---|---|
| HYD | 60 | 1.8% | 0.0% | 0.0% | 0/10 | 5.8% | 93% |
| BLR | 60 | 5.5% | 0.0% | 0.0% | 0/5 | 3.0% | 94% |
| CCJ | 60 | 2.3% | 0.0% | 0.0% | 0/7 | 6.6% | 97% |
| IXM | 60 | 2.6% | 0.0% | 0.0% | 0/7 | 5.9% | 96% |
| VGA | 60 | 3.6% | 0.0% | 0.0% | 0/13 | 12.4% | 93% |

#### 1b. The same, by the criterion registered in the protocol (any alarm in the window)

Background false alarms (about 2 % of samples) also fall inside long fault windows, so this flatters long faults (frozen 48 h, clock shift 4 days) and every system, baselines included. Kept because it was registered before the holdout.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 95% | 95% | 87% | 100% | 99% |
| AtmosGuard as registered (every remedy off) | 100% | 95% | 95% | 87% | 100% | 99% |
| AtmosGuard + remedy 3 (expected-change-aware step rule) | 100% | 95% | 95% | 87% | 100% | 99% |
| AtmosGuard + remedy 4 (sustained one-channel offset) | 100% | 95% | 96% | 87% | 100% | 99% |
| AtmosGuard + remedies 3 and 4 | 100% | 95% | 96% | 87% | 100% | 99% |
| baseline: range check only | 0% | 15% | 16% | 16% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 79% | 92% | 81% | 8% | 91% |
| baseline: climatology z-score only | 45% | 63% | 59% | 28% | 2% | 80% |
| baseline: Isolation Forest only | 8% | 15% | 21% | 23% | 0% | 67% |
| baseline: Mahalanobis distance only | 45% | 100% | 94% | 67% | 0% | 57% |
| (faults injected) | 306 | 306 | 306 | 306 | 306 | 303 |
| AtmosGuard: median minutes to the alarm | 300 | 0 | 0 | 360 | 0 | 780 |

#### No single simpler system is good at every fault type

Each system's weakest fault type from table 1, beside its false-alarm rate and its record on real extreme weather. A system that is best at one fault type is blind to another; the layers exist for coverage, and the WEATHER verdict exists so that coverage does not cost real storms.

| system | weakest injected-fault type (fault raised the alarm) | false alarms on clean data | real extreme weather, windows with a FAULT |
|---|---|---|---|
| AtmosGuard (full) | noise burst: 83% | 3.2% | 0/42 |
| AtmosGuard as registered (every remedy off) | noise burst: 83% | 3.2% | 0/42 |
| AtmosGuard + remedy 3 (expected-change-aware step rule) | noise burst: 83% | 3.2% | 0/42 |
| AtmosGuard + remedy 4 (sustained one-channel offset) | noise burst: 83% | 4.0% | 0/42 |
| AtmosGuard + remedies 3 and 4 | noise burst: 83% | 4.0% | 0/42 |
| baseline: range check only | frozen: 0% | 0.0% | 0/42 |
| baseline: textbook range + step + persistence | dropout: 0% | 5.0% | 38/42 |
| baseline: climatology z-score only | dropout: 0% | 1.6% | 0/42 |
| baseline: Isolation Forest only | dropout: 0% | 0.4% | 0/42 |
| baseline: Mahalanobis distance only | dropout: 0% | 0.4% | 0/42 |

### 4.7 FRESH2, the seven Australian automatic weather stations only

*Subset of FRESH2: hourly SYNOP from Bureau of Meteorology AWS at 0.1 C and 0.1 hPa, including two Coral Sea cyclone-track islands.* Stations: CWS, LEI, WIL, GLS, COT, THB, MTC.

#### Headline

Five separate numbers. They are never merged.

| question | answer |
|---|---|
| False alarms on clean real data (nothing injected) | 13.6% (13.5-13.7) of 263732 samples got FAULT or SUSPECT; 0.0% (0.0-0.0) got FAULT |
| What happens to real extreme weather (cyclones, heat, cold, sharp fronts; nothing injected) | FAULT on 0.0% (0.0-0.1) of 10738 samples (4 of 92 windows); WEATHER on 3.0%, SUSPECT on 17.6% |
| Injected faults whose alarm the fault raised (each type on its own; injected, not real) | frozen 100%; spike 87%; level shift 89%; noise burst 84%; dropout 91%; clock 3 h out 86% |
| Agreement with NOAA's own quality flags (another automated system, not ground truth) | escalated (FAULT, SUSPECT or WEATHER) on 67.7% of 502 NOAA-flagged values (FAULT or SUSPECT alone: 48.6%); escalated on 14.9% of the 274338 values NOAA left alone |
| Slow drift (health monitor, single station, no reference) | false drift claims on 0.2% of 10339 station-days; an injected ramp reaching 8x the service limit was found in 39% of trials |

#### 1. Detection of injected faults, by type (the fault raised the alarm)

Alarm = FAULT or SUSPECT on a sample that was NOT an alarm on the same series without the fault (paired), from the first faulty sample to the last plus 60 minutes. The faults are injected, not real. Ablation rows switch one layer off; baseline rows are simpler systems on the same data.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 87% | 89% | 84% | 91% | 86% |
| AtmosGuard as registered (every remedy off) | 100% | 87% | 89% | 84% | 91% | 86% |
| AtmosGuard + remedy 3 (expected-change-aware step rule) | 100% | 87% | 89% | 84% | 91% | 86% |
| AtmosGuard + remedy 4 (sustained one-channel offset) | 100% | 87% | 90% | 83% | 91% | 86% |
| AtmosGuard + remedies 3 and 4 | 100% | 87% | 90% | 83% | 91% | 86% |
| baseline: range check only | 0% | 12% | 13% | 12% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 75% | 83% | 63% | 0% | 52% |
| baseline: climatology z-score only | 5% | 21% | 22% | 8% | 0% | 28% |
| baseline: Isolation Forest only | 3% | 14% | 15% | 17% | 0% | 43% |
| baseline: Mahalanobis distance only | 47% | 98% | 89% | 78% | 0% | 58% |
| (faults injected) | 621 | 621 | 621 | 621 | 621 | 559 |
| AtmosGuard: median minutes to the alarm | 180 | 0 | 0 | 240 | 0 | 780 |

#### 1d. How sure are the detection numbers? (AtmosGuard full, paired criterion, Wilson 95 % interval)

Faults are injected at random places; each row's interval says how much the percentage could move with another draw of the same size. Faults of one type overlap little but are not fully independent, so read the interval as a guide, not a guarantee.

| fault type | injected | raised the alarm (fault-raised) | named FAULT |
|---|---|---|---|
| frozen | 621 | 100.0% (99.4-100.0) | 97.4% (95.9-98.4) |
| spike | 621 | 87.1% (84.3-89.5) | 12.1% (9.7-14.9) |
| level shift | 621 | 88.9% (86.2-91.1) | 12.2% (9.9-15.1) |
| noise burst | 621 | 83.6% (80.5-86.3) | 11.8% (9.5-14.5) |
| dropout | 621 | 90.8% (88.3-92.8) | 90.8% (88.3-92.8) |
| clock 3 h out | 559 | 85.7% (82.5-88.3) | 1.4% (0.7-2.8) |

#### 1c. How AtmosGuard names what it detects, and the WEATHER-masking check

A FAULT verdict names the problem; SUSPECT asks for review. The last row is the risk of the coherent-level WEATHER route: a fault that was not alarmed but made samples look like real weather.

| AtmosGuard, injected faults | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| raised an alarm (FAULT or SUSPECT) | 100% | 87% | 89% | 84% | 91% | 86% |
| of which named FAULT | 97% | 12% | 12% | 12% | 91% | 1% |
| missed, but made some samples look like WEATHER | 0% | 1% | 3% | 3% | 0% | 4% |

#### The two Amendment 3 remedies, judged by the decision rule registered before the run

Remedy 3 (expected-change-aware step rule): adopt only if the windows with a FAULT are fewer than with `full`, the FAULT share does not rise, no fault type loses more than 2 points and clean false alarms rise by at most 0.2 points. Remedy 4 (sustained one-channel offset): adopt only if the windows with a FAULT and the FAULT share do not rise, no type loses more than 2 points, clean false alarms rise by at most 0.5 points, level-shift detection gains at least 5 points and the SUSPECT share in real extreme weather rises by at most 2 points. Compared with `full` (the shipped pipeline before this amendment) on the same stations.

| configuration | windows with a FAULT (full / this) | FAULT share of extreme-weather samples (full / this) | worst change in paired detection | level-shift detection change | change in clean false alarms | SUSPECT share in extreme weather (change) | remedy 3 rule (a: fewer FAULT windows, b, c) | remedy 4 rule (a, b, c 0.5 pp, d +5 pp level shift, e) | adopt |
|---|---|---|---|---|---|---|---|---|---|
| AtmosGuard + remedy 3 (expected-change-aware step rule) | 4 / 1 of 92 | 0.04% / 0.01% | none | +0.0 pp | -0.02 pp | -0.04 pp | pass | FAIL | yes |
| AtmosGuard + remedy 4 (sustained one-channel offset) | 4 / 3 of 92 | 0.04% / 0.03% | -0.3 pp (spike) | +1.1 pp | +0.26 pp | +1.19 pp | FAIL | FAIL | no |
| AtmosGuard + remedies 3 and 4 | 4 / 1 of 92 | 0.04% / 0.01% | -0.3 pp (spike) | +1.1 pp | +0.24 pp | +1.15 pp | FAIL | FAIL | no |

#### 2. False alarms on clean real data

No fault injected. Extreme-weather windows and NOAA-flagged values removed.

| configuration | any alarm | FAULT only | WEATHER verdicts | samples |
|---|---|---|---|---|
| AtmosGuard (full) | 13.6% | 0.0% | 1.0% | 263732 |
| AtmosGuard as registered (every remedy off) | 13.6% | 0.1% | 1.0% | 263732 |
| AtmosGuard + remedy 3 (expected-change-aware step rule) | 13.6% | 0.0% | 1.0% | 263732 |
| AtmosGuard + remedy 4 (sustained one-channel offset) | 13.9% | 0.0% | 1.0% | 263732 |
| AtmosGuard + remedies 3 and 4 | 13.9% | 0.0% | 1.0% | 263732 |
| baseline: range check only | 0.0% | 0.0% | - | 263732 |
| baseline: textbook range + step + persistence | 1.9% | 1.9% | - | 263732 |
| baseline: climatology z-score only | 0.4% | 0.0% | - | 263732 |
| baseline: Isolation Forest only | 0.7% | 0.0% | - | 263732 |
| baseline: Mahalanobis distance only | 0.7% | 0.0% | - | 263732 |

#### 3. Real extreme weather (nothing injected)

A FAULT here is a failure: real weather called a broken sensor. WEATHER is the escalated, correct verdict.

| configuration | FAULT | SUSPECT | WEATHER | VALID | windows with a FAULT |
|---|---|---|---|---|---|
| AtmosGuard (full) | 0.0% | 17.6% | 3.0% | 79.4% | 4/92 |
| AtmosGuard as registered (every remedy off) | 0.0% | 17.6% | 2.9% | 79.4% | 4/92 |
| AtmosGuard + remedy 3 (expected-change-aware step rule) | 0.0% | 17.5% | 3.0% | 79.5% | 1/92 |
| AtmosGuard + remedy 4 (sustained one-channel offset) | 0.0% | 18.8% | 3.2% | 78.0% | 3/92 |
| AtmosGuard + remedies 3 and 4 | 0.0% | 18.7% | 3.2% | 78.1% | 1/92 |
| baseline: range check only | 0.0% | 0.0% | - | 100.0% | 0/92 |
| baseline: textbook range + step + persistence | 3.8% | 0.0% | - | 96.2% | 62/92 |
| baseline: climatology z-score only | 0.0% | 2.1% | - | 97.9% | 0/92 |
| baseline: Isolation Forest only | 0.0% | 2.4% | - | 97.6% | 0/92 |
| baseline: Mahalanobis distance only | 0.0% | 2.7% | - | 97.3% | 0/92 |

Full pipeline, by kind of extreme weather:

| kind of extreme weather | samples | FAULT | SUSPECT | WEATHER | windows with a FAULT |
|---|---|---|---|---|---|
| cold | 2068 | 0.0% | 16.1% | 2.8% | 0/15 |
| heat | 1813 | 0.0% | 14.8% | 2.7% | 0/14 |
| low | 3618 | 0.1% | 16.3% | 3.8% | 2/28 |
| sharp | 3239 | 0.1% | 21.5% | 2.3% | 2/35 |

#### 4. Agreement with NOAA's own quality flags

NOAA's flags come from another automated system. Agreement means consistency with existing practice, not proof of real-world accuracy.

| measure | value |
|---|---|
| NOAA-flagged values (suspect or erroneous) | 502 |
|   of which erroneous | 0 |
| AtmosGuard alarmed (FAULT or SUSPECT) on flagged values | 48.6% |
| AtmosGuard escalated at all (also WEATHER) on flagged values | 67.7% |
| AtmosGuard alarmed on erroneous values | n/a |
| values NOAA did not flag | 274338 |
| AtmosGuard alarmed on those (extra flags) | 13.9% |
| AtmosGuard escalated at all on those | 14.9% |

#### 5. Slow drift, judged by the health monitor

A ramp over 45 days is added to one channel of clean real data. Severity = offset at the end of the ramp in multiples of the service limit (T 0.5 C, P 1 hPa, RH 3 %). One station, no reference: small drifts cannot be told from weather.

| drift at end of ramp | temperature | pressure | humidity |
|---|---|---|---|
| none (false claims) | 1.9% of 52 chunks | 1.9% of 52 chunks | 1.9% of 52 chunks |
| 1x service limit | 6% of 52 (day 36, 3.3x at detection) | 0% of 52 (-, - at detection) | 2% of 52 (day 211, 5.3x at detection) |
| 2x service limit | 10% of 52 (day 48, 4.0x at detection) | 2% of 52 (day 66, 3.3x at detection) | 4% of 52 (day 126, 5.4x at detection) |
| 4x service limit | 23% of 52 (day 48, 4.8x at detection) | 4% of 52 (day 54, 3.9x at detection) | 17% of 52 (day 49, 5.7x at detection) |
| 8x service limit | 46% of 52 (day 39, 5.9x at detection) | 21% of 52 (day 41, 5.4x at detection) | 50% of 52 (day 43, 7.6x at detection) |

#### By station (full pipeline)

Each station judged on its own record.

| station | cadence (min) | clean any alarm | clean FAULT | extreme weather FAULT | windows with a FAULT | extreme weather WEATHER | injected faults detected |
|---|---|---|---|---|---|---|---|
| CWS | 60 | 25.5% | 0.0% | 0.0% | 0/10 | 4.3% | 92% |
| LEI | 60 | 21.1% | 0.0% | 0.0% | 0/16 | 2.5% | 91% |
| WIL | 60 | 8.3% | 0.0% | 0.0% | 0/15 | 3.2% | 94% |
| GLS | 60 | 1.9% | 0.0% | 0.2% | 2/11 | 3.2% | 88% |
| COT | 60 | 0.9% | 0.0% | 0.0% | 0/13 | 5.6% | 87% |
| THB | 60 | 2.1% | 0.2% | 0.1% | 2/15 | 1.5% | 87% |
| MTC | 60 | 32.7% | 0.0% | 0.0% | 0/12 | 0.5% | 88% |

#### 1b. The same, by the criterion registered in the protocol (any alarm in the window)

Background false alarms (about 2 % of samples) also fall inside long fault windows, so this flatters long faults (frozen 48 h, clock shift 4 days) and every system, baselines included. Kept because it was registered before the holdout.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 97% | 91% | 86% | 100% | 86% |
| AtmosGuard as registered (every remedy off) | 100% | 97% | 91% | 86% | 100% | 86% |
| AtmosGuard + remedy 3 (expected-change-aware step rule) | 100% | 97% | 91% | 86% | 100% | 86% |
| AtmosGuard + remedy 4 (sustained one-channel offset) | 100% | 97% | 92% | 86% | 100% | 87% |
| AtmosGuard + remedies 3 and 4 | 100% | 97% | 92% | 86% | 100% | 87% |
| baseline: range check only | 0% | 12% | 13% | 12% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 76% | 86% | 71% | 2% | 52% |
| baseline: climatology z-score only | 10% | 22% | 25% | 10% | 0% | 28% |
| baseline: Isolation Forest only | 10% | 15% | 22% | 23% | 0% | 44% |
| baseline: Mahalanobis distance only | 52% | 98% | 90% | 80% | 0% | 58% |
| (faults injected) | 621 | 621 | 621 | 621 | 621 | 559 |
| AtmosGuard: median minutes to the alarm | 180 | 0 | 0 | 180 | 0 | 540 |

#### No single simpler system is good at every fault type

Each system's weakest fault type from table 1, beside its false-alarm rate and its record on real extreme weather. A system that is best at one fault type is blind to another; the layers exist for coverage, and the WEATHER verdict exists so that coverage does not cost real storms.

| system | weakest injected-fault type (fault raised the alarm) | false alarms on clean data | real extreme weather, windows with a FAULT |
|---|---|---|---|
| AtmosGuard (full) | noise burst: 84% | 13.6% | 4/92 |
| AtmosGuard as registered (every remedy off) | noise burst: 84% | 13.6% | 4/92 |
| AtmosGuard + remedy 3 (expected-change-aware step rule) | noise burst: 84% | 13.6% | 1/92 |
| AtmosGuard + remedy 4 (sustained one-channel offset) | noise burst: 83% | 13.9% | 3/92 |
| AtmosGuard + remedies 3 and 4 | noise burst: 83% | 13.9% | 1/92 |
| baseline: range check only | frozen: 0% | 0.0% | 0/92 |
| baseline: textbook range + step + persistence | dropout: 0% | 1.9% | 62/92 |
| baseline: climatology z-score only | dropout: 0% | 0.4% | 0/92 |
| baseline: Isolation Forest only | dropout: 0% | 0.7% | 0/92 |
| baseline: Mahalanobis distance only | dropout: 0% | 0.7% | 0/92 |

### 4.8 FRESH3: a fourth set of twelve stations, 2020-2024

*Chosen and sealed before the Amendment 4 remedy was tested (config/protocol.md). Seven US automated stations reporting every 20 minutes at 0.1 C and five Australian automatic stations with irregular training years. `AtmosGuard (full)` is the pipeline as shipped.* Stations: FHB, PTT, MDS, LPO, GGW, GRC, HUT, WEI, TNC, ASP, LRM, BRM.

#### Headline

Five separate numbers. They are never merged.

| question | answer |
|---|---|
| False alarms on clean real data (nothing injected) | 9.7% (9.6-9.8) of 1026508 samples got FAULT or SUSPECT; 0.0% (0.0-0.0) got FAULT |
| What happens to real extreme weather (cyclones, heat, cold, sharp fronts; nothing injected) | FAULT on 0.1% (0.1-0.1) of 45332 samples (5 of 160 windows); WEATHER on 3.0%, SUSPECT on 12.8% |
| Injected faults whose alarm the fault raised (each type on its own; injected, not real) | frozen 100%; spike 84%; level shift 95%; noise burst 100%; dropout 88%; clock 3 h out 96% |
| Agreement with NOAA's own quality flags (another automated system, not ground truth) | escalated (FAULT, SUSPECT or WEATHER) on 59.9% of 845 NOAA-flagged values (FAULT or SUSPECT alone: 50.4%); escalated on 11.3% of the 1071872 values NOAA left alone |
| Slow drift (health monitor, single station, no reference) | false drift claims on 0.6% of 17824 station-days; an injected ramp reaching 8x the service limit was found in 27% of trials |

#### 1. Detection of injected faults, by type (the fault raised the alarm)

Alarm = FAULT or SUSPECT on a sample that was NOT an alarm on the same series without the fault (paired), from the first faulty sample to the last plus 60 minutes. The faults are injected, not real. Ablation rows switch one layer off; baseline rows are simpler systems on the same data.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 84% | 95% | 100% | 88% | 96% |
| AtmosGuard + remedy 6 (unlearned limits filled from the first regular stretch) | 100% | 97% | 93% | 94% | 99% | 95% |
| baseline: range check only | 0% | 14% | 13% | 16% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 90% | 92% | 87% | 0% | 94% |
| baseline: climatology z-score only | 11% | 10% | 14% | 5% | 0% | 38% |
| baseline: Isolation Forest only | 6% | 15% | 22% | 42% | 0% | 78% |
| baseline: Mahalanobis distance only | 66% | 100% | 98% | 92% | 0% | 85% |
| (faults injected) | 1143 | 1143 | 1143 | 1143 | 1143 | 967 |
| AtmosGuard: median minutes to the alarm | 280 | 0 | 0 | 100 | 0 | 420 |

#### 1d. How sure are the detection numbers? (AtmosGuard full, paired criterion, Wilson 95 % interval)

Faults are injected at random places; each row's interval says how much the percentage could move with another draw of the same size. Faults of one type overlap little but are not fully independent, so read the interval as a guide, not a guarantee.

| fault type | injected | raised the alarm (fault-raised) | named FAULT |
|---|---|---|---|
| frozen | 1143 | 100.0% (99.7-100.0) | 98.7% (97.8-99.2) |
| spike | 1143 | 84.0% (81.8-86.0) | 12.1% (10.3-14.1) |
| level shift | 1143 | 95.0% (93.6-96.1) | 12.6% (10.8-14.6) |
| noise burst | 1143 | 99.6% (99.0-99.8) | 15.6% (13.6-17.8) |
| dropout | 1143 | 88.2% (86.2-89.9) | 88.2% (86.2-89.9) |
| clock 3 h out | 967 | 96.2% (94.8-97.2) | 1.2% (0.7-2.2) |

#### 1c. How AtmosGuard names what it detects, and the WEATHER-masking check

A FAULT verdict names the problem; SUSPECT asks for review. The last row is the risk of the coherent-level WEATHER route: a fault that was not alarmed but made samples look like real weather.

| AtmosGuard, injected faults | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| raised an alarm (FAULT or SUSPECT) | 100% | 84% | 95% | 100% | 88% | 96% |
| of which named FAULT | 99% | 12% | 13% | 16% | 88% | 1% |
| missed, but made some samples look like WEATHER | 0% | 1% | 1% | 0% | 0% | 2% |

#### The Amendment 4 remedy (unlearned limits filled from the first regular stretch), judged by the rule registered before the run

Adopt only if (a) clean false alarms at the stations where the warm-up applied fall by at least 3 points, (b) no fault type loses more than 2 points, (c) real-weather windows with a FAULT and their share do not rise, (d) the SUSPECT share in real weather rises by at most 2 points. At those stations every configuration is judged only after the warm-up stretch.

| configuration | stations where the warm-up applied | (a) clean false alarms there (full / this) | (b) worst change in paired detection | (c) windows with a FAULT (full / this) | (d) SUSPECT share in real weather (change) | rule (a) | rule (b) | rule (c) | rule (d) | adopt |
|---|---|---|---|---|---|---|---|---|---|---|
| AtmosGuard + remedy 6 (unlearned limits filled from the first regular stretch) | WEI, TNC, ASP, LRM, BRM | 45.4% / 1.8% | -6.0 pp (noise burst) | 5 / 5 of 160 | -7.90 pp | pass | FAIL | pass | pass | no |

#### 2. False alarms on clean real data

No fault injected. Extreme-weather windows and NOAA-flagged values removed.

| configuration | any alarm | FAULT only | WEATHER verdicts | samples |
|---|---|---|---|---|
| AtmosGuard (full) | 9.7% | 0.0% | 1.2% | 1026508 |
| AtmosGuard + remedy 6 (unlearned limits filled from the first regular stretch) | 2.6% | 0.0% | 1.4% | 1026508 |
| baseline: range check only | 0.0% | 0.0% | - | 1026508 |
| baseline: textbook range + step + persistence | 5.1% | 5.1% | - | 1026508 |
| baseline: climatology z-score only | 0.7% | 0.0% | - | 1026508 |
| baseline: Isolation Forest only | 0.8% | 0.0% | - | 1026508 |
| baseline: Mahalanobis distance only | 0.7% | 0.0% | - | 1026508 |

#### 3. Real extreme weather (nothing injected)

A FAULT here is a failure: real weather called a broken sensor. WEATHER is the escalated, correct verdict.

| configuration | FAULT | SUSPECT | WEATHER | VALID | windows with a FAULT |
|---|---|---|---|---|---|
| AtmosGuard (full) | 0.1% | 12.8% | 3.0% | 84.1% | 5/160 |
| AtmosGuard + remedy 6 (unlearned limits filled from the first regular stretch) | 0.1% | 4.9% | 3.6% | 91.4% | 5/160 |
| baseline: range check only | 0.0% | 0.0% | - | 100.0% | 0/160 |
| baseline: textbook range + step + persistence | 6.4% | 0.0% | - | 93.6% | 157/160 |
| baseline: climatology z-score only | 0.0% | 1.7% | - | 98.3% | 0/160 |
| baseline: Isolation Forest only | 0.0% | 1.7% | - | 98.3% | 0/160 |
| baseline: Mahalanobis distance only | 0.0% | 1.6% | - | 98.4% | 0/160 |

Full pipeline, by kind of extreme weather:

| kind of extreme weather | samples | FAULT | SUSPECT | WEATHER | windows with a FAULT |
|---|---|---|---|---|---|
| cold | 8727 | 0.1% | 18.7% | 1.8% | 1/30 |
| heat | 10828 | 0.0% | 8.4% | 4.8% | 0/32 |
| low | 13786 | 0.3% | 13.3% | 3.1% | 3/41 |
| sharp | 11991 | 0.0% | 11.9% | 2.3% | 1/57 |

#### 4. Agreement with NOAA's own quality flags

NOAA's flags come from another automated system. Agreement means consistency with existing practice, not proof of real-world accuracy.

| measure | value |
|---|---|
| NOAA-flagged values (suspect or erroneous) | 845 |
|   of which erroneous | 0 |
| AtmosGuard alarmed (FAULT or SUSPECT) on flagged values | 50.4% |
| AtmosGuard escalated at all (also WEATHER) on flagged values | 59.9% |
| AtmosGuard alarmed on erroneous values | n/a |
| values NOAA did not flag | 1071872 |
| AtmosGuard alarmed on those (extra flags) | 10.0% |
| AtmosGuard escalated at all on those | 11.3% |

#### 5. Slow drift, judged by the health monitor

A ramp over 45 days is added to one channel of clean real data. Severity = offset at the end of the ramp in multiples of the service limit (T 0.5 C, P 1 hPa, RH 3 %). One station, no reference: small drifts cannot be told from weather.

| drift at end of ramp | temperature | pressure | humidity |
|---|---|---|---|
| none (false claims) | 2.4% of 84 chunks | 2.4% of 84 chunks | 14.3% of 84 chunks |
| 1x service limit | 1% of 84 (day 30, 12.0x at detection) | 1% of 84 (day 18, 2.7x at detection) | 4% of 84 (day 149, 7.5x at detection) |
| 2x service limit | 1% of 84 (day 30, 12.5x at detection) | 1% of 84 (day 18, 3.1x at detection) | 5% of 84 (day 112, 6.8x at detection) |
| 4x service limit | 5% of 84 (day 45, 6.0x at detection) | 10% of 84 (day 68, 4.7x at detection) | 11% of 84 (day 52, 6.3x at detection) |
| 8x service limit | 13% of 84 (day 38, 9.6x at detection) | 25% of 84 (day 47, 6.2x at detection) | 44% of 84 (day 53, 9.2x at detection) |

#### By station (full pipeline)

Each station judged on its own record.

| station | cadence (min) | clean any alarm | clean FAULT | extreme weather FAULT | windows with a FAULT | extreme weather WEATHER | injected faults detected |
|---|---|---|---|---|---|---|---|
| FHB | 20 | 3.2% | 0.2% | 0.4% | 1/14 | 2.7% | 98% |
| PTT | 20 | 1.4% | 0.0% | 0.0% | 0/17 | 2.5% | 98% |
| MDS | 20 | 1.6% | 0.0% | 0.0% | 0/12 | 1.8% | 98% |
| LPO | 20 | 3.7% | 0.1% | 0.4% | 2/14 | 0.7% | 97% |
| GGW | 20 | 1.4% | 0.0% | 0.0% | 0/15 | 2.5% | 99% |
| GRC | 20 | 4.6% | 0.0% | 0.0% | 0/16 | 8.4% | 99% |
| HUT | 20 | 3.0% | 0.0% | 0.0% | 0/15 | 3.8% | 99% |
| WEI | 60 | 29.3% | 0.0% | 0.0% | 0/10 | 1.3% | 92% |
| TNC | 60 | 42.1% | 0.0% | 0.0% | 0/16 | 1.6% | 88% |
| ASP | 60 | 60.7% | 0.0% | 0.1% | 2/14 | 0.5% | 77% |
| LRM | 60 | 49.3% | 0.0% | 0.0% | 0/8 | 0.8% | 86% |
| BRM | 60 | 42.7% | 0.0% | 0.0% | 0/9 | 2.9% | 85% |

#### 1b. The same, by the criterion registered in the protocol (any alarm in the window)

Background false alarms (about 2 % of samples) also fall inside long fault windows, so this flatters long faults (frozen 48 h, clock shift 4 days) and every system, baselines included. Kept because it was registered before the holdout.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 99% | 100% | 100% | 100% | 96% |
| AtmosGuard + remedy 6 (unlearned limits filled from the first regular stretch) | 100% | 99% | 94% | 94% | 100% | 95% |
| baseline: range check only | 0% | 14% | 13% | 16% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 92% | 96% | 92% | 18% | 94% |
| baseline: climatology z-score only | 15% | 11% | 16% | 7% | 1% | 39% |
| baseline: Isolation Forest only | 18% | 16% | 35% | 50% | 1% | 78% |
| baseline: Mahalanobis distance only | 76% | 100% | 98% | 94% | 1% | 85% |
| (faults injected) | 1143 | 1143 | 1143 | 1143 | 1143 | 967 |
| AtmosGuard: median minutes to the alarm | 240 | 0 | 0 | 60 | 0 | 60 |

#### No single simpler system is good at every fault type

Each system's weakest fault type from table 1, beside its false-alarm rate and its record on real extreme weather. A system that is best at one fault type is blind to another; the layers exist for coverage, and the WEATHER verdict exists so that coverage does not cost real storms.

| system | weakest injected-fault type (fault raised the alarm) | false alarms on clean data | real extreme weather, windows with a FAULT |
|---|---|---|---|
| AtmosGuard (full) | spike: 84% | 9.7% | 5/160 |
| AtmosGuard + remedy 6 (unlearned limits filled from the first regular stretch) | level shift: 93% | 2.6% | 5/160 |
| baseline: range check only | frozen: 0% | 0.0% | 0/160 |
| baseline: textbook range + step + persistence | dropout: 0% | 5.1% | 157/160 |
| baseline: climatology z-score only | dropout: 0% | 0.7% | 0/160 |
| baseline: Isolation Forest only | dropout: 0% | 0.8% | 0/160 |
| baseline: Mahalanobis distance only | dropout: 0% | 0.7% | 0/160 |

### 4.9 FRESH3, the seven US 20-minute stations only

*The first sub-hourly, fine-resolution records in the project: routine METAR at :15, :35 and :55.* Stations: FHB, PTT, MDS, LPO, GGW, GRC, HUT.

#### Headline

Five separate numbers. They are never merged.

| question | answer |
|---|---|
| False alarms on clean real data (nothing injected) | 2.7% (2.7-2.7) of 858141 samples got FAULT or SUSPECT; 0.0% (0.0-0.0) got FAULT |
| What happens to real extreme weather (cyclones, heat, cold, sharp fronts; nothing injected) | FAULT on 0.1% (0.1-0.1) of 38294 samples (3 of 103 windows); WEATHER on 3.4%, SUSPECT on 5.3% |
| Injected faults whose alarm the fault raised (each type on its own; injected, not real) | frozen 100%; spike 97%; level shift 99%; noise burst 100%; dropout 99%; clock 3 h out 94% |
| Agreement with NOAA's own quality flags (another automated system, not ground truth) | escalated (FAULT, SUSPECT or WEATHER) on 39.6% of 498 NOAA-flagged values (FAULT or SUSPECT alone: 24.7%); escalated on 4.3% of the 896769 values NOAA left alone |
| Slow drift (health monitor, single station, no reference) | false drift claims on 0.7% of 11208 station-days; an injected ramp reaching 8x the service limit was found in 18% of trials |

#### 1. Detection of injected faults, by type (the fault raised the alarm)

Alarm = FAULT or SUSPECT on a sample that was NOT an alarm on the same series without the fault (paired), from the first faulty sample to the last plus 60 minutes. The faults are injected, not real. Ablation rows switch one layer off; baseline rows are simpler systems on the same data.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 97% | 99% | 100% | 99% | 94% |
| AtmosGuard + remedy 6 (unlearned limits filled from the first regular stretch) | 100% | 97% | 99% | 100% | 99% | 94% |
| baseline: range check only | 0% | 14% | 13% | 21% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 98% | 99% | 100% | 0% | 100% |
| baseline: climatology z-score only | 8% | 7% | 8% | 4% | 0% | 29% |
| baseline: Isolation Forest only | 7% | 15% | 24% | 55% | 0% | 85% |
| baseline: Mahalanobis distance only | 73% | 100% | 100% | 100% | 0% | 90% |
| (faults injected) | 738 | 738 | 738 | 738 | 738 | 612 |
| AtmosGuard: median minutes to the alarm | 280 | 0 | 0 | 60 | 0 | 800 |

#### 1d. How sure are the detection numbers? (AtmosGuard full, paired criterion, Wilson 95 % interval)

Faults are injected at random places; each row's interval says how much the percentage could move with another draw of the same size. Faults of one type overlap little but are not fully independent, so read the interval as a guide, not a guarantee.

| fault type | injected | raised the alarm (fault-raised) | named FAULT |
|---|---|---|---|
| frozen | 738 | 100.0% (99.5-100.0) | 98.1% (96.8-98.9) |
| spike | 738 | 97.3% (95.9-98.2) | 13.6% (11.3-16.2) |
| level shift | 738 | 99.1% (98.1-99.5) | 13.3% (11.0-15.9) |
| noise burst | 738 | 100.0% (99.5-100.0) | 21.0% (18.2-24.1) |
| dropout | 738 | 99.3% (98.4-99.7) | 99.3% (98.4-99.7) |
| clock 3 h out | 612 | 94.0% (91.8-95.6) | 2.0% (1.1-3.4) |

#### 1c. How AtmosGuard names what it detects, and the WEATHER-masking check

A FAULT verdict names the problem; SUSPECT asks for review. The last row is the risk of the coherent-level WEATHER route: a fault that was not alarmed but made samples look like real weather.

| AtmosGuard, injected faults | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| raised an alarm (FAULT or SUSPECT) | 100% | 97% | 99% | 100% | 99% | 94% |
| of which named FAULT | 98% | 14% | 13% | 21% | 99% | 2% |
| missed, but made some samples look like WEATHER | 0% | 1% | 1% | 0% | 0% | 4% |

#### The Amendment 4 remedy (unlearned limits filled from the first regular stretch), judged by the rule registered before the run

Adopt only if (a) clean false alarms at the stations where the warm-up applied fall by at least 3 points, (b) no fault type loses more than 2 points, (c) real-weather windows with a FAULT and their share do not rise, (d) the SUSPECT share in real weather rises by at most 2 points. At those stations every configuration is judged only after the warm-up stretch.

| configuration | stations where the warm-up applied | (a) clean false alarms there (full / this) | (b) worst change in paired detection | (c) windows with a FAULT (full / this) | (d) SUSPECT share in real weather (change) | rule (a) | rule (b) | rule (c) | rule (d) | adopt |
|---|---|---|---|---|---|---|---|---|---|---|
| AtmosGuard + remedy 6 (unlearned limits filled from the first regular stretch) | WEI, TNC, ASP, LRM, BRM | 45.4% / 1.8% | none | 3 / 3 of 103 | +0.00 pp | pass | pass | pass | pass | yes |

#### 2. False alarms on clean real data

No fault injected. Extreme-weather windows and NOAA-flagged values removed.

| configuration | any alarm | FAULT only | WEATHER verdicts | samples |
|---|---|---|---|---|
| AtmosGuard (full) | 2.7% | 0.0% | 1.3% | 858141 |
| AtmosGuard + remedy 6 (unlearned limits filled from the first regular stretch) | 2.7% | 0.0% | 1.3% | 858141 |
| baseline: range check only | 0.0% | 0.0% | - | 858141 |
| baseline: textbook range + step + persistence | 5.6% | 5.6% | - | 858141 |
| baseline: climatology z-score only | 0.8% | 0.0% | - | 858141 |
| baseline: Isolation Forest only | 0.7% | 0.0% | - | 858141 |
| baseline: Mahalanobis distance only | 0.6% | 0.0% | - | 858141 |

#### 3. Real extreme weather (nothing injected)

A FAULT here is a failure: real weather called a broken sensor. WEATHER is the escalated, correct verdict.

| configuration | FAULT | SUSPECT | WEATHER | VALID | windows with a FAULT |
|---|---|---|---|---|---|
| AtmosGuard (full) | 0.1% | 5.3% | 3.4% | 91.3% | 3/103 |
| AtmosGuard + remedy 6 (unlearned limits filled from the first regular stretch) | 0.1% | 5.3% | 3.4% | 91.3% | 3/103 |
| baseline: range check only | 0.0% | 0.0% | - | 100.0% | 0/103 |
| baseline: textbook range + step + persistence | 6.7% | 0.0% | - | 93.3% | 103/103 |
| baseline: climatology z-score only | 0.0% | 1.7% | - | 98.3% | 0/103 |
| baseline: Isolation Forest only | 0.0% | 1.4% | - | 98.6% | 0/103 |
| baseline: Mahalanobis distance only | 0.0% | 1.2% | - | 98.8% | 0/103 |

Full pipeline, by kind of extreme weather:

| kind of extreme weather | samples | FAULT | SUSPECT | WEATHER | windows with a FAULT |
|---|---|---|---|---|---|
| cold | 6722 | 0.1% | 7.4% | 1.8% | 1/16 |
| heat | 9570 | 0.0% | 3.4% | 5.4% | 0/23 |
| low | 12056 | 0.3% | 7.6% | 3.2% | 2/29 |
| sharp | 9946 | 0.0% | 2.8% | 2.7% | 0/35 |

#### 4. Agreement with NOAA's own quality flags

NOAA's flags come from another automated system. Agreement means consistency with existing practice, not proof of real-world accuracy.

| measure | value |
|---|---|
| NOAA-flagged values (suspect or erroneous) | 498 |
|   of which erroneous | 0 |
| AtmosGuard alarmed (FAULT or SUSPECT) on flagged values | 24.7% |
| AtmosGuard escalated at all (also WEATHER) on flagged values | 39.6% |
| AtmosGuard alarmed on erroneous values | n/a |
| values NOAA did not flag | 896769 |
| AtmosGuard alarmed on those (extra flags) | 2.9% |
| AtmosGuard escalated at all on those | 4.3% |

#### 5. Slow drift, judged by the health monitor

A ramp over 45 days is added to one channel of clean real data. Severity = offset at the end of the ramp in multiples of the service limit (T 0.5 C, P 1 hPa, RH 3 %). One station, no reference: small drifts cannot be told from weather.

| drift at end of ramp | temperature | pressure | humidity |
|---|---|---|---|
| none (false claims) | 1.9% of 53 chunks | 0.0% of 53 chunks | 15.1% of 53 chunks |
| 1x service limit | 0% of 53 (-, - at detection) | 0% of 53 (-, - at detection) | 4% of 53 (day 138, 7.6x at detection) |
| 2x service limit | 0% of 53 (-, - at detection) | 0% of 53 (-, - at detection) | 6% of 53 (day 74, 8.7x at detection) |
| 4x service limit | 0% of 53 (-, - at detection) | 0% of 53 (-, - at detection) | 11% of 53 (day 49, 7.0x at detection) |
| 8x service limit | 0% of 53 (-, - at detection) | 4% of 53 (day 43, 8.0x at detection) | 49% of 53 (day 53, 8.1x at detection) |

#### By station (full pipeline)

Each station judged on its own record.

| station | cadence (min) | clean any alarm | clean FAULT | extreme weather FAULT | windows with a FAULT | extreme weather WEATHER | injected faults detected |
|---|---|---|---|---|---|---|---|
| FHB | 20 | 3.2% | 0.2% | 0.4% | 1/14 | 2.7% | 98% |
| PTT | 20 | 1.4% | 0.0% | 0.0% | 0/17 | 2.5% | 98% |
| MDS | 20 | 1.6% | 0.0% | 0.0% | 0/12 | 1.8% | 98% |
| LPO | 20 | 3.7% | 0.1% | 0.4% | 2/14 | 0.7% | 97% |
| GGW | 20 | 1.4% | 0.0% | 0.0% | 0/15 | 2.5% | 99% |
| GRC | 20 | 4.6% | 0.0% | 0.0% | 0/16 | 8.4% | 99% |
| HUT | 20 | 3.0% | 0.0% | 0.0% | 0/15 | 3.8% | 99% |

#### 1b. The same, by the criterion registered in the protocol (any alarm in the window)

Background false alarms (about 2 % of samples) also fall inside long fault windows, so this flatters long faults (frozen 48 h, clock shift 4 days) and every system, baselines included. Kept because it was registered before the holdout.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 100% | 99% | 100% | 100% | 94% |
| AtmosGuard + remedy 6 (unlearned limits filled from the first regular stretch) | 100% | 100% | 99% | 100% | 100% | 94% |
| baseline: range check only | 0% | 14% | 13% | 21% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 100% | 100% | 100% | 24% | 100% |
| baseline: climatology z-score only | 11% | 8% | 11% | 6% | 1% | 30% |
| baseline: Isolation Forest only | 18% | 16% | 35% | 60% | 1% | 85% |
| baseline: Mahalanobis distance only | 81% | 100% | 100% | 100% | 1% | 90% |
| (faults injected) | 738 | 738 | 738 | 738 | 738 | 612 |
| AtmosGuard: median minutes to the alarm | 280 | 0 | 0 | 60 | 0 | 740 |

#### No single simpler system is good at every fault type

Each system's weakest fault type from table 1, beside its false-alarm rate and its record on real extreme weather. A system that is best at one fault type is blind to another; the layers exist for coverage, and the WEATHER verdict exists so that coverage does not cost real storms.

| system | weakest injected-fault type (fault raised the alarm) | false alarms on clean data | real extreme weather, windows with a FAULT |
|---|---|---|---|
| AtmosGuard (full) | clock 3 h out: 94% | 2.7% | 3/103 |
| AtmosGuard + remedy 6 (unlearned limits filled from the first regular stretch) | clock 3 h out: 94% | 2.7% | 3/103 |
| baseline: range check only | frozen: 0% | 0.0% | 0/103 |
| baseline: textbook range + step + persistence | dropout: 0% | 5.6% | 103/103 |
| baseline: climatology z-score only | dropout: 0% | 0.8% | 0/103 |
| baseline: Isolation Forest only | dropout: 0% | 0.7% | 0/103 |
| baseline: Mahalanobis distance only | dropout: 0% | 0.6% | 0/103 |

### 4.10 FRESH3, the five Australian automatic stations only

*Irregular 2016-2019 records (16 reports a day with alternating 1 h and 2 h gaps), hourly after.* Stations: WEI, TNC, ASP, LRM, BRM.

#### Headline

Five separate numbers. They are never merged.

| question | answer |
|---|---|
| False alarms on clean real data (nothing injected) | 45.4% (45.1-45.6) of 168367 samples got FAULT or SUSPECT; 0.0% (0.0-0.0) got FAULT |
| What happens to real extreme weather (cyclones, heat, cold, sharp fronts; nothing injected) | FAULT on 0.0% (0.0-0.1) of 7038 samples (2 of 57 windows); WEATHER on 1.3%, SUSPECT on 53.7% |
| Injected faults whose alarm the fault raised (each type on its own; injected, not real) | frozen 100%; spike 60%; level shift 88%; noise burst 99%; dropout 68%; clock 3 h out 100% |
| Agreement with NOAA's own quality flags (another automated system, not ground truth) | escalated (FAULT, SUSPECT or WEATHER) on 89.0% of 347 NOAA-flagged values (FAULT or SUSPECT alone: 87.3%); escalated on 47.1% of the 175103 values NOAA left alone |
| Slow drift (health monitor, single station, no reference) | false drift claims on 0.5% of 6616 station-days; an injected ramp reaching 8x the service limit was found in 44% of trials |

#### 1. Detection of injected faults, by type (the fault raised the alarm)

Alarm = FAULT or SUSPECT on a sample that was NOT an alarm on the same series without the fault (paired), from the first faulty sample to the last plus 60 minutes. The faults are injected, not real. Ablation rows switch one layer off; baseline rows are simpler systems on the same data.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 60% | 88% | 99% | 68% | 100% |
| AtmosGuard + remedy 6 (unlearned limits filled from the first regular stretch) | 100% | 97% | 83% | 82% | 100% | 98% |
| baseline: range check only | 0% | 13% | 12% | 6% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 76% | 80% | 63% | 0% | 84% |
| baseline: climatology z-score only | 18% | 16% | 24% | 6% | 0% | 54% |
| baseline: Isolation Forest only | 5% | 16% | 20% | 18% | 0% | 66% |
| baseline: Mahalanobis distance only | 52% | 100% | 93% | 79% | 0% | 76% |
| (faults injected) | 405 | 405 | 405 | 405 | 405 | 355 |
| AtmosGuard: median minutes to the alarm | 300 | 0 | 60 | 240 | 0 | 240 |

#### 1d. How sure are the detection numbers? (AtmosGuard full, paired criterion, Wilson 95 % interval)

Faults are injected at random places; each row's interval says how much the percentage could move with another draw of the same size. Faults of one type overlap little but are not fully independent, so read the interval as a guide, not a guarantee.

| fault type | injected | raised the alarm (fault-raised) | named FAULT |
|---|---|---|---|
| frozen | 405 | 100.0% (99.1-100.0) | 99.8% (98.6-100.0) |
| spike | 405 | 59.8% (54.9-64.4) | 9.4% (6.9-12.6) |
| level shift | 405 | 87.7% (84.1-90.5) | 11.4% (8.6-14.8) |
| noise burst | 405 | 98.8% (97.1-99.5) | 5.7% (3.8-8.4) |
| dropout | 405 | 67.9% (63.2-72.3) | 67.9% (63.2-72.3) |
| clock 3 h out | 355 | 100.0% (98.9-100.0) | 0.0% (0.0-1.1) |

#### 1c. How AtmosGuard names what it detects, and the WEATHER-masking check

A FAULT verdict names the problem; SUSPECT asks for review. The last row is the risk of the coherent-level WEATHER route: a fault that was not alarmed but made samples look like real weather.

| AtmosGuard, injected faults | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| raised an alarm (FAULT or SUSPECT) | 100% | 60% | 88% | 99% | 68% | 100% |
| of which named FAULT | 100% | 9% | 11% | 6% | 68% | 0% |
| missed, but made some samples look like WEATHER | 0% | 1% | 0% | 0% | 0% | 0% |

#### The Amendment 4 remedy (unlearned limits filled from the first regular stretch), judged by the rule registered before the run

Adopt only if (a) clean false alarms at the stations where the warm-up applied fall by at least 3 points, (b) no fault type loses more than 2 points, (c) real-weather windows with a FAULT and their share do not rise, (d) the SUSPECT share in real weather rises by at most 2 points. At those stations every configuration is judged only after the warm-up stretch.

| configuration | stations where the warm-up applied | (a) clean false alarms there (full / this) | (b) worst change in paired detection | (c) windows with a FAULT (full / this) | (d) SUSPECT share in real weather (change) | rule (a) | rule (b) | rule (c) | rule (d) | adopt |
|---|---|---|---|---|---|---|---|---|---|---|
| AtmosGuard + remedy 6 (unlearned limits filled from the first regular stretch) | WEI, TNC, ASP, LRM, BRM | 45.4% / 1.8% | -17.0 pp (noise burst) | 2 / 2 of 57 | -50.85 pp | pass | FAIL | pass | pass | no |

#### 2. False alarms on clean real data

No fault injected. Extreme-weather windows and NOAA-flagged values removed.

| configuration | any alarm | FAULT only | WEATHER verdicts | samples |
|---|---|---|---|---|
| AtmosGuard (full) | 45.4% | 0.0% | 0.5% | 168367 |
| AtmosGuard + remedy 6 (unlearned limits filled from the first regular stretch) | 1.8% | 0.0% | 2.0% | 168367 |
| baseline: range check only | 0.0% | 0.0% | - | 168367 |
| baseline: textbook range + step + persistence | 2.6% | 2.6% | - | 168367 |
| baseline: climatology z-score only | 0.5% | 0.0% | - | 168367 |
| baseline: Isolation Forest only | 1.2% | 0.0% | - | 168367 |
| baseline: Mahalanobis distance only | 1.3% | 0.0% | - | 168367 |

#### 3. Real extreme weather (nothing injected)

A FAULT here is a failure: real weather called a broken sensor. WEATHER is the escalated, correct verdict.

| configuration | FAULT | SUSPECT | WEATHER | VALID | windows with a FAULT |
|---|---|---|---|---|---|
| AtmosGuard (full) | 0.0% | 53.7% | 1.3% | 45.0% | 2/57 |
| AtmosGuard + remedy 6 (unlearned limits filled from the first regular stretch) | 0.0% | 2.8% | 5.2% | 92.0% | 2/57 |
| baseline: range check only | 0.0% | 0.0% | - | 100.0% | 0/57 |
| baseline: textbook range + step + persistence | 4.6% | 0.0% | - | 95.4% | 54/57 |
| baseline: climatology z-score only | 0.0% | 1.4% | - | 98.6% | 0/57 |
| baseline: Isolation Forest only | 0.0% | 3.5% | - | 96.5% | 0/57 |
| baseline: Mahalanobis distance only | 0.0% | 3.9% | - | 96.1% | 0/57 |

Full pipeline, by kind of extreme weather:

| kind of extreme weather | samples | FAULT | SUSPECT | WEATHER | windows with a FAULT |
|---|---|---|---|---|---|
| cold | 2005 | 0.0% | 56.9% | 1.7% | 0/14 |
| heat | 1258 | 0.0% | 46.3% | 0.7% | 0/9 |
| low | 1730 | 0.1% | 53.0% | 1.9% | 1/12 |
| sharp | 2045 | 0.0% | 55.6% | 0.8% | 1/22 |

#### 4. Agreement with NOAA's own quality flags

NOAA's flags come from another automated system. Agreement means consistency with existing practice, not proof of real-world accuracy.

| measure | value |
|---|---|
| NOAA-flagged values (suspect or erroneous) | 347 |
|   of which erroneous | 0 |
| AtmosGuard alarmed (FAULT or SUSPECT) on flagged values | 87.3% |
| AtmosGuard escalated at all (also WEATHER) on flagged values | 89.0% |
| AtmosGuard alarmed on erroneous values | n/a |
| values NOAA did not flag | 175103 |
| AtmosGuard alarmed on those (extra flags) | 46.6% |
| AtmosGuard escalated at all on those | 47.1% |

#### 5. Slow drift, judged by the health monitor

A ramp over 45 days is added to one channel of clean real data. Severity = offset at the end of the ramp in multiples of the service limit (T 0.5 C, P 1 hPa, RH 3 %). One station, no reference: small drifts cannot be told from weather.

| drift at end of ramp | temperature | pressure | humidity |
|---|---|---|---|
| none (false claims) | 3.2% of 31 chunks | 6.5% of 31 chunks | 12.9% of 31 chunks |
| 1x service limit | 3% of 31 (day 30, 12.0x at detection) | 3% of 31 (day 18, 2.7x at detection) | 3% of 31 (day 149, 3.7x at detection) |
| 2x service limit | 3% of 31 (day 30, 12.5x at detection) | 3% of 31 (day 18, 3.1x at detection) | 3% of 31 (day 149, 4.8x at detection) |
| 4x service limit | 13% of 31 (day 45, 6.0x at detection) | 26% of 31 (day 68, 4.7x at detection) | 10% of 31 (day 70, 6.3x at detection) |
| 8x service limit | 35% of 31 (day 38, 9.6x at detection) | 61% of 31 (day 47, 6.2x at detection) | 35% of 31 (day 54, 10.0x at detection) |

#### By station (full pipeline)

Each station judged on its own record.

| station | cadence (min) | clean any alarm | clean FAULT | extreme weather FAULT | windows with a FAULT | extreme weather WEATHER | injected faults detected |
|---|---|---|---|---|---|---|---|
| WEI | 60 | 29.3% | 0.0% | 0.0% | 0/10 | 1.3% | 92% |
| TNC | 60 | 42.1% | 0.0% | 0.0% | 0/16 | 1.6% | 88% |
| ASP | 60 | 60.7% | 0.0% | 0.1% | 2/14 | 0.5% | 77% |
| LRM | 60 | 49.3% | 0.0% | 0.0% | 0/8 | 0.8% | 86% |
| BRM | 60 | 42.7% | 0.0% | 0.0% | 0/9 | 2.9% | 85% |

#### 1b. The same, by the criterion registered in the protocol (any alarm in the window)

Background false alarms (about 2 % of samples) also fall inside long fault windows, so this flatters long faults (frozen 48 h, clock shift 4 days) and every system, baselines included. Kept because it was registered before the holdout.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 99% | 100% | 100% | 100% | 100% |
| AtmosGuard + remedy 6 (unlearned limits filled from the first regular stretch) | 100% | 98% | 85% | 83% | 100% | 98% |
| baseline: range check only | 0% | 13% | 12% | 6% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 77% | 90% | 77% | 7% | 84% |
| baseline: climatology z-score only | 21% | 17% | 26% | 9% | 1% | 55% |
| baseline: Isolation Forest only | 17% | 17% | 33% | 31% | 0% | 66% |
| baseline: Mahalanobis distance only | 66% | 100% | 94% | 84% | 0% | 77% |
| (faults injected) | 405 | 405 | 405 | 405 | 405 | 355 |
| AtmosGuard: median minutes to the alarm | 0 | 0 | 0 | 0 | 0 | 0 |

#### No single simpler system is good at every fault type

Each system's weakest fault type from table 1, beside its false-alarm rate and its record on real extreme weather. A system that is best at one fault type is blind to another; the layers exist for coverage, and the WEATHER verdict exists so that coverage does not cost real storms.

| system | weakest injected-fault type (fault raised the alarm) | false alarms on clean data | real extreme weather, windows with a FAULT |
|---|---|---|---|
| AtmosGuard (full) | spike: 60% | 45.4% | 2/57 |
| AtmosGuard + remedy 6 (unlearned limits filled from the first regular stretch) | noise burst: 82% | 1.8% | 2/57 |
| baseline: range check only | frozen: 0% | 0.0% | 0/57 |
| baseline: textbook range + step + persistence | dropout: 0% | 2.6% | 54/57 |
| baseline: climatology z-score only | dropout: 0% | 0.5% | 0/57 |
| baseline: Isolation Forest only | dropout: 0% | 1.2% | 0/57 |
| baseline: Mahalanobis distance only | dropout: 0% | 1.3% | 0/57 |

### 4.11 FRESH4: a fifth set of twelve northern US stations with freezing winters, 2020-2024

*Chosen and sealed before the Amendment 5 freezing-point remedy was tested (config/protocol.md). Hourly airport METAR, whole degrees.* Stations: GSH, BFF, AMW, MTP, HLG, JMS, EKO, OWD, BTV, BRD, BMI, MIE.

#### Headline

Five separate numbers. They are never merged.

| question | answer |
|---|---|
| False alarms on clean real data (nothing injected) | 2.0% (1.9-2.0) of 498994 samples got FAULT or SUSPECT; 0.0% (0.0-0.0) got FAULT |
| What happens to real extreme weather (cyclones, heat, cold, sharp fronts; nothing injected) | FAULT on 0.0% (0.0-0.0) of 22864 samples (0 of 180 windows); WEATHER on 4.0%, SUSPECT on 6.2% |
| Injected faults whose alarm the fault raised (each type on its own; injected, not real) | frozen 100%; spike 97%; level shift 90%; noise burst 75%; dropout 99%; clock 3 h out 80% |
| Agreement with NOAA's own quality flags (another automated system, not ground truth) | escalated (FAULT, SUSPECT or WEATHER) on 17.4% of 728 NOAA-flagged values (FAULT or SUSPECT alone: 8.1%); escalated on 3.6% of the 521418 values NOAA left alone |
| Slow drift (health monitor, single station, no reference) | false drift claims on 0.4% of 19527 station-days; an injected ramp reaching 8x the service limit was found in 22% of trials |

#### 1. Detection of injected faults, by type (the fault raised the alarm)

Alarm = FAULT or SUSPECT on a sample that was NOT an alarm on the same series without the fault (paired), from the first faulty sample to the last plus 60 minutes. The faults are injected, not real. Ablation rows switch one layer off; baseline rows are simpler systems on the same data.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 97% | 90% | 75% | 99% | 80% |
| AtmosGuard + remedy 7 (freezing-point plateau is a soft flag) | 100% | 97% | 90% | 75% | 99% | 80% |
| baseline: range check only | 0% | 11% | 13% | 9% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 73% | 83% | 64% | 0% | 82% |
| baseline: climatology z-score only | 6% | 5% | 5% | 2% | 0% | 18% |
| baseline: Isolation Forest only | 5% | 18% | 15% | 20% | 0% | 52% |
| baseline: Mahalanobis distance only | 61% | 100% | 93% | 75% | 0% | 54% |
| (faults injected) | 1350 | 1350 | 1350 | 1350 | 1350 | 1113 |
| AtmosGuard: median minutes to the alarm | 420 | 0 | 0 | 480 | 0 | 1500 |

#### 1d. How sure are the detection numbers? (AtmosGuard full, paired criterion, Wilson 95 % interval)

Faults are injected at random places; each row's interval says how much the percentage could move with another draw of the same size. Faults of one type overlap little but are not fully independent, so read the interval as a guide, not a guarantee.

| fault type | injected | raised the alarm (fault-raised) | named FAULT |
|---|---|---|---|
| frozen | 1350 | 100.0% (99.7-100.0) | 99.7% (99.2-99.9) |
| spike | 1350 | 96.7% (95.6-97.5) | 11.3% (9.8-13.1) |
| level shift | 1350 | 90.4% (88.7-91.8) | 12.7% (11.1-14.6) |
| noise burst | 1350 | 74.8% (72.4-77.1) | 8.8% (7.4-10.4) |
| dropout | 1350 | 99.2% (98.5-99.5) | 99.2% (98.5-99.5) |
| clock 3 h out | 1113 | 79.7% (77.2-82.0) | 0.3% (0.1-0.8) |

#### 1c. How AtmosGuard names what it detects, and the WEATHER-masking check

A FAULT verdict names the problem; SUSPECT asks for review. The last row is the risk of the coherent-level WEATHER route: a fault that was not alarmed but made samples look like real weather.

| AtmosGuard, injected faults | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| raised an alarm (FAULT or SUSPECT) | 100% | 97% | 90% | 75% | 99% | 80% |
| of which named FAULT | 100% | 11% | 13% | 9% | 99% | 0% |
| missed, but made some samples look like WEATHER | 0% | 2% | 5% | 7% | 0% | 12% |

#### The Amendment 5 remedy (freezing-point plateau is a soft flag), judged by the rule registered before the run

Adopt only if (a) windows with a FAULT are fewer than with `full` and the FAULT share does not rise, (b) no fault type loses more than 2 points, (c) clean false alarms rise by at most 0.2 points, (d) the SUSPECT share in real weather rises by at most 2 points.

| configuration | (a) windows with a FAULT (full / this) | (a) FAULT share (full / this) | (b) worst change in paired detection | (c) change in clean false alarms | (d) SUSPECT share change | rule (a) | rule (b) | rule (c) | rule (d) | adopt |
|---|---|---|---|---|---|---|---|---|---|---|
| AtmosGuard + remedy 7 (freezing-point plateau is a soft flag) | 0 / 0 of 180 | 0.00% / 0.00% | none | +0.00 pp | +0.00 pp | FAIL | pass | pass | pass | no |

#### 2. False alarms on clean real data

No fault injected. Extreme-weather windows and NOAA-flagged values removed.

| configuration | any alarm | FAULT only | WEATHER verdicts | samples |
|---|---|---|---|---|
| AtmosGuard (full) | 2.0% | 0.0% | 1.3% | 498994 |
| AtmosGuard + remedy 7 (freezing-point plateau is a soft flag) | 2.0% | 0.0% | 1.3% | 498994 |
| baseline: range check only | 0.0% | 0.0% | - | 498994 |
| baseline: textbook range + step + persistence | 2.7% | 2.7% | - | 498994 |
| baseline: climatology z-score only | 0.2% | 0.0% | - | 498994 |
| baseline: Isolation Forest only | 0.5% | 0.0% | - | 498994 |
| baseline: Mahalanobis distance only | 0.5% | 0.0% | - | 498994 |

#### 3. Real extreme weather (nothing injected)

A FAULT here is a failure: real weather called a broken sensor. WEATHER is the escalated, correct verdict.

| configuration | FAULT | SUSPECT | WEATHER | VALID | windows with a FAULT |
|---|---|---|---|---|---|
| AtmosGuard (full) | 0.0% | 6.2% | 4.0% | 89.7% | 0/180 |
| AtmosGuard + remedy 7 (freezing-point plateau is a soft flag) | 0.0% | 6.2% | 4.0% | 89.7% | 0/180 |
| baseline: range check only | 0.0% | 0.0% | - | 100.0% | 0/180 |
| baseline: textbook range + step + persistence | 4.2% | 0.0% | - | 95.8% | 166/180 |
| baseline: climatology z-score only | 0.0% | 0.8% | - | 99.2% | 0/180 |
| baseline: Isolation Forest only | 0.0% | 2.3% | - | 97.7% | 0/180 |
| baseline: Mahalanobis distance only | 0.0% | 2.4% | - | 97.6% | 0/180 |

Full pipeline, by kind of extreme weather:

| kind of extreme weather | samples | FAULT | SUSPECT | WEATHER | windows with a FAULT |
|---|---|---|---|---|---|
| cold | 3708 | 0.0% | 11.4% | 3.5% | 0/26 |
| heat | 5166 | 0.0% | 3.4% | 3.8% | 0/36 |
| low | 8258 | 0.0% | 7.3% | 4.2% | 0/58 |
| sharp | 5732 | 0.0% | 3.8% | 4.4% | 0/60 |

#### 4. Agreement with NOAA's own quality flags

NOAA's flags come from another automated system. Agreement means consistency with existing practice, not proof of real-world accuracy.

| measure | value |
|---|---|
| NOAA-flagged values (suspect or erroneous) | 728 |
|   of which erroneous | 87 |
| AtmosGuard alarmed (FAULT or SUSPECT) on flagged values | 8.1% |
| AtmosGuard escalated at all (also WEATHER) on flagged values | 17.4% |
| AtmosGuard alarmed on erroneous values | 1.1% |
| values NOAA did not flag | 521418 |
| AtmosGuard alarmed on those (extra flags) | 2.2% |
| AtmosGuard escalated at all on those | 3.6% |

#### 5. Slow drift, judged by the health monitor

A ramp over 45 days is added to one channel of clean real data. Severity = offset at the end of the ramp in multiples of the service limit (T 0.5 C, P 1 hPa, RH 3 %). One station, no reference: small drifts cannot be told from weather.

| drift at end of ramp | temperature | pressure | humidity |
|---|---|---|---|
| none (false claims) | 3.3% of 90 chunks | 0.0% of 90 chunks | 10.0% of 90 chunks |
| 1x service limit | 2% of 90 (day 95, 9.1x at detection) | 0% of 90 (-, - at detection) | 4% of 90 (day 74, 4.7x at detection) |
| 2x service limit | 2% of 90 (day 95, 10.2x at detection) | 0% of 90 (-, - at detection) | 8% of 90 (day 63, 6.2x at detection) |
| 4x service limit | 2% of 90 (day 95, 12.4x at detection) | 0% of 90 (-, - at detection) | 16% of 90 (day 57, 6.6x at detection) |
| 8x service limit | 7% of 90 (day 58, 14.6x at detection) | 6% of 90 (day 52, 10.5x at detection) | 53% of 90 (day 48, 8.3x at detection) |

#### By station (full pipeline)

Each station judged on its own record.

| station | cadence (min) | clean any alarm | clean FAULT | extreme weather FAULT | windows with a FAULT | extreme weather WEATHER | injected faults detected |
|---|---|---|---|---|---|---|---|
| GSH | 60 | 1.6% | 0.0% | 0.0% | 0/12 | 3.3% | 92% |
| BFF | 60 | 2.2% | 0.0% | 0.0% | 0/17 | 5.8% | 85% |
| AMW | 60 | 2.3% | 0.0% | 0.0% | 0/15 | 4.9% | 93% |
| MTP | 60 | 1.3% | 0.0% | 0.0% | 0/13 | 3.9% | 90% |
| HLG | 60 | 2.2% | 0.0% | 0.0% | 0/16 | 1.2% | 92% |
| JMS | 60 | 2.4% | 0.0% | 0.0% | 0/16 | 6.4% | 92% |
| EKO | 60 | 2.2% | 0.0% | 0.0% | 0/14 | 4.7% | 89% |
| OWD | 60 | 1.7% | 0.0% | 0.0% | 0/14 | 3.8% | 91% |
| BTV | 60 | 1.6% | 0.0% | 0.0% | 0/13 | 3.8% | 91% |
| BRD | 60 | 1.9% | 0.0% | 0.0% | 0/18 | 5.7% | 89% |
| BMI | 60 | 1.9% | 0.0% | 0.0% | 0/15 | 2.0% | 90% |
| MIE | 60 | 2.2% | 0.0% | 0.0% | 0/17 | 2.4% | 92% |

#### 1b. The same, by the criterion registered in the protocol (any alarm in the window)

Background false alarms (about 2 % of samples) also fall inside long fault windows, so this flatters long faults (frozen 48 h, clock shift 4 days) and every system, baselines included. Kept because it was registered before the holdout.

| configuration | frozen | spike | level shift | noise burst | dropout | clock 3 h out |
|---|---|---|---|---|---|---|
| AtmosGuard (full) | 100% | 99% | 91% | 78% | 100% | 80% |
| AtmosGuard + remedy 7 (freezing-point plateau is a soft flag) | 100% | 99% | 91% | 78% | 100% | 80% |
| baseline: range check only | 0% | 11% | 13% | 9% | 0% | 0% |
| baseline: textbook range + step + persistence | 100% | 75% | 90% | 77% | 5% | 83% |
| baseline: climatology z-score only | 7% | 5% | 5% | 3% | 0% | 19% |
| baseline: Isolation Forest only | 8% | 19% | 21% | 24% | 0% | 52% |
| baseline: Mahalanobis distance only | 65% | 100% | 93% | 76% | 0% | 54% |
| (faults injected) | 1350 | 1350 | 1350 | 1350 | 1350 | 1113 |
| AtmosGuard: median minutes to the alarm | 420 | 0 | 0 | 480 | 0 | 1440 |

#### No single simpler system is good at every fault type

Each system's weakest fault type from table 1, beside its false-alarm rate and its record on real extreme weather. A system that is best at one fault type is blind to another; the layers exist for coverage, and the WEATHER verdict exists so that coverage does not cost real storms.

| system | weakest injected-fault type (fault raised the alarm) | false alarms on clean data | real extreme weather, windows with a FAULT |
|---|---|---|---|
| AtmosGuard (full) | noise burst: 75% | 2.0% | 0/180 |
| AtmosGuard + remedy 7 (freezing-point plateau is a soft flag) | noise burst: 75% | 2.0% | 0/180 |
| baseline: range check only | frozen: 0% | 0.0% | 0/180 |
| baseline: textbook range + step + persistence | dropout: 0% | 2.7% | 166/180 |
| baseline: climatology z-score only | dropout: 0% | 0.2% | 0/180 |
| baseline: Isolation Forest only | dropout: 0% | 0.5% | 0/180 |
| baseline: Mahalanobis distance only | dropout: 0% | 0.5% | 0/180 |

### 4.12 Scale and speed

Simulated stations on one machine (a design check, not a deployment proof). cpu_count=4, python=3.11.15.

| stations | readings/s | median ms | p95 ms | p99 ms | MB/station | KB stored/station |
|---|---|---|---|---|---|---|
| 1 | 923.8 | 0.921 | 2.368 | 2.787 | 6.92 | 1584.5 |
| 10 | 851.4 | 0.968 | 2.553 | 2.994 | 3.05 | 1584.5 |
| 50 | 836.6 | 0.968 | 2.559 | 3.065 | 2.99 | 1584.5 |
| 100 | 819.0 | 0.986 | 2.555 | 3.109 | 1.78 | 1584.5 |

The same test with the Isolation Forest layer switched off (`layers.mlmodel: false`). In the ablation (tables above) the forest adds almost nothing to the verdicts, and it is most of the per-reading time:

| stations | readings/s | median ms | p95 ms | p99 ms |
|---|---|---|---|---|
| 1 | 1536.9 | 0.499 | 1.713 | 2.071 |
| 50 | 1353.0 | 0.526 | 1.977 | 2.395 |

Real HTTP server (FastAPI + SQLite), 50 stations, 8 concurrent clients: 164.8 requests/s, median 44.89 ms, p95 59.17 ms, p99 66.33 ms, errors 0.

### 4.13 How big must a fault be? (DEV, injected)

How big must a fault be? Spikes, level shifts and noise bursts of 0.25 to 4 times the configured size, injected into clean real data of the six DEV stations (the tuning set, so an envelope study and not a held-out result). A detection is an alarm the fault itself raised. The 1x row is a separate random draw (two faults of each type per series, one round), so it is close to but not identical with the main table.

| system | size (x the configured fault) | spike | level shift | noise burst |
|---|---|---|---|---|
| AtmosGuard | 0.25x | 13% | 2% | 11% |
| AtmosGuard | 0.5x | 70% | 26% | 28% |
| AtmosGuard | 1x | 94% | 94% | 87% |
| AtmosGuard | 2x | 98% | 100% | 100% |
| AtmosGuard | 4x | 98% | 100% | 100% |
| textbook range + step + persistence | 0.25x | 6% | 0% | 13% |
| textbook range + step + persistence | 0.5x | 54% | 24% | 24% |
| textbook range + step + persistence | 1x | 70% | 78% | 69% |
| textbook range + step + persistence | 2x | 98% | 94% | 100% |
| textbook range + step + persistence | 4x | 98% | 100% | 100% |
| Mahalanobis distance only | 0.25x | 9% | 0% | 2% |
| Mahalanobis distance only | 0.5x | 91% | 26% | 24% |
| Mahalanobis distance only | 1x | 100% | 100% | 83% |
| Mahalanobis distance only | 2x | 100% | 100% | 100% |
| Mahalanobis distance only | 4x | 100% | 100% | 100% |

### 4.14 A new station on day one (cold start)

Leave-one-station-out on the six DEV stations, judged on their DEV years. A starter is a frozen table from the nearest other station. Injected faults: frozen, spike, level shift.

| days of own history | with a starter: clean false alarms | with a starter: FAULT on real extreme weather | with a starter: injected faults detected | own data only: clean false alarms | own data only: FAULT on real extreme weather | own data only: injected faults detected |
|---|---|---|---|---|---|---|
| 0 | 6.09% | 0.0% | 86.4% | 62.72% | 28.6% | 79.6% |
| 30 | 5.79% | 0.0% | 85.8% | 16.53% | 4.97% | 84.0% |
| 90 | 7.34% | 0.0% | 95.7% | 12.83% | 0.03% | 92.0% |
| 365 | 4.17% | 0.0% | 97.5% | 5.3% | 0.0% | 96.9% |
| 1460 | 1.88% | 0.0% | 96.3% | 1.88% | 0.0% | 96.3% |

The study ran 42 jobs in 8.7 minutes on 4 workers (`python evaluate_coldstart.py`; `--estimate` projects the running time first).

### 4.15 Figures

![Figure 3. The same real data and the same three numbers for AtmosGuard and simpler systems, in every split (lower is better in the first two columns, higher in the third).](figures/fig_baselines.png)

*Figure 3. The same real data and the same three numbers for AtmosGuard and simpler systems, in every split (lower is better in the first two columns, higher in the third).*

![Figure 4. Ablation on DEV: what each layer is worth (bars) and what it costs in false alarms on clean real data (top).](figures/fig_ablation.png)

*Figure 4. Ablation on DEV: what each layer is worth (bars) and what it costs in false alarms on clean real data (top).*

![Figure 5. Three real cyclones with nothing injected: the pressure crash is escalated as weather, never called a fault.](figures/fig_real_cyclones.png)

*Figure 5. Three real cyclones with nothing injected: the pressure crash is escalated as weather, never called a fault.*

![Figure 6. The fresh stations: what the two remedies from the holdout post-mortem do (registered decision rule, Section 2.7).](figures/fig_remedies.png)

*Figure 6. The fresh stations: what the two remedies from the holdout post-mortem do (registered decision rule, Section 2.7).*

![Figure 6b. The third sealed set (fresh-2): what the two Amendment 3 remedies do (registered decision rule, Section 2.9).](figures/fig_amendment3.png)

*Figure 6b. The third sealed set (fresh-2): what the two Amendment 3 remedies do (registered decision rule, Section 2.9).*

![Figure 6c. The optional peer layer: constant offsets found with and without neighbours, two Australian AWS clusters (injected faults).](figures/fig_peers.png)

*Figure 6c. The optional peer layer: constant offsets found with and without neighbours, two Australian AWS clusters (injected faults).*

![Figure 7. How big must a fault be? Detection against fault size on the DEV stations (injected faults, tuning set).](figures/fig_detectability.png)

*Figure 7. How big must a fault be? Detection against fault size on the DEV stations (injected faults, tuning set).*

![Figure 8. A new station on day one: with a starter from the nearest other station, and with its own data only.](figures/fig_coldstart.png)

*Figure 8. A new station on day one: with a starter from the nearest other station, and with its own data only.*

![Figure 9. Per-reading cost against the number of stations (state is per station).](figures/fig_scale.png)

*Figure 9. Per-reading cost against the number of stations (state is per station).*

![Figure 10. Slow drift: the share of chunks where the drift monitor claims drift, against the size of the ramp.](figures/fig_drift_power.png)

*Figure 10. Slow drift: the share of chunks where the drift monitor claims drift, against the size of the ramp.*


### The optional peer layer: constant offsets and slow drift, seen with neighbours

**The limit it removes.** A single station, judged only against its own history, cannot see a sensor that was 1 hPa high from the day it was installed, or one that
drifted 2 C over two months: the offset becomes part of its "normal". `docs/WHAT_WE_DO_NOT_CLAIM.md` says so and the drift monitor states the smallest drift it can see.
Neighbouring stations weather the same synoptic systems, so a station's *departure from its own normal* moves with its neighbours' departures. When it stops doing so
and stays apart, the sensor has moved.

**This is optional and outside the core.** The problem statement is one station from T, P and RH alone, and the core pipeline stays exactly that. The peer layer is
for a network that can supply neighbours: `atmos/peers.py`, off unless used. It does nothing for a lone station in the Andamans or Ladakh, and it says so by returning
no result when fewer than three neighbours have a reading.

#### How it works
1. **Anomaly** = reading minus the station's own smooth normal (the same month x hour table the pipeline already fits). This removes elevation and local climate, so
   neighbours need not be alike.
2. **Difference** = own anomaly minus the *median* of the neighbours' anomalies at the same hour (neighbours within 250 km, at least three with a valid reading). A median
   is not moved by one bad neighbour.
3. **Alarm** = the 7-day mean of the difference is beyond a limit learned from the station's clean 2016-2019 years: the 99.5th percentile of the absolute 7-day mean, times
   1.1. It is the same construction as the station-learned limits in `atmos/limits.py`; nothing is tuned on the faults.

#### Evidence (injected faults; a study on dense networks, not a claim about sparse ones)
Two disjoint clusters of twelve Australian Bureau of Meteorology automatic weather stations, hourly at 0.1 C and 0.1 hPa, 2016-2024 (`data_tools/stations_peers_nsw.yaml`,
`stations_peers_vic.yaml`; central-west New South Wales and northern Victoria, none in any sealed set). Each station is trained on 2016-2019. Into 2020-2023, at random start
times, 60-day constant offsets of three sizes per channel and 60-day linear drifts are injected (12 starts per station, size and channel, 12 stations). An offset counts as
detected if the fault raised an alarm within 21 days of its start (paired, as in Amendment 1: an alarm that was already there without the fault does not count); a drift, within
its 60 days. Each cell: detected share (detected/trials, median days to the alarm). *Alone* is the same statistic on the station's own anomaly with no neighbours, which is all
a single station has.

**The settings were fixed on the NSW cluster, then run unchanged on the VIC cluster.** Four settings were tried on NSW (7 or 14 days, 99th or 99.5th percentile); the one
kept is the most sensitive whose false-alarm share stays at or below 1 % of days in every channel with neighbours. The VIC column is the check on it.

![Offsets found with and without neighbours](figures/fig_peers.png)

<!-- PEERS:START -->
| fault (60 days long) | NSW: with neighbours / alone | VIC: with neighbours / alone | INDIA: with neighbours / alone |
|---|---|---|---|
| temperature offset of 0.5 C | 9% (13/144, 7 d) / 3% (4/141, 12 d) | 17% (24/141, 12 d) / 0% (0/141) | 10% (26/250, 9 d) / 3% (9/285, 5 d) |
| temperature offset of 1 C | 38% (54/143, 7 d) / 3% (5/144, 10 d) | 48% (68/143, 8 d) / 0% (0/144) | 17% (42/250, 8 d) / 10% (29/284, 6 d) |
| temperature offset of 2 C | 86% (122/142, 6 d) / 9% (13/144, 7 d) | 88% (125/142, 5 d) / 1% (2/144, 8 d) | 54% (134/250, 7 d) / 21% (59/283, 8 d) |
| temperature drift, 0 to 2 C | 82% (118/144, 40 d) / 3% (5/144, 42 d) | 84% (120/143, 36 d) / 3% (5/143, 48 d) | 48% (119/250, 40 d) / 20% (55/282, 42 d) |
| pressure offset of 0.5 hPa | 31% (44/144, 10 d) / 1% (1/140, 19 d) | 23% (32/141, 12 d) / 0% (0/143) | 20% (50/249, 7 d) / 5% (15/285, 9 d) |
| pressure offset of 1 hPa | 67% (96/143, 6 d) / 1% (2/141, 11 d) | 65% (93/143, 7 d) / 0% (0/143) | 50% (125/249, 6 d) / 10% (30/287, 7 d) |
| pressure offset of 2 hPa | 96% (138/144, 4 d) / 4% (6/143, 9 d) | 91% (131/144, 5 d) / 0% (0/143) | 91% (228/251, 4 d) / 21% (59/287, 8 d) |
| pressure drift, 0 to 2 hPa | 94% (135/143, 32 d) / 3% (4/143, 19 d) | 90% (128/142, 35 d) / 1% (2/143, 38 d) | 85% (214/251, 33 d) / 25% (71/283, 44 d) |
| humidity offset of 3 % | 12% (17/144, 9 d) / 13% (19/143, 6 d) | 15% (21/142, 9 d) / 17% (25/144, 8 d) | 10% (24/250, 7 d) / 14% (39/284, 7 d) |
| humidity offset of 6 % | 34% (48/142, 9 d) / 26% (37/143, 11 d) | 41% (59/143, 8 d) / 28% (40/142, 8 d) | 19% (48/249, 7 d) / 24% (67/285, 7 d) |
| humidity offset of 12 % | 75% (107/143, 6 d) / 46% (66/144, 7 d) | 90% (130/144, 5 d) / 53% (74/140, 8 d) | 67% (170/252, 6 d) / 62% (178/285, 6 d) |
| humidity drift, 0 to 12 % | 69% (99/144, 36 d) / 47% (68/144, 33 d) | 90% (128/143, 35 d) / 61% (88/144, 31 d) | 63% (158/249, 39 d) / 57% (164/287, 37 d) |

| share of clean days with an alarm | NSW: with neighbours / alone | VIC: with neighbours / alone | INDIA: with neighbours / alone |
|---|---|---|---|
| temperature | 0.52% / 2.60% | 0.62% / 0.43% | 2.69% / 2.27% |
| pressure | 0.95% / 0.77% | 0.20% / 0.30% | 3.90% / 1.75% |
| humidity | 0.96% / 2.36% | 2.45% / 3.09% | 2.11% / 2.30% |

<!-- PEERS:END -->

A "quiet" setting (99.9th percentile x 1.2) is in `results/peers_*_quiet.*`: false alarms below 0.25 % of days on NSW and below 0.75 % on VIC, at the cost of a large part of the
detection at small and medium sizes (a 1 hPa offset: 40 % instead of 67 % on NSW, 32 % instead of 65 % on VIC).

#### Does it work at Indian station spacing? (INDIA column)
Indian airports are far apart: only 4 of 31 stations have three neighbours within 250 km, but 28 of 31 have three within 600 km. The INDIA column runs the same settings on the 31 Indian airport
stations already in this repository (DEV, holdout, fresh and fresh-2 files; whole-degree hourly METAR, some 3-hourly SYNOP), with the neighbour radius widened to **600 km** (`python evaluate_peers.py --cluster india
--radius-km 600`); nothing is tuned on them and nothing new is downloaded. Result, in short: **pressure works** (a 2 hPa offset found in 91 % of trials against 21 % alone, a 2 hPa drift 85 % against 25 %; 1 hPa 50 % against
10 %), temperature works at 2 C (54 % against 21 %) and much less below, **humidity gains nothing**, and false alarms are higher than on the Australian clusters (about 2-4 % of clean days, 3.9 % for pressure) because the
records are rounded to whole hPa and the neighbours are farther away. So the honest statement is: with a 600 km radius, an Indian network of airport-spacing stations can see pressure offsets and drift of about 1-2 hPa
that no single station can; it is not a substitute for calibration visits, and it was measured on injected faults.

#### What it does not do
- **Small offsets.** Half a degree, half a hPa and 3 % humidity are mostly missed even with neighbours, and humidity is weak throughout (its departures are local: fog, irrigation, a
  different exposure). Pressure is the strong channel, temperature next.
- **False alarms are not zero.** About 1-2 % of clean days carry a peer alarm in the humidity channel (2.4 % on VIC, above the 1 % the NSW rule targeted), and it is a review flag, not a fault.
- **A fault that moves all the neighbours too** (a common calibration error, a network-wide change of instrument) is invisible to it.
- **It needs a network.** At least three neighbours within 250 km, all reporting; a sparse network gets nothing. Whether India's AWS network is dense enough in a given region is
  a question about the network, not about this code.
- **The faults are injected** (into the anomaly series), and the stations are Australian. It is a mechanism and a measurement on real weather, not a field trial.

#### Reproduce
```bash
python -m data_tools.make_peers --cluster nsw && python -m data_tools.make_peers --cluster vic
python evaluate_peers.py --cluster nsw --quantile 0.995 --margin 1.1 --out results/peers_nsw.json
python evaluate_peers.py --cluster vic --quantile 0.995 --margin 1.1 --out results/peers_vic.json
python -m data_tools.make_peers --cluster india && python evaluate_peers.py --cluster india --radius-km 600 --quantile 0.995 --margin 1.1 --out results/peers_india.json
python make_summary.py results/dev_run4.json ... --peers results/peers_nsw.json results/peers_vic.json results/peers_india.json --peers-doc docs/PEER_LAYER.md   # refreshes the tables above
```
For a cluster of your own: a catalog like `data_tools/stations_peers_nsw.yaml` (identity and coordinates) and one CSV per station in `data/peers/<cluster>/`.

## 5. What the holdout found that development did not

The holdout exists to find what DEV could not. On the eight stations never used for any tuning, **3 of 98 real extreme-weather windows contain a
`FAULT` verdict** (0.3 % of those samples). On the same six DEV stations in later years, none of 38 do, and DEV had none of 30. This is a
post-mortem: it explains the three windows and proposes remedies. **The pipeline was not changed in response**, because that would be tuning on the
holdout; the numbers in `results/REPORT.md` are for the pipeline exactly as frozen in commit `9cd24f1`. (The windows were read only to explain
verdicts already reported.)

### The three windows
| Station | Event | What the data did | Which rule fired | Why it is wrong |
|---|---|---|---|---|
| Visakhapatnam | low-pressure window centred 26 Sep 2021 | humidity at exactly 100 % for 22+ hours | `frozen:humidity_pct` beyond twice the learned limit -> hard -> FAULT | Sustained torrential rain gives T = Td, so derived RH is pinned at its physical ceiling. A saturated stuck sensor and a real downpour look identical without rain information. |
| Visakhapatnam | low-pressure window centred 8 Sep 2024 | humidity pinned at 100 % and temperature at 26 C for about 38 hours, while pressure kept moving (998-1001 hPa) | `frozen:humidity_pct` and `frozen:temperature_c` | Same cause: an isothermal, saturated air mass has no diurnal cycle either. |
| Bhuj (3-hourly SYNOP, arid) | sharp-temperature-change window centred 16 Feb 2023 (the verdict is on 14 Feb) | one 6-hour gap in the reports, then temperature +15.6 C over the gap (18.6 -> 34.2) with pressure and humidity changing ordinarily | `step:temperature_c` (allowed 10 C) -> rule 2 -> FAULT | An arid station warms 15 C between about 08:30 and 14:30 local time on a clear day; the fixed 10 C step cap is wrong for a 3-hourly (here 6-hourly) interval at a desert station. |

### Proposed remedies (not applied, not evaluated)
1. **Ceiling-aware frozen rule.** A channel pinned at a physical limit (humidity at 100 %) is at most a **soft** flag, and temperature frozen while humidity is
   saturated is soft too. Reason: saturation is a ceiling that real weather holds for a day or more. A stuck sensor at 100 % would then be `SUSPECT`, not `FAULT`;
   it would be caught by the health score and by a disagreement with the other channels, which is weaker but honest.
2. **Station-learned step cap.** Replace the fixed 10 C / 10 hPa / 40 % caps by the 99.9th percentile of |change| at the station's cadence from its clean history
   (the same treatment the frozen and noise limits already get), never below the configured value. Reason: the largest ordinary change depends on cadence and climate.

Both are small, both follow the pattern the real data taught us (limits belong to the station and the cadence), and both need a fresh set of unseen stations to be
evaluated honestly. Re-running them on this holdout would turn it into a tuning set, so they are listed as next work.

### What it says about the claim
The claim is "0 FAULT on real extreme weather" on DEV and on the time holdout, and "0.3 % of samples, 3 of 98 windows" on unseen stations, with the cause of each. It is
not "never". The textbook rules baseline gets 95 of those 98 windows wrong.

### What happened next: the remedies, tested on stations nobody had looked at
The two remedies above were not applied to the sealed holdout. Instead we registered a decision rule (Amendment 2 in `config/protocol.md`) and tested both on
twelve more Indian stations that had not been used for anything (`data_tools/stations_fresh.yaml`), in one run behind its own guard. The result, judged by
that rule and nothing else:

- **Remedy 1, the ceiling-aware frozen rule, is adopted.** Real extreme-weather windows with a `FAULT`: 3 of 139 become 2; detection and false alarms are
  unchanged. The window it removed is Ranchi in May 2021: humidity at 100 % for more than 35 hours, the same cause as Visakhapatnam.
- **Remedy 2, the station-learned step cap, is rejected.** It also takes the windows from 3 to 2 and lowers clean false alarms slightly, but it costs 4.2 points of
  wrong-clock detection: the same fixed step cap is what flags the jump when a logger clock goes wrong. That breaks rule (b), so it is not shipped.
- The frozen pipeline on these twelve stations had 3 windows with a `FAULT` out of 139 (0.1 % of samples): Ranchi (saturation), Coimbatore (humidity up 47 %
  in two hours against a 40 % cap, one sample) and Jodhpur (temperature up 16 C across a 6-hour reporting gap, the Bhuj cause again). So the two step causes are
  still open. A step cap that scales with the reporting gap, or that applies to the "one channel jumped" rule only, is the obvious next candidate, and it would
  need a third set of unseen stations to be judged honestly.

What the adopted remedy costs: a humidity sensor that really is stuck at 100 % is now a `SUSPECT` (review), not a `FAULT`, until it disagrees with the other
channels or the health score drops. We take that trade because sustained saturation is real weather more often than a stuck sensor is, and we say so.


### What happened after that: the third set (Amendment 3)
The step causes were the open item. A step cap that scales with what the station's own daily cycle explains was registered as remedy 3 (with a second remedy aimed at level shifts) and tested once on twelve more
stations nobody had looked at: five Indian airports and seven Australian automatic weather stations (`data_tools/stations_fresh2.yaml`). By the rule registered first, **remedy 3 is adopted**: real
extreme-weather windows with a `FAULT` 4 to 1 of 134 (the four were fast humidity drops and an afternoon warming at Giles in the desert and Thredbo in the Alps), no detection type moved, clean false alarms
-0.02 points. The one window left is Thredbo, October 2023 (humidity -48.9 % in two hours). Remedy 4 (a sustained one-channel offset) is **rejected**: level-shift detection +1 point against the +5 registered,
clean false alarms +0.48 points. Details and every number: Amendment 3 and its outcome in `config/protocol.md`, `results/REPORT.md`.

### And a fourth set (Amendment 4)
Twelve more stations (seven US automated stations reporting every 20 minutes at 0.1 C, five Australian stations with irregular training years) tested a limits warm-up for stations whose training record left the noise limit unlearned. It cut their
false alarms from 45.4 % to 1.8 % and cost 6 points of noise-burst detection, so by the rule registered first it is **rejected** (kept as an operator's option, `refit.py --complete`). The fourth set also produced five more real-weather windows with a `FAULT`
(5 of 160): temperature pinned at 0 C for about nine hours in freezing rain (Fitch H Beach and La Porte, January 2024), and a +12.5 C night-time jump at Alice Springs. The freezing-point plateau is the same kind of cause as the saturated humidity of the first
post-mortem, and would need its own registered remedy and another unseen set. Details: Amendment 4 and its outcome in `config/protocol.md`.

### And a fifth set (Amendment 5)
A freezing-point remedy (a frozen temperature or humidity near 0 C in humid air is a soft flag) was registered and tested on twelve northern US airport stations nobody had looked at. The pipeline as shipped raised **no `FAULT` in any of their 180
real extreme-weather windows** (cold windows 0 of 26), clean false alarms were 2.0 % and the remedy changed no number at all, so rule (a), which needs strictly fewer windows with a `FAULT`, failed and the remedy is **not adopted**. The FRESH3 case is real but rare (two stations
in one January 2024 outbreak) and this set did not reproduce it; the test neither confirms nor refutes the remedy, and the limit stays open. Details: Amendment 5 and its outcome in `config/protocol.md`.

## 6. Limitations: what we do not claim and cannot see

### About the data
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

### About the results
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

### About novelty
- **No technique here is new.** Physics checks, persistence tests, CUSUM, Isolation Forest and SHAP are standard. See
  `docs/NOVELTY_AND_PRIOR_ART.md` for what is standard, what we adapted, and what is ours.
- **We are not the first to separate weather from faults.** ECMWF, the Oklahoma Mesonet and several SIH entries do it.
- **τ_RH (humidity response time) is research, not a feature.** It is not in the live pipeline and we do not claim it detects
  faults in the field. What exists is analysis code for a bench experiment and a simulation of where the idea breaks.
- **The pressure-tide test and a "35 °C wet-bulb is impossible" rule were dropped.** The wet-bulb check is a soft flag only.

### About the hardware and deployment
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

### What the system cannot see

1. **A constant offset present from the start.** No single-station method can see it.
2. **Drift slower than the detectability floor.** The dashboard shows the smallest slope it can see at this station now.
   On our real data that is several times the service limit within weeks.
3. **A drift that starts during a weather or seasonal transition.** The isolated-trend rule masks it until the transition ends.
4. **A stuck sensor that sits at a value the station commonly holds** for less than the learned frozen limit (about half a day
   to a day at hourly cadence, longer for humidity).
5. **Small noise increases.** At whole-degree resolution they are inside the rounding.
6. **Faults hidden inside data gaps.** The gap is reported; what happened inside it is not known.
7. **A weather event that looks exactly like a fault** (a real one-channel jump). Rule 2 would call it a fault. We tune toward
   protecting weather (mixed evidence is `SUSPECT`, not `FAULT`), and we report the FAULT rate on real extreme weather
   separately so the cost is visible.
8. **A humidity sensor stuck exactly at 100 %.** Since the ceiling-aware frozen rule was adopted (Amendment 2), this is a `SUSPECT`, not a `FAULT`: sustained
   heavy rain holds derived humidity at its ceiling for a day or more, and on twelve unseen stations that was the more common cause of a real-weather FAULT.
9. **A real one-sample jump larger than the fixed step cap** (a 47 % humidity rise in two hours after rain; a 16 C warming across a 6-hour reporting gap at an
   arid station). Still called a `FAULT` (3 of 139 real extreme-weather windows on the fresh stations). The fix we tried costs wrong-clock detection.
10. **Anything that needs a reference:** neighbour stations, a forecast model, a calibration record. By design we use none.

## 7. Related work and what is ours

### 7.1 What is standard

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

### 7.2 What we adapted

| What | From | What we changed | What we measured |
|---|---|---|---|
| Learned frozen-run limit | HadISD streak thresholds | Learned per station from clean history *online*, detects the station's reporting resolution, and grades the flag: a run just past the limit is `SUSPECT`, a run twice the limit is `FAULT` | On the six real DEV stations, switching the learned limits off (the ablation; fixed limits) makes **63.1 %** of clean samples alarm and gives FAULT on 28.6 % of real extreme-weather samples (all 30 windows); with learned, graded limits it is **1.9 %** and 0 FAULT verdicts in 30 windows (the fixed-limit version produced FAULTs from a real pressure plateau inside a cyclone) |
| Isolated-trend rule for drift | blind-calibration / environmental-vs-instrumental drift literature | Applied to the daily-mean residuals of a single station's three channels, with a persistence requirement | False drift claims on clean real data fell from **97.7 %** to about **1 %** of station-days |
| Autocorrelation-aware drift test | Mann-Kendall prewhitening literature | Daily means, AR(1)-inflated standard error, winsorised residuals, smooth (not stepped) climatology | see the drift table in `results/REPORT.md` |
| Common-mode / clock checks | HadISD diurnal-cycle timing check; industrial FDI | Implemented as layers T1/T2 that can be switched off; T1 evaluated on real data with an injected 3-hour clock shift | ablation row "without timing layer" |

### 7.3 What is ours

1. **The evidence standard.** Every other public repository we read for this problem statement is synthetic-only, reports
   unverified metrics, or has no metrics at all (the survey is in Section 7.4). AtmosGuard is evaluated on **26 real Indian
   airport stations (2016-2024, NOAA ISD)**, with:
   - a protocol written and committed before the holdout was read (`config/protocol.md`, lock file `data/holdout/.holdout_used`);
   - a holdout sealed **in time** (same six stations, 2022-2024) **and in space** (eight stations never used for any tuning,
     including three that report only every 3 hours);
   - extreme-weather windows picked by objective rules on the data, not by what the system says about them;
   - the false-alarm rate **on real cyclones, heat, cold and sharp fronts, reported separately** from the injected-fault score;
   - baselines and an ablation run on the same real data;
   - agreement with NOAA's own quality flags, described as agreement with another automated system;
   - the failures found and fixed, listed (Section 7.5).
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

### 7.4 The field on this problem statement

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

### 7.5 Failures real data exposed, and what we did

| Finding | Evidence | Fix |
|---|---|---|
| Fixed frozen and noise limits treat rounded values as stuck sensors | 63.1 % of clean DEV samples alarmed without them (1.9 % with), results table 2 | station-learned limits (`atmos/limits.py`) |
| A pressure plateau inside a cyclone reads as a frozen barometer | FAULT verdicts on real cyclone windows | two-tier frozen rule: soft just past the limit, hard at twice the limit |
| The drift monitor claimed drift almost every day | 97.7 % of station-days | daily means, autocorrelation-aware test, isolated-trend rule, persistence (about 1 %) |
| The seasonal cycle read as drift through a step-function climatology | reproduced in a unit test | smooth (bilinear in month and hour) expected value |
| A communication gap made the *next, healthy* reading SUSPECT | gap flags counted as false alarms | gaps are notices on the reading, not verdict changes |

## 8. Reproducing this report

Times are for 4 CPU cores. The exact commands and the commit each result was produced under are in `results/RUNS.md`.

### Does it work?

```bash
python -m pytest -q                                   # 400+ tests, including the C++ edge-parity tests (needs g++)
```

### The evidence

| What | Command | Time | Writes |
|---|---|---|---|
| DEV results (six stations, 2020-2021) | `python evaluate_real.py --dev --workers 4 --out results/dev_run4.json` | 15 min | text report + JSON |
| The twelve FRESH stations (Amendment 2) | `python -m data_tools.make_fresh fetch` and `build`, then `python evaluate_real.py --fresh --workers 4 --out results/fresh_run1.json` | 1 h | **refused if already run**; explains verdicts: `python window_forensics.py --phase FRESH --station IXR` |
| Holdout in time and space | `python evaluate_real.py --holdout --workers 4 --out results/holdout_run1.json` | 30-40 min | **refused if already run**; `--force-rerun-holdout` reproduces it (that is how `holdout_run2` was made, see `results/RUNS.md`) |
| Summary, tables, README block, Q&A numbers | `python make_summary.py results/dev_run4.json results/holdout_run2.json results/fresh_run1.json --scale results/scale.json --coldstart results/coldstart.json --sensitivity results/sensitivity.json --readme README.md --numbers docs/JUDGE_QA.md docs/SUBMISSION_TEXT.md` | seconds | `results/summary.json`, `results/REPORT.md` |
| Technical report | `python make_report.py --docx` (`pip install pypandoc_binary` for the .docx) | seconds | `docs/TECHNICAL_REPORT.md`, `.docx` |
| Scale and speed | `python loadtest.py --stations 1 10 50 100` (on a quiet machine) | 12 min | `results/scale.json` |
| How big must a fault be? (detection against fault size, DEV) | `python evaluate_sensitivity.py --workers 4` (`--estimate` first) | 3 min | `results/sensitivity.json` |
| Cold start for a new station | `python evaluate_coldstart.py --estimate` first (projects the time), then `python evaluate_coldstart.py --workers 4` (`--resume` continues an interrupted run) | 9 min | `results/coldstart.json` |
| The same evaluation on your own station CSV | `python evaluate_csv.py your.csv --station NAME` | 5-15 min | prints (see `docs/USE_YOUR_DATA.md`) |
| Offline demo page | `python make_offline_demo.py` | 1 min | `docs/demo/index.html` |
| Figures | `python make_figures.py` | 1 min | `docs/figures/*.png` |
| Diagrams, one-page PDF, dashboard screenshots and video | `python make_diagrams.py`, `python make_onepager.py`, `python capture_dashboard.py` (Playwright and a Chromium) | 3 min | `docs/figures/diagram_*`, `docs/AtmosGuard_one_page.*`, `docs/screenshots/`, `docs/demo/*.webm` |
| Humidity response-time research | `python research/tau_rh.py study` and `selftest` | seconds | prints |
| Synthetic plumbing check (not a result) | `python evaluate.py --synthetic` | 1 min | prints |

`--quick` on `evaluate_real.py` (one year, one fault round) and `--parts drift,detect,events,noaa,latency` are for tuning loops only.

### Determinism

One seed (`seed: 42`) drives the fault plans, the Isolation Forest and the synthetic generators. Same code, same data,
same seed give the same numbers, except timing figures (they depend on the machine) and library-version differences in
the Isolation Forest scores.

## References

1. Smith, A., Lott, N., Vose, R. (2011). The Integrated Surface Database: recent developments and partnering with the National Climatic Data Center. *Bulletin of the American Meteorological Society* 92, 704-708.
2. Dunn, R. J. H., Willett, K. M., Thorne, P. W., et al. (2012). HadISD: a quality-controlled global synoptic report database for selected variables at long-term stations from 1973-2011. *Climate of the Past* 8, 1649-1679.
3. Dunn, R. J. H., Willett, K. M., Parker, D. E., Mitchell, L. (2016). Expanding HadISD: quality-controlled, sub-daily station data from 1931. *Geoscientific Instrumentation, Methods and Data Systems* 5, 473-491.
4. Shafer, M. A., Fiebrich, C. A., Arndt, D. S., Fredrickson, S. E., Hughes, T. W. (2000). Quality assurance procedures in the Oklahoma Mesonetwork. *Journal of Atmospheric and Oceanic Technology* 17, 474-494.
5. Fiebrich, C. A., Morgan, C. R., McCombs, A. G., Hall, P. K., McPherson, R. A. (2010). Quality assurance procedures for mesoscale meteorological data. *Journal of Atmospheric and Oceanic Technology* 27, 1565-1582.
6. World Meteorological Organization. *Guide to Instruments and Methods of Observation* (WMO-No. 8).
7. Alduchov, O. A., Eskridge, R. E. (1996). Improved Magnus form approximation of saturation vapor pressure. *Journal of Applied Meteorology* 35, 601-609.
8. Stull, R. (2011). Wet-bulb temperature from relative humidity and air temperature. *Journal of Applied Meteorology and Climatology* 50, 2267-2269.
9. Liu, F. T., Ting, K. M., Zhou, Z.-H. (2008). Isolation Forest. *Proceedings of the IEEE International Conference on Data Mining*, 413-422.
10. Mahalanobis, P. C. (1936). On the generalised distance in statistics. *Proceedings of the National Institute of Sciences of India* 2, 49-55.
11. Page, E. S. (1954). Continuous inspection schemes. *Biometrika* 41, 100-115.
12. Mann, H. B. (1945). Nonparametric tests against trend. *Econometrica* 13, 245-259.
13. Sen, P. K. (1968). Estimates of the regression coefficient based on Kendall's tau. *Journal of the American Statistical Association* 63, 1379-1389.
14. Lundberg, S. M., Lee, S.-I. (2017). A unified approach to interpreting model predictions. *Advances in Neural Information Processing Systems* 30.
15. Ibrom, A., Dellwik, E., Flyvbjerg, H., Jensen, N. O., Pilegaard, K. (2007). Strong low-pass filtering effects on water vapour flux measurements with closed-path eddy correlation systems. *Agricultural and Forest Meteorology* 147, 140-156.
16. Mammarella, I., Launiainen, S., Gronholm, T., et al. (2009). Relative humidity effect on the high-frequency attenuation of water vapor flux measured by a closed-path eddy covariance system. *Journal of Atmospheric and Oceanic Technology* 26, 1856-1866.

Further sources (ECMWF observation monitoring, MADIS, sensor-network drift literature, the public repositories surveyed) are named next to the claim they support in Section 7 and in `docs/NOVELTY_AND_PRIOR_ART.md`.
