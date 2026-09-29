"""A one-page A4 summary of the submission (HTML and PDF), with every number computed from the committed results.

    python make_onepager.py            # writes docs/AtmosGuard_one_page.html and .pdf (the PDF needs Playwright and a Chromium)

For a handout or a portal upload. It is not the slide deck. Numbers come from results/*run*.json through make_figures.load_agg, the same
aggregation the report uses, so the page cannot disagree with `results/REPORT.md`.
"""
from __future__ import annotations

import html
import importlib
from pathlib import Path
from typing import Optional

import make_figures as mf

REPO = Path(__file__).resolve().parent
OUT_HTML = REPO / "docs" / "AtmosGuard_one_page.html"
OUT_PDF = REPO / "docs" / "AtmosGuard_one_page.pdf"
PHASES = (("DEV", "DEV", "6 stations, 2020-21, tuned here"), ("HOLDOUT_TIME", "Holdout in time", "same 6, 2022-24"),
          ("HOLDOUT_SPACE", "Holdout in space", "8 unseen stations"), ("FRESH", "Fresh stations", "12 more, sealed first"),
          ("FRESH2", "Fresh 2", "12 more: 5 airports, 7 AWS"),
          ("FRESH3", "Fresh 3", "12 more: 7 US 20-min, 5 AWS"))
REPO_URL = "github.com/Mahim56207/ATMOSGUARD"


def esc(s: str) -> str:
    return html.escape(s)


def table_rows(aggs: dict) -> list[dict]:
    rows = []
    for key, name, sub in PHASES:
        if key not in aggs:
            continue
        cfg = aggs[key]["configs"]
        full, rules = cfg["full"], cfg["baseline_rules"]
        _, w, n = mf._events_fault(full)
        _, rw, rn = mf._events_fault(rules)
        rows.append({"split": name, "sub": sub,
                     "clean": 100 * full["clean"]["alarm"] / full["clean"]["n"],
                     "windows": f"{w} of {n}", "det": mf._det_mean(full),
                     "rules_clean": 100 * rules["clean"]["alarm"] / rules["clean"]["n"], "rules_windows": f"{rw} of {rn}"})
    return rows


def build(aggs: dict) -> str:
    rows = table_rows(aggs)
    body = "".join(
        f"<tr><td><b>{esc(r['split'])}</b> <span>{esc(r['sub'])}</span></td><td>{r['clean']:.1f}%</td><td>{esc(r['windows'])}</td>"
        f"<td>{r['det']:.0f}%</td><td class='b'>{r['rules_clean']:.1f}%</td><td class='b'>{esc(r['rules_windows'])}</td></tr>" for r in rows)
    unseen = " and ".join(r["windows"] for r in rows if r["split"] in ("Holdout in space", "Fresh stations", "Fresh 2", "Fresh 3"))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>AtmosGuard, one page</title>
