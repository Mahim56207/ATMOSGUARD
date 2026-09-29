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
    try:
        report = fetch(api_url, "/health", {"station_id": station})["stations"][station]
    except httpx.HTTPStatusError as e:
        if e.response.status_code != 404:
            raise
        report = {"score": None, "service_date": None, "ticket": None, "channels": {},
                  "note": "No health report yet: the checks have not processed this station since the API started."}

    c1, c2, c3 = st.columns([2, 1, 1])
    v = newest.verdict
    c1.metric("Latest verdict", v.verdict.value if v else "pending")
    if v:
        c1.caption(f"Confidence {v.confidence:.2f}. {v.reason}")
        for note in v.notices:
            c1.caption(f"Notice: {note}")
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
    with st.expander("Why the statistical layers found it unusual (exact Mahalanobis contributions, SHAP for the Isolation Forest)"):
        try:
            ex = fetch(api_url, "/explain", {"station_id": station, "record_id": newest.id})
        except httpx.HTTPError:
            ex = None
        if not ex:
            st.caption("No explanation available from the API.")
        else:
            for key, title in (("mahalanobis", "Mahalanobis distance"), ("isolation_forest", "Isolation Forest")):
                part = ex.get(key, {})
                st.markdown(f"**{title}**")
                rows = part.get("contributions") or part.get("shap")
                if not part.get("available") or not rows:
                    st.caption(part.get("note", "Not available."))
                    continue
                head = (f"distance^2 {part['distance2']} (limit {part['threshold']})" if key == "mahalanobis"
                        else f"score {part['score']} (limit {part['threshold']})")
                st.caption(f"{head}. {part.get('note', '')}")
                st.dataframe(rows, width="stretch", hide_index=True)
    with st.expander("Data table (same readings as the charts)"):
        st.dataframe(series_rows(records), width="stretch", hide_index=True)


def _headers() -> dict:
    key = os.environ.get("ATMOS_API_KEY")
    return {"X-API-Key": key} if key else {}


def post(api_url: str, path: str, body: Optional[dict] = None):
    r = httpx.post(api_url.rstrip("/") + path, json=body, timeout=15, headers=_headers())
    r.raise_for_status()
    return r.json()


def delete(api_url: str, path: str, params: Optional[dict] = None):
    r = httpx.delete(api_url.rstrip("/") + path, params=params, timeout=15, headers=_headers())
    r.raise_for_status()
    return r.json()


FAULT_TYPES = ("frozen", "spike", "step", "drift", "noise", "dropout")


def upload_body(name: str, data: bytes, station: str, speed: float, limit: int, learn: bool = True) -> dict:
    """The JSON the API's /replay/upload expects, from an uploaded file."""
    body = {"filename": name, "text": data.decode("utf-8-sig"), "speed": float(speed), "learn_fraction": 0.5 if learn else 0.0}
    if station:
        body["station_id"] = station
    if limit:
        body["limit"] = int(limit)
    return body


VERDICT_RANK = {"FAULT": 0, "SUSPECT": 1, "WEATHER": 2, "VALID": 3, None: 4}


def fleet_rows(fleet: dict) -> list[dict]:
    """The network table, most urgent first: FAULT before SUSPECT before WEATHER before VALID, then the lowest health score.
    Each station is judged on its own record; this only lists them side by side."""
    stations = fleet.get("stations", [])
    ordered = sorted(stations, key=lambda s: (VERDICT_RANK.get(s.get("verdict"), 4), s.get("health_score") if s.get("health_score") is not None else 101.0))
    rows = []
    for s in ordered:
        tk = s.get("ticket")
        cs = s.get("channel_scores") or {}
        rows.append({"station": s["station_id"], "verdict": s.get("verdict") or "no reading yet",
                     "health (0-100)": s.get("health_score"),
                     "T": cs.get("temperature_c"), "P": cs.get("pressure_hpa"), "RH": cs.get("humidity_pct"),
                     "ticket": (tk["priority"] + ": " + ", ".join(c.split("_")[0] for c in tk["channels"])) if tk else "none",
                     "service by": s.get("service_date") or "none", "alerts (last 200)": s.get("recent_alerts", 0),
                     "newest reading": (s.get("last_time") or "")[:16].replace("T", " "), "why": s.get("reason") or ""})
    return rows


