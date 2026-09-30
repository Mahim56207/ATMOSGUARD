"""Choose the FRESH5 stations (Amendment 6 in config/protocol.md) by a rule fixed before any pipeline verdict is computed.

FRESH5 tests one remedy, for stations whose 2016-2019 record is NOT equally spaced (Australian Bureau of Meteorology automatic stations that reported about 16 times
a day with alternating 1 h and 2 h gaps and hourly, all day, from 2020). Six such stations are the test; six Australian stations with an ordinary hourly record in
both periods are the control (the remedy must change nothing there, and they show what ordinary detection looks like on the same kind of instrument).

The rule (applied to NOAA's own file listing, then to the downloaded records; never to a verdict):
  pool      SYNOP automatic stations with USAF 94xxxx or 95xxxx that have a file for every year 2016-2019 and 2022, are in no earlier catalog, and whose 2022 file is
            2.0-3.6 MB (a full hourly record at 0.1 resolution). Irregular pool: the 2017 file is 52-80 % of the size of the 2022 file. Regular pool: 93-110 %.
  order     a seeded shuffle of each pool (seed 17)
  gate      taken in that order, downloaded for 2016-2024, and kept when
              irregular   2016-2019: at most 65 % of the gaps between consecutive reports are exactly 60 min and at least 90 % are 60 or 120 min,
                          and at least 4,500 complete reports a year
              regular     2016-2019: at least 90 % of the gaps are exactly 60 min and at least 7,400 complete reports a year
              both        2020-2024: at least 7,400 complete reports a year (temperature, dew point and pressure all present), and every station's three
                          channels are present on at least 90 % of its reports
  take      the first six irregular and the first six regular stations that pass.

    python -m data_tools.select_fresh5 --write data_tools/stations_fresh5.yaml
"""
from __future__ import annotations

import argparse
import glob
import random
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

from . import isd

BUCKET = "https://noaa-global-hourly-pds.s3.amazonaws.com/"
HERE = Path(__file__).resolve().parent
SEED = 17
N_EACH = 6
HISTORY_URL = "https://noaa-isd-pds.s3.amazonaws.com/isd-history.csv"


def list_sizes(prefix: str) -> dict[str, int]:
    out: dict[str, int] = {}
    token: Optional[str] = None
    while True:
        url = BUCKET + "?list-type=2&max-keys=1000&prefix=" + urllib.parse.quote(prefix) + (f"&continuation-token={urllib.parse.quote(token)}" if token else "")
        x = urllib.request.urlopen(url, timeout=60).read().decode()
        for k, s in re.findall(r"<Key>([^<]*)</Key>.*?<Size>(\d+)</Size>", x, flags=re.S):
            out[k] = int(s)
        m = re.search(r"<NextContinuationToken>([^<]*)</NextContinuationToken>", x)
        if not m:
            return out
        token = m.group(1)


def used_files() -> set[str]:
    used: set[str] = set()
    for f in glob.glob(str(HERE / "stations_*.yaml")):
        if f.endswith("stations_fresh5.yaml"):
            continue
        for v in yaml.safe_load(open(f))["stations"].values():
            used.add(str(v.get("file") or ""))
    return used


def pools() -> tuple[list[str], list[str]]:
    sizes: dict[str, dict[int, int]] = {}
    for y in (2016, 2017, 2018, 2019, 2022):
        for pre in ("94", "95"):
            for k, s in list_sizes(f"{y}/{pre}").items():
                sizes.setdefault(k.split("/")[1][:-4], {})[y] = s
    used = used_files()
    irregular, regular = [], []
    for fid, v in sorted(sizes.items()):
        if fid in used or not all(y in v for y in (2016, 2017, 2018, 2019, 2022)):
            continue
        mb22 = v[2022] / 1e6
        if not 2.0 <= mb22 <= 3.6:
            continue
        ratio = v[2017] / v[2022]
        if 0.52 <= ratio <= 0.80:
            irregular.append(fid)
        elif 0.93 <= ratio <= 1.10:
            regular.append(fid)
    rng = random.Random(SEED)
    rng.shuffle(irregular)
    rng.shuffle(regular)
    return irregular, regular


