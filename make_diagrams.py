"""Three diagrams for the slides and the report, as SVG (and PNG when Playwright and a Chromium are available).

    python make_diagrams.py            # writes docs/figures/diagram_*.svg and .png

  diagram_pipeline.svg   what a reading goes through and what comes out
  diagram_sensor_or_sky  the four verdicts, with a small trace of what each looks like
  diagram_evidence.svg   the order in which the evidence was produced (protocol first, holdout once, amendments, fresh stations)

Plain shapes, one font stack, colours that match the report figures. Text sits on light fills so the diagrams work on a white or dark slide.
"""
from __future__ import annotations

import html
import importlib
import re
import textwrap
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent
OUT = REPO / "docs" / "figures"
FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
INK, MUTED, LINE, PAPER = "#16150f", "#5b5a53", "#b9b8ac", "#fbfaf7"
BLUE, ORANGE, GREEN, RED, AMBER, PURPLE, GREY = "#2a78d6", "#eb6834", "#1baf7a", "#d03b3b", "#e6a10a", "#4a3aa7", "#8a8a80"
TINT = {BLUE: "#e6f0fb", ORANGE: "#fdece5", GREEN: "#e3f6ee", RED: "#fbe7e7", AMBER: "#fdf3dc", PURPLE: "#ebe8f7", GREY: "#efeee9"}


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def wrap(rows: list[str], width: float, size: float) -> list[str]:
    """Break each row so it fits `width` pixels (a proportional font averages about 0.57 x its size per character)."""
    n = max(8, int(width / (size * 0.57)))
    out: list[str] = []
    for r in rows:
        out += textwrap.wrap(r, n) or [""]
    return out


