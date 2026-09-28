"""Tests for dashboard.py: chart building, table rows, and a full Streamlit run against a fake API."""
import copy
from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

import dashboard as db
from atmos.config import load_settings
from atmos.fusion import Pipeline
from atmos.schema import CHANNELS, StoredRecord
from tests.conftest import synthetic_readings

SCRIPT = str(Path(__file__).resolve().parent.parent / "dashboard.py")


@pytest.fixture(scope="module")
def cfg():
    return copy.deepcopy(load_settings())


@pytest.fixture(scope="module")
def records(cfg):
    """A day of synthetic readings with a frozen temperature and a pressure dropout, run through the pipeline."""
    from atmos.injector import FaultSpec, inject
    clean = synthetic_readings(days=1, cadence=15, seed=4, noise_t=0.1)
    faulted = inject(clean, cfg, [FaultSpec("frozen", "temperature_c", 30), FaultSpec("dropout", "pressure_hpa", 60)])
    pipe = Pipeline(cfg, {"S1": {"cadence_minutes": 15}})
    return [StoredRecord(id=i + 1, reading=r, verdict=pipe.process(r)) for i, r in enumerate(faulted.readings)]


def _traces(fig, name):
    return [t for t in fig.data if t.name == name]


def test_figure_has_one_panel_per_channel_with_titles(records, cfg):
    fig = db.build_figure(records, cfg)
    assert [a.text for a in fig.layout.annotations] == [db.CHANNEL_LABELS[c] for c in CHANNELS]
    lines = [t for t in fig.data if t.mode == "lines"]
    assert len(lines) == 3 and all(len(t.x) == len(records) for t in lines)


def test_fault_is_marked_only_on_the_channel_it_points_at(records, cfg):
    fig = db.build_figure(records, cfg)
    fault_traces = _traces(fig, "FAULT")
    assert len(fault_traces) == 2                               # temperature panel and pressure panel only
    assert {t.yaxis for t in fault_traces} == {"y", "y2"}       # not the humidity panel (y3)


def test_verdicts_use_different_shapes_and_appear_once_in_the_legend(records, cfg):
    fig = db.build_figure(records, cfg)
    assert _traces(fig, "FAULT")[0].marker.symbol == "x"
    assert sum(1 for t in _traces(fig, "FAULT") if t.showlegend) == 1
    assert len({db.VERDICT_SYMBOL[v] for v in db.VERDICT_SYMBOL}) == 3


def test_dropout_leaves_a_gap_and_a_marker_at_the_last_known_value(records, cfg):
    fig = db.build_figure(records, cfg)
    pressure_line = [t for t in fig.data if t.mode == "lines"][1]
    assert None in list(pressure_line.y) or any(y != y for y in pressure_line.y)      # gap in the line
    marker = [t for t in _traces(fig, "FAULT") if t.yaxis == "y2"][0]
    assert any("value missing" in txt for txt in marker.text)


def test_both_colour_modes_build(records, cfg):
    for mode in ("light", "dark"):
        fig = db.build_figure(records, cfg, mode)
        assert fig.data[0].line.color == db.THEMES[mode]["series"]["temperature_c"]


def test_no_records_gives_an_empty_but_valid_figure(cfg):
    assert len(db.build_figure([], cfg).data) == 3


def test_table_rows(records):
    alerts = [r for r in records if r.verdict.verdict.value != "VALID"]
    rows = db.alert_rows(alerts)
    assert rows and {"time", "station", "verdict", "confidence", "reason"} <= set(rows[0])
    assert all(r["verdict"] != "VALID" for r in rows)
    assert len(db.series_rows(records)) == len(records)
    assert db.check_rows(records[-1]) and "reason" in db.check_rows(records[-1])[0]


def test_parse_records_sorts_oldest_first(records):
    raw = [r.model_dump(mode="json") for r in reversed(records)]
    parsed = db.parse_records(raw)
    assert [r.id for r in parsed] == [r.id for r in records]


