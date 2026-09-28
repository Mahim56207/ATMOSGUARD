# Reproduce everything

A stranger with a laptop should be able to get from a fresh clone to every number in `results/REPORT.md`. Times are for
4 CPU cores. Python 3.13 is what the pinned `requirements.txt` and the Dockerfile target (3.11 and 3.12 also work with newer
unpinned versions of the same libraries).

```bash
git clone https://github.com/Mahim56207/ATMOSGUARD && cd ATMOSGUARD
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 1. Does it work? (about 1 minute)
```bash
python -m pytest -q                                   # 340+ tests, including the C++ edge-parity tests (needs g++)
```

## 2. Run it (the committed models and real data are in the repo)
```bash
uvicorn api:app --port 8000                           # API, docs at http://localhost:8000/docs
streamlit run dashboard.py                            # dashboard, http://localhost:8501
python replay.py data/demo/fani_BBI_2019-05.csv --speed 0   # or use the dashboard's Control panel
open docs/demo/index.html                             # the offline replay page: no server needed
docker compose up --build                             # the same, in containers
```
Retrain the six station models from the committed real data (deterministic, about 1 minute): `python train.py --all`.

## 3. The evidence
| What | Command | Time | Writes |
|---|---|---|---|
| DEV results (six stations, 2020-2021) | `python evaluate_real.py --dev --workers 4 --out results/dev_run3.json` | 15 min | text report + JSON |
| Holdout in time and space | `python evaluate_real.py --holdout --out results/holdout_run1.json` | 30-40 min | **refused if already run**; `--force-rerun-holdout` reproduces it |
| Summary, tables, report | `python make_summary.py results/dev_run3.json results/holdout_run1.json --scale results/scale.json` | seconds | `results/summary.json`, `results/REPORT.md` |
| Scale and speed | `python loadtest.py` (on a quiet machine) | 5 min | `results/scale.json` |
| Cold start for a new station | `python evaluate_coldstart.py --workers 4` | 10 min | `results/coldstart.json` |
| Offline demo page | `python make_offline_demo.py` | 1 min | `docs/demo/index.html` |
| Figures | `python make_figures.py` | 1 min | `docs/figures/*.png` |
| Humidity response-time research | `python research/tau_rh.py study` and `selftest` | seconds | prints |
| Synthetic plumbing check (not a result) | `python evaluate.py --synthetic` | 1 min | prints |

`--quick` on `evaluate_real.py` (one year, one fault round) and `--parts drift,detect,events,noaa,latency` are for tuning loops only.

## 4. The data (optional: the processed CSVs are committed)
```bash
python -m data_tools.isd fetch --years 2016 2024      # ~1 GB from NOAA's open-data bucket into data/raw/isd (git-ignored)
python -m data_tools.isd build
python -m data_tools.make_dataset                     # DEV / HOLDOUT split and the event windows
python -m data_tools.make_demo_data                   # data/demo/*.csv
```
Fetching needs internet access to `noaa-global-hourly-pds.s3.amazonaws.com`.

## 5. Firmware
```bash
python firmware/node/gen_config.py                    # limits header from settings.yaml (--check to verify)
```
then Arduino IDE (`docs/HARDWARE.md`). The L0 logic is tested on the laptop by `tests/test_edge_parity.py`.

## Determinism
One seed (`seed: 42`) drives the fault plans, the Isolation Forest and the synthetic generators. Same code, same data,
same seed give the same numbers, except timing figures (they depend on the machine) and library-version differences in
the Isolation Forest scores.

## What was run to produce the committed results
The exact commands and the commit each ran under are recorded in `results/RUNS.md`.
