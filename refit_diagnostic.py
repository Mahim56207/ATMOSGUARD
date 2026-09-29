"""Post-hoc diagnostic on the FRESH2 Australian AWS: what a REFIT at the current cadence does. Not sealed evidence.

    python refit_diagnostic.py --out results/fresh2_refit_diagnostic.json

The FRESH2 result showed 13.6 % clean false alarms on the seven Australian AWS, concentrated at four whose 2016-2019 records are irregular (16 reports a day with
alternating 1 h and 2 h gaps) while 2020-2024 is hourly all day: no noise limit could be learned from the old years. Here each station is fitted on 2020-2021 only
(hourly, all day) and judged on 2022-2024. The stations are the ones that revealed the problem, so this is a diagnosis of the cause, not a held-out test of a remedy:
nothing was tuned, the only change is which years the station-learned models are fitted on.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

import evaluate_real as er

AWS = ("CWS", "LEI", "WIL", "GLS", "COT", "THB", "MTC")
FIT_FROM, FIT_TO = pd.Timestamp("2020-01-01"), pd.Timestamp("2022-01-01")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    orig_read = er.read_frame

    def read_frame(path, settings, allow_holdout):
        df = orig_read(path, settings, allow_holdout)
        return df[df["timestamp"] >= FIT_FROM].reset_index(drop=True)          # the irregular 2016-2019 years are not used at all
    er.read_frame = read_frame
    er.TRAIN_END = FIT_TO
    meta = er.load_events("FRESH2")
    plans = [er.PhasePlan("FRESH2", sid, er.REAL_FRESH2_DIR / f"{sid}.csv", er.REAL_FRESH2_DIR / f"{sid}.csv",
                          (FIT_TO, pd.Timestamp("2025-01-01")), True) for sid in AWS]
    from concurrent.futures import ProcessPoolExecutor
    settings = er.load_settings()
    jobs = [(p, settings, False, meta["events"][p.station], frozenset({"detect", "events"})) for p in plans]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(er._worker, jobs))
    res = {"quick": False, "generated": pd.Timestamp.utcnow().isoformat(), "rules": meta["rules"], "stations": rows,
           "note": "fitted on 2020-2021 only, judged 2022-2024; post-hoc diagnostic, not sealed evidence"}
    args.out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    agg = er.aggregate(rows, "FRESH2")
    for name in ("full", "r3_expected_step", "baseline_rules"):
        c = agg["configs"][name]
        det = {t: round(100 * c["detection"][t]["detected_new"] / max(c["detection"][t]["injected"], 1)) for t in er.REAL_TYPES}
        print(name, "clean alarm %.2f%%" % (100 * c["clean"]["alarm"] / c["clean"]["n"]), det)
    for r in rows:
        c = r["configs"]["full"]["clean"]
        print(r["station"], "clean alarm %.1f%%" % (100 * c["alarm"] / c["n"]), {ch: v["noise_std"] is not None for ch, v in r["limits"].items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
