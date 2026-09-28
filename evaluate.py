"""Baselines, ablation, DEV vs HOLDOUT metrics. Reads data/holdout/ once, at the end.
Must always print three separate numbers: detection rate per fault type,
false-alarm rate on clean data, false-alarm rate on real extreme-weather windows (no faults injected).

Build step 6. STUB - not implemented yet.
Rules: thresholds come from config/settings.yaml (no magic numbers); windows in minutes;
layer is toggleable by a config flag; every check returns a reason string.
"""
