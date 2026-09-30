"""evaluate_crn.py and data_tools/crn.py: labelled sensor faults from three redundant thermometers, and the two-channel 5-minute study."""
import gzip
import io
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import evaluate_crn as ec
from data_tools import crn


def station_frame(n=288 * 10, seed=0):
    rng = np.random.default_rng(seed)
    t = pd.date_range("2020-03-01", periods=n, freq="5min")
    base = 15 + 5 * np.sin(np.arange(n) / 288 * 2 * np.pi)
    df = pd.DataFrame({"timestamp": t, "rh": 60 + 5 * np.cos(np.arange(n) / 288 * 2 * np.pi), "rh_q": 1.0})
    for k in (1, 2, 3):
        df[f"t{k}"] = base + rng.normal(0, 0.05, n)
        df[f"q{k}"] = 1.0
    return df


def test_no_fault_means_no_label():
    eps = ec.label_episodes(station_frame())
    assert all(len(v) == 0 for v in eps.values())


def test_one_thermometer_off_by_three_degrees_is_a_clear_redundancy_episode_on_that_sensor_only():
    df = station_frame()
    df.loc[1000:1040, "t2"] += 3.0                                  # 41 samples = 205 min
    eps = ec.label_episodes(df)
    assert len(eps[1]) == 0 and len(eps[3]) == 0
    (ep,) = eps[2]
    assert (ep.start, ep.end) == (1000, 1040) and ep.kind == "redundancy" and ep.tier == "clear" and ep.max_dev == pytest.approx(3.0, abs=0.3)


def test_a_one_and_a_half_degree_short_offset_is_marginal_and_a_blip_below_fifteen_minutes_is_nothing():
    df = station_frame()
    df.loc[500:504, "t1"] += 1.5                                      # 25 min, 1.5 C: marginal
    df.loc[2000:2001, "t3"] += 5.0                                    # 10 min: too short
    eps = ec.label_episodes(df)
    assert [e.tier for e in eps[1]] == ["marginal"] and eps[3] == []


def test_two_sensors_disagreeing_with_each_other_label_nobody():
    df = station_frame()
    df.loc[300:340, "t1"] += 2.0
    df.loc[300:340, "t2"] -= 2.0                                      # the pair no longer agrees, so the third cannot be blamed on redundancy
    eps = ec.label_episodes(df)
    assert all(e == [] for e in eps.values())


def test_crn_quality_code_3_is_a_clear_episode_even_when_the_other_sensors_cannot_confirm_it():
    df = station_frame()
    df.loc[700:720, "q1"] = 3.0
    (ep,) = ec.label_episodes(df)[1]
    assert ep.kind == "qc" and ep.tier == "clear" and (ep.start, ep.end) == (700, 720)
    df.loc[700:703, "q3"] = 3.0                                      # 4 samples: shorter than the 30 minutes a QC episode needs
    assert ec.label_episodes(df)[3] == []


def test_a_qc_code_and_a_redundancy_episode_that_overlap_become_one_episode_of_kind_both():
    df = station_frame()
    df.loc[900:930, "t1"] += 4.0
    df.loc[915:940, "q1"] = 3.0
    (ep,) = ec.label_episodes(df)[1]
    assert ep.kind == "both" and ep.tier == "clear" and ep.start == 900 and ep.end == 940


def test_gaps_up_to_half_an_hour_do_not_split_an_episode():
    df = station_frame()
    df.loc[1200:1220, "t2"] += 3.0
    df.loc[1227:1250, "t2"] += 3.0                                   # 6 samples back to normal between: merged
    assert len(ec.label_episodes(df)[2]) == 1
    df2 = station_frame()
    df2.loc[1200:1220, "t2"] += 3.0
    df2.loc[1240:1260, "t2"] += 3.0                                  # 19 samples apart: two episodes
    assert len(ec.label_episodes(df2)[2]) == 2


def test_label_mask_covers_every_sensor_with_a_day_either_side():
    df = station_frame(288 * 20)
    df.loc[2000:2020, "t2"] += 3.0
    m = ec.label_mask(df, ec.label_episodes(df))
    assert m[2000 - 288] and m[2020 + 288] and not m[2000 - 290] and not m[2020 + 290]