def complete_per_year(df: pd.DataFrame) -> dict[int, int]:
    ts = pd.to_datetime(df["timestamp"])
    ok = df[["temperature_c", "pressure_hpa", "humidity_pct"]].notna().all(axis=1)
    return {int(y): int(n) for y, n in ts[ok].dt.year.value_counts().items()}


def gate(df: pd.DataFrame, kind: str) -> tuple[bool, dict]:
    ts = pd.to_datetime(df["timestamp"])
    years = complete_per_year(df)
    train = ts[ts.dt.year <= 2019]
    gaps = train.diff().dt.total_seconds().div(60).dropna()
    f60 = float((gaps == 60).mean()) if len(gaps) else 0.0
    f_alt = float(gaps.isin([60, 120]).mean()) if len(gaps) else 0.0
    train_min = min((years.get(y, 0) for y in (2016, 2017, 2018, 2019)), default=0)
    test_min = min((years.get(y, 0) for y in range(2020, 2025)), default=0)
    chan_ok = float(df[["temperature_c", "pressure_hpa", "humidity_pct"]].notna().all(axis=1).mean())
    info = {"f60": round(f60, 3), "f60_or_120": round(f_alt, 3), "train_min_year": train_min, "test_min_year": test_min}
    if kind == "irregular":
        ok = f60 <= 0.65 and f_alt >= 0.90 and train_min >= 4500
    else:
        ok = f60 >= 0.90 and train_min >= 7400
    return ok and test_min >= 7400 and chan_ok >= 0.90, info


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", type=Path, help="write the catalog here")
    a = ap.parse_args(argv)
    hist = pd.read_csv(HISTORY_URL, dtype={"USAF": str, "WBAN": str})
    hist["fid"] = hist["USAF"] + hist["WBAN"]
    meta = hist.set_index("fid")
    irregular, regular = pools()
    print(f"pools: {len(irregular)} irregular, {len(regular)} regular")
    chosen: dict[str, list[tuple[str, dict]]] = {"irregular": [], "regular": []}
    for kind, pool in (("irregular", irregular), ("regular", regular)):
        for fid in pool:
            if len(chosen[kind]) >= N_EACH:
                break
            isd.fetch_all([fid], list(range(2016, 2025)))
            df = isd.build_station({"file": fid, "source": "synop"}, list(range(2016, 2025)), cadence_minutes=60)
            ok, info = gate(df, kind) if len(df) else (False, {})
            print(f"  {kind:9s} {fid} {meta.loc[fid, 'STATION NAME'] if fid in meta.index else '?':35s} {'KEEP' if ok else 'drop'} {info}", flush=True)
            if ok:
                chosen[kind].append((fid, info))
    stations = {}
    for kind, prefix in (("irregular", "IR"), ("regular", "RG")):
        for i, (fid, info) in enumerate(chosen[kind], start=1):
            m = meta.loc[fid]
            stations[f"{prefix}{i}"] = {"file": fid, "name": str(m["STATION NAME"]).title(), "lat": float(m["LAT"]), "lon": float(m["LON"]),
                                        "elevation_m": float(m["ELEV(M)"]), "climate_zone": f"Australia, {kind} 2016-2019 record", "source": "synop",
                                        "cadence_minutes": 60, "record": kind}
    cat = {"years": {"first": 2016, "last": 2024}, "stations": stations}
    if a.write:
        head = ("# The FRESH5 stations (Amendment 6 in config/protocol.md). Six Australian automatic stations whose 2016-2019 record is not equally spaced (IR1-IR6) and six with\n"
                "# an ordinary hourly record (RG1-RG6), chosen by the rule in data_tools/select_fresh5.py (seed 17) before any pipeline verdict. Source: NOAA ISD.\n")
        a.write.write_text(head + yaml.safe_dump(cat, sort_keys=False, width=200), encoding="utf-8")
        print(f"wrote {a.write}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
