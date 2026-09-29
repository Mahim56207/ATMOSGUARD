"""Real station data from NOAA's Integrated Surface Database (ISD), "global hourly" open-data bucket.

Source (public, no key): https://noaa-global-hourly-pds.s3.amazonaws.com/<year>/<USAF><WBAN>.csv
Each row is one surface report (METAR = FM-15, SYNOP = FM-12, ...). We use only the three channels the problem
allows and NOTHING else from the report (no wind, rain, visibility, cloud):

  temperature_c  <- TMP   (tenths of a degree C)
  humidity_pct   <- computed from TMP and DEW (Magnus / Alduchov-Eskridge). RH is NOT reported by ISD.
  pressure_hpa   <- METAR: altimeter setting (QNH, whole hPa) from MA1;  SYNOP: sea-level pressure (SLP, 0.1 hPa)

Every value keeps NOAA's own quality code as a side column (`noaa_flag`: 0 none, 1 suspect, 2 erroneous). It is
never used to make a verdict; it is only the weak label for the "agreement with NOAA QC" comparison.

Honest limits, printed in the docs too:
  * METAR values are whole degrees / whole hPa (resolution 1). The pipeline has to cope with that (atmos/limits.py).
  * RH is derived from the dew point, so T and RH are not independent measurements here.
  * These are airport stations, not IMD AWS units. IMD AWS records are not public.

Usage:
    python -m data_tools.isd fetch --years 2014 2024          # download raw files into data/raw (git-ignored)
    python -m data_tools.isd build                            # write hourly CSVs into data/real/<station>/
"""
from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import yaml

BASE_URL = "https://noaa-global-hourly-pds.s3.amazonaws.com"
REPO = Path(__file__).resolve().parent.parent
RAW_DIR = REPO / "data" / "raw" / "isd"
REAL_DIR = REPO / "data" / "real"
CATALOG = Path(__file__).resolve().parent / "stations_real.yaml"

# Magnus constants (Alduchov & Eskridge 1996), the same family the L0 physics layer uses
_A, _B = 17.625, 243.04


def rh_from_dew_point(t_c: np.ndarray, td_c: np.ndarray) -> np.ndarray:
    """Relative humidity (%) from air temperature and dew point (degC). Clipped to 0-100: METAR rounding can
    make the dew point 1 degC above the temperature, which is a rounding artefact, not supersaturation."""
    es_t = np.exp(_A * t_c / (_B + t_c))
    es_td = np.exp(_A * td_c / (_B + td_c))
    return np.clip(100.0 * es_td / es_t, 0.0, 100.0)


def load_catalog(path: Path = CATALOG) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------------ download
def raw_path(file_id: str, year: int, raw_dir: Path = RAW_DIR) -> Path:
    return raw_dir / f"{year}_{file_id}.csv"


def download(file_id: str, year: int, raw_dir: Path = RAW_DIR, retries: int = 4) -> Optional[Path]:
    """Fetch one station-year. Returns None if NOAA has no such file (404). Already-downloaded files are kept."""
    dest = raw_path(file_id, year, raw_dir)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"{BASE_URL}/{year}/{file_id}.csv"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                data = resp.read()
            dest.write_bytes(data)
            return dest
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return None
            err = e
        except Exception as e:                                  # network hiccup: retry with back-off
            err = e
        time.sleep(2 ** (attempt + 1))
    print(f"  failed {url}: {err}", file=sys.stderr)
    return None


def fetch_all(file_ids: list[str], years: list[int], workers: int = 6) -> dict[tuple[str, int], Optional[Path]]:
    jobs = [(f, y) for f in file_ids for y in years]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        got = list(pool.map(lambda j: download(*j), jobs))
    return dict(zip(jobs, got))


# ------------------------------------------------------------------------------------------------ parse
_QC_ERRONEOUS = set("37")     # NOAA: 3 = erroneous, 7 = erroneous (value changed by the human validator)
_QC_SUSPECT = set("26")       # NOAA: 2 = suspect, 6 = suspect


def _field(series: pd.Series, part: int) -> pd.Series:
    return series.astype("string").str.split(",", expand=True).reindex(columns=range(part + 1)).iloc[:, part]


def _num(series: pd.Series, part: int, scale: float, missing: float) -> pd.Series:
    x = pd.to_numeric(_field(series, part), errors="coerce")
    return (x.where(x != missing)) / scale


def parse_raw(path: Path) -> pd.DataFrame:
    """One raw ISD file -> one row per report: ts, rtype, t, td, slp, alt, qc_t, qc_td, qc_p. UTC timestamps."""
    d = pd.read_csv(path, usecols=lambda c: c in {"DATE", "REPORT_TYPE", "TMP", "DEW", "SLP", "MA1"},
                    low_memory=False, dtype=str)
    for col in ("TMP", "DEW", "SLP", "MA1"):          # some station-years have no pressure group at all
        if col not in d.columns:
            d[col] = pd.NA
    out = pd.DataFrame({
        "ts": pd.to_datetime(d["DATE"]),
        "rtype": d["REPORT_TYPE"].str.strip(),
        "t": _num(d["TMP"], 0, 10.0, 9999),
        "td": _num(d["DEW"], 0, 10.0, 9999),
        "slp": _num(d["SLP"], 0, 10.0, 99999),
        "alt": _num(d["MA1"], 0, 10.0, 99999),
        "qc_t": _field(d["TMP"], 1),
        "qc_td": _field(d["DEW"], 1),
        "qc_slp": _field(d["SLP"], 1),
        "qc_alt": _field(d["MA1"], 1),
    })
    return out


