"""US Climate Reference Network (USCRN) 5-minute records, from NOAA's ISD "global hourly" open-data bucket.

The same public bucket as `data_tools/isd.py`: https://noaa-global-hourly-pds.s3.amazonaws.com/<year>/<USAF><WBAN>.csv
USCRN stations appear there with USAF 999999 and a 5-minute report stream (report type CRN05, about 12 reports an hour).
Each station carries THREE independent, aspirated platinum thermometers (CT1, CT2, CT3), which is what makes real labelled
sensor faults possible: a fault on one of the three shows up as a disagreement the other two do not share.

What is kept (and nothing else from the report): the merged air temperature (TMP), the three thermometers (CT1-3), the
5-minute temperature and relative humidity of the main probe (CH1), and the hourly aspirator fan speeds (CF1-3). There is
NO barometer in this stream.

    python -m data_tools.crn fetch --stations 40 --years 2016 2024 --out data/crn
    python -m data_tools.crn fetch --ids 03072 04990 --years 2022 2022 --out /tmp/crn_try

Each station-year is reduced on the fly to a small gzip CSV and the raw download is deleted (the raw files are 45 MB each).
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

BASE_URL = "https://noaa-global-hourly-pds.s3.amazonaws.com"
REPO = Path(__file__).resolve().parent.parent
MISSING = 9999

USE_COLUMNS = {"DATE", "REPORT_TYPE", "TMP", "CH1", "CT1", "CT2", "CT3", "CF1", "CF2", "CF3"}
OUT_COLUMNS = ["timestamp", "t_main", "t1", "t2", "t3", "q1", "q2", "q3", "rh", "rh_q", "f1", "f2", "f3"]


def _num(series: pd.Series, index: int, scale: float, missing: float = MISSING) -> pd.Series:
    """Field `index` of a comma separated ISD group, scaled; the ISD missing code becomes NaN."""
    part = series.str.split(",", expand=True)
    if index >= part.shape[1]:
        return pd.Series(np.nan, index=series.index)
    v = pd.to_numeric(part[index], errors="coerce")
    v = v.where(v.abs() < missing, np.nan)
    return v * scale


def _code(series: pd.Series, index: int) -> pd.Series:
    part = series.str.split(",", expand=True)
    if index >= part.shape[1]:
        return pd.Series(np.nan, index=series.index)
    return pd.to_numeric(part[index], errors="coerce")


def reduce_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """One ISD frame of a CRN station-year to the compact 5-minute frame (see OUT_COLUMNS)."""
    for col in USE_COLUMNS:                                     # some station-years lack a group altogether (older files carry no CH1, say)
        if col not in raw.columns:
            raw[col] = np.nan
    raw = raw[raw["REPORT_TYPE"] == "CRN05"].copy()
    ts = pd.to_datetime(raw["DATE"], errors="coerce")
    out = pd.DataFrame({"timestamp": ts})
    tmp = raw["TMP"].fillna("").astype(str)
    out["t_main"] = _num(tmp, 0, 0.1, missing=9999).where(_code(tmp, 1).isin([1, 5, 0]), np.nan)
    for i in (1, 2, 3):
        g = raw[f"CT{i}"].fillna("").astype(str)
        out[f"t{i}"] = _num(g, 0, 0.1, missing=9999)
        out[f"q{i}"] = _code(g, 1)
    ch = raw["CH1"].fillna("").astype(str)
    out["rh"] = _num(ch, 4, 0.1, missing=9999)
    out["rh_q"] = _code(ch, 5)
    for i in (1, 2, 3):
        g = raw[f"CF{i}"].fillna("").astype(str)
        out[f"f{i}"] = _num(g, 0, 1.0, missing=9999)
    out = out.dropna(subset=["timestamp"]).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    return out[OUT_COLUMNS]


def fetch_one(usaf_wban: str, year: int, out_dir: Path, retries: int = 4) -> Optional[Path]:
    dest = out_dir / f"{usaf_wban}_{year}.csv.gz"
    if dest.exists():
        return dest
    url = f"{BASE_URL}/{year}/{usaf_wban}.csv"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                raw = pd.read_csv(io.BytesIO(resp.read()), dtype=str, usecols=lambda c: c in USE_COLUMNS)
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 ** attempt)
        except Exception:
            time.sleep(2 ** attempt)
    else:
        print(f"  giving up on {usaf_wban} {year}", file=sys.stderr)
        return None
    red = reduce_frame(raw)
    if red.empty:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    red.to_csv(dest, index=False, compression="gzip", float_format="%.2f")
    return dest


def _job(job: tuple, out_dir: Path) -> Optional[Path]:
    return fetch_one(job[0], job[1], out_dir)


def crn_candidates(inventory_csv: Path, history_csv: Path, first_year: int, last_year: int, min_per_hour: float = 10.0) -> pd.DataFrame:
    """CRN stations (USAF 999999) that report about every 5 minutes in every year of the window, from NOAA's own inventory."""
    inv = pd.read_csv(inventory_csv, dtype={"USAF": str, "WBAN": str})
    hist = pd.read_csv(history_csv, dtype={"USAF": str, "WBAN": str})
    months = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
    inv["per_hr"] = inv[months].sum(axis=1) / 8760.0
    wide = inv[inv["USAF"] == "999999"].pivot_table(index=["USAF", "WBAN"], columns="YEAR", values="per_hr")
    years = list(range(first_year, last_year + 1))
    ok = wide[(wide.reindex(columns=years).min(axis=1) >= min_per_hour)].reset_index()
    return ok.merge(hist[["USAF", "WBAN", "STATION NAME", "CTRY", "STATE", "LAT", "LON", "ELEV(M)"]], on=["USAF", "WBAN"], how="left")


