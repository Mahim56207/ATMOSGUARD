# Evaluation Protocol

**This file must be committed BEFORE the first holdout run.** `evaluate.py --holdout` refuses to run unless this
file is tracked by git, has no uncommitted changes, and contains no unfinished markers.

## Rules (from the setup guide)
- Tune on DEV data only.
- `data/holdout/` is read once, by `evaluate.py`, at the end. Nothing else may read it (`replay.py` and `/replay` refuse it).
- Fixed random seeds everywhere (`seed` in `config/settings.yaml`); results must reproduce exactly.
- `evaluate.py` always prints three separate numbers, for every configuration:
  1. Detection rate per fault type
  2. False-alarm rate on clean data
  3. False-alarm rate on real extreme-weather windows (no faults injected)

## Data split
| Set | Where | Used for |
|---|---|---|
| DEV train | first `evaluate.train_fraction` of `data/clean/*.csv` (in time order) | fit the normality table and the IsolationForest |
| DEV clean-eval | the rest of `data/clean/*.csv` | number 2 (false alarms on clean data) and the base for fault injection (number 1) |
| DEV events | each file in `data/events/*.csv` (one window per file, with lead-in before the event) | number 3 |
| HOLDOUT clean | each file in `data/holdout/clean/*.csv` | number 2 and fault injection, on HOLDOUT |
| HOLDOUT events | each file in `data/holdout/events/*.csv` | number 3, on HOLDOUT |

Models are always fitted on DEV train only. HOLDOUT is never used for fitting or tuning.
One CSV file = one station. Columns: `timestamp, temperature_c, pressure_hpa, humidity_pct` (+ optional `station_id`).
The events files must be real extreme-weather windows with no faults injected. If a real sensor fault is known to be
inside a window, cut it out and note that in the run log.

## Definitions
- **Alarm:** the verdict is `FAULT` or `SUSPECT`. `WEATHER` is a correct answer on a weather window, so it is not an alarm.
  On clean data and on event windows, the share of `WEATHER` verdicts is printed next to the false-alarm rate.
- **Detection of an injected fault:** at least one alarm from the first faulty sample to the last faulty sample plus
  `evaluate.detection_grace_minutes`. Rate = detected faults / injected faults, per fault type.
- **False-alarm rate:** alarmed samples / all samples, on data with no injected faults.

## Fault injection
- Fault types (from the L1 checks): `frozen`, `spike`, `step`, `drift`, `noise`, `dropout`.
- Sizes, durations and placement come from the `injector` section of `config/settings.yaml`.
- `evaluate.injection_rounds` rounds, each with a different seeded plan. Same seed gives the same faults.

## Baselines
1. `baseline_range`: physical range check only (L0 ranges).
2. `baseline_range_persistence`: range check plus the frozen-value check (standard operational QC).
3. `baseline_isolation_forest`: the IsolationForest alone, alarm when its score is below the trained limit.

## Ablation
The full pipeline, then the full pipeline with one layer switched off by its config flag:
`no_physics`, `no_health`, `no_normality`, `no_mlmodel`, `no_timing`.
(`impute` does not change any verdict, so it is not ablated. `lstm_ae` is not built.)
The fault types above contain no timing fault (clock shift, co-jump), so `no_timing` only shows the effect of the
timing layer on false alarms, not on detection.

## Order of work
1. Tune thresholds on DEV only (`python evaluate.py`).
2. Finish and commit this file.
3. Run `python evaluate.py --holdout` once. A lock file (`data/holdout/.holdout_used`) is written; a second run is refused.