class Svg:
    def __init__(self, w: int, h: int):
        self.w, self.h, self.parts = w, h, []

    def add(self, s: str) -> None:
        self.parts.append(s)

    def rect(self, x, y, w, h, fill=PAPER, stroke=LINE, r=10, sw=1.5) -> None:
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')

    def text(self, x, y, s, size=18, weight=400, fill=INK, anchor="start") -> None:
        self.add(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{esc(s)}</text>')

    def lines(self, x, y, rows: list[str], size=16, gap=22, fill=MUTED, anchor="start", weight=400) -> None:
        for i, s in enumerate(rows):
            self.text(x, y + i * gap, s, size, weight, fill, anchor)

    def arrow(self, x1, y1, x2, y2, color=GREY) -> None:
        self.add(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="2.4"/>')
        import math
        a = math.atan2(y2 - y1, x2 - x1)
        p = [(x2, y2), (x2 - 11 * math.cos(a - 0.45), y2 - 11 * math.sin(a - 0.45)), (x2 - 11 * math.cos(a + 0.45), y2 - 11 * math.sin(a + 0.45))]
        self.add(f'<polygon points="{" ".join(f"{a_:.1f},{b_:.1f}" for a_, b_ in p)}" fill="{color}"/>')

    def card(self, x, y, w, h, color, title, rows, size=15) -> None:
        self.rect(x, y, w, h, TINT[color], color)
        self.text(x + 16, y + 28, title, 18, 700, INK)
        self.lines(x + 16, y + 54, wrap(rows, w - 32, size), size, 20, MUTED)

    def polyline(self, pts, color, sw=3) -> None:
        self.add(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" fill="none" stroke="{color}" stroke-width="{sw}" '
                 f'stroke-linejoin="round" stroke-linecap="round"/>')

    def render(self) -> str:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" height="{self.h}" '
                f'font-family="{FONT}"><rect width="{self.w}" height="{self.h}" fill="{PAPER}"/>' + "".join(self.parts) + "</svg>")


def pipeline() -> str:
    s = Svg(1700, 860)
    s.text(40, 52, "What one reading goes through", 30, 700)
    s.text(40, 82, "One station, its own history, no neighbours. Temperature, pressure and humidity only.", 18, 400, MUTED)
    s.card(40, 130, 340, 170, BLUE, "Where readings come from", ["ESP32 + BME280 (layer 0 runs on the device)", "Replay of real records", "Live fault injection (the demo)"])
    s.card(40, 340, 340, 190, GREY, "Learned per station", ["What is normal for this month and hour", "The reporting resolution", "The longest ordinary frozen run, the jitter, the usual step"])
    s.arrow(380, 215, 470, 215)
    s.arrow(380, 435, 470, 435)
    layers = [(BLUE, "L0 physics", "ranges, dew point <= temperature, wet-bulb (soft flag)"),
              (ORANGE, "L1 health", "frozen (two tiers), step, spike, noise, gaps, CUSUM"),
              (GREEN, "L2 normality", "is this normal for THIS station, month and hour?"),
              (PURPLE, "L3 multivariate", "Isolation Forest, and a Mahalanobis distance of departures and rates of change"),
              (AMBER, "Timing", "a wrong clock (3 h), a same-instant jump on several channels")]
    y = 120
    for color, title, sub in layers:
        s.rect(470, y, 520, 108, TINT[color], color)
        s.text(488, y + 34, title, 21, 700)
        s.lines(488, y + 62, wrap([sub], 480, 16), 16, 21, MUTED)
        y += 122
    s.arrow(990, 350, 1080, 350)
    s.rect(1080, 120, 320, 596, "#ffffff", INK, sw=2)
    s.text(1100, 156, "Fusion", 24, 700)
    s.lines(1100, 194, ["Impossible, frozen or missing", "   -> FAULT", "", "One channel jumps while the", "others are actually quiet", "   -> FAULT", "",
                        "Several channels move or", "depart together", "   -> WEATHER (an alert)", "", "Unusual but ambiguous", "   -> SUSPECT"], 16, 26, INK)
    s.arrow(1400, 350, 1450, 350)
    for i, (label, color, note) in enumerate((("VALID", GREY, "trust it"), ("WEATHER", PURPLE, "escalate, never delete"),
                                              ("SUSPECT", AMBER, "review, value kept"), ("FAULT", RED, "sensor problem"))):
        yy = 150 + i * 120
        s.rect(1450, yy, 210, 88, TINT[color], color, r=44, sw=2.5)
        s.text(1555, yy + 38, label, 22, 700, INK, "middle")
        s.text(1555, yy + 64, note, 15, 400, MUTED, "middle")
    s.rect(470, 748, 1190, 92, "#ffffff", LINE)
    s.text(488, 778, "Every verdict also carries", 17, 700)
    s.lines(488, 802, wrap(["a plain-English reason  |  a health score and the drift monitor  |  a maintenance ticket and service date  |  "
                            "an estimate with an uncertainty band (the raw value is never overwritten)"], 1150, 15), 15, 20, MUTED)
    return s.render()


def sensor_or_sky() -> str:
    s = Svg(1600, 620)
    s.text(40, 52, "Is this the sensor, or is this the sky?", 30, 700)
    s.text(40, 82, "The four verdicts, and what each one looks like on the three channels (sketches).", 18, 400, MUTED)
    cards = [
        (RED, "FAULT: one channel jumps", "The others stay calm.", [("T", [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5], BLUE), ("P", [0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6], ORANGE),
                                                                     ("RH", [0.2, 0.2, 0.2, 0.9, 0.9, 0.9, 0.9, 0.9], GREEN)]),
        (PURPLE, "WEATHER: all move together", "A cyclone, a front, an outflow.", [("T", [0.7, 0.7, 0.6, 0.45, 0.3, 0.3, 0.35, 0.4], BLUE),
                                                                                 ("P", [0.8, 0.8, 0.7, 0.45, 0.15, 0.2, 0.5, 0.7], ORANGE),
                                                                                 ("RH", [0.3, 0.3, 0.4, 0.6, 0.85, 0.9, 0.8, 0.7], GREEN)]),
        (RED, "FAULT: flat for too long", "Longer than this station ever holds.", [("T", [0.5, 0.6, 0.4, 0.5, 0.5, 0.5, 0.5, 0.5], BLUE),
                                                                                 ("P", [0.4, 0.5, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6], ORANGE),
                                                                                 ("RH", [0.5, 0.4, 0.6, 0.55, 0.55, 0.55, 0.55, 0.55], GREEN)]),
        (AMBER, "SUSPECT: unusual, mixed", "Reviewed by a person, value kept.", [("T", [0.5, 0.55, 0.5, 0.6, 0.75, 0.5, 0.55, 0.5], BLUE),
                                                                              ("P", [0.55, 0.55, 0.5, 0.5, 0.5, 0.55, 0.55, 0.5], ORANGE),
                                                                              ("RH", [0.5, 0.45, 0.5, 0.5, 0.45, 0.5, 0.5, 0.5], GREEN)])]
    for i, (color, title, note, traces) in enumerate(cards):
        x = 40 + i * 385
        s.rect(x, 120, 360, 470, TINT[color], color, sw=2)
        s.text(x + 18, 156, title, 19, 700)
        s.text(x + 18, 184, note, 16, 400, MUTED)
        for k, (lab, ys, col) in enumerate(traces):
            top = 216 + k * 118
            s.text(x + 18, top + 16, lab, 15, 700, col)
            pts = [(x + 60 + j * (270 / (len(ys) - 1)), top + 92 - v * 84) for j, v in enumerate(ys)]
            s.add(f'<line x1="{x + 60}" y1="{top + 96}" x2="{x + 330}" y2="{top + 96}" stroke="{LINE}" stroke-width="1"/>')
            s.polyline(pts, col)
    return s.render()


def evidence() -> str:
    s = Svg(1700, 560)
    s.text(40, 52, "The order the evidence was produced in", 30, 700)
    s.text(40, 82, "Each step is a commit. Nothing was tuned after the holdout was read.", 18, 400, MUTED)
    steps = [(BLUE, "1", "Protocol", "Splits, extreme-weather rules, metrics and baselines written and committed first"),
             (GREEN, "2", "Train and tune", "Own 2016-2019 record per station; tuning on six DEV stations, 2020-2021 only"),
             (AMBER, "3", "Freeze", "Code and settings frozen; real-data failures and their fixes are in the tuning log"),
             (PURPLE, "4", "Holdout, once", "Same six stations 2022-2024 and eight unseen stations; a lock file records the run"),
             (RED, "5", "Post-mortem", "3 of 98 windows got a FAULT; causes explained, remedies proposed, nothing tuned"),
             (ORANGE, "6", "Amendments", "1: fairer detection scoring. 2: remedies tested on twelve fresh stations, rule set first"),
             (GREY, "7", "Fresh run, once", "Twelve stations nobody had looked at; the registered rule decides, whatever it says")]
    w, gap = 200, 40
    for i, (color, n, title, body) in enumerate(steps):
        x = 30 + i * (w + gap)
        s.rect(x, 140, w, 340, TINT[color], color, sw=2)
        s.add(f'<circle cx="{x + 36}" cy="{184}" r="20" fill="{color}"/>')
        s.text(x + 36, 191, n, 20, 700, "#ffffff", "middle")
        s.text(x + 16, 246, title, 18, 700)
        s.lines(x + 16, 280, wrap([body], w - 30, 15), 15, 22, MUTED)
        if i < len(steps) - 1:
            s.arrow(x + w + 4, 310, x + w + gap - 4, 310)
    s.text(40, 530, "Reported for every split: false alarms on clean data, real extreme weather, injected faults, NOAA flags, drift. Never merged into one score.",
           16, 400, MUTED)
    return s.render()


DIAGRAMS = {"diagram_pipeline": pipeline, "diagram_sensor_or_sky": sensor_or_sky, "diagram_evidence": evidence}


def to_png(svg_path: Path) -> Optional[Path]:
    try:                                   # optional: Playwright is not a requirement of the project
        sync_playwright = importlib.import_module("playwright.sync_api").sync_playwright
    except ImportError:
        return None
    svg = svg_path.read_text(encoding="utf-8")
    png = svg_path.with_suffix(".png")
    exe = next((p for p in Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome")), None)
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(executable_path=str(exe) if exe else None, args=["--no-sandbox"])
        except Exception:
            return None
        w, h = (int(v) for v in re.search(r'viewBox="0 0 (\d+) (\d+)"', svg).groups())
        page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1.5)
        page.set_content(f'<html><body style="margin:0">{svg}</body></html>')
        page.screenshot(path=str(png), clip={"x": 0, "y": 0, "width": w, "height": h})
        browser.close()
    return png


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, fn in DIAGRAMS.items():
        p = OUT / f"{name}.svg"
        p.write_text(fn(), encoding="utf-8")
        png = to_png(p)
        print(f"wrote {p.name}" + (f" and {png.name}" if png else " (no PNG: Playwright/Chromium not available)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