def test_stream_frame_gives_one_sensor_plus_humidity_and_no_pressure():
    df = station_frame(50)
    df.loc[3, "q2"] = 3.0
    f = ec.stream_frame(df, 2, "03047")
    assert f["station_id"].iloc[0] == "03047-S2" and f["pressure_hpa"].isna().all()
    assert f["temperature_c"].iloc[0] == round(df["t2"].iloc[0], 2) and f["noaa_flag"].iloc[3] == 1 and f["noaa_flag"].sum() == 1
    rs = ec.to_readings(f)
    assert rs[0].pressure_hpa is None and rs[0].temperature_c == f["temperature_c"].iloc[0]


def test_crn_settings_declare_the_barometer_absent_and_nothing_else_changes():
    from atmos.config import load_settings
    base = load_settings()
    s = ec.crn_settings(base)
    assert s["channels"]["absent"] == ["pressure_hpa"] and base["channels"]["absent"] == []


def test_the_crn_guard_needs_amendment_7(tmp_path):
    import subprocess
    import evaluate as ev
    from atmos.config import load_settings
    repo = tmp_path / "repo"
    (repo / "config").mkdir(parents=True)
    (repo / "config/protocol.md").write_text("# Protocol\nDone.\n")
    for cmd in (["init", "-q"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "p"]):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True)
    with pytest.raises(ev.HoldoutError, match="Amendment 7"):
        ev.guard_crn(load_settings(), repo, tmp_path / "data")
    (repo / "config/protocol.md").write_text("# Protocol\nDone.\n\n## Amendment 7\nCRN.\n")
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "a"], check=True)
    ev.guard_crn(load_settings(), repo, tmp_path / "data")
    assert (tmp_path / "data/crn/.crn_used").exists()


# ---- the compact-file reducer and the manifest ----------------------------------------------------------------
RAW = """"STATION","DATE","REPORT_TYPE","TMP","CH1","CT1","CT2","CT3","CF1","CF2","CF3"
"99999903072","2022-01-01T00:00:00","CRN05","+0174,1","05,+0175,1,0,0436,1,0","+0175,1,0","+0174,1,0","+0174,3,0","0807,1,0","0816,1,0","0798,1,0"
"99999903072","2022-01-01T00:05:00","CRN05","+0176,1","05,+0176,1,0,0434,1,0","+0176,1,0","+0176,1,0","+9999,9,0",,,
"99999903072","2022-01-01T00:05:00","SOD","+0176,1",,,,,,,
"""


def test_reduce_frame_keeps_the_five_minute_rows_and_reads_the_groups():
    raw = pd.read_csv(io.StringIO(RAW), dtype=str)
    out = crn.reduce_frame(raw)
    assert list(out.columns) == crn.OUT_COLUMNS and len(out) == 2
    r0, r1 = out.iloc[0], out.iloc[1]
    assert r0["t1"] == pytest.approx(17.5) and r0["t2"] == pytest.approx(17.4) and r0["q3"] == 3 and r0["rh"] == pytest.approx(43.6) and r0["f1"] == 807
    assert np.isnan(r1["t3"]) and r1["t_main"] == pytest.approx(17.6)                                   # +9999 is the missing code


def test_manifest_takes_the_dev_stations_and_a_seeded_sample_of_the_rest(tmp_path):
    def write(w, years=range(2016, 2025), frac=1.0):
        for y in years:
            n = int((366 if y % 4 == 0 else 365) * 288 * frac)
            pd.DataFrame({"timestamp": pd.date_range(f"{y}-01-01", periods=n, freq="5min"), "t1": 1.0, "t2": 1.0, "t3": 1.0, "rh": 50.0}).to_csv(
                tmp_path / f"999999{w}_{y}.csv.gz", index=False, compression="gzip")
    for w in (*crn.DEV_STATIONS[:2], "10001", "10002", "10003", "10004"):
        write(w)
    write("10005", frac=0.9)                                          # fails the 95 % gate
    write("10006", years=range(2018, 2025))                           # not all nine years
    m = crn.build_manifest(tmp_path, seed=1, n=2)
    assert m["stations_with_all_years"] == 7 and m["stations_passing_the_gate"] == 6
    assert len(m["sealed_stations"]) == 2 and set(m["sealed_stations"]) <= {"10001", "10002", "10003", "10004"}
    assert m["sealed_stations"] == crn.build_manifest(tmp_path, seed=1, n=2)["sealed_stations"]          # seeded: the same choice again
    assert all(len(h) == 64 for h in m["sha256"].values()) and len(m["sha256"]) == 9 * 4            # the two development stations present and the two sealed ones
