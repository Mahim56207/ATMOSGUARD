"""Figures for the report, from the committed results. Skips any figure whose input is missing.

    python make_figures.py                       # reads results/*.json, writes docs/figures/*.png

Colours: one colour per system, chosen to be distinguishable with the common colour-vision deficiencies, and every bar is
also labelled with its value, so colour is never the only cue.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import evaluate_real as er
from atmos.config import load_settings
from atmos.fusion import Pipeline
from atmos.schema import CHANNELS

REPO = Path(__file__).resolve().parent
RES = REPO / "results"
OUT = REPO / "docs" / "figures"
INK, MUTED, GRID = "#16150f", "#5b5a53", "#dcdad2"
C = {"full": "#2a78d6", "base": "#8a8a80", "bad": "#d03b3b", "warn": "#e6a10a", "ok": "#1baf7a", "weather": "#4a3aa7",
     "T": "#2a78d6", "P": "#eb6834", "RH": "#1baf7a"}
LABELS = {"full": "AtmosGuard", "baseline_rules": "textbook range+step+persistence", "baseline_range": "range check only",
          "baseline_climatology": "climatology z-score", "baseline_isolation_forest": "Isolation Forest only",
          "baseline_mahalanobis": "Mahalanobis only", "no_limits": "AtmosGuard without learned limits"}


def style(ax, title: str) -> None:
    ax.set_title(title, loc="left", fontsize=11, color=INK, fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(axis="x", color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)


def load_agg() -> dict[str, dict]:
    aggs: dict[str, dict] = {}
    for f in sorted(RES.glob("*run*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if not d.get("stations") or d.get("quick") or "configs" not in d["stations"][0]:
            continue
        for ph in dict.fromkeys(r["phase"] for r in d["stations"]):
            aggs[ph] = er.aggregate(d["stations"], ph)
    return aggs


def fig_events() -> None:
    """Three real cyclones with the verdict AtmosGuard gave every reading. Nothing injected."""
    settings = load_settings()
    demos = [("fani_BBI_2019-05", "BBI", "Cyclone Fani, Bhubaneswar, May 2019"),
             ("vardah_MAA_2016-12", "MAA", "Cyclone Vardah, Chennai, Dec 2016"),
             ("amphan_CCU_2020-05", "CCU", "Cyclone Amphan, Kolkata, May 2020")]
    fig, axes = plt.subplots(3, 3, figsize=(13, 8.6), sharex="row")
    for row, (name, sid, title) in enumerate(demos):
        df = pd.read_csv(REPO / "data" / "demo" / f"{name}.csv", parse_dates=["timestamp"])
        pipe = Pipeline(settings, {sid: {"cadence_minutes": 60}})
        pipe.load_models(sid)
        verdicts = [pipe.process(r).verdict.value for r in er.to_readings(df)]
        for col, (ch, lab, key) in enumerate((("temperature_c", "temperature (C)", "T"), ("pressure_hpa", "pressure (hPa)", "P"),
                                              ("humidity_pct", "relative humidity (%)", "RH"))):
            ax = axes[row, col]
            ax.plot(df["timestamp"], df[ch], color=C[key], lw=1.6)
            for v, marker, colr in (("WEATHER", "^", C["weather"]), ("SUSPECT", "D", C["warn"]), ("FAULT", "x", C["bad"])):
                idx = [i for i, x in enumerate(verdicts) if x == v]
                if idx:
                    ax.scatter(df["timestamp"].iloc[idx], df[ch].iloc[idx], marker=marker, s=34, color=colr, zorder=3,
                               label=v.lower(), linewidths=1.6 if v == "FAULT" else 0.6, edgecolors="white" if v != "FAULT" else colr)
            style(ax, f"{title}: {lab}" if col == 0 else lab)
            ax.tick_params(axis="x", rotation=25)
            ax.grid(axis="y", color=GRID, linewidth=0.6)
        counts = {k: verdicts.count(k) for k in ("VALID", "WEATHER", "SUSPECT", "FAULT")}
        axes[row, 0].text(0.01, 0.04, f"{counts['WEATHER']} weather, {counts['SUSPECT']} suspect, {counts['FAULT']} fault of {len(verdicts)}",
                          transform=axes[row, 0].transAxes, fontsize=9, color=MUTED)
    h, l = axes[0, 1].get_legend_handles_labels()
    fig.legend(h, l, loc="upper right", ncol=3, frameon=False, fontsize=10)
    fig.suptitle("Real cyclones, nothing injected: the pressure crash is escalated as weather, never called a fault", x=0.01, ha="left",
                 fontsize=13, fontweight="bold", color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(OUT / "fig_real_cyclones.png", dpi=150)
    plt.close(fig)


def _det_mean(c: dict) -> float:
    r = [100 * c["detection"][t].get("detected_new", 0) / c["detection"][t]["injected"] for t in er.REAL_TYPES if c["detection"][t]["injected"]]
    return float(np.mean(r)) if r else float("nan")


def _events_fault(c: dict) -> tuple[float, int, int]:
    t = {k: sum(d.get(k, 0) for d in c["events"].values()) for k in ("n", "FAULT", "windows", "windows_with_fault")}
    return 100 * t["FAULT"] / max(t["n"], 1), t["windows_with_fault"], t["windows"]


def fig_baselines(aggs: dict) -> None:
    order = ["full", "baseline_rules", "baseline_mahalanobis", "baseline_climatology", "baseline_isolation_forest", "baseline_range", "no_limits"]
    phases = [p for p in ("DEV", "HOLDOUT_TIME", "HOLDOUT_SPACE", "FRESH") if p in aggs]
    if not phases:
        return
    fig, axes = plt.subplots(len(phases), 3, figsize=(14, 3.3 * len(phases) + 0.6), squeeze=False)
    titles = {"DEV": "DEV", "HOLDOUT_TIME": "holdout in time", "HOLDOUT_SPACE": "holdout in space", "FRESH": "fresh stations"}
    for r, ph in enumerate(phases):
        cfg = aggs[ph]["configs"]
        y = np.arange(len(order))[::-1]
        measures = [
            ("false alarms on clean data (%)", [100 * cfg[n]["clean"]["alarm"] / cfg[n]["clean"]["n"] for n in order], "{:.1f}%"),
            ("FAULT on real extreme weather (%)", [_events_fault(cfg[n])[0] for n in order], "{:.1f}%"),
            ("injected faults detected (mean, %)", [_det_mean(cfg[n]) for n in order], "{:.0f}%"),
        ]
        for c, (title, vals, fmt) in enumerate(measures):
            ax = axes[r, c]
            colors = [C["full"] if n == "full" else C["bad"] if n == "no_limits" else C["base"] for n in order]
            ax.barh(y, vals, color=colors, height=0.62)
            for yy, v in zip(y, vals):
                ax.text(v + max(vals) * 0.012, yy, fmt.format(v), va="center", fontsize=9, color=INK)
            ax.set_yticks(y)
            ax.set_yticklabels([LABELS[n] for n in order] if c == 0 else [], fontsize=9)
            ax.set_xlim(0, max(vals) * 1.18 if max(vals) > 0 else 1)
            style(ax, f"{titles[ph]}\n{title}")
    fig.suptitle("Same real data, same three numbers, for AtmosGuard and simpler systems (lower is better in the first two, higher in the third)",
                 x=0.01, ha="left", fontsize=12, fontweight="bold", color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(OUT / "fig_baselines.png", dpi=150)
    plt.close(fig)


def fig_ablation(aggs: dict) -> None:
    if "DEV" not in aggs:
        return
    cfg = aggs["DEV"]["configs"]
    names = ["full", "no_physics", "no_health", "no_normality", "no_mlmodel", "no_mahalanobis", "no_timing", "no_limits"]
    names = [n for n in names if n in cfg]
    labels = {"full": "full", "no_physics": "no physics", "no_health": "no health", "no_normality": "no normality",
              "no_mlmodel": "no Isolation Forest", "no_mahalanobis": "no Mahalanobis", "no_timing": "no timing", "no_limits": "no learned limits"}
    fig, ax = plt.subplots(figsize=(12, 4.6))
    w = 0.8 / len(er.REAL_TYPES)
    pal = ["#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7", "#e6a10a", "#8a8a80"]
    x = np.arange(len(names))
    for i, t in enumerate(er.REAL_TYPES):
        vals = [100 * cfg[n]["detection"][t].get("detected_new", 0) / max(cfg[n]["detection"][t]["injected"], 1) for n in names]
        ax.bar(x + (i - len(er.REAL_TYPES) / 2 + 0.5) * w, vals, w, label=t.replace("_", " "), color=pal[i])
    ax.set_xticks(x)
    ax.set_xticklabels([labels[n] for n in names], fontsize=9)
    ax.set_ylabel("injected faults whose alarm the fault raised (%)", color=MUTED)
    ax.legend(ncol=6, frameon=False, fontsize=9, loc="lower center", bbox_to_anchor=(0.5, 1.0))
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    for i, n in enumerate(names):
        fa = 100 * cfg[n]["clean"]["alarm"] / cfg[n]["clean"]["n"]
        ax.text(i, 104, f"{fa:.1f}%\nfalse alarms", ha="center", fontsize=8, color=C["bad"] if fa > 10 else MUTED)
    ax.set_ylim(0, 118)
    fig.suptitle("Ablation on DEV: what each layer is worth (bars) and what it costs in false alarms on clean real data (top)", x=0.01, ha="left",
                 fontsize=12, fontweight="bold", color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(OUT / "fig_ablation.png", dpi=150)
    plt.close(fig)


def fig_remedies(aggs: dict) -> None:
    """The two post-mortem remedies against the frozen pipeline, on stations nobody had looked at (Amendment 2)."""
    if "FRESH" not in aggs or "remedies" not in aggs["FRESH"]["configs"]:
        return
    cfg = aggs["FRESH"]["configs"]
    names = ["full", "remedy_frozen", "remedy_step", "remedies"]
    labels = {"full": "frozen\npipeline", "remedy_frozen": "+ remedy 1\nceiling-aware\nfrozen rule", "remedy_step": "+ remedy 2\nlearned\nstep cap",
              "remedies": "+ both"}
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.6))
    fw = [_events_fault(cfg[n])[1] for n in names]
    fs = [_events_fault(cfg[n])[0] for n in names]
    det = [_det_mean(cfg[n]) for n in names]
    for ax, vals, title, fmt in ((axes[0], fw, "real extreme-weather windows with a FAULT", "{:.0f}"),
                                 (axes[1], fs, "FAULT share of extreme-weather samples (%)", "{:.2f}%"),
                                 (axes[2], det, "injected faults detected (mean of types, %)", "{:.1f}%")):
        ax.bar(range(len(names)), vals, color=[C["full"], C["ok"], C["ok"], C["weather"]], width=0.6)
        for i, v in enumerate(vals):
            ax.text(i, v + max(max(vals) * 0.02, 0.01), fmt.format(v), ha="center", fontsize=9, color=INK)
        ax.set_xticks(range(len(names)))
        ax.set_xticklabels([labels[n] for n in names], fontsize=8.5)
        ax.set_ylim(0, max(vals) * 1.18 if max(vals) > 0 else 1)
        ax.set_title(title, loc="left", fontsize=10, color=INK, fontweight="bold")
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", color=GRID, linewidth=0.6)
        ax.set_axisbelow(True)
    fig.suptitle("Fresh stations, sealed before the test: what the two remedies from the holdout post-mortem do", x=0.01, ha="left",
                 fontsize=12, fontweight="bold", color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(OUT / "fig_remedies.png", dpi=150)
    plt.close(fig)


def fig_drift(aggs: dict) -> None:
    ph = "HOLDOUT_TIME" if "HOLDOUT_TIME" in aggs else "DEV" if "DEV" in aggs else None
    if ph is None:
        return
    d = aggs[ph]["drift"]
    sev = (0.0, *er.DRIFT_SEVERITIES)
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    for ch, key in zip(CHANNELS, ("T", "P", "RH")):
        y = [100 * d[f"{ch}|{s:g}"]["detected"] / max(d[f"{ch}|{s:g}"]["trials"], 1) for s in sev]
        ax.plot(range(len(sev)), y, marker="o", color=C[key], lw=2, label={"T": "temperature", "P": "pressure", "RH": "humidity"}[key])
    ax.set_xticks(range(len(sev)))
    ax.set_xticklabels(["none\n(false claims)"] + [f"{s:g}x" for s in er.DRIFT_SEVERITIES])
    ax.set_xlabel("drift at the end of a 45-day ramp, in multiples of the service limit", color=MUTED)
    ax.set_ylabel("chunks where drift was claimed (%)", color=MUTED)
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    fig.suptitle(f"One station, no reference ({ph.replace('_', ' ').lower()}): only large drifts are visible", x=0.01, ha="left", fontsize=11,
                 fontweight="bold", color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(OUT / "fig_drift_power.png", dpi=150)
    plt.close(fig)


def fig_scale() -> None:
    p = RES / "scale.json"
    if not p.exists():
        return
    d = json.loads(p.read_text(encoding="utf-8"))
    rows = d["pipeline_by_station_count"]
    n = [r["stations"] for r in rows]
    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    for key, lab, col in (("median_ms", "median", C["full"]), ("p95_ms", "95th percentile", C["warn"]), ("p99_ms", "99th percentile", C["bad"])):
        ax.plot(n, [r[key] for r in rows], marker="o", color=col, lw=2, label=lab)
    nf = d.get("pipeline_without_isolation_forest") or []
    if nf:
        ax.plot([r["stations"] for r in nf], [r["median_ms"] for r in nf], marker="s", ls="--", color=C["ok"], lw=2,
                label="median, Isolation Forest layer off")
    ax.set_xscale("log")
    ax.set_xticks(n)
    ax.set_xticklabels([str(x) for x in n])
    ax.set_xlabel("simulated stations on one machine", color=MUTED)
    ax.set_ylabel("time per reading in the pipeline (ms)", color=MUTED)
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    fig.suptitle("Per-reading cost does not grow with the number of stations (state is per station)", x=0.01, ha="left", fontsize=11,
                 fontweight="bold", color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(OUT / "fig_scale.png", dpi=150)
    plt.close(fig)


def fig_coldstart() -> None:
    p = RES / "coldstart.json"
    if not p.exists():
        return
    rows = json.loads(p.read_text(encoding="utf-8"))["summary"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, key, title in ((axes[0], "clean_alarm_pct", "false alarms on clean data (%)"), (axes[1], "detect_pct", "injected faults detected (%)")):
        for mode, col, lab in (("starter", C["full"], "with a starter from the nearest other station"), ("own_only", C["bad"], "own data only")):
            sel = [r for r in rows if r["mode"] == mode]
            ax.plot(range(len(sel)), [r[key] for r in sel], marker="o", color=col, lw=2, label=lab)
        days = sorted({r["days"] for r in rows})
        ax.set_xticks(range(len(days)))
        ax.set_xticklabels([str(d) for d in days])
        ax.set_xlabel("days of the new station's own history", color=MUTED)
        ax.set_ylim(0, 100 if key == "detect_pct" else None)          # start at zero: a truncated axis exaggerates the gain
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", color=GRID, linewidth=0.6)
        ax.set_title(title, loc="left", fontsize=10, color=INK, fontweight="bold")
    axes[0].legend(frameon=False, fontsize=9)
    fig.suptitle("A new station on day one: leave-one-station-out on six real stations", x=0.01, ha="left", fontsize=11, fontweight="bold", color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(OUT / "fig_coldstart.png", dpi=150)
    plt.close(fig)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    aggs = load_agg()
    fig_events()
    fig_baselines(aggs)
    fig_ablation(aggs)
    fig_remedies(aggs)
    fig_drift(aggs)
    fig_scale()
    fig_coldstart()
    print("wrote", ", ".join(sorted(p.name for p in OUT.glob("*.png"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
