# What was run to produce the results in this directory

Every result file here was written by a command in this table, on the code state named beside it. Nothing was edited by hand.

| File | Command | Code state | What it is |
|---|---|---|---|
| `history/dev_run1.*`, `history/dev_run2.*` | `python evaluate_real.py --dev` | earlier commits, see `history/README.md` | Earlier DEV runs, kept for the record. Not current results. |
| `dev_run3.json`, `.txt` | `python evaluate_real.py --dev --workers 4 --out results/dev_run3.json` | `9cd24f1` (the freeze) | DEV, **registered criterion** only (any alarm in the fault window). The DEV numbers quoted in `config/protocol.md`. |
| `holdout_run1.json`, `.txt` | `python evaluate_real.py --holdout --workers 4 --out results/holdout_run1.json` | `9cd24f1` (lock file `data/holdout/.holdout_used`) | **The single registered holdout run**, in time and in space. Registered criterion only. Kept unedited. |
| `dev_run4.json`, `.txt` | `python evaluate_real.py --dev --workers 4 --out results/dev_run4.json` | `d29eb02` (pipeline files unchanged since) | The same DEV evaluation re-scored with Amendment 1 (paired detection, table 1) and the registered criterion (table 1b). |
| `holdout_run2.json`, `.txt` | `python evaluate_real.py --holdout --force-rerun-holdout --workers 4 --out results/holdout_run2.json` | `d29eb02` (pipeline files unchanged since) | The holdout again, with both criteria. Made only to score detection under Amendment 1; **no tuning followed**. |
| `scale.json` | `python loadtest.py --stations 1 10 50 100` | `d29eb02` + `loadtest.py` fixed in the commit that adds the station-id regression test | Scale and speed on simulated stations, one machine, every layer on, plus rows with the Isolation Forest layer off. An earlier `scale.json` (committed before this fix) fed readings under a different station id, so its pipeline ran with no per-station models; it was replaced. |
| `coldstart.json` | `python evaluate_coldstart.py --workers 4 --out results/coldstart.json` (after `--estimate`, which projected 8 min) | `d29eb02` + the instrumented runner (pipeline files unchanged) | Leave-one-station-out cold-start study on the six DEV stations: 42 jobs, 9 minutes on 4 workers. An earlier attempt with the first version of the runner (one job per station, no progress output) was stopped after 90 minutes and its output discarded; the current runner scores the Isolation Forest in batches (verdicts identical, tested) and reports its own ETA. |
| `summary.json`, `REPORT.md` | `python make_summary.py results/dev_run4.json results/holdout_run2.json --scale results/scale.json --coldstart results/coldstart.json --readme README.md --numbers docs/JUDGE_QA.md docs/SUBMISSION_TEXT.md` | generated | The tables everything else reads. |

## The pipeline did not change between the freeze and the reruns
`git diff 9cd24f1 HEAD -- atmos config/settings.yaml` shows only a new `atmos/explain.py` (the `/explain` endpoint), an optional retention method
in `atmos/store.py`, and an `api:` block in the settings. `evaluate_real.py` changed only to add the paired detection score (memoised predictions, the paired count, and a
two-table detection printout; Amendment 1 in `config/protocol.md`); the registered count is computed as before.

## Determinism check
`python compare_runs.py results/holdout_run1.json results/holdout_run2.json` compared **61,019** numbers (counts, delays and rates for every station and
configuration; timings excluded) and found **0 differences**. `python compare_runs.py results/dev_run3.json results/dev_run4.json` compared
**16,615** numbers and found **0 differences**. The rerun is deterministic, so the registered-criterion numbers in `holdout_run2` are exactly those
of the single registered run, and the only new content is the paired detection score.

## Timing numbers
The "speed" line at the bottom of each evaluation result was measured while four worker processes shared four cores, so it is an upper bound.
The number to quote is `scale.json`, measured with `python loadtest.py` on a machine doing nothing else.
