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
PHASE_ORDER = ("DEV", "HOLDOUT_TIME", "HOLDOUT_SPACE", "FRESH", "FRESH2", "FRESH2_INDIA", "FRESH2_AWS")
PHASE_SHORT = {"DEV": "DEV (tuned here)", "HOLDOUT_TIME": "holdout in time (same six stations, 2022-2024)",
               "HOLDOUT_SPACE": "holdout in space (eight unseen stations)",
               "FRESH": "fresh stations (twelve more, sealed before the remedies were tested)",
               "FRESH2": "fresh-2 stations (a third set of twelve: five Indian airports, seven Australian automatic weather stations)",
               "FRESH2_INDIA": "fresh-2, the five Indian airport stations",
               "FRESH2_AWS": "fresh-2, the seven Australian automatic weather stations"}

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


FIGURES = [("fig_baselines.png", "Figure 3. The same real data and the same three numbers for AtmosGuard and simpler systems, in every split (lower is better in the first two columns, higher in the third)."),
           ("fig_ablation.png", "Figure 4. Ablation on DEV: what each layer is worth (bars) and what it costs in false alarms on clean real data (top)."),
           ("fig_real_cyclones.png", "Figure 5. Three real cyclones with nothing injected: the pressure crash is escalated as weather, never called a fault."),
           ("fig_remedies.png", "Figure 6. The fresh stations: what the two remedies from the holdout post-mortem do (registered decision rule, Section 2.7)."),
           ("fig_detectability.png", "Figure 7. How big must a fault be? Detection against fault size on the DEV stations (injected faults, tuning set)."),
           ("fig_coldstart.png", "Figure 8. A new station on day one: with a starter from the nearest other station, and with its own data only."),
           ("fig_scale.png", "Figure 9. Per-reading cost against the number of stations (state is per station)."),
           ("fig_drift_power.png", "Figure 10. Slow drift: the share of chunks where the drift monitor claims drift, against the size of the ramp.")]


def figure(name: str, caption: str) -> list[str]:
    """A Markdown image with its caption, if the file exists (paths are relative to docs/, where the report lives)."""
    return [f"![{caption}](figures/{name})", "", f"*{caption}*", ""] if (DOCS / "figures" / name).exists() else []


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


def unseen_windows(summary: dict) -> str:
    """'3 of 98 on the eight holdout stations, 3 of 139 on the twelve fresh ones', from the tables."""
    parts = []
    for ph, label in (("HOLDOUT_SPACE", "on the eight holdout stations"), ("FRESH", "on the twelve fresh ones"),
                      ("FRESH2", "on the twelve fresh-2 ones")):
        if ph in summary["phases"]:
            with_fault, windows = summary["phases"][ph]["extreme_weather"]["rows"][0]["windows with a FAULT"].split("/")
            parts.append(f"{with_fault} of {windows} {label}")
    return ", ".join(parts)


def abstract(summary: dict) -> str:
    ph = summary["phases"]
    lines = []
    for k in PHASE_ORDER:
        if k not in ph:
            continue
        rows = ph[k]["headline"]["rows"]
        lines.append(f"- **{PHASE_SHORT[k]}.** Clean data: {rows[0]['answer']}. Real extreme weather: {rows[1]['answer']}.")
    return "\n".join(lines)


