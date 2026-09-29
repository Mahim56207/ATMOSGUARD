"""Turn evaluate_real.py results into ONE summary that everything else reads.

    python make_summary.py results/dev_run1.json [results/holdout_run1.json] [--scale results/scale.json]

Writes:
  results/summary.json   served by the API at /metrics and drawn by the dashboard's Evaluation tab
  results/REPORT.md      the same tables as Markdown (README, technical report and slides copy from here)

Every table is labelled with what it is: injected faults are injected faults, "real extreme weather" is real data with
nothing injected, and NOAA agreement is agreement with another automated system. The three headline numbers are never
merged into one.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

import numpy as np

import evaluate_real as er

PHASE_TITLES = {
    "DEV": ("DEV: the six stations we were allowed to tune on, 2020-2021",
            "Tuning happened here. These numbers are the optimistic ones."),
    "HOLDOUT_TIME": ("HOLDOUT in time: the same six stations, 2022-2024",
                     "Sealed until the single holdout run. Same stations, later years."),
    "HOLDOUT_SPACE": ("HOLDOUT in space: eight stations never used for any tuning, 2020-2024",
                      "Five hourly airport stations and three 3-hourly SYNOP stations (Port Blair, Bhuj, Cochin)."),
}
FULL_NAMES = {"full": "AtmosGuard (full)", "no_physics": "without physics layer", "no_health": "without health layer",
              "no_normality": "without normality layer", "no_mlmodel": "without Isolation Forest",
              "no_timing": "without timing layer", "no_limits": "without station-learned limits",
              "baseline_range": "baseline: range check only",
              "baseline_rules": "baseline: textbook range + step + persistence",
              "baseline_climatology": "baseline: climatology z-score only",
              "baseline_isolation_forest": "baseline: Isolation Forest only",
              "baseline_mahalanobis": "baseline: Mahalanobis distance only"}
TYPE_NAMES = {"frozen": "frozen", "spike": "spike", "step": "level shift", "noise": "noise burst", "dropout": "dropout",
              "clock_shift": "clock 3 h out"}


def pct(a: float, n: float, digits: int = 1) -> str:
    return "n/a" if not n else f"{100.0 * a / n:.{digits}f}%"


def ci_pct(a: int, n: int) -> str:
    """Rate with a Wilson 95 % interval, so a small count does not look more certain than it is."""
    if not n:
        return "n/a"
    z, p = 1.96, a / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return f"{100 * p:.1f}% ({100 * max(0, centre - half):.1f}-{100 * min(1, centre + half):.1f})"


def _events_total(c: dict) -> dict:
    tot = {k: 0 for k in ("n", "FAULT", "SUSPECT", "WEATHER", "VALID", "windows", "windows_with_fault")}
    for d in c["events"].values():
        for k in tot:
            tot[k] += d.get(k, 0)
    return tot


def phase_tables(agg: dict) -> dict:
    cfgs = agg["configs"]
    full = cfgs["full"]
    ev_full = _events_total(full)
    ck = full["clean"]
    det = full["detection"]
    n = agg["noaa"]
    drift = agg["drift"]
    fa = agg["drift_false"]

    headline = [
        {"question": "False alarms on clean real data (nothing injected)",
         "answer": f"{ci_pct(ck['alarm'], ck['n'])} of {ck['n']} samples got FAULT or SUSPECT; "
                   f"{ci_pct(ck['fault'], ck['n'])} got FAULT"},
        {"question": "What happens to real extreme weather (cyclones, heat, cold, sharp fronts; nothing injected)",
         "answer": f"FAULT on {ci_pct(ev_full['FAULT'], ev_full['n'])} of {ev_full['n']} samples "
                   f"({ev_full['windows_with_fault']} of {ev_full['windows']} windows); "
                   f"WEATHER on {pct(ev_full['WEATHER'], ev_full['n'])}, SUSPECT on {pct(ev_full['SUSPECT'], ev_full['n'])}"},
        {"question": "Injected faults whose alarm the fault raised (each type on its own; injected, not real)",
         "answer": "; ".join(f"{TYPE_NAMES[t]} {pct(det[t].get('detected_new', 0), det[t]['injected'], 0)}"
                              for t in er.REAL_TYPES if det[t]["injected"])},
        {"question": "Agreement with NOAA's own quality flags (another automated system, not ground truth)",
         "answer": f"escalated (FAULT, SUSPECT or WEATHER) on {pct(n.get('flagged_escalated', 0), n.get('flagged', 0))} of {n.get('flagged', 0)} NOAA-flagged values "
                   f"(FAULT or SUSPECT alone: {pct(n.get('flagged_caught', 0), n.get('flagged', 0))}); "
                   f"escalated on {pct(n.get('unflagged_escalated', 0), n.get('unflagged', 0))} of the {n.get('unflagged', 0)} values NOAA left alone"},
        {"question": "Slow drift (health monitor, single station, no reference)",
         "answer": f"false drift claims on {pct(fa.get('days_with_significant', 0), fa.get('days', 0))} of {fa.get('days', 0)} station-days; "
                   f"an injected ramp reaching 8x the service limit was found in "
                   f"{pct(sum(drift.get(f'{ch}|8', {}).get('detected', 0) for ch in er.CHANNELS), sum(drift.get(f'{ch}|8', {}).get('trials', 0) for ch in er.CHANNELS), 0)} of trials"},
    ]
    def det_rows(key: str, delays_key: str) -> list[dict]:
        rows = []
        for name, c in cfgs.items():
            row = {"configuration": FULL_NAMES.get(name, name)}
            for t in er.REAL_TYPES:
                d = c["detection"][t]
                row[TYPE_NAMES[t]] = pct(d.get(key, 0), d["injected"], 0)
            rows.append(row)
        injected_row = {"configuration": "(faults injected)"}
        for t in er.REAL_TYPES:
            injected_row[TYPE_NAMES[t]] = str(det[t]["injected"])
        rows.append(injected_row)
        med = {"configuration": "AtmosGuard: median minutes to the alarm"}
        for t in er.REAL_TYPES:
            v = det[t].get(delays_key, [])
            med[TYPE_NAMES[t]] = "-" if not v else f"{np.median(v):.0f}"
        rows.append(med)
        return rows
    named_rows = []
    for label, key in (("raised an alarm (FAULT or SUSPECT)", "detected_new"), ("of which named FAULT", "named_fault"),
                       ("missed, but made some samples look like WEATHER", "masked_as_weather")):
        row = {"AtmosGuard, injected faults": label}
        for t in er.REAL_TYPES:
            row[TYPE_NAMES[t]] = pct(det[t].get(key, 0), det[t]["injected"], 0)
        named_rows.append(row)
    detection_rows = det_rows("detected_new", "delays_new_min")
    registered_rows = det_rows("detected", "delays_min")

    clean_rows = []
    for name, c in cfgs.items():
        k = c["clean"]
        clean_rows.append({"configuration": FULL_NAMES.get(name, name), "any alarm": pct(k["alarm"], k["n"]),
                           "FAULT only": pct(k["fault"], k["n"]),
                           "WEATHER verdicts": "-" if c["kind"] == "baseline" else pct(k["weather"], k["n"]),
                           "samples": k["n"]})
    ev_rows = []
    for name, c in cfgs.items():
        t = _events_total(c)
        ev_rows.append({"configuration": FULL_NAMES.get(name, name), "FAULT": pct(t["FAULT"], t["n"]),
                        "SUSPECT": pct(t["SUSPECT"], t["n"]),
                        "WEATHER": "-" if c["kind"] == "baseline" else pct(t["WEATHER"], t["n"]),
                        "VALID": pct(t["VALID"], t["n"]),
                        "windows with a FAULT": f"{t['windows_with_fault']}/{t['windows']}"})
    kind_rows = []
    for k, d in sorted(full["events"].items()):
        kind_rows.append({"kind of extreme weather": k, "samples": d["n"], "FAULT": pct(d.get("FAULT", 0), d["n"]),
                          "SUSPECT": pct(d.get("SUSPECT", 0), d["n"]), "WEATHER": pct(d.get("WEATHER", 0), d["n"]),
                          "windows with a FAULT": f"{d['windows_with_fault']}/{d['windows']}"})

    noaa_rows = [
        {"measure": "NOAA-flagged values (suspect or erroneous)", "value": n.get("flagged", 0)},
        {"measure": "  of which erroneous", "value": n.get("erroneous", 0)},
        {"measure": "AtmosGuard alarmed (FAULT or SUSPECT) on flagged values", "value": pct(n.get("flagged_caught", 0), n.get("flagged", 0))},
        {"measure": "AtmosGuard escalated at all (also WEATHER) on flagged values", "value": pct(n.get("flagged_escalated", 0), n.get("flagged", 0))},
        {"measure": "AtmosGuard alarmed on erroneous values", "value": pct(n.get("erroneous_caught", 0), n.get("erroneous", 0))},
        {"measure": "values NOAA did not flag", "value": n.get("unflagged", 0)},
        {"measure": "AtmosGuard alarmed on those (extra flags)", "value": pct(n.get("unflagged_alarm", 0), n.get("unflagged", 0))},
        {"measure": "AtmosGuard escalated at all on those", "value": pct(n.get("unflagged_escalated", 0), n.get("unflagged", 0))},
    ]
    drift_rows = []
    for sev in (0.0, *er.DRIFT_SEVERITIES):
        row = {"drift at end of ramp": "none (false claims)" if sev == 0 else f"{sev:g}x service limit"}
        for ch in er.CHANNELS:
            a = drift.get(f"{ch}|{sev:g}")
            label = ch.split("_")[0]
            if not a or not a["trials"]:
                row[label] = "n/a"
            elif sev == 0:
                row[label] = f"{pct(a['detected'], a['trials'])} of {a['trials']} chunks"
            else:
                day = f"day {np.median(a['days_to_detect']):.0f}" if a["days_to_detect"] else "-"
                off = f"{np.median(a['offset_over_limit']):.1f}x" if a["offset_over_limit"] else "-"
                row[label] = f"{pct(a['detected'], a['trials'], 0)} of {a['trials']} ({day}, {off} at detection)"
        drift_rows.append(row)
    return {
        "stations": agg["stations"],
        "headline": {"title": "Headline", "caption": "Five separate numbers. They are never merged.", "rows": headline},
        "detection": {"title": "1. Detection of injected faults, by type (the fault raised the alarm)",
                      "caption": "Alarm = FAULT or SUSPECT on a sample that was NOT an alarm on the same series without the fault "
                                 "(paired), from the first faulty sample to the last plus 60 minutes. The faults are injected, not real. "
                                 "Ablation rows switch one layer off; baseline rows are simpler systems on the same data.",
                      "rows": detection_rows},
        "detection_named": {"title": "1c. How AtmosGuard names what it detects, and the WEATHER-masking check",
                            "caption": "A FAULT verdict names the problem; SUSPECT asks for review. The last row is the risk of the coherent-level "
                                       "WEATHER route: a fault that was not alarmed but made samples look like real weather.", "rows": named_rows},
        "detection_registered": {"title": "1b. The same, by the criterion registered in the protocol (any alarm in the window)",
                                 "caption": "Background false alarms (about 2 % of samples) also fall inside long fault windows, so this "
                                            "flatters long faults (frozen 48 h, clock shift 4 days) and every system, baselines included. "
                                            "Kept because it was registered before the holdout.", "rows": registered_rows},
        "clean": {"title": "2. False alarms on clean real data",
                  "caption": "No fault injected. Extreme-weather windows and NOAA-flagged values removed.", "rows": clean_rows},
        "extreme_weather": {"title": "3. Real extreme weather (nothing injected)",
                            "caption": "A FAULT here is a failure: real weather called a broken sensor. WEATHER is the escalated, "
                                       "correct verdict.", "rows": ev_rows, "by_kind": kind_rows},
        "noaa": {"title": "4. Agreement with NOAA's own quality flags",
                 "caption": "NOAA's flags come from another automated system. Agreement means consistency with existing practice, "
                            "not proof of real-world accuracy.", "rows": noaa_rows},
        "drift": {"title": "5. Slow drift, judged by the health monitor",
                  "caption": f"A ramp over {er.DRIFT_RAMP_DAYS} days is added to one channel of clean real data. "
                             "Severity = offset at the end of the ramp in multiples of the service limit "
                             "(T 0.5 C, P 1 hPa, RH 3 %). One station, no reference: small drifts cannot be told from weather.",
                  "rows": drift_rows},
    }


def station_rows(rows: list[dict], phase: str) -> list[dict]:
    """One line per station for the full pipeline: how far the headline numbers move between stations."""
    out = []
    for r in rows:
        if r["phase"] != phase:
            continue
        c = r["configs"]["full"]
        ev = _events_total(c)
        det = c["detection"]
        got = sum(det[t].get("detected_new", 0) for t in er.REAL_TYPES)
        inj = sum(det[t]["injected"] for t in er.REAL_TYPES)
        out.append({"station": r["station"], "cadence (min)": int(r["cadence_minutes"]),
                    "clean any alarm": pct(c["clean"]["alarm"], c["clean"]["n"]), "clean FAULT": pct(c["clean"]["fault"], c["clean"]["n"]),
                    "extreme weather FAULT": pct(ev["FAULT"], ev["n"]), "windows with a FAULT": f"{ev['windows_with_fault']}/{ev['windows']}",
                    "extreme weather WEATHER": pct(ev["WEATHER"], ev["n"]), "injected faults detected": pct(got, inj, 0)})
    return out


def build_summary(results: dict[str, dict], scale: Optional[dict]) -> dict:
    phases = {}
    for label, res in results.items():
        for ph in dict.fromkeys(r["phase"] for r in res["stations"]):
            agg = er.aggregate(res["stations"], ph)
            title, sub = PHASE_TITLES[ph]
            phases[ph] = {"title": title, "subtitle": sub, "generated": res["generated"],
                          "quick": res.get("quick", False), **phase_tables(agg),
                          "by_station": {"title": "By station (full pipeline)", "caption": "Each station judged on its own record.",
                                         "rows": station_rows(res["stations"], ph)}}
    out = {"note": "Real NOAA ISD airport records (METAR and SYNOP), 2016-2024. RH is derived from dew point. Injected faults are "
                   "injected. NOAA agreement is not ground truth. See docs/WHAT_WE_DO_NOT_CLAIM.md.",
           "phases": phases}
    if scale:
        rows = scale["pipeline_by_station_count"]
        out["scale"] = {"note": scale["note"], "pipeline": rows, "http": scale.get("http")}
    return out


def to_markdown(summary: dict) -> str:
    L = ["# AtmosGuard evaluation results", "", summary["note"], ""]

    def table(rows: list[dict]) -> None:
        if not rows:
            return
        cols = list(rows[0])
        L.append("| " + " | ".join(cols) + " |")
        L.append("|" + "|".join("---" for _ in cols) + "|")
        for r in rows:
            L.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
        L.append("")
    for ph in summary["phases"].values():
        L += [f"## {ph['title']}", "", f"*{ph['subtitle']}*  Stations: {', '.join(ph['stations'])}."
              + ("  **Quick run (one year, one fault round): tuning loop only.**" if ph.get("quick") else ""), ""]
        for key in ("headline", "detection", "detection_named", "detection_registered", "clean", "extreme_weather", "noaa", "drift"):
            t = ph[key]
            L += [f"### {t['title']}", "", t["caption"], ""]
            table(t["rows"])
            if key == "extreme_weather":
                L += ["Full pipeline, by kind of extreme weather:", ""]
                table(t["by_kind"])
        L += [f"### {ph['by_station']['title']}", "", ph["by_station"]["caption"], ""]
        table(ph["by_station"]["rows"])
    if "scale" in summary:
        L += ["## Scale (simulated stations, one machine)", "", summary["scale"]["note"], ""]
        table([{"stations": r["stations"], "readings/s": r["readings_per_second"], "median ms": r["median_ms"],
                "p95 ms": r["p95_ms"], "p99 ms": r["p99_ms"], "MB/station": r["memory_per_station_mb"],
                "KB stored/station": r["storage_per_station"]["total_kb"]} for r in summary["scale"]["pipeline"]])
        h = summary["scale"].get("http")
        if h:
            L += [f"Real HTTP server (FastAPI + SQLite), {h['stations']} stations, {h['clients']} concurrent clients: "
                  f"{h['requests_per_second']} requests/s, median {h['median_ms']} ms, p95 {h['p95_ms']} ms, "
                  f"p99 {h['p99_ms']} ms, errors {h['errors']}.", ""]
    return "\n".join(L)


README_START, README_END = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"


def readme_block(summary: dict) -> str:
    """A compact headline table for the README, straight from the summary (so it cannot drift from the results)."""
    L = ["| | DEV (tuned here) | Holdout, same stations, later years | Holdout, eight unseen stations |", "|---|---|---|---|"]
    order = ["DEV", "HOLDOUT_TIME", "HOLDOUT_SPACE"]
    ph = summary["phases"]
    questions = [("False alarms on clean real data", 0), ("Real cyclones, heat, cold, fronts (nothing injected)", 1),
                 ("Injected faults detected (injected, not real)", 2), ("Agreement with NOAA quality flags", 3),
                 ("Slow drift (one station, no reference)", 4)]
    for label, i in questions:
        cells = [ph[k]["headline"]["rows"][i]["answer"] if k in ph else "not run" for k in order]
        L.append(f"| **{label}** | " + " | ".join(c.replace("|", "/") for c in cells) + " |")
    L.append("")
    L.append("Real NOAA airport records, 14 Indian stations. Full tables, baselines and ablation: [`results/REPORT.md`](results/REPORT.md). "
             "Protocol written and committed before the holdout was read: [`config/protocol.md`](config/protocol.md).")
    return "\n".join(L)


def update_readme(summary: dict, path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if README_START not in text or README_END not in text:
        return False
    a, b = text.index(README_START) + len(README_START), text.index(README_END)
    path.write_text(text[:a] + "\n" + readme_block(summary) + "\n" + text[b:], encoding="utf-8")
    return True


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Build results/summary.json and results/REPORT.md.")
    ap.add_argument("results", nargs="+", type=Path, help="JSON files written by evaluate_real.py --out")
    ap.add_argument("--scale", type=Path, default=None, help="JSON written by loadtest.py")
    ap.add_argument("--out-dir", type=Path, default=er.RESULTS_DIR)
    ap.add_argument("--readme", type=Path, default=None, help="refresh the block between the RESULTS markers in this README")
    args = ap.parse_args(argv)
    results = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in args.results}
    scale = json.loads(args.scale.read_text(encoding="utf-8")) if args.scale and args.scale.exists() else None
    summary = build_summary(results, scale)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    (args.out_dir / "REPORT.md").write_text(to_markdown(summary), encoding="utf-8")
    print(f"wrote {args.out_dir / 'summary.json'} and {args.out_dir / 'REPORT.md'}")
    if args.readme:
        print("README updated" if update_readme(summary, args.readme) else "README has no RESULTS markers: not updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
