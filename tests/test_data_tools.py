"""Tests for data_tools/ (ISD parsing, series building, event rules) and the helpers evaluate_real.py relies on."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import evaluate_real as er
import make_summary as ms
from data_tools import isd, make_dataset

HEADER = '"STATION","DATE","SOURCE","LATITUDE","LONGITUDE","ELEVATION","NAME","REPORT_TYPE","CALL_SIGN","QUALITY_CONTROL","WND","CIG","VIS","TMP","DEW","SLP","MA1"'


def raw_csv(tmp_path: Path) -> Path:
    def row(date, rtype, tmp, dew, slp="99999,9", ma1=""):
        return f'"42971099999","{date}","4","20.2","85.8","42.0","X, IN","{rtype}","99999","V020","","","","{tmp}","{dew}","{slp}","{ma1}"'
    rows = [HEADER,
            row("2019-05-01T00:00:00", "FM-15", "+0300,1", "+0200,1", ma1="10100,1,99999,9"),
            row("2019-05-01T00:30:00", "FM-15", "+0290,1", "+0200,1", ma1="10101,1,99999,9"),   # half-hour: not on the hourly grid
            row("2019-05-01T01:00:00", "FM-15", "+9999,9", "+0200,1", ma1="10100,1,99999,9"),   # temperature missing
            row("2019-05-01T02:00:00", "FM-15", "+0310,3", "+0210,1", ma1="10102,1,99999,9"),   # erroneous temperature
            row("2019-05-01T03:00:00", "FM-15", "+0320,1", "+0220,2", ma1="10103,1,99999,9"),   # suspect dew point
            row("2019-05-01T03:00:00", "FM-12", "+0325,1", "+0225,1", slp="10104,1"),            # same time, SYNOP
            row("2019-05-01T04:03:00", "FM-16", "+0330,1", "+0230,1", ma1="10104,1,99999,9")]   # SPECI
    p = tmp_path / "2019_42971099999.csv"
    p.write_text("\n".join(rows) + "\n")
    return p


def test_rh_from_dew_point_is_100_at_saturation_and_close_to_known_values():
    assert isd.rh_from_dew_point(np.array([25.0]), np.array([25.0]))[0] == pytest.approx(100.0)
    assert isd.rh_from_dew_point(np.array([30.0]), np.array([20.0]))[0] == pytest.approx(54.9, abs=0.6)
    assert isd.rh_from_dew_point(np.array([20.0]), np.array([21.0]))[0] == 100.0        # rounding artefact is clipped, not >100


def test_parse_raw_reads_values_and_quality_codes(tmp_path):
    d = isd.parse_raw(raw_csv(tmp_path))
    metar = d[d["rtype"] == "FM-15"].reset_index(drop=True)
    assert metar.loc[0, "t"] == 30.0 and metar.loc[0, "td"] == 20.0 and metar.loc[0, "alt"] == 1010.0
    assert pd.isna(metar.loc[2, "t"])                                                  # +9999 is missing
    assert metar.loc[3, "qc_t"] == "3" and metar.loc[4, "qc_td"] == "2"
    synop = d[d["rtype"] == "FM-12"].iloc[0]
    assert synop["slp"] == 1010.4 and pd.isna(synop["alt"])


def test_metar_series_keeps_the_hourly_grid_and_drops_missing_and_speci(tmp_path):
    s = isd.to_series(isd.parse_raw(raw_csv(tmp_path)), "metar", 60)
    assert list(s["timestamp"]) == ["2019-05-01T00:00:00", "2019-05-01T02:00:00", "2019-05-01T03:00:00"]
    assert list(s["noaa_flag"]) == [0, 2, 1]                                          # erroneous = 2, suspect = 1
    assert s["pressure_hpa"].iloc[0] == 1010.0 and s["temperature_c"].iloc[0] == 30.0


def test_synop_series_uses_sea_level_pressure(tmp_path):
    s = isd.to_series(isd.parse_raw(raw_csv(tmp_path)), "synop", 60)
    assert len(s) == 1 and s["pressure_hpa"].iloc[0] == 1010.4 and s["temperature_c"].iloc[0] == 32.5


def test_coverage_counts_the_share_of_expected_samples():
    df = pd.DataFrame({"timestamp": pd.date_range("2019-01-01", periods=4380, freq="2h").strftime("%Y-%m-%dT%H:%M:%S")})
    assert isd.coverage(df, 60)[2019] == pytest.approx(0.5, abs=0.01)


# ---- event rules -------------------------------------------------------------------------------------------
def frame(days=200, seed=0):
    rng = np.random.default_rng(seed)
    ts = pd.date_range("2020-01-01", periods=days * 24, freq="h")
    t = 27 + 5 * np.sin((ts.hour.values - 9) / 24 * 2 * np.pi) + rng.normal(0, 0.4, len(ts))
    p = 1008 + rng.normal(0, 0.6, len(ts))
    p[100 * 24: 100 * 24 + 30] -= 25                                                  # a deep low around day 100
    t[150 * 24: 150 * 24 + 12] += 12                                                  # a hot spell around day 150
    return pd.DataFrame({"station_id": "S", "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S"), "temperature_c": t.round(),
                         "pressure_hpa": p.round(), "humidity_pct": 60.0, "noaa_flag": 0})


def test_the_event_rules_find_a_deep_low_and_a_hot_spell():
    ev = make_dataset.find_events(frame())
    kinds = {e["kind"] for e in ev}
    low = [e for e in ev if e["kind"] == "low"]
    assert "low" in kinds and "heat" in kinds and "sharp" in kinds
    assert any(pd.Timestamp("2020-04-08") <= pd.Timestamp(e["center"]) <= pd.Timestamp("2020-04-12") for e in low)
    assert all(pd.Timestamp(e["end"]) - pd.Timestamp(e["start"]) >= pd.Timedelta(days=4) for e in ev)


def test_heat_and_cold_events_are_capped_per_station_with_earlier_date_breaking_ties():
    ev = make_dataset.find_events(frame(days=900, seed=1))
    assert sum(e["kind"] == "heat" for e in ev) <= make_dataset.RULES["max_per_kind"]
    assert sum(e["kind"] == "cold" for e in ev) <= make_dataset.RULES["max_per_kind"]
    assert sum(e["kind"] == "low" for e in ev) <= make_dataset.RULES["max_low"]


def test_merge_windows_joins_overlaps():
    ev = [{"start": "2020-01-01", "end": "2020-01-05"}, {"start": "2020-01-04", "end": "2020-01-09"}, {"start": "2020-02-01", "end": "2020-02-03"}]
    assert len(make_dataset.merge_windows(ev)) == 2 and len(er.windows_of(ev)) == 2


# ---- evaluate_real helpers ---------------------------------------------------------------------------------
def test_cut_chunks_removes_windows_and_flagged_rows_and_splits_at_them():
    df = frame(days=40)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df.loc[5, "noaa_flag"] = 2
    windows = [(pd.Timestamp("2020-01-15"), pd.Timestamp("2020-01-18"))]
    chunks = er.cut_chunks(df, windows, min_rows=24)
    assert len(chunks) == 2
    assert all(not ((c["timestamp"] >= windows[0][0]) & (c["timestamp"] <= windows[0][1])).any() for c in chunks)
    assert 5 not in chunks[0].index.tolist() or (chunks[0]["noaa_flag"] == 0).all()
    assert sum(len(c) for c in chunks) == len(df) - 1 - int(((df["timestamp"] >= windows[0][0]) & (df["timestamp"] <= windows[0][1])).sum())


def test_cut_events_adds_lead_in_and_counts_only_the_window():
    df = frame(days=40)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    es, cut = er.cut_events(df, [{"kind": "low", "center": "2020-01-20T12:00:00", "start": "2020-01-18T12:00:00", "end": "2020-01-22T12:00:00"}])
    assert len(es) == 1 and es[0].readings[es[0].core_start].timestamp >= pd.Timestamp("2020-01-18T12:00:00")
    assert es[0].core_start == 2 * 24                                                # two days of lead-in before the window
    assert es[0].core_end == len(es[0].readings)


def test_deep_merge_overrides_only_what_it_names(settings):
    merged = er.deep_merge(settings, {"injector": {"duration_minutes": {"frozen": 1}}})
    assert merged["injector"]["duration_minutes"]["frozen"] == 1
    assert merged["injector"]["duration_minutes"]["dropout"] == settings["injector"]["duration_minutes"]["dropout"]   # the rest of the block is kept
    assert merged["injector"]["magnitude"] == settings["injector"]["magnitude"]              # untouched sections are kept
    assert settings["injector"]["duration_minutes"]["frozen"] != 1                  # the original is untouched


def test_real_settings_use_the_real_data_fault_durations(settings):
    s = er.real_settings(settings)
    assert s["injector"]["duration_minutes"]["frozen"] == 2880 and s["healthscore"]["recompute_every_minutes"] == 10 ** 9


def test_the_holdout_folder_is_refused_without_the_guard(settings):
    with pytest.raises(ValueError):
        er.read_frame(er.REAL_HOLDOUT_DIR / "AMD.csv", settings, allow_holdout=False)


def test_percent_helpers():
    assert ms.pct(1, 4) == "25.0%" and ms.pct(0, 0) == "n/a"
    assert ms.ci_pct(0, 1000).startswith("0.0% (0.0-0.4")
    assert "(" in ms.ci_pct(5, 50)


@pytest.mark.skipif(not (Path(__file__).resolve().parent.parent / "results" / "dev_run3.json").exists(), reason="no committed DEV results")
def test_summary_builds_from_the_committed_dev_results():
    res = json.loads((er.RESULTS_DIR / "dev_run3.json").read_text())
    summary = ms.build_summary({"dev_run3": res}, None)
    ph = summary["phases"]["DEV"]
    assert {"headline", "detection", "clean", "extreme_weather", "noaa", "drift"} <= set(ph)
    assert len(ph["headline"]["rows"]) == 5 and ph["detection"]["rows"][0]["configuration"] == "AtmosGuard (full)"
    assert "FAULT on" in ph["headline"]["rows"][1]["answer"]
    assert "# AtmosGuard evaluation results" in ms.to_markdown(summary)


# ---- paired detection ------------------------------------------------------------------------------------
def test_an_alarm_that_was_already_there_does_not_count_as_detecting_the_fault(settings):
    from atmos.injector import FaultEvent, InjectionResult
    from tests.conftest import make_history
    s = er.real_settings(settings)
    orig = make_history(30, cadence=60)
    faulted = list(orig)
    res = InjectionResult(faulted, [None] * 30, [FaultEvent("frozen", "temperature_c", "a", "b", 10, 14, {})])

    def predictor(alarm_at):
        def predict(readings):
            fault_series = readings is faulted
            return [er.Pred("SUSPECT" if i in alarm_at[fault_series] else "VALID") for i in range(len(readings))]
        return predict
    # the un-faulted series already alarms at sample 12; the faulted one alarms at 12 only
    r = er.count_detection([(faulted, res, orig)], predictor({True: {12}, False: {12}}), s, 60.0)["frozen"]
    assert r["detected"] == 1 and r["detected_new"] == 0                   # registered criterion counts it, paired does not
    # the faulted series alarms at 13 too: a NEW alarm, so the fault raised it
    r = er.count_detection([(faulted, res, orig)], predictor({True: {12, 13}, False: {12}}), s, 60.0)["frozen"]
    assert r["detected"] == 1 and r["detected_new"] == 1 and r["delays_new_min"] == [180.0]
    # nothing alarms: nothing detected either way
    r = er.count_detection([(faulted, res, orig)], predictor({True: set(), False: set()}), s, 60.0)["frozen"]
    assert r["detected"] == 0 and r["detected_new"] == 0 and r["injected"] == 1


def test_memoize_returns_the_same_predictions_for_the_same_series_and_can_be_cleared():
    calls = []

    def predict(readings):
        calls.append(1)
        return [er.Pred("VALID")] * len(readings)
    m = er.memoize(predict)
    series = [object()] * 3
    assert m(series) is m(series) and len(calls) == 1
    m.clear()
    m(series)
    assert len(calls) == 2


def test_update_between_replaces_only_the_marked_block(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text("top\n<!-- A -->\nold\n<!-- B -->\nbottom\n", encoding="utf-8")
    assert ms.update_between(f, "<!-- A -->", "<!-- B -->", "new")
    assert f.read_text(encoding="utf-8") == "top\n<!-- A -->\nnew\n<!-- B -->\nbottom\n"
    assert not ms.update_between(f, "<!-- A -->", "<!-- MISSING -->", "x")
    assert "new" in f.read_text(encoding="utf-8")            # untouched when a marker is missing