# ---- run the real Streamlit script against a fake API ------------------------------------------------
def _fake_get(records, report, status):
    def get(url, params=None, timeout=None):
        path = url.split("8000")[-1]
        if path == "/status":
            body = status
        elif path == "/latest":
            body = [r.model_dump(mode="json") for r in list(reversed(records))[: params["limit"]]]
        elif path == "/alerts":
            body = [r.model_dump(mode="json") for r in reversed(records) if r.verdict.verdict.value != "VALID"]
        elif path == "/health":
            body = {"stations": {"S1": report}}
        else:
            raise AssertionError(path)
        return httpx.Response(200, json=body, request=httpx.Request("GET", url))
    return get


def _report(cfg, records):
    pipe = Pipeline(cfg, {"S1": {"cadence_minutes": 15}})
    for r in records:
        pipe.process(r.reading)
    return pipe.health_report("S1").model_dump(mode="json")


def test_streamlit_app_renders_status_health_ticket_and_alerts(records, cfg, monkeypatch):
    status = {"status": "ok", "stations_seen": ["S1"], "models_loaded": {"normality": [], "isolation_forest": []},
              "replay": {"state": "idle", "sent": 0, "total": 0}}
    monkeypatch.setattr(httpx, "get", _fake_get(records, _report(cfg, records), status))
    at = AppTest.from_file(SCRIPT, default_timeout=30).run()
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert "Latest verdict" in labels and "Health score" in labels and "Projected service date" in labels
    assert {db.CHANNEL_LABELS[c] for c in CHANNELS} <= set(labels)
    assert len(at.dataframe) >= 3                               # alerts, checks, data table


def test_streamlit_app_says_so_when_the_api_is_down(monkeypatch):
    def down(*a, **k):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(httpx, "get", down)
    at = AppTest.from_file(SCRIPT, default_timeout=30).run()
    assert any("Cannot reach the API" in e.value for e in at.error)


def test_streamlit_app_shows_a_hint_when_there_are_no_readings(monkeypatch):
    status = {"status": "ok", "stations_seen": [], "models_loaded": {"normality": [], "isolation_forest": []}}
    monkeypatch.setattr(httpx, "get", _fake_get([], {}, status))
    at = AppTest.from_file(SCRIPT, default_timeout=30).run()
    assert any("replay.py" in i.value for i in at.info)


def test_streamlit_app_shows_the_estimate_for_a_missing_value(cfg, monkeypatch):
    from tests.conftest import make_history, make_reading
    pipe = Pipeline(cfg, {"S1": {"cadence_minutes": 15}})
    rows = [StoredRecord(id=i + 1, reading=r, verdict=pipe.process(r)) for i, r in enumerate(make_history(30, cadence=15))]
    last = make_reading(30 * 15, p=None)
    rows.append(StoredRecord(id=31, reading=last, verdict=pipe.process(last)))
    status = {"status": "ok", "stations_seen": ["S1"], "models_loaded": {"normality": [], "isolation_forest": []},
              "replay": {"state": "idle", "sent": 0, "total": 0}}
    monkeypatch.setattr(httpx, "get", _fake_get(rows, _report(cfg, rows), status))
    at = AppTest.from_file(SCRIPT, default_timeout=30).run()
    assert not at.exception
    text = " ".join(c.value for c in at.caption)
    assert "Estimated for the missing or faulty value" in text and "Pressure (hPa)" in text and "band" in text


def test_streamlit_app_copes_with_a_station_that_has_no_health_report_yet(records, monkeypatch):
    status = {"status": "ok", "stations_seen": ["S1"], "models_loaded": {"normality": [], "isolation_forest": []},
              "replay": {"state": "idle", "sent": 0, "total": 0}}
    good = _fake_get(records, {}, status)

    def get(url, params=None, timeout=None):
        if url.endswith("/health"):
            return httpx.Response(404, json={"detail": "none"}, request=httpx.Request("GET", url))
        return good(url, params, timeout)

    monkeypatch.setattr(httpx, "get", lambda url, params=None, timeout=None: (
        lambda r: (r.raise_for_status(), r)[1])(get(url, params, timeout)))
    at = AppTest.from_file(SCRIPT, default_timeout=30).run()
    assert not at.exception and not at.error
    assert any("No health report yet" in c.value for c in at.caption)