def render_network(api_url: str) -> None:
    st.subheader("The network, station by station")
    st.caption("One line per station, most urgent first. Every station is judged on its own record; nothing here compares one "
               "station with another. Health is 0-100 (T, P and RH are the channel scores).")
    try:
        fleet = fetch(api_url, "/fleet")
    except httpx.HTTPError as e:
        st.info(f"The API has no network view yet ({e}).")
        return
    rows = fleet_rows(fleet)
    if not rows:
        st.info("No stations have sent readings yet.")
        return
    attention = [r for r in rows if r["verdict"] in ("FAULT", "SUSPECT") or r["ticket"] != "none"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Stations", len(rows))
    c2.metric("Need attention", len(attention))
    scores = [r["health (0-100)"] for r in rows if r["health (0-100)"] is not None]
    c3.metric("Lowest health score", f"{min(scores):.0f}" if scores else "n/a")
    st.dataframe(rows, width="stretch", hide_index=True, column_config={
        "health (0-100)": st.column_config.NumberColumn("health (0-100)", format="%.0f"),
        "T": st.column_config.NumberColumn("T", format="%.0f"), "P": st.column_config.NumberColumn("P", format="%.0f"),
        "RH": st.column_config.NumberColumn("RH", format="%.0f")})


def render_controls(api_url: str, station: str, status: dict) -> None:
    """Break the sensor on demand, and start or stop a replay. Everything here calls the API."""
    st.subheader("Break the sensor")
    st.caption("Arms a fault on this station's NEXT readings. Whatever streams in (a replay, the fake node, a real "
               "ESP32) is altered the way a failing sensor would alter it. Watch the verdict, the reason and the "
               "health score react on the Live monitor tab.")
    c1, c2, c3, c4 = st.columns(4)
    fault = c1.selectbox("Fault", FAULT_TYPES, key="fault_type")
    channel = c2.selectbox("Channel", CHANNELS, format_func=lambda c: CHANNEL_LABELS[c], key="fault_channel")
    samples = c3.number_input("Lasts (readings)", min_value=1, max_value=100000, value={"spike": 1, "drift": 60}.get(fault, 30),
                              key="fault_samples")
    if c4.button("Arm fault", type="primary", key="arm"):
        try:
            armed = post(api_url, "/inject", {"station_id": station, "fault_type": fault, "channel": channel,
                                              "samples": int(samples)})["armed"]
            st.success(f"Armed: {armed['fault_type']} on {armed['channel']} for {armed['samples']} readings.")
        except httpx.HTTPError as e:
            st.error(f"Could not arm the fault: {e}")
    active = [i for i in status.get("injections", []) if i.get("active")]
    if active:
        st.warning("Armed now: " + "; ".join(f"{i['fault_type']} on {i['channel']} ({i['applied']}/{i['samples']})" for i in active))
        if st.button("Clear all armed faults", key="clear"):
            delete(api_url, "/inject")
            st.rerun()

    st.subheader("Replay recorded data")
    st.caption("Plays a CSV from the data folder through the same pipeline. Real cyclone windows are in data/real/dev.")
    try:
        files = httpx.get(api_url.rstrip("/") + "/datasets", timeout=15).json().get("datasets", [])
    except (httpx.HTTPError, ValueError):
        files = []
    r1, r2, r3 = st.columns([3, 1, 1])
    path = r1.selectbox("File", files or ["(no CSV files under data/)"], key="replay_file")
    speed = r2.number_input("Speed (0 = fastest)", min_value=0.0, value=0.0, key="replay_speed")
    limit = r3.number_input("Readings (0 = all)", min_value=0, value=500, key="replay_limit")
    station_id = st.text_input("Station id (only if the CSV has no station_id column)", value="", key="replay_station")
    b1, b2 = st.columns(2)
    if b1.button("Start replay", key="replay_start") and files:
        body = {"csv_path": path, "speed": float(speed)}
        if station_id:
            body["station_id"] = station_id
        if limit:
            body["limit"] = int(limit)
        try:
            post(api_url, "/replay", body)
            st.success("Replay started. Switch to the Live monitor tab.")
        except httpx.HTTPStatusError as e:
            st.error(e.response.json().get("detail", str(e)))
    if b2.button("Stop replay", key="replay_stop"):
        delete(api_url, "/replay")

    st.subheader("Bring your own CSV")
    st.caption("A CSV with timestamp (UTC), temperature_c, pressure_hpa, humidity_pct (station_id optional). It is judged through the same "
               "pipeline, live. The server keeps a copy under data/uploads/.")
    uploaded = st.file_uploader("CSV file", type="csv", key="upload_file")
    v1, v2, v3 = st.columns([2, 1, 1])
    up_station = v1.text_input("Station id (only if the CSV has no station_id column)", value="", key="upload_station")
    up_speed = v2.number_input("Speed (0 = fastest)", min_value=0.0, value=0.0, key="upload_speed")
    up_limit = v3.number_input("Readings (0 = all)", min_value=0, value=0, key="upload_limit")
    up_learn = st.checkbox("A station the server has no models for learns from the first half of the file, then the second half is judged", value=True, key="upload_learn")
    if st.button("Judge this file", key="upload_go", disabled=uploaded is None) and uploaded is not None:
        try:
            out = post(api_url, "/replay/upload", upload_body(uploaded.name, uploaded.getvalue(), up_station, up_speed, up_limit, up_learn))
            st.success(f"Judging {out['total']} readings from {uploaded.name}. Switch to the Live monitor tab and pick the station.")
            for note in out.get("notes", []):
                st.info(note)
        except httpx.HTTPStatusError as e:
            st.error(e.response.json().get("detail", str(e)))
        except UnicodeDecodeError:
            st.error("The file is not text (UTF-8). Save it as CSV and try again.")


def render_evaluation(api_url: str) -> None:
    """The committed evaluation summary. Three separate numbers, never merged, always labelled."""
    try:
        r = httpx.get(api_url.rstrip("/") + "/metrics", timeout=15)
        r.raise_for_status()
        summary = r.json()
    except Exception:                                   # no summary committed yet, or the API is older
        st.info("No evaluation summary available from the API yet. Run `python evaluate_real.py --dev` and "
                "`python make_summary.py`, then reload.")
        return
    st.caption(summary.get("note", ""))
    for name, phase in summary.get("phases", {}).items():
        st.subheader(phase.get("title", name))
        st.caption(phase.get("subtitle", ""))
        for key in ("headline", "detection", "detection_ci", "detection_named", "detection_registered", "tradeoff", "remedies", "clean", "extreme_weather", "noaa", "drift", "by_station", "speed"):
            table = phase.get(key)
            if not table:
                continue
            st.markdown(f"**{table['title']}**")
            if table.get("caption"):
                st.caption(table["caption"])
            if key == "headline":
                st.table(table["rows"])                 # long sentences: a static table wraps them, a dataframe cuts them off
            else:
                st.dataframe(table["rows"], width="stretch", hide_index=True)


def render_method() -> None:
    st.markdown("""
**Four verdicts.** `VALID`, `WEATHER`, `SUSPECT`, `FAULT`. A cyclone is escalated as `WEATHER`, never deleted as noise.

**Layers (each can be switched off in `config/settings.yaml`):** L0 physics (ranges, dew point, wet-bulb; also runs on the
ESP32) → L1 health (frozen, step, spike, noise, gap, CUSUM; limits learned per station) → L2 normality (station x month x
hour) → L3 Isolation Forest → timing (clock shift, co-jump) → fusion → health score, drift monitor, ticket, imputation.

**Fusion rule in words.** Impossible, frozen or missing: FAULT. One channel jumps while the other two stay calm: FAULT.
Several channels move together, smoothly, in a known weather pattern: WEATHER. Unusual but ambiguous: SUSPECT.

**Confidence** is agreement between checks, not a calibrated probability. **Imputed values** sit beside the raw value and
carry an uncertainty band; the raw value is never overwritten.
""")


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

    tab_live, tab_net, tab_ctrl, tab_eval, tab_method = st.tabs(["Live monitor", "Network", "Control panel", "Evaluation", "How it decides"])
    with tab_live:
        @st.fragment(run_every=cfg["refresh_seconds"])
        def live():
            try:
                render_live(api_url, settings, station)
            except httpx.HTTPError as e:
                st.error(f"Lost the API at {api_url}: {e}")
        live()
    with tab_net:
        render_network(api_url)
    with tab_ctrl:
        render_controls(api_url, station, status)
    with tab_eval:
        render_evaluation(api_url)
    with tab_method:
        render_method()


if __name__ == "__main__":
    main()
