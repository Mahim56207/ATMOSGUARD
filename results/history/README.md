# Earlier DEV runs (kept for the record, not current results)

| Run | Code state | Note |
|---|---|---|
| `dev_run1` | learned limits, graded frozen, new drift monitor; no Mahalanobis layer, rule 2 checked flags not movement, no coherent-level WEATHER | 2 of 30 real windows had a FAULT (thunderstorm outflows); level shift 74 %, noise 66 % |
| `dev_run2` | + rule 2 quiet check, Mahalanobis layer, coherent-level WEATHER | quiet threshold still a share of the step cap (too loose at 3-hourly cadence) |

The current DEV result is `results/dev_run3.*` (final code, the state the holdout was run on).
