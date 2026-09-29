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

FRESH2_INDIAN = ("HYD", "BLR", "CCJ", "IXM", "VGA")            # the other seven FRESH2 stations are Australian AWS at 0.1 resolution
PHASE_TITLES = {
    "FRESH2": ("FRESH2: a third set of twelve stations, 2020-2024",
               "Chosen and sealed before the two Amendment 3 remedies were tested (config/protocol.md). Five Indian airport stations (hourly METAR, whole "
               "degrees) and seven Australian automatic weather stations (hourly SYNOP at 0.1 C and 0.1 hPa). `AtmosGuard (full)` here is the pipeline as "
               "shipped before Amendment 3 (remedy 1 on)."),
    "FRESH2_INDIA": ("FRESH2, the five Indian airport stations only",
                     "Subset of FRESH2: hourly METAR at whole-degree resolution."),
    "FRESH2_AWS": ("FRESH2, the seven Australian automatic weather stations only",
                   "Subset of FRESH2: hourly SYNOP from Bureau of Meteorology AWS at 0.1 C and 0.1 hPa, including two Coral Sea cyclone-track islands."),
    "FRESH": ("FRESH: twelve more stations nobody had looked at, 2020-2024",
              "Chosen and sealed before the two remedies from the holdout post-mortem were tested (Amendment 2 in config/protocol.md). "
              "Eight hourly airport stations and four 3-hourly SYNOP stations."),
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
              "no_mahalanobis": "without Mahalanobis layer",
              "registered": "AtmosGuard as registered (every remedy off)",
              "r3_expected_step": "AtmosGuard + remedy 3 (expected-change-aware step rule)",
              "r4_offset": "AtmosGuard + remedy 4 (sustained one-channel offset)",
              "r34_both": "AtmosGuard + remedies 3 and 4",
              "remedy_frozen": "AtmosGuard + remedy 1 (ceiling-aware frozen rule)", "remedy_step": "AtmosGuard + remedy 2 (learned step cap)",
              "remedies": "AtmosGuard + both remedies",
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


def _num(cell: str) -> Optional[float]:
    try:
        return float(str(cell).rstrip("%"))
    except ValueError:
        return None


def tradeoff_rows(phase: dict) -> list[dict]:
    """One line per system: its weakest injected-fault type, its clean false-alarm rate and its real-weather FAULT windows.

    Built from the phase's own tables, so it cannot drift from them. It shows that no single simpler system covers every type.
    """
    det = {r["configuration"]: r for r in phase["detection"]["rows"] if not r["configuration"].startswith(("(", "AtmosGuard: median"))}
    clean = {r["configuration"]: r for r in phase["clean"]["rows"]}
    ev = {r["configuration"]: r for r in phase["extreme_weather"]["rows"]}
    out = []
    for name, row in det.items():
        if name.startswith("without"):
            continue
        vals = {k: _num(v) for k, v in row.items() if k != "configuration"}
        vals = {k: v for k, v in vals.items() if v is not None}
        weakest = min(vals, key=vals.get)
        out.append({"system": name, "weakest injected-fault type (fault raised the alarm)": f"{weakest}: {vals[weakest]:.0f}%",
                    "false alarms on clean data": clean[name]["any alarm"],
                    "real extreme weather, windows with a FAULT": ev[name]["windows with a FAULT"]})
    return out


REMEDY_CONFIGS = ("remedy_frozen", "remedy_step", "remedies")
RULE_DETECTION_DROP_PP = 2.0          # Amendment 2 (b): no injected-fault type may lose more than this many points
RULE_CLEAN_RISE_PP = 0.2              # Amendment 2 (c): clean false alarms may not rise by more than this many points


def remedy_rows(agg: dict) -> list[dict]:
    """The decision rule registered in Amendment 2 of config/protocol.md, applied to a phase's pooled numbers.

    (a) windows with a FAULT on real extreme weather not higher than `full`, and the FAULT share of those samples not higher;
    (b) paired detection not lower than `full` by more than 2 points for any injected-fault type;
    (c) clean false alarms not higher by more than 0.2 points.  Every number is shown, so the verdict can be checked by eye."""
    cfgs = agg["configs"]
    if "full" not in cfgs or not any(r in cfgs for r in REMEDY_CONFIGS):
        return []
    full = cfgs["full"]
    f_ev, f_ck = _events_total(full), full["clean"]
    rows = []
    for name in REMEDY_CONFIGS:
        if name not in cfgs:
            continue
        c = cfgs[name]
        ev_, ck = _events_total(c), c["clean"]
        worst_type, worst = None, 0.0
        for ty in er.REAL_TYPES:
            d0, d1 = full["detection"][ty], c["detection"][ty]
            if not d0["injected"]:
                continue
            change = 100.0 * (d1.get("detected_new", 0) - d0.get("detected_new", 0)) / d0["injected"]
            if change < worst:
                worst_type, worst = ty, change
        clean_rise = 100.0 * (ck["alarm"] / ck["n"] - f_ck["alarm"] / f_ck["n"])
        share = lambda e: e["FAULT"] / e["n"] if e["n"] else 0.0
        a = ev_["windows_with_fault"] <= f_ev["windows_with_fault"] and share(ev_) <= share(f_ev)
        b = worst >= -RULE_DETECTION_DROP_PP
        cc = clean_rise <= RULE_CLEAN_RISE_PP
        rows.append({"configuration": FULL_NAMES.get(name, name),
                     "(a) windows with a FAULT (full / this)": f"{f_ev['windows_with_fault']} / {ev_['windows_with_fault']} of {ev_['windows']}",
                     "(a) FAULT share of extreme-weather samples (full / this)": f"{100 * share(f_ev):.2f}% / {100 * share(ev_):.2f}%",
                     "(b) worst change in paired detection": "none" if worst_type is None else f"{worst:+.1f} pp ({TYPE_NAMES[worst_type]})",
                     "(c) change in clean false alarms": f"{clean_rise:+.2f} pp",
                     "rule (a)": "pass" if a else "FAIL", "rule (b)": "pass" if b else "FAIL", "rule (c)": "pass" if cc else "FAIL",
                     "adopt": "yes" if (a and b and cc) else "no"})
    return rows


A3_CONFIGS = ("r3_expected_step", "r4_offset", "r34_both")
A3_DETECTION_DROP_PP = 2.0            # Amendment 3 (b) for both remedies
A3_R3_CLEAN_RISE_PP, A3_R4_CLEAN_RISE_PP = 0.2, 0.5
A3_R4_LEVEL_SHIFT_GAIN_PP = 5.0       # Amendment 3 remedy 4 (d)
A3_R4_SUSPECT_RISE_PP = 2.0           # Amendment 3 remedy 4 (e)


def amendment3_rows(agg: dict) -> list[dict]:
    """The decision rules registered in Amendment 3 of config/protocol.md, applied to the pooled FRESH2 numbers. Every number is shown."""
    cfgs = agg["configs"]
    if "full" not in cfgs or not any(r in cfgs for r in A3_CONFIGS):
        return []
    full = cfgs["full"]
    f_ev, f_ck = _events_total(full), full["clean"]
    share = lambda e: e["FAULT"] / e["n"] if e["n"] else 0.0
    susp = lambda e: 100.0 * e["SUSPECT"] / e["n"] if e["n"] else 0.0
    rows = []
    for name in A3_CONFIGS:
        if name not in cfgs:
            continue
        c = cfgs[name]
        ev_, ck = _events_total(c), c["clean"]
        worst_type, worst = None, 0.0
        for ty in er.REAL_TYPES:
            d0, d1 = full["detection"][ty], c["detection"][ty]
            if not d0["injected"]:
                continue
            change = 100.0 * (d1.get("detected_new", 0) - d0.get("detected_new", 0)) / d0["injected"]
            if change < worst:
                worst_type, worst = ty, change
        d0, d1 = full["detection"]["step"], c["detection"]["step"]
        level_gain = 100.0 * (d1.get("detected_new", 0) - d0.get("detected_new", 0)) / d0["injected"] if d0["injected"] else 0.0
        clean_rise = 100.0 * (ck["alarm"] / ck["n"] - f_ck["alarm"] / f_ck["n"])
        susp_rise = susp(ev_) - susp(f_ev)
        no_more_faults = ev_["windows_with_fault"] <= f_ev["windows_with_fault"] and share(ev_) <= share(f_ev)
        strictly_fewer = ev_["windows_with_fault"] < f_ev["windows_with_fault"] and share(ev_) <= share(f_ev)
        b = worst >= -A3_DETECTION_DROP_PP
        row = {"configuration": FULL_NAMES.get(name, name),
               "windows with a FAULT (full / this)": f"{f_ev['windows_with_fault']} / {ev_['windows_with_fault']} of {ev_['windows']}",
               "FAULT share of extreme-weather samples (full / this)": f"{100 * share(f_ev):.2f}% / {100 * share(ev_):.2f}%",
               "worst change in paired detection": "none" if worst_type is None else f"{worst:+.1f} pp ({TYPE_NAMES[worst_type]})",
               "level-shift detection change": f"{level_gain:+.1f} pp",
               "change in clean false alarms": f"{clean_rise:+.2f} pp",
               "SUSPECT share in extreme weather (change)": f"{susp_rise:+.2f} pp"}
        r3 = strictly_fewer and b and clean_rise <= A3_R3_CLEAN_RISE_PP
        r4 = no_more_faults and b and clean_rise <= A3_R4_CLEAN_RISE_PP and level_gain >= A3_R4_LEVEL_SHIFT_GAIN_PP and susp_rise <= A3_R4_SUSPECT_RISE_PP
        row["remedy 3 rule (a: fewer FAULT windows, b, c)"] = "pass" if r3 else "FAIL"
        row["remedy 4 rule (a, b, c 0.5 pp, d +5 pp level shift, e)"] = "pass" if r4 else "FAIL"
        if name == "r3_expected_step":
            row["adopt"] = "yes" if r3 else "no"
        elif name == "r4_offset":
            row["adopt"] = "yes" if r4 else "no"
        else:
            row["adopt"] = "both only"
        rows.append(row)
    both = [r for r in rows if r["configuration"] in (FULL_NAMES["r3_expected_step"], FULL_NAMES["r4_offset"])]
    for r in rows:
        if r["adopt"] == "both only":
            r["adopt"] = "yes" if len(both) == 2 and all(x["adopt"] == "yes" for x in both) else "no"
    return rows


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
    result = {
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
    result["detection_ci"] = {"title": "1d. How sure are the detection numbers? (AtmosGuard full, paired criterion, Wilson 95 % interval)",
                              "caption": "Faults are injected at random places; each row's interval says how much the percentage could move with another "
                                         "draw of the same size. Faults of one type overlap little but are not fully independent, so read the interval as a "
                                         "guide, not a guarantee.",
                              "rows": [{"fault type": TYPE_NAMES[ty], "injected": det[ty]["injected"],
                                        "raised the alarm (fault-raised)": ci_pct(det[ty].get("detected_new", 0), det[ty]["injected"]),
                                        "named FAULT": ci_pct(det[ty].get("named_fault", 0), det[ty]["injected"])}
                                       for ty in er.REAL_TYPES if det[ty]["injected"]]}
    rr = remedy_rows(agg)
    if rr:
        result["remedies"] = {"title": "The two remedies from the post-mortem, judged by the decision rule registered in Amendment 2",
                              "caption": "Rule: adopt only if (a) real extreme-weather windows with a FAULT and the FAULT share do not rise, (b) paired "
                                         "detection loses at most 2 points for any injected-fault type, (c) clean false alarms rise by at most 0.2 "
                                         "points. Compared with the frozen `full` pipeline on the same stations.", "rows": rr}
    a3 = amendment3_rows(agg)
    if a3:
        result["amendment3"] = {"title": "The two Amendment 3 remedies, judged by the decision rule registered before the run",
                                "caption": "Remedy 3 (expected-change-aware step rule): adopt only if the windows with a FAULT are fewer than with `full`, "
                                           "the FAULT share does not rise, no fault type loses more than 2 points and clean false alarms rise by at most 0.2 "
                                           "points. Remedy 4 (sustained one-channel offset): adopt only if the windows with a FAULT and the FAULT share do "
                                           "not rise, no type loses more than 2 points, clean false alarms rise by at most 0.5 points, level-shift detection "
                                           "gains at least 5 points and the SUSPECT share in real extreme weather rises by at most 2 points. Compared with "
                                           "`full` (the shipped pipeline before this amendment) on the same stations.", "rows": a3}
    result["tradeoff"] = {"title": "No single simpler system is good at every fault type",
                          "caption": "Each system's weakest fault type from table 1, beside its false-alarm rate and its record on real "
                                     "extreme weather. A system that is best at one fault type is blind to another; the layers exist for "
                                     "coverage, and the WEATHER verdict exists so that coverage does not cost real storms.",
                          "rows": tradeoff_rows(result)}
    return result


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


def sensitivity_rows(sens: dict) -> list[dict]:
    """Detection against fault size: one row per system and size, one column per swept fault type."""
    names = {"spike": "spike", "step": "level shift", "noise": "noise burst"}
    rows = []
    for key, label in sens["systems"].items():
        for m in sens["multipliers"]:
            cells = sens["pooled"][key][str(m)]
            row = {"system": label, "size (x the configured fault)": f"{m:g}x"}
            for ty in sens["swept"]:
                d, n = cells[ty]
                row[names[ty]] = pct(d, n, 0)
            rows.append(row)
    return rows


def build_summary(results: dict[str, dict], scale: Optional[dict], cold: Optional[dict] = None, sens: Optional[dict] = None) -> dict:
    phases = {}
    for label, res in results.items():
        rows_all = list(res["stations"])
        for r in res["stations"]:
            if r["phase"] == "FRESH2":                      # the same stations again, as two groups, so the airport and AWS records can be read apart
                rows_all.append({**r, "phase": "FRESH2_INDIA" if r["station"] in FRESH2_INDIAN else "FRESH2_AWS"})
        res = {**res, "stations": rows_all}
        for ph in dict.fromkeys(r["phase"] for r in res["stations"]):
            agg = er.aggregate(res["stations"], ph)
            title, sub = PHASE_TITLES[ph]
            phases[ph] = {"title": title, "subtitle": sub, "generated": res["generated"],
                          "quick": res.get("quick", False), **phase_tables(agg),
                          "by_station": {"title": "By station (full pipeline)", "caption": "Each station judged on its own record.",
                                         "rows": station_rows(res["stations"], ph)}}
    out = {"note": "Real NOAA ISD records (airport METAR and SYNOP from airports and automatic weather stations), 2016-2024. RH is derived from dew point. Injected faults are "
                   "injected. NOAA agreement is not ground truth. See docs/WHAT_WE_DO_NOT_CLAIM.md.",
           "phases": phases}
    if sens:
        out["sensitivity"] = {"note": "How big must a fault be? Spikes, level shifts and noise bursts of 0.25 to 4 times the configured size, injected into "
                                      "clean real data of the six DEV stations (the tuning set, so an envelope study and not a held-out result). "
                                      "A detection is an alarm the fault itself raised. The 1x row is a separate random draw (two faults of each type per "
                                      "series, one round), so it is close to but not identical with the main table.",
                              "rows": sensitivity_rows(sens), "timing": sens.get("timing", {})}
    if cold:
        out["coldstart"] = {"note": "Leave-one-station-out on the six DEV stations, judged on their DEV years. A starter is a frozen table "
                                    "from the nearest other station. Injected faults: frozen, spike, level shift.",
                            "rows": coldstart_table(cold), "timing": cold.get("timing", {})}
    if scale:
        rows = scale["pipeline_by_station_count"]
        out["scale"] = {"note": scale["note"], "pipeline": rows, "http": scale.get("http"),
                        "pipeline_no_forest": scale.get("pipeline_without_isolation_forest", [])}
    return out


def markdown_table(rows: list[dict]) -> list[str]:
    """Lines of a Markdown table (plus a blank line) for a list of same-keyed dicts; nothing for an empty list."""
    if not rows:
        return []
    cols = list(rows[0])
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    out += ["| " + " | ".join(str(r.get(c, "")).replace("|", "/") for c in cols) + " |" for r in rows]
    return out + [""]


def to_markdown(summary: dict) -> str:
    L = ["# AtmosGuard evaluation results", "", summary["note"], ""]

    def table(rows: list[dict]) -> None:
        L.extend(markdown_table(rows))
    for ph in summary["phases"].values():
        L += [f"## {ph['title']}", "", f"*{ph['subtitle']}*  Stations: {', '.join(ph['stations'])}."
              + ("  **Quick run (one year, one fault round): tuning loop only.**" if ph.get("quick") else ""), ""]
        for key in ("headline", "detection", "detection_ci", "detection_named", "detection_registered", "tradeoff", "remedies", "amendment3", "clean", "extreme_weather", "noaa", "drift"):
            if key not in ph:
                continue
            t = ph[key]
            L += [f"### {t['title']}", "", t["caption"], ""]
            table(t["rows"])
            if key == "extreme_weather":
                L += ["Full pipeline, by kind of extreme weather:", ""]
                table(t["by_kind"])
        L += [f"### {ph['by_station']['title']}", "", ph["by_station"]["caption"], ""]
        table(ph["by_station"]["rows"])
    if "sensitivity" in summary:
        L += ["## How big must a fault be? (DEV, injected)", "", summary["sensitivity"]["note"], ""]
        table(summary["sensitivity"]["rows"])
    if "coldstart" in summary:
        L += ["## A new station on day one (cold start)", "", summary["coldstart"]["note"], ""]
        table(summary["coldstart"]["rows"])
    if "scale" in summary:
        L += ["## Scale (simulated stations, one machine)", "", summary["scale"]["note"], ""]
        table([{"stations": r["stations"], "readings/s": r["readings_per_second"], "median ms": r["median_ms"],
                "p95 ms": r["p95_ms"], "p99 ms": r["p99_ms"], "MB/station": r["memory_per_station_mb"],
                "KB stored/station": r["storage_per_station"]["total_kb"]} for r in summary["scale"]["pipeline"]])
        nf = summary["scale"].get("pipeline_no_forest")
        if nf:
            L += ["The same test with the Isolation Forest layer switched off (`layers.mlmodel: false`); the ablation shows it adds "
                  "almost nothing to the verdicts:", ""]
            table([{"stations": r["stations"], "readings/s": r["readings_per_second"], "median ms": r["median_ms"],
                    "p95 ms": r["p95_ms"], "p99 ms": r["p99_ms"]} for r in nf])
        h = summary["scale"].get("http")
        if h:
            L += [f"Real HTTP server (FastAPI + SQLite), {h['stations']} stations, {h['clients']} concurrent clients: "
                  f"{h['requests_per_second']} requests/s, median {h['median_ms']} ms, p95 {h['p95_ms']} ms, "
                  f"p99 {h['p99_ms']} ms, errors {h['errors']}.", ""]
    return "\n".join(L)


PEERS_START, PEERS_END = "<!-- PEERS:START -->", "<!-- PEERS:END -->"
CHANNEL_SHORT = {"temperature_c": "temperature", "pressure_hpa": "pressure", "humidity_pct": "humidity"}
UNITS = {"temperature_c": "C", "pressure_hpa": "hPa", "humidity_pct": "%"}


def peers_tables(clusters: dict[str, dict]) -> str:
    """Markdown for docs/PEER_LAYER.md from the JSON that evaluate_peers.py wrote (one entry per cluster name)."""
    def cell(d: Optional[dict]) -> str:
        if d is None:
            return "n/a"
        days = "" if d["median_days"] is None else f", {d['median_days']:.0f} d"
        return f"{100 * d['rate']:.0f}% ({d['detected']}/{d['trials']}{days})"
    L = []
    keys = sorted({(d["channel"], d["kind"], d["size"]) for res in clusters.values() for d in res["summary"]["detection"]},
                  key=lambda k: (list(CHANNEL_SHORT).index(k[0]), k[1] != "offset", k[2]))
    idx = {name: {(d["channel"], d["kind"], d["size"], d["mode"]): d for d in res["summary"]["detection"]} for name, res in clusters.items()}
    head = ["fault (60 days long)"] + [f"{name}: with neighbours / alone" for name in clusters]
    rows = []
    for ch, kind, size in keys:
        label = (f"{CHANNEL_SHORT[ch]} offset of {size:g} {UNITS[ch]}" if kind == "offset"
                 else f"{CHANNEL_SHORT[ch]} drift, 0 to {size:g} {UNITS[ch]}")
        rows.append({head[0]: label, **{h: f"{cell(idx[n].get((ch, kind, size, 'peer')))} / {cell(idx[n].get((ch, kind, size, 'own')))}"
                                        for h, n in zip(head[1:], clusters)}})
    L += markdown_table(rows)
    fa = []
    for ch in CHANNEL_SHORT:
        row = {"share of clean days with an alarm": CHANNEL_SHORT[ch]}
        for n, res in clusters.items():
            vals = {(f["channel"], f["mode"]): f["mean_alarm_day_fraction"] for f in res["summary"]["false_alarms"]}
            row[f"{n}: with neighbours / alone"] = f"{100 * vals[(ch, 'peer')]:.2f}% / {100 * vals[(ch, 'own')]:.2f}%"
        fa.append(row)
    L += markdown_table(fa)
    return "\n".join(L)


def update_peers(clusters: dict[str, dict], path: Path) -> bool:
    return update_between(path, PEERS_START, PEERS_END, peers_tables(clusters))


README_START, README_END = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"


def readme_block(summary: dict) -> str:
    """A compact headline table for the README, straight from the summary (so it cannot drift from the results)."""
    ph = summary["phases"]
    heads = {"DEV": "DEV (tuned here)", "HOLDOUT_TIME": "Holdout, same stations, later years",
             "HOLDOUT_SPACE": "Holdout, eight unseen stations", "FRESH": "Fresh, twelve more unseen stations (sealed before the remedies were tested)",
             "FRESH2": "Fresh 2, twelve more: five Indian airports and seven Australian AWS at 0.1 resolution"}
    order = [k for k in heads if k in ph]
    L = ["| | " + " | ".join(heads[k] for k in order) + " |", "|---|" + "---|" * len(order)]
    questions = [("False alarms on clean real data", 0), ("Real cyclones, heat, cold, fronts (nothing injected)", 1),
                 ("Injected faults detected (injected, not real)", 2), ("Agreement with NOAA quality flags", 3),
                 ("Slow drift (one station, no reference)", 4)]
    for label, i in questions:
        cells = [ph[k]["headline"]["rows"][i]["answer"] for k in order]
        L.append(f"| **{label}** | " + " | ".join(c.replace("|", "/") for c in cells) + " |")
    L.append("")
    L.append("Real NOAA records: 26 Indian airport stations in DEV, holdout and Fresh, then Fresh 2 with five more Indian airports and seven Australian automatic weather stations. Full tables, baselines and ablation: [`results/REPORT.md`](results/REPORT.md). "
             "Protocol written and committed before the holdout was read: [`config/protocol.md`](config/protocol.md).")
    return "\n".join(L)


def update_between(path: Path, start: str, end: str, body: str) -> bool:
    """Replace what lies between two marker lines in a file; False (file untouched) if a marker is missing."""
    text = path.read_text(encoding="utf-8")
    if start not in text or end not in text:
        return False
    a, b = text.index(start) + len(start), text.index(end)
    path.write_text(text[:a] + "\n" + body + "\n" + text[b:], encoding="utf-8")
    return True


def update_readme(summary: dict, path: Path) -> bool:
    return update_between(path, README_START, README_END, readme_block(summary))


COLD_START, COLD_END = "<!-- COLDSTART:START -->", "<!-- COLDSTART:END -->"


def coldstart_table(cold: dict, days=(0, 30, 90, 365, 1460)) -> list[dict]:
    """A new station with D days of its own history, with and without a starter borrowed from the nearest other station."""
    by = {(r["days"], r["mode"]): r for r in cold["summary"]}
    rows = []
    for d in days:
        s, o = by.get((d, "starter")), by.get((d, "own_only"))
        if not s or not o:
            continue
        rows.append({"days of own history": d,
                     "with a starter: clean false alarms": f"{s['clean_alarm_pct']}%",
                     "with a starter: FAULT on real extreme weather": f"{s['event_fault_pct']}%",
                     "with a starter: injected faults detected": f"{s['detect_pct']}%",
                     "own data only: clean false alarms": f"{o['clean_alarm_pct']}%",
                     "own data only: FAULT on real extreme weather": f"{o['event_fault_pct']}%",
                     "own data only: injected faults detected": f"{o['detect_pct']}%"})
    return rows


def coldstart_block(cold: dict) -> str:
    L = markdown_table(coldstart_table(cold))
    t = cold.get("timing", {})
    L.append("Leave-one-station-out on the six DEV stations, judged on each station's DEV years (2020-2021), which it never trained on. "
             "The starter is a frozen normality table and frozen limits from the nearest other station, blended out as the station's own "
             "history grows; no live data of another station is used. Injected faults here are frozen, spike and level shift only. "
             "Details: [`results/REPORT.md`](results/REPORT.md)." + (f" ({t['jobs']} jobs, {t['wall_minutes']} minutes on {t['workers']} workers.)" if t else ""))
    return "\n".join(L)


def update_coldstart(cold: dict, path: Path) -> bool:
    return update_between(path, COLD_START, COLD_END, coldstart_block(cold))


JUDGE_START, JUDGE_END = "<!-- NUMBERS:START -->", "<!-- NUMBERS:END -->"


def judge_block(summary: dict) -> str:
    """The numbers to have in your head at the demo table, per split, straight from the summary."""
    L = ["**Numbers to have in your head** (generated from `results/summary.json`; say which split you are quoting):", ""]
    names = {"DEV": "DEV (tuned here)", "HOLDOUT_TIME": "holdout, same stations, later years",
             "HOLDOUT_SPACE": "holdout, eight unseen stations", "FRESH": "fresh, twelve more unseen stations"}
    for k, label in names.items():
        if k not in summary["phases"]:
            continue
        rows = summary["phases"][k]["headline"]["rows"]
        L.append(f"- **{label}:** clean data: {rows[0]['answer']}. Real extreme weather: {rows[1]['answer']}. "
                 f"Injected faults raised the alarm: {rows[2]['answer']}.")
    sc = summary.get("scale")
    if sc:
        big = sc["pipeline"][-1]
        L.append(f"- **Speed (simulated stations, one machine, one core, in-process, every layer on):** median {big['median_ms']} ms and "
                 f"99th percentile {big['p99_ms']} ms per reading with {big['stations']} stations, {big['readings_per_second']} readings/s.")
        L.append(f"- **What that means:** one core keeps up with about {int(big['readings_per_second'] * 60):,} stations reporting once a minute "
                 f"(readings per second x 60: arithmetic from the figure above, not a load test); more cores or worker processes scale it further.")
        nf = sc.get("pipeline_no_forest")
        if nf:
            L.append(f"- **The same with the Isolation Forest layer off** (a config flag; the ablation shows it adds almost nothing to the verdicts): "
                     f"median {nf[-1]['median_ms']} ms, {nf[-1]['readings_per_second']} readings/s.")
        h = sc.get("http")
        if h:
            L.append(f"- **Speed through the real HTTP server (FastAPI + SQLite, {h['stations']} stations, {h['clients']} clients):** "
                     f"median {h['median_ms']} ms, 95th percentile {h['p95_ms']} ms, {h['requests_per_second']} requests/s, "
                     f"{h['errors']} errors.")
    return "\n".join(L)


def update_judge_qa(summary: dict, path: Path) -> bool:
    return update_between(path, JUDGE_START, JUDGE_END, judge_block(summary))


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Build results/summary.json and results/REPORT.md.")
    ap.add_argument("results", nargs="+", type=Path, help="JSON files written by evaluate_real.py --out")
    ap.add_argument("--scale", type=Path, default=None, help="JSON written by loadtest.py")
    ap.add_argument("--coldstart", type=Path, default=None, help="JSON written by evaluate_coldstart.py")
    ap.add_argument("--sensitivity", type=Path, default=None, help="JSON written by evaluate_sensitivity.py")
    ap.add_argument("--peers", type=Path, nargs="*", default=[], help="JSON files written by evaluate_peers.py (cluster name = the part of the file name after peers_)")
    ap.add_argument("--peers-doc", type=Path, default=None, help="refresh the block between the PEERS markers in this file")
    ap.add_argument("--out-dir", type=Path, default=er.RESULTS_DIR)
    ap.add_argument("--readme", type=Path, default=None, help="refresh the block between the RESULTS markers in this README")
    ap.add_argument("--numbers", type=Path, nargs="*", default=[], help="refresh the block between the NUMBERS markers in these files")
    args = ap.parse_args(argv)
    results = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in args.results}
    scale = json.loads(args.scale.read_text(encoding="utf-8")) if args.scale and args.scale.exists() else None
    cold = json.loads(args.coldstart.read_text(encoding="utf-8")) if args.coldstart and args.coldstart.exists() else None
    sens = json.loads(args.sensitivity.read_text(encoding="utf-8")) if args.sensitivity and args.sensitivity.exists() else None
    summary = build_summary(results, scale, cold, sens)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    (args.out_dir / "REPORT.md").write_text(to_markdown(summary), encoding="utf-8")
    print(f"wrote {args.out_dir / 'summary.json'} and {args.out_dir / 'REPORT.md'}")
    if args.readme:
        print("README updated" if update_readme(summary, args.readme) else "README has no RESULTS markers: not updated")
    if args.readme and cold:
        print("README cold-start block updated" if update_coldstart(cold, args.readme) else "README has no COLDSTART markers: not updated")
    for f in args.numbers:
        print(f"{f}: numbers updated" if update_judge_qa(summary, f) else f"{f}: no NUMBERS markers, not updated")
    if args.peers and args.peers_doc:
        clusters = {p.stem.replace("peers_", "").upper(): json.loads(p.read_text(encoding="utf-8")) for p in args.peers}
        print("peer-layer doc updated" if update_peers(clusters, args.peers_doc) else "peer-layer doc has no PEERS markers: not updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
