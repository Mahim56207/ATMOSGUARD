"""Cut small replayable CSVs of real extreme-weather events for the demo (data/demo/).

Only DEV-period events (2016-2021 at DEV stations) are used, so nothing from the sealed holdout is exposed. Each file has
LEAD_IN_DAYS of ordinary days before the event so the station's history is warm when the event starts. NOAA-flagged values
are left in (they are real) and the `noaa_flag` column is kept.

    python -m data_tools.make_demo_data
"""
from __future__ import annotations

import json

import pandas as pd

from . import isd

REPO = isd.REPO
LEAD_IN_DAYS = 4
DEMOS = [
    # (file name, station, event center prefix, story)
    ("fani_BBI_2019-05", "BBI", "2019-05-03", "Cyclone Fani, Bhubaneswar: pressure falls 30 hPa, the station's reports stop at landfall"),
    ("vardah_MAA_2016-12", "MAA", "2016-12-12", "Cyclone Vardah, Chennai: pressure falls 32 hPa"),
    ("amphan_CCU_2020-05", "CCU", "2020-05-20", "Cyclone Amphan, Kolkata: pressure falls 29 hPa"),
    ("yaas_BBI_2021-05", "BBI", "2021-05-25", "Cyclone Yaas, Bhubaneswar"),
    ("outflow_CCU_2021-06", "CCU", "2021-06-05", "Thunderstorm outflow, Kolkata: temperature falls up to 14 C in 3 h while humidity jumps. An earlier rule called it a fault"),
    ("outflow_DEL_2021-04", "DEL", "2021-04-16", "Outflow, Delhi: humidity jumps 47 % and temperature falls 8 C in an hour. An earlier rule called it a fault"),
]


def main() -> int:
    events = json.loads((REPO / "data" / "real" / "events.json").read_text(encoding="utf-8"))["events"]
    out = REPO / "data" / "demo"
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, sid, day, story in DEMOS:
        ev = next(e for e in events[sid] if e["center"].startswith(day))
        df = pd.read_csv(REPO / "data" / "real" / "dev" / f"{sid}.csv", parse_dates=["timestamp"])
        lo = pd.Timestamp(ev["start"]) - pd.Timedelta(days=LEAD_IN_DAYS)
        seg = df[(df["timestamp"] >= lo) & (df["timestamp"] <= pd.Timestamp(ev["end"]))]
        seg.to_csv(out / f"{name}.csv", index=False)
        manifest.append({"file": f"{name}.csv", "station": sid, "event": ev["kind"], "center": ev["center"],
                         "rows": len(seg), "story": story})
        print(f"{name}: {len(seg)} rows ({ev['note']})")
    (out / "README.md").write_text(
        "# Demo data\n\nReal recorded events (NOAA ISD airport records, DEV period only). Replay one from the dashboard's "
        "Control panel, or `python replay.py data/demo/<file> --speed 3600`.\n\n| file | station | what |\n|---|---|---|\n"
        + "\n".join(f"| {m['file']} | {m['station']} | {m['story']} |" for m in manifest) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
