"""Build a twelve-station cluster of the peer-layer study (data_tools/stations_peers_<cluster>.yaml) into data/peers/<cluster>/<ID>.csv.

    python -m data_tools.make_peers                  # cluster nsw (the one the settings were fixed on)
    python -m data_tools.make_peers --cluster vic    # the disjoint cluster that checks them
Downloads the 2016-2024 raw files (git-ignored) if they are missing, then writes the CSVs (git-ignored).
"""
from __future__ import annotations

import argparse
from pathlib import Path

from . import isd

CLUSTERS = ("nsw", "vic", "india")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cluster", choices=CLUSTERS, default="nsw")
    args = ap.parse_args(argv)
    cat = isd.load_catalog(Path(__file__).resolve().parent / f"stations_peers_{args.cluster}.yaml")
    OUT_DIR = isd.REPO / "data" / "peers" / args.cluster
    if args.cluster == "india":                        # assembled from the repository's own station files, nothing downloaded
        import pandas as pd
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        repo = isd.REPO / "data"
        for sid in cat["stations"]:
            parts = [repo / "real" / "dev" / f"{sid}.csv", repo / "holdout" / "real" / f"{sid}_future.csv", repo / "holdout" / "real" / f"{sid}.csv",
                     repo / "fresh" / "real" / f"{sid}.csv", repo / "fresh2" / "real" / f"{sid}.csv"]
            df = pd.concat([pd.read_csv(p) for p in parts if p.exists()], ignore_index=True)
            df = df.drop_duplicates("timestamp").sort_values("timestamp")
            df.to_csv(OUT_DIR / f"{sid}.csv", index=False)
            print(f"{sid}: {len(df)} rows")
        return 0
    years = list(range(cat["years"]["first"], cat["years"]["last"] + 1))
    isd.fetch_all([s["file"] for s in cat["stations"].values()], years)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for sid, st in cat["stations"].items():
        df = isd.build_station(st, years, cadence_minutes=st["cadence_minutes"])
        df.insert(0, "station_id", sid)
        df.to_csv(OUT_DIR / f"{sid}.csv", index=False)
        print(f"{sid}: {len(df)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
