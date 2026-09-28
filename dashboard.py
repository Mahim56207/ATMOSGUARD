"""Streamlit + Plotly dashboard. It only READS from the API (/status /latest /alerts /health).

Run:  streamlit run dashboard.py      (API address: env ATMOS_API_URL, else dashboard.api_url in settings.yaml)

Charts: one panel per channel (identity by panel and title, fixed colour per channel). Verdicts are marked
on the panel of the channel they point at, with a different SHAPE per verdict so colour is never the only
cue. A table view of the same data is under "Data table".
"""
from __future__ import annotations

import os
from typing import Optional

import httpx
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from atmos.config import load_settings
from atmos.healthscore import flagged_channels
from atmos.schema import CHANNELS, StoredRecord

CHANNEL_LABELS = {"temperature_c": "Temperature (°C)", "pressure_hpa": "Pressure (hPa)",
                  "humidity_pct": "Relative humidity (%)"}

# Colours: validated with the dataviz palette validator (categorical slots 1-3, all-pairs, both modes).
THEMES = {
    "light": {"text": "#0b0b0b", "muted": "#52514e", "grid": "rgba(80,80,78,0.18)",
              "series": {"temperature_c": "#2a78d6", "pressure_hpa": "#eb6834", "humidity_pct": "#1baf7a"},
              "verdict": {"FAULT": "#d03b3b", "SUSPECT": "#fab219", "WEATHER": "#4a3aa7"}},
    "dark": {"text": "#ffffff", "muted": "#c3c2b7", "grid": "rgba(200,200,190,0.18)",
             "series": {"temperature_c": "#3987e5", "pressure_hpa": "#d95926", "humidity_pct": "#199e70"},
             "verdict": {"FAULT": "#d03b3b", "SUSPECT": "#fab219", "WEATHER": "#9085e9"}},
}
VERDICT_SYMBOL = {"FAULT": "x", "SUSPECT": "diamond", "WEATHER": "triangle-up"}


def fetch(api_url: str, path: str, params: Optional[dict] = None):
    r = httpx.get(api_url.rstrip("/") + path, params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def db_label(ch: str) -> str:
    return CHANNEL_LABELS[ch]


def parse_records(raw: list[dict]) -> list[StoredRecord]:
    """API returns newest first; the charts want oldest first."""
    return sorted((StoredRecord.model_validate(x) for x in raw), key=lambda r: (r.reading.timestamp, r.id))


def marked_channels(rec: StoredRecord, settings: dict) -> frozenset:
    """Channels to mark on the charts. If no flagged check points at a channel, mark all three."""
    if rec.verdict is None:
        return frozenset()
    return flagged_channels(rec.verdict.checks, rec.reading, settings) or frozenset(CHANNELS)


def build_figure(records: list[StoredRecord], settings: dict, mode: str = "light") -> go.Figure:
    theme = THEMES[mode]
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.09,
                        subplot_titles=[CHANNEL_LABELS[c] for c in CHANNELS])
    shown: set[str] = set()
    for row, ch in enumerate(CHANNELS, start=1):
        xs = [r.reading.timestamp for r in records]
        ys = [getattr(r.reading, ch) for r in records]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", name=CHANNEL_LABELS[ch], showlegend=False,
                                 line=dict(color=theme["series"][ch], width=2), connectgaps=False,
                                 hovertemplate="%{x|%Y-%m-%d %H:%M}<br>%{y:.2f}<extra>" + CHANNEL_LABELS[ch] + "</extra>"),
                      row=row, col=1)
        marks: dict[str, dict[str, list]] = {}
        last_known: Optional[float] = None
        for r in records:
            v = getattr(r.reading, ch)
            if v is not None:
                last_known = v
            if r.verdict is None or r.verdict.verdict.value == "VALID" or ch not in marked_channels(r, settings):
                continue
            y = v if v is not None else last_known
            if y is None:
                continue
            m = marks.setdefault(r.verdict.verdict.value, {"x": [], "y": [], "text": []})
            m["x"].append(r.reading.timestamp)
            m["y"].append(y)
            note = "value missing, drawn at last known value<br>" if v is None else ""
            m["text"].append(f"{r.verdict.verdict.value} ({r.verdict.confidence:.2f})<br>{note}{_wrap(r.verdict.reason)}")
        for verdict, m in marks.items():
            fig.add_trace(go.Scatter(
                x=m["x"], y=m["y"], mode="markers", name=verdict, legendgroup=verdict,
                showlegend=verdict not in shown, text=m["text"], hovertemplate="%{text}<extra></extra>",
                marker=dict(symbol=VERDICT_SYMBOL[verdict], size=11, color=theme["verdict"][verdict],
                            line=dict(width=1.5, color=theme["text"] if verdict != "FAULT" else theme["verdict"][verdict]))),
                row=row, col=1)
            shown.add(verdict)
        fig.update_yaxes(row=row, col=1, gridcolor=theme["grid"], zeroline=False, tickfont=dict(color=theme["muted"]))
    fig.update_xaxes(gridcolor=theme["grid"], tickfont=dict(color=theme["muted"]))
    for note in fig.layout.annotations:                    # panel titles: left-aligned, above each panel
        note.update(x=0, xanchor="left", font=dict(color=theme["text"], size=14))
    fig.update_layout(height=640, margin=dict(l=10, r=10, t=70, b=10), hovermode="closest",
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(color=theme["text"]), legend=dict(orientation="h", y=1.11, x=0, font=dict(color=theme["text"])))
    return fig


