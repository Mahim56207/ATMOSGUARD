"""evaluate_csv.py: reading a user's CSV. (The evaluation itself is tested through evaluate_real.)"""
import pandas as pd
import pytest

import evaluate_csv


def _write(tmp_path, rows, columns):
    p = tmp_path / "aws.csv"
    pd.DataFrame(rows, columns=columns).to_csv(p, index=False)
    return p


def test_prepare_sorts_dedups_and_names_the_station(tmp_path):
    cols = ["timestamp", "temperature_c", "pressure_hpa", "humidity_pct"]
    p = _write(tmp_path, [
        ["2021-01-01 02:00", 21.0, 1010.0, 60.0],
        ["2021-01-01 00:00", 20.0, 1011.0, 62.0],
        ["2021-01-01 00:00", 99.0, 1011.0, 62.0],       # duplicate timestamp: first one wins
        ["2021-01-01 01:00", None, 1010.5, 61.0],       # an empty cell stays missing
    ], cols)
    df = evaluate_csv.prepare(p, "MYAWS")
    assert list(df["timestamp"]) == sorted(df["timestamp"])
    assert len(df) == 3
    assert set(df["station_id"]) == {"MYAWS"}
    assert df["temperature_c"].isna().sum() == 1
    assert (df["noaa_flag"] == 0).all()                 # no flag column given: nothing flagged


def test_prepare_keeps_a_supplied_flag_column(tmp_path):
    cols = ["timestamp", "temperature_c", "pressure_hpa", "humidity_pct", "noaa_flag"]
    p = _write(tmp_path, [["2021-01-01 00:00", 20.0, 1011.0, 62.0, 3]], cols)
    assert int(evaluate_csv.prepare(p, "X")["noaa_flag"].iloc[0]) == 3


def test_prepare_names_missing_columns(tmp_path):
    p = _write(tmp_path, [["2021-01-01 00:00", 20.0]], ["timestamp", "temperature_c"])
    with pytest.raises(SystemExit) as e:
        evaluate_csv.prepare(p, "X")
    assert "pressure_hpa" in str(e.value) and "humidity_pct" in str(e.value)
