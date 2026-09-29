"""Assemble docs/TECHNICAL_REPORT.md from its parts and from the results, so no number in it is typed by hand.

    python make_report.py                       # reads results/summary.json, writes docs/TECHNICAL_REPORT.md
    python make_report.py --docx                # also docs/TECHNICAL_REPORT.docx (needs pandoc or pypandoc_binary)

Parts (all committed):  docs/report_src/*.md (introduction, data and protocol), docs/REPRODUCE.md, docs/TECHNICAL_REPORT_methods.md,
config/protocol.md (tuning log and Amendment 1, quoted), docs/HOLDOUT_POSTMORTEM.md, docs/WHAT_WE_DO_NOT_CLAIM.md,
docs/FAILURE_MODES.md, docs/NOVELTY_AND_PRIOR_ART.md.  Tables come from results/summary.json (built by make_summary.py) and
results/coldstart.json.
"""
from __future__ import annotations

import argparse
import importlib
import json
import re
import subprocess
from pathlib import Path
from typing import Optional

from make_summary import markdown_table

REPO = Path(__file__).resolve().parent
DOCS = REPO / "docs"
PHASE_ORDER = ("DEV", "HOLDOUT_TIME", "HOLDOUT_SPACE")
PHASE_SHORT = {"DEV": "DEV (tuned here)", "HOLDOUT_TIME": "holdout in time (same six stations, 2022-2024)",
               "HOLDOUT_SPACE": "holdout in space (eight unseen stations)"}

REFERENCES = """\
1. Smith, A., Lott, N., Vose, R. (2011). The Integrated Surface Database: recent developments and partnering with the National Climatic Data Center. *Bulletin of the American Meteorological Society* 92, 704-708.
2. Dunn, R. J. H., Willett, K. M., Thorne, P. W., et al. (2012). HadISD: a quality-controlled global synoptic report database for selected variables at long-term stations from 1973-2011. *Climate of the Past* 8, 1649-1679.
3. Dunn, R. J. H., Willett, K. M., Parker, D. E., Mitchell, L. (2016). Expanding HadISD: quality-controlled, sub-daily station data from 1931. *Geoscientific Instrumentation, Methods and Data Systems* 5, 473-491.
4. Shafer, M. A., Fiebrich, C. A., Arndt, D. S., Fredrickson, S. E., Hughes, T. W. (2000). Quality assurance procedures in the Oklahoma Mesonetwork. *Journal of Atmospheric and Oceanic Technology* 17, 474-494.
5. Fiebrich, C. A., Morgan, C. R., McCombs, A. G., Hall, P. K., McPherson, R. A. (2010). Quality assurance procedures for mesoscale meteorological data. *Journal of Atmospheric and Oceanic Technology* 27, 1565-1582.
6. World Meteorological Organization. *Guide to Instruments and Methods of Observation* (WMO-No. 8).
7. Alduchov, O. A., Eskridge, R. E. (1996). Improved Magnus form approximation of saturation vapor pressure. *Journal of Applied Meteorology* 35, 601-609.
8. Stull, R. (2011). Wet-bulb temperature from relative humidity and air temperature. *Journal of Applied Meteorology and Climatology* 50, 2267-2269.
9. Liu, F. T., Ting, K. M., Zhou, Z.-H. (2008). Isolation Forest. *Proceedings of the IEEE International Conference on Data Mining*, 413-422.
10. Mahalanobis, P. C. (1936). On the generalised distance in statistics. *Proceedings of the National Institute of Sciences of India* 2, 49-55.
11. Page, E. S. (1954). Continuous inspection schemes. *Biometrika* 41, 100-115.
12. Mann, H. B. (1945). Nonparametric tests against trend. *Econometrica* 13, 245-259.
13. Sen, P. K. (1968). Estimates of the regression coefficient based on Kendall's tau. *Journal of the American Statistical Association* 63, 1379-1389.
14. Lundberg, S. M., Lee, S.-I. (2017). A unified approach to interpreting model predictions. *Advances in Neural Information Processing Systems* 30.
15. Ibrom, A., Dellwik, E., Flyvbjerg, H., Jensen, N. O., Pilegaard, K. (2007). Strong low-pass filtering effects on water vapour flux measurements with closed-path eddy correlation systems. *Agricultural and Forest Meteorology* 147, 140-156.
16. Mammarella, I., Launiainen, S., Gronholm, T., et al. (2009). Relative humidity effect on the high-frequency attenuation of water vapor flux measured by a closed-path eddy covariance system. *Journal of Atmospheric and Oceanic Technology* 26, 1856-1866.

Further sources (ECMWF observation monitoring, MADIS, sensor-network drift literature, the public repositories surveyed) are named next to the claim they support in Section 7 and in `docs/NOVELTY_AND_PRIOR_ART.md`.
"""


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def demote(md: str, by: int) -> str:
    """Push every Markdown heading `by` levels down (outside code fences)."""
    out, fenced = [], False
    for line in md.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
        if not fenced and re.match(r"#{1,6} ", line):
            line = "#" * min(6, line.index(" ") + by) + line[line.index(" "):]
        out.append(line)
    return "\n".join(out)


