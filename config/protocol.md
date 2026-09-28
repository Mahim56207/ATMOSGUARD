# Evaluation Protocol

**Commit this file BEFORE the first holdout run.**

## Rules (from the setup guide)
- Tune on DEV data only.
- `data/holdout/` is read once, by `evaluate.py`, at the end.
- Fixed random seeds everywhere; results must reproduce exactly.
- `evaluate.py` always prints three separate numbers:
  1. Detection rate per fault type
  2. False-alarm rate on clean data
  3. False-alarm rate on real extreme-weather windows (no faults injected)

## To fill in before the first holdout run
- DEV / HOLDOUT split definition
- Fault types and injection settings
- Baselines
- Ablation list (one row per layer flag)
