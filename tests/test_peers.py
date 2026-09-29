"""The optional peer layer (atmos/peers.py): neighbours find the offsets and drifts a single station cannot."""
import numpy as np
import pandas as pd
import pytest

from atmos import peers

IDX = pd.date_range("2020-01-01", periods=24 * 400, freq="h")


def field(seed=1):
    """A shared weather signal (slow, synoptic) that every station sees, plus small local noise."""
    rng = np.random.default_rng(seed)
    shared = pd.Series(np.convolve(rng.normal(0, 1, len(IDX) + 71), np.ones(72) / 72 * 12.0, mode="valid")[: len(IDX)], index=IDX)
    return shared, rng


def stations(n=5, seed=1):
    shared, rng = field(seed)
    return {f"S{i}": shared + pd.Series(rng.normal(0, 0.15, len(IDX)), index=IDX) for i in range(n)}


def test_haversine_and_neighbours_are_ordered_by_distance():
    assert peers.haversine_km(0, 0, 0, 1) == pytest.approx(111.2, abs=0.5)
    coords = {"A": (0.0, 0.0), "B": (0.0, 1.0), "C": (0.0, 3.0), "D": (0.0, 9.0)}
    assert peers.neighbours(coords, "A", 400.0) == ["B", "C"]


def test_peer_difference_is_small_when_all_stations_share_the_weather():
    anoms = stations()
    diff = peers.peer_difference(anoms, "S0", ["S1", "S2", "S3", "S4"])
    assert diff.abs().mean() < 0.3                                   # the shared signal cancels; local noise remains


def test_too_few_peers_gives_nothing():
    anoms = stations()
    diff = peers.peer_difference(anoms, "S0", ["S1", "S2"], min_peers=3)
    assert diff.isna().all()


def test_a_constant_offset_is_seen_with_peers_and_not_from_the_station_alone():
    anoms = stations()
    train = IDX < IDX[24 * 250]
    fault = pd.Series(0.0, index=IDX)
    fault.iloc[24 * 300: 24 * 340] = 1.0                            # 1 unit for 40 days, small next to the shared weather swings
    bad = dict(anoms)
    bad["S0"] = anoms["S0"] + fault
    peer_clean = peers.peer_difference(anoms, "S0", ["S1", "S2", "S3", "S4"])
    lim_peer = peers.fit_limit(peer_clean[train], 168, 0.995, 1.1, min_windows=100)
    peer_bad = peers.peer_difference(bad, "S0", ["S1", "S2", "S3", "S4"])
    assert peers.offset_alarm(peer_bad, lim_peer).iloc[24 * 300: 24 * 340].any()
    lim_own = peers.fit_limit(anoms["S0"][train], 168, 0.995, 1.1, min_windows=100)
    own_bad = peers.offset_alarm(bad["S0"], lim_own).iloc[24 * 300: 24 * 340]
    assert own_bad.mean() < 0.5                                     # the station's own weather swings are as big as the offset


def test_no_alarm_on_clean_series_after_the_training_years():
    anoms = stations(seed=3)
    d = peers.peer_difference(anoms, "S0", ["S1", "S2", "S3", "S4"])
    lim = peers.fit_limit(d[IDX < IDX[24 * 250]], 168, 0.999, 1.2, min_windows=100)
    assert peers.offset_alarm(d, lim).iloc[24 * 250:].mean() < 0.05


def test_thin_training_data_gives_no_limit():
    d = pd.Series(np.zeros(50), index=IDX[:50])
    assert peers.fit_limit(d, 168) is None


def test_the_study_runs_end_to_end_on_a_small_synthetic_cluster(monkeypatch):
    """evaluate_peers.evaluate / summarise / format_text on five synthetic stations (few trials), so the script cannot rot unnoticed."""
    import evaluate_peers as ep
    idx = pd.date_range("2016-01-01", "2024-12-31 23:00", freq="h")
    rng = np.random.default_rng(3)
    shared = pd.Series(np.convolve(rng.normal(0, 1, len(idx) + 71), np.ones(72) / 72 * 12.0, mode="valid")[: len(idx)], index=idx)
    anoms = {f"S{i}": {ch: shared + pd.Series(rng.normal(0, 0.2, len(idx)), index=idx) for ch in ("temperature_c", "pressure_hpa", "humidity_pct")}
             for i in range(5)}
    coords = {f"S{i}": (0.0, 0.1 * i) for i in range(5)}
    monkeypatch.setattr(ep, "TRIALS_PER_STATION", 2)
    res = ep.evaluate(coords, anoms, idx)
    summ = ep.summarise(res)
    assert res["stations"]["S0"]["n_peers"] == 4 and summ["detection"] and summ["false_alarms"]
    text = ep.format_text(res, summ)
    assert "pressure_hpa" in text and "with neighbours" in text.replace("peers = with neighbours", "with neighbours")
    big = [d for d in summ["detection"] if d["channel"] == "pressure_hpa" and d["kind"] == "offset" and d["size"] == 2.0]
    assert {d["mode"] for d in big} == {"peer", "own"}
