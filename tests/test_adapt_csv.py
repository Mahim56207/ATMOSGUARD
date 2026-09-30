"""data_tools/adapt_csv.py: a station file in another layout becomes the CSV AtmosGuard reads, with every decision printed."""
import io
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from atmos.config import load_settings
from data_tools import adapt_csv as ac
import replay


def imd_like(n=24 * 60, station="VOBL", start="2023-01-01 00:00"):
    t = pd.date_range(start, periods=n, freq="h")
    rng = np.random.default_rng(0)
    return pd.DataFrame({
        "STATION": station,
        "DATE": t.strftime("%d/%m/%Y"),
        "TIME (IST)": t.strftime("%H:%M"),
        "TEMP (°C)": np.round(25 + 5 * np.sin(np.arange(n) / 3.8) + rng.normal(0, .3, n), 1),
        "RH (%)": np.round(60 + 10 * np.cos(np.arange(n) / 3.8) + rng.normal(0, 1, n), 1),
        "STN PRES (hPa)": np.round(915 + rng.normal(0, .8, n), 1),
        "QC": 0,
    })


def test_an_imd_style_sheet_becomes_utc_with_every_decision_printed():
    raw = imd_like()
    raw.loc[5, "TEMP (°C)"] = -999
    raw.loc[6, "TEMP (°C)"] = -999
    raw.loc[7, "TEMP (°C)"] = -999
    raw.loc[9, "QC"] = 2
    frames, notes = ac.adapt(raw, tz="IST")
    (g,) = frames.values()
    assert list(g.columns) == ["timestamp", "temperature_c", "pressure_hpa", "humidity_pct", "noaa_flag"]
    assert g["timestamp"].iloc[0] == "2022-12-31T18:30:00"                      # 00:00 IST is 18:30 UTC the day before
    assert g["temperature_c"].isna().sum() == 3 and g["noaa_flag"].sum() == 1
    text = "\n".join(notes)
    assert "-999" in text and "+5.5" in text and "day-first" in text or "DAY-first" in text
    assert "station level" in text


def test_without_a_zone_it_says_it_assumed_utc():
    _, notes = ac.adapt(imd_like())
    assert any("taken as UTC" in n and "--tz IST" in n for n in notes)


def test_units_are_converted_from_kelvin_pascal_and_fractions():
    raw = pd.DataFrame({"time": pd.date_range("2024-01-01", periods=300, freq="h").strftime("%Y-%m-%d %H:%M"),
                        "Temp K": 290.0 + np.arange(300) % 7, "Pressure Pa": 91500.0 + np.arange(300) % 5, "RH": 0.55 + (np.arange(300) % 9) / 100})
    (g,), notes = list(ac.adapt(raw)[0].values()), ac.adapt(raw)[1]
    assert 16 < g["temperature_c"].iloc[0] < 25 and 914 < g["pressure_hpa"].iloc[0] < 920 and 54 < g["humidity_pct"].iloc[0] < 70
    text = "\n".join(notes)
    assert "kelvin" in text and "Pa" in text and "fraction" in text


def test_fahrenheit_inches_of_mercury_and_a_decimal_comma():
    n = 300
    raw = pd.DataFrame({"Timestamp": pd.date_range("2024-06-01", periods=n, freq="30min").strftime("%Y-%m-%dT%H:%M:%S"),
                        "Air Temperature (F)": 70.0 + np.arange(n) % 9, "Pressure (inHg)": 29.9 + (np.arange(n) % 4) / 100,
                        "Humidity": [f"{50 + i % 20},5" for i in range(n)]})
    (g,), notes = list(ac.adapt(raw)[0].values()), ac.adapt(raw)[1]
    assert 20 < g["temperature_c"].iloc[0] < 30 and 1010 < g["pressure_hpa"].iloc[0] < 1016
    assert 50 < g["humidity_pct"].iloc[0] < 52


def test_excel_serial_dates_and_month_first_dates():
    n = 100
    serial = pd.DataFrame({"obs_time": 45000 + np.arange(n) / 24.0, "T": 20.0 + np.arange(n) % 5, "P": 1000.0 + np.arange(n) % 3, "RH": 50.0 + np.arange(n) % 10})
    (g,) = ac.adapt(serial)[0].values()
    assert g["timestamp"].iloc[0].startswith("2023-03-15")
    mf = pd.DataFrame({"date": ["12/31/2024", "12/31/2024"], "time": ["00:00", "01:00"], "T": [20.0, 21.0], "P": [1000.0, 1001.0], "RH": [50.0, 51.0]})
    (g,) = ac.adapt(mf)[0].values()
    assert g["timestamp"].iloc[0] == "2024-12-31T00:00:00"


