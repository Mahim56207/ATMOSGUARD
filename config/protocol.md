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