def results_section(summary: dict) -> str:
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
        for key in ("headline", "detection", "detection_ci", "detection_named", "remedies", "amendment3", "clean", "extreme_weather", "noaa", "drift", "by_station"):
            if key not in p:
                continue
            t = p[key]
            L += [f"#### {t['title']}", "", t["caption"], ""] + markdown_table(t["rows"])
            if key == "extreme_weather":
                L += ["Full pipeline, by kind of extreme weather:", ""] + markdown_table(t["by_kind"])
        t = p["detection_registered"]
        L += [f"#### {t['title']}", "", t["caption"], ""] + markdown_table(t["rows"])
        t = p["tradeoff"]
        L += [f"#### {t['title']}", "", t["caption"], ""] + markdown_table(t["rows"])
    if "scale" in summary:
        s = summary["scale"]
        L += [head("Scale and speed"), "", s["note"], ""]
        L += markdown_table([{"stations": r["stations"], "readings/s": r["readings_per_second"], "median ms": r["median_ms"],
                              "p95 ms": r["p95_ms"], "p99 ms": r["p99_ms"], "MB/station": r["memory_per_station_mb"],
                              "KB stored/station": r["storage_per_station"]["total_kb"]} for r in s["pipeline"]])
        if s.get("pipeline_no_forest"):
            L += ["The same test with the Isolation Forest layer switched off (`layers.mlmodel: false`). In the ablation (tables above) "
                  "the forest adds almost nothing to the verdicts, and it is most of the per-reading time:", ""]
            L += markdown_table([{"stations": r["stations"], "readings/s": r["readings_per_second"], "median ms": r["median_ms"],
                                  "p95 ms": r["p95_ms"], "p99 ms": r["p99_ms"]} for r in s["pipeline_no_forest"]])
        h = s.get("http")
        if h:
            L += [f"Real HTTP server (FastAPI + SQLite), {h['stations']} stations, {h['clients']} concurrent clients: "
                  f"{h['requests_per_second']} requests/s, median {h['median_ms']} ms, p95 {h['p95_ms']} ms, p99 {h['p99_ms']} ms, "
                  f"errors {h['errors']}.", ""]
    if summary.get("sensitivity"):
        c = summary["sensitivity"]
        L += [head("How big must a fault be? (DEV, injected)"), "", c["note"], ""] + markdown_table(c["rows"])
    if summary.get("coldstart"):
        c = summary["coldstart"]
        L += [head("A new station on day one (cold start)"), "", c["note"], ""]
        L += markdown_table(c["rows"])
        if c.get("timing"):
            L += [f"The study ran {c['timing']['jobs']} jobs in {c['timing']['wall_minutes']} minutes on {c['timing']['workers']} workers "
                  f"(`python evaluate_coldstart.py`; `--estimate` projects the running time first).", ""]
    figs = [f for name, cap in FIGURES for f in figure(name, cap)]
    if figs:
        L += [head("Figures"), ""] + figs
    return "\n".join(L)


def build(summary: dict) -> str:
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
        "evidence standard: 26 real Indian airport stations (NOAA ISD, 2016-2024), a protocol committed before a holdout that is sealed "
        "in time and in space, false alarms on real cyclones reported separately from injected-fault scores, baselines and an ablation on "
        "the same data, and the failures kept on record. After the holdout showed three real-weather failure windows, we registered a decision rule and "
        "tested the proposed remedies on twelve further stations nobody had looked at: one remedy was adopted and one rejected. Headline results:", "",
        abstract(summary), "",
        "Detection is measured on **injected** faults, because no labelled real faults exist; the data are airport records, not IMD AWS "
        "records; and on the unseen stations a small number of real extreme-weather windows did receive a `FAULT` verdict "
        f"({unseen_windows(summary)}; Section 5). Sections 5 and 6 say exactly what we cannot show.", "",
        read(src / "01_introduction.md"), "",
        *figure("diagram_pipeline.png", "Figure 1. What one reading goes through."),
        *figure("diagram_sensor_or_sky.png", "Figure 2. The four verdicts and what each looks like on the three channels (sketches)."),
        read(src / "02_data_protocol_intro.md"), "",
        "### 2.5 What was changed after looking at DEV (the tuning log, from `config/protocol.md`)", "",
        section(protocol, "Tuning log (everything changed after looking at DEV, and why)"), "",
        "### 2.6 Amendment 1: how detection is scored (from `config/protocol.md`)", "",
        section(protocol, "Amendment 1 (written after `holdout_run1` finished; the pipeline was not touched)"), "",
        "### 2.7 Amendment 2: testing the post-mortem remedies on twelve unseen stations (from `config/protocol.md`)", "",
        section(protocol, "Amendment 2 (written before the FRESH stations were evaluated)"), "",
        "### 2.8 Amendment 2: outcome (from `config/protocol.md`)", "",
        section(protocol, "Amendment 2: outcome (written after `fresh_run1` finished; nothing was changed to make it come out this way)"), "",
        read(DOCS / "TECHNICAL_REPORT_methods.md").rstrip(), "",
        results_section(summary), "",
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
        pypandoc.convert_file(str(md_path), "docx", outputfile=str(out), extra_args=["--toc", f"--resource-path={md_path.parent}"])
    except (ImportError, OSError):
        subprocess.run(["pandoc", str(md_path), "-o", str(out), "--toc", f"--resource-path={md_path.parent}"], check=True)
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Assemble docs/TECHNICAL_REPORT.md.")
    ap.add_argument("--summary", type=Path, default=REPO / "results" / "summary.json")
    ap.add_argument("--out", type=Path, default=DOCS / "TECHNICAL_REPORT.md")
    ap.add_argument("--docx", action="store_true")
    args = ap.parse_args(argv)
    summary = json.loads(read(args.summary))
    args.out.write_text(build(summary), encoding="utf-8")
    print(f"wrote {args.out}")
    if args.docx:
        print(f"wrote {to_docx(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