DEV_STATIONS = ("03047", "03048", "03054", "03055", "03060", "03062", "03063", "03067")      # WBAN numbers; the labelling rules in evaluate_crn.py were settled on these
SEALED_SEED = 23
SEALED_N = 24


def station_ids(directory: Path) -> list[str]:
    """WBAN numbers that have a file for every year 2016-2024 in `directory`."""
    years: dict[str, set[int]] = {}
    for p in directory.glob("999999*_*.csv.gz"):
        wban, year = p.name[6:].split(".")[0].split("_")
        years.setdefault(wban, set()).add(int(year))
    return sorted(w for w, ys in years.items() if ys >= set(range(2016, 2025)))


def gate(directory: Path, wban: str) -> tuple[bool, dict]:
    """A station enters the sealed pool when, in every year 2016-2024, each of the three thermometers and the humidity probe has at least 95 % of the 5-minute samples present."""
    worst = {"t1": 1.0, "t2": 1.0, "t3": 1.0, "rh": 1.0}
    for y in range(2016, 2025):
        d = pd.read_csv(directory / f"999999{wban}_{y}.csv.gz", usecols=["timestamp", "t1", "t2", "t3", "rh"])
        expected = (366 if y % 4 == 0 else 365) * 288
        for c in worst:
            worst[c] = min(worst[c], float(d[c].notna().sum()) / expected)
    return all(v >= 0.95 for v in worst.values()), {k: round(v, 3) for k, v in worst.items()}


def build_manifest(directory: Path, seed: int = SEALED_SEED, n: int = SEALED_N) -> dict:
    """The development stations (fixed above) and a seeded random sample of `n` of the other stations that pass the gate, with the sha256 of every compact file so anyone can
    download the same records again and check them."""
    import hashlib
    import random
    ids = station_ids(directory)
    passing = {w: g for w in ids for ok, g in [gate(directory, w)] if ok}
    pool = sorted(w for w in passing if w not in DEV_STATIONS)
    random.Random(seed).shuffle(pool)
    sealed = sorted(pool[:n])
    files = {}
    for w in (*DEV_STATIONS, *sealed):
        for y in range(2016, 2025):
            p = directory / f"999999{w}_{y}.csv.gz"
            if p.exists():
                files[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return {"seed": seed, "gate": "every year 2016-2024: t1, t2, t3 and rh present on at least 95 % of 5-minute samples", "stations_with_all_years": len(ids),
            "stations_passing_the_gate": len(passing), "dev_stations": list(DEV_STATIONS), "sealed_stations": sealed, "sha256": files}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("manifest", help="choose the sealed stations (seeded) and write manifest.json with file hashes")
    m.add_argument("--dir", type=Path, default=REPO / "data" / "crn")
    f = sub.add_parser("fetch")
    f.add_argument("--ids", nargs="*", help="WBAN numbers (USAF is 999999), e.g. 03072")
    f.add_argument("--stations", type=int, default=0, help="take this many stations from NOAA's inventory (all if 0 and no --ids)")
    f.add_argument("--years", nargs=2, type=int, default=[2016, 2024])
    f.add_argument("--out", type=Path, default=REPO / "data" / "crn")
    f.add_argument("--inventory", type=Path, default=Path("/tmp/isd-inventory.csv"))
    f.add_argument("--history", type=Path, default=Path("/tmp/isd-history.csv"))
    f.add_argument("--workers", type=int, default=6)
    a = ap.parse_args(argv)
    if a.cmd == "manifest":
        man = build_manifest(a.dir)
        (a.dir / "manifest.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
        print(f"{man['stations_with_all_years']} stations have all nine years, {man['stations_passing_the_gate']} pass the gate; sealed: {', '.join(man['sealed_stations'])}")
        return 0
    if a.ids:
        ids = [f"999999{w}" for w in a.ids]
    else:
        cand = crn_candidates(a.inventory, a.history, a.years[0], a.years[1])
        if a.stations:
            cand = cand.head(a.stations)
        ids = [f"{u}{w}" for u, w in zip(cand["USAF"], cand["WBAN"])]
    jobs = [(i, y) for i in ids for y in range(a.years[0], a.years[1] + 1)]
    done = 0
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        for res in ex.map(_job, jobs, [a.out] * len(jobs), chunksize=4):
            done += 1
            if done % 20 == 0:
                print(f"{done}/{len(jobs)}", flush=True)
    print(f"done: {done} station-years into {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