def test_several_stations_are_split_and_each_is_sorted_and_deduplicated():
    a, b = imd_like(200, "AAA"), imd_like(200, "BBB")
    raw = pd.concat([b, a, a.iloc[:5]]).reset_index(drop=True)
    frames, notes = ac.adapt(raw)
    assert set(frames) == {"AAA", "BBB"} and len(frames["AAA"]) == 200
    assert frames["AAA"]["timestamp"].is_monotonic_increasing
    assert any("duplicate" in n for n in notes)


def test_it_stops_and_says_what_to_pass_when_it_cannot_decide():
    with pytest.raises(SystemExit, match="pressure"):
        ac.adapt(imd_like().drop(columns="STN PRES (hPa)"))
    with pytest.raises(SystemExit, match="outside"):
        bad = imd_like()
        bad["TEMP (°C)"] = 400.0 + np.arange(len(bad)) % 7                                  # not kelvin, not anything
        ac.adapt(bad)
    with pytest.raises(SystemExit, match="No time column"):
        ac.adapt(imd_like().drop(columns=["DATE", "TIME (IST)"]))
    with pytest.raises(SystemExit, match="--tz"):
        ac.adapt(imd_like(), tz="moon")


def test_explicit_column_overrides_win():
    raw = imd_like().rename(columns={"STN PRES (hPa)": "weird_p", "TEMP (°C)": "weird_t", "RH (%)": "weird_h"})
    with pytest.raises(SystemExit):
        ac.adapt(raw)
    (g,) = ac.adapt(raw, pressure_column="weird_p", temperature_column="weird_t", humidity_column="weird_h")[0].values()
    assert len(g) == len(raw)


def test_the_output_is_read_by_the_replay_loader_and_the_evaluation_prepare(tmp_path):
    frames, _ = ac.adapt(imd_like(400), tz="IST")
    (g,) = frames.values()
    path = tmp_path / "aws.csv"
    g.to_csv(path, index=False)
    rs = replay.read_readings(path, load_settings(), "VOBL")
    assert len(rs) == 400 and rs[0].timestamp.isoformat() == "2022-12-31T18:30:00"
    import evaluate_csv
    df = evaluate_csv.prepare(path, "VOBL")
    assert len(df) == 400 and set(df.columns) >= {"station_id", "noaa_flag"}


def test_cli_writes_one_file_per_station_and_inspect_writes_nothing(tmp_path, capsys):
    src = tmp_path / "raw.csv"
    pd.concat([imd_like(100, "AAA"), imd_like(100, "BBB")]).to_csv(src, index=False, sep=";")
    assert ac.main([str(src), "--inspect"]) == 0
    assert "nothing written" in capsys.readouterr().out
    out = tmp_path / "out" / "aws.csv"
    assert ac.main([str(src), "--out", str(out), "--tz", "IST"]) == 0
    assert (tmp_path / "out" / "aws_AAA.csv").exists() and (tmp_path / "out" / "aws_BBB.csv").exists()
    assert "evaluate_csv.py" in capsys.readouterr().out


def test_excel_files_are_read_when_openpyxl_is_installed(tmp_path):
    pytest.importorskip("openpyxl")
    path = tmp_path / "raw.xlsx"
    imd_like(120).to_excel(path, index=False)
    frames, _ = ac.adapt(ac.read_table(path), tz="IST")
    assert len(next(iter(frames.values()))) == 120


def test_aggregates_only_drops_every_example_value_and_timestamp():
    import evaluate_csv
    result = {"station": "X", "noaa": {"flagged": 3, "examples": [{"t": "2024-01-01T00:00:00", "T": 31.2, "P": 1001.0, "RH": 40.0}]},
              "warm": {"start": "2024-01-01"}, "configs": {"full": {"clean": {"n": 10, "alarm": 1}}}}
    out = evaluate_csv.aggregates_only(result)
    assert "examples" not in out["noaa"] and "warm" not in out and out["noaa"]["flagged"] == 3 and out["configs"]["full"]["clean"]["alarm"] == 1
    assert "2024-01-01" not in str(out) and "31.2" not in str(out)