def _flag_rank(codes: pd.Series) -> pd.Series:
    """0 = fine/missing, 1 = suspect, 2 = erroneous, per value."""
    c = codes.fillna("9").astype(str)
    return np.where(c.isin(_QC_ERRONEOUS), 2, np.where(c.isin(_QC_SUSPECT), 1, 0))


def to_series(reports: pd.DataFrame, source: str, cadence_minutes: int = 60, any_minute: bool = False) -> pd.DataFrame:
    """Reports -> a regular-ish series in AtmosGuard's CSV layout.

    source 'metar': routine METAR only (FM-15), pressure = altimeter setting (QNH).
    source 'synop': SYNOP only (FM-12), pressure = sea-level pressure.
    Only reports on the cadence grid (minute 0 for hourly, minutes 0 and 30 for half-hourly; `any_minute` keeps every routine report) are kept; SPECI and
    off-grid reports are dropped. A time with no report simply has no row: real gaps stay gaps.
    """
    rtype = {"metar": "FM-15", "synop": "FM-12"}[source]
    pcol, qcol = ("alt", "qc_alt") if source == "metar" else ("slp", "qc_slp")
    r = reports[reports["rtype"] == rtype].copy()
    step = cadence_minutes
    on_grid = (r["ts"].dt.minute % step == 0) if step < 60 else (r["ts"].dt.minute == 0)
    if any_minute:                     # automated stations that report at a fixed offset (a US AWOS at :15, :35, :55): keep every routine report
        on_grid = pd.Series(True, index=r.index)
        r = r.sort_values("ts")           # some years carry a second copy of each report one minute later: keep the first of any reports less than 5 minutes apart
        keep, last = [], None
        for t in r["ts"]:
            ok = last is None or (t - last).total_seconds() >= 300
            keep.append(ok)
            if ok:
                last = t
        r = r[pd.Series(keep, index=r.index)]
        on_grid = pd.Series(True, index=r.index)
    r = r[on_grid & r["t"].notna() & r["td"].notna() & r[pcol].notna()]
    r = r.drop_duplicates("ts", keep="first").sort_values("ts")
    flag = np.maximum.reduce([_flag_rank(r["qc_t"]), _flag_rank(r["qc_td"]), _flag_rank(r[qcol])])
    return pd.DataFrame({
        "timestamp": r["ts"].dt.strftime("%Y-%m-%dT%H:%M:%S").values,
        "temperature_c": r["t"].round(1).values,
        "pressure_hpa": r[pcol].round(1).values,
        "humidity_pct": np.round(rh_from_dew_point(r["t"].values, r["td"].values), 1),
        "noaa_flag": flag,
    })


def build_station(station: dict, years: list[int], raw_dir: Path = RAW_DIR, cadence_minutes: int = 60
                  ) -> pd.DataFrame:
    frames = []
    for y in years:
        p = raw_path(station["file"], y, raw_dir)
        if not p.exists():
            continue
        frames.append(to_series(parse_raw(p), station["source"], cadence_minutes, bool(station.get("any_minute", False))))
    if not frames:
        return pd.DataFrame(columns=["timestamp", "temperature_c", "pressure_hpa", "humidity_pct", "noaa_flag"])
    return pd.concat(frames, ignore_index=True)


def coverage(df: pd.DataFrame, cadence_minutes: int = 60) -> dict[int, float]:
    """Share of expected samples present, per year."""
    ts = pd.to_datetime(df["timestamp"])
    out = {}
    for y, g in ts.groupby(ts.dt.year):
        expected = (366 if y % 4 == 0 else 365) * 24 * 60 / cadence_minutes
        out[int(y)] = round(len(g) / expected, 3)
    return out


# ------------------------------------------------------------------------------------------------ CLI
def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Fetch and build real NOAA ISD station data.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="download raw station-years into data/raw/isd")
    f.add_argument("--years", type=int, nargs=2, default=None, metavar=("FIRST", "LAST"))
    f.add_argument("--stations", nargs="*", default=None)
    b = sub.add_parser("build", help="write processed CSVs into data/real/<station>/")
    b.add_argument("--stations", nargs="*", default=None)
    b.add_argument("--cadence", type=int, default=60, choices=(30, 60))
    args = ap.parse_args(argv)

    cat = load_catalog()
    stations = {k: v for k, v in cat["stations"].items() if not args.stations or k in args.stations}
    if args.cmd == "fetch":
        first, last = args.years or (cat["years"]["first"], cat["years"]["last"])
        res = fetch_all([s["file"] for s in stations.values()], list(range(first, last + 1)))
        missing = sorted(f"{k[1]}/{k[0]}" for k, v in res.items() if v is None)
        print(f"downloaded {sum(v is not None for v in res.values())} files; missing: {missing or 'none'}")
        return 0
    REAL_DIR.mkdir(parents=True, exist_ok=True)
    for sid, st in stations.items():
        years = list(range(st.get("first_year", cat["years"]["first"]), cat["years"]["last"] + 1))
        df = build_station(st, years, cadence_minutes=args.cadence)
        out = REAL_DIR / sid
        out.mkdir(parents=True, exist_ok=True)
        df.insert(0, "station_id", sid)
        df.to_csv(out / f"{sid}_{args.cadence}min.csv", index=False)
        cov = coverage(df, args.cadence)
        print(f"{sid}: {len(df)} rows, coverage by year {cov}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
