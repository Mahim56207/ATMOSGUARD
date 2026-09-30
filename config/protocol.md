# Evaluation protocol

**This file is committed BEFORE the first holdout run.** `evaluate_real.py --holdout` refuses to run unless this file is
tracked by git, has no uncommitted changes, and has no unfinished markers. The commit that adds this text is the proof of
order. The holdout is read once; a lock file (`data/holdout/.holdout_used`) records when and under which commit.

Whatever the holdout gives is reported, including if it is worse than DEV.

## What is evaluated
The full pipeline (`evaluate_real.py`), on **real** NOAA ISD airport records, 14 Indian stations, 2016-2024
(`docs/DATA.md`). Injected faults are injected; everything else is real weather with nothing changed.
(`evaluate.py --synthetic` is a plumbing check on fake weather and is not a result.)

## Data split
| Set | Stations | Years | Use |
|---|---|---|---|
| Training | every station, on its **own** record | 2016-2019, extreme-weather windows and NOAA-flagged values removed | fit the normality table, Isolation Forest, Mahalanobis model, learned limits |
| DEV | Bhubaneswar, Chennai, Kolkata, Delhi, Jaipur, Thiruvananthapuram (hourly METAR) | 2020-2021 | **tuning was allowed here** |
| HOLDOUT in time | the same six | 2022-2024 | sealed until the single holdout run |
| HOLDOUT in space | Ahmedabad, Nagpur, Mumbai, Guwahati, Visakhapatnam (hourly METAR) and Port Blair, Bhuj, Cochin (3-hourly SYNOP) | 2020-2024 | sealed; no threshold was ever chosen by looking at these stations |

`data/holdout/` is read only by `evaluate_real.py` after its guard passes. `replay.py` and the API's `/replay` refuse it.
The demo data (`data/demo/`) use DEV-period events only.

## Extreme-weather windows (chosen by rule on the data, before looking at any verdict)
| Kind | Rule | Window |
|---|---|---|
| low | pressure at least 10 hPa below its trailing 30-day median; the 8 deepest per station | +/- 3 days |
| heat | top 0.3 % of daily maximum temperature; up to 5 per station, 7 days apart | +/- 3 days |
| cold | bottom 0.3 % of daily minimum temperature; up to 5 per station | +/- 3 days |
| sharp | the largest 3-hour temperature change of each year | +/- 2 days |

`data/real/events.json` holds the rules and every window. Windows are removed from a station's training data and its clean
evaluation data. A window is fed with two extra days of lead-in that are not counted. NOAA-flagged values are cut out of the
windows (they are analysed separately in the agreement table).

## The numbers, always separate, for every configuration
1. **Detection of injected faults**, per type: frozen (48 h), spike (1 sample), level shift (24 h), noise burst (24 h),
   dropout (3 samples), clock shift by 3 h (4 days). Seeded plans (`seed` in `config/settings.yaml`), 2 rounds on DEV. A fault
   is detected if there is an alarm from its first sample to its last plus 60 minutes. Also reported: median minutes to the first alarm.
2. **False alarms on clean real data**: share of samples that get `FAULT` or `SUSPECT` (an alarm); share that get `FAULT`;
   share that get `WEATHER` (not an alarm).
3. **Real extreme weather**: share of samples that get `FAULT` (a failure), `SUSPECT`, `WEATHER`, `VALID`; number of windows
   containing at least one `FAULT`; and the same by kind of window.
4. **Agreement with NOAA's own quality flags** on the raw record: how often AtmosGuard alarms on, and escalates, flagged
   values, and on values NOAA did not flag. Another automated system, not ground truth.
5. **Slow drift** (health monitor, not alarms): a ramp over 45 days is added to one channel of clean real chunks (at least 80
   days long), reaching 1, 2, 4 or 8 times the service limit (T 0.5 C, P 1 hPa, RH 3 %); detected = significant with the right sign;
   plus **false drift claims** on the same real weather with no ramp, and on all clean station-days.
6. **Speed**: median and 95th percentile time per reading (`loadtest.py` on an otherwise quiet machine is the number to quote).

Rates on small counts are shown with the count (`make_summary.py` adds Wilson 95 % intervals to the headline).

## Configurations (same data, same three numbers)
- **full**;
- **ablations**, each one layer off by its config flag (no code edits): physics, health, normality, Isolation Forest, Mahalanobis,
  timing, station-learned limits;
- **baselines**: range check only; textbook range + step + persistence (fixed limits, 6 h identical, the guide's Appendix A step limits);
  climatology z-score only; Isolation Forest only; Mahalanobis distance only (the other common approach on this problem).
  Fitted on the same training data.

## Definitions
- **Alarm:** verdict `FAULT` or `SUSPECT`. `WEATHER` is a correct answer on real weather, so it is not an alarm; its share is printed beside.
- **A communication gap** is a notice on the reading, never an alarm.
- **Confidence** is agreement between checks. It is not used in any metric and is not a probability.

## Tuning log (everything changed after looking at DEV, and why)
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

## Holdout procedure
1. Freeze the code and `config/settings.yaml`. Commit this file (this commit).
2. `python evaluate_real.py --holdout --out results/holdout_run1.json` runs once. It writes the lock file; a second run is refused
   (`--force-rerun-holdout` reproduces a run that was already made; the original lock stays in git history).
3. `python make_summary.py results/dev_run3.json results/holdout_run1.json --scale results/scale.json` builds `results/summary.json`
   and `results/REPORT.md`. Nothing is tuned afterwards.

## Known limits of this protocol
- The stations are airport records with derived humidity and whole-degree, whole-hPa reporting.
- No labelled real faults exist: detection is on injected faults.
- Windows chosen by rule can still contain a real sensor fault that neither we nor NOAA flagged.
- The DEV stations were also used to look at failure cases, which is why they are the optimistic numbers.

## Amendment 1 (written after `holdout_run1` finished; the pipeline was not touched)
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

## Amendment 2 (written before the FRESH stations were evaluated)
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

## Amendment 2: outcome (written after `fresh_run1` finished; nothing was changed to make it come out this way)
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

## Amendment 3 (written before the FRESH2 stations were evaluated)
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

## Amendment 3: outcome (written after `fresh2_run1` finished; nothing was changed to make it come out this way)
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

## Amendment 4 (written before the FRESH3 stations were evaluated)
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

## Amendment 4: outcome (written after `fresh3_run1` finished; nothing was changed to make it come out this way)
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

## Amendment 5 (written before the FRESH4 stations were evaluated)
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