def _wrap(text: str, width: int = 70) -> str:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    return "<br>".join(lines + [cur])


def alert_rows(records: list[StoredRecord]) -> list[dict]:
    return [{"time": r.reading.timestamp.isoformat(sep=" "), "station": r.reading.station_id,
             "verdict": r.verdict.verdict.value, "confidence": r.verdict.confidence, "reason": r.verdict.reason}
            for r in records if r.verdict is not None]


def check_rows(rec: StoredRecord) -> list[dict]:
    return [{"check": c.check, "flagged": c.flagged, "severity": c.severity, "reason": c.reason}
            for c in (rec.verdict.checks if rec.verdict else [])]


def series_rows(records: list[StoredRecord]) -> list[dict]:
    return [{"time": r.reading.timestamp.isoformat(sep=" "), **{c: getattr(r.reading, c) for c in CHANNELS},
             "verdict": r.verdict.verdict.value if r.verdict else None} for r in reversed(records)]


def theme_mode() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:                                  # older Streamlit or no theme info
        return "light"


def render_live(api_url: str, settings: dict, station: str) -> None:
    cfg = settings["dashboard"]
    raw = fetch(api_url, "/latest", {"station_id": station, "limit": cfg["points"]})
    records = parse_records(raw)
    if not records:
        st.info("No readings for this station yet.")
        return
    newest = records[-1]
    report = fetch(api_url, "/health", {"station_id": station})["stations"][station]

    c1, c2, c3 = st.columns([2, 1, 1])
    v = newest.verdict
    c1.metric("Latest verdict", v.verdict.value if v else "pending")
    if v:
        c1.caption(f"Confidence {v.confidence:.2f}. {v.reason}")
        if v.imputation:
            c1.caption("Estimated for the missing or faulty value (raw value kept): " + "; ".join(
                f"{db_label(ch)} {e.value:.2f} (band {e.lower:.2f} to {e.upper:.2f})" for ch, e in v.imputation.channels.items()))
    c2.metric("Health score", "n/a" if report["score"] is None else f"{report['score']:.0f} / 100")
    c3.metric("Projected service date", report["service_date"] or "none")
    c3.caption("No drift trend needing service." if not report["service_date"] and report["score"] is not None else "")
    if report["score"] is None:
        st.caption(report["note"])
    if report["ticket"]:
        t = report["ticket"]
        (st.error if t["priority"] == "high" else st.warning)(
            f"Ticket ({t['priority']} priority): {t['reason']}", icon="🔧")

    if report["channels"]:
        cols = st.columns(3)
        for col, ch in zip(cols, CHANNELS):
            h = report["channels"][ch]
            col.metric(CHANNEL_LABELS[ch], f"{h['score']:.0f} / 100")
            col.caption(h["note"])

    st.plotly_chart(build_figure(records, settings, theme_mode()), width="stretch", theme=None)

    alerts = parse_records(fetch(api_url, "/alerts", {"station_id": station, "limit": cfg["alerts_shown"]}))
    st.subheader("Alerts")
    st.caption("Everything that is not VALID, newest first. WEATHER is listed on purpose: it is escalated, never hidden.")
    rows = alert_rows(list(reversed(alerts)))
    st.dataframe(rows, width="stretch", hide_index=True) if rows else st.write("No alerts.")

    with st.expander("Checks behind the latest verdict"):
        st.dataframe(check_rows(newest), width="stretch", hide_index=True)
    with st.expander("Data table (same readings as the charts)"):
        st.dataframe(series_rows(records), width="stretch", hide_index=True)


def main() -> None:
    settings = load_settings()
    cfg = settings["dashboard"]
    api_url = os.environ.get("ATMOS_API_URL") or cfg["api_url"]
    st.set_page_config(page_title="AtmosGuard", layout="wide")
    st.title("AtmosGuard")
    st.caption("Single-station anomaly and sensor-health monitor. Inputs: temperature, pressure, humidity only.")
    try:
        status = fetch(api_url, "/status")
    except httpx.HTTPError as e:
        st.error(f"Cannot reach the API at {api_url}: {e}")
        st.stop()
    stations = status["stations_seen"]
    if not stations:
        st.info("The API has no readings yet. Start a replay, for example: "
                "`python replay.py data/clean/demo.csv --station S1 --speed 60`")
        st.stop()
    station = st.sidebar.selectbox("Station", stations)
    rp = status.get("replay", {})
    if rp.get("state") not in (None, "idle"):
        st.sidebar.write(f"Replay: {rp['state']} ({rp['sent']} of {rp['total']})")
    st.sidebar.caption(f"Refreshes every {cfg['refresh_seconds']} s. Models loaded: "
                       f"{status['models_loaded']['normality'] or 'none'}")

    @st.fragment(run_every=cfg["refresh_seconds"])
    def live():
        try:
            render_live(api_url, settings, station)
        except httpx.HTTPError as e:
            st.error(f"Lost the API at {api_url}: {e}")
    live()


if __name__ == "__main__":
    main()