def section(md: str, heading: str) -> str:
    """The body of the `## heading` section (up to the next `## `), without the heading line."""
    m = re.search(rf"^## {re.escape(heading)}[^\n]*\n(.*?)(?=^## |\Z)", md, re.S | re.M)
    if not m:
        raise KeyError(f"no section '{heading}'")
    return m.group(1).strip("\n")


def drop_title(md: str) -> str:
    return re.sub(r"\A# [^\n]*\n+", "", md)


def from_first_section(md: str) -> str:
    """Everything from the first `## ` heading on (drops a title and an intro written for the demo, not for the report)."""
    i = md.index("\n## ") + 1
    return md[i:]


def _num(cell: str) -> Optional[float]:
    try:
        return float(str(cell).rstrip("%"))
    except ValueError:
        return None


def tradeoff_rows(phase: dict) -> list[dict]:
    """One line per system: its weakest injected-fault type, its clean false-alarm rate and its real-weather FAULT windows.

    Built from the phase tables, so it cannot drift from them. It shows that no single baseline is good at every fault type.
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


def abstract(summary: dict) -> str:
    ph = summary["phases"]
    lines = []
    for k in PHASE_ORDER:
        if k not in ph:
            continue
        rows = ph[k]["headline"]["rows"]
        lines.append(f"- **{PHASE_SHORT[k]}.** Clean data: {rows[0]['answer']}. Real extreme weather: {rows[1]['answer']}.")
    return "\n".join(lines)


def results_section(summary: dict, coldstart: Optional[list[dict]]) -> str:
    L = ["## 4. Results", "",
         "Everything in this section is generated by `make_summary.py` from the JSON that `evaluate_real.py` wrote, and is copied here by "
         "`make_report.py`; nothing is typed by hand. **The five numbers are never merged**: the injected-fault score, the "
         "false-alarm rate on clean data, what happens to real extreme weather, agreement with NOAA's flags, and drift are different "
         "questions. Injected faults are injected; NOAA's flags come from another automated system, not from truth.", ""]
    n = 0

    def head(title: str) -> str:
        nonlocal n
        n += 1
        return f"### 4.{n} {title}"

    for k in PHASE_ORDER:
        if k not in summary["phases"]:
            continue
        p = summary["phases"][k]
        L += [head(p["title"]), "", f"*{p['subtitle']}* Stations: {', '.join(p['stations'])}.", ""]
        for key in ("headline", "detection", "detection_named", "clean", "extreme_weather", "noaa", "drift", "by_station"):
            t = p[key]
            L += [f"#### {t['title']}", "", t["caption"], ""] + markdown_table(t["rows"])
            if key == "extreme_weather":
                L += ["Full pipeline, by kind of extreme weather:", ""] + markdown_table(t["by_kind"])
        t = p["detection_registered"]
        L += [f"#### {t['title']}", "", t["caption"], ""] + markdown_table(t["rows"])
        L += ["#### No single simpler system is good at every fault type", "",
              "Each system's weakest fault type from table 1, beside its false-alarm rate and its record on real extreme weather. A system "
              "that is best at one fault type is blind to another; the layers exist for coverage, and the WEATHER verdict exists so that "
              "coverage does not cost real storms.", ""] + markdown_table(tradeoff_rows(p))
    if "scale" in summary:
        s = summary["scale"]
        L += [head("Scale and speed"), "", s["note"], ""]
        L += markdown_table([{"stations": r["stations"], "readings/s": r["readings_per_second"], "median ms": r["median_ms"],
                              "p95 ms": r["p95_ms"], "p99 ms": r["p99_ms"], "MB/station": r["memory_per_station_mb"],
                              "KB stored/station": r["storage_per_station"]["total_kb"]} for r in s["pipeline"]])
        h = s.get("http")
        if h:
            L += [f"Real HTTP server (FastAPI + SQLite), {h['stations']} stations, {h['clients']} concurrent clients: "
                  f"{h['requests_per_second']} requests/s, median {h['median_ms']} ms, p95 {h['p95_ms']} ms, p99 {h['p99_ms']} ms, "
                  f"errors {h['errors']}.", ""]
    if coldstart:
        L += [head("A new station on day one (cold start)"), "",
              "Leave-one-station-out on the six DEV stations: the station is treated as brand new with D days of its own clean history; a "
              "starter is a frozen normality table borrowed from the nearest other station (never their live data), blended out as the "
              "station's own history grows. Judged on the station's DEV years it never trained on.", ""]
        L += markdown_table([{"own days": r["days"], "start": "starter" if r["mode"] == "starter" else "own data only",
                              "clean false alarms": f"{r['clean_alarm_pct']}%", "clean FAULT": f"{r['clean_fault_pct']}%",
                              "real-weather FAULT": f"{r['event_fault_pct']}%", "WEATHER": f"{r['event_weather_pct']}%",
                              "injected faults detected (frozen, spike, level shift)": f"{r['detect_pct']}%"} for r in coldstart])
    return "\n".join(L)


def build(summary: dict, coldstart: Optional[list[dict]]) -> str:
    src = DOCS / "report_src"
    protocol = read(REPO / "config" / "protocol.md")
    parts = [
        "# AtmosGuard: telling a broken sensor from real weather at one automatic weather station", "",
        "**Technical report.** Smart India Hackathon 2026, problem statement 26073. Repository: "
        "<https://github.com/Mahim56207/ATMOSGUARD>. Every number below is generated from the committed result files "
        "(`results/`), which are produced by the commands in `results/RUNS.md`.", "",
        "## Abstract", "",
        "AtmosGuard judges every temperature, pressure and humidity reading of a single automatic weather station, with no "
        "neighbouring stations, as `VALID`, `WEATHER`, `SUSPECT` or `FAULT`, and says why. Real extreme weather is escalated as its own "
        "verdict and is never deleted as noise. We claim no new algorithm; the contribution is the integration for one station and an "
        "evidence standard: 14 real Indian airport stations (NOAA ISD, 2016-2024), a protocol committed before a holdout that is sealed "
        "in time and in space, false alarms on real cyclones reported separately from injected-fault scores, baselines and an ablation on "
        "the same data, and the failures kept on record. Headline results:", "",
        abstract(summary), "",
        "Detection is measured on **injected** faults, because no labelled real faults exist; the data are airport records, not IMD AWS "
        "records; and on the eight unseen stations a small number of real extreme-weather windows did receive a `FAULT` verdict "
        "(Section 5). Sections 5 and 6 say exactly what we cannot show.", "",
        read(src / "01_introduction.md"), "",
        read(src / "02_data_protocol_intro.md"), "",
        "### 2.5 What was changed after looking at DEV (the tuning log, from `config/protocol.md`)", "",
        section(protocol, "Tuning log (everything changed after looking at DEV, and why)"), "",
        "### 2.6 Amendment: how detection is scored (from `config/protocol.md`)", "",
        section(protocol, "Amendment 1 (written after `holdout_run1` finished; the pipeline was not touched)"), "",
        read(DOCS / "TECHNICAL_REPORT_methods.md").rstrip(), "",
        results_section(summary, coldstart), "",
        "## 5. What the holdout found that development did not", "",
        demote(drop_title(read(DOCS / "HOLDOUT_POSTMORTEM.md")), 1), "",
        "## 6. Limitations: what we do not claim and cannot see", "",
        demote(from_first_section(read(DOCS / "WHAT_WE_DO_NOT_CLAIM.md")), 1), "",
        "### What the system cannot see", "",
        section(read(DOCS / "FAILURE_MODES.md"), "What the system cannot see"), "",
        "## 7. Related work and what is ours", "",
        "### 7.1 What is standard", "", section(read(DOCS / "NOVELTY_AND_PRIOR_ART.md"), "1. What is standard (not ours)"), "",
        "### 7.2 What we adapted", "", section(read(DOCS / "NOVELTY_AND_PRIOR_ART.md"), "2. What we adapted (their idea, our engineering)"), "",
        "### 7.3 What is ours", "", section(read(DOCS / "NOVELTY_AND_PRIOR_ART.md"), "3. What is ours")
        .replace("(the survey is in section 5)", "(the survey is in Section 7.4)").replace("listed (section 6)", "listed (Section 7.5)"), "",
        "### 7.4 The field on this problem statement", "", section(read(DOCS / "NOVELTY_AND_PRIOR_ART.md"), "5. The field on this problem statement (what judges will see side by side)"), "",
        "### 7.5 Failures real data exposed, and what we did", "", section(read(DOCS / "NOVELTY_AND_PRIOR_ART.md"), "6. Failures real data exposed, and what we did (kept on purpose)"), "",
        "## 8. Reproducing this report", "",
        "Times are for 4 CPU cores. The exact commands and the commit each result was produced under are in `results/RUNS.md`.", "",
        "### Does it work?", "", section(read(DOCS / "REPRODUCE.md"), "1. Does it work? (about 1 minute)"), "",
        "### The evidence", "", section(read(DOCS / "REPRODUCE.md"), "3. The evidence"), "",
        "### Determinism", "", section(read(DOCS / "REPRODUCE.md"), "Determinism"), "",
        "## References", "", REFERENCES,
    ]
    return "\n".join(parts).rstrip() + "\n"


def to_docx(md_path: Path) -> Path:
    out = md_path.with_suffix(".docx")
    try:                                        # optional: `pip install pypandoc_binary` (not in requirements.txt on purpose)
        pypandoc = importlib.import_module("pypandoc")
        pypandoc.convert_file(str(md_path), "docx", outputfile=str(out), extra_args=["--toc"])
    except (ImportError, OSError):
        subprocess.run(["pandoc", str(md_path), "-o", str(out), "--toc"], check=True)
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Assemble docs/TECHNICAL_REPORT.md.")
    ap.add_argument("--summary", type=Path, default=REPO / "results" / "summary.json")
    ap.add_argument("--coldstart", type=Path, default=REPO / "results" / "coldstart.json")
    ap.add_argument("--out", type=Path, default=DOCS / "TECHNICAL_REPORT.md")
    ap.add_argument("--docx", action="store_true")
    args = ap.parse_args(argv)
    summary = json.loads(read(args.summary))
    cold = json.loads(read(args.coldstart))["summary"] if args.coldstart.exists() else None
    args.out.write_text(build(summary, cold), encoding="utf-8")
    print(f"wrote {args.out}")
    if args.docx:
        print(f"wrote {to_docx(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