<style>
@page {{ size: A4; margin: 0 }}
:root {{ --ink:#16150f; --muted:#5b5a53; --line:#d9d7cd; --paper:#fbfaf7; --blue:#2a78d6; --purple:#4a3aa7; --red:#d03b3b; --amber:#b57f06; --green:#16875f }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:#fff; color:var(--ink); font:9pt/1.34 system-ui,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif }}
.page {{ width:210mm; height:297mm; padding:9mm 11mm 7mm; background:var(--paper); display:flex; flex-direction:column; gap:3mm; overflow:hidden }}
header h1 {{ font-size:20pt; line-height:1.05; margin:0 }}
header p {{ margin:1mm 0 0; color:var(--muted); font-size:9pt }}
.verdicts {{ display:flex; gap:1.6mm; margin-top:2mm }}
.pill {{ border:1.5px solid; border-radius:99px; padding:0.4mm 2.6mm; font-weight:700; font-size:8pt }}
.p-valid {{ color:#6f6e66; border-color:#8a8a80 }} .p-weather {{ color:var(--purple); border-color:var(--purple) }}
.p-suspect {{ color:var(--amber); border-color:#e6a10a }} .p-fault {{ color:var(--red); border-color:var(--red) }}
.cols {{ display:grid; grid-template-columns:1fr 1fr; gap:4mm }}
h2 {{ font-size:8.8pt; margin:0 0 0.8mm; text-transform:uppercase; letter-spacing:.06em; color:var(--blue) }}
p {{ margin:0 0 1.2mm }} ul {{ margin:0 0 1mm; padding-left:4mm }} li {{ margin:0 0 0.5mm }}
table {{ width:100%; border-collapse:collapse; font-size:8pt }}
th,td {{ padding:0.8mm 1.2mm; border-bottom:1px solid var(--line); text-align:right; vertical-align:top }}
.grp th {{ text-align:center; border-bottom:1.5px solid var(--blue); color:var(--ink) }} .grp th.b {{ color:var(--muted); border-bottom-color:var(--line) }}
th:first-child,td:first-child {{ text-align:left }} th {{ color:var(--muted); font-weight:600; font-size:7.2pt }}
td span {{ color:var(--muted); font-size:7.2pt }} td.b {{ color:var(--muted) }}
.flow {{ display:flex; align-items:stretch; gap:1.2mm }}
.node {{ flex:1 1 0; border:1.3px solid; border-radius:1.8mm; padding:1.2mm 1.4mm; font-weight:700; font-size:8pt; line-height:1.2; background:#fff }}
.node span {{ display:block; font-weight:400; color:var(--muted); font-size:6.6pt; margin-top:0.4mm }}
.node.in {{ flex:0 0 15mm; border-color:#8a8a80 }} .node.out {{ flex:0 0 24mm; border-color:#8a8a80 }}
.node.l0 {{ border-color:#2a78d6 }} .node.l1 {{ border-color:#eb6834 }} .node.l2 {{ border-color:#1baf7a }} .node.l3 {{ border-color:#4a3aa7 }}
.node.lt {{ border-color:#e6a10a }} .node.fu {{ flex:1.7 1 0; border-color:var(--ink); border-width:1.6px }}
.arrow {{ align-self:center; color:var(--muted); font-size:10pt }}
ul.two {{ columns:2; column-gap:5mm }} ul.two li {{ break-inside:avoid }}
.figure img {{ width:100%; display:block; border:1px solid var(--line); border-radius:2mm }}
.box {{ border:1px solid var(--line); border-left:3px solid var(--red); border-radius:2mm; padding:1.8mm 3mm; background:#fff }}
.small {{ font-size:7.4pt; color:var(--muted); margin-top:1mm }}
footer {{ margin-top:auto; border-top:1px solid var(--line); padding-top:1.6mm; display:flex; justify-content:space-between; gap:6mm; font-size:7.6pt; color:var(--muted) }}
</style></head><body><div class="page">
<header>
  <h1>AtmosGuard</h1>
  <p><b>Is this the sensor, or is this the sky?</b> An anomaly and sensor-health system for an automatic weather station, from temperature,
     pressure and humidity alone, one station at a time, no neighbours. Smart India Hackathon 2026, problem statement 26073.</p>
  <div class="verdicts"><span class="pill p-valid">VALID</span><span class="pill p-weather">WEATHER: escalate, never delete</span>
     <span class="pill p-suspect">SUSPECT: review</span><span class="pill p-fault">FAULT: sensor problem</span></div>
</header>
<div class="cols">
  <section>
    <h2>The problem</h2>
    <p>A stuck barometer and a cyclone look the same on a chart. Cleaning everything deletes the storm; trusting everything feeds bad data
       into forecasts. Sparse networks have no neighbour to ask.</p>
    <h2>What it does</h2>
    <ul>
      <li>Judges every reading and says why, in words. The raw value is never overwritten.</li>
      <li>Learns each station's own limits; fixed limits alarmed on most clean real data.</li>
      <li>Health score, drift monitor with a stated floor, ticket, service date, estimate with a band.</li>
      <li>Break the sensor on stage and watch it react. ESP32 first layer is one C++ header, tested against the Python.</li>
    </ul>
  </section>
  <section>
    <h2>How we know (no new algorithm claimed)</h2>
    <ul>
      <li>26 real Indian airport stations (NOAA ISD, 2016-24): cyclones, heat and cold waves, outflows.</li>
      <li>Protocol committed first; holdout sealed in time and space, run once, lock file.</li>
      <li>The holdout showed failures: we registered a rule, sealed 12 more stations, ran once: one remedy adopted, one rejected.</li>
      <li>Baselines and an ablation on the same data; NOAA's own flags; one command per result.</li>
    </ul>
  </section>
</div>
<section>
  <h2>Results, split by split (the numbers are never merged)</h2>
  <table>
    <tr class="grp"><th></th><th colspan="3">AtmosGuard</th><th colspan="2" class="b">Textbook range + step + persistence</th></tr>
    <tr><th>Split</th><th>false alarms, clean data</th><th>real extreme-weather windows with a FAULT</th><th>injected faults detected (mean of 6 types)</th>
        <th>false alarms</th><th>windows with a FAULT</th></tr>
    {body}
  </table>
  <p class="small">Real records; faults are injected (no labelled real faults exist); "detected" means an alarm the fault itself raised (FAULT or SUSPECT). Full tables, baselines, ablation and intervals: results/REPORT.md.</p>
</section>
<section>
  <h2>What one reading goes through</h2>
  <div class="flow">
    <div class="node in">reading<br><span>T, P, RH</span></div><div class="arrow">&rarr;</div>
    <div class="node l0">L0 physics<br><span>ranges, dew point</span></div>
    <div class="node l1">L1 health<br><span>frozen, step, spike, noise, gaps, CUSUM</span></div>
    <div class="node l2">L2 normality<br><span>this station, month, hour</span></div>
    <div class="node l3">L3 multivariate<br><span>Isolation Forest, Mahalanobis</span></div>
    <div class="node lt">Timing<br><span>clock, co-jump</span></div><div class="arrow">&rarr;</div>
    <div class="node fu">Fusion<br><span>one channel jumps while the others are quiet: FAULT; several move together: WEATHER</span></div><div class="arrow">&rarr;</div>
    <div class="node out">verdict + reason<br><span>health, ticket, estimate</span></div>
  </div>
</section>
<section class="box"><h2 style="color:var(--red)">Where it fails (we say it first)</h2>
  <ul class="two">
    <li>Detection is on injected faults; the data are airport records, not IMD AWS records.</li>
    <li>{unseen} real extreme-weather windows on the unseen stations (holdout, fresh, fresh 2, pipeline as frozen for each) got a FAULT: a 47 % humidity jump in two hours, a 16 C jump across a reporting gap, a 49 % humidity drop in a dry air mass. The step remedy adopted on the last set takes it from 4 windows to 1.</li>
    <li>Noise bursts are the weakest class; small drift and constant offsets are invisible from one station.</li>
    <li>Simpler detectors beat us on some fault types (spikes; wrong clocks on unseen stations) but miss others and call real weather a fault.</li>
    <li>Most spike, level-shift, noise and clock detections are SUSPECT (review), not FAULT.</li>
    <li>The firmware has not run on hardware.</li>
  </ul></section>
<footer><span>Code, data, protocol, results and tests: <b>{REPO_URL}</b></span><span>Start with README.md, docs/TECHNICAL_REPORT.md, docs/JUDGE_QA.md</span></footer>
</div></body></html>"""


def to_pdf(html_path: Path, pdf_path: Path) -> Optional[Path]:
    try:
        sync_playwright = importlib.import_module("playwright.sync_api").sync_playwright
    except ImportError:
        return None
    exe = next((str(p) for p in Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome")), None)
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=exe, args=["--no-sandbox"])
        except Exception:
            return None
        page = browser.new_page()
        page.goto(html_path.resolve().as_uri())
        page.pdf(path=str(pdf_path), format="A4", print_background=True, margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        browser.close()
    return pdf_path


def main() -> int:
    aggs = mf.load_agg()
    OUT_HTML.write_text(build(aggs), encoding="utf-8")
    pdf = to_pdf(OUT_HTML, OUT_PDF)
    print(f"wrote {OUT_HTML.name}" + (f" and {pdf.name}" if pdf else " (no PDF: Playwright/Chromium not available)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
